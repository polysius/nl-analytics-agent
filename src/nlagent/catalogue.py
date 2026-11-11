"""The column catalogue: one searchable document per column of the F1 database.

Documents are stored in the catalog.columns table with a pgvector embedding, so schema
retrieval needs no second datastore.
"""

from dataclasses import dataclass

import psycopg
from pgvector.psycopg import register_vector

from nlagent.config import settings

EMBEDDING_DIMENSIONS = 384  # output size of BAAI/bge-small-en-v1.5

# Hand-written notes for places where the column names alone mislead a model.
TABLE_NOTES = {
    "race_data": (
        "One wide table for every kind of per-driver-per-race result. The `type` column says "
        "which kind: RACE_RESULT, QUALIFYING_RESULT, STARTING_GRID_POSITION, PIT_STOP, "
        "FASTEST_LAP, SPRINT_RACE_RESULT and others. Columns are prefixed by kind and only "
        "filled for the matching type. Prefer the per-type views (race_result, "
        "qualifying_result, pit_stop, fastest_lap, starting_grid_position) which already filter `type`."
    ),
    "race_result": "View of race_data for race finishes, one row per driver per race: position_number (final position, 1 = win), points, pole_position (bool), grid_position_number, laps, fastest_lap (bool), reason_retired, time_millis.",
    "qualifying_result": "View of race_data for qualifying: position_number, time_millis, q1, q2, q3.",
    "pit_stop": "View of race_data for pit stops: stop (stop number), lap, time_millis.",
    "fastest_lap": "View of race_data for each driver's fastest lap in a race: lap, time_millis.",
    "starting_grid_position": "View of race_data for the starting grid: position_number, grid_penalty_positions.",
    "driver": "Drivers. `id` is a slug such as 'max-verstappen'. Career totals are stored here.",
    "constructor": "Teams. `id` is a slug such as 'ferrari'. Career totals are stored here.",
    "race": "One row per Grand Prix. `year` and `round` identify the season and order.",
    "season_driver_standing": "Final drivers' championship table per year. `championship_won` marks the champion.",
    "season_constructor_standing": "Final constructors' championship table per year.",
}


@dataclass(frozen=True)
class ColumnDoc:
    table: str
    column: str
    data_type: str
    text: str  # what gets embedded and BM25-indexed

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}"


def describe_column(table: str, column: str, data_type: str) -> str:
    """Plain-language text for retrieval: names split into words plus the table's role."""
    words = column.replace("_", " ")
    table_words = table.replace("_", " ")
    note = TABLE_NOTES.get(table, "")
    return f"{table_words}: {words} ({data_type}). {note}".strip()


def fetch_columns(conn: psycopg.Connection) -> list[ColumnDoc]:
    rows = conn.execute(
        "select table_name, column_name, data_type from information_schema.columns "
        "where table_schema = 'public' order by table_name, ordinal_position"
    ).fetchall()
    return [ColumnDoc(t, c, d, describe_column(t, c, d)) for t, c, d in rows]


def fetch_foreign_keys(conn: psycopg.Connection) -> list[tuple[str, str, str, str]]:
    """(table, column, referenced table, referenced column) for every foreign key."""
    return conn.execute(
        """
        select kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name
        from information_schema.table_constraints tc
        join information_schema.key_column_usage kcu
          on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
        join information_schema.constraint_column_usage ccu
          on tc.constraint_name = ccu.constraint_name and tc.table_schema = ccu.table_schema
        where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = 'public'
        order by 1, 2
        """
    ).fetchall()


def build_catalogue(embed) -> int:
    """(Re)create catalog.columns and fill it. `embed` maps a list of texts to vectors."""
    with psycopg.connect(settings.admin_database_url, autocommit=True) as conn:
        conn.execute("create extension if not exists vector")
        register_vector(conn)
        docs = fetch_columns(conn)
        vectors = embed([doc.text for doc in docs])
        conn.execute("create schema if not exists catalog")
        conn.execute("drop table if exists catalog.columns")
        conn.execute(
            f"""create table catalog.columns (
                id serial primary key,
                table_name text not null,
                column_name text not null,
                data_type text not null,
                doc text not null,
                embedding vector({EMBEDDING_DIMENSIONS}) not null)"""
        )
        with conn.cursor() as cur:
            cur.executemany(
                "insert into catalog.columns (table_name, column_name, data_type, doc, embedding) "
                "values (%s, %s, %s, %s, %s)",
                [(d.table, d.column, d.data_type, d.text, v) for d, v in zip(docs, vectors, strict=True)],
            )
        conn.execute(
            "create index on catalog.columns using hnsw (embedding vector_cosine_ops)"
        )
        conn.execute("grant select on all tables in schema catalog to agent_ro")
    return len(docs)


def load_catalogue() -> list[ColumnDoc]:
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "select table_name, column_name, data_type, doc from catalog.columns order by id"
        ).fetchall()
    return [ColumnDoc(t, c, d, text) for t, c, d, text in rows]
