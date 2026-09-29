"""Benchmark Orchestrator: fan out (agent x task) runs into sandboxes and collect grades."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from sandbox import SandboxError, SandboxManager

from .grader import PYTEST_COMMAND, grade
from .models import GradeResult, Submission, Task, Verdict

REFERENCE_AGENT = "reference"


@dataclass
class SuiteReport:
    started_at: str
    wall_seconds: float
    budget_seconds: float
    results: list[GradeResult] = field(default_factory=list)
    invalid_tasks: list[str] = field(default_factory=list)  # reference failed -> tests not trustworthy
    leaked_containers: list[str] = field(default_factory=list)


class BenchmarkRunner:
    def __init__(
        self,
        manager: SandboxManager,
        tasks: Sequence[Task],
        workers: int = 4,
        suite_budget_seconds: float = 2400.0,  # 40 minutes: the hard ceiling for the whole suite
        include_reference: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.manager = manager
        self.tasks = {t.id: t for t in tasks}
        self.workers = max(1, workers)
        self.budget = suite_budget_seconds
        self.include_reference = include_reference
        self._clock = clock

    # -- discovery ---------------------------------------------------------------
    def discover_submissions(self, root: Path) -> list[Submission]:
        """Layout: <root>/<agent>/<task_id>/<entrypoint>. Unknown task ids are ignored."""
        found = []
        for agent_dir in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            for task_dir in sorted(p for p in agent_dir.iterdir() if p.is_dir()):
                if task_dir.name in self.tasks:
                    found.append(Submission(agent_dir.name, task_dir.name, task_dir))
        return found

    # -- execution ---------------------------------------------------------------
    def run(self, submissions: Sequence[Submission]) -> SuiteReport:
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = self._clock()
        deadline = t0 + self.budget
        report = SuiteReport(started_at=started_at, wall_seconds=0.0, budget_seconds=self.budget)

        reference_totals: dict[str, int] = {}
        if self.include_reference:
            refs = [Submission(REFERENCE_AGENT, t.id, t.reference_dir) for t in self.tasks.values()]
            for grade_result in self._map(refs, deadline, reference_totals={}):
                report.results.append(grade_result)
                if grade_result.verdict is Verdict.PASSED:
                    reference_totals[grade_result.task_id] = grade_result.tests_total
                else:
                    report.invalid_tasks.append(grade_result.task_id)
        else:
            reference_totals = {}

        runnable = [s for s in submissions if s.task_id not in report.invalid_tasks]
        report.results.extend(self._map(runnable, deadline, reference_totals))

        report.results.sort(key=lambda r: (r.agent != REFERENCE_AGENT, r.agent, r.task_id))
        report.wall_seconds = round(self._clock() - t0, 2)
        try:
            report.leaked_containers = self.manager.list_leaked()
        except SandboxError:
            report.leaked_containers = []
        return report

    def _map(self, submissions: Sequence[Submission], deadline: float, reference_totals: dict[str, int]) -> list[GradeResult]:
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._run_one, s, deadline, reference_totals.get(s.task_id)) for s in submissions]
            return [f.result() for f in futures]

    def _run_one(self, sub: Submission, deadline: float, reference_total: int | None) -> GradeResult:
        task = self.tasks[sub.task_id]
        if self._clock() >= deadline:
            return GradeResult(sub.agent, sub.task_id, Verdict.SKIPPED_BUDGET, note="suite time budget exhausted")

        entry = sub.path / task.entrypoint
        if not entry.is_file():
            return GradeResult(sub.agent, sub.task_id, Verdict.ERROR, note=f"missing {task.entrypoint}")

        policy = self.manager.policy
        if task.timeout_seconds:  # a task may tighten the ceiling, never loosen it
            policy = replace(policy, wall_clock_seconds=min(policy.wall_clock_seconds, task.timeout_seconds))
        # Never let one run outlive the suite budget.
        policy = replace(policy, wall_clock_seconds=min(policy.wall_clock_seconds, max(deadline - self._clock(), 1.0)))

        try:
            with self.manager.staged_workspace({task.entrypoint: entry, "tests": task.tests_dir}) as workspace:
                result = self.manager.run(workspace, PYTEST_COMMAND, policy=policy)
        except SandboxError as exc:
            return GradeResult(sub.agent, sub.task_id, Verdict.ERROR, note=f"sandbox failure: {exc}")
        return grade(result, sub.agent, sub.task_id, reference_total)
