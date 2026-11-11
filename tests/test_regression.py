from nlagent.regression import check


def report(accuracy):
    return {"summary": {"execution_accuracy": accuracy}}


def test_small_drop_passes():
    passed, _ = check(report(0.75), {"execution_accuracy": 0.80}, max_drop=0.10)
    assert passed


def test_improvement_passes():
    passed, _ = check(report(0.90), {"execution_accuracy": 0.80}, max_drop=0.10)
    assert passed


def test_a_broken_prompt_that_halves_accuracy_fails():
    passed, message = check(report(0.40), {"execution_accuracy": 0.80}, max_drop=0.10)
    assert not passed
    assert "drop +0.400" in message


def test_a_drop_exactly_at_the_threshold_passes():
    passed, _ = check(report(0.70), {"execution_accuracy": 0.80}, max_drop=0.10 + 1e-9)
    assert passed


def test_a_report_over_different_questions_fails_even_with_higher_accuracy():
    current = {"summary": {"execution_accuracy": 0.95}, "per_question": [{"id": "q01"}, {"id": "q02"}]}
    baseline = {"execution_accuracy": 0.80, "question_ids": ["q01", "q03"]}
    passed, message = check(current, baseline, max_drop=0.10)
    assert not passed
    assert "different questions" in message


def test_a_report_over_the_baseline_questions_is_compared_on_accuracy():
    current = {"summary": {"execution_accuracy": 0.75}, "per_question": [{"id": "q01"}, {"id": "q02"}]}
    baseline = {"execution_accuracy": 0.80, "question_ids": ["q01", "q02"]}
    passed, _ = check(current, baseline, max_drop=0.10)
    assert passed
