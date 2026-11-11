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
