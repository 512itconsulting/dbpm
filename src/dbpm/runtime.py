from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, TextIO

from .errors import ExecutionError


RECEIPT_SCHEMA = "dbpm.receipt.v0"
RECEIPT_DIR_NAME = ".dbpm"
RECEIPT_FILE_NAME = "receipt.json"
LOCK_FILE_NAME = "lock"


def resolve_runtime_prefix(runtime: dict[str, object], prefix_override: str | None) -> Path:
    name = str(runtime.get("name") or "runtime")
    home_env = str(runtime.get("home_env") or "")
    raw = prefix_override or (os.environ.get(home_env) if home_env else None)
    if not raw:
        raise ExecutionError(
            f"Runtime component `{name}` requires a target prefix; "
            f"set {home_env} or pass --runtime-prefix"
        )
    prefix = Path(raw).expanduser().resolve()
    if not prefix.is_dir():
        raise ExecutionError(
            f"Runtime prefix does not exist or is not a directory: {prefix}. "
            "Creating the prefix is an operator prerequisite; dbpm does not create it."
        )
    if not os.access(prefix, os.W_OK):
        raise ExecutionError(f"Runtime prefix is not writable by the current user: {prefix}")
    return prefix


def receipt_path(prefix: Path) -> Path:
    return prefix / RECEIPT_DIR_NAME / RECEIPT_FILE_NAME


def load_receipt(prefix: Path, runtime_name: str) -> dict[str, object]:
    path = receipt_path(prefix)
    if not path.exists():
        return {"schema": RECEIPT_SCHEMA, "runtime": runtime_name, "packages": {}}
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"Cannot read runtime receipt {path}: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ExecutionError(f"Unsupported runtime receipt schema in {path}")
    if receipt.get("runtime") != runtime_name:
        raise ExecutionError(
            f"Runtime prefix {prefix} is owned by runtime `{receipt.get('runtime')}`, "
            f"not `{runtime_name}`"
        )
    if not isinstance(receipt.get("packages"), dict):
        raise ExecutionError(f"Runtime receipt packages must be a mapping in {path}")
    return receipt


def write_receipt(prefix: Path, receipt: dict[str, object]) -> None:
    path = receipt_path(prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


@contextmanager
def receipt_lock(prefix: Path) -> Iterator[None]:
    lock_dir = prefix / RECEIPT_DIR_NAME
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / LOCK_FILE_NAME
    try:
        descriptor = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ExecutionError(
            f"Another dbpm deployment appears to be running for this prefix; "
            f"remove the lock file if no deployment is active: {lock_file}"
        ) from None
    try:
        os.write(descriptor, f"{os.getpid()}\n".encode("utf-8"))
        os.close(descriptor)
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def execute_runtime_step(
    runtime: dict[str, object],
    *,
    log_file: Path,
    prefix_override: str | None = None,
) -> None:
    environment = runtime.get("environment")
    if not isinstance(environment, dict):
        raise ExecutionError("Runtime plan step does not contain an environment mapping")
    mode = str(environment.get("DBPM_RUNTIME_MODE") or "")
    package_name = str(environment.get("DBPM_PACKAGE_NAME") or "")
    target_version = str(environment.get("DBPM_PACKAGE_VERSION") or "")
    script_ref = runtime.get("script_ref")
    if not script_ref:
        raise ExecutionError("Runtime plan step does not contain an executable script")
    script_path = Path(str(script_ref))
    if not script_path.is_file():
        raise ExecutionError(f"Runtime script not found: {script_path}")

    prefix = resolve_runtime_prefix(runtime, prefix_override)
    runtime_name = str(runtime.get("name") or "")

    with receipt_lock(prefix):
        receipt = load_receipt(prefix, runtime_name)
        packages = receipt["packages"]
        assert isinstance(packages, dict)
        entry = packages.get(package_name)
        entry = entry if isinstance(entry, dict) else None
        _assert_receipt_allows_mode(
            mode,
            entry,
            package_name=package_name,
            target_version=target_version,
            prefix=prefix,
        )

        env = dict(os.environ)
        env.update({key: str(value) for key, value in environment.items()})
        env["DBPM_RUNTIME_PREFIX"] = str(prefix)
        env["DBPM_INSTALLED_VERSION"] = _installed_version(entry) or ""

        returncode = _run_script(
            script_path,
            cwd=str(runtime.get("package_root") or script_path.parent),
            env=env,
            log_file=log_file,
        )

        if mode != "validate":
            packages[package_name] = _receipt_entry(
                runtime,
                environment,
                mode=mode,
                status="complete" if returncode == 0 else "failed",
                previous_entry=entry,
            )
            write_receipt(prefix, receipt)

        if returncode != 0:
            raise ExecutionError(
                f"Runtime script failed with exit code {returncode}; see {log_file}"
            )


def _installed_version(entry: dict[str, object] | None) -> str | None:
    if entry is None:
        return None
    if entry.get("status") == "complete":
        version = entry.get("version")
        return str(version) if version else None
    previous = entry.get("previous_version")
    return str(previous) if previous else None


def _assert_receipt_allows_mode(
    mode: str,
    entry: dict[str, object] | None,
    *,
    package_name: str,
    target_version: str,
    prefix: Path,
) -> None:
    if mode in {"reinstall", "resume"}:
        return

    if mode == "install":
        if entry is not None and entry.get("status") == "complete":
            raise ExecutionError(
                f"Runtime component of {package_name} version {entry.get('version')} "
                f"is already installed in {prefix}; use upgrade or reinstall"
            )
        return

    if mode == "validate":
        if entry is None or entry.get("status") != "complete":
            raise ExecutionError(
                f"Runtime component of {package_name} is not installed in {prefix}; "
                "validate requires a completed runtime install"
            )
        return

    if mode == "upgrade":
        if entry is None or entry.get("status") != "complete":
            raise ExecutionError(
                f"Runtime component of {package_name} is not installed in {prefix}; "
                "use install or resume before upgrade"
            )
        installed_version = str(entry.get("version") or "")
        comparison = _compare_versions(installed_version, target_version)
        if comparison == 0:
            raise ExecutionError(
                f"Runtime component of {package_name} version {target_version} "
                f"is already installed in {prefix}; no upgrade needed"
            )
        if comparison is not None and comparison > 0:
            raise ExecutionError(
                f"Cannot downgrade runtime component of {package_name} "
                f"from {installed_version} to {target_version} in {prefix}"
            )
        return


def _compare_versions(a: str, b: str) -> int | None:
    try:
        parts_a = tuple(int(part) for part in a.split("."))
        parts_b = tuple(int(part) for part in b.split("."))
    except ValueError:
        return None
    length = max(len(parts_a), len(parts_b))
    parts_a = parts_a + (0,) * (length - len(parts_a))
    parts_b = parts_b + (0,) * (length - len(parts_b))
    return (parts_a > parts_b) - (parts_a < parts_b)


def _receipt_entry(
    runtime: dict[str, object],
    environment: dict[str, object],
    *,
    mode: str,
    status: str,
    previous_entry: dict[str, object] | None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "role": "owner",
        "version": str(environment.get("DBPM_PACKAGE_VERSION") or ""),
        "commit": str(environment.get("DBPM_COMMIT_HASH") or ""),
        "artifact_url": str(environment.get("DBPM_ARTIFACT_URL") or ""),
        "artifact_sha256": str(environment.get("DBPM_ARTIFACT_SHA256") or "") or None,
        "installed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "status": status,
    }
    if status == "failed":
        entry["previous_version"] = _installed_version(previous_entry)
    return entry


def _run_script(script_path: Path, *, cwd: str, env: dict[str, str], log_file: Path) -> int:
    _ensure_executable(script_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        try:
            process = subprocess.Popen(
                [str(script_path)],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise ExecutionError(f"Cannot execute runtime script {script_path}: {exc}") from exc
        if process.stdout is not None:
            _tee_output(process.stdout, log)
        return process.wait()


def _ensure_executable(script_path: Path) -> None:
    # ZIP extraction does not preserve permission bits, so extracted scripts
    # need the execute bit restored before they can run.
    if os.access(script_path, os.X_OK):
        return
    try:
        mode = script_path.stat().st_mode
        script_path.chmod(mode | stat.S_IXUSR)
    except OSError as exc:
        raise ExecutionError(f"Runtime script is not executable: {script_path} ({exc})") from exc


def _tee_output(source: TextIO, log: TextIO) -> None:
    for line in source:
        sys.stdout.write(line)
        sys.stdout.flush()
        log.write(line)
        log.flush()
