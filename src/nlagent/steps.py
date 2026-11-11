"""The individual pipeline steps. Each one makes at most one LLM call and returns its usage."""

import json
import re
from dataclasses import dataclass, field

from nlagent import prompts
from nlagent.db import QueryResult
from nlagent.llm import LLMClient, LLMResponse


@dataclass
class Usage:
    """Token, cost and call counts accumulated over a whole question."""

    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    llm_latency_s: float = 0.0
    calls: list[dict] = field(default_factory=list)

    def add(self, step: str, response: LLMResponse) -> None:
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.llm_calls += 1
        self.llm_latency_s += response.latency_s
        self.calls.append({"step": step, "in": response.input_tokens, "out": response.output_tokens})


def extract_sql(text: str) -> str:
    """Pull the SQL out of a reply that may be wrapped in a code fence or followed by prose."""
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    sql = fenced.group(1) if fenced else text
    sql = re.sub(r"^\s*SQL:\s*", "", sql.strip(), flags=re.IGNORECASE)
    return sql.strip().rstrip(";").strip()


def generate_sql(llm: LLMClient, question: str, schema: str, few_shot: bool) -> tuple[str, LLMResponse]:
    response = llm.complete(prompts.SQL_SYSTEM, prompts.sql_user_prompt(question, schema, few_shot))
    return extract_sql(response.text), response


def repair_sql(llm: LLMClient, question: str, schema: str, sql: str, error: str) -> tuple[str, LLMResponse]:
    response = llm.complete(prompts.REPAIR_SYSTEM, prompts.repair_user_prompt(question, schema, sql, error))
    return extract_sql(response.text), response


def classify_intent(llm: LLMClient, question: str) -> tuple[dict, LLMResponse]:
    response = llm.complete(prompts.CLASSIFY_SYSTEM, f"Question: {question}", max_tokens=200)
    parsed = parse_json(response.text) or {}
    intent = parsed.get("intent")
    if intent not in {"data_question", "ambiguous", "out_of_scope"}:
        intent = "data_question"  # when unsure, try to answer rather than block the user
    return {"intent": intent, "clarification": parsed.get("clarification", "")}, response


def format_result(result: QueryResult, max_rows: int = 20) -> str:
    lines = [" | ".join(result.columns)]
    lines += [" | ".join(str(v) for v in row) for row in result.rows[:max_rows]]
    if len(result.rows) > max_rows:
        lines.append(f"... {len(result.rows) - max_rows} more rows")
    if result.truncated:
        lines.append("(result was cut off at the row cap)")
    return "\n".join(lines)


def synthesise_answer(
    llm: LLMClient, question: str, sql: str, result: QueryResult
) -> tuple[str, LLMResponse]:
    user = f"Question: {question}\n\nSQL: {sql}\n\nResult:\n{format_result(result)}"
    response = llm.complete(prompts.SYNTHESIS_SYSTEM, user, max_tokens=300)
    return response.text.strip(), response


def parse_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
