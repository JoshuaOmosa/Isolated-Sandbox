from dataclasses import replace
from pathlib import Path

import pytest

from orchestrator import BenchmarkRunner, Submission, Task, Verdict
from sandbox import ExecutionResult, SandboxError, SandboxManager, SandboxPolicy

from .fakes import FakeClock


def outcome(logs, code=0, timed_out=False):
    return ExecutionResult(code, logs, 0.5, timed_out, False, "sbx-fake", True)


class ScriptedManager(SandboxManager):
    """Real workspace staging, scripted execution: behaviour is chosen by a marker in solution.py."""

    def __init__(self, scratch_root, **kw):
        super().__init__(policy=SandboxPolicy(wall_clock_seconds=30), client=object(), scratch_root=scratch_root, **kw)
        self.policies = []
        self.calls = 0
        self.leaked = []

    def run(self, workspace, command, policy=None):
        self.calls += 1
        self.policies.append(policy)
        text = (workspace / "solution.py").read_text()
        if "RAISE" in text:
            raise SandboxError("daemon unreachable")
        if "HANG" in text:
            return outcome("", 137, timed_out=True)
        if "FLAWED" in text:
            return outcome("1 failed, 3 passed in 0.1s", 1)
        if "BROKEN_REFERENCE" in text:
            return outcome("1 failed in 0.1s", 1)
        return outcome("4 passed in 0.1s", 0)

    def list_leaked(self):
        return self.leaked


def make_task(root: Path, task_id: str, reference_text="# ok", timeout=None) -> Task:
    path = root / "tasks" / task_id
    (path / "tests").mkdir(parents=True)
    (path / "reference").mkdir()
    (path / "tests" / "test_task.py").write_text("def test_x(): pass\n")
    (path / "reference" / "solution.py").write_text(reference_text)
    return Task(id=task_id, title=task_id, prompt="", path=path, timeout_seconds=timeout)


def make_sub(root: Path, agent: str, task: Task, text: str) -> Submission:
    path = root / "subs" / agent / task.id
    path.mkdir(parents=True)
    (path / "solution.py").write_text(text)
    return Submission(agent, task.id, path)


@pytest.fixture()
def root(tmp_path):
    return tmp_path


def test_results_include_reference_and_are_sorted_reference_first(root):
    t1, t2 = make_task(root, "b_task"), make_task(root, "a_task")
    subs = [make_sub(root, "zed", t1, "ok"), make_sub(root, "alpha", t2, "FLAWED")]
    report = BenchmarkRunner(ScriptedManager(root), [t1, t2], workers=2).run(subs)

    keys = [(r.agent, r.task_id) for r in report.results]
    assert keys == [("reference", "a_task"), ("reference", "b_task"), ("alpha", "a_task"), ("zed", "b_task")]
    assert report.invalid_tasks == []


def test_score_is_graded_relative_to_the_reference(root):
    task = make_task(root, "t")
    report = BenchmarkRunner(ScriptedManager(root), [task]).run([make_sub(root, "agent", task, "FLAWED")])
    agent = next(r for r in report.results if r.agent == "agent")
    assert agent.verdict is Verdict.FAILED and agent.score == 0.75  # 3 of the reference's 4 tests


def test_task_whose_reference_fails_is_invalid_and_agents_are_not_run(root):
    bad = make_task(root, "bad", reference_text="BROKEN_REFERENCE")
    good = make_task(root, "good")
    manager = ScriptedManager(root)
    subs = [make_sub(root, "agent", bad, "ok"), make_sub(root, "agent", good, "ok")]
    report = BenchmarkRunner(manager, [bad, good]).run(subs)

    assert report.invalid_tasks == ["bad"]
    assert [r.task_id for r in report.results if r.agent == "agent"] == ["good"]


def test_runaway_submission_is_reported_as_timeout(root):
    task = make_task(root, "t")
    report = BenchmarkRunner(ScriptedManager(root), [task]).run([make_sub(root, "evil", task, "HANG")])
    assert next(r for r in report.results if r.agent == "evil").verdict is Verdict.TIMEOUT


def test_exhausted_suite_budget_skips_remaining_runs(root):
    clock = FakeClock()
    task = make_task(root, "t")

    class SlowManager(ScriptedManager):
        def run(self, workspace, command, policy=None):
            clock.now += 11  # each sandbox run "takes" longer than the whole suite budget
            return super().run(workspace, command, policy)

    manager = SlowManager(root)
    runner = BenchmarkRunner(manager, [task], suite_budget_seconds=10, clock=clock, workers=1)
    report = runner.run([make_sub(root, "agent", task, "ok")])

    by_agent = {r.agent: r for r in report.results}
    assert by_agent["reference"].verdict is Verdict.PASSED  # calibration ran while budget remained
    assert by_agent["agent"].verdict is Verdict.SKIPPED_BUDGET
    assert manager.calls == 1  # the skipped run never started a container


def test_task_can_tighten_but_never_loosen_the_ceiling(root):
    tight = make_task(root, "tight", timeout=5)
    loose = make_task(root, "loose", timeout=999)
    manager = ScriptedManager(root)
    BenchmarkRunner(manager, [tight, loose], workers=1).run([])
    ceilings = sorted(p.wall_clock_seconds for p in manager.policies)
    assert ceilings == [5, 30]


def test_no_run_can_outlive_the_suite_budget(root):
    task = make_task(root, "t")
    manager = ScriptedManager(root)
    BenchmarkRunner(manager, [task], suite_budget_seconds=12).run([])
    assert manager.policies[0].wall_clock_seconds <= 12


def test_missing_entrypoint_is_an_error_without_starting_a_container(root):
    task = make_task(root, "t")
    empty = root / "subs" / "agent" / "t"
    empty.mkdir(parents=True)
    manager = ScriptedManager(root)
    report = BenchmarkRunner(manager, [task], include_reference=False).run([Submission("agent", "t", empty)])
    assert report.results[0].verdict is Verdict.ERROR and manager.calls == 0


def test_sandbox_failure_becomes_an_error_result_not_a_crash(root):
    task = make_task(root, "t")
    report = BenchmarkRunner(ScriptedManager(root), [task]).run([make_sub(root, "agent", task, "RAISE")])
    err = next(r for r in report.results if r.agent == "agent")
    assert err.verdict is Verdict.ERROR and "sandbox failure" in err.note


def test_leaked_containers_are_reported(root):
    task = make_task(root, "t")
    manager = ScriptedManager(root)
    manager.leaked = ["sbx-abc"]
    assert BenchmarkRunner(manager, [task]).run([]).leaked_containers == ["sbx-abc"]


def test_discover_submissions_ignores_unknown_tasks(root):
    task = make_task(root, "known")
    (root / "subs" / "agent" / "known").mkdir(parents=True)
    (root / "subs" / "agent" / "mystery").mkdir(parents=True)
    found = BenchmarkRunner(ScriptedManager(root), [task]).discover_submissions(root / "subs")
    assert [(s.agent, s.task_id) for s in found] == [("agent", "known")]


def test_no_workspace_directories_are_left_behind(root):
    task = make_task(root, "t")
    BenchmarkRunner(ScriptedManager(root), [task]).run([make_sub(root, "agent", task, "ok")])
    assert not list(root.glob("sbx-ws-*"))
