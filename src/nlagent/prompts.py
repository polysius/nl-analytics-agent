"""Prompt text for every LLM call in the pipeline. Subject-specific text comes from the domain."""

from nlagent.domains import active_domain

_domain = active_domain()
SQL_SYSTEM = _domain.sql_system
FEW_SHOT = _domain.few_shot
CLASSIFY_SYSTEM = _domain.classify_system

REPAIR_SYSTEM = SQL_SYSTEM + """
The previous query failed or returned an error. Fix it and reply with one corrected SELECT query."""

SYNTHESIS_SYSTEM = """You answer a user's question using only the SQL result you are given.
Answer in one or two plain sentences. If the result is empty, say no matching data was found.
If the result was cut off at the row cap, say the list is partial. Do not invent facts."""

JUDGE_SYSTEM = """You check whether an answer is faithful to a SQL result.
Reply with JSON only: {"faithful": true | false, "reason": "..."}.
Faithful means every fact in the answer is supported by the result and nothing is invented."""


def sql_user_prompt(question: str, schema: str, few_shot: bool) -> str:
    parts = [f"Schema:\n{schema}"]
    if few_shot:
        parts.append(FEW_SHOT)
    parts.append(f"Question: {question}\nSQL:")
    return "\n\n".join(parts)


def repair_user_prompt(question: str, schema: str, sql: str, error: str) -> str:
    return (
        f"Schema:\n{schema}\n\nQuestion: {question}\n\nFailed SQL:\n{sql}\n\nError:\n{error}\n\nCorrected SQL:"
    )
