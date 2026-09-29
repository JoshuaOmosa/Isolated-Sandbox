"""Validates the benchmark tasks themselves.

Reference and demo-agent solutions are *trusted repository code*, so they are run
directly on the host here. The hostile submissions are never executed by any unit test.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.grader import PYTEST_COMMAND, parse_summary
from orchestrator.tasks import discover_tasks, load_task

ROOT = Path(__file__).resolve().parents[2]
TASKS = discover_tasks(ROOT / "tasks")


def run_on_host(task, solution: Path, tmp_path: Path) -> dict:
    ws = tmp_path / "ws"
    ws.mkdir()
    shutil.copyfile(solution, ws / task.entrypoint)
    shutil.copytree(task.tests_dir, ws / "tests")
    command = [sys.executable] + PYTEST_COMMAND[1:]
    proc = subprocess.run(command, cwd=ws, capture_output=True, text=True, timeout=60,
                          env={**os.environ, "PYTHONPATH": str(ws), "PYTHONDONTWRITEBYTECODE": "1"})
    summary = parse_summary(proc.stdout)
    assert summary is not None, proc.stdout + proc.stderr
    return {"code": proc.returncode, **summary}


def test_expected_tasks_are_present():
    assert {t.id for t in TASKS} == {"merge_intervals", "lru_cache", "log_parser"}


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_reference_solution_passes_every_test(task, tmp_path):
    outcome = run_on_host(task, task.reference_dir / task.entrypoint, tmp_path)
    assert outcome["code"] == 0 and outcome.get("failed", 0) == 0 and outcome["passed"] >= 8


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_good_demo_agent_passes(task, tmp_path):
    outcome = run_on_host(task, ROOT / "submissions" / "agent_good" / task.id / task.entrypoint, tmp_path)
    assert outcome["code"] == 0


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_flawed_demo_agent_fails_some_but_not_all_tests(task, tmp_path):
    outcome = run_on_host(task, ROOT / "submissions" / "agent_flawed" / task.id / task.entrypoint, tmp_path)
    assert outcome["code"] == 1
    assert outcome.get("failed", 0) >= 1 and outcome.get("passed", 0) >= 1, outcome


def test_every_task_has_a_prompt_and_a_tight_timeout():
    for task in TASKS:
        assert task.prompt.strip()
        assert task.timeout_seconds and task.timeout_seconds <= 60


def test_entrypoint_must_be_a_plain_filename(tmp_path):
    task_dir = tmp_path / "t"
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "task.json").write_text('{"id": "t", "entrypoint": "../evil.py"}')
    with pytest.raises(ValueError):
        load_task(task_dir)


def test_hostile_submissions_live_outside_the_default_submissions_dir():
    assert not (ROOT / "submissions" / "agent_hostile").exists()
    assert (ROOT / "submissions_hostile" / "agent_hostile").is_dir()
