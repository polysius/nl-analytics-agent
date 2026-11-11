"""Fail the build when execution accuracy drops more than an allowed amount.

    python -m nlagent.regression --report reports/pr.json --baseline benchmark/ci_baseline.json

The baseline file holds the accuracy of the main branch on the same fixed question subset:
    {"execution_accuracy": 0.8, "question_ids": ["q01", ...]}
Write it with `--write-baseline` after an intentional change.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MAX_DROP = 0.10  # ten percentage points, chosen by the repository owner


def check(report: dict, baseline: dict, max_drop: float) -> tuple[bool, str]:
    baseline_ids = baseline.get("question_ids")
    if baseline_ids is not None and baseline_ids != [row["id"] for row in report["per_question"]]:
        return False, "report ran different questions than the baseline; rerun the same subset or rewrite the baseline"
    current = report["summary"]["execution_accuracy"]
    previous = baseline["execution_accuracy"]
    drop = previous - current
    message = f"accuracy {current:.3f} vs baseline {previous:.3f} (drop {drop:+.3f}, allowed {max_drop:.3f})"
    return drop <= max_drop, message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--max-drop", type=float, default=DEFAULT_MAX_DROP)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if args.write_baseline:
        baseline = {
            "execution_accuracy": report["summary"]["execution_accuracy"],
            "question_ids": [row["id"] for row in report["per_question"]],
            "model": report["model"],
        }
        args.baseline.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        print(f"Wrote {args.baseline}")
        return 0

    if not args.baseline.exists():
        print(f"No baseline at {args.baseline}. Create one with --write-baseline.")
        return 1
    passed, message = check(report, json.loads(args.baseline.read_text(encoding="utf-8")), args.max_drop)
    print(("PASS: " if passed else "FAIL: ") + message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
