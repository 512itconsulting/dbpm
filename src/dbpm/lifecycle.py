from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from .errors import ExecutionError
from .source import _tree_files, _tree_sha256


LIFECYCLE_RECEIPT_SCHEMA = "dbpm.installed-lifecycle.v1"
LIFECYCLE_RECEIPT_FILE = "lifecycle-receipt.json"


def snapshot_plan(plan: dict[str, object], *, runtime_prefix: str | None = None) -> dict[str, object]:
    """Snapshot directory sources and rewrite every executable reference to the snapshot."""
    result = deepcopy(plan)
    store = _store_path(runtime_prefix)
    for package_plan in _package_plans(result):
        source = package_plan.get("source")
        if not isinstance(source, dict) or source.get("type") != "directory":
            continue
        root = Path(str(source.get("path") or "")).resolve()
        expected = str(source.get("checksum") or "")
        checksum = _tree_sha256(root)
        if expected and checksum != expected:
            raise ExecutionError(
                f"Mutable package changed after planning: {root}; plan again before execution"
            )
        destination = store / "artifacts" / checksum
        if not destination.exists():
            temporary = store / "artifacts" / f".{checksum}.{os.getpid()}.tmp"
            temporary.mkdir(parents=True, mode=0o700, exist_ok=False)
            try:
                for item in _tree_files(root):
                    relative = item.relative_to(root)
                    target = temporary / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)
                if _tree_sha256(temporary) != checksum:
                    raise ExecutionError(f"Lifecycle snapshot verification failed for {root}")
                temporary.replace(destination)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
        _rewrite_package_paths(package_plan, root, destination, checksum)
    _refresh_runtime_graph(result)
    runtime = result.get("application_runtime")
    if isinstance(runtime, dict):
        runtime["receipt_backed"] = True
    return result


def write_lifecycle_receipt(plan: dict[str, object], *, runtime_prefix: str | None) -> Path:
    path = lifecycle_receipt_path(runtime_prefix)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = {"schema": LIFECYCLE_RECEIPT_SCHEMA, "plan": plan}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


def load_lifecycle_receipt(*, runtime_prefix: str | None) -> dict[str, object]:
    path = lifecycle_receipt_path(runtime_prefix)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionError(f"Installed lifecycle receipt is unavailable or invalid: {path}") from exc
    if payload.get("schema") != LIFECYCLE_RECEIPT_SCHEMA or not isinstance(payload.get("plan"), dict):
        raise ExecutionError(f"Unsupported installed lifecycle receipt: {path}")
    plan = payload["plan"]
    for package_plan in _package_plans(plan):
        snapshot = package_plan.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        root = Path(str(snapshot.get("path") or ""))
        expected = str(snapshot.get("checksum") or "")
        if not root.is_dir() or _tree_sha256(root) != expected:
            raise ExecutionError(
                f"Installed lifecycle snapshot checksum mismatch for {root}; no hook was executed"
            )
    return plan


def lifecycle_receipt_path(runtime_prefix: str | None) -> Path:
    return _store_path(runtime_prefix) / LIFECYCLE_RECEIPT_FILE


def _store_path(runtime_prefix: str | None) -> Path:
    if runtime_prefix:
        return Path(runtime_prefix).expanduser().resolve() / ".dbpm" / "lifecycle"
    configured = os.environ.get("DBPM_LIFECYCLE_CACHE")
    return Path(configured).expanduser().resolve() if configured else Path(".dbpm-cache/installations").resolve()


def _package_plans(plan: dict[str, object]) -> list[dict[str, object]]:
    packages = plan.get("packages")
    if isinstance(packages, list):
        return [item for item in packages if isinstance(item, dict)]
    return [plan]


def _rewrite_package_paths(plan: dict[str, object], old: Path, new: Path, checksum: str) -> None:
    plan["snapshot"] = {"path": str(new), "checksum": checksum, "checksum_alg": "TREE-SHA-256"}
    source = plan.get("source")
    if isinstance(source, dict):
        source["path"] = str(new)
        source["snapshot_of"] = str(old)
    for field in ("execution", "lifecycle"):
        value = plan.get(field)
        if isinstance(value, dict):
            _rewrite_mapping_paths(value, old, new)
    for field in ("pre_actions", "post_actions"):
        actions = plan.get(field)
        if isinstance(actions, list):
            for action in actions:
                if isinstance(action, dict):
                    _rewrite_mapping_paths(action, old, new)
    runtime = plan.get("runtime_package")
    if isinstance(runtime, dict):
        _rewrite_mapping_paths(runtime, old, new)
        runtime["package_root"] = str(new)
        artifact = runtime.get("artifact")
        if isinstance(artifact, dict):
            artifact["checksum"] = checksum
            artifact["checksum_alg"] = "TREE-SHA-256"


def _rewrite_mapping_paths(value: dict[str, Any], old: Path, new: Path) -> None:
    for key, item in value.items():
        if isinstance(item, dict):
            _rewrite_mapping_paths(item, old, new)
        elif isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    _rewrite_mapping_paths(nested, old, new)
        elif isinstance(item, str) and key in ("ref", "script_ref"):
            try:
                relative = Path(item).resolve().relative_to(old)
            except (ValueError, OSError):
                continue
            value[key] = str(new / relative)


def _refresh_runtime_graph(plan: dict[str, object]) -> None:
    packages = _package_plans(plan)
    runtime = plan.get("application_runtime")
    if not isinstance(runtime, dict):
        return
    by_name = {
        item.get("runtime_package", {}).get("package"): item.get("runtime_package")
        for item in packages
        if isinstance(item.get("runtime_package"), dict)
    }
    payloads = runtime.get("payloads")
    if isinstance(payloads, list):
        runtime["payloads"] = [by_name.get(item.get("package"), item) if isinstance(item, dict) else item for item in payloads]
