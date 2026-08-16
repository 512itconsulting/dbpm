from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .errors import ManifestError


MANIFEST_NAMES = ("dbpm.yaml", "dbpm.yml", "dbpm.json", "package.dbpm.yaml")
PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
RUNTIME_COMMAND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
STATE_CATEGORIES = frozenset(
    {"config", "secret", "business_data", "work_state", "cache", "log"}
)
NEVER_PURGED_STATE_CATEGORIES = frozenset({"config", "secret"})


@dataclass(frozen=True)
class PublishConfig:
    group: str
    artifact_id: str | None = None


@dataclass(frozen=True)
class ScriptSet:
    install: str | None = None
    upgrade: str | None = None
    upgrade_from: str | None = None
    validate: str | None = None
    uninstall: str | None = None


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str


@dataclass(frozen=True)
class RuntimeCommandExport:
    name: str
    target: str


@dataclass(frozen=True)
class RuntimeCommandAlias:
    export: str
    name: str


@dataclass(frozen=True)
class StatePath:
    path: str
    category: str


@dataclass(frozen=True)
class RuntimeComponent:
    install: str | None
    upgrade: str | None = None
    validate: str | None = None
    uninstall: str | None = None
    command_exports: tuple[RuntimeCommandExport, ...] = ()
    command_aliases: tuple[RuntimeCommandAlias, ...] = ()
    disabled_commands: tuple[str, ...] = ()

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
    dbpm_minimum_version: str | None = None
    publish: PublishConfig | None = None
    runtime: RuntimeComponent | None = None
    state: tuple[StatePath, ...] = ()

    @property
    def is_core(self) -> bool:
        return self.application_name == "CORE"

    @property
    def has_database_component(self) -> bool:
        scripts = self.scripts
        return any((scripts.install, scripts.upgrade, scripts.validate, scripts.uninstall))


def parse_manifest(text: str, source_name: str) -> PackageManifest:
    data = _parse_structured_text(text, source_name)
    if not isinstance(data, dict):
        raise ManifestError(f"{source_name} must contain a mapping at the top level")

    package = _required_mapping(data, "package", source_name)
    database = _optional_mapping(data, "database")
    core = _optional_mapping(data, "core")
    dbpm = _optional_mapping(data, "dbpm")
    scripts = _optional_mapping(data, "scripts")
    publish_data = _optional_mapping(data, "publish")
    runtime_data = data.get("runtime")

    name = _required_string(package, "name", source_name)
    _validate_package_name(name, source_name)
    version = _required_string(package, "version", source_name)
    dependencies = _parse_dependencies(data.get("dependencies", []), source_name)
    dbpm_minimum_version = _optional_string(dbpm, "minimum_version")
    if dbpm_minimum_version is not None:
        _validate_semantic_version(
            dbpm_minimum_version,
            field="dbpm.minimum_version",
            source_name=source_name,
        )

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
        scripts=_parse_scripts(scripts, source_name),
        dbpm_minimum_version=dbpm_minimum_version,
        publish=_parse_publish_config(publish_data, source_name) if publish_data else None,
        runtime=_parse_runtime(runtime_data, source_name) if runtime_data is not None else None,
        state=tuple(_parse_state(data.get("state"), source_name)),
    )


def _validate_semantic_version(value: str, *, field: str, source_name: str) -> None:
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ManifestError(f"{field} in {source_name} must use major.minor.patch")


def normalize_script_path(path: str) -> str:
    if any(char in path for char in "\r\n"):
        raise ManifestError(f"Script paths must not contain control characters: {path!r}")
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = normalized.parts
    if (
        not parts
        or normalized.as_posix() in {"", "."}
        or normalized.is_absolute()
        or ".." in parts
        or any(":" in part for part in parts)
        or parts[0].startswith("@")
    ):
        raise ManifestError(f"Script paths must be package-relative paths: {path!r}")
    return normalized.as_posix()


def _validate_package_name(name: str, source_name: str) -> None:
    if not PACKAGE_NAME_RE.fullmatch(name):
        raise ManifestError(
            f"`package.name` in {source_name} must start with a lowercase letter "
            "and contain only lowercase letters, digits, underscores, or hyphens"
        )


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


def _parse_state(value: Any, source_name: str) -> list[StatePath]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError(f"`state` in {source_name} must be a list")

    entries: list[StatePath] = []
    for item in value:
        if not isinstance(item, dict):
            raise ManifestError(f"Each `state` entry in {source_name} must be a mapping")
        path = _required_string(item, "path", source_name)
        category = _required_string(item, "category", source_name)
        if category not in STATE_CATEGORIES:
            raise ManifestError(
                f"`state` entry for path {path!r} in {source_name} has unknown "
                f"category {category!r}; must be one of {sorted(STATE_CATEGORIES)}"
            )
        entries.append(StatePath(path=_normalize_state_path(path, source_name), category=category))
    return entries


def _normalize_state_path(path: str, source_name: str) -> str:
    if any(char in path for char in "\r\n"):
        raise ManifestError(f"`state` paths must not contain control characters: {path!r}")
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = normalized.parts
    if (
        not parts
        or normalized.as_posix() in {"", "."}
        or normalized.is_absolute()
        or ".." in parts
        or parts[0] not in ("etc", "var")
    ):
        raise ManifestError(
            f"`state` path {path!r} in {source_name} must be a relative path "
            "rooted at etc/ or var/"
        )
    return normalized.as_posix()


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


def _parse_publish_config(data: dict[str, Any], source_name: str) -> PublishConfig:
    group = _required_string(data, "group", source_name)
    return PublishConfig(
        group=group,
        artifact_id=_optional_string(data, "artifact_id"),
    )


def _parse_scripts(data: dict[str, Any], source_name: str) -> ScriptSet:
    upgrade_from = _optional_string(data, "upgrade_from")
    if upgrade_from is not None and not _valid_version_constraint(upgrade_from):
        raise ManifestError(
            f"`scripts.upgrade_from` in {source_name} must be a semantic version "
            f"constraint such as '1.2.0' or '^1.2.0', got: {upgrade_from!r}"
        )
    return ScriptSet(
        install=_optional_script(data, "install"),
        upgrade=_optional_script(data, "upgrade"),
        upgrade_from=upgrade_from,
        validate=_optional_script(data, "validate"),
        uninstall=_optional_script(data, "uninstall"),
    )


def _valid_version_constraint(value: str) -> bool:
    normalized = value.removeprefix("^").removeprefix("~")
    parts = normalized.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _optional_script(data: dict[str, Any], key: str) -> str | None:
    value = _optional_string(data, key)
    return None if value is None else normalize_script_path(value)


def _parse_runtime(data: Any, source_name: str) -> RuntimeComponent:
    if not isinstance(data, dict):
        raise ManifestError(f"`runtime` in {source_name} must be a mapping")
    removed = [field for field in ("name", "home_env", "into", "layout") if field in data]
    if removed:
        fields = ", ".join(f"`runtime.{field}`" for field in removed)
        raise ManifestError(
            f"{fields} in {source_name} are not part of the composable runtime "
            "manifest; declare package-local scripts, exports, or root activation"
        )

    scripts = _optional_mapping(data, "scripts")
    exports = _optional_mapping(data, "exports")
    activation = _optional_mapping(data, "activation")
    activation_commands = _optional_mapping(activation, "commands")
    command_exports = _parse_runtime_command_exports(
        exports.get("commands"),
        source_name,
    )
    command_aliases = _parse_runtime_command_aliases(
        activation_commands.get("aliases"),
        source_name,
    )
    disabled_commands = _parse_disabled_runtime_commands(
        activation_commands.get("disabled"),
        source_name,
    )
    overlap = {alias.export for alias in command_aliases}.intersection(disabled_commands)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise ManifestError(
            f"Runtime command exports cannot be both aliased and disabled in "
            f"{source_name}: {names}"
        )
    install = _optional_script(scripts, "install")
    if command_exports and install is None:
        raise ManifestError(
            f"`runtime.scripts.install` is required when "
            f"`runtime.exports.commands` are declared in {source_name}"
        )

    return RuntimeComponent(
        install=install,
        upgrade=_optional_script(scripts, "upgrade"),
        validate=_optional_script(scripts, "validate"),
        uninstall=_optional_script(scripts, "uninstall"),
        command_exports=tuple(command_exports),
        command_aliases=tuple(command_aliases),
        disabled_commands=tuple(disabled_commands),
    )


def _parse_runtime_command_exports(
    value: Any,
    source_name: str,
) -> list[RuntimeCommandExport]:
    if value is None:
        return []
    if not isinstance(value, dict):
        raise ManifestError(
            f"`runtime.exports.commands` in {source_name} must be a mapping"
        )
    exports: list[RuntimeCommandExport] = []
    for raw_name, raw_target in value.items():
        name = str(raw_name)
        _validate_runtime_command_name(
            name,
            field="runtime.exports.commands",
            source_name=source_name,
        )
        if raw_target is None or str(raw_target).strip() == "":
            raise ManifestError(
                f"Command export `{name}` in {source_name} requires a target path"
            )
        exports.append(
            RuntimeCommandExport(
                name=name,
                target=normalize_script_path(str(raw_target)),
            )
        )
    return exports


def _parse_runtime_command_aliases(
    value: Any,
    source_name: str,
) -> list[RuntimeCommandAlias]:
    if value is None:
        return []
    if not isinstance(value, dict):
        raise ManifestError(
            f"`runtime.activation.commands.aliases` in {source_name} must be a mapping"
        )
    aliases: list[RuntimeCommandAlias] = []
    activated_names: set[str] = set()
    for raw_export, raw_name in value.items():
        export = _validate_canonical_runtime_export(str(raw_export), source_name)
        name = str(raw_name)
        _validate_runtime_command_name(
            name,
            field="runtime.activation.commands.aliases",
            source_name=source_name,
        )
        if name in activated_names:
            raise ManifestError(
                f"Runtime command alias `{name}` is assigned more than once in "
                f"{source_name}"
            )
        activated_names.add(name)
        aliases.append(RuntimeCommandAlias(export=export, name=name))
    return aliases


def _parse_disabled_runtime_commands(value: Any, source_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError(
            f"`runtime.activation.commands.disabled` in {source_name} must be a list"
        )
    disabled: list[str] = []
    for raw_export in value:
        if isinstance(raw_export, (dict, list)) or raw_export is None:
            raise ManifestError(
                f"Each disabled runtime command in {source_name} must be a "
                "canonical `<package>.<export>` string"
            )
        export = _validate_canonical_runtime_export(str(raw_export), source_name)
        if export in disabled:
            raise ManifestError(
                f"Disabled runtime command `{export}` is repeated in {source_name}"
            )
        disabled.append(export)
    return disabled


def _validate_canonical_runtime_export(value: str, source_name: str) -> str:
    package_name, separator, export_name = value.partition(".")
    if (
        not separator
        or not PACKAGE_NAME_RE.fullmatch(package_name)
        or not RUNTIME_COMMAND_NAME_RE.fullmatch(export_name)
    ):
        raise ManifestError(
            f"Runtime command export reference in {source_name} must use canonical "
            f"`<package>.<export>` form, got: {value!r}"
        )
    return value


def _validate_runtime_command_name(
    value: str,
    *,
    field: str,
    source_name: str,
) -> None:
    if not RUNTIME_COMMAND_NAME_RE.fullmatch(value):
        raise ManifestError(
            f"`{field}` command names in {source_name} must start with a letter "
            "or digit and contain only letters, digits, dots, underscores, or hyphens"
        )

def _application_name(name: str) -> str:
    return name.replace("-", "_").upper()


def _parse_simple_yaml(text: str, source_name: str) -> dict[str, Any]:
    """Parse the small YAML subset used by the MVP manifest examples."""
    root: dict[str, Any] = {}
    current_map: dict[str, Any] | None = None
    current_list: list[dict[str, Any]] | None = None
    current_item: dict[str, Any] | None = None
    current_submap: dict[str, Any] | None = None

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
                if key in ("dependencies", "state"):
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
            current_submap = None
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
            if value is None:
                current_submap = {}
                current_map[key] = current_submap
            else:
                current_map[key] = _yaml_scalar(value)
                current_submap = None
        elif indent == 4:
            key, value = _split_yaml_pair(stripped, source_name)
            if current_item is not None:
                current_item[key] = _yaml_scalar(value)
            elif current_submap is not None:
                current_submap[key] = _yaml_scalar(value)
            else:
                raise ManifestError(f"Unexpected nested item in {source_name}: {raw_line}")
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
