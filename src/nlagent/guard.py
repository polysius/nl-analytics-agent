"""Static SQL safety check, the first of three layers that keep the database read-only.

Layer 1 (this file): parse the SQL and reject anything that is not one SELECT over
the allowed tables. Layer 2: the database role only has SELECT. Layer 3: the session
is read-only and has a statement timeout. A bug in one layer does not open the database.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

# sqlglot gives common SQL functions (count, sum, round, coalesce, ...) their own node type.
# Any function it cannot name is "anonymous" and is rejected unless listed here. An allowlist
# is used because a denylist missed XML helpers that run arbitrary SQL or read system tables.
ALLOWED_ANONYMOUS_FUNCTIONS = {"percentile_cont", "percentile_disc", "mode"}

# Functions that read files, sleep, change settings or reach other servers. Kept as a second
# check in case sqlglot ever gives one of these its own node type.
FORBIDDEN_FUNCTIONS = {
    "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "set_config", "dblink", "dblink_exec", "lo_import", "lo_export", "pg_terminate_backend",
    "pg_cancel_backend", "current_setting", "query_to_xml", "pg_advisory_lock",
    "version", "currentversion", "inet_server_addr", "pg_get_userbyid",
    "table_to_xml", "schema_to_xml", "database_to_xml", "query_to_xml_and_xmlschema",
}


class UnsafeSQLError(ValueError):
    """Raised when a query is not allowed to reach the database."""


@dataclass(frozen=True)
class GuardResult:
    sql: str
    tables: frozenset[str]


def validate_select(sql: str, allowed_tables: set[str]) -> GuardResult:
    """Return the cleaned SQL if it is a single read-only SELECT over allowed tables."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError as error:
        raise UnsafeSQLError(f"SQL could not be parsed: {error}") from error

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise UnsafeSQLError("Exactly one SQL statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        raise UnsafeSQLError(f"Only SELECT queries are allowed, got {type(tree).__name__}.")

    _reject_write_nodes(tree)
    _reject_forbidden_functions(tree)
    _reject_system_cte_names(tree)
    tables = _check_tables(tree, allowed_tables)
    return GuardResult(sql=tree.sql(dialect="postgres"), tables=frozenset(tables))


def _reject_write_nodes(tree: exp.Expression) -> None:
    write_nodes = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
        exp.Command, exp.Merge, exp.Set, exp.Copy, exp.Into, exp.TruncateTable, exp.Grant,
        exp.Lock,  # SELECT ... FOR UPDATE
    )
    for node in tree.walk():
        if isinstance(node, write_nodes):
            raise UnsafeSQLError(f"{type(node).__name__} is not allowed inside a query.")


def _reject_forbidden_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = (func.name or type(func).__name__).lower()
        if name in FORBIDDEN_FUNCTIONS:
            raise UnsafeSQLError(f"Function {name} is not allowed.")
    for anonymous in tree.find_all(exp.Anonymous):
        name = str(anonymous.this).lower()
        if name in FORBIDDEN_FUNCTIONS or name not in ALLOWED_ANONYMOUS_FUNCTIONS:
            raise UnsafeSQLError(f"Function {name} is not allowed.")


def _reject_system_cte_names(tree: exp.Expression) -> None:
    """A WITH alias such as "PG_ROLES" (quoted, so case-sensitive) can hide the real pg_ table."""
    for cte in tree.find_all(exp.CTE):
        if cte.alias_or_name.lower().startswith("pg_"):
            raise UnsafeSQLError(f"WITH alias {cte.alias_or_name} is not allowed.")


def _is_local_cte(table: exp.Table, name: str) -> bool:
    """True when `name` resolves to a WITH alias visible at this reference.

    A non-recursive CTE sees only the CTEs defined before it; the query body sees all of
    them. Any other reference resolves to the real table in Postgres.
    """
    child: exp.Expression = table
    node = table.parent
    while node is not None:
        if isinstance(node, exp.With):
            ctes = node.expressions
            visible = ctes if node.args.get("recursive") else ctes[: ctes.index(child)]
        else:
            with_clause = node.args.get("with") or node.args.get("with_")
            visible = with_clause.expressions if with_clause and child is not with_clause else []
        if any(cte.alias_or_name.lower() == name for cte in visible):
            return True
        child, node = node, node.parent
    return False


def _check_tables(tree: exp.Expression, allowed_tables: set[str]) -> set[str]:
    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not table.args.get("db") and _is_local_cte(table, name):
            continue
        schema = table.args["db"].name.lower() if table.args.get("db") else "public"
        if schema != "public" or name not in allowed_tables:
            raise UnsafeSQLError(f"Table {schema}.{name} is not in the allowed set.")
        used.add(name)
    return used
