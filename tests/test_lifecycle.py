from pathlib import Path

import pytest

from dbpm.application_runtime import validate_application_runtime_collisions
from dbpm.errors import ExecutionError
from dbpm.lifecycle import load_lifecycle_receipt, snapshot_plan, write_lifecycle_receipt
from dbpm.source import _tree_sha256


def _plan(source: Path) -> dict[str, object]:
    checksum = _tree_sha256(source)
    return {
        "mode": "install",
        "source": {"type": "directory", "path": str(source), "checksum": checksum},
        "execution": {"script_ref": str(source / "deploy.sql")},
        "lifecycle": {"uninstall": {"ref": str(source / "uninstall.sh")}},
        "runtime_package": {
            "package": "demo",
            "package_root": str(source),
            "artifact": {},
            "scripts": {"uninstall": {"ref": str(source / "uninstall.sh")}},
        },
    }


def test_snapshot_uses_same_filtered_tree_and_receipt_detects_tampering(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "dbpm.yaml").write_text("package: {name: demo, version: 1.0.0}\n")
    (source / "deploy.sql").write_text("prompt deploy\n")
    (source / "uninstall.sh").write_text("#!/bin/sh\n")
    (source / ".env").write_text("secret\n")
    (source / ".dbpmignore").write_text(".env\n")
    prefix = tmp_path / "runtime"

    snapshotted = snapshot_plan(_plan(source), runtime_prefix=str(prefix))
    write_lifecycle_receipt(snapshotted, runtime_prefix=str(prefix))
    snapshot = Path(str(snapshotted["snapshot"]["path"]))
    assert not (snapshot / ".env").exists()
    assert load_lifecycle_receipt(runtime_prefix=str(prefix))["snapshot"] == snapshotted["snapshot"]

    (snapshot / "uninstall.sh").write_text("tampered\n")
    with pytest.raises(ExecutionError, match="checksum mismatch.*no hook was executed"):
        load_lifecycle_receipt(runtime_prefix=str(prefix))


def test_collision_validation_reports_all_destinations_without_mutation(tmp_path: Path):
    prefix = tmp_path / "runtime"
    first = prefix / "packages/a/1.0.0"
    second = prefix / "packages/b/1.0.0"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    graph = {
        "root_package": "root",
        "payloads": [
            {"package": "a", "version": "1.0.0", "payload_path": "packages/a/1.0.0", "artifact": {}},
            {"package": "b", "version": "1.0.0", "payload_path": "packages/b/1.0.0", "artifact": {}},
        ],
        "commands": [],
    }

    with pytest.raises(ExecutionError) as raised:
        validate_application_runtime_collisions(graph, prefix=prefix, mode="install")
    assert str(first) in str(raised.value)
    assert str(second) in str(raised.value)
    assert first.is_dir() and second.is_dir()
