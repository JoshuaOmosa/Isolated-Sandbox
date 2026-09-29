import subprocess
import sys
from pathlib import Path

from orchestrator.probing import ProbeReport, parse_probe_output, run_probes
from sandbox import ExecutionResult, SandboxManager, SandboxPolicy

ROOT = Path(__file__).resolve().parents[2]

LOGS = (
    'PROBE {"probe": "network_egress", "contained": true, "detail": "refused"}\n'
    'noise line\n'
    'PROBE {"probe": "rootfs_write", "contained": false, "detail": "wrote"}\n'
    'PROBE {"probe": "memory_limit_applied", "contained": null, "detail": "unreadable"}\n'
    "PROBE {broken json\n"
    "PROBES_DONE\n"
)


def test_parse_probe_output_ignores_noise_and_bad_json():
    probes, finished = parse_probe_output(LOGS)
    assert [p["probe"] for p in probes] == ["network_egress", "rootfs_write", "memory_limit_applied"]
    assert finished is True


def test_report_ok_requires_completion_and_no_breach():
    ok = ProbeReport(probes=[{"probe": "a", "contained": True}, {"probe": "b", "contained": None}], finished=True)
    assert ok.ok and len(ok.unverified) == 1
    assert not ProbeReport(probes=[{"probe": "a", "contained": False}], finished=True).ok
    assert not ProbeReport(probes=[{"probe": "a", "contained": True}], finished=False).ok
    assert not ProbeReport(probes=[], finished=True).ok


def test_run_probes_opts_in_via_env_and_gets_a_longer_ceiling(tmp_path):
    captured = {}

    class Capturing(SandboxManager):
        def run(self, workspace, command, policy=None):
            captured["policy"], captured["command"] = policy, list(command)
            captured["staged"] = sorted(p.name for p in workspace.iterdir())
            return ExecutionResult(0, LOGS, 1.0, False, False, "sbx-probe", True)

    manager = Capturing(SandboxPolicy(wall_clock_seconds=5), client=object(), scratch_root=tmp_path)
    report = run_probes(manager, ROOT / "probes")

    assert captured["policy"].env["SANDBOX_PROBES"] == "1"
    assert captured["policy"].wall_clock_seconds >= 60
    assert captured["staged"] == ["escape_probes.py"]
    assert len(report.breaches) == 1 and report.finished


def test_probe_script_refuses_to_run_outside_the_sandbox():
    """Regression: the probes attempt mounts and /proc writes, so they must never run on a host."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "SANDBOX_PROBES"}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "probes" / "escape_probes.py")],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 2
    assert "PROBE " not in proc.stdout
    assert "refusing to run" in proc.stderr


def _load_probes():
    import importlib.util

    spec = importlib.util.spec_from_file_location("escape_probes", ROOT / "probes" / "escape_probes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # safe: probes only run from main(), which is guarded
    return module


def test_public_image_gpg_key_is_not_reported_as_a_leaked_secret():
    """Regression: the python base image ships GPG_KEY (a public key fingerprint)."""
    probes = _load_probes()
    assert probes.suspicious_variables({"GPG_KEY": "7169605F62C751356D054A26A821E680E5FA6305", "PATH": "/usr/bin"}) == []


def test_real_looking_secrets_are_still_flagged():
    probes = _load_probes()
    env = {"AWS_SECRET_ACCESS_KEY": "x", "GITHUB_TOKEN": "y", "DB_PASSWORD": "z", "GPG_KEY": "pub", "HOME": "/tmp"}
    assert probes.suspicious_variables(env) == ["AWS_SECRET_ACCESS_KEY", "DB_PASSWORD", "GITHUB_TOKEN"]