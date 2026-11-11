# Failure taxonomy

Every benchmark question answered incorrectly is assigned one class by `failures.py`. The evaluation writes the class into each report, and the summary counts them.

| Class | Rule |
|---|---|
| `ambiguity` | The agent asked a clarifying question instead of answering |
| `hallucinated_column` | The database said a column or table does not exist, or the guard rejected a table outside the allowed set |
| `wrong_join` | The query ran but touches a different set of tables than the gold query |
| `aggregation_error` | Same tables, but different aggregate functions, grouping, HAVING or LIMIT |
| `wrong_filter` | Same tables and aggregation, but different WHERE conditions (table aliases ignored) |
| `other` | Everything else, such as the right query shape with a wrong projection, or an unparseable query |

The rules are heuristics over SQL structure. A query can fail for two reasons at once and gets the first matching class in the order above. The counts track movement between milestones. They are not a substitute for reading examples.

## Counts per milestone (pending)

Needs benchmark runs with an API key. Each row is one `reports/<config>.json`.

| Stage | ambiguity | hallucinated_column | wrong_join | aggregation_error | wrong_filter | other |
|---|---|---|---|---|---|---|
| Baseline: full_schema | pending | pending | pending | pending | pending | pending |
| Baseline: retrieved | pending | pending | pending | pending | pending | pending |
| Baseline: retrieved_fewshot | pending | pending | pending | pending | pending | pending |
| Baseline: retrieved_fewshot_repair | pending | pending | pending | pending | pending | pending |
| Graph (hybrid + rerank, classify, repair) | pending | pending | pending | pending | pending | pending |

## Worked examples (pending)

The specification asks for three worked examples. They must come from real failures, so they are not written until the benchmark has been run. For each one, record the question, the gold SQL, the predicted SQL, the class, the root cause, and which change fixed it or why it remains.
