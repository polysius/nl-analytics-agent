"""Run the benchmark against one configuration and write a JSON report.

    python -m nlagent.evaluate --config graph --out reports/graph.json
    python -m nlagent.evaluate --config full_schema --limit 10 --max-cost-usd 0.50
"""

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from nlagent.baseline import BASELINE_CONFIGS, run_baseline
from nlagent.benchmark import Question, load_questions, results_match
from nlagent.db import run_query
from nlagent.failures import classify_failure
from nlagent.graph import GraphConfig, build_graph, run_graph
from nlagent.llm import LLMClient, ReplyTruncatedError, estimate_cost, get_llm
from nlagent.runs import AgentRun
from nlagent.tracing import emit_trace

GRAPH_CONFIGS = {
    "graph": GraphConfig(retrieval="hybrid_rerank"),
    "graph_vector": GraphConfig(retrieval="vector"),
    "graph_hybrid": GraphConfig(retrieval="hybrid"),
    "graph_no_classify": GraphConfig(retrieval="hybrid_rerank", classify=False),
}
ALL_CONFIGS = [*BASELINE_CONFIGS, *GRAPH_CONFIGS]


class TokenTally:
    """Wraps an LLM client and counts every billed token, including calls that end in an exception."""

    def __init__(self, llm: LLMClient):
        self._llm = llm
        self.model = llm.model
        self.input_tokens = 0
        self.output_tokens = 0

    def reset(self) -> None:
        self.input_tokens = self.output_tokens = 0

    def complete(self, system: str, user: str, max_tokens: int = 1024):
        try:
            response = self._llm.complete(system, user, max_tokens)
        except ReplyTruncatedError as exc:
            self.input_tokens += exc.input_tokens
            self.output_tokens += exc.output_tokens
            raise
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        return response


def make_runner(config_name: str, llm: LLMClient):
    """Return a function that takes a question string and returns an AgentRun."""
    if config_name in BASELINE_CONFIGS:
        config = BASELINE_CONFIGS[config_name]
        return lambda question: run_baseline(llm, question, config)
    if config_name in GRAPH_CONFIGS:
        compiled = build_graph(llm, GRAPH_CONFIGS[config_name])
        return lambda question: run_graph(compiled, question)
    raise SystemExit(f"Unknown config {config_name!r}. Choose from: {', '.join(ALL_CONFIGS)}")


def score_question(question: Question, run: AgentRun, model: str) -> dict:
    gold_rows = run_query(question.gold_sql).rows
    answered = run.result is not None and run.status not in ("clarification", "refused")
    correct = answered and results_match(run.result.rows, gold_rows, question.ordered)
    failure = None
    if not correct:
        failure = classify_failure(run.status, run.error, run.sql, question.gold_sql)
    return {
        "id": question.id,
        "difficulty": question.difficulty,
        "question": question.question,
        "correct": bool(correct),
        "status": run.status,
        "predicted_sql": run.sql,
        "gold_sql": question.gold_sql,
        "error": run.error,
        "failure_class": failure,
        "retries": run.retries,
        "latency_s": round(run.total_latency_s, 3),
        "input_tokens": run.usage.input_tokens,
        "output_tokens": run.usage.output_tokens,
        "cost_usd": round(estimate_cost(model, run.usage.input_tokens, run.usage.output_tokens), 6),
        "retrieved_columns": run.retrieved_columns,
    }


def summarise(per_question: list[dict]) -> dict:
    by_difficulty = defaultdict(list)
    for row in per_question:
        by_difficulty[row["difficulty"]].append(row["correct"])
    latencies = sorted(row["latency_s"] for row in per_question)
    p95_index = max(0, int(round(0.95 * len(latencies))) - 1)
    return {
        "questions": len(per_question),
        "execution_accuracy": round(sum(r["correct"] for r in per_question) / len(per_question), 4),
        "by_difficulty": {d: round(sum(v) / len(v), 4) for d, v in sorted(by_difficulty.items())},
        "failure_classes": dict(Counter(r["failure_class"] for r in per_question if r["failure_class"])),
        "latency_p50_s": round(statistics.median(latencies), 3),
        "latency_p95_s": latencies[p95_index],
        "cost_total_usd": round(sum(r["cost_usd"] for r in per_question), 4),
        "cost_per_query_usd": round(sum(r["cost_usd"] for r in per_question) / len(per_question), 5),
    }


def run_eval(config_name: str, llm: LLMClient, questions: list[Question], max_cost_usd: float | None) -> dict:
    tally = TokenTally(llm)
    runner = make_runner(config_name, tally)
    per_question, spent = [], 0.0
    for question in questions:
        tally.reset()
        try:
            run = runner(question.question)
        except ReplyTruncatedError as exc:
            # One truncated reply must not abort the whole benchmark; record it as a failed question.
            run = AgentRun(question=question.question, status="failed", error=str(exc))
            run.usage.input_tokens = tally.input_tokens
            run.usage.output_tokens = tally.output_tokens
        if run.trace:  # graph runs only; a no-op unless LANGFUSE_HOST and keys are set
            emit_trace(run, user_id="benchmark", model=llm.model)
        row = score_question(question, run, llm.model)
        per_question.append(row)
        spent += row["cost_usd"]
        print(f"{question.id} {'ok ' if row['correct'] else 'ERR'} {row['latency_s']:.1f}s", flush=True)
        if max_cost_usd is not None and spent > max_cost_usd:
            print(f"Stopping: spent ${spent:.2f}, over the ${max_cost_usd:.2f} cap.")
            break
    return {
        "config": config_name,
        "model": llm.model,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": summarise(per_question),
        "per_question": per_question,
    }


def select_questions(limit: int | None, ids: str | None) -> list[Question]:
    questions = load_questions()
    if ids:
        wanted = set(ids.split(","))
        return [q for q in questions if q.id in wanted]
    if limit:
        # Sample evenly across the whole list so a small subset keeps the easy/medium/hard mix.
        count = min(limit, len(questions))
        return [questions[i * len(questions) // count] for i in range(count)]
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, choices=ALL_CONFIGS)
    parser.add_argument("--limit", type=int, help="run an evenly spaced subset of this size")
    parser.add_argument("--ids", help="comma separated question ids, for example q01,q07")
    parser.add_argument("--max-cost-usd", type=float, help="stop once estimated spend passes this")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    started = time.perf_counter()
    report = run_eval(args.config, get_llm(), select_questions(args.limit, args.ids), args.max_cost_usd)
    out = args.out or Path("reports") / f"{args.config}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Wrote {out} in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
