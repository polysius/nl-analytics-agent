"""Create the taxi database from the CSV snapshot in data/taxi, then the read-only role grants.

    AGENT_DOMAIN=taxi python scripts/load_taxi.py
    AGENT_DOMAIN=taxi python scripts/build_catalogue.py

The CSV files come from lakehouse-pipeline (`scripts/export_gold.py`) and are committed, so this
needs no Databricks access. Safe to rerun: the schema file drops and recreates every table.
"""

from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from nlagent.config import settings

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "dim_zone", "dim_date", "dim_payment_type", "dim_rate_code", "dim_vendor",
    "metric_daily_trips", "metric_borough_revenue", "metric_tip_rate",
    "metric_hourly_demand", "metric_top_zones",
)  # dimensions first, because the metric tables reference dim_date


def create_database_if_missing() -> None:
    """Connect to the maintenance database, since the taxi database may not exist yet."""
    name = conninfo_to_dict(settings.admin_database_url)["dbname"]
    maintenance = make_conninfo(settings.admin_database_url, dbname="postgres")
    with psycopg.connect(maintenance, autocommit=True) as conn:
        exists = conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))


def load_tables() -> None:
    with psycopg.connect(settings.admin_database_url) as conn:
        conn.execute((ROOT / "scripts" / "taxi_schema.sql").read_text(encoding="utf-8"))
        for table in TABLES:
            csv_path = ROOT / "data" / "taxi" / f"{table}.csv"
            with conn.cursor() as cur, cur.copy(
                sql.SQL("copy {} from stdin with (format csv, header true)").format(sql.Identifier(table))
            ) as copy:
                copy.write(csv_path.read_bytes())
            print(f"{table}: {conn.execute(sql.SQL('select count(*) from {}').format(sql.Identifier(table))).fetchone()[0]} rows")
        conn.execute((ROOT / "scripts" / "setup_roles.sql").read_text(encoding="utf-8"))


if __name__ == "__main__":
    create_database_if_missing()
    load_tables()
