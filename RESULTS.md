# Results

Only measured numbers appear here.

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
| SQL guard: allowed read-only queries accepted | 8 | 8 |
| SQL guard: write statements rejected (DROP, DELETE, UPDATE, INSERT, TRUNCATE, CREATE, ALTER, GRANT, SELECT INTO, stacked, CTE write, COPY, SET) | 13 | 13 |
| SQL guard: tables outside the allowed set rejected (pg_catalog, information_schema, catalog, CTE alias tricks) | 9 | 9 |
| SQL guard: dangerous functions, XML helpers, server info, lock clauses and case-quoted system CTE names rejected | 13 | 13 |
| Each database layer blocks a write on its own (guard, role, read-only session) | 3 | 3 |
| Compromised LLM obeys the attacker: attack never reaches the database, table counts unchanged | 17 | 17 |
| Injection phrases blocked before any LLM call | 5 | 5 |
| Out-of-scope question refused by the classifier (scripted classifier) | 1 | 1 |
| Rate limit applies per user | 1 | 1 |

These are deterministic tests, so the pass rate is 100% by construction wherever the layers work, and a failure would show up as a red test. They do not measure how well the real classifier refuses out-of-scope questions or how often the real model complies with an injection. Running an adversarial question set through `Agent` with a real LLM is not done yet.

## Execution accuracy by configuration (measured)

Model: `gemini-3-flash-preview` through Google's OpenAI-compatible endpoint, temperature 0, one run per configuration over all 56 questions. Reports are in `reports/<config>.json`. One question is worth 1.8 points, and a 95% interval on a score near 85% over 56 questions is roughly plus or minus 9 points. Treat gaps smaller than that as noise.

| Config | Correct | Overall | Easy (20) | Medium (24) | Hard (12) |
|---|---|---|---|---|---|
| full_schema (all 699 columns) | 49 | 87.5% | 90% | 83% | 92% |
| retrieved (vector top 25) | 43 | 76.8% | 90% | 71% | 67% |
| retrieved_fewshot | 49 | 87.5% | 95% | 79% | 92% |
| retrieved_fewshot_repair | 47 | 83.9% | 95% | 75% | 83% |
| graph, vector retrieval | 48 | 85.7% | 95% | 75% | 92% |
| graph, hybrid retrieval | 52 | 92.9% | 95% | 92% | 92% |
| graph, hybrid + rerank (the default `graph`) | 47 | 83.9% | 95% | 71% | 92% |

What this shows:

- **M1 acceptance is not met by the default graph.** `graph` scores 47/56 against 49/56 for the best baselines (`full_schema` and `retrieved_fewshot`), two questions short. The same graph with hybrid retrieval and no reranker scores 52/56 and clears the bar. With this much noise I would not claim the reranker hurts, but there is no evidence here that it helps, and it adds about 1.5 s per question.
- Few-shot examples are the clearest single gain among the baselines (76.8% to 87.5%). The repair loop did not add accuracy here (87.5% to 83.9%, within noise). It spends extra calls on errors that are usually value mistakes, which a retry rarely fixes. See FAILURES.md.
- The full schema in the prompt matches the best retrieved configuration. A 699 column schema fits easily in this model's context, so retrieval earns its keep on cost and latency rather than accuracy: `full_schema` costs about $0.009 per question against about $0.006 for `retrieved_fewshot`.
- Differences between configurations are mostly within noise. I ran each once, so run to run variation at temperature 0 is not measured.

## Retrieval mode vs end-to-end accuracy (measured)

| Graph retrieval | recall@25 (columns) | Execution accuracy |
|---|---|---|
| vector | 0.409 | 85.7% (48/56) |
| hybrid | 0.536 | 92.9% (52/56) |
| hybrid + rerank | 0.521 | 83.9% (47/56) |

Hybrid beats vector on both measures, in the same order for recall and for accuracy. The reranker does not beat hybrid on either. Recall below 0.55 still produced 84 to 93% accuracy because the prompt adds join keys and the model often needs only a few of the columns the metric counts.

## Latency and cost per query (measured)

| Config | p50 | p95 | Cost per question |
|---|---|---|---|
| full_schema | 5.0 s | 19.9 s | $0.0091 |
| retrieved_fewshot | 6.0 s | 20.8 s | $0.0057 |
| retrieved_fewshot_repair | 5.5 s | 20.6 s | $0.0060 |
| graph (default) | 9.1 s | 25.2 s | $0.0068 |
| graph, hybrid | 7.8 s | 23.5 s | $0.0076 |

Latency includes waiting on a shared API with retries, so treat it as a rough guide. The `retrieved` run had a p50 of 19 s because part of it ran under rate limiting, so it is left out of the table. Cost uses an estimated price of $0.50 per million input tokens and $3.00 per million output tokens (including thinking tokens). That price is my assumption, not Google's published rate. Check the Google billing page for actual spend.

## LLM judge agreement (measured)

20 hand-labelled cases (9 faithful, 11 with one deliberate fault). The judge matched the label on 20 of 20, with unfaithful precision 1.0 and recall 1.0. The cases were written with clear faults, so this is an easy test. A harder set with subtle unsupported claims would be needed to say much about the judge. An earlier run scored 90% while replies were being truncated by the token limit.

## Method notes

- **Truncation bug found and fixed.** The first full run scored 52 to 68% because Gemini's hidden thinking tokens counted against `max_tokens`, cutting answers off mid-word (`race_`, `sd.driver_`). The client now adds 4,096 tokens of headroom and raises an error if a reply is still cut off. Cost is now counted from total tokens, which includes thinking. The truncated reports are kept locally in `reports/old_truncated/` (not committed) and are not used in any table.
- **Spend caps ended two runs early.** `retrieved` and `retrieved_fewshot` hit their caps after 33 and 54 questions. I ran only the missing questions and merged them (`scripts/merge_reports.py`), so every row above covers all 56 questions.
- **Model choice.** `gemini-3.8-flash` returned 503 under load and `gemini-2.5-flash` is closed to new keys, so these results are from `gemini-3-flash-preview`. Numbers will differ on another model.
