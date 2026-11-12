"""Merge a partial evaluation report into a base report and recompute the summary.

Used when a spend cap stopped a run early: rerun only the missing question ids, then merge.
    python scripts/merge_reports.py reports/retrieved.json reports/retrieved_rest.json
"""

import json
import sys
from pathlib import Path

from nlagent.evaluate import summarise

if __name__ == "__main__":
    base_path, extra_path = Path(sys.argv[1]), Path(sys.argv[2])
    base, extra = json.loads(base_path.read_text()), json.loads(extra_path.read_text())
    seen = {row["id"] for row in base["per_question"]}
    rows = base["per_question"] + [r for r in extra["per_question"] if r["id"] not in seen]
    rows.sort(key=lambda r: r["id"])
    base["per_question"] = rows
    base["summary"] = summarise(rows)
    base_path.write_text(json.dumps(base, indent=2, default=str))
    print(base_path.name, base["summary"]["questions"], base["summary"]["execution_accuracy"])
