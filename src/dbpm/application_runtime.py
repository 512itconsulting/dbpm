from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ExecutionError
from .manifest import PACKAGE_NAME_RE, RUNTIME_COMMAND_NAME_RE


APPLICATION_RECEIPT_SCHEMA = "dbpm.application-runtime.v1"
APPLICATION_RECEIPT_DIR_NAME = ".dbpm"
APPLICATION_RECEIPT_FILE_NAME = "receipt.json"


@dataclass(frozen=True)
class ApplicationRuntimePackage:
    name: str
    version: str
    path: str
    commit: str
    artifact_uri: str
    artifact_checksum: str | None
    artifact_checksum_alg: str | None


@dataclass(frozen=True)
class ActivatedRuntimeCommand:
    name: str
    package: str
    export: str
    target: str


@dataclass(frozen=True)
class ApplicationRuntimeReceipt:
    application_name: str
    application_version: str
    generation: int
    activated_at: str
    lock_schema: str | None
    lock_checksum: str | None
    packages: tuple[ApplicationRuntimePackage, ...]
    commands: tuple[ActivatedRuntimeCommand, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": APPLICATION_RECEIPT_SCHEMA,
            "application": {
                "name": self.application_name,
                "version": self.application_version,
            },
            "generation": self.generation,
            "activated_at": self.activated_at,
            "resolution": {
                "lock_schema": self.lock_schema,
                "lock_checksum": self.lock_checksum,
            },
            "packages": {
                package.name: {
                    "version": package.version,
                    "path": package.path,
                    "commit": package.commit,
                    "artifact": {
                        "uri": package.artifact_uri,
                        "checksum": package.artifact_checksum,
                        "checksum_alg": package.artifact_checksum_alg,
                    },
                }
                for package in self.packages
            },
            "commands": {
                command.name: {
                    "package": command.package,
                    "export": command.export,
                    "target": command.target,
                }
                for command in self.commands
            },
        }


def application_receipt_path(prefix: Path) -> Path:
    return prefix / APPLICATION_RECEIPT_DIR_NAME / APPLICATION_RECEIPT_FILE_NAME


def parse_application_runtime_receipt(
    value: object,
    *,
    source: str = "application runtime receipt",
) -> ApplicationRuntimeReceipt:
    receipt = _mapping(value, source)
    if receipt.get("schema") != APPLICATION_RECEIPT_SCHEMA:
        raise ExecutionError(f"Unsupported application runtime receipt schema in {source}")

    application = _mapping(receipt.get("application"), f"{source} application")
    application_name = _package_name(application.get("name"), f"{source} application name")
    application_version = _nonempty_string(
        application.get("version"),
        f"{source} application version",
    )
    generation = receipt.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ExecutionError(f"{source} generation must be a positive integer")
    activated_at = _nonempty_string(receipt.get("activated_at"), f"{source} activated_at")

    resolution = _mapping(receipt.get("resolution"), f"{source} resolution")
    lock_schema = _optional_string(resolution.get("lock_schema"), f"{source} lock_schema")
    lock_checksum = _optional_string(
        resolution.get("lock_checksum"),
        f"{source} lock_checksum",
    )
    if (lock_schema is None) != (lock_checksum is None):
        raise ExecutionError(
            f"{source} resolution must provide both lock_schema and lock_checksum, "
            "or neither"
        )

    packages_value = _mapping(receipt.get("packages"), f"{source} packages")
    packages: list[ApplicationRuntimePackage] = []
    for raw_name, raw_package in packages_value.items():
        name = _package_name(raw_name, f"{source} package name")
        package = _mapping(raw_package, f"{source} package {name}")
        artifact = _mapping(package.get("artifact"), f"{source} package {name} artifact")
        checksum = _optional_string(
            artifact.get("checksum"),
            f"{source} package {name} artifact checksum",
        )
        checksum_alg = _optional_string(
            artifact.get("checksum_alg"),
            f"{source} package {name} artifact checksum algorithm",
        )
        if (checksum is None) != (checksum_alg is None):
            raise ExecutionError(
                f"{source} package {name} artifact must provide both checksum "
                "and checksum_alg, or neither"
            )
        packages.append(
            ApplicationRuntimePackage(
                name=name,
                version=_nonempty_string(
                    package.get("version"),
                    f"{source} package {name} version",
                ),
                path=_safe_relative_path(
                    package.get("path"),
                    f"{source} package {name} path",
                ),
                commit=_string(package.get("commit"), f"{source} package {name} commit"),
                artifact_uri=_string(
                    artifact.get("uri"),
                    f"{source} package {name} artifact URI",
                ),
                artifact_checksum=checksum,
                artifact_checksum_alg=checksum_alg,
            )
        )
    if application_name not in {package.name for package in packages}:
        raise ExecutionError(
            f"{source} packages do not contain root application `{application_name}`"
        )

    packages_by_name = {package.name: package for package in packages}
    commands_value = _mapping(receipt.get("commands"), f"{source} commands")
    commands: list[ActivatedRuntimeCommand] = []
    for raw_name, raw_command in commands_value.items():
        name = _command_name(raw_name, f"{source} activated command name")
        command = _mapping(raw_command, f"{source} command {name}")
        package_name = _package_name(
            command.get("package"),
            f"{source} command {name} package",
        )
        if package_name not in packages_by_name:
            raise ExecutionError(
                f"{source} command `{name}` references missing package `{package_name}`"
            )
        target = _safe_relative_path(
            command.get("target"),
            f"{source} command {name} target",
        )
        package_path = PurePosixPath(packages_by_name[package_name].path)
        target_path = PurePosixPath(target)
        if target_path != package_path and package_path not in target_path.parents:
            raise ExecutionError(
                f"{source} command `{name}` target is outside package "
                f"`{package_name}` payload"
            )
        commands.append(
            ActivatedRuntimeCommand(
                name=name,
                package=package_name,
                export=_command_name(
                    command.get("export"),
                    f"{source} command {name} export",
                ),
                target=target,
            )
        )

    return ApplicationRuntimeReceipt(
        application_name=application_name,
        application_version=application_version,
        generation=generation,
        activated_at=activated_at,
        lock_schema=lock_schema,
        lock_checksum=lock_checksum,
        packages=tuple(packages),
        commands=tuple(commands),
    )


def load_application_runtime_receipt(
    prefix: Path,
    *,
    expected_application: str | None = None,
) -> ApplicationRuntimeReceipt:
    path = application_receipt_path(prefix)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExecutionError(f"Application runtime receipt does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"Cannot read application runtime receipt {path}: {exc}") from exc
    receipt = parse_application_runtime_receipt(value, source=str(path))
    if expected_application is not None and receipt.application_name != expected_application:
        raise ExecutionError(
            f"Application runtime prefix {prefix} belongs to "
            f"`{receipt.application_name}`, not `{expected_application}`"
        )
    return receipt


def write_application_runtime_receipt(
    prefix: Path,
    receipt: ApplicationRuntimeReceipt,
) -> None:
    path = application_receipt_path(prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExecutionError(f"{field} must be a mapping")
    return value


def _package_name(value: object, field: str) -> str:
    text = _nonempty_string(value, field)
    if not PACKAGE_NAME_RE.fullmatch(text):
        raise ExecutionError(f"{field} is not a valid package name: {text!r}")
    return text


def _command_name(value: object, field: str) -> str:
    text = _nonempty_string(value, field)
    if not RUNTIME_COMMAND_NAME_RE.fullmatch(text):
        raise ExecutionError(f"{field} is not a valid runtime command name: {text!r}")
    return text


def _safe_relative_path(value: object, field: str) -> str:
    text = _nonempty_string(value, field)
    normalized = PurePosixPath(text.replace("\\", "/"))
    if (
        normalized.is_absolute()
        or not normalized.parts
        or normalized.as_posix() in {"", "."}
        or ".." in normalized.parts
        or any(":" in part for part in normalized.parts)
    ):
        raise ExecutionError(f"{field} must be a safe relative path: {text!r}")
    return normalized.as_posix()


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionError(f"{field} must be a non-empty string")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ExecutionError(f"{field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)
