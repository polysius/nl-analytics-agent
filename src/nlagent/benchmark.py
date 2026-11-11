"""Benchmark questions, execution-accuracy scoring and gold-column extraction."""

import datetime
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import sqlglot
import yaml
from sqlglot import expressions as exp
from sqlglot.optimizer.qualify import qualify

from nlagent.catalogue import ColumnDoc

QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "questions.yaml"

# A per-type view column means the same as the prefixed column of race_data.
VIEW_PREFIX = {
    "race_result": "race_",
    "qualifying_result": "qualifying_",
    "pit_stop": "pit_stop_",
    "fastest_lap": "fastest_lap_",
    "starting_grid_position": "starting_grid_position_",
}


@dataclass(frozen=True)
class Question:
    id: str
    difficulty: str
    question: str
    gold_sql: str
    ordered: bool = False


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Question(
            id=e["id"],
            difficulty=e["difficulty"],
            question=e["question"],
            gold_sql=" ".join(e["gold_sql"].split()),
            ordered=e.get("ordered", False),
        )
        for e in entries
    ]


def _canonical(value):
    if isinstance(value, (Decimal, float)):
        return round(float(value), 2)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def results_match(predicted: list[tuple], gold: list[tuple], ordered: bool = False) -> bool:
    """Execution accuracy: same rows, ignoring row order unless the question needs an order."""
    predicted_rows = [tuple(_canonical(v) for v in row) for row in predicted]
    gold_rows = [tuple(_canonical(v) for v in row) for row in gold]
    if ordered:
        return predicted_rows == gold_rows
    return Counter(predicted_rows) == Counter(gold_rows)


def gold_columns(gold_sql: str, catalogue: list[ColumnDoc]) -> set[str]:
    """The non-key columns a gold query reads, as 'table.column' keys. Used for retrieval recall."""
    schema: dict[str, dict[str, str]] = {}
    for doc in catalogue:
        schema.setdefault(doc.table, {})[doc.column] = doc.data_type
    tree = qualify(sqlglot.parse_one(gold_sql, read="postgres"), schema=schema, dialect="postgres")
    # After qualification a column carries its table alias (r.year), so map aliases back to tables.
    table_of_alias = {t.alias_or_name: t.name for t in tree.find_all(exp.Table)}
    columns = set()
    for column in tree.find_all(exp.Column):
        table = table_of_alias.get(column.table)
        if table and column.name != "id" and not column.name.endswith("_id"):
            columns.add(f"{table}.{column.name}")
    return columns


def equivalent_keys(key: str) -> set[str]:
    """Column keys that satisfy a gold column: itself or its race_data twin for view columns."""
    table, column = key.split(".")
    keys = {key}
    if table in VIEW_PREFIX:
        keys.add(f"race_data.{VIEW_PREFIX[table]}{column}")
    return keys


def column_recall(retrieved: list[ColumnDoc], gold: set[str]) -> float:
    """Share of gold columns present in the retrieved list."""
    if not gold:
        return 1.0
    retrieved_keys = {doc.key for doc in retrieved}
    hits = sum(1 for key in gold if equivalent_keys(key) & retrieved_keys)
    return hits / len(gold)
