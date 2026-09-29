"""Test doubles: a fake Docker client and a controllable clock (no daemon needed)."""
from __future__ import annotations

from typing import Any


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeContainer:
    def __init__(
        self,
        clock: FakeClock,
        *,
        polls_until_exit: int = 2,
        exit_code: int = 0,
        oom: bool = False,
        logs: bytes = b"",
        hangs: bool = False,
        remove_raises: Exception | None = None,
        name: str = "fake",
    ) -> None:
        self.clock = clock
        self.status = "created"
        self.attrs: dict[str, Any] = {"State": {}}
        self.name = name
        self._polls_left = polls_until_exit
        self._exit_code = exit_code
        self._oom = oom
        self._logs = logs
        self._hangs = hangs
        self._remove_raises = remove_raises
        self.killed = False
        self.removed_with: dict[str, Any] | None = None

    def start(self) -> None:
        self.status = "running"

    def reload(self) -> None:
        if self.status == "running" and not self._hangs:
            self._polls_left -= 1
            if self._polls_left <= 0:
                self._finish(self._exit_code)

    def kill(self) -> None:
        self.killed = True
        self._finish(137)

    def _finish(self, code: int) -> None:
        self.status = "exited"
        self.attrs = {"State": {"ExitCode": code, "OOMKilled": self._oom}}

    def logs(self, **_: Any) -> bytes:
        return self._logs

    def remove(self, force: bool = False, v: bool = False) -> None:
        if self._remove_raises:
            raise self._remove_raises
        self.removed_with = {"force": force, "v": v}


class FakeContainers:
    def __init__(self, factory) -> None:
        self._factory = factory
        self.created: list[dict[str, Any]] = []
        self.instances: list[FakeContainer] = []
        self.listed: list[FakeContainer] = []

    def create(self, **kwargs: Any) -> FakeContainer:
        self.created.append(kwargs)
        container = self._factory(kwargs)
        self.instances.append(container)
        return container

    def list(self, **_: Any) -> list[FakeContainer]:
        return self.listed


class FakeDockerClient:
    def __init__(self, factory) -> None:
        self.containers = FakeContainers(factory)
