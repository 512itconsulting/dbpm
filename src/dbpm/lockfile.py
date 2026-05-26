from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import DbpmError


LOCKFILE_NAME = "dbpm-lock.json"
LOCK_SCHEMA_VERSION = "dbpm.lock.v0"


class LockfileError(DbpmError):
    """Raised when a lockfile is missing, invalid, or does not match."""


def create_lockfile(plan: dict[str, object]) -> dict[str, object]:
    packages = _package_plans(plan)
    locked_packages = [_locked_package(package_plan) for package_plan in packages]

    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "root_application_name": _root_application_name(plan),
        "execution_order": [
            package["application_name"]
            for package in locked_packages
            if isinstance(package.get("application_name"), str)
        ],
        "packages": locked_packages,
        "satisfied_dependencies": plan.get("satisfied_dependencies", []),
    }


def load_lockfile(path: Path) -> dict[str, object]:
    try:
        lockfile = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LockfileError(f"Lockfile does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LockfileError(f"Invalid lockfile JSON: {path}") from exc

    if not isinstance(lockfile, dict) or lockfile.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise LockfileError(f"Unsupported lockfile schema in {path}")
    return lockfile


def write_lockfile(lockfile: dict[str, object], path: Path) -> None:
    path.write_text(
        json.dumps(lockfile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assert_lockfile_matches_plan(
    lockfile: dict[str, object],
    plan: dict[str, object],
) -> None:
    expected = create_lockfile(plan)
    errors = _compare_lockfiles(lockfile, expected)
    if errors:
        raise LockfileError("; ".join(errors))


def assert_database_matches_lockfile(
    lockfile: dict[str, object],
    plan: dict[str, object],
) -> None:
    locked = _locked_packages_by_app(lockfile)
    planned = _plans_by_app(plan)
    errors: list[str] = []

    for app_name, locked_package in locked.items():
        package_plan = planned.get(app_name)
        if package_plan is None:
            continue
        state = package_plan.get("installed_state")
        version = locked_package.get("version")
        if not isinstance(state, dict):
            errors.append(f"{app_name} is not installed")
            continue
        installed_version = state.get("version")
        deploy_status = state.get("deploy_status")
        if deploy_status != "C":
            errors.append(f"{app_name} deploy_status is {deploy_status}; expected C")
        if installed_version != version:
            errors.append(f"{app_name} installed version is {installed_version}; expected {version}")

    if errors:
        raise LockfileError("; ".join(errors))


def assert_database_states_match_lockfile(
    lockfile: dict[str, object],
    states_by_app: dict[str, dict[str, str] | None],
) -> None:
    errors: list[str] = []
    for app_name, locked_package in _locked_packages_by_app(lockfile).items():
        state = states_by_app.get(app_name)
        version = locked_package.get("version")
        if state is None:
            errors.append(f"{app_name} is not installed")
            continue
        installed_version = state.get("version")
        deploy_status = state.get("deploy_status")
        if deploy_status != "C":
            errors.append(f"{app_name} deploy_status is {deploy_status}; expected C")
        if installed_version != version:
            errors.append(f"{app_name} installed version is {installed_version}; expected {version}")

    if errors:
        raise LockfileError("; ".join(errors))


def assert_database_provenance_matches_lockfile(
    lockfile: dict[str, object],
    provenances_by_app: dict[str, dict[str, object] | None],
) -> None:
    errors: list[str] = []
    for app_name, locked_package in _locked_packages_by_app(lockfile).items():
        provenance = provenances_by_app.get(app_name)
        if provenance is None:
            errors.append(f"{app_name} deployment provenance is not recorded")
            continue
        errors.extend(_compare_package_provenance(locked_package, provenance))

    if errors:
        raise LockfileError("; ".join(errors))


def deployment_provenance_requests(lockfile: dict[str, object]) -> list[tuple[str, str]]:
    requests = []
    for app_name, locked_package in _locked_packages_by_app(lockfile).items():
        version = locked_package.get("version")
        if not isinstance(version, str) or not version:
            raise LockfileError(f"{app_name} lockfile entry is missing version")
        requests.append((app_name, version))
    return requests


def package_sources_from_lockfile(lockfile: dict[str, object]) -> tuple[str, list[str]]:
    packages = lockfile.get("packages", [])
    execution_order = lockfile.get("execution_order", [])
    root_application_name = lockfile.get("root_application_name")
    if not isinstance(packages, list):
        raise LockfileError("Lockfile packages must be a list")
    if not isinstance(execution_order, list):
        raise LockfileError("Lockfile execution_order must be a list")
    if not isinstance(root_application_name, str):
        raise LockfileError("Lockfile is missing root_application_name")

    packages_by_app = _locked_packages_by_app(lockfile)
    if root_application_name not in packages_by_app:
        raise LockfileError(f"Lockfile root package is missing: {root_application_name}")
    root_source = _package_source_reference(packages_by_app[root_application_name])
    dependency_sources = [
        _package_source_reference(packages_by_app[app_name])
        for app_name in execution_order
        if isinstance(app_name, str) and app_name != root_application_name
    ]
    return root_source, dependency_sources


def _compare_package_provenance(
    locked_package: dict[str, object],
    provenance: dict[str, object],
) -> list[str]:
    app_name = str(locked_package.get("application_name"))
    version = str(locked_package.get("version"))
    artifact = _dict(locked_package.get("artifact"))
    locked_provenance = _dict(locked_package.get("provenance"))
    errors: list[str] = []

    version_parts = version.split(".")
    if len(version_parts) == 3:
        for field, expected in zip(("major_version", "minor_version", "patch_version"), version_parts):
            if _normalize(provenance.get(field)) != expected:
                errors.append(
                    f"{app_name} provenance {field} mismatch: "
                    f"expected {expected}, found {provenance.get(field)}"
                )

    comparisons = {
        "artifact_uri": artifact.get("uri"),
        "artifact_checksum": artifact.get("checksum"),
        "artifact_checksum_alg": artifact.get("checksum_alg"),
        "artifact_file_name": artifact.get("file_name"),
        "artifact_repository_type": artifact.get("repository_type"),
        "artifact_group_id": artifact.get("group_id"),
        "artifact_id": artifact.get("artifact_id"),
        "artifact_version": artifact.get("artifact_version"),
        "artifact_classifier": artifact.get("classifier"),
        "artifact_extension": artifact.get("extension"),
        "package_coordinate": artifact.get("coordinate"),
        "source_repository_url": locked_provenance.get("source_repository_url"),
        "source_commit_hash": locked_provenance.get("source_commit_hash"),
        "source_path": artifact.get("uri"),
        "build_id": locked_provenance.get("build_id"),
        "build_url": locked_provenance.get("build_url"),
        "build_time": locked_provenance.get("build_time"),
    }
    for field, expected in comparisons.items():
        if _normalize(expected) != _normalize(provenance.get(field)):
            errors.append(
                f"{app_name} provenance {field} mismatch: "
                f"expected {expected}, found {provenance.get(field)}"
            )
    return errors


def _compare_lockfiles(
    actual: dict[str, object],
    expected: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    actual_packages = _locked_packages_by_app(actual)
    expected_packages = _locked_packages_by_app(expected)

    actual_order = actual.get("execution_order")
    expected_order = expected.get("execution_order")
    if actual_order != expected_order:
        errors.append(f"execution_order mismatch: expected {expected_order}, found {actual_order}")

    for app_name, expected_package in expected_packages.items():
        actual_package = actual_packages.get(app_name)
        if actual_package is None:
            errors.append(f"{app_name} is missing from lockfile")
            continue
        for field in ("name", "application_name", "version"):
            if actual_package.get(field) != expected_package.get(field):
                errors.append(
                    f"{app_name} {field} mismatch: "
                    f"expected {expected_package.get(field)}, found {actual_package.get(field)}"
                )
        actual_artifact = _dict(actual_package.get("artifact"))
        expected_artifact = _dict(expected_package.get("artifact"))
        for field in ("uri", "checksum", "checksum_alg", "coordinate"):
            if actual_artifact.get(field) != expected_artifact.get(field):
                errors.append(
                    f"{app_name} artifact {field} mismatch: "
                    f"expected {expected_artifact.get(field)}, found {actual_artifact.get(field)}"
                )

    for app_name in actual_packages:
        if app_name not in expected_packages:
            errors.append(f"{app_name} is present in lockfile but not in current resolution")

    return errors


def _package_source_reference(package: dict[str, object]) -> str:
    artifact = _dict(package.get("artifact"))
    source = _dict(package.get("source"))
    value = artifact.get("uri") or source.get("path")
    if not isinstance(value, str) or not value:
        app_name = package.get("application_name") or "<unknown>"
        raise LockfileError(f"{app_name} lockfile entry has no usable source URI")
    return value


def _package_plans(plan: dict[str, object]) -> list[dict[str, object]]:
    packages = plan.get("packages")
    if isinstance(packages, list):
        return [package for package in packages if isinstance(package, dict)]
    return [plan]


def _locked_package(package_plan: dict[str, object]) -> dict[str, object]:
    package = _dict(package_plan.get("package"))
    source = _dict(package_plan.get("source"))
    provenance = _dict(package_plan.get("provenance"))
    payload = _provenance_payload(package_plan)

    return {
        "name": package.get("name"),
        "application_name": package.get("application_name"),
        "version": package.get("version"),
        "source": {
            "type": source.get("type"),
            "path": source.get("path"),
            "root": source.get("root"),
            "manifest": source.get("manifest"),
        },
        "artifact": {
            "uri": payload.get("artifact_uri") or source.get("path"),
            "checksum": payload.get("artifact_checksum"),
            "checksum_alg": payload.get("artifact_checksum_alg"),
            "file_name": payload.get("artifact_file_name"),
            "repository_type": payload.get("artifact_repository_type"),
            "group_id": payload.get("artifact_group_id"),
            "artifact_id": payload.get("artifact_id"),
            "artifact_version": payload.get("artifact_version"),
            "classifier": payload.get("artifact_classifier"),
            "extension": payload.get("artifact_extension"),
            "coordinate": payload.get("package_coordinate"),
        },
        "provenance": {
            "commit": provenance.get("commit"),
            "source": provenance.get("source"),
            "dirty": provenance.get("dirty"),
            "source_repository_url": payload.get("source_repository_url"),
            "source_commit_hash": payload.get("source_commit_hash"),
            "build_id": payload.get("build_id"),
            "build_url": payload.get("build_url"),
            "build_time": payload.get("build_time"),
        },
        "dependencies": package_plan.get("dependencies", []),
    }


def _provenance_payload(package_plan: dict[str, object]) -> dict[str, object]:
    pre_actions = package_plan.get("pre_actions", [])
    if not isinstance(pre_actions, list):
        return {}
    for action in pre_actions:
        if not isinstance(action, dict) or action.get("type") != "stage_deployment_provenance":
            continue
        payload = action.get("payload")
        if isinstance(payload, dict):
            return payload
    return {}


def _locked_packages_by_app(lockfile: dict[str, object]) -> dict[str, dict[str, object]]:
    packages = lockfile.get("packages", [])
    if not isinstance(packages, list):
        raise LockfileError("Lockfile packages must be a list")
    result: dict[str, dict[str, object]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise LockfileError("Lockfile package entries must be objects")
        app_name = package.get("application_name")
        if not isinstance(app_name, str):
            raise LockfileError("Lockfile package is missing application_name")
        result[app_name] = package
    return result


def _plans_by_app(plan: dict[str, object]) -> dict[str, dict[str, object]]:
    result = {}
    for package_plan in _package_plans(plan):
        package = _dict(package_plan.get("package"))
        app_name = package.get("application_name")
        if isinstance(app_name, str):
            result[app_name] = package_plan
    return result


def _root_application_name(plan: dict[str, object]) -> object:
    package = _dict(plan.get("package"))
    return package.get("application_name")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
