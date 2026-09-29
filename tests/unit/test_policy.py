import json
from dataclasses import replace
from pathlib import Path

import pytest

from sandbox import SandboxPolicy
from sandbox.policy import LABEL_KEY

WS = Path("/tmp/ws")
CMD = ["python", "-m", "pytest"]


@pytest.fixture()
def kwargs():
    return SandboxPolicy().container_kwargs(WS, CMD, "sbx-test")


def test_network_is_disabled(kwargs):
    assert kwargs["network_mode"] == "none"


def test_root_filesystem_is_read_only_and_only_tmp_is_writable(kwargs):
    assert kwargs["read_only"] is True
    assert list(kwargs["tmpfs"]) == ["/tmp"]
    options = kwargs["tmpfs"]["/tmp"].split(",")
    assert {"noexec", "nosuid", "nodev"} <= set(options)


def test_workspace_is_mounted_read_only(kwargs):
    assert kwargs["volumes"] == {str(WS): {"bind": "/workspace", "mode": "ro"}}


def test_no_privileges(kwargs):
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["privileged"] is False
    assert "no-new-privileges" in kwargs["security_opt"]
    assert kwargs["ipc_mode"] == "private"
    assert kwargs["user"].split(":")[0] not in ("0", "root", "")


def test_seccomp_profile_is_embedded_as_valid_json(kwargs):
    entries = [o for o in kwargs["security_opt"] if o.startswith("seccomp=")]
    assert len(entries) == 1
    profile = json.loads(entries[0].removeprefix("seccomp="))
    assert profile["defaultAction"] != "SCMP_ACT_ALLOW"
    assert "unconfined" not in entries[0]


def test_resource_ceilings(kwargs):
    assert kwargs["mem_limit"] == kwargs["memswap_limit"]  # swap disabled
    assert kwargs["pids_limit"] == 64
    assert kwargs["nano_cpus"] == 1_000_000_000
    assert any(u["name"] == "core" and u["hard"] == 0 for u in kwargs["ulimits"])


def test_container_is_labelled_for_orphan_cleanup(kwargs):
    assert kwargs["labels"] == {LABEL_KEY: "1"}


def test_host_sockets_are_never_mounted(kwargs):
    assert not any("docker.sock" in path for path in kwargs["volumes"])


def test_environment_is_minimal(kwargs):
    assert set(kwargs["environment"]) == {"PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONPATH", "HOME"}


def test_custom_runtime_is_passed_through_only_when_set():
    assert "runtime" not in SandboxPolicy().container_kwargs(WS, CMD, "n")
    assert replace(SandboxPolicy(), runtime="runsc").container_kwargs(WS, CMD, "n")["runtime"] == "runsc"


def test_docker_sdk_accepts_the_generated_arguments(kwargs):
    """Feed the arguments through docker-py's own builder: catches typos without a daemon."""
    containers = pytest.importorskip("docker.models.containers")
    builder = getattr(containers, "_create_container_args", None)
    if builder is None:
        pytest.skip("docker-py internals changed")
    built = builder({**kwargs, "version": "1.44"})
    host = built["host_config"]
    assert host["NetworkMode"] == "none"
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"]
    assert host["PidsLimit"] == 64
    assert host["Memory"] == host["MemorySwap"]
    assert host["Binds"] == [f"{WS}:/workspace:ro"]
