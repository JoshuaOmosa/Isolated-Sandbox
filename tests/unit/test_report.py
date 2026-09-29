import json

from orchestrator import GradeResult, SuiteReport, Verdict
from orchestrator.report import to_json, to_markdown


def sample():
    return SuiteReport(
        started_at="2026-01-01T00:00:00+00:00",
        wall_seconds=12.5,
        budget_seconds=2400,
        results=[
            GradeResult("reference", "t1", Verdict.PASSED, 4, 0, 4, 1.0, 1.0),
            GradeResult("agent", "t1", Verdict.FAILED, 3, 1, 4, 0.75, 1.0),
            GradeResult("evil", "t1", Verdict.TIMEOUT, duration_seconds=20.0, note="killed at the wall-clock ceiling"),
        ],
        leaked_containers=[],
    )


def test_json_round_trips_and_uses_string_verdicts():
    data = json.loads(to_json(sample()))
    assert data["results"][1]["verdict"] == "FAILED"
    assert data["wall_seconds"] == 12.5 and data["leaked_containers"] == []


def test_markdown_shows_grid_scores_and_notable_runs():
    md = to_markdown(sample())
    assert "Verdict grid" in md and "PASSED (4/4)" in md and "FAILED (3/4)" in md
    assert "| agent | 1 | 0 | 0.75 |" in md
    assert "`evil` / `t1`: TIMEOUT" in md
    assert "Leaked containers: **0**" in md


def test_markdown_flags_invalid_tasks_and_unremoved_containers():
    report = sample()
    report.invalid_tasks = ["broken"]
    report.results[1].removed = False
    md = to_markdown(report)
    assert "Invalid tasks" in md and "`broken`" in md
    assert "container not removed" in md
