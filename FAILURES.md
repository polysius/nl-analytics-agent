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

## Counts per configuration (measured, Gemini)

Failures per class over the 56 benchmark questions, from `reports/<config>.json`, one run each. No question was classed `ambiguity`: the baselines never ask for clarification, and the classifier did not ask on any benchmark question.

| Stage | Failures | ambiguity | hallucinated_column | wrong_join | aggregation_error | wrong_filter | other |
|---|---|---|---|---|---|---|---|
| Baseline: full_schema | 7 | 0 | 0 | 3 | 0 | 2 | 2 |
| Baseline: retrieved | 13 | 0 | 6 | 4 | 0 | 1 | 2 |
| Baseline: retrieved_fewshot | 7 | 0 | 0 | 4 | 0 | 2 | 1 |
| Baseline: retrieved_fewshot_repair | 9 | 0 | 0 | 5 | 1 | 1 | 2 |
| Graph, vector retrieval | 8 | 0 | 0 | 5 | 0 | 2 | 1 |
| Graph, hybrid retrieval | 4 | 0 | 0 | 1 | 0 | 1 | 2 |
| Graph, hybrid + rerank (default) | 9 | 0 | 0 | 5 | 0 | 2 | 2 |

- Few-shot examples coincide with hallucinated columns dropping from 6 to 0. I did not isolate the cause, but the examples show the view names and join keys that the model otherwise invents.
- Most of what remains is not a SQL logic error. Reading all nine default-graph failures, the dominant cause is the model not knowing how values are stored. The classifier files these as wrong join or wrong filter because the query shape differs from the gold query, which hides the real cause.

## Worked examples

All three come from the default `graph` run.

**1. Value encoding: q11 "How many female drivers are in the database?" (class: other)**
- Gold: `select count(*) from driver where gender = 'FEMALE'`
- Predicted: `SELECT count(*) FROM driver WHERE gender = 'Female'`
- The query is valid and returns 0, so nothing triggered the repair loop. The schema shows `gender` as a text column with no example values, and the model guessed the casing. The same cause explains q32 (`c.name = 'Autodromo Nazionale di Monza'` where the data has `Monza`) and q42 (`'Circuit de Monaco'` against `Monaco`), which the classifier labels wrong_join. Not fixed. The obvious change is to put a few example values for low-cardinality text columns into the catalogue documents and the prompt.

**2. Wrong key type, repair could not recover: q40 "fastest pit stop at the 2023 Monaco Grand Prix" (class: wrong_filter)**
- Gold filters on `r.grand_prix_id = 'monaco'`.
- Predicted filters on `r.id = 'monaco-grand-prix'`, a guessed slug compared against an integer key.
- The database returned `invalid input syntax for type integer`, the repair node ran twice, and it failed both times, so the run ended as `failed`. The error message does not say which column holds the Grand Prix slug, so repair had nothing to correct against. This is why the repair loop did not raise accuracy: errors that come from missing knowledge of the data are not fixed by retrying with the same knowledge.

**3. A defensible different answer: q43 "How many drivers took part in the 2010 season?" (class: wrong_join)**
- Gold counts distinct drivers in race results for 2010 (27).
- Predicted: `SELECT count(*) FROM season_driver WHERE year = 2010`.
- The model counted drivers registered for the season rather than drivers who appeared in a race. The question is ambiguous and the prediction is a reasonable reading, so this is arguably a benchmark question that needs rewording, not a model error. q25 (pole counted from qualifying position 1 rather than the `pole_position` flag) and q48 (grid position 1 rather than `pole_position`) are the same kind of case. Three of the nine failures may be a benchmark problem, which a second reviewer should settle.

## Second model: Claude Sonnet (measured)

Same classifier, same 56 questions, runs in `reports/sonnet/`. Counts are for one run each.

| Stage | Failures | hallucinated_column | wrong_join | aggregation_error | wrong_filter | other |
|---|---|---|---|---|---|---|
| full_schema (all 699 columns) | 6 | 0 | 0 | 0 | 2 | 4 |
| retrieved (vector top 25) | 22 | 2 | 11 | 0 | 1 | 8 |
| retrieved_fewshot | 5 | 0 | 4 | 0 | 0 | 1 |
| retrieved_fewshot_repair | 5 | 0 | 4 | 0 | 0 | 1 |
| graph, vector retrieval | 4 | 0 | 3 | 0 | 0 | 1 |
| graph, hybrid retrieval | 7 | 0 | 1 | 0 | 2 | 4 |
| graph, hybrid + rerank (default) | 6 | 0 | 2 | 0 | 1 | 3 |

The default graph's six misses on Sonnet, read one by one:

- **q08** returned `id` where the gold returns `name`. The answer is probably the right person, but the result set differs.
- **q50 and q52** added a column (`points`, `wins`). The result contains the gold answer plus more, and strict row equality counts it wrong. Whether that should count as wrong is a scoring policy decision, not a model failure.
- **q33** counted rows in the `fastest_lap` view, which has one row per driver per race for every driver who set a lap, instead of the `fastest_lap` flag in race results. The question is easy to misread, so a clearer wording is worth considering.
- **q34** counted countries through the Grand Prix instead of through the circuit. Gemini made the same choice, so it is the only question both models missed. The country on a Grand Prix and the country of the circuit it uses can differ, so the question probably needs rewording.
- **q20** ("How many turns does the Monza circuit have?") was refused by the intent classifier as out of scope. This is a genuine agent defect: the classifier is rejecting a plain question about the data. It cost one question here, and it would cost users more than the benchmark shows. Not fixed yet. A first step would be to tell the classifier that circuit attributes are in scope and to default to answering when unsure.

Taken with the Gemini results, a good share of the remaining misses across both models come from the benchmark and the scoring rule, not the models. A second reviewer should settle q25, q33, q34, q43 and q48, and the scoring could accept a result that contains the gold columns plus extras.
