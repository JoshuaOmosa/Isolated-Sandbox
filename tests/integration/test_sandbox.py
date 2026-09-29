"""End-to-end checks against a real Docker daemon.

Run with:  make test-integration
"""
from pathlib import Path

import pytest

from orchestrator import BenchmarkRunner, Verdict
from orchestrator.probing import run_probes
from orchestrator.tasks import discover_tasks

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[2]


def by_key(report):
    return {(r.agent, r.task_id): r for r in report.results}


def test_escape_probe_battery_is_fully_contained(manager):
    report = run_probes(manager, ROOT / "probes")
    details = "\n".join(f"{p['probe']}: {p['contained']} ({p['detail']})" for p in report.probes)
    assert report.finished, details
    assert not report.breaches, details
    assert len(report.probes) >= 15


def test_reference_solutions_pass_inside_the_sandbox(manager):
    tasks = discover_tasks(ROOT / "tasks")
    report = BenchmarkRunner(manager, tasks, workers=3).run([])
    assert report.invalid_tasks == []
    assert {r.verdict for r in report.results} == {Verdict.PASSED}
    assert report.leaked_containers == []


def test_demo_agents_are_graded_relative_to_the_reference(manager):
    runner = BenchmarkRunner(manager, discover_tasks(ROOT / "tasks"), workers=3)
    report = runner.run(runner.discover_submissions(ROOT / "submissions"))
    results = by_key(report)

    for task in ("merge_intervals", "lru_cache", "log_parser"):
        assert results[("agent_good", task)].verdict is Verdict.PASSED
        flawed = results[("agent_flawed", task)]
        assert flawed.verdict is Verdict.FAILED and 0 < flawed.score < 1
    assert report.leaked_containers == []


def test_hostile_submissions_are_contained_and_cleaned_up(manager):
    runner = BenchmarkRunner(manager, discover_tasks(ROOT / "tasks"), workers=3)
    report = runner.run(runner.discover_submissions(ROOT / "submissions_hostile"))
    results = by_key(report)

    assert results[("agent_hostile", "merge_intervals")].verdict is Verdict.TIMEOUT  # infinite loop
    assert results[("agent_hostile", "lru_cache")].verdict is Verdict.OOM_KILLED  # memory hog
    fork_bomb = results[("agent_hostile", "log_parser")]
    assert fork_bomb.verdict in {Verdict.TIMEOUT, Verdict.OOM_KILLED, Verdict.ERROR}  # never PASSED

    ceiling = manager.policy.wall_clock_seconds
    assert all(r.duration_seconds < ceiling + 15 for r in report.results)  # hard ceiling honoured
    assert all(r.removed for r in report.results)
    assert report.leaked_containers == []  # nothing survives the run


def test_no_state_leaks_between_runs(manager):
    write = ["python", "-c", "open('/tmp/marker', 'w').write('contaminated')"]
    read = ["python", "-c", "import os, sys; sys.exit(1 if os.path.exists('/tmp/marker') else 0)"]
    with manager.staged_workspace({}) as workspace:
        first = manager.run(workspace, write)
        second = manager.run(workspace, read)
    assert first.exit_code == 0, first.logs
    assert second.exit_code == 0, "marker from the previous run was visible"
    assert first.container_name != second.container_name


def test_containers_are_removed_even_when_the_code_crashes(manager):
    with manager.staged_workspace({}) as workspace:
        result = manager.run(workspace, ["python", "-c", "raise SystemExit(3)"])
    assert result.exit_code == 3 and result.removed
    assert manager.list_leaked() == []
