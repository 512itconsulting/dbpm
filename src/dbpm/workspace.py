from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import WorkspaceError
from .manifest import MANIFEST_NAMES, PackageManifest, parse_manifest


WORKSPACE_MANIFEST_NAME = "dbpm-workspace.yaml"


@dataclass(frozen=True)
class WorkspacePackage:
    relative_path: str
    path: Path
    manifest_name: str
    manifest: PackageManifest

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.relative_path,
            "absolute_path": str(self.path),
            "manifest": self.manifest_name,
            "name": self.manifest.name,
            "application_name": self.manifest.application_name,
            "version": self.manifest.version,
        }


@dataclass(frozen=True)
class Workspace:
    root: Path
    manifest_path: Path
    packages: tuple[WorkspacePackage, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_root": str(self.root),
            "manifest": str(self.manifest_path),
            "packages": [package.as_dict() for package in self.packages],
        }


def is_workspace_root(path: Path) -> bool:
    return path.is_dir() and (path / WORKSPACE_MANIFEST_NAME).is_file()


def load_workspace(path: str | Path) -> Workspace:
    root = Path(path).expanduser().resolve()
    manifest_path = root / WORKSPACE_MANIFEST_NAME if root.is_dir() else root
    if manifest_path.name != WORKSPACE_MANIFEST_NAME:
        raise WorkspaceError(f"Workspace manifest must be named {WORKSPACE_MANIFEST_NAME}")
    if not manifest_path.is_file():
        raise WorkspaceError(f"Workspace manifest does not exist: {manifest_path}")
    root = manifest_path.parent

    data = _parse_workspace_yaml(manifest_path.read_text(encoding="utf-8"), manifest_path.name)
    workspace = data.get("workspace") if isinstance(data, dict) else None
    if not isinstance(workspace, dict):
        raise WorkspaceError("Workspace manifest must contain a `workspace` mapping")

    package_values = workspace.get("packages")
    if not isinstance(package_values, list):
        raise WorkspaceError("Workspace manifest must contain `workspace.packages` as a list")
    if not package_values:
        raise WorkspaceError("Workspace manifest must list at least one package")

    seen: set[str] = set()
    packages: list[WorkspacePackage] = []
    for value in package_values:
        if not isinstance(value, str) or not value.strip():
            raise WorkspaceError("Workspace package entries must be non-empty strings")
        relative_path = _normalize_relative_package_path(value)
        key = relative_path.lower()
        if key in seen:
            raise WorkspaceError(f"Duplicate workspace package root: {relative_path}")
        seen.add(key)
        packages.append(_load_workspace_package(root, relative_path))

    return Workspace(root=root, manifest_path=manifest_path, packages=tuple(packages))


def select_workspace_package(workspace: Workspace, selector: str | None) -> WorkspacePackage:
    if selector is None:
        if len(workspace.packages) == 1:
            return workspace.packages[0]
        raise WorkspaceError(
            "Workspace contains multiple packages; use --package or run dbpm workspace list"
        )

    matches = [
        package
        for package in workspace.packages
        if _matches_package_selector(package, selector)
    ]
    if not matches:
        raise WorkspaceError(f"Workspace package not found: {selector}")
    if len(matches) > 1:
        raise WorkspaceError(f"Workspace package selector is ambiguous: {selector}")
    return matches[0]


def workspace_dependency_sources(
    workspace: Workspace | None,
    selected: WorkspacePackage | None,
    explicit_sources: list[str],
) -> list[str]:
    if workspace is None or selected is None:
        return []
    if not selected.manifest.dependencies:
        return []

    explicit_apps = _explicit_source_application_names(explicit_sources)
    selected_app = selected.manifest.application_name
    dependency_sources: list[str] = []
    for package in workspace.packages:
        app_name = package.manifest.application_name
        if app_name == selected_app or app_name in explicit_apps:
            continue
        dependency_sources.append(str(package.path))
    return dependency_sources


def _explicit_source_application_names(raw_sources: list[str]) -> set[str]:
    apps: set[str] = set()
    for raw in raw_sources:
        path = Path(raw).expanduser()
        if not path.exists():
            continue
        manifest = _find_manifest(path.resolve())
        if manifest is None:
            continue
        _, package_manifest = manifest
        apps.add(package_manifest.application_name)
    return apps


def _matches_package_selector(package: WorkspacePackage, selector: str) -> bool:
    normalized = selector.strip()
    return (
        package.manifest.name == normalized
        or package.manifest.name.lower() == normalized.lower()
        or package.manifest.application_name == normalized.upper().replace("-", "_")
    )


def _normalize_relative_package_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute():
        raise WorkspaceError(f"Workspace package path must be relative: {value}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise WorkspaceError(f"Workspace package path must not contain . or ..: {value}")
    return pure.as_posix()


def _load_workspace_package(root: Path, relative_path: str) -> WorkspacePackage:
    package_root = (root / relative_path).resolve()
    try:
        package_root.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"Workspace package escapes workspace root: {relative_path}") from exc
    if not package_root.is_dir():
        raise WorkspaceError(f"Workspace package directory does not exist: {relative_path}")

    manifest = _find_manifest(package_root)
    if manifest is None:
        raise WorkspaceError(f"Workspace package has no dbpm manifest: {relative_path}")
    manifest_name, package_manifest = manifest
    return WorkspacePackage(
        relative_path=relative_path,
        path=package_root,
        manifest_name=manifest_name,
        manifest=package_manifest,
    )


def _find_manifest(package_root: Path) -> tuple[str, PackageManifest] | None:
    if not package_root.is_dir():
        return None
    for name in MANIFEST_NAMES:
        manifest_path = package_root / name
        if manifest_path.is_file():
            text = manifest_path.read_text(encoding="utf-8")
            return name, parse_manifest(text, name)
    return None


def _parse_workspace_yaml(text: str, source_name: str) -> Any:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - PyYAML is a dependency
        raise WorkspaceError("PyYAML is required to parse dbpm-workspace.yaml") from exc
    try:
        return yaml.safe_load(text)
    except Exception as exc:
        raise WorkspaceError(f"Invalid YAML in {source_name}: {exc}") from exc
