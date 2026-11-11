"""The four ablation configurations that form the baseline for the LangGraph agent.

Each configuration adds one thing to the previous one, so the accuracy gap between
neighbours shows what that thing is worth.
"""

import time
from dataclasses import dataclass

from nlagent import steps
from nlagent.config import settings
from nlagent.db import QueryError, UnsafeSQLError, run_query
from nlagent.llm import LLMClient
from nlagent.retrieval import RetrievalMode, render_full_schema, render_schema, retrieve_columns
from nlagent.runs import AgentRun


@dataclass(frozen=True)
class BaselineConfig:
    name: str
    retrieval: RetrievalMode | None  # None means the prompt carries the full schema
    few_shot: bool
    repair: bool


BASELINE_CONFIGS = {
    c.name: c
    for c in [
        BaselineConfig("full_schema", None, few_shot=False, repair=False),
        BaselineConfig("retrieved", "vector", few_shot=False, repair=False),
        BaselineConfig("retrieved_fewshot", "vector", few_shot=True, repair=False),
        BaselineConfig("retrieved_fewshot_repair", "vector", few_shot=True, repair=True),
    ]
}


def run_baseline(llm: LLMClient, question: str, config: BaselineConfig) -> AgentRun:
    started = time.perf_counter()
    run = AgentRun(question=question)

    if config.retrieval is None:
        schema = render_full_schema()
    else:
        columns = retrieve_columns(question, config.retrieval)
        run.retrieved_columns = [c.key for c in columns]
        schema = render_schema(columns)

    sql, response = steps.generate_sql(llm, question, schema, config.few_shot)
    run.usage.add("generate_sql", response)
    run.sql = sql

    attempts_left = settings.max_repair_retries if config.repair else 0
    while True:
        try:
            run.result = run_query(run.sql)
            run.status, run.error = "answered", ""
            break
        except (QueryError, UnsafeSQLError) as error:
            run.error = str(error)
            if attempts_left == 0:
                break
            attempts_left -= 1
            run.retries += 1
            run.sql, response = steps.repair_sql(llm, question, schema, run.sql, run.error)
            run.usage.add("repair_sql", response)

    run.total_latency_s = time.perf_counter() - started
    return run
