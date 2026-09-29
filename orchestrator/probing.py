"""Run the escape-attempt battery inside a sandbox and interpret the result."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sandbox import SandboxManager

PROBE_PREFIX = "PROBE "
DONE_MARKER = "PROBES_DONE"


@dataclass
class ProbeReport:
    probes: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False
    container: str = ""
    timed_out: bool = False

    @property
    def breaches(self) -> list[dict[str, Any]]:
        return [p for p in self.probes if p.get("contained") is False]

    @property
    def unverified(self) -> list[dict[str, Any]]:
        return [p for p in self.probes if p.get("contained") is None]

    @property
    def ok(self) -> bool:
        """Every probe ran to completion and none succeeded."""
        return self.finished and bool(self.probes) and not self.breaches


def parse_probe_output(logs: str) -> tuple[list[dict[str, Any]], bool]:
    probes, finished = [], False
    for line in logs.splitlines():
        line = line.strip()
        if line.startswith(PROBE_PREFIX):
            try:
                probes.append(json.loads(line[len(PROBE_PREFIX):]))
            except json.JSONDecodeError:
                continue
        elif line == DONE_MARKER:
            finished = True
    return probes, finished


def run_probes(manager: SandboxManager, probes_dir: Path) -> ProbeReport:
    # SANDBOX_PROBES=1 is the opt-in the script requires before it will attempt anything.
    policy = replace(
        manager.policy,
        wall_clock_seconds=max(manager.policy.wall_clock_seconds, 60.0),
        env={**manager.policy.env, "SANDBOX_PROBES": "1"},
    )
    with manager.staged_workspace({"escape_probes.py": Path(probes_dir) / "escape_probes.py"}) as workspace:
        result = manager.run(workspace, ["python", "/workspace/escape_probes.py"], policy=policy)
    probes, finished = parse_probe_output(result.logs)
    return ProbeReport(probes=probes, finished=finished, container=result.container_name, timed_out=result.timed_out)
