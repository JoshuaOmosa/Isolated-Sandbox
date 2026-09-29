from pathlib import Path

import docker.errors
import pytest

from sandbox import SandboxError, SandboxManager, SandboxPolicy

from .fakes import FakeClock, FakeContainer, FakeDockerClient

CMD = ["python", "-m", "pytest"]


def make_manager(clock, policy=None, **container_kwargs):
    client = FakeDockerClient(lambda kw: FakeContainer(clock, name=kw["name"], **container_kwargs))
    manager = SandboxManager(policy or SandboxPolicy(wall_clock_seconds=5), client=client, clock=clock, sleep=clock.sleep)
    return manager, client


def test_normal_run_is_captured_and_container_removed():
    clock = FakeClock()
    manager, client = make_manager(clock, exit_code=0, logs=b"3 passed in 0.01s")
    result = manager.run(Path("/tmp/ws"), CMD)

    assert (result.exit_code, result.timed_out, result.oom_killed) == (0, False, False)
    assert "3 passed" in result.logs
    assert result.removed is True
    container = client.containers.instances[0]
    assert container.removed_with == {"force": True, "v": True}
    assert container.killed is False


def test_every_run_gets_a_fresh_uniquely_named_container():
    clock = FakeClock()
    manager, client = make_manager(clock)
    manager.run(Path("/tmp/ws"), CMD)
    manager.run(Path("/tmp/ws"), CMD)
    names = [kw["name"] for kw in client.containers.created]
    assert len(set(names)) == 2 and all(n.startswith("sbx-") for n in names)


def test_hard_ceiling_kills_runaway_container_and_still_removes_it():
    clock = FakeClock()
    manager, client = make_manager(clock, hangs=True)
    result = manager.run(Path("/tmp/ws"), CMD)

    container = client.containers.instances[0]
    assert result.timed_out is True
    assert container.killed is True
    assert container.removed_with is not None
    assert 5 <= result.duration_seconds < 6  # ceiling honoured, no runaway waiting


def test_oom_kill_is_reported():
    clock = FakeClock()
    manager, _ = make_manager(clock, exit_code=137, oom=True)
    assert manager.run(Path("/tmp/ws"), CMD).oom_killed is True


def test_removal_failure_is_surfaced_as_a_leak_not_swallowed():
    clock = FakeClock()
    manager, _ = make_manager(clock, remove_raises=RuntimeError("daemon hiccup"))
    result = manager.run(Path("/tmp/ws"), CMD)
    assert result.removed is False


def test_already_gone_container_counts_as_removed():
    clock = FakeClock()
    manager, _ = make_manager(clock, remove_raises=docker.errors.NotFound("gone"))
    assert manager.run(Path("/tmp/ws"), CMD).removed is True


def test_long_logs_are_truncated_keeping_the_tail():
    clock = FakeClock()
    policy = SandboxPolicy(wall_clock_seconds=5, max_log_bytes=100)
    manager, _ = make_manager(clock, policy, logs=b"x" * 5000 + b"THE-END")
    logs = manager.run(Path("/tmp/ws"), CMD).logs
    assert logs.endswith("THE-END") and len(logs) < 200 and "truncated" in logs


def test_missing_image_becomes_a_helpful_sandbox_error():
    clock = FakeClock()

    def factory(_):
        raise docker.errors.ImageNotFound("nope")

    manager = SandboxManager(SandboxPolicy(), client=FakeDockerClient(factory), clock=clock, sleep=clock.sleep)
    with pytest.raises(SandboxError, match="make image"):
        manager.run(Path("/tmp/ws"), CMD)


def test_run_uses_the_policy_it_is_given():
    clock = FakeClock()
    manager, client = make_manager(clock)
    manager.run(Path("/tmp/ws"), CMD, policy=SandboxPolicy(wall_clock_seconds=5, memory="64m"))
    assert client.containers.created[0]["mem_limit"] == "64m"


def test_cleanup_orphans_removes_every_labelled_container():
    clock = FakeClock()
    manager, client = make_manager(clock)
    client.containers.listed = [FakeContainer(clock, name="a"), FakeContainer(clock, name="b")]
    assert manager.cleanup_orphans() == 2
    assert all(c.removed_with for c in client.containers.listed)
    assert manager.list_leaked() == ["a", "b"]


def test_staged_workspace_copies_inputs_makes_them_readable_and_cleans_up(tmp_path):
    src = tmp_path / "solution.py"
    src.write_text("x = 1\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_task.py").write_text("def test_x(): pass\n")
    src.chmod(0o600)  # unreadable to 'other' on purpose

    manager = SandboxManager(client=object(), scratch_root=tmp_path)
    with manager.staged_workspace({"solution.py": src, "tests": tests}) as ws:
        assert (ws / "solution.py").read_text() == "x = 1\n"
        assert (ws / "tests" / "test_task.py").exists()
        assert (ws / "solution.py").stat().st_mode & 0o004  # world-readable for the unprivileged uid
        assert ws.stat().st_mode & 0o005 == 0o005
    assert not ws.exists()


@pytest.mark.parametrize("bad", ["../escape.py", "/etc/passwd", "a/../../b"])
def test_staged_workspace_rejects_path_traversal(tmp_path, bad):
    src = tmp_path / "f.py"
    src.write_text("")
    manager = SandboxManager(client=object(), scratch_root=tmp_path)
    with pytest.raises(ValueError):
        with manager.staged_workspace({bad: src}):
            pass
