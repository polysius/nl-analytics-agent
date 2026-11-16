"""Domain text and, when the taxi database is selected, its safety layers.

The first tests need no database. The rest run with AGENT_DOMAIN=taxi:
    AGENT_DOMAIN=taxi pytest tests/test_domains.py
The F1 suites run with the default domain and are skipped under taxi.
"""

import json

import psycopg
import pytest

from nlagent.agent import Agent
from nlagent.config import settings
from nlagent.db import UnsafeSQLError, allowed_tables, run_query
from nlagent.domains import DOMAINS, F1, TAXI
from nlagent.llm import StubLLM

on_taxi = pytest.mark.skipif(settings.domain != "taxi", reason="needs AGENT_DOMAIN=taxi")
DATA_QUESTION = json.dumps({"intent": "data_question", "clarification": ""})


def test_domain_names_match_database_names():
    assert set(DOMAINS) == {"f1", "taxi"}
    assert all(name == domain.name for name, domain in DOMAINS.items())


def test_taxi_prompts_do_not_mention_formula_one():
    for text in (TAXI.sql_system, TAXI.few_shot, TAXI.classify_system, TAXI.refuse_message):
        assert "formula" not in text.lower()
        assert "race" not in text.lower()


def test_f1_prompts_do_not_mention_taxis():
    for text in (F1.sql_system, F1.few_shot, F1.classify_system, F1.refuse_message):
        assert "taxi" not in text.lower()


def test_every_taxi_table_note_names_a_loaded_table():
    assert set(TAXI.table_notes) == {
        "metric_daily_trips", "metric_borough_revenue", "metric_tip_rate",
        "metric_hourly_demand", "metric_top_zones", "dim_zone", "dim_date",
        "dim_payment_type", "dim_rate_code", "dim_vendor",
    }


@pytest.mark.db
@on_taxi
def test_taxi_database_exposes_only_the_gold_tables():
    assert allowed_tables() == frozenset(TAXI.table_notes)


@pytest.mark.db
@on_taxi
def test_taxi_query_runs_and_matches_the_lakehouse_total():
    result = run_query("select sum(trips) from metric_daily_trips")
    assert result.rows == [(39687869,)]


@pytest.mark.db
@on_taxi
def test_f1_table_is_rejected_on_the_taxi_database():
    with pytest.raises(UnsafeSQLError):
        run_query("select * from race")


@pytest.mark.db
@on_taxi
def test_read_only_role_cannot_write_to_the_taxi_database():
    # The guard is bypassed on purpose: layer 2 must stop the write on its own.
    with psycopg.connect(settings.database_url) as conn, pytest.raises(psycopg.Error):
        conn.execute("delete from dim_zone")


@pytest.mark.db
@on_taxi
@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE dim_zone", "DELETE FROM metric_daily_trips", "SELECT * FROM catalog.columns",
     "SELECT * FROM pg_shadow", "SELECT 1; DROP TABLE dim_zone"],
)
def test_compromised_llm_cannot_change_the_taxi_database(sql, monkeypatch):
    from nlagent import graph as graph_module

    monkeypatch.setattr(graph_module, "retrieve_columns", lambda question, mode: [])
    monkeypatch.setattr(graph_module, "render_schema", lambda columns: "TABLE dim_zone")
    with psycopg.connect(settings.admin_database_url) as conn:
        before = conn.execute("select count(*) from dim_zone").fetchone()[0]

    run = Agent(StubLLM([DATA_QUESTION, sql, sql, sql])).ask("Show me the zones")

    assert run.status == "failed"
    with psycopg.connect(settings.admin_database_url) as conn:
        assert conn.execute("select count(*) from dim_zone").fetchone()[0] == before
