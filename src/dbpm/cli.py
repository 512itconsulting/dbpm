from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .chain import ChainError, resolve_upgrade_chain
from .resolver import parse_version
from .publisher import PublishReceipt, build_artifact, publish_to_repository, verify_publish
from .db import check_core, get_application_state, get_deployment_provenance, get_reverse_dependencies
from .environment import resolve_environment
from .errors import DbpmError
from .executor import execute_plan
from .lockfile import (
    LOCKFILE_NAME,
    assert_database_matches_lockfile,
    assert_database_provenance_matches_lockfile,
    assert_database_states_match_lockfile,
    assert_lockfile_matches_plan,
    create_lockfile,
    deployment_provenance_requests,
    load_lockfile,
    lockfile_package_sources_with_checksums,
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
        if args.command == "publish":
            _run_publish(args)
            return 0
        if args.command == "plan":
            plan = _build_plan(args.mode, args, include_installed_state=bool(args.connect))
            _print_json(plan)
            return 0
        if args.command == "lock":
            if args.check_db and not args.check:
                raise DbpmError("--check-db requires --check")
            plan = _build_plan("install", args, include_installed_state=False)
            lockfile_path = Path(args.output)
            if args.check:
                lockfile = load_lockfile(lockfile_path)
                assert_lockfile_matches_plan(lockfile, plan)
                if args.check_db:
                    if not args.connect:
                        raise DbpmError("Database lockfile check requires --connect or DBPM_CONNECT")
                    states = {
                        app_name: _get_installed_state(args, app_name)
                        for app_name, _ in deployment_provenance_requests(lockfile)
                    }
                    assert_database_states_match_lockfile(lockfile, states)
                    provenances = {
                        app_name: get_deployment_provenance(
                            connect=_connect_string(args),
                            runner=args.runner,
                            application_name=app_name,
                            version=version,
                        )
                        for app_name, version in deployment_provenance_requests(lockfile)
                    }
                    assert_database_provenance_matches_lockfile(lockfile, provenances)
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
            if args.command == "install" and args.lockfile:
                plan = _build_plan_from_lockfile(args, include_installed_state=not args.dry_run)
            else:
                if args.command == "install" and args.source is None:
                    raise DbpmError("install requires a source or --lockfile")
                include_installed = not args.dry_run or (
                    args.command == "upgrade" and bool(args.connect)
                )
                plan = _build_plan(args.command, args, include_installed_state=include_installed)
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


def _run_publish(args: argparse.Namespace) -> None:
    from pathlib import Path
    from .errors import PublishError
    from .manifest import PublishConfig

    source = load_package_source(args.source)
    manifest = source.manifest

    publish_config = manifest.publish
    if args.group or args.artifact_id:
        group = args.group or (publish_config.group if publish_config else None)
        if not group:
            raise DbpmError("--group is required when publish.group is not set in the manifest")
        artifact_id = args.artifact_id or (publish_config.artifact_id if publish_config else None)
        publish_config = PublishConfig(group=group, artifact_id=artifact_id)
    elif publish_config is None:
        raise DbpmError(
            "No publish configuration found. Add a publish: section to dbpm.yaml or use --group"
        )

    if not args.signing_key:
        raise DbpmError(
            "A signing key is required. Use --signing-key or set DBPM_SIGNING_KEY"
        )

    if args.dry_run:
        artifact_id = publish_config.artifact_id or manifest.name
        version = manifest.version
        artifact_name = f"{artifact_id}-{version}.zip"
        pom_name = f"{artifact_id}-{version}.pom"
        print(f"DRY_RUN: would publish {artifact_name} to {args.target}")
        print(f"  artifact: {artifact_name}")
        print(f"  pom:      {pom_name}")
        print(f"  checksums: {artifact_name}.sha256, {artifact_name}.sha1")
        print(f"  signature: {artifact_name}.asc")
        print(f"  group:     {publish_config.group}")
        print(f"  artifact_id: {artifact_id}")
        print(f"  version:   {version}")
        print(f"  signing_key: {args.signing_key}")
        return

    source_path = source.path
    artifact_path = build_artifact(source_path, manifest, publish_config)
    receipt = publish_to_repository(args.target, manifest, publish_config, artifact_path, args.signing_key)
    verify_publish(args.target, manifest, publish_config, manifest.version, receipt.checksum)
    print(f"PUBLISHED={receipt.artifact_url}")


def _build_parser() -> argparse.ArgumentParser:
    from importlib.metadata import version as _pkg_version
    parser = argparse.ArgumentParser(prog="dbpm")
    parser.add_argument("--version", action="version", version=f"dbpm {_pkg_version('dbpm')}")
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
    _add_common_args(install, source_required=False)
    _add_execution_args(install)
    _add_dependency_source_args(install)
    install.add_argument(
        "--lockfile",
        nargs="?",
        const=LOCKFILE_NAME,
        help=f"Install from a resolved lockfile, default when no value is provided: {LOCKFILE_NAME}",
    )

    upgrade = subparsers.add_parser("upgrade", help="Upgrade an installed package to a new version")
    _add_common_args(upgrade)
    _add_execution_args(upgrade)
    _add_dependency_source_args(upgrade)
    upgrade.add_argument(
        "--allow-dependent-break",
        action="store_true",
        help="Allow major upgrade even when installed dependents may have incompatible constraints",
    )

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
    _add_dependency_source_args(validate)

    publish = subparsers.add_parser("publish", help="Build and publish a package to a Maven repository")
    publish.add_argument("source", help="Local package directory or ZIP to publish")
    publish.add_argument(
        "--target",
        required=True,
        help="Publish target: gh-maven:owner/repo or maven:https://...",
    )
    publish.add_argument(
        "--group",
        default=None,
        help="Maven group ID (overrides publish.group in manifest)",
    )
    publish.add_argument(
        "--artifact-id",
        default=None,
        dest="artifact_id",
        help="Maven artifact ID (overrides publish.artifact_id in manifest)",
    )
    publish.add_argument(
        "--signing-key",
        default=os.environ.get("DBPM_SIGNING_KEY"),
        dest="signing_key",
        help="GPG key ID, fingerprint, or email (default: DBPM_SIGNING_KEY)",
    )
    publish.add_argument("--dry-run", action="store_true", help="Print what would be published without uploading")

    return parser


def _add_common_args(parser: argparse.ArgumentParser, *, source_required: bool = True) -> None:
    if source_required:
        parser.add_argument("source", help="Package source: local directory, ZIP, URL, or Maven coordinate")
    else:
        parser.add_argument("source", nargs="?", help="Package source: local directory, ZIP, URL, or Maven coordinate")
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
    if include_installed_state and _should_read_installed_state(mode, source.manifest.is_core):
        installed_state = _get_installed_state(args, source.manifest.application_name)
        if not source.manifest.is_core:
            reverse_dependencies = _get_reverse_dependencies(args, source.manifest.application_name)

    if args.command in {"plan", "install", "lock", "upgrade", "validate"} and (
        dependency_sources or source.manifest.dependencies
    ):
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

    if mode == "upgrade" and installed_state is not None:
        installed_version = installed_state.get("version")
        if isinstance(installed_version, str):
            chain = resolve_upgrade_chain(source, args.source, installed_version)
            if len(chain) > 1:
                return _build_chain_plan(chain, args, installed_version, environment, allow_destructive)

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


def _build_plan_from_lockfile(
    args: argparse.Namespace,
    *,
    include_installed_state: bool = False,
) -> dict[str, object]:
    if args.source is not None or getattr(args, "dependency_source", []):
        raise DbpmError("--lockfile cannot be combined with source or --dependency-source")

    lockfile_path = Path(args.lockfile)
    lockfile = load_lockfile(lockfile_path)
    root_entry, dep_entries = lockfile_package_sources_with_checksums(lockfile)

    root_uri, root_checksum, root_alg, root_sig_url = root_entry
    root_source = load_package_source(
        root_uri,
        expected_checksum=root_checksum,
        expected_checksum_alg=root_alg,
        expected_signature_url=root_sig_url,
    )
    dep_sources = [
        load_package_source(
            uri,
            expected_checksum=checksum,
            expected_checksum_alg=alg,
            expected_signature_url=sig_url,
        )
        for uri, checksum, alg, sig_url in dep_entries
    ]

    environment = resolve_environment(args.env)
    installed_states: dict[str, dict[str, str] | None] = {}
    reverse_dependencies_by_app: dict[str, list[str]] = {}

    if include_installed_state:
        for source in [root_source, *dep_sources]:
            app_name = source.manifest.application_name
            if _should_read_installed_state("install", source.manifest.is_core):
                installed_states[app_name] = _get_installed_state(args, app_name)
                reverse_dependencies_by_app[app_name] = _get_reverse_dependencies(args, app_name)

    plan = create_multi_package_plan(
        mode="install",
        source=root_source,
        dependency_sources=dep_sources,
        environment=environment,
        installed_states=installed_states,
        reverse_dependencies=reverse_dependencies_by_app,
        allow_destructive=False,
        approve=args.approve,
    )
    assert_lockfile_matches_plan(lockfile, plan)
    return plan


def _build_chain_plan(
    chain: list,
    args: argparse.Namespace,
    installed_version: str,
    environment: object,
    allow_destructive: bool,
) -> dict[str, object]:
    from .provenance import resolve_provenance
    steps = []
    modeled_version = installed_version
    for step_source in chain:
        modeled_state = {"version": modeled_version, "deploy_status": "C"}
        step_plan = create_plan(
            mode="upgrade",
            source=step_source,
            provenance=resolve_provenance(step_source),
            environment=environment,
            installed_state=modeled_state,
            reverse_dependencies=None,
            allow_destructive=allow_destructive,
            approve=args.approve,
        )
        steps.append(step_plan)
        modeled_version = step_source.manifest.version

    target = chain[-1]
    return {
        "schema_version": "dbpm.upgrade-chain.v0",
        "mode": "upgrade",
        "package": {
            "name": target.manifest.name,
            "application_name": target.manifest.application_name,
            "version": target.manifest.version,
        },
        "installed_version": installed_version,
        "steps": steps,
    }


def _execute_or_explain(plan: dict[str, object], args: argparse.Namespace) -> None:
    if plan.get("schema_version") == "dbpm.upgrade-chain.v0":
        _execute_upgrade_chain(plan, args)
        return

    packages = plan.get("packages")
    if isinstance(packages, list):
        allow_dependent_break = getattr(args, "allow_dependent_break", False)
        for child_plan in packages:
            if not isinstance(child_plan, dict):
                raise DbpmError("Multi-package plan entries must be objects")
            _execute_or_explain_policy(child_plan)
            _enforce_installed_state(child_plan)
            _enforce_core_minimum_version(child_plan, args)
            _enforce_major_upgrade_dependencies(child_plan, allow_dependent_break)
        execute_plan(plan, connect=_connect_string(args), runner=args.runner)
        return

    _execute_or_explain_policy(plan)
    _enforce_installed_state(plan)
    _enforce_core_minimum_version(plan, args)
    _enforce_major_upgrade_dependencies(plan, getattr(args, "allow_dependent_break", False))
    execute_plan(plan, connect=_connect_string(args), runner=args.runner)


def _execute_upgrade_chain(plan: dict[str, object], args: argparse.Namespace) -> None:
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        raise DbpmError("Upgrade chain plan steps must be a list")
    allow_dependent_break = getattr(args, "allow_dependent_break", False)
    for i, step_plan in enumerate(steps):
        if not isinstance(step_plan, dict):
            raise DbpmError("Upgrade chain step must be an object")
        if i > 0:
            package = step_plan.get("package")
            app_name = package.get("application_name") if isinstance(package, dict) else None
            if isinstance(app_name, str):
                fresh_state = _get_installed_state(args, app_name)
                step_plan = dict(step_plan)
                step_plan["installed_state"] = fresh_state
        _execute_or_explain_policy(step_plan)
        _enforce_installed_state(step_plan)
        _enforce_core_minimum_version(step_plan, args)
        _enforce_major_upgrade_dependencies(step_plan, allow_dependent_break)
        execute_plan(step_plan, connect=_connect_string(args), runner=args.runner)


def _enforce_major_upgrade_dependencies(
    plan: dict[str, object],
    allow_dependent_break: bool,
) -> None:
    if allow_dependent_break or plan.get("mode") != "upgrade":
        return
    package = plan.get("package")
    state = plan.get("installed_state")
    if not isinstance(package, dict) or not isinstance(state, dict):
        return
    installed_version = state.get("version")
    target_version = package.get("version")
    if not isinstance(installed_version, str) or not isinstance(target_version, str):
        return
    if _major(target_version) <= _major(installed_version):
        return
    reverse_deps = plan.get("reverse_dependencies", [])
    if not reverse_deps:
        return
    app_name = package.get("application_name")
    names = ", ".join(str(n) for n in reverse_deps)
    raise DbpmError(
        f"Cannot upgrade {app_name} from {installed_version} to {target_version}; "
        f"installed dependents may have incompatible constraints: {names}. "
        f"Provide updated dependent versions with --dependency-source, "
        f"or use --allow-dependent-break to override."
    )


def _enforce_core_minimum_version(plan: dict[str, object], args: argparse.Namespace) -> None:
    if plan.get("mode") == "bootstrap-core":
        return
    core = plan.get("core")
    if not isinstance(core, dict):
        return
    required = core.get("minimum_version")
    if not isinstance(required, str):
        return
    installed_state = _get_installed_state(args, "CORE")
    if installed_state is None:
        raise DbpmError(
            f"This package requires Core {required} or newer, but Core is not installed. "
            f"Install Core first with: dbpm bootstrap-core"
        )
    status = installed_state.get("deploy_status")
    if status != "C":
        raise DbpmError(
            f"This package requires Core {required} or newer, but Core deployment "
            f"status is {status}; resume or reinstall Core first."
        )
    installed = installed_state.get("version")
    if not isinstance(installed, str):
        return
    try:
        if parse_version(installed) < parse_version(required):
            raise DbpmError(
                f"This package requires Core {required} or newer; "
                f"Core {installed} is installed. "
                f"Upgrade Core first with: dbpm upgrade <core-source> --connect ..."
            )
    except ValueError:
        pass


def _major(version: str) -> int:
    try:
        return int(version.split(".")[0])
    except (ValueError, IndexError):
        return 0


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


def _should_read_installed_state(mode: str, is_core: bool) -> bool:
    if not is_core:
        return True
    return mode in {"upgrade", "resume", "validate"}


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
