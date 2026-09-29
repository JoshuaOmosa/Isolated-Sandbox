"""Turn a raw sandbox execution into a verdict and a score.

The harness output is produced *inside* the same process tree as untrusted code,
so it is treated as evidence, not truth. A PASSED verdict requires the pytest exit
code, the printed summary line and the reported counts to all agree; anything
inconsistent (for example an early `os._exit(0)`) is an ERROR, never a pass.
"""
from __future__ import annotations

import re

from sandbox import ExecutionResult

from .models import GradeResult, Verdict

PYTEST_COMMAND = [
    "python", "-m", "pytest", "tests",
    "-q", "-p", "no:cacheprovider", "--noconftest", "--disable-warnings",
]

_SUMMARY = re.compile(r"\b\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b.* in [\d.]+s")
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)")

_PYTEST_OK, _PYTEST_TESTS_FAILED = 0, 1


def parse_summary(logs: str) -> dict[str, int] | None:
    """Extract counts from pytest's final summary line, or None if there isn't one."""
    for line in reversed(logs.strip().splitlines()):
        if _SUMMARY.search(line):
            counts: dict[str, int] = {}
            for number, label in _COUNT.findall(line):
                key = "error" if label.startswith("error") else label
                counts[key] = counts.get(key, 0) + int(number)
            return counts
    return None


def grade(
    result: ExecutionResult,
    agent: str,
    task_id: str,
    reference_total: int | None = None,
) -> GradeResult:
    base = dict(
        agent=agent,
        task_id=task_id,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        container=result.container_name,
        removed=result.removed,
        log_tail=result.logs[-2000:],
    )

    if result.timed_out:
        return GradeResult(verdict=Verdict.TIMEOUT, note="killed at the wall-clock ceiling", **base)
    if result.oom_killed:
        return GradeResult(verdict=Verdict.OOM_KILLED, note="exceeded the memory limit", **base)
    if result.exit_code is None:
        return GradeResult(verdict=Verdict.ERROR, note="container reported no exit code", **base)

    summary = parse_summary(result.logs)
    if summary is None:
        return GradeResult(
            verdict=Verdict.ERROR,
            note=f"no pytest summary in output (exit code {result.exit_code})",
            **base,
        )

    passed, failed, errors = summary.get("passed", 0), summary.get("failed", 0), summary.get("error", 0)
    total = passed + failed + errors
    denominator = max(reference_total or 0, total) or 1
    score = round(min(passed / denominator, 1.0), 4)
    counts = dict(tests_passed=passed, tests_failed=failed + errors, tests_total=total, score=score)

    if result.exit_code == _PYTEST_OK:
        if failed or errors or passed == 0:
            return GradeResult(verdict=Verdict.ERROR, note="exit code 0 contradicts the summary line", **base, **counts)
        return GradeResult(verdict=Verdict.PASSED, **base, **counts)
    if result.exit_code == _PYTEST_TESTS_FAILED and failed and not errors:
        return GradeResult(verdict=Verdict.FAILED, **base, **counts)
    return GradeResult(
        verdict=Verdict.ERROR,
        note=f"pytest exited with code {result.exit_code} (collection error, crash or signal)",
        **base,
        **counts,
    )
