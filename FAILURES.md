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

## Counts per configuration (measured)

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
