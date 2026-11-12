"""Send one Langfuse trace per question, with a span or generation for every graph node.

Traces are built after the run from the node records and sent to Langfuse's OpenTelemetry
endpoint as OTLP over HTTP/JSON. (Langfuse 4 rejects the older /api/public/ingestion endpoint,
so that route is not used.) Tracing never raises: a down Langfuse host must not break an answer.
"""

import base64
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

import httpx

from nlagent.llm import estimate_cost
from nlagent.runs import AgentRun

logger = logging.getLogger(__name__)

OTLP_PATH = "/api/public/otel/v1/traces"
SPAN_KIND_INTERNAL = 1
STATUS_ERROR = 2


def langfuse_configured() -> bool:
    return all(os.getenv(name) for name in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))


def _nanos(moment: datetime) -> str:
    """OTLP wants nanoseconds since the epoch, as a string so JSON does not lose precision."""
    return str(int(moment.timestamp()) * 10**9 + moment.microsecond * 1000)


def _attribute(key: str, value) -> dict:
    if isinstance(value, bool):
        typed = {"boolValue": value}
    elif isinstance(value, int):
        typed = {"intValue": str(value)}
    elif isinstance(value, float):
        typed = {"doubleValue": value}
    else:
        typed = {"stringValue": value if isinstance(value, str) else json.dumps(value, default=str)}
    return {"key": key, "value": typed}


def _span(trace_id: str, parent_id: str | None, name: str, start: datetime, end: datetime,
          attributes: dict, error: str = "") -> dict:
    span = {
        "traceId": trace_id,
        "spanId": secrets.token_hex(8),
        "name": name,
        "kind": SPAN_KIND_INTERNAL,
        "startTimeUnixNano": _nanos(start),
        "endTimeUnixNano": _nanos(end),
        "attributes": [_attribute(k, v) for k, v in attributes.items()],
    }
    if parent_id:
        span["parentSpanId"] = parent_id
    if error:
        span["status"] = {"code": STATUS_ERROR, "message": error}
    return span


def build_otlp_payload(run: AgentRun, user_id: str, model: str, started_at: datetime) -> dict:
    """Translate an AgentRun into an OTLP trace: a root span for the question, a child per node."""
    trace_id = secrets.token_hex(16)
    total_cost = estimate_cost(model, run.usage.input_tokens, run.usage.output_tokens)
    ended_at = started_at + timedelta(seconds=run.total_latency_s)

    root = _span(trace_id, None, "f1-agent-question", started_at, ended_at, {
        "langfuse.observation.type": "span",
        "langfuse.trace.name": "f1-agent-question",
        "user.id": user_id,
        "langfuse.trace.input": run.question,
        "langfuse.trace.output": run.answer,
        "langfuse.observation.input": run.question,
        "langfuse.observation.output": run.answer,
        "langfuse.trace.metadata.status": run.status,
        "langfuse.trace.metadata.retries": run.retries,
        "langfuse.trace.metadata.sql": run.sql,
        "langfuse.trace.metadata.total_cost_usd": total_cost,
    })
    spans = [root]

    cursor = started_at
    for node in run.trace:
        node_end = cursor + timedelta(seconds=node["latency_s"])
        attributes = {f"langfuse.observation.metadata.{k}": v for k, v in node.items()
                      if k not in ("node", "latency_s")}
        error = node.get("error", "")
        if error:
            attributes["langfuse.observation.level"] = "ERROR"
            attributes["langfuse.observation.status_message"] = error

        if "tokens_in" in node:  # an LLM call: a generation, so tokens and cost show up in Langfuse
            tokens_in, tokens_out = node["tokens_in"], node["tokens_out"]
            attributes.update({
                "langfuse.observation.type": "generation",
                "gen_ai.request.model": model,
                "langfuse.observation.model.name": model,
                "langfuse.observation.usage_details": json.dumps({"input": tokens_in, "output": tokens_out}),
                "langfuse.observation.cost_details": json.dumps(
                    {"total": estimate_cost(model, tokens_in, tokens_out)}),
            })
        else:
            attributes["langfuse.observation.type"] = "span"
        spans.append(_span(trace_id, root["spanId"], node["node"], cursor, node_end, attributes, error))
        cursor = node_end

    return {"resourceSpans": [{
        "resource": {"attributes": [_attribute("service.name", "f1-agent")]},
        "scopeSpans": [{"scope": {"name": "nlagent"}, "spans": spans}],
    }]}


def emit_trace(run: AgentRun, user_id: str, model: str, client: httpx.Client | None = None) -> None:
    if not langfuse_configured():
        return
    started_at = datetime.now(UTC) - timedelta(seconds=run.total_latency_s)
    payload = build_otlp_payload(run, user_id, model, started_at)
    credentials = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
    headers = {
        "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
        "x-langfuse-ingestion-version": "4",  # ask for real-time ingestion on Langfuse 4
    }
    url = os.environ["LANGFUSE_HOST"].rstrip("/") + OTLP_PATH
    try:
        if client is not None:
            _post(client, url, payload, headers)
        else:
            with httpx.Client(timeout=5.0) as http:
                _post(http, url, payload, headers)
    except httpx.HTTPError as error:
        logger.warning("Langfuse trace was not sent: %s", error)


def _post(http: httpx.Client, url: str, payload: dict, headers: dict[str, str]) -> None:
    response = http.post(url, json=payload, headers=headers)
    response.raise_for_status()
