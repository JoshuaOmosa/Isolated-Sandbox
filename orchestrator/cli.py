"""Command line entry point:  python -m orchestrator {run,probe,cleanup} ..."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sandbox import SandboxError, SandboxManager, SandboxPolicy

from .probing import run_probes
from .report import to_json, to_markdown
from .runner import BenchmarkRunner
from .tasks import discover_tasks


def _add_policy_args(parser: argparse.ArgumentParser) -> None:
    defaults = SandboxPolicy()
    group = parser.add_argument_group("sandbox policy")
    group.add_argument("--image", default=defaults.image, help="runner image (build with `make image`)")
    group.add_argument("--memory", default=defaults.memory, help="hard memory cap, swap disabled (default: %(default)s)")
    group.add_argument("--cpus", type=float, default=defaults.cpus, help="CPU quota (default: %(default)s)")
    group.add_argument("--pids", type=int, default=defaults.pids_limit, help="max processes per sandbox (default: %(default)s)")
    group.add_argument("--wall-seconds", type=float, default=defaults.wall_clock_seconds, help="per-run wall-clock ceiling (default: %(default)s)")
    group.add_argument("--runtime", default=None, help="OCI runtime override, e.g. runsc for gVisor")


def _manager(args: argparse.Namespace) -> SandboxManager:
    policy = SandboxPolicy(
        image=args.image,
        memory=args.memory,
        cpus=args.cpus,
        pids_limit=args.pids,
        wall_clock_seconds=args.wall_seconds,
        runtime=args.runtime,
    )
    return SandboxManager(policy)


def cmd_run(args: argparse.Namespace) -> int:
    tasks = discover_tasks(Path(args.tasks))
    if not tasks:
        print(f"no tasks found in {args.tasks}", file=sys.stderr)
        return 2
    manager = _manager(args)
    runner = BenchmarkRunner(
        manager,
        tasks,
        workers=args.workers,
        suite_budget_seconds=args.budget_seconds,
        include_reference=not args.no_reference,
    )
    submissions = runner.discover_submissions(Path(args.submissions))
    if not submissions:
        print(f"no submissions found in {args.submissions} (expected <agent>/<task_id>/solution.py)", file=sys.stderr)
        return 2

    print(f"running {len(submissions)} submissions across {len(tasks)} tasks with {args.workers} workers ...", file=sys.stderr)
    report = runner.run(submissions)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"report-{stamp}.json").write_text(to_json(report))
    markdown = to_markdown(report)
    (out / f"report-{stamp}.md").write_text(markdown)
    print(markdown)
    print(f"reports written to {out}/report-{stamp}.{{json,md}}", file=sys.stderr)

    if report.invalid_tasks or report.leaked_containers:
        return 1  # infrastructure problems fail the command; a failing *agent* does not
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    report = run_probes(_manager(args), Path(args.probes))
    width = max((len(p["probe"]) for p in report.probes), default=10)
    symbol = {True: "contained", False: "BREACH   ", None: "unverified"}
    for p in report.probes:
        print(f"{symbol[p['contained']]}  {p['probe']:<{width}}  {p['detail']}")
    print()
    if report.timed_out:
        print("probe run hit the wall-clock ceiling", file=sys.stderr)
    if not report.finished:
        print("probe battery did not finish", file=sys.stderr)
    verdict = "all probes contained" if report.ok else f"{len(report.breaches)} breach(es), finished={report.finished}"
    print(f"{len(report.probes)} probes: {verdict}; {len(report.unverified)} unverified")
    return 0 if report.ok else 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    print(f"removed {_manager(args).cleanup_orphans()} orphaned sandbox container(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m orchestrator", description="Sandboxed AI agent benchmarking")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="grade submissions inside ephemeral sandboxes")
    run.add_argument("--tasks", default="tasks")
    run.add_argument("--submissions", default="submissions")
    run.add_argument("--out", default="results")
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--budget-seconds", type=float, default=2400.0, help="whole-suite ceiling (default: 40 min)")
    run.add_argument("--no-reference", action="store_true", help="skip reference calibration (not recommended)")
    _add_policy_args(run)
    run.set_defaults(func=cmd_run)

    probe = sub.add_parser("probe", help="run the escape-attempt battery inside a sandbox")
    probe.add_argument("--probes", default="probes")
    _add_policy_args(probe)
    probe.set_defaults(func=cmd_probe)

    cleanup = sub.add_parser("cleanup", help="remove leaked sandbox containers")
    _add_policy_args(cleanup)
    cleanup.set_defaults(func=cmd_cleanup)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SandboxError as exc:
        print(f"sandbox error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
