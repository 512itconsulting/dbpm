from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .errors import ManifestError


MANIFEST_NAMES = ("dbpm.yaml", "dbpm.yml", "dbpm.json", "package.dbpm.yaml")


@dataclass(frozen=True)
class ScriptSet:
    install: str | None = None
    upgrade: str | None = None
    validate: str | None = None
    uninstall: str | None = None


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str


@dataclass(frozen=True)
class PackageManifest:
    name: str
    version: str
    application_name: str
    description: str | None
    vendor: str | None
    license: str | None
    database_platform: str
    database_minimum_version: str | None
    core_minimum_version: str | None
    dependencies: tuple[Dependency, ...]
    scripts: ScriptSet

    @property
    def is_core(self) -> bool:
        return self.application_name == "CORE"


def parse_manifest(text: str, source_name: str) -> PackageManifest:
    data = _parse_structured_text(text, source_name)
    if not isinstance(data, dict):
        raise ManifestError(f"{source_name} must contain a mapping at the top level")

    package = _required_mapping(data, "package", source_name)
    database = _optional_mapping(data, "database")
    core = _optional_mapping(data, "core")
    scripts = _optional_mapping(data, "scripts")

    name = _required_string(package, "name", source_name)
    version = _required_string(package, "version", source_name)
    dependencies = _parse_dependencies(data.get("dependencies", []), source_name)

    return PackageManifest(
        name=name,
        version=version,
        application_name=_application_name(name),
        description=_optional_string(package, "description"),
        vendor=_optional_string(package, "vendor"),
        license=_optional_string(package, "license"),
        database_platform=_optional_string(database, "platform") or "oracle",
        database_minimum_version=_optional_string(database, "minimum_version"),
        core_minimum_version=_optional_string(core, "minimum_version"),
        dependencies=tuple(dependencies),
        scripts=ScriptSet(
            install=_optional_script(scripts, "install"),
            upgrade=_optional_script(scripts, "upgrade"),
            validate=_optional_script(scripts, "validate"),
            uninstall=_optional_script(scripts, "uninstall"),
        ),
    )


def normalize_script_path(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _parse_structured_text(text: str, source_name: str) -> Any:
    if source_name.endswith(".json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Invalid JSON in {source_name}: {exc}") from exc

    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _parse_simple_yaml(text, source_name)

    try:
        return yaml.safe_load(text)
    except Exception as exc:  # pragma: no cover - depends on optional PyYAML
        raise ManifestError(f"Invalid YAML in {source_name}: {exc}") from exc


def _parse_dependencies(value: Any, source_name: str) -> list[Dependency]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError(f"`dependencies` in {source_name} must be a list")

    dependencies: list[Dependency] = []
    for item in value:
        if not isinstance(item, dict):
            raise ManifestError(f"Each dependency in {source_name} must be a mapping")
        dependencies.append(
            Dependency(
                name=_required_string(item, "name", source_name),
                version=_required_string(item, "version", source_name),
            )
        )
    return dependencies


def _required_mapping(data: dict[str, Any], key: str, source_name: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ManifestError(f"`{key}` mapping is required in {source_name}")
    return value


def _optional_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _required_string(data: dict[str, Any], key: str, source_name: str) -> str:
    value = data.get(key)
    if value is None or str(value).strip() == "":
        raise ManifestError(f"`{key}` is required in {source_name}")
    return str(value)


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return None if value is None else str(value)


def _optional_script(data: dict[str, Any], key: str) -> str | None:
    value = _optional_string(data, key)
    return None if value is None else normalize_script_path(value)


def _application_name(name: str) -> str:
    return name.replace("-", "_").upper()


def _parse_simple_yaml(text: str, source_name: str) -> dict[str, Any]:
    """Parse the small YAML subset used by the MVP manifest examples."""
    root: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None
    current_list: list[dict[str, Any]] | None = None
    current_item: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        raw_line = raw_line.lstrip("\ufeff")
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            key, value = _split_yaml_pair(stripped, source_name)
            if value is None:
                if key == "dependencies":
                    current_list = []
                    root[key] = current_list
                    current_map = None
                else:
                    current_map = {}
                    root[key] = current_map
                    current_list = None
                current_item = None
            else:
                root[key] = _yaml_scalar(value)
                current_map = None
                current_list = None
                current_item = None
        elif indent == 2 and stripped.startswith("- "):
            if current_list is None:
                raise ManifestError(f"Unexpected list item in {source_name}: {raw_line}")
            current_item = {}
            current_list.append(current_item)
            rest = stripped[2:].strip()
            if rest:
                key, value = _split_yaml_pair(rest, source_name)
                current_item[key] = _yaml_scalar(value)
        elif indent == 2:
            if current_map is None:
                raise ManifestError(f"Unexpected mapping item in {source_name}: {raw_line}")
            key, value = _split_yaml_pair(stripped, source_name)
            current_map[key] = _yaml_scalar(value)
        elif indent == 4:
            if current_item is None:
                raise ManifestError(f"Unexpected nested item in {source_name}: {raw_line}")
            key, value = _split_yaml_pair(stripped, source_name)
            current_item[key] = _yaml_scalar(value)
        else:
            raise ManifestError(f"Unsupported YAML indentation in {source_name}: {raw_line}")

    return root


def _split_yaml_pair(text: str, source_name: str) -> tuple[str, str | None]:
    if ":" not in text:
        raise ManifestError(f"Expected key/value pair in {source_name}: {text}")
    key, value = text.split(":", 1)
    value = value.strip()
    return key.strip(), None if value == "" else value


def _yaml_scalar(value: str | None) -> str | None:
    if value is None:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
