from __future__ import annotations

from dataclasses import asdict
from .environment import DeploymentPolicy
from .errors import ManifestError
from .manifest import PackageManifest
from .provenance import Provenance
from .source import PackageSource


CORE_UNINSTALL_SCRIPT = "Deployment_Manifests/uninstall.core.sql"


def create_plan(
    *,
    mode: str,
    source: PackageSource,
    provenance: Provenance,
    environment: DeploymentPolicy,
    installed_state: dict[str, str] | None = None,
    reverse_dependencies: list[str] | None = None,
    allow_destructive: bool = False,
    confirm_delete_system: bool = False,
    approve: bool = False,
) -> dict[str, object]:
    manifest = source.manifest
    policy = environment.evaluate(
        mode,
        dirty=provenance.dirty,
        allow_destructive=allow_destructive,
        approve=approve,
    )
    policy = _apply_core_reinstall_policy(
        policy,
        mode=mode,
        manifest=manifest,
        confirm_delete_system=confirm_delete_system,
    )
    script = _script_for_mode(mode, manifest)
    if mode in {"bootstrap-core", "install", "reinstall", "resume", "upgrade", "validate"} and not script:
        raise ManifestError(f"No script is declared for deployment mode `{mode}`")

    return {
        "schema_version": "dbpm.plan.v0",
        "mode": mode,
        "package": _package_dict(manifest),
        "source": {
            "type": source.source_type,
            "path": source.display_path,
            "root": source.root,
            "manifest": source.manifest_name,
            "registry_url": source.registry_url,
            "registry_package": source.registry_package,
            "registry_constraint": source.registry_constraint,
        },
        "core": {
            "required": not manifest.is_core,
            "minimum_version": manifest.core_minimum_version,
            "bootstrap": mode == "bootstrap-core",
        },
        "dependencies": [asdict(dependency) for dependency in manifest.dependencies],
        "reverse_dependencies": reverse_dependencies or [],
        "installed_state": installed_state,
        "warnings": source.warnings or [],
        "provenance": provenance.as_dict(),
        "policy": policy,
        "pre_actions": _pre_actions_for_mode(mode, manifest, source, provenance, installed_state),
        "post_actions": _post_actions_for_mode(mode, manifest, source, provenance, installed_state),
        "execution": {
            "script": script,
            "script_ref": str(source.resolve_script_path(script)) if script else None,
            "arguments": _script_arguments_for_mode(mode, provenance) if script else [],
        },
    }


def _package_dict(manifest: PackageManifest) -> dict[str, object]:
    return {
        "name": manifest.name,
        "application_name": manifest.application_name,
        "version": manifest.version,
        "description": manifest.description,
        "vendor": manifest.vendor,
        "license": manifest.license,
        "database": {
            "platform": manifest.database_platform,
            "minimum_version": manifest.database_minimum_version,
        },
    }


def _apply_core_reinstall_policy(
    policy: dict[str, object],
    *,
    mode: str,
    manifest: PackageManifest,
    confirm_delete_system: bool,
) -> dict[str, object]:
    if mode != "reinstall" or not manifest.is_core or confirm_delete_system:
        return policy

    updated = dict(policy)
    approvals = list(updated.get("required_approvals", []))
    approvals.append("Core reinstall requires --confirm-delete-system CORE")
    updated["required_approvals"] = approvals
    updated["result"] = "blocked" if updated.get("blocked") else "requires-approval"
    return updated


def _script_for_mode(mode: str, manifest: PackageManifest) -> str | None:
    if mode in {"install", "reinstall", "resume", "bootstrap-core"}:
        return manifest.scripts.install
    if mode == "upgrade":
        return manifest.scripts.upgrade
    if mode == "validate":
        return manifest.scripts.validate
    return None


def _script_arguments_for_mode(mode: str, provenance: Provenance) -> list[str]:
    if mode == "validate":
        return []
    return [provenance.commit]


def _pre_actions_for_mode(
    mode: str,
    manifest: PackageManifest,
    source: PackageSource,
    provenance: Provenance,
    installed_state: dict[str, str] | None,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if mode == "reinstall":
        if manifest.is_core:
            actions.extend(
                [
                    {
                        "type": "delete_system",
                    },
                    {
                        "type": "execute_script",
                        "script": CORE_UNINSTALL_SCRIPT,
                        "script_ref": str(source.resolve_script_path(CORE_UNINSTALL_SCRIPT)),
                        "arguments": [],
                    },
                ]
            )
        else:
            actions.append(
                {
                    "type": "delete_application",
                    "application_name": manifest.application_name,
                    "fail_on_not_found": "N",
                }
            )
    if mode in {"install", "reinstall", "resume", "upgrade"} and _can_stage_provenance(
        mode,
        manifest,
        installed_state,
    ):
        actions.append(
            {
                "type": "stage_deployment_provenance",
                "payload": _deployment_provenance_payload(
                    mode=mode,
                    manifest=manifest,
                    source=source,
                    provenance=provenance,
                    installed_state=installed_state,
                ),
            }
        )
    return actions


def _post_actions_for_mode(
    mode: str,
    manifest: PackageManifest,
    source: PackageSource,
    provenance: Provenance,
    installed_state: dict[str, str] | None,
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if mode in {"bootstrap-core", "reinstall"} and _can_record_core_post_deploy_provenance(manifest):
        actions.append(
            {
                "type": "record_deployment_provenance",
                "payload": _deployment_provenance_payload(
                    mode=mode,
                    manifest=manifest,
                    source=source,
                    provenance=provenance,
                    installed_state=installed_state,
                ),
            }
        )
    return actions


def _can_stage_provenance(
    mode: str,
    manifest: PackageManifest,
    installed_state: dict[str, str] | None,
) -> bool:
    if not manifest.is_core:
        return True
    if mode != "upgrade" or installed_state is None:
        return False
    installed_version = installed_state.get("version")
    if installed_version is None:
        return False
    return _parse_semver(installed_version) >= (3, 2, 0)


def _can_record_core_post_deploy_provenance(manifest: PackageManifest) -> bool:
    return manifest.is_core and _parse_semver(manifest.version) >= (3, 4, 0)


def _deployment_provenance_payload(
    *,
    mode: str,
    manifest: PackageManifest,
    source: PackageSource,
    provenance: Provenance,
    installed_state: dict[str, str] | None,
) -> dict[str, object]:
    artifact = provenance.artifact
    coordinate = _package_coordinate(artifact)
    payload: dict[str, object] = {
        "application_name": manifest.application_name,
        "version": manifest.version,
        "deployment_type": _deployment_type_for_mode(mode, manifest, installed_state),
        "deploy_commit_hash": provenance.commit,
        "artifact_uri": source.display_path,
        "artifact_checksum": source.artifact_checksum,
        "artifact_checksum_alg": source.artifact_checksum_alg,
        "artifact_signature_url": source.artifact_signature_url,
        "publisher_key_fingerprint": source.publisher_key_fingerprint,
        "artifact_file_name": source.path.name if source.is_zip else None,
        "artifact_repository_type": "file" if source.is_zip else "local",
        "artifact_group_id": artifact.get("artifact.groupId"),
        "artifact_id": artifact.get("artifact.artifactId"),
        "artifact_version": artifact.get("artifact.version"),
        "artifact_classifier": artifact.get("artifact.classifier"),
        "artifact_extension": artifact.get("artifact.extension") or ("zip" if source.is_zip else None),
        "package_coordinate": coordinate,
        "source_repository_url": artifact.get("git.remote.origin.url"),
        "source_commit_hash": provenance.commit,
        "source_path": source.display_path,
        "build_id": artifact.get("build.id"),
        "build_url": artifact.get("build.url"),
        "build_time": artifact.get("build.time"),
        "build_metadata_json": {
            "source": provenance.source,
            "dirty": provenance.dirty,
            "artifact": artifact,
        },
    }
    return payload


def _deployment_type_for_mode(
    mode: str,
    manifest: PackageManifest,
    installed_state: dict[str, str] | None,
) -> str:
    if mode in {"install", "reinstall", "resume"}:
        return "I"
    if mode == "bootstrap-core":
        return "I"
    if mode == "upgrade" and installed_state:
        installed_version = installed_state.get("version")
        if installed_version:
            installed_major, installed_minor, _ = _parse_semver(installed_version)
            target_major, target_minor, _ = _parse_semver(manifest.version)
            if target_major > installed_major:
                return "V"
            if target_minor > installed_minor:
                return "M"
    return "P"


def _parse_semver(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3:
        raise ManifestError(f"Version must be major.minor.patch: {value}")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise ManifestError(f"Version must be numeric: {value}") from exc


def _package_coordinate(artifact: dict[str, str]) -> str | None:
    group_id = artifact.get("artifact.groupId")
    artifact_id = artifact.get("artifact.artifactId")
    version = artifact.get("artifact.version")
    if group_id and artifact_id and version:
        return f"{group_id}:{artifact_id}:{version}"
    return None
