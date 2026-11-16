"""Domain text and, when the taxi database is selected, its safety layers.

The first tests need no database. The rest run with AGENT_DOMAIN=taxi:
    AGENT_DOMAIN=taxi pytest tests/test_domains.py
The F1 suites run with the default domain and are skipped under taxi.
"""

import json
import re
from pathlib import Path

import psycopg
import pytest

from nlagent import steps
from nlagent.agent import Agent
from nlagent.config import settings
from nlagent.db import UnsafeSQLError, allowed_tables, run_query
from nlagent.domains import DOMAINS, TAXI, active_domain
from nlagent.llm import StubLLM

on_taxi = pytest.mark.skipif(settings.domain != "taxi", reason="needs AGENT_DOMAIN=taxi")
DATA_QUESTION = json.dumps({"intent": "data_question", "clarification": ""})


def test_domain_names_match_database_names():
    assert set(DOMAINS) == {"f1", "taxi"}
    assert all(name == domain.name for name, domain in DOMAINS.items())


def test_prompts_sent_to_the_model_come_from_the_active_domain():
    llm = StubLLM(["select 1"])
    steps.generate_sql(llm, "How many?", "TABLE t", few_shot=True)
    system, user = llm.calls[0]

    assert system == active_domain().sql_system
    assert active_domain().few_shot in user


def test_every_taxi_table_note_names_a_table_in_the_schema_file():
    schema = (Path(__file__).resolve().parents[1] / "scripts" / "taxi_schema.sql").read_text()
    created = set(re.findall(r"create table (\w+)", schema))
    assert set(TAXI.table_notes) == created


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
