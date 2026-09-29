from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Verdict(str, Enum):
    PASSED = "PASSED"  # every test passed and the harness output is self-consistent
    FAILED = "FAILED"  # ran to completion, some tests failed
    TIMEOUT = "TIMEOUT"  # hit the wall-clock ceiling and was killed
    OOM_KILLED = "OOM_KILLED"  # exceeded the memory cap
    ERROR = "ERROR"  # crashed, produced no trustworthy result, or the sandbox itself failed
    SKIPPED_BUDGET = "SKIPPED_BUDGET"  # suite budget exhausted before this run started


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    prompt: str
    path: Path
    entrypoint: str = "solution.py"
    timeout_seconds: float | None = None

    @property
    def tests_dir(self) -> Path:
        return self.path / "tests"

    @property
    def reference_dir(self) -> Path:
        return self.path / "reference"


@dataclass(frozen=True)
class Submission:
    agent: str
    task_id: str
    path: Path  # directory containing the agent's entrypoint file


@dataclass
class GradeResult:
    agent: str
    task_id: str
    verdict: Verdict
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    score: float = 0.0  # tests_passed / tests the reference passes, capped at 1.0
    duration_seconds: float = 0.0
    exit_code: int | None = None
    container: str | None = None
    removed: bool = True
    note: str = ""
    log_tail: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        return data
