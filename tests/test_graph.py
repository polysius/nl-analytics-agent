"""Graph routing tests with a scripted LLM. Needs Postgres for execution, not an API key."""

import json

import pytest

from nlagent import graph as graph_module
from nlagent.graph import GraphConfig, build_graph, run_graph
from nlagent.llm import StubLLM

pytestmark = pytest.mark.db

DATA_QUESTION = json.dumps({"intent": "data_question", "clarification": ""})
GOOD_SQL = "select count(*) from race where year = 2021"
BAD_SQL = "select count(*) from race where yr = 2021"


@pytest.fixture(autouse=True)
def no_retrieval(monkeypatch):
    """Skip the embedding model: retrieval has its own tests."""
    monkeypatch.setattr(graph_module, "retrieve_columns", lambda question, mode: [])
    monkeypatch.setattr(graph_module, "render_schema", lambda columns: "TABLE race\n  year integer")


def nodes_visited(run):
    return [entry["node"] for entry in run.trace]


def test_happy_path_answers_from_the_query_result():
    llm = StubLLM([DATA_QUESTION, GOOD_SQL, "There were 22 races in 2021."])
    run = run_graph(build_graph(llm), "How many races were held in 2021?")

    assert run.status == "answered"
    assert run.result.rows == [(22,)]
    assert run.answer == "There were 22 races in 2021."
    assert nodes_visited(run) == ["classify", "retrieve", "generate", "execute", "synthesise"]
    assert run.usage.llm_calls == 3


def test_sql_error_is_repaired_then_answered():
    llm = StubLLM([DATA_QUESTION, BAD_SQL, GOOD_SQL, "22 races."])
    run = run_graph(build_graph(llm), "How many races were held in 2021?")

    assert run.status == "answered"
    assert run.retries == 1
    assert nodes_visited(run) == [
        "classify", "retrieve", "generate", "execute", "repair", "execute", "synthesise",
    ]


def test_gives_up_after_the_retry_limit():
    llm = StubLLM([DATA_QUESTION, BAD_SQL])  # the stub repeats the bad SQL forever
    run = run_graph(build_graph(llm, GraphConfig(max_retries=2)), "How many races in 2021?")

    assert run.status == "failed"
    assert run.retries == 2
    assert nodes_visited(run).count("execute") == 3


def test_blocked_sql_goes_through_repair_not_the_database():
    llm = StubLLM([DATA_QUESTION, "drop table driver", GOOD_SQL, "22 races."])
    run = run_graph(build_graph(llm), "Drop the driver table")

    assert run.retries == 1
    assert "not allowed" in run.trace[3]["error"] or "Only SELECT" in run.trace[3]["error"]


def test_ambiguous_question_asks_for_clarification_and_skips_the_database():
    llm = StubLLM([json.dumps({"intent": "ambiguous", "clarification": "Best by which measure?"})])
    run = run_graph(build_graph(llm), "Who is the best driver?")

    assert run.status == "clarification"
    assert run.answer == "Best by which measure?"
    assert nodes_visited(run) == ["classify", "clarify"]


def test_out_of_scope_question_is_refused():
    llm = StubLLM([json.dumps({"intent": "out_of_scope", "clarification": ""})])
    run = run_graph(build_graph(llm), "What is the weather in Paris?")

    assert run.status == "refused"
    assert nodes_visited(run) == ["classify", "refuse"]


def test_unparseable_classification_defaults_to_answering():
    llm = StubLLM(["not json at all", GOOD_SQL, "22 races."])
    run = run_graph(build_graph(llm), "How many races were held in 2021?")

    assert run.intent == "data_question"
    assert run.status == "answered"
