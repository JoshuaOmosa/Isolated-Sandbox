"""Render a SuiteReport as JSON (machine-readable) and Markdown (human-readable)."""
from __future__ import annotations

import json
from collections import defaultdict

from .models import Verdict
from .runner import SuiteReport

_ICON = {
    Verdict.PASSED: "✅",
    Verdict.FAILED: "❌",
    Verdict.TIMEOUT: "⏱️",
    Verdict.OOM_KILLED: "💥",
    Verdict.ERROR: "⚠️",
    Verdict.SKIPPED_BUDGET: "⏭️",
}


def to_json(report: SuiteReport) -> str:
    payload = {
        "started_at": report.started_at,
        "wall_seconds": report.wall_seconds,
        "budget_seconds": report.budget_seconds,
        "invalid_tasks": report.invalid_tasks,
        "leaked_containers": report.leaked_containers,
        "results": [r.to_dict() for r in report.results],
    }
    return json.dumps(payload, indent=2) + "\n"


def to_markdown(report: SuiteReport) -> str:
    results = report.results
    agents = list(dict.fromkeys(r.agent for r in results))
    tasks = sorted({r.task_id for r in results})
    by_key = {(r.agent, r.task_id): r for r in results}

    lines = [
        "# Benchmark report",
        "",
        f"- Started: `{report.started_at}`",
        f"- Wall time: **{report.wall_seconds:.1f}s** of a {report.budget_seconds:.0f}s budget",
        f"- Runs: **{len(results)}** (each in its own ephemeral container)",
        f"- Leaked containers: **{len(report.leaked_containers)}**",
    ]
    if report.invalid_tasks:
        lines.append(f"- ⚠️ Invalid tasks (reference solution did not pass, agents not run): `{', '.join(report.invalid_tasks)}`")

    lines += ["", "## Verdict grid", "", "| agent | " + " | ".join(tasks) + " |", "|---|" + "---|" * len(tasks)]
    for agent in agents:
        cells = []
        for task in tasks:
            r = by_key.get((agent, task))
            cells.append("–" if r is None else f"{_ICON[r.verdict]} {r.verdict.value} ({r.tests_passed}/{r.tests_total})" if r.tests_total else f"{_ICON[r.verdict]} {r.verdict.value}")
        lines.append(f"| {agent} | " + " | ".join(cells) + " |")

    scores: dict[str, list[float]] = defaultdict(list)
    for r in results:
        scores[r.agent].append(r.score)
    lines += ["", "## Scores", "", "| agent | runs | passed | mean score |", "|---|---|---|---|"]
    for agent in agents:
        rs = [r for r in results if r.agent == agent]
        passed = sum(r.verdict is Verdict.PASSED for r in rs)
        mean = sum(scores[agent]) / len(scores[agent])
        lines.append(f"| {agent} | {len(rs)} | {passed} | {mean:.2f} |")

    problems = [r for r in results if r.verdict in (Verdict.ERROR, Verdict.TIMEOUT, Verdict.OOM_KILLED) or not r.removed]
    if problems:
        lines += ["", "## Notable runs", ""]
        for r in problems:
            suffix = "" if r.removed else " **(container not removed!)**"
            lines.append(f"- `{r.agent}` / `{r.task_id}`: {r.verdict.value} after {r.duration_seconds:.1f}s — {r.note}{suffix}")
    return "\n".join(lines) + "\n"
