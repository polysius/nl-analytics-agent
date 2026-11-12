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

## Execution accuracy by configuration (measured, Gemini)

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

## Retrieval mode vs end-to-end accuracy (measured, Gemini)

| Graph retrieval | recall@25 (columns) | Execution accuracy |
|---|---|---|
| vector | 0.409 | 85.7% (48/56) |
| hybrid | 0.536 | 92.9% (52/56) |
| hybrid + rerank | 0.521 | 83.9% (47/56) |

Hybrid beats vector on both measures, in the same order for recall and for accuracy. The reranker does not beat hybrid on either. Recall below 0.55 still produced 84 to 93% accuracy because the prompt adds join keys and the model often needs only a few of the columns the metric counts.

## Latency and cost per query (measured, Gemini)

| Config | p50 | p95 | Cost per question |
|---|---|---|---|
| full_schema | 5.0 s | 19.9 s | $0.0091 |
| retrieved_fewshot | 6.0 s | 20.8 s | $0.0057 |
| retrieved_fewshot_repair | 5.5 s | 20.6 s | $0.0060 |
| graph (default) | 9.1 s | 25.2 s | $0.0068 |
| graph, hybrid | 7.8 s | 23.5 s | $0.0076 |

Latency includes waiting on a shared API with retries, so treat it as a rough guide. The `retrieved` run had a p50 of 19 s because part of it ran under rate limiting, so it is left out of the table. Cost uses an estimated price of $0.50 per million input tokens and $3.00 per million output tokens (including thinking tokens). That price is my assumption, not Google's published rate. Check the Google billing page for actual spend.

## LLM judge agreement (measured, Gemini as judge)

20 hand-labelled cases (9 faithful, 11 with one deliberate fault). The judge matched the label on 20 of 20, with unfaithful precision 1.0 and recall 1.0. The cases were written with clear faults, so this is an easy test. A harder set with subtle unsupported claims would be needed to say much about the judge. An earlier run scored 90% while replies were being truncated by the token limit.

## Second model: Claude Sonnet through the Claude Code CLI (measured)

The Gemini key ran out of credit, so the same seven configurations were rerun on Claude Sonnet (`claude-sonnet-5-5`) through the local Claude Code CLI, using `scripts/claude_cli_bridge.py`. Same 56 questions, one run each, reports in `reports/sonnet/`. The CLI has no temperature setting, so these runs are not deterministic. `full_schema` hit its spend cap at 50 questions, so its last six were run separately and merged.

| Config | Correct | Overall | Easy (20) | Medium (24) | Hard (12) |
|---|---|---|---|---|---|
| full_schema (all 699 columns) | 50 | 89.3% | 100% | 92% | 67% |
| retrieved (vector top 25) | 34 | 60.7% | 80% | 62% | 25% |
| retrieved_fewshot | 51 | 91.1% | 100% | 88% | 83% |
| retrieved_fewshot_repair | 51 | 91.1% | 100% | 88% | 83% |
| graph, vector retrieval | 52 | 92.9% | 95% | 88% | 100% |
| graph, hybrid retrieval | 49 | 87.5% | 80% | 92% | 92% |
| graph, hybrid + rerank (the default `graph`) | 50 | 89.3% | 90% | 92% | 83% |

| Config | p50 | p95 | Cost per question (list price) |
|---|---|---|---|
| full_schema (all 699 columns) | 2.8 s | 3.7 s | $0.0409 |
| retrieved (vector top 25) | 3.8 s | 6.5 s | $0.0088 |
| retrieved_fewshot | 2.8 s | 4.8 s | $0.0074 |
| retrieved_fewshot_repair | 2.7 s | 4.3 s | $0.0072 |
| graph, vector retrieval | 7.6 s | 9.8 s | $0.0128 |
| graph, hybrid retrieval | 7.8 s | 10.2 s | $0.0131 |
| graph, hybrid + rerank (the default `graph`) | 9.5 s | 11.4 s | $0.0125 |

Cost is the list-price equivalent. These calls ran on a Claude Code plan, so no card was charged. Latency here is much steadier than the Gemini runs because the CLI is a dedicated local call, not a shared free-tier endpoint.

What the two models agree on:

- **Few-shot examples matter most.** On the baseline with vector retrieval, adding them moves Sonnet from 60.7% to 91.1% and Gemini from 76.8% to 87.5%.
- **The repair loop adds nothing here.** Sonnet scores 51/56 with and without it. Gemini scored 49 without and 47 with.
- **The default graph again misses the baseline target by one or two questions.** Sonnet: 50 against 51 for the best baselines. Gemini: 47 against 49. The graph with vector retrieval scored highest on Sonnet (52/56), and the one with hybrid retrieval scored highest on Gemini (52/56). Across both models the graph variants land between 47 and 52, which is noise at this sample size. There is no evidence that the reranker or the hybrid search improves end-to-end accuracy, even though hybrid search clearly improves retrieval recall.
- **A long prompt is not a problem for these models.** `full_schema` matches the best retrieved configuration on both, at about five times the cost per question on Sonnet ($0.041 against $0.0074).

Where they differ: Sonnet's misses are mostly about the shape of the answer under strict scoring. Two returned an extra column (q50, q52), one returned an id instead of a name (q08), and one used a different view than the gold query (q33). The classifier also wrongly refused one plain data question (q20), which is a real defect in the graph and is listed in FAILURES.md. Only q34 failed on both models.

The LLM judge was not rerun on Sonnet.

## Intent classifier check (measured, Claude Sonnet)

The classifier sorts each question into data_question, ambiguous or out_of_scope. A wrong refusal turns a real user away, so `scripts/check_classifier.py` checks that all 56 benchmark questions come back as data_question, plus hand-labelled cases in `benchmark/triage.yaml` (10 out of scope including injection and write requests, 6 ambiguous, 8 plain data questions).

| Prompt | Benchmark + triage (80 cases) | Held-out (20 cases) |
|---|---|---|
| Before | 78 of 80. Two false refusals: q20 (out of scope) and q11 (ambiguous) | 17 of 20. Three false refusals of data questions |
| After | 80 of 80 | 19 of 20 |

The fix rewrote `CLASSIFY_SYSTEM`: it now lists what the database covers, says that a single fact such as a circuit's direction counts as a data question, restricts "ambiguous" to questions with no sensible default reading, and says to choose data_question when unsure.

Three caveats. The first rewrite named the failing questions' own topics, so it was partly tuned to the benchmark. I replaced those examples with a circuit's length and a constructor's nationality, which also appear in the 80 case set, so that set is not independent of the prompt. The 20 questions in `benchmark/triage_heldout.yaml` do not overlap those two examples, but they are not fully independent either: the prompt's topic list names tyre suppliers, which matches the held-out question about the 1980 tyre manufacturer, and two other prompt examples ("who is the best driver?", "how many wins?") also appear in the 80 case set. That is where the "before" prompt wrongly refused 3 of 10 data questions and the "after" prompt refused none. An earlier version of the prompt used examples that did overlap two held-out questions. I caught it in review, changed the examples, and remeasured, and the result was the same. I did see the held-out results before finalising, though I changed nothing in response to them. Second, the new prompt is more willing to answer: it answered "Compare Hamilton and Verstappen." instead of asking what to compare, which was the one held-out miss. That is the intended trade, but it means some under-specified questions get a default reading. Twenty held-out cases is small, and each case was run once. A full graph run on q11 and q20 after the fix, recorded in `reports/sonnet/classifier_fix_e2e.json`, answered both correctly.

## Langfuse tracing (measured, Claude Sonnet)

Langfuse 4.78 ran locally from `observability/langfuse/docker-compose.yml`. Ten benchmark questions (`--limit 10`) were run through the graph with tracing on. The report is `reports/sonnet/langfuse_run.json`.

Reading the traces back through Langfuse's API after the run (11 traces, because one earlier single question was also sent):

| What Langfuse holds | Count |
|---|---|
| Traces (one per question) | 11 |
| Observations in total | 66 |
| Per question | 1 root span, `retrieve` span, `execute` span, and `classify`, `generate`, `synthesise` generations |
| Generations with model, input tokens, output tokens and cost | all 33 |

The token and cost totals in Langfuse (40,194 input, 1,780 output, $0.147 at list price) match the evaluation report for the same questions. No node recorded an error in this run, so the error-level display is covered by a unit test but was not seen live.

Latency and cost per query for those ten questions: p50 9.8 s, p95 14.1 s, $0.0135 per question at list price. The full 56-question figures are in the Sonnet table above.

**A bug this exposed.** The first version of the tracer sent events to Langfuse's legacy `/api/public/ingestion` endpoint. Langfuse 4 accepts the request but drops the events, and its log says "These events were not stored". The unit tests passed because they used a mocked server. The tracer now sends OpenTelemetry (OTLP over HTTP/JSON) to `/api/public/otel/v1/traces`, which was checked against the live server as above.

## Accuracy gate demonstration (measured, Claude Sonnet)

The gate scores a fixed 20-question subset of the benchmark and compares it with `benchmark/ci_baseline.json`. The baseline is 85% (17 of 20). Reports are in `reports/sonnet/`.

| Run | Accuracy | Gate result |
|---|---|---|
| Baseline run | 85% | baseline written |
| Rerun with no change | 80% (16 of 20) | PASS, drop of 5 points against 10 allowed |
| Deliberately broken SQL prompt (`scripts/demo_broken_prompt.py`) | 40% (8 of 20) | FAIL, drop of 45 points, exit code 1 |

The gate catches a broken prompt. The unchanged rerun lost a question on its own, which shows the noise the threshold has to absorb. The broken prompt still scored 40% rather than near zero: it only replaced the instruction text, and the question and schema in the user message were enough for the model to write valid SQL for some questions anyway.

## Method notes

- **Truncation bug found and fixed.** The first full run scored 52 to 68% because Gemini's hidden thinking tokens counted against `max_tokens`, cutting answers off mid-word (`race_`, `sd.driver_`). The client now adds 4,096 tokens of headroom and raises an error if a reply is still cut off. Cost is now counted from total tokens, which includes thinking. The truncated reports are kept locally in `reports/old_truncated/` (not committed) and are not used in any table.
- **Spend caps ended two runs early.** `retrieved` and `retrieved_fewshot` hit their caps after 33 and 54 questions. I ran only the missing questions and merged them (`scripts/merge_reports.py`), so every row above covers all 56 questions.
- **Bridge runs.** The first Sonnet attempt launched three evaluations at once and every call failed with an empty error, so the runs were redone one at a time. The bridge now reports the CLI's real error text.
- **Model choice.** `gemini-3.8-flash` returned 503 under load and `gemini-2.5-flash` is closed to new keys, so these results are from `gemini-3-flash-preview`. Numbers will differ on another model.
