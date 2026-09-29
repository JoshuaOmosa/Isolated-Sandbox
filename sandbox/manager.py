"""Sandbox Manager: creates, supervises and destroys ephemeral containers.

One `SandboxManager.run` call == one container. The container is created from an
immutable image, started, watched against a wall-clock ceiling, force-killed on
overrun, and *always* removed together with its anonymous volumes. Nothing
survives between runs, which is what rules out state contamination.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .policy import LABEL_KEY, SandboxPolicy

_STOPPED = {"exited", "dead"}


class SandboxError(RuntimeError):
    """The sandbox itself failed (daemon unreachable, image missing, ...), not the code inside it."""


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int | None
    logs: str
    duration_seconds: float
    timed_out: bool
    oom_killed: bool
    container_name: str
    removed: bool  # False means the container could not be destroyed -> a leak


class SandboxManager:
    def __init__(
        self,
        policy: SandboxPolicy | None = None,
        client: Any = None,
        scratch_root: Path | None = None,
        poll_interval: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy or SandboxPolicy()
        self._client = client
        self.scratch_root = Path(scratch_root) if scratch_root else None
        self.poll_interval = poll_interval
        self._clock = clock
        self._sleep = sleep

    # -- docker plumbing --------------------------------------------------------
    @property
    def client(self) -> Any:
        if self._client is None:
            import docker  # imported lazily so unit tests need no daemon

            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:  # noqa: BLE001 - surface any connectivity problem uniformly
                raise SandboxError(f"cannot reach the Docker daemon: {exc}") from exc
        return self._client

    def _docker_errors(self):
        import docker.errors as errors

        return errors

    # -- workspace staging ------------------------------------------------------
    @contextmanager
    def staged_workspace(self, files: Mapping[str, Path]) -> Iterator[Path]:
        """Copy `files` (dest name -> source path) into a fresh, world-readable temp dir.

        The directory is mounted read-only into the container. A brand-new copy per
        run means a submission can never see or alter another run's inputs.
        """
        root = Path(tempfile.mkdtemp(prefix="sbx-ws-", dir=self.scratch_root))
        try:
            for dest, source in files.items():
                dest_path = Path(dest)
                if dest_path.is_absolute() or ".." in dest_path.parts:
                    raise ValueError(f"unsafe workspace destination: {dest!r}")
                target = root / dest_path
                target.parent.mkdir(parents=True, exist_ok=True)
                source = Path(source)
                if source.is_dir():
                    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copyfile(source, target)
            _make_world_readable(root)
            yield root
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # -- the run ----------------------------------------------------------------
    def run(
        self,
        workspace: Path,
        command: Sequence[str],
        policy: SandboxPolicy | None = None,
    ) -> ExecutionResult:
        policy = policy or self.policy
        name = f"sbx-{uuid.uuid4().hex[:12]}"
        errors = self._docker_errors()
        container = None
        timed_out = False
        started = self._clock()
        try:
            try:
                container = self.client.containers.create(**policy.container_kwargs(workspace, command, name))
                container.start()
            except errors.ImageNotFound as exc:
                raise SandboxError(f"image {policy.image!r} not found; build it with `make image`") from exc
            except errors.APIError as exc:
                raise SandboxError(f"docker refused to start the sandbox: {exc}") from exc

            deadline = started + policy.wall_clock_seconds
            while True:
                container.reload()
                if container.status in _STOPPED:
                    break
                if self._clock() >= deadline:
                    timed_out = True
                    _safe(container.kill)
                    self._wait_stopped(container, grace=10.0)
                    break
                self._sleep(self.poll_interval)

            duration = self._clock() - started
            container.reload()
            state = container.attrs.get("State", {})
            raw = container.logs(stdout=True, stderr=True, tail=500)
            logs = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if len(logs) > policy.max_log_bytes:
                logs = "[log truncated]\n" + logs[-policy.max_log_bytes :]
            exit_code = state.get("ExitCode")
            oom_killed = bool(state.get("OOMKilled"))
        finally:
            removed = True
            if container is not None:
                removed = self._destroy(container)

        return ExecutionResult(
            exit_code=exit_code,
            logs=logs,
            duration_seconds=round(duration, 3),
            timed_out=timed_out,
            oom_killed=oom_killed,
            container_name=name,
            removed=removed,
        )

    def _wait_stopped(self, container: Any, grace: float) -> None:
        deadline = self._clock() + grace
        while self._clock() < deadline:
            try:
                container.reload()
            except Exception:  # noqa: BLE001
                return
            if container.status in _STOPPED:
                return
            self._sleep(0.05)

    def _destroy(self, container: Any) -> bool:
        errors = self._docker_errors()
        try:
            container.remove(force=True, v=True)
            return True
        except errors.NotFound:
            return True
        except Exception:  # noqa: BLE001 - never let cleanup mask the real result
            return False

    # -- housekeeping -----------------------------------------------------------
    def list_leaked(self) -> list[str]:
        """Names of containers created by this framework that still exist."""
        found = self.client.containers.list(all=True, filters={"label": f"{LABEL_KEY}=1"})
        return sorted(c.name for c in found)

    def cleanup_orphans(self) -> int:
        """Force-remove any framework container left behind (e.g. after a crash)."""
        removed = 0
        for container in self.client.containers.list(all=True, filters={"label": f"{LABEL_KEY}=1"}):
            if self._destroy(container):
                removed += 1
        return removed


def _safe(fn: Callable[[], Any]) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - the container may already be gone
        pass


def _make_world_readable(root: Path) -> None:
    """The container runs as an unprivileged uid, so inputs must be readable by 'other'."""
    os.chmod(root, 0o755)
    for path in root.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
