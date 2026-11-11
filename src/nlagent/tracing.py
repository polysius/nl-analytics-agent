"""Send one Langfuse trace per question, with a span or generation for every graph node.

Traces are built after the run from the node records, and sent over Langfuse's REST
ingestion API. Tracing never raises: a down Langfuse host must not break an answer.
"""

import base64
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from nlagent.llm import estimate_cost
from nlagent.runs import AgentRun

logger = logging.getLogger(__name__)


def langfuse_configured() -> bool:
    return all(os.getenv(name) for name in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_events(run: AgentRun, user_id: str, model: str, started_at: datetime) -> list[dict]:
    """Translate an AgentRun into Langfuse ingestion events (one trace, one event per node)."""
    trace_id = str(uuid.uuid4())

    def event(kind: str, body: dict, at: datetime) -> dict:
        return {"id": str(uuid.uuid4()), "type": kind, "timestamp": _iso(at), "body": body}

    events = [event("trace-create", {
        "id": trace_id,
        "name": "f1-agent-question",
        "userId": user_id,
        "input": run.question,
        "output": run.answer,
        "metadata": {
            "status": run.status, "retries": run.retries, "sql": run.sql,
            "total_cost_usd": estimate_cost(model, run.usage.input_tokens, run.usage.output_tokens),
        },
    }, started_at)]

    cursor = started_at
    for node in run.trace:
        node_end = cursor + timedelta(seconds=node["latency_s"])
        body = {
            "id": str(uuid.uuid4()),
            "traceId": trace_id,
            "name": node["node"],
            "startTime": _iso(cursor),
            "endTime": _iso(node_end),
            "metadata": {k: v for k, v in node.items() if k not in ("node", "latency_s")},
        }
        if node.get("error"):
            body.update(level="ERROR", statusMessage=node["error"])

        if "tokens_in" in node:  # an LLM call: record it as a generation so tokens and cost show up
            tokens_in, tokens_out = node["tokens_in"], node["tokens_out"]
            body.update(
                model=model,
                usage={"input": tokens_in, "output": tokens_out, "unit": "TOKENS"},
                costDetails={"total": estimate_cost(model, tokens_in, tokens_out)},
            )
            events.append(event("generation-create", body, node_end))
        else:
            events.append(event("span-create", body, node_end))
        cursor = node_end

    return events


def emit_trace(run: AgentRun, user_id: str, model: str, client: httpx.Client | None = None) -> None:
    if not langfuse_configured():
        return
    started_at = datetime.now(UTC) - timedelta(seconds=run.total_latency_s)
    events = build_events(run, user_id, model, started_at)
    credentials = f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}"
    headers = {"Authorization": "Basic " + base64.b64encode(credentials.encode()).decode()}
    try:
        http = client or httpx.Client(timeout=5.0)
        response = http.post(
            os.environ["LANGFUSE_HOST"].rstrip("/") + "/api/public/ingestion",
            json={"batch": events}, headers=headers,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.warning("Langfuse trace was not sent: %s", error)
