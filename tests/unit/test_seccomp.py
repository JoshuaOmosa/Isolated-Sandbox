import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = json.loads((ROOT / "sandbox" / "seccomp.json").read_text())

MUST_NOT_BE_ALLOWED = {
    "ptrace", "process_vm_readv", "process_vm_writev", "mount", "umount2", "unshare", "setns",
    "keyctl", "bpf", "perf_event_open", "userfaultfd", "reboot", "kexec_load", "init_module",
    "open_by_handle_at", "memfd_create", "pivot_root", "chroot", "swapon",
}


def _allowed_names():
    names = set()
    for rule in PROFILE["syscalls"]:
        if rule["action"] == "SCMP_ACT_ALLOW":
            names |= set(rule["names"])
    return names


def test_profile_is_an_allowlist():
    assert PROFILE["defaultAction"] == "SCMP_ACT_ERRNO"


def test_dangerous_syscalls_are_not_allowed():
    assert not (MUST_NOT_BE_ALLOWED & _allowed_names())


def test_no_capability_gated_rules_remain():
    assert not [r for r in PROFILE["syscalls"] if "caps" in r.get("includes", {})]


def test_socket_is_restricted_to_af_unix():
    socket_rules = [r for r in PROFILE["syscalls"] if "socket" in r["names"]]
    assert len(socket_rules) == 1
    (arg,) = socket_rules[0]["args"]
    assert (arg["index"], arg["value"], arg["op"]) == (0, 1, "SCMP_CMP_EQ")


def test_clone_stays_namespace_restricted():
    clone_rules = [r for r in PROFILE["syscalls"] if r["names"] == ["clone"]]
    assert clone_rules and all(r["args"][0]["op"] == "SCMP_CMP_MASKED_EQ" for r in clone_rules)


def test_python_and_pytest_basics_remain_allowed():
    for name in ("read", "write", "openat", "mmap", "futex", "execve", "fork", "pipe2", "getrandom", "wait4"):
        assert name in _allowed_names(), name


def test_committed_profile_matches_generator_output():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_seccomp.py"), "--check"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
