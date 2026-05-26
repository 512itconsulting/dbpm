from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .db import check_core, get_application_state, get_reverse_dependencies
from .environment import resolve_environment
from .errors import DbpmError
from .executor import execute_plan
from .lockfile import (
    LOCKFILE_NAME,
    assert_database_matches_lockfile,
    assert_lockfile_matches_plan,
    create_lockfile,
    load_lockfile,
    write_lockfile,
)
from .planner import create_plan
from .provenance import resolve_provenance
from .resolver import create_multi_package_plan
from .source import load_package_source


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "plan":
            plan = _build_plan(args.mode, args, include_installed_state=bool(args.connect))
            _print_json(plan)
            return 0
        if args.command == "lock":
            if args.check_db and not args.check:
                raise DbpmError("--check-db requires --check")
            plan = _build_plan("install", args, include_installed_state=bool(args.connect))
            lockfile_path = Path(args.output)
            if args.check:
                lockfile = load_lockfile(lockfile_path)
                assert_lockfile_matches_plan(lockfile, plan)
                if args.check_db:
                    if not args.connect:
                        raise DbpmError("Database lockfile check requires --connect or DBPM_CONNECT")
                    assert_database_matches_lockfile(lockfile, plan)
                print(f"LOCKFILE_OK={lockfile_path}")
                return 0
            lockfile = create_lockfile(plan)
            write_lockfile(lockfile, lockfile_path)
            print(f"WROTE_LOCKFILE={lockfile_path}")
            return 0
        if args.command == "check-core":
            result = check_core(
                connect=_connect_string(args),
                runner=args.runner,
                minimum_version=args.minimum_version,
            )
            print(result.stdout.strip())
            return 0
        if args.command in {"bootstrap-core", "install", "upgrade", "reinstall", "resume", "validate"}:
            plan = _build_plan(args.command, args, include_installed_state=not args.dry_run)
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

    check = subparsers.add_parser("check-core", help="Verify Core is available in a target database")
    _add_database_args(check)
    check.add_argument("--minimum-version", help="Minimum Core version, such as 3.0.0")

    plan = subparsers.add_parser("plan", help="Generate a deployment plan")
    _add_common_args(plan)
    plan.add_argument(
        "--mode",
        choices=("bootstrap-core", "install", "upgrade", "reinstall", "resume", "validate"),
        default="install",
        help="Deployment mode to plan",
    )
    _add_dependency_source_args(plan)
    _add_database_args(plan)

    lock = subparsers.add_parser("lock", help="Write or verify a dependency lockfile")
    _add_common_args(lock)
    _add_dependency_source_args(lock)
    _add_database_args(lock)
    lock.add_argument("--output", default=LOCKFILE_NAME, help=f"Lockfile path, default: {LOCKFILE_NAME}")
    lock.add_argument("--check", action="store_true", help="Verify the current resolution matches the lockfile")
    lock.add_argument(
        "--check-db",
        action="store_true",
        help="With --check, verify installed database versions match the lockfile",
    )

    bootstrap = subparsers.add_parser("bootstrap-core", help="Bootstrap Core")
    _add_common_args(bootstrap)
    _add_execution_args(bootstrap)

    install = subparsers.add_parser("install", help="Install a package")
    _add_common_args(install)
    _add_execution_args(install)
    _add_dependency_source_args(install)

    upgrade = subparsers.add_parser("upgrade", help="Upgrade an installed package to a new version")
    _add_common_args(upgrade)
    _add_execution_args(upgrade)

    reinstall = subparsers.add_parser("reinstall", help="Destructively reinstall a package")
    _add_common_args(reinstall)
    _add_execution_args(reinstall)
    reinstall.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow destructive reinstall planning/execution",
    )

    resume = subparsers.add_parser("resume", help="Resume a running or failed deployment")
    _add_common_args(resume)
    _add_execution_args(resume)

    validate = subparsers.add_parser("validate", help="Run a package validation script")
    _add_common_args(validate)
    _add_execution_args(validate)

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="Local package directory or built ZIP")
    parser.add_argument("--env", default="development", help="Target environment name")
    parser.add_argument("--approve", action="store_true", help="Approve policy-gated actions")


def _add_execution_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without executing")
    _add_database_args(parser)


def _add_dependency_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dependency-source",
        action="append",
        default=[],
        help="Local package directory or ZIP that may satisfy a manifest dependency",
    )


def _add_database_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--connect",
        default=os.environ.get("DBPM_CONNECT"),
        help="SQLPlus/SQLcl connect string, default: DBPM_CONNECT",
    )
    parser.add_argument(
        "--runner",
        default=os.environ.get("DBPM_SQL_RUNNER", "sqlplus"),
        help="SQL runner executable, default: DBPM_SQL_RUNNER or sqlplus",
    )


def _build_plan(
    mode: str,
    args: argparse.Namespace,
    *,
    include_installed_state: bool = False,
) -> dict[str, object]:
    source = load_package_source(args.source)
    dependency_sources = [
        load_package_source(raw_path)
        for raw_path in getattr(args, "dependency_source", [])
    ]
    provenance = resolve_provenance(source)
    environment = resolve_environment(args.env)
    allow_destructive = bool(getattr(args, "allow_destructive", False))
    installed_state = None
    reverse_dependencies = None
    if include_installed_state and not source.manifest.is_core:
        installed_state = _get_installed_state(args, source.manifest.application_name)
        reverse_dependencies = _get_reverse_dependencies(args, source.manifest.application_name)

    if args.command in {"plan", "install", "lock"} and (dependency_sources or source.manifest.dependencies):
        installed_states = {source.manifest.application_name: installed_state}
        reverse_dependencies_by_app = {source.manifest.application_name: reverse_dependencies or []}
        if include_installed_state:
            for dependency in source.manifest.dependencies:
                app_name = _application_name(dependency.name)
                installed_states[app_name] = _get_installed_state(args, app_name)
                reverse_dependencies_by_app[app_name] = _get_reverse_dependencies(args, app_name)
            for dependency_source in dependency_sources:
                app_name = dependency_source.manifest.application_name
                installed_states[app_name] = _get_installed_state(args, app_name)
                reverse_dependencies_by_app[app_name] = _get_reverse_dependencies(args, app_name)
        return create_multi_package_plan(
            mode=mode,
            source=source,
            dependency_sources=dependency_sources,
            environment=environment,
            installed_states=installed_states,
            reverse_dependencies=reverse_dependencies_by_app,
            allow_destructive=allow_destructive,
            approve=args.approve,
        )

    return create_plan(
        mode=mode,
        source=source,
        provenance=provenance,
        environment=environment,
        installed_state=installed_state,
        reverse_dependencies=reverse_dependencies,
        allow_destructive=allow_destructive,
        approve=args.approve,
    )


def _execute_or_explain(plan: dict[str, object], args: argparse.Namespace) -> None:
    packages = plan.get("packages")
    if isinstance(packages, list):
        for child_plan in packages:
            if not isinstance(child_plan, dict):
                raise DbpmError("Multi-package plan entries must be objects")
            _execute_or_explain_policy(child_plan)
            _enforce_installed_state(child_plan)
        execute_plan(plan, connect=_connect_string(args), runner=args.runner)
        return

    _execute_or_explain_policy(plan)
    _enforce_installed_state(plan)
    execute_plan(plan, connect=_connect_string(args), runner=args.runner)


def _execute_or_explain_policy(plan: dict[str, object]) -> None:
    policy = plan.get("policy")
    if isinstance(policy, dict) and policy.get("result") != "allowed":
        blocked = policy.get("blocked", [])
        approvals = policy.get("required_approvals", [])
        reasons = [*blocked, *approvals] if isinstance(blocked, list) and isinstance(approvals, list) else []
        raise DbpmError("; ".join(str(reason) for reason in reasons) or "Policy blocks execution")


def _get_installed_state(args: argparse.Namespace, application_name: str) -> dict[str, str] | None:
    state = get_application_state(
        connect=_connect_string(args),
        runner=args.runner,
        application_name=application_name,
    )
    return None if state is None else state.as_dict()


def _get_reverse_dependencies(args: argparse.Namespace, application_name: str) -> list[str]:
    return get_reverse_dependencies(
        connect=_connect_string(args),
        runner=args.runner,
        application_name=application_name,
    )


def _enforce_installed_state(plan: dict[str, object]) -> None:
    mode = plan.get("mode")
    state = plan.get("installed_state")
    package = plan.get("package")
    app_name = None
    if isinstance(package, dict):
        app_name = package.get("application_name")

    status = state.get("deploy_status") if isinstance(state, dict) else None

    if mode == "install":
        if state is None:
            return
        if status == "C":
            raise DbpmError(f"{app_name} is already installed; use reinstall or upgrade")
        raise DbpmError(f"{app_name} deployment status is {status}; use resume or reinstall")

    if mode == "resume":
        if state is None:
            raise DbpmError(f"{app_name} is not installed; use install")
        if status not in {"R", "F"}:
            raise DbpmError(f"{app_name} deployment status is {status}; resume requires R or F")
        return

    if mode == "validate":
        if state is None:
            raise DbpmError(f"{app_name} is not installed; use install")
        if status != "C":
            raise DbpmError(f"{app_name} deployment status is {status}; validate requires C")
        return

    if mode == "upgrade":
        if state is None:
            raise DbpmError(f"{app_name} is not installed; use install")
        if status != "C":
            raise DbpmError(f"{app_name} deployment status is {status}; upgrade requires C")
        installed_version = state.get("version") if isinstance(state, dict) else None
        target_version = package.get("version") if isinstance(package, dict) else None
        if installed_version and target_version:
            cmp = _compare_versions(installed_version, target_version)
            if cmp == 0:
                raise DbpmError(
                    f"{app_name} version {target_version} is already installed; no upgrade needed"
                )
            if cmp > 0:
                raise DbpmError(
                    f"Cannot downgrade {app_name} from {installed_version} to {target_version}"
                )
        return

    if mode == "reinstall":
        reverse_dependencies = plan.get("reverse_dependencies", [])
        if reverse_dependencies:
            names = ", ".join(str(name) for name in reverse_dependencies)
            raise DbpmError(f"Cannot reinstall {app_name}; installed applications depend on it: {names}")
        return

    if isinstance(state, dict) and status != "C":
        raise DbpmError(f"{app_name} deployment status is {status}; expected C")


def _connect_string(args: argparse.Namespace) -> str:
    if not args.connect:
        raise DbpmError("Database access requires --connect or DBPM_CONNECT")
    return args.connect


def _application_name(name: str) -> str:
    return name.replace("-", "_").upper()


def _compare_versions(a: str, b: str) -> int:
    """Return negative if a < b, 0 if equal, positive if a > b."""
    def _parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    pa, pb = _parts(a), _parts(b)
    length = max(len(pa), len(pb))
    pa = pa + (0,) * (length - len(pa))
    pb = pb + (0,) * (length - len(pb))
    for x, y in zip(pa, pb):
        if x != y:
            return x - y
    return 0


def _print_json(value: dict[str, object]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
