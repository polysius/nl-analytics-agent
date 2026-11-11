"""Read-only query execution with a row cap and a timeout."""

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import psycopg

from nlagent.config import settings
from nlagent.guard import GuardResult, UnsafeSQLError, validate_select


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True when the row cap cut the result short


class QueryError(RuntimeError):
    """The database rejected or failed the query. The message is safe to show to an LLM."""


@lru_cache(maxsize=1)
def allowed_tables() -> frozenset[str]:
    """Real tables in the public schema. Everything else is off limits to the agent."""
    with psycopg.connect(settings.admin_database_url) as conn:
        rows = conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public' and table_type = 'BASE TABLE'"
        ).fetchall()
    return frozenset(row[0] for row in rows)


def check_sql(sql: str) -> GuardResult:
    return validate_select(sql, set(allowed_tables()))


def run_query(sql: str, row_cap: int | None = None) -> QueryResult:
    """Validate then run a query as the read-only role.

    Raises UnsafeSQLError for blocked SQL and QueryError for database failures.
    """
    cap = row_cap or settings.row_cap
    guarded = check_sql(sql)
    # The options make the session itself read-only and bounded, even if layer 1 is bypassed.
    options = (
        f"-c default_transaction_read_only=on -c statement_timeout={settings.statement_timeout_ms}"
    )
    try:
        with psycopg.connect(settings.database_url, options=options) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(guarded.sql)
                columns = [d.name for d in cur.description or []]
                fetched = cur.fetchmany(cap + 1)
    except psycopg.Error as error:
        raise QueryError(str(error).strip().splitlines()[0]) from error
    return QueryResult(columns, [tuple(r) for r in fetched[:cap]], truncated=len(fetched) > cap)


def normalise_value(value):
    """Make values comparable across runs: decimals and floats rounded, others unchanged."""
    if isinstance(value, (Decimal, float)):
        return round(float(value), 4)
    return value


__all__ = ["QueryResult", "QueryError", "UnsafeSQLError", "run_query", "check_sql", "allowed_tables"]
