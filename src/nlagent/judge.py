"""LLM-as-judge for answer faithfulness, and its agreement with hand labels.

Faithful means every fact in the answer is supported by the SQL result. The judge is only
useful if it agrees with a human, so the module measures that agreement on labelled cases.

    python -m nlagent.judge
"""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from nlagent import prompts
from nlagent.db import QueryResult
from nlagent.llm import LLMClient
from nlagent.steps import format_result, parse_json

LABELS_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "judge_labels.yaml"


def judge_faithfulness(llm: LLMClient, question: str, sql: str, result: QueryResult, answer: str) -> dict:
    user = (
        f"Question: {question}\n\nSQL: {sql}\n\nResult:\n{format_result(result)}\n\nAnswer to check: {answer}"
    )
    response = llm.complete(prompts.JUDGE_SYSTEM, user, max_tokens=200)
    parsed = parse_json(response.text) or {}
    return {"faithful": bool(parsed.get("faithful", False)), "reason": parsed.get("reason", "")}


@dataclass(frozen=True)
class LabelledCase:
    question: str
    columns: list[str]
    rows: list[list]
    answer: str
    faithful: bool  # the human label


def load_labelled_cases(path: Path = LABELS_PATH) -> list[LabelledCase]:
    return [LabelledCase(**entry) for entry in yaml.safe_load(path.read_text(encoding="utf-8"))]


def agreement(llm: LLMClient, cases: list[LabelledCase]) -> dict:
    """Share of cases where the judge matches the human, plus precision and recall for 'unfaithful'."""
    verdicts = []
    for case in cases:
        result = QueryResult(case.columns, [tuple(row) for row in case.rows], truncated=False)
        verdict = judge_faithfulness(llm, case.question, "", result, case.answer)
        verdicts.append((case.faithful, verdict["faithful"]))

    agree = sum(human == judge for human, judge in verdicts)
    caught = sum(1 for human, judge in verdicts if not human and not judge)
    flagged = sum(1 for _, judge in verdicts if not judge)
    unfaithful = sum(1 for human, _ in verdicts if not human)
    return {
        "cases": len(cases),
        "agreement": round(agree / len(cases), 4),
        "unfaithful_precision": round(caught / flagged, 4) if flagged else None,
        "unfaithful_recall": round(caught / unfaithful, 4) if unfaithful else None,
    }


if __name__ == "__main__":
    from nlagent.llm import get_llm

    print(json.dumps(agreement(get_llm(), load_labelled_cases()), indent=2))
