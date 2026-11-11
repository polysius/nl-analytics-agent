"""Scoring and taxonomy logic, plus a check that every gold query in the benchmark is valid."""

import datetime
from decimal import Decimal

import pytest

from nlagent.benchmark import equivalent_keys, load_questions, results_match
from nlagent.failures import classify_failure


def test_row_order_is_ignored_unless_the_question_is_ordered():
    assert results_match([(1,), (2,)], [(2,), (1,)])
    assert not results_match([(1,), (2,)], [(2,), (1,)], ordered=True)


def test_numbers_compare_with_rounding_and_across_types():
    assert results_match([(Decimal("52.0100"),)], [(52.01,)])
    assert results_match([(datetime.date(2020, 1, 2),)], [(datetime.date(2020, 1, 2),)])


def test_duplicate_rows_matter():
    assert not results_match([(1,), (1,)], [(1,)])


def test_view_columns_match_their_race_data_twin():
    assert "race_data.race_points" in equivalent_keys("race_result.points")
    assert equivalent_keys("driver.name") == {"driver.name"}


def test_benchmark_has_unique_ids_and_a_difficulty_mix():
    questions = load_questions()
    assert len({q.id for q in questions}) == len(questions)
    assert {q.difficulty for q in questions} == {"easy", "medium", "hard"}


@pytest.mark.db
def test_every_gold_query_runs_and_returns_rows():
    from nlagent.db import run_query

    for question in load_questions():
        assert run_query(question.gold_sql).rows, question.id


GOLD = "select count(*) from race_result rr join race r on r.id = rr.race_id where r.year = 2014 and rr.position_number = 1"


@pytest.mark.parametrize(
    "predicted,status,error,expected",
    [
        ("select count(*) from race_result rr where rr.position_number = 1", "answered", "", "wrong_join"),
        ("select name from race_result rr join race r on r.id = rr.race_id where r.year = 2014", "answered", "", "aggregation_error"),
        ("select count(*) from race_result rr join race r on r.id = rr.race_id where r.year = 2015 and rr.position_number = 1", "answered", "", "wrong_filter"),
        ("select count(*) from race where yr = 2014", "failed", 'column "yr" does not exist', "hallucinated_column"),
        ("", "clarification", "", "ambiguity"),
    ],
)
def test_failure_classes(predicted, status, error, expected):
    assert classify_failure(status, error, predicted, GOLD) == expected


@pytest.mark.db
def test_gold_columns_resolve_aliases_to_real_tables():
    from nlagent.benchmark import gold_columns
    from nlagent.catalogue import load_catalogue

    columns = gold_columns(GOLD, load_catalogue())
    assert columns == {"race.year", "race_result.position_number"}
