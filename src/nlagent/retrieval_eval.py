"""Measure schema retrieval recall@k for each retrieval mode. Needs no LLM or API key.

    python -m nlagent.retrieval_eval            # writes reports/retrieval.json, prints a table
"""

import json
import statistics
import time
from pathlib import Path

from nlagent.benchmark import column_recall, gold_columns, load_questions
from nlagent.catalogue import load_catalogue
from nlagent.retrieval import RetrievalMode, retrieve_columns

MODES: list[RetrievalMode] = ["vector", "hybrid", "hybrid_rerank"]
CUTOFFS = [10, 25, 50]


def evaluate_retrieval() -> dict:
    catalogue = load_catalogue()
    questions = load_questions()
    gold = {q.id: gold_columns(q.gold_sql, catalogue) for q in questions}

    report = {"questions": len(questions), "modes": {}}
    for mode in MODES:
        recalls = {k: [] for k in CUTOFFS}
        latencies = []
        for question in questions:
            started = time.perf_counter()
            retrieved = retrieve_columns(question.question, mode, k=max(CUTOFFS))
            latencies.append(time.perf_counter() - started)
            for k in CUTOFFS:
                recalls[k].append(column_recall(retrieved[:k], gold[question.id]))
        report["modes"][mode] = {
            "recall_at_k": {str(k): round(statistics.mean(v), 4) for k, v in recalls.items()},
            "full_recall_at_k": {str(k): round(sum(r == 1.0 for r in v) / len(v), 4) for k, v in recalls.items()},
            "latency_p50_ms": round(statistics.median(latencies) * 1000, 1),
        }
    return report


def to_markdown(report: dict) -> str:
    header = "| Mode | " + " | ".join(f"recall@{k}" for k in CUTOFFS) + " | all columns found @25 | p50 latency |"
    lines = [header, "|---|" + "---|" * (len(CUTOFFS) + 2)]
    for mode, stats in report["modes"].items():
        recalls = " | ".join(f"{stats['recall_at_k'][str(k)]:.3f}" for k in CUTOFFS)
        lines.append(
            f"| {mode} | {recalls} | {stats['full_recall_at_k']['25']:.3f} | {stats['latency_p50_ms']} ms |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    report = evaluate_retrieval()
    Path("reports").mkdir(exist_ok=True)
    Path("reports/retrieval.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(to_markdown(report))
