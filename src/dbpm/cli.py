from __future__ import annotations

import argparse
import json
import os
import sys

from .environment import resolve_environment
from .errors import DbpmError
from .executor import execute_plan
from .planner import create_plan
from .provenance import resolve_provenance
from .source import load_package_source


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "plan":
            plan = _build_plan(args.mode, args)
            _print_json(plan)
            return 0
        if args.command in {"bootstrap-core", "install", "reinstall"}:
            plan = _build_plan(args.command, args)
            if args.dry_run:
                _print_json(plan)
                return 0
            _execute_or_explain(plan, args)
            return 0
    except DbpmError as exc:
        print(f"dbpm: {exc}", file=sys.stderr)
        return 2

    parser.error("No command selected")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dbpm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Generate a deployment plan")
    _add_common_args(plan)
    plan.add_argument(
        "--mode",
        choices=("bootstrap-core", "install", "upgrade", "reinstall", "repair"),
        default="install",
        help="Deployment mode to plan",
    )

    bootstrap = subparsers.add_parser("bootstrap-core", help="Bootstrap Core")
    _add_common_args(bootstrap)
    _add_execution_args(bootstrap)

    install = subparsers.add_parser("install", help="Install a package")
    _add_common_args(install)
    _add_execution_args(install)

    reinstall = subparsers.add_parser("reinstall", help="Destructively reinstall a package")
    _add_common_args(reinstall)
    _add_execution_args(reinstall)
    reinstall.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow destructive reinstall planning/execution",
    )

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="Local package directory or built ZIP")
    parser.add_argument("--env", default="development", help="Target environment name")
    parser.add_argument("--approve", action="store_true", help="Approve policy-gated actions")


def _add_execution_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without executing")
    parser.add_argument("--connect", help="SQLPlus/SQLcl connect string")
    parser.add_argument(
        "--runner",
        default=os.environ.get("DBPM_SQL_RUNNER", "sqlplus"),
        help="SQL runner executable, default: sqlplus",
    )


def _build_plan(mode: str, args: argparse.Namespace) -> dict[str, object]:
    source = load_package_source(args.source)
    provenance = resolve_provenance(source)
    environment = resolve_environment(args.env)
    allow_destructive = bool(getattr(args, "allow_destructive", False))
    return create_plan(
        mode=mode,
        source=source,
        provenance=provenance,
        environment=environment,
        allow_destructive=allow_destructive,
        approve=args.approve,
    )


def _execute_or_explain(plan: dict[str, object], args: argparse.Namespace) -> None:
    policy = plan.get("policy")
    if isinstance(policy, dict) and policy.get("result") != "allowed":
        blocked = policy.get("blocked", [])
        approvals = policy.get("required_approvals", [])
        reasons = [*blocked, *approvals] if isinstance(blocked, list) and isinstance(approvals, list) else []
        raise DbpmError("; ".join(str(reason) for reason in reasons) or "Policy blocks execution")

    if not args.connect:
        raise DbpmError("Execution requires --connect, or use --dry-run to print the plan")
    execute_plan(plan, connect=args.connect, runner=args.runner)


def _print_json(value: dict[str, object]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
