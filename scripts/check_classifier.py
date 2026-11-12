"""Measure the intent classifier against the benchmark questions and the hand-labelled triage cases.

    python scripts/check_classifier.py [label] [triage.yaml]   # writes reports/classifier_<label>.json

With a second argument, only that triage file is used and the benchmark questions are skipped.

Needs a working LLM (see LLM_PROVIDER in the README). Every benchmark question must come back as
data_question: a refusal there means a real user question would be turned away.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from nlagent.benchmark import load_questions
from nlagent.llm import get_llm
from nlagent.steps import classify_intent

TRIAGE_PATH = Path(__file__).resolve().parents[1] / "benchmark" / "triage.yaml"


def main(label: str, triage_path: Path | None = None) -> None:
    llm = get_llm()
    cases = []
    if triage_path is None:
        cases = [{"question": q.question, "expected": "data_question", "source": q.id} for q in load_questions()]
    cases += [{**c, "source": "triage"} for c in yaml.safe_load((triage_path or TRIAGE_PATH).read_text(encoding="utf-8"))]

    rows = []
    for case in cases:
        verdict, _ = classify_intent(llm, case["question"])
        rows.append({**case, "got": verdict["intent"], "correct": verdict["intent"] == case["expected"]})

    by_expected: dict[str, list[bool]] = {}
    for row in rows:
        by_expected.setdefault(row["expected"], []).append(row["correct"])
    summary = {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_expected.items())}
    summary["errors"] = dict(Counter(f"{r['expected']} -> {r['got']}" for r in rows if not r["correct"]))

    Path("reports").mkdir(exist_ok=True)
    Path(f"reports/classifier_{label}.json").write_text(
        json.dumps({"model": llm.model, "summary": summary, "rows": rows}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    for row in rows:
        if not row["correct"]:
            print(f"  [{row['source']}] expected {row['expected']}, got {row['got']}: {row['question']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "run", Path(sys.argv[2]) if len(sys.argv) > 2 else None)
