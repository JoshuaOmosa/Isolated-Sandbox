#!/usr/bin/env python3
"""Derive the sandbox seccomp profile from Docker's upstream default profile.

The upstream profile (moby/profiles, seccomp/default.json) is an allowlist tuned
for general-purpose containers. Untrusted, agent-generated code needs far less,
so this script tightens it deterministically:

1. Drop every rule gated on a capability (`includes.caps`). The sandbox runs with
   all capabilities dropped, so these rules are dead weight at best and an
   accidental grant at worst.
2. Restrict `socket()` to AF_UNIX. Network is already disabled at the namespace
   level; this removes AF_INET/AF_INET6/AF_NETLINK/AF_PACKET/AF_ALG kernel
   attack surface as a second, independent layer.
3. Remove syscalls that enable process introspection, fileless execution or
   handle-based file access (see REMOVED_SYSCALLS).

Usage:
    python scripts/generate_seccomp.py            # rewrite sandbox/seccomp.json
    python scripts/generate_seccomp.py --check    # exit 1 if the file is stale
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "sandbox" / "upstream" / "moby-default.seccomp.json"
OUTPUT = ROOT / "sandbox" / "seccomp.json"

AF_UNIX = 1

# Syscalls removed from every ALLOW rule, with the reason each is unwanted.
REMOVED_SYSCALLS = {
    "ptrace": "process introspection / tracing of sibling processes",
    "process_vm_readv": "cross-process memory read",
    "process_vm_writev": "cross-process memory write",
    "kcmp": "process comparison / info leak",
    "pidfd_getfd": "steal file descriptors from other processes",
    "process_madvise": "cross-process memory advice",
    "memfd_create": "fileless execution would bypass the noexec tmpfs",
    "name_to_handle_at": "prerequisite for open_by_handle_at style escapes",
    "open_by_handle_at": "handle-based file access ('Shocker' class escapes)",
}


def build(upstream: dict) -> dict:
    profile = copy.deepcopy(upstream)
    rules = []
    for rule in profile["syscalls"]:
        includes = rule.get("includes", {})
        if "caps" in includes:
            continue  # capability-gated rules: unreachable with cap_drop=ALL
        if rule["names"] == ["socket"]:
            continue  # replaced by the single AF_UNIX rule below
        rule["names"] = [n for n in rule["names"] if n not in REMOVED_SYSCALLS]
        if rule["names"]:
            rules.append(rule)
    rules.append(
        {
            "names": ["socket"],
            "action": "SCMP_ACT_ALLOW",
            "args": [{"index": 0, "value": AF_UNIX, "op": "SCMP_CMP_EQ"}],
        }
    )
    profile["syscalls"] = rules
    return profile


def render(profile: dict) -> str:
    return json.dumps(profile, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if output is stale")
    args = parser.parse_args()

    generated = render(build(json.loads(UPSTREAM.read_text())))
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != generated:
            print("sandbox/seccomp.json is stale; run scripts/generate_seccomp.py", file=sys.stderr)
            return 1
        print("sandbox/seccomp.json is up to date")
        return 0
    OUTPUT.write_text(generated)
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
