import itertools
import json
from datetime import UTC, datetime

import httpx

from nlagent.runs import AgentRun
from nlagent.steps import Usage
from nlagent.tracing import build_otlp_payload, emit_trace

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
START = datetime(2026, 1, 1, tzinfo=UTC)


def spans_of(payload):
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"]


def attributes_of(span):
    """Flatten OTLP attributes ({key, value: {stringValue: ...}}) into a plain dict."""
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_payload_has_one_root_span_and_a_child_per_node():
    spans = spans_of(build_otlp_payload(RUN, "alice", "claude-sonnet-5-5", START))

    assert [s["name"] for s in spans] == ["f1-agent-question", "retrieve", "generate", "execute", "repair"]
    root = spans[0]
    assert "parentSpanId" not in root
    assert all(s["traceId"] == root["traceId"] and s["parentSpanId"] == root["spanId"] for s in spans[1:])
    assert len(root["traceId"]) == 32 and len(root["spanId"]) == 16


def test_root_span_carries_the_question_answer_and_user():
    root = spans_of(build_otlp_payload(RUN, "alice", "claude-sonnet-5-5", START))[0]
    attrs = attributes_of(root)

    assert attrs["user.id"] == "alice"
    assert attrs["langfuse.trace.input"] == "How many races in 2021?"
    assert attrs["langfuse.trace.output"] == "22 races."
    assert attrs["langfuse.trace.metadata.status"] == "answered"


def test_llm_nodes_are_generations_with_tokens_and_cost():
    spans = spans_of(build_otlp_payload(RUN, "alice", "claude-sonnet-5-5", START))
    generate = attributes_of(spans[2])

    assert generate["langfuse.observation.type"] == "generation"
    assert json.loads(generate["langfuse.observation.usage_details"]) == {"input": 200, "output": 30}
    assert json.loads(generate["langfuse.observation.cost_details"])["total"] > 0
    assert generate["gen_ai.request.model"] == "claude-sonnet-5-5"
    assert attributes_of(spans[1])["langfuse.observation.type"] == "span"


def test_tool_errors_are_flagged_on_the_span():
    execute = spans_of(build_otlp_payload(RUN, "alice", "claude-sonnet-5-5", START))[3]
    attrs = attributes_of(execute)

    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "column yr does not exist"
    assert execute["status"] == {"code": 2, "message": "column yr does not exist"}


def test_node_times_follow_each_other_without_gaps():
    nodes = spans_of(build_otlp_payload(RUN, "alice", "claude-sonnet-5-5", START))[1:]
    for earlier, later in itertools.pairwise(nodes):
        assert earlier["endTimeUnixNano"] == later["startTimeUnixNano"]


def test_emit_posts_otlp_json_with_basic_auth(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    emit_trace(RUN, "alice", "claude-sonnet-5-5", client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert seen["url"] == "http://langfuse.test/api/public/otel/v1/traces"
    assert seen["auth"].startswith("Basic ")
    assert len(spans_of(seen["body"])) == 5


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
