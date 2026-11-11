# Results

Only measured numbers appear here. Sections that need an LLM are marked pending and name the command that fills them in.

## Schema retrieval (measured)

Recall is the share of the non-key columns that the gold SQL reads which appear in the top k retrieved columns, averaged over the 56 benchmark questions. A view column such as `race_result.points` also counts as found when its `race_data` twin (`race_data.race_points`) is retrieved. "All found @25" is the share of questions where every needed column was in the top 25. The catalogue has 699 columns. Run: `make retrieval-eval` (`reports/retrieval.json`).

| Mode | recall@10 | recall@25 | recall@50 | all found @25 | p50 latency |
|---|---|---|---|---|---|
| vector only | 0.244 | 0.409 | 0.503 | 0.232 | 28 ms |
| hybrid (vector + BM25, rank fusion) | 0.426 | 0.536 | 0.635 | 0.321 | 27 ms |
| hybrid + cross-encoder rerank | 0.446 | 0.521 | 0.626 | 0.339 | 1,533 ms |

What this shows:

- Adding BM25 to vector search is worth about 13 points of recall@25 for no extra latency. A likely reason is that column names such as `pole_position` match lexically where a small embedding model blurs them, but I did not isolate that.
- The reranker helps at k=10 (+2 points) and in the all-found rate, but it is no better than hybrid at k=25 and costs about 1.5 s per question on CPU. With this catalogue it is not clearly worth its latency. The end-to-end accuracy comparison below is what decides whether to keep it.
- Absolute recall is moderate. Many tables repeat the same column names (`total_pole_positions` exists in many tables), so top-k fills with near duplicates. A table-level retrieval step or column descriptions with example values are the obvious next experiments.

Method note: an earlier run of this evaluation scored 7 to 13 points lower at k=25 depending on the mode, because the gold columns were extracted with table aliases (`r.year`) instead of table names. That was a bug in the metric and is fixed and covered by a test.

## Safety and guardrails (measured, no LLM)

| Check | Cases | Passed |
|---|---|---|
| SQL guard: allowed read-only queries accepted | 5 | 5 |
| SQL guard: write statements rejected (DROP, DELETE, UPDATE, INSERT, TRUNCATE, CREATE, ALTER, GRANT, SELECT INTO, stacked, CTE write, COPY, SET) | 13 | 13 |
| SQL guard: tables outside the allowed set rejected (pg_catalog, information_schema, catalog, CTE alias tricks) | 9 | 9 |
| SQL guard: dangerous functions rejected | 3 | 3 |
| Each database layer blocks a write on its own (guard, role, read-only session) | 3 | 3 |
| Compromised LLM obeys the attacker: attack never reaches the database, table counts unchanged | 17 | 17 |
| Injection phrases blocked before any LLM call | 5 | 5 |
| Out-of-scope question refused by the classifier (scripted classifier) | 1 | 1 |
| Rate limit applies per user | 1 | 1 |

These are deterministic tests, so the pass rate is 100% by construction wherever the layers work, and a failure would show up as a red test. They do not measure how well the real classifier refuses out-of-scope questions or how often the real model complies with an injection. That needs an API key: pending, run the adversarial question set through `Agent` with a real LLM.

## Execution accuracy by configuration (pending)

Needs `ANTHROPIC_API_KEY`. Run `make eval-all`; reports land in `reports/<config>.json`.

| Config | Overall | Easy | Medium | Hard |
|---|---|---|---|---|
| full_schema | pending | pending | pending | pending |
| retrieved | pending | pending | pending | pending |
| retrieved_fewshot | pending | pending | pending | pending |
| retrieved_fewshot_repair | pending | pending | pending | pending |
| graph | pending | pending | pending | pending |

Acceptance for M1: `graph` is equal to or better than the best baseline config.

## Retrieval mode vs end-to-end accuracy (pending)

Run `python -m nlagent.evaluate --config graph_vector`, `graph_hybrid` and `graph`.

## Latency and cost per query (pending)

Reported by the evaluation summary (`latency_p50_s`, `latency_p95_s`, `cost_per_query_usd`). Cost uses list prices in `llm.py`.

## LLM judge agreement (pending)

`benchmark/judge_labels.yaml` holds 20 hand-labelled cases (9 faithful, 11 with one deliberate fault). Run `make judge-eval` for agreement, and precision and recall for the unfaithful class.
