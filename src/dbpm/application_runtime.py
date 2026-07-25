from __future__ import annotations

import json
import os
import subprocess
import tempfile
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, TextIO

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


@dataclass(frozen=True)
class StagedApplicationRuntime:
    path: Path
    payload_root: Path
    log_files: tuple[Path, ...]


def validate_application_runtime_graph(
    graph: dict[str, object],
    *,
    prefix: Path,
    log_dir: Path,
) -> ApplicationRuntimeReceipt:
    root_name = _package_name(graph.get("root_package"), "runtime root package")
    root_version = _nonempty_string(graph.get("root_version"), "runtime root version")
    payloads = graph.get("payloads")
    commands = graph.get("commands")
    if not isinstance(payloads, list) or not isinstance(commands, list):
        raise ExecutionError("Application runtime graph is incomplete")
    _assert_runtime_prefix(prefix)
    receipt = load_application_runtime_receipt(prefix, expected_application=root_name)
    if receipt.application_version != root_version:
        raise ExecutionError(
            f"Application runtime version is {receipt.application_version}; "
            f"expected {root_version}"
        )

    receipt_packages = {package.name: package for package in receipt.packages}
    planned_packages: set[str] = set()
    log_dir.mkdir(parents=True, exist_ok=True)
    for sequence, raw_payload in enumerate(payloads, start=1):
        payload = _mapping(raw_payload, "application runtime payload")
        name = _package_name(payload.get("package"), "runtime payload package")
        planned_packages.add(name)
        installed = receipt_packages.get(name)
        if installed is None:
            raise ExecutionError(f"Application runtime receipt is missing package `{name}`")
        version = _nonempty_string(payload.get("version"), f"runtime payload {name} version")
        path = _safe_relative_path(payload.get("payload_path"), f"runtime payload {name} path")
        artifact = _mapping(payload.get("artifact"), f"runtime payload {name} artifact")
        expected = (
            version,
            path,
            str(artifact.get("commit") or ""),
            str(artifact.get("uri") or ""),
            str(artifact.get("checksum")) if artifact.get("checksum") else None,
            str(artifact.get("checksum_alg")) if artifact.get("checksum_alg") else None,
        )
        actual = (
            installed.version,
            installed.path,
            installed.commit,
            installed.artifact_uri,
            installed.artifact_checksum,
            installed.artifact_checksum_alg,
        )
        if actual != expected:
            raise ExecutionError(f"Application runtime package `{name}` does not match the plan")
        package_prefix = prefix / path
        if not package_prefix.is_dir():
            raise ExecutionError(f"Application runtime payload is missing: {package_prefix}")
        script = _validation_script(payload)
        if script is not None:
            log_file = log_dir / f"{sequence:03d}-{name}-runtime-validate.log"
            environment = dict(os.environ)
            environment.update(
                {
                    "DBPM_RUNTIME_PREFIX": str(prefix.resolve()),
                    "DBPM_RUNTIME_PACKAGE_PREFIX": str(package_prefix.resolve()),
                    "DBPM_RUNTIME_MODE": "validate",
                    "DBPM_ROOT_PACKAGE_NAME": root_name,
                    "DBPM_ROOT_PACKAGE_VERSION": root_version,
                    "DBPM_PACKAGE_NAME": name,
                    "DBPM_PACKAGE_VERSION": version,
                    "DBPM_INSTALLED_VERSION": installed.version,
                    "DBPM_COMMIT_HASH": installed.commit,
                    "DBPM_ARTIFACT_URL": installed.artifact_uri,
                    "DBPM_ARTIFACT_SHA256": (
                        installed.artifact_checksum or ""
                        if installed.artifact_checksum_alg == "SHA-256"
                        else ""
                    ),
                }
            )
            returncode = _run_runtime_script(
                Path(_nonempty_string(script.get("ref"), f"runtime payload {name} validate script")),
                cwd=Path(_nonempty_string(payload.get("package_root"), f"runtime payload {name} package_root")),
                environment=environment,
                log_file=log_file,
            )
            if returncode != 0:
                raise ExecutionError(
                    f"Runtime validation script for {name} failed with exit code "
                    f"{returncode}; see {log_file}"
                )
    extra_packages = set(receipt_packages).difference(planned_packages)
    if extra_packages:
        raise ExecutionError(
            "Application runtime receipt contains unplanned packages: "
            + ", ".join(sorted(extra_packages))
        )

    expected_commands = {
        _command_name(command.get("name"), "runtime command name"): (
            _package_name(command.get("package"), "runtime command package"),
            _command_name(command.get("export"), "runtime command export"),
            _safe_relative_path(command.get("target"), "runtime command target"),
        )
        for command in (_mapping(raw, "application runtime command") for raw in commands)
    }
    receipt_commands = {
        command.name: (command.package, command.export, command.target)
        for command in receipt.commands
    }
    if receipt_commands != expected_commands:
        raise ExecutionError("Application runtime commands do not match the plan")
    bin_path = prefix / "bin"
    actual_names = {item.name for item in bin_path.iterdir()} if bin_path.is_dir() else set()
    if actual_names != set(expected_commands):
        raise ExecutionError("Application runtime bin directory does not match the receipt")
    for name, (_, _, target) in expected_commands.items():
        link = bin_path / name
        if not link.is_symlink():
            raise ExecutionError(f"Application runtime command is not a managed symlink: {link}")
        expected_target = (prefix / target).resolve(strict=True)
        if link.resolve(strict=True) != expected_target or not os.access(expected_target, os.X_OK):
            raise ExecutionError(f"Application runtime command target is invalid: {link}")
    return receipt


def _validation_script(payload: dict[str, Any]) -> dict[str, Any] | None:
    scripts = _mapping(payload.get("scripts"), "application runtime payload scripts")
    script = scripts.get("validate")
    if not isinstance(script, dict) or script.get("ref") is None:
        return None
    return script


def activate_staged_application_runtime(
    graph: dict[str, object],
    staged: StagedApplicationRuntime,
    *,
    prefix: Path,
    mode: str = "install",
) -> ApplicationRuntimeReceipt:
    payloads = graph.get("payloads")
    commands = graph.get("commands")
    if not isinstance(payloads, list) or not isinstance(commands, list):
        raise ExecutionError("Application runtime graph is incomplete")
    root_name = _package_name(graph.get("root_package"), "runtime root package")
    root_version = _nonempty_string(graph.get("root_version"), "runtime root version")

    with application_runtime_lock(prefix):
        receipt_file = application_receipt_path(prefix)
        prior = (
            load_application_runtime_receipt(prefix, expected_application=root_name)
            if receipt_file.exists()
            else None
        )
        generation = prior.generation + 1 if prior else 1
        packages: list[ApplicationRuntimePackage] = []
        promoted: list[Path] = []
        replaced: list[tuple[Path, Path]] = []
        bin_path = prefix / "bin"
        bin_backup = prefix / APPLICATION_RECEIPT_DIR_NAME / f"bin-generation-{generation - 1}"
        staged_bin = staged.path / "bin"
        staged_bin.mkdir()
        bin_activated = False

        for raw_command in commands:
            command = _mapping(raw_command, "application runtime command")
            name = _command_name(command.get("name"), "runtime command name")
            target = _safe_relative_path(command.get("target"), f"runtime command {name} target")
            os.symlink(f"../{target}", staged_bin / name)

        try:
            for raw_payload in payloads:
                payload = _mapping(raw_payload, "application runtime payload")
                name = _package_name(payload.get("package"), "runtime payload package")
                version = _nonempty_string(payload.get("version"), f"runtime payload {name} version")
                relative = _safe_relative_path(payload.get("payload_path"), f"runtime payload {name} path")
                source = staged.path / relative
                destination = prefix / relative
                artifact = _mapping(payload.get("artifact"), f"runtime payload {name} artifact")
                package_record = ApplicationRuntimePackage(
                        name=name,
                        version=version,
                        path=relative,
                        commit=str(artifact.get("commit") or ""),
                        artifact_uri=str(artifact.get("uri") or ""),
                        artifact_checksum=(
                            str(artifact.get("checksum")) if artifact.get("checksum") else None
                        ),
                        artifact_checksum_alg=(
                            str(artifact.get("checksum_alg"))
                            if artifact.get("checksum_alg")
                            else None
                        ),
                    )
                if destination.exists():
                    if mode == "reinstall":
                        backup = (
                            prefix
                            / APPLICATION_RECEIPT_DIR_NAME
                            / "payload-backups"
                            / f"generation-{generation - 1}"
                            / relative
                        )
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        destination.replace(backup)
                        replaced.append((destination, backup))
                        source.replace(destination)
                        promoted.append(destination)
                        packages.append(package_record)
                        continue
                    prior_package = (
                        next((item for item in prior.packages if item.name == name), None)
                        if prior
                        else None
                    )
                    if prior_package != package_record:
                        raise ExecutionError(
                            f"Runtime payload path exists with different identity: {destination}"
                        )
                    shutil.rmtree(source)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(destination)
                    promoted.append(destination)
                packages.append(package_record)

            if bin_path.exists():
                if prior is None:
                    raise ExecutionError(
                        f"Application runtime bin directory is not managed by dbpm: {bin_path}"
                    )
                if bin_backup.exists():
                    raise ExecutionError(f"Runtime activation backup already exists: {bin_backup}")
                bin_path.replace(bin_backup)
            staged_bin.replace(bin_path)
            bin_activated = True
            receipt = ApplicationRuntimeReceipt(
                application_name=root_name,
                application_version=root_version,
                generation=generation,
                activated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                lock_schema=None,
                lock_checksum=None,
                packages=tuple(packages),
                commands=tuple(
                    ActivatedRuntimeCommand(
                        name=_command_name(item.get("name"), "runtime command name"),
                        package=_package_name(item.get("package"), "runtime command package"),
                        export=_command_name(item.get("export"), "runtime command export"),
                        target=_safe_relative_path(item.get("target"), "runtime command target"),
                    )
                    for item in (_mapping(raw, "application runtime command") for raw in commands)
                ),
            )
            if prior is not None:
                generation_dir = (
                    prefix
                    / APPLICATION_RECEIPT_DIR_NAME
                    / "generations"
                    / str(prior.generation)
                )
                generation_dir.mkdir(parents=True, exist_ok=True)
                (generation_dir / APPLICATION_RECEIPT_FILE_NAME).write_text(
                    json.dumps(prior.as_dict(), indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            write_application_runtime_receipt(prefix, receipt)
            return receipt
        except Exception:
            if bin_activated and bin_path.exists():
                bin_path.replace(staged_bin)
            if bin_backup.exists():
                bin_backup.replace(bin_path)
            for destination in reversed(promoted):
                source = staged.path / destination.relative_to(prefix)
                source.parent.mkdir(parents=True, exist_ok=True)
                destination.replace(source)
            for destination, backup in reversed(replaced):
                if backup.exists():
                    backup.replace(destination)
            raise


def stage_application_runtime_graph(
    graph: dict[str, object],
    *,
    prefix: Path,
    mode: str,
    log_dir: Path,
    staging_path: Path | None = None,
) -> StagedApplicationRuntime:
    root_package = _nonempty_string(
        graph.get("root_package"),
        "application runtime graph root_package",
    )
    root_version = _nonempty_string(
        graph.get("root_version"),
        "application runtime graph root_version",
    )
    payloads = graph.get("payloads")
    commands = graph.get("commands")
    if not isinstance(payloads, list):
        raise ExecutionError("Application runtime graph payloads must be a list")
    if not isinstance(commands, list):
        raise ExecutionError("Application runtime graph commands must be a list")
    if mode not in {"install", "upgrade", "reinstall", "resume"}:
        raise ExecutionError(f"Application runtime staging does not support mode `{mode}`")
    _assert_runtime_prefix(prefix)
    installed_versions: dict[str, str] = {}
    if application_receipt_path(prefix).exists():
        installed_versions = {
            package.name: package.version
            for package in load_application_runtime_receipt(
                prefix,
                expected_application=root_package,
            ).packages
        }

    log_dir.mkdir(parents=True, exist_ok=True)
    with application_runtime_lock(prefix):
        staging_parent = prefix / APPLICATION_RECEIPT_DIR_NAME / "staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        staging_path = staging_path or Path(
            tempfile.mkdtemp(prefix="generation-", dir=staging_parent)
        )
        staging_path.mkdir(parents=True, exist_ok=True)
        (staging_path / "graph.json").write_text(
            json.dumps(graph, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_stage_status(staging_path, "staging")
        payload_root = staging_path / "packages"
        payload_root.mkdir(exist_ok=True)
        log_files: list[Path] = []

        for sequence, raw_payload in enumerate(payloads, start=1):
            payload = _mapping(raw_payload, "application runtime payload")
            package_name = _package_name(
                payload.get("package"),
                "application runtime payload package",
            )
            package_version = _nonempty_string(
                payload.get("version"),
                f"application runtime payload {package_name} version",
            )
            relative_payload = _safe_relative_path(
                payload.get("payload_path"),
                f"application runtime payload {package_name} path",
            )
            package_prefix = staging_path / relative_payload
            package_prefix.mkdir(parents=True)
            script = _runtime_script_for_mode(payload, mode)
            if script is None:
                continue
            script_path = Path(
                _nonempty_string(
                    script.get("ref"),
                    f"application runtime payload {package_name} script",
                )
            )
            if not script_path.is_file():
                raise ExecutionError(f"Runtime script not found: {script_path}")
            package_root = Path(
                _nonempty_string(
                    payload.get("package_root"),
                    f"application runtime payload {package_name} package_root",
                )
            )
            artifact = _mapping(
                payload.get("artifact"),
                f"application runtime payload {package_name} artifact",
            )
            environment = dict(os.environ)
            environment.update(
                {
                    "DBPM_RUNTIME_PREFIX": str(prefix.resolve()),
                    "DBPM_RUNTIME_PACKAGE_PREFIX": str(package_prefix.resolve()),
                    "DBPM_RUNTIME_MODE": mode,
                    "DBPM_ROOT_PACKAGE_NAME": root_package,
                    "DBPM_ROOT_PACKAGE_VERSION": root_version,
                    "DBPM_PACKAGE_NAME": package_name,
                    "DBPM_PACKAGE_VERSION": package_version,
                    "DBPM_INSTALLED_VERSION": installed_versions.get(package_name, ""),
                    "DBPM_COMMIT_HASH": str(artifact.get("commit") or ""),
                    "DBPM_ARTIFACT_URL": str(artifact.get("uri") or ""),
                    "DBPM_ARTIFACT_SHA256": (
                        str(artifact.get("checksum") or "")
                        if artifact.get("checksum_alg") == "SHA-256"
                        else ""
                    ),
                }
            )
            log_file = log_dir / f"{sequence:03d}-{package_name}-runtime-stage.log"
            log_files.append(log_file)
            returncode = _run_runtime_script(
                script_path,
                cwd=package_root,
                environment=environment,
                log_file=log_file,
            )
            if returncode != 0:
                _write_stage_status(staging_path, "failed")
                raise ExecutionError(
                    f"Runtime script for {package_name} failed with exit code "
                    f"{returncode}; staged files remain in {staging_path}; see {log_file}"
                )

        _validate_staged_commands(commands, staging_path, payloads)
        _write_stage_status(staging_path, "ready")
        return StagedApplicationRuntime(
            path=staging_path,
            payload_root=payload_root,
            log_files=tuple(log_files),
        )


def resume_application_runtime_graph(
    graph: dict[str, object],
    *,
    prefix: Path,
    log_dir: Path,
) -> StagedApplicationRuntime:
    staging_parent = prefix / APPLICATION_RECEIPT_DIR_NAME / "staging"
    expected = json.dumps(graph, sort_keys=True, separators=(",", ":"))
    matches: list[Path] = []
    if staging_parent.is_dir():
        for candidate in staging_parent.iterdir():
            graph_file = candidate / "graph.json"
            status_file = candidate / "status.json"
            if not graph_file.is_file() or not status_file.is_file():
                continue
            try:
                recorded = json.loads(graph_file.read_text(encoding="utf-8"))
                status = json.loads(status_file.read_text(encoding="utf-8")).get("status")
            except (OSError, json.JSONDecodeError):
                continue
            if (
                json.dumps(recorded, sort_keys=True, separators=(",", ":")) == expected
                and status in {"failed", "staging", "ready"}
            ):
                matches.append(candidate)
    if not matches:
        raise ExecutionError("No matching incomplete application runtime generation to resume")
    candidate = max(matches, key=lambda item: item.stat().st_mtime_ns)
    if json.loads((candidate / "status.json").read_text(encoding="utf-8")).get("status") == "ready":
        return StagedApplicationRuntime(
            path=candidate,
            payload_root=candidate / "packages",
            log_files=(),
        )
    payload_root = candidate / "packages"
    if payload_root.exists():
        shutil.rmtree(payload_root)
    return stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode="resume",
        log_dir=log_dir,
        staging_path=candidate,
    )


def _write_stage_status(staging_path: Path, status: str) -> None:
    (staging_path / "status.json").write_text(
        json.dumps({"status": status}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@contextmanager
def application_runtime_lock(prefix: Path) -> Iterator[None]:
    metadata = prefix / APPLICATION_RECEIPT_DIR_NAME
    metadata.mkdir(parents=True, exist_ok=True)
    lock_file = metadata / "lock"
    try:
        descriptor = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ExecutionError(
            f"Another dbpm application runtime operation appears to be active: "
            f"{lock_file}"
        ) from None
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def _assert_runtime_prefix(prefix: Path) -> None:
    if not prefix.is_dir():
        raise ExecutionError(
            f"Application runtime prefix does not exist or is not a directory: {prefix}"
        )
    if not os.access(prefix, os.W_OK):
        raise ExecutionError(
            f"Application runtime prefix is not writable by the current user: {prefix}"
        )


def _runtime_script_for_mode(
    payload: dict[str, Any],
    mode: str,
) -> dict[str, Any] | None:
    scripts = _mapping(payload.get("scripts"), "application runtime payload scripts")
    script_name = "upgrade" if mode == "upgrade" else "install"
    raw_script = scripts.get(script_name)
    if mode == "upgrade" and (
        not isinstance(raw_script, dict) or raw_script.get("ref") is None
    ):
        raw_script = scripts.get("install")
    if not isinstance(raw_script, dict) or raw_script.get("ref") is None:
        return None
    return raw_script


def _run_runtime_script(
    script_path: Path,
    *,
    cwd: Path,
    environment: dict[str, str],
    log_file: Path,
) -> int:
    try:
        mode = script_path.stat().st_mode
        if not mode & 0o111:
            script_path.chmod(mode | 0o100)
    except OSError as exc:
        raise ExecutionError(f"Runtime script is not executable: {script_path}: {exc}") from exc
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        try:
            process = subprocess.Popen(
                [str(script_path)],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
            )
        except OSError as exc:
            raise ExecutionError(f"Cannot execute runtime script {script_path}: {exc}") from exc
        if process.stdout is not None:
            _tee_output(process.stdout, log)
        return process.wait()


def _tee_output(stream: TextIO, log: TextIO) -> None:
    for line in iter(stream.readline, ""):
        log.write(line)
        log.flush()
    stream.close()


def _validate_staged_commands(
    commands: list[object],
    staging_path: Path,
    payloads: list[object],
) -> None:
    package_paths: dict[str, Path] = {}
    for raw_payload in payloads:
        payload = _mapping(raw_payload, "application runtime payload")
        package = _package_name(payload.get("package"), "application runtime payload package")
        relative = _safe_relative_path(
            payload.get("payload_path"),
            f"application runtime payload {package} path",
        )
        package_paths[package] = (staging_path / relative).resolve()

    for raw_command in commands:
        command = _mapping(raw_command, "application runtime command")
        name = _command_name(command.get("name"), "activated runtime command")
        package = _package_name(
            command.get("package"),
            f"runtime command {name} package",
        )
        package_path = package_paths.get(package)
        if package_path is None:
            raise ExecutionError(
                f"Runtime command `{name}` references missing payload `{package}`"
            )
        target = staging_path / _safe_relative_path(
            command.get("target"),
            f"runtime command {name} target",
        )
        try:
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise ExecutionError(
                f"Runtime command `{name}` target does not exist: {target}"
            ) from exc
        if not resolved.is_relative_to(package_path):
            raise ExecutionError(
                f"Runtime command `{name}` target escapes package `{package}` payload"
            )
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ExecutionError(
                f"Runtime command `{name}` target is not an executable file: {target}"
            )


def application_receipt_path(prefix: Path) -> Path:
    return prefix / APPLICATION_RECEIPT_DIR_NAME / APPLICATION_RECEIPT_FILE_NAME


def garbage_collect_application_runtime(
    prefix: Path,
    *,
    retain_generations: int = 1,
) -> tuple[Path, ...]:
    if retain_generations < 0:
        raise ExecutionError("retain_generations must not be negative")
    with application_runtime_lock(prefix):
        return _garbage_collect_application_runtime_unlocked(
            prefix,
            retain_generations=retain_generations,
        )


def _garbage_collect_application_runtime_unlocked(
    prefix: Path,
    *,
    retain_generations: int,
) -> tuple[Path, ...]:
    active = load_application_runtime_receipt(prefix)
    generations_root = prefix / APPLICATION_RECEIPT_DIR_NAME / "generations"
    generation_dirs = sorted(
        (
            item
            for item in generations_root.iterdir()
            if item.is_dir() and item.name.isdigit()
        ),
        key=lambda item: int(item.name),
        reverse=True,
    ) if generations_root.is_dir() else []
    retained = generation_dirs[:retain_generations]
    receipts = [active]
    for directory in retained:
        value = json.loads((directory / APPLICATION_RECEIPT_FILE_NAME).read_text(encoding="utf-8"))
        receipts.append(parse_application_runtime_receipt(value, source=str(directory)))
    referenced = {package.path for receipt in receipts for package in receipt.packages}
    removed: list[Path] = []
    packages_root = prefix / "packages"
    if packages_root.is_dir():
        for package_dir in packages_root.iterdir():
            if not package_dir.is_dir():
                continue
            for version_dir in package_dir.iterdir():
                relative = version_dir.relative_to(prefix).as_posix()
                if version_dir.is_dir() and relative not in referenced:
                    shutil.rmtree(version_dir)
                    removed.append(version_dir)
    for directory in generation_dirs[retain_generations:]:
        shutil.rmtree(directory)
        removed.append(directory)
        bin_backup = prefix / APPLICATION_RECEIPT_DIR_NAME / f"bin-generation-{directory.name}"
        if bin_backup.exists():
            shutil.rmtree(bin_backup)
            removed.append(bin_backup)
        payload_backup = (
            prefix
            / APPLICATION_RECEIPT_DIR_NAME
            / "payload-backups"
            / f"generation-{directory.name}"
        )
        if payload_backup.exists():
            shutil.rmtree(payload_backup)
            removed.append(payload_backup)
    return tuple(removed)


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
