"""Task discovery. A task is a directory:

    tasks/<id>/
      task.json          id, title, prompt, optional entrypoint / timeout_seconds
      tests/test_task.py hidden tests that define correct behaviour
      reference/<entry>  known-good solution used to calibrate the tests
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Task


def load_task(path: Path) -> Task:
    meta = json.loads((path / "task.json").read_text())
    entrypoint = meta.get("entrypoint", "solution.py")
    if "/" in entrypoint or "\\" in entrypoint or entrypoint.startswith("."):
        raise ValueError(f"{path.name}: entrypoint must be a plain file name, got {entrypoint!r}")
    task = Task(
        id=meta["id"],
        title=meta.get("title", meta["id"]),
        prompt=meta.get("prompt", ""),
        path=path,
        entrypoint=entrypoint,
        timeout_seconds=meta.get("timeout_seconds"),
    )
    if not (task.tests_dir / "test_task.py").is_file():
        raise FileNotFoundError(f"{task.id}: missing tests/test_task.py")
    if not (task.reference_dir / entrypoint).is_file():
        raise FileNotFoundError(f"{task.id}: missing reference/{entrypoint}")
    return task


def discover_tasks(root: Path) -> list[Task]:
    tasks = [load_task(p) for p in sorted(Path(root).iterdir()) if (p / "task.json").is_file()]
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids found")
    return tasks
