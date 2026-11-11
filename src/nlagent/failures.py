"""Rule-based failure taxonomy for benchmark questions that were answered incorrectly.

The rules are heuristics over the predicted and gold SQL. They give counts that are good
enough to track change between milestones; FAILURES.md reviews worked examples by hand.
"""

import sqlglot
from sqlglot import expressions as exp

CLASSES = ["wrong_join", "wrong_filter", "hallucinated_column", "aggregation_error", "ambiguity", "other"]


def classify_failure(status: str, error: str, predicted_sql: str, gold_sql: str) -> str:
    if status == "clarification":
        return "ambiguity"
    if error and ("does not exist" in error or "not in the allowed set" in error):
        return "hallucinated_column"
    if not predicted_sql:
        return "other"
    try:
        predicted = sqlglot.parse_one(predicted_sql, read="postgres")
        gold = sqlglot.parse_one(gold_sql, read="postgres")
    except sqlglot.errors.SqlglotError:
        return "other"

    if _tables(predicted) != _tables(gold):
        return "wrong_join"
    if _shape(predicted) != _shape(gold):
        return "aggregation_error"
    if _filters(predicted) != _filters(gold):
        return "wrong_filter"
    return "other"


def _tables(tree: exp.Expression) -> set[str]:
    ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name not in ctes}


def _shape(tree: exp.Expression) -> tuple:
    """Which aggregation features the query uses: functions, grouping, ordering and limits."""
    return (
        tuple(sorted({type(f).__name__ for f in tree.find_all(exp.AggFunc)})),
        tree.find(exp.Group) is not None,
        tree.find(exp.Having) is not None,
        tree.find(exp.Limit) is not None,
    )


def _filters(tree: exp.Expression) -> set[str]:
    """WHERE conditions as text, with table aliases removed so `r.year` equals `year`."""
    where = tree.find(exp.Where)
    if where is None:
        return set()
    condition = where.this.copy()
    for column in condition.find_all(exp.Column):
        column.set("table", None)
    parts = condition.flatten() if isinstance(condition, exp.And) else [condition]
    return {part.sql(dialect="postgres").lower() for part in parts}
