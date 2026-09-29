"""Escape-attempt battery. Runs INSIDE the sandbox and reports what was contained.

WARNING: these probes really attempt privileged operations (mount, writing to
/proc/sys, writing to the root filesystem, fork storms). In a correctly configured
sandbox they all fail. Outside one, running them as root CAN modify the machine, so
this script refuses to start unless SANDBOX_PROBES=1 is set, which only
`python -m orchestrator probe` does (from inside the locked-down container).
Never run it directly on a host or a dev container.

Each probe prints one line:  PROBE {"probe": ..., "contained": true|false|null, "detail": ...}

`contained: true`  the attempt was refused (good)
`contained: false` the attempt succeeded (the sandbox is misconfigured)
`contained: null`  the platform did not expose enough information to tell

Where an attempt does succeed, the probe undoes it and keeps its footprint minimal.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time

PROBES = []


def probe(fn):
    PROBES.append(fn)
    return fn


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def _status_field(name: str) -> str | None:
    try:
        for line in open("/proc/self/status"):
            if line.startswith(name + ":"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _mount_options(mountpoint: str) -> str | None:
    try:
        for line in open("/proc/self/mounts"):
            fields = line.split()
            if len(fields) >= 4 and fields[1] == mountpoint:
                return fields[3]
    except OSError:
        pass
    return None


@probe
def non_root_user():
    uid = os.geteuid()
    return uid != 0, f"euid={uid}"


@probe
def capabilities_dropped():
    cap_eff = _status_field("CapEff")
    if cap_eff is None:
        return None, "CapEff not readable"
    return int(cap_eff, 16) == 0, f"CapEff={cap_eff}"


@probe
def no_new_privileges():
    value = _status_field("NoNewPrivs")
    return (value == "1") if value is not None else None, f"NoNewPrivs={value}"


@probe
def seccomp_filter_active():
    value = _status_field("Seccomp")  # 2 == filter mode
    return (value == "2") if value is not None else None, f"Seccomp={value}"


@probe
def network_egress():
    try:
        conn = socket.create_connection(("1.1.1.1", 53), timeout=2)
        conn.close()
        return False, "connected to 1.1.1.1:53"
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}: {exc}"


@probe
def dns_resolution():
    try:
        socket.getaddrinfo("example.com", 80)
        return False, "resolved example.com"
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}"


@probe
def rootfs_read_only():
    options = _mount_options("/")
    if options is None:
        return None, "cannot read mount table"
    return options.split(",")[0] == "ro", f"/ mounted with '{options.split(',')[0]}'"


@probe
def rootfs_write():
    target = "/etc/sandbox-probe"
    try:
        with open(target, "w") as handle:
            handle.write("probe")
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}"
    os.remove(target)  # undo: the write should never have worked
    return False, "wrote /etc/sandbox-probe"


@probe
def workspace_write():
    target = "/workspace/sandbox-probe"
    try:
        with open(target, "w") as handle:
            handle.write("probe")
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}"
    os.remove(target)  # undo
    return False, "wrote into /workspace"


@probe
def tmp_is_noexec():
    path = "/tmp/probe.sh"
    try:
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\necho executed\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        completed = subprocess.run([path], capture_output=True, timeout=5)
        return False, f"executed from /tmp (rc={completed.returncode})"
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"refused: {exc.__class__.__name__}"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@probe
def syscall_mount():
    libc = _libc()
    target = "/tmp/probe-mnt"  # a throwaway directory, never a real mount point
    os.makedirs(target, exist_ok=True)
    rc = libc.mount(b"none", target.encode(), b"tmpfs", 0, None)
    err = ctypes.get_errno()
    if rc == 0:
        libc.umount(target.encode())  # undo
    try:
        os.rmdir(target)
    except OSError:
        pass
    return rc != 0, f"mount() rc={rc} errno={err}"


@probe
def syscall_unshare_userns():
    libc = _libc()
    rc = libc.unshare(0x10000000)  # CLONE_NEWUSER
    err = ctypes.get_errno()
    return rc != 0, f"unshare(CLONE_NEWUSER) rc={rc} errno={err}"


@probe
def syscall_ptrace():
    libc = _libc()
    libc.ptrace.restype = ctypes.c_long
    rc = libc.ptrace(16, 1, None, None)  # PTRACE_ATTACH to pid 1
    err = ctypes.get_errno()
    return rc != 0, f"ptrace(ATTACH, 1) rc={rc} errno={err}"


@probe
def syscall_memfd_create():
    try:
        fd = os.memfd_create("probe")
        os.close(fd)
        return False, "memfd_create succeeded (fileless exec possible)"
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}"


@probe
def socket_family_restricted():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.close()
        return False, "AF_INET socket created"
    except OSError as exc:
        return True, f"AF_INET refused: {exc.__class__.__name__}"


@probe
def proc_sys_write():
    path = "/proc/sys/kernel/hostname"
    try:
        current = open(path).read()
        with open(path, "w") as handle:
            handle.write(current.strip())  # rewrite the *same* value: a no-op if it works
        return False, "wrote /proc/sys/kernel/hostname"
    except OSError as exc:
        return True, f"refused: {exc.__class__.__name__}"


@probe
def docker_socket_absent():
    present = [p for p in ("/var/run/docker.sock", "/run/docker.sock") if os.path.exists(p)]
    return not present, f"present={present}"


@probe
def environment_clean():
    pattern = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AWS_|GITHUB_", re.I)
    leaked = sorted(name for name in os.environ if pattern.search(name))
    return not leaked, f"suspicious variables: {leaked}"


@probe
def pid_namespace_isolated():
    visible = len([d for d in os.listdir("/proc") if d.isdigit()])
    return visible < 20, f"{visible} processes visible (a host namespace shows hundreds)"


@probe
def memory_limit_applied():
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            value = open(path).read().strip()
        except OSError:
            continue
        finite = value != "max" and value.isdigit() and int(value) < 2**50
        return finite, f"{path}={value}"
    return None, "cgroup memory file not readable"


@probe
def pid_limit_stops_fork_storm():
    children, refused = [], False
    for _ in range(512):
        try:
            pid = os.fork()
        except OSError:
            refused = True
            break
        if pid == 0:
            time.sleep(2)
            os._exit(0)
        children.append(pid)
    for pid in children:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass
    return refused, f"fork refused after {len(children)} children" if refused else "512 forks succeeded"


def main() -> int:
    if os.environ.get("SANDBOX_PROBES") != "1":
        print(
            "refusing to run: these probes attempt privileged operations and must only run "
            "inside the sandbox (use `python -m orchestrator probe`).",
            file=sys.stderr,
        )
        return 2
    for fn in PROBES:
        try:
            contained, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a crashing probe is reported, not fatal
            contained, detail = None, f"probe crashed: {exc.__class__.__name__}: {exc}"
        print("PROBE " + json.dumps({"probe": fn.__name__, "contained": contained, "detail": detail}), flush=True)
    print("PROBES_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
