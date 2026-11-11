import json
from datetime import UTC, datetime

import httpx

from nlagent.runs import AgentRun
from nlagent.steps import Usage
from nlagent.tracing import build_events, emit_trace

RUN = AgentRun(
    question="How many races in 2021?",
    status="answered",
    sql="select count(*) from race where year = 2021",
    answer="22 races.",
    retries=1,
    usage=Usage(input_tokens=300, output_tokens=40),
    total_latency_s=2.0,
    trace=[
        {"node": "retrieve", "latency_s": 0.2, "mode": "hybrid_rerank", "columns": 25},
        {"node": "generate", "latency_s": 0.8, "tokens_in": 200, "tokens_out": 30},
        {"node": "execute", "latency_s": 0.1, "error": "column yr does not exist"},
        {"node": "repair", "latency_s": 0.9, "tokens_in": 100, "tokens_out": 10},
    ],
)


def test_events_hold_one_trace_with_a_child_per_node():
    events = build_events(RUN, "alice", "claude-sonnet-5-5", datetime(2026, 1, 1, tzinfo=UTC))

    assert [e["type"] for e in events] == [
        "trace-create", "span-create", "generation-create", "span-create", "generation-create",
    ]
    trace_id = events[0]["body"]["id"]
    assert all(e["body"]["traceId"] == trace_id for e in events[1:])


def test_llm_nodes_carry_tokens_and_cost_and_tool_errors_are_flagged():
    events = build_events(RUN, "alice", "claude-sonnet-5-5", datetime(2026, 1, 1, tzinfo=UTC))
    generation = events[2]["body"]
    failed_execute = events[3]["body"]

    assert generation["usage"] == {"input": 200, "output": 30, "unit": "TOKENS"}
    assert generation["costDetails"]["total"] > 0
    assert failed_execute["level"] == "ERROR"
    assert failed_execute["statusMessage"] == "column yr does not exist"


def test_node_times_follow_each_other_without_gaps():
    events = build_events(RUN, "alice", "claude-sonnet-5-5", datetime(2026, 1, 1, tzinfo=UTC))
    nodes = [e["body"] for e in events[1:]]
    for earlier, later in zip(nodes, nodes[1:], strict=False):
        assert earlier["endTime"] == later["startTime"]


def test_emit_posts_a_batch_with_basic_auth(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["batch"] = json.loads(request.content)["batch"]
        return httpx.Response(207, json={"successes": [], "errors": []})

    emit_trace(RUN, "alice", "claude-sonnet-5-5", client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert seen["url"] == "http://langfuse.test/api/public/ingestion"
    assert seen["auth"].startswith("Basic ")
    assert len(seen["batch"]) == 5


def test_emit_never_raises_when_langfuse_is_down(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def handler(request):
        raise httpx.ConnectError("down")

    emit_trace(RUN, "alice", "claude-sonnet-5-5", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_emit_does_nothing_when_langfuse_is_not_configured(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    emit_trace(RUN, "alice", "claude-sonnet-5-5")  # no client given: would fail if it tried to send
