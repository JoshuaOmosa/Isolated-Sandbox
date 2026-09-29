"""Integration tests need a Docker daemon and the runner image (`make image`)."""
import os

import pytest

from sandbox import SandboxManager, SandboxPolicy

IMAGE = os.environ.get("SANDBOX_IMAGE", "sandbox-runner:latest")


@pytest.fixture(scope="session")
def manager():
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(IMAGE)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker or image {IMAGE!r} unavailable ({exc}); run `make image`")
    return SandboxManager(SandboxPolicy(image=IMAGE, wall_clock_seconds=10), client=client)
