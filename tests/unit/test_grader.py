import pytest

from orchestrator import Verdict, grade
from orchestrator.grader import parse_summary
from sandbox import ExecutionResult


def result(logs="", exit_code=0, timed_out=False, oom=False):
    return ExecutionResult(exit_code=exit_code, logs=logs, duration_seconds=1.0, timed_out=timed_out,
                           oom_killed=oom, container_name="sbx-x", removed=True)


@pytest.mark.parametrize(
    "logs, expected",
    [
        ("....\n4 passed in 0.02s", {"passed": 4}),
        ("F.\n1 failed, 1 passed in 0.03s", {"failed": 1, "passed": 1}),
        ("1 failed, 2 passed, 1 skipped in 1.20s", {"failed": 1, "passed": 2, "skipped": 1}),
        ("2 errors in 0.10s", {"error": 2}),
        ("== 3 passed in 0.5s ==", {"passed": 3}),
        ("no summary here", None),
        ("", None),
    ],
)
def test_parse_summary(logs, expected):
    assert parse_summary(logs) == expected


def test_all_tests_passing_is_passed():
    g = grade(result("10 passed in 0.1s", 0), "a", "t", reference_total=10)
    assert g.verdict is Verdict.PASSED and g.score == 1.0 and g.tests_total == 10


def test_some_failures_is_failed_with_partial_score():
    g = grade(result("2 failed, 8 passed in 0.1s", 1), "a", "t", reference_total=10)
    assert g.verdict is Verdict.FAILED and g.score == 0.8 and g.tests_failed == 2


def test_score_is_relative_to_reference_when_agent_collects_fewer_tests():
    g = grade(result("1 failed, 3 passed in 0.1s", 1), "a", "t", reference_total=10)
    assert g.score == 0.3


def test_timeout_wins_over_everything():
    g = grade(result("10 passed in 0.1s", 137, timed_out=True), "a", "t")
    assert g.verdict is Verdict.TIMEOUT and g.score == 0.0


def test_oom_is_reported():
    assert grade(result("", 137, oom=True), "a", "t").verdict is Verdict.OOM_KILLED


def test_missing_exit_code_is_error():
    assert grade(result("10 passed in 0.1s", None), "a", "t").verdict is Verdict.ERROR


def test_exit_zero_without_summary_is_never_a_pass():
    """e.g. a submission that calls os._exit(0) at import time."""
    g = grade(result("", 0), "a", "t")
    assert g.verdict is Verdict.ERROR and "no pytest summary" in g.note


def test_exit_zero_contradicting_summary_is_error():
    g = grade(result("1 failed, 9 passed in 0.1s", 0), "a", "t")
    assert g.verdict is Verdict.ERROR and "contradicts" in g.note


def test_zero_tests_collected_is_error_not_pass():
    assert grade(result("0 passed in 0.01s", 0), "a", "t").verdict is Verdict.ERROR


@pytest.mark.parametrize("code", [2, 3, 4, 5, 139])
def test_pytest_infrastructure_exit_codes_are_errors(code):
    assert grade(result("1 passed in 0.1s", code), "a", "t").verdict is Verdict.ERROR


def test_collection_errors_are_errors():
    g = grade(result("2 errors in 0.10s", 2), "a", "t")
    assert g.verdict is Verdict.ERROR
