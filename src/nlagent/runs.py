"""The record of one question going through the agent. Shared by the baseline and the graph."""

from dataclasses import dataclass, field

from nlagent.db import QueryResult
from nlagent.steps import Usage


@dataclass
class AgentRun:
    question: str
    status: str = "failed"  # answered | clarification | refused | failed
    sql: str = ""
    result: QueryResult | None = None
    answer: str = ""
    error: str = ""
    retries: int = 0
    intent: str = ""
    retrieved_columns: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    trace: list[dict] = field(default_factory=list)  # one entry per node, in order
    total_latency_s: float = 0.0
