from __future__ import annotations

from dataclasses import asdict

from .environment import EnvironmentPolicy
from .errors import ManifestError
from .manifest import PackageManifest
from .provenance import Provenance
from .source import PackageSource


def create_plan(
    *,
    mode: str,
    source: PackageSource,
    provenance: Provenance,
    environment: EnvironmentPolicy,
    installed_state: dict[str, str] | None = None,
    allow_destructive: bool = False,
    approve: bool = False,
) -> dict[str, object]:
    manifest = source.manifest
    policy = environment.evaluate(
        mode,
        dirty=provenance.dirty,
        allow_destructive=allow_destructive,
        approve=approve,
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
        },
        "core": {
            "required": not manifest.is_core,
            "minimum_version": manifest.core_minimum_version,
            "bootstrap": mode == "bootstrap-core",
        },
        "dependencies": [asdict(dependency) for dependency in manifest.dependencies],
        "installed_state": installed_state,
        "provenance": provenance.as_dict(),
        "policy": policy,
        "pre_actions": _pre_actions_for_mode(mode, manifest),
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


def _pre_actions_for_mode(mode: str, manifest: PackageManifest) -> list[dict[str, str]]:
    if mode == "reinstall":
        return [
            {
                "type": "delete_application",
                "application_name": manifest.application_name,
                "fail_on_not_found": "N",
            }
        ]
    return []
