"""Declarative isolation policy for a single sandbox run.

Every guardrail lives in one place so it can be reviewed, unit-tested without a
Docker daemon, and printed in the README. `SandboxPolicy.container_kwargs`
translates the policy into arguments for `docker.containers.create`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

SECCOMP_PATH = Path(__file__).with_name("seccomp.json")
LABEL_KEY = "sandbox-benchmark"
WORKSPACE_MOUNT = "/workspace"
SCRATCH_MOUNT = "/tmp"


@dataclass(frozen=True)
class SandboxPolicy:
    """Resource ceilings and isolation switches for one ephemeral container."""

    image: str = "sandbox-runner:latest"
    memory: str = "256m"  # hard cap; swap is pinned to the same value (no swap)
    cpus: float = 1.0
    pids_limit: int = 64  # fork-bomb ceiling
    wall_clock_seconds: float = 30.0  # hard execution ceiling per run
    tmpfs_size: str = "32m"  # the only writable location besides nothing else
    max_log_bytes: int = 64 * 1024
    user: str = "65534:65534"  # nobody:nogroup, never root
    runtime: str | None = None  # e.g. "runsc" (gVisor) for a stronger boundary
    seccomp_profile: Path = SECCOMP_PATH
    env: Mapping[str, str] = field(default_factory=dict)

    def seccomp_json(self) -> str:
        """Return the seccomp profile as compact JSON (the Docker API takes contents, not a path)."""
        return json.dumps(json.loads(Path(self.seccomp_profile).read_text()), separators=(",", ":"))

    def container_kwargs(self, workspace: Path, command: Sequence[str], name: str) -> dict[str, Any]:
        environment = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": WORKSPACE_MOUNT,
            "HOME": SCRATCH_MOUNT,
            **self.env,
        }
        kwargs: dict[str, Any] = {
            "image": self.image,
            "command": list(command),
            "name": name,
            "detach": True,
            "working_dir": WORKSPACE_MOUNT,
            "user": self.user,
            "environment": environment,
            # --- isolation ---------------------------------------------------
            "network_mode": "none",  # loopback only, no external interfaces
            "read_only": True,  # immutable root filesystem
            "tmpfs": {SCRATCH_MOUNT: f"rw,noexec,nosuid,nodev,size={self.tmpfs_size}"},
            "volumes": {str(workspace): {"bind": WORKSPACE_MOUNT, "mode": "ro"}},
            "cap_drop": ["ALL"],
            "privileged": False,
            "ipc_mode": "private",
            "init": True,  # reap zombies so a fork storm cannot hide behind them
            "security_opt": ["no-new-privileges", f"seccomp={self.seccomp_json()}"],
            # --- resource ceilings --------------------------------------------
            "mem_limit": self.memory,
            "memswap_limit": self.memory,
            "nano_cpus": int(self.cpus * 1_000_000_000),
            "pids_limit": self.pids_limit,
            "ulimits": [
                {"name": "nofile", "soft": 256, "hard": 256},
                {"name": "core", "soft": 0, "hard": 0},
                {"name": "fsize", "soft": 16 * 1024 * 1024, "hard": 16 * 1024 * 1024},
            ],
            "log_config": {"type": "json-file", "config": {"max-size": "1m", "max-file": "1"}},
            # --- bookkeeping --------------------------------------------------
            "labels": {LABEL_KEY: "1"},
        }
        if self.runtime:
            kwargs["runtime"] = self.runtime
        return kwargs
