import json
from pathlib import Path

import pytest

from dbpm.application_runtime import (
    APPLICATION_RECEIPT_SCHEMA,
    ActivatedRuntimeCommand,
    ApplicationRuntimePackage,
    ApplicationRuntimeReceipt,
    application_receipt_path,
    application_runtime_lock,
    garbage_collect_application_runtime,
    load_application_runtime_receipt,
    parse_application_runtime_receipt,
    resume_application_runtime_graph,
    rollback_application_runtime,
    stage_application_runtime_graph,
    write_application_runtime_receipt,
)
from dbpm.errors import ExecutionError


def _receipt() -> ApplicationRuntimeReceipt:
    return ApplicationRuntimeReceipt(
        application_name="warehouse_app",
        application_version="2.0.0",
        generation=3,
        activated_at="2026-07-25T18:04:00Z",
        lock_schema="dbpm.lock.v0",
        lock_checksum="sha256:abc123",
        packages=(
            ApplicationRuntimePackage(
                name="warehouse_app",
                version="2.0.0",
                path="packages/warehouse_app/2.0.0",
                commit="a" * 40,
                artifact_uri="https://example.invalid/warehouse_app.zip",
                artifact_checksum="abc123",
                artifact_checksum_alg="SHA-256",
            ),
            ApplicationRuntimePackage(
                name="job_control",
                version="1.1.0",
                path="packages/job_control/1.1.0",
                commit="b" * 40,
                artifact_uri="https://example.invalid/job_control.zip",
                artifact_checksum="def456",
                artifact_checksum_alg="SHA-256",
            ),
        ),
        commands=(
            ActivatedRuntimeCommand(
                name="job-control",
                package="job_control",
                export="job-control",
                target="packages/job_control/1.1.0/bin/job-control",
            ),
        ),
    )


def test_application_runtime_receipt_roundtrip(tmp_path: Path):
    receipt = _receipt()

    write_application_runtime_receipt(tmp_path, receipt)
    loaded = load_application_runtime_receipt(
        tmp_path,
        expected_application="warehouse_app",
    )

    assert loaded.as_dict() == receipt.as_dict()
    raw = json.loads(application_receipt_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema"] == APPLICATION_RECEIPT_SCHEMA
    assert raw["generation"] == 3
    assert raw["commands"]["job-control"]["package"] == "job_control"


def test_application_runtime_receipt_rejects_wrong_application(tmp_path: Path):
    write_application_runtime_receipt(tmp_path, _receipt())

    with pytest.raises(ExecutionError, match="belongs to `warehouse_app`"):
        load_application_runtime_receipt(
            tmp_path,
            expected_application="another_app",
        )


def test_application_runtime_receipt_requires_root_in_packages():
    value = _receipt().as_dict()
    value["packages"].pop("warehouse_app")

    with pytest.raises(ExecutionError, match="do not contain root application"):
        parse_application_runtime_receipt(value)


def test_application_runtime_receipt_rejects_command_for_missing_package():
    value = _receipt().as_dict()
    value["commands"]["job-control"]["package"] = "missing"

    with pytest.raises(ExecutionError, match="references missing package"):
        parse_application_runtime_receipt(value)


def test_application_runtime_receipt_rejects_command_outside_package_payload():
    value = _receipt().as_dict()
    value["commands"]["job-control"]["target"] = (
        "packages/warehouse_app/2.0.0/bin/job-control"
    )

    with pytest.raises(ExecutionError, match="outside package"):
        parse_application_runtime_receipt(value)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("generation", 0, "positive integer"),
        ("generation", True, "positive integer"),
        ("schema", "dbpm.receipt.v0", "Unsupported"),
    ],
)
def test_application_runtime_receipt_rejects_invalid_top_level_fields(
    field: str,
    value: object,
    match: str,
):
    receipt = _receipt().as_dict()
    receipt[field] = value

    with pytest.raises(ExecutionError, match=match):
        parse_application_runtime_receipt(receipt)


def test_application_runtime_receipt_requires_complete_lock_identity():
    receipt = _receipt().as_dict()
    receipt["resolution"]["lock_checksum"] = None

    with pytest.raises(ExecutionError, match="both lock_schema and lock_checksum"):
        parse_application_runtime_receipt(receipt)


def test_application_runtime_receipt_rejects_unsafe_package_path():
    receipt = _receipt().as_dict()
    receipt["packages"]["job_control"]["path"] = "../job_control"

    with pytest.raises(ExecutionError, match="safe relative path"):
        parse_application_runtime_receipt(receipt)


def test_stage_application_runtime_executes_package_in_isolated_prefix(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    script = package_root / "install.sh"
    script.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > "
        "\"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "printf '%s\\n' \"$DBPM_ROOT_PACKAGE_NAME\" \"$DBPM_PACKAGE_NAME\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    staged = stage_application_runtime_graph(
        _graph(package_root=package_root, script=script),
        prefix=prefix,
        mode="install",
        log_dir=tmp_path / "logs",
    )

    command = staged.path / "packages/demo/1.0.0/bin/demo"
    assert command.is_file()
    assert command.stat().st_mode & 0o111
    assert not (prefix / "packages").exists()
    assert staged.log_files[0].read_text(encoding="utf-8") == "demo\ndemo\n"
    assert not (prefix / ".dbpm" / "lock").exists()


def test_stage_application_runtime_keeps_failed_payload_for_diagnostics(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    script = package_root / "install.sh"
    script.write_text(
        "#!/bin/sh\n"
        "printf broken > \"$DBPM_RUNTIME_PACKAGE_PREFIX/partial.txt\"\n"
        "exit 7\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    with pytest.raises(ExecutionError, match="failed with exit code 7") as exc_info:
        stage_application_runtime_graph(
            _graph(package_root=package_root, script=script),
            prefix=prefix,
            mode="install",
            log_dir=tmp_path / "logs",
        )

    message = str(exc_info.value)
    staging_path = Path(message.split("staged files remain in ", 1)[1].split(";", 1)[0])
    assert (staging_path / "packages/demo/1.0.0/partial.txt").read_text() == "broken"
    assert not (prefix / ".dbpm" / "lock").exists()


def test_stage_application_runtime_rejects_export_symlink_escape(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    outside.chmod(0o755)
    script = package_root / "install.sh"
    script.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        f"ln -s {outside} \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    with pytest.raises(ExecutionError, match="escapes package"):
        stage_application_runtime_graph(
            _graph(package_root=package_root, script=script),
            prefix=prefix,
            mode="install",
            log_dir=tmp_path / "logs",
        )


def test_application_runtime_lock_rejects_concurrent_operation(tmp_path: Path):
    with application_runtime_lock(tmp_path):
        with pytest.raises(ExecutionError, match="appears to be active"):
            with application_runtime_lock(tmp_path):
                pass


def test_resume_reuses_matching_failed_generation(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    script = package_root / "install.sh"
    marker = package_root / "failed-once"
    script.write_text(
        "#!/bin/sh\n"
        f"if [ ! -f '{marker}' ]; then touch '{marker}'; exit 7; fi\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    graph = _graph(package_root=package_root, script=script)

    with pytest.raises(ExecutionError, match="failed with exit code 7") as exc_info:
        stage_application_runtime_graph(
            graph,
            prefix=prefix,
            mode="install",
            log_dir=tmp_path / "logs",
        )
    failed_path = Path(
        str(exc_info.value).split("staged files remain in ", 1)[1].split(";", 1)[0]
    )

    resumed = resume_application_runtime_graph(
        graph,
        prefix=prefix,
        log_dir=tmp_path / "logs",
    )

    assert resumed.path == failed_path
    assert json.loads((resumed.path / "status.json").read_text())["status"] == "ready"
    assert (resumed.path / "packages/demo/1.0.0/bin/demo").is_file()


def test_resume_rejects_when_no_matching_generation(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()

    with pytest.raises(ExecutionError, match="No matching incomplete"):
        resume_application_runtime_graph(
            {"root_package": "demo", "root_version": "1.0.0", "payloads": [], "commands": []},
            prefix=prefix,
            log_dir=tmp_path / "logs",
        )


def test_garbage_collection_preserves_active_and_retained_payloads(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    active = _generation_receipt(3, "3.0.0")
    retained = _generation_receipt(2, "2.0.0")
    expired = _generation_receipt(1, "1.0.0")
    write_application_runtime_receipt(prefix, active)
    for receipt in (retained, expired):
        directory = prefix / ".dbpm/generations" / str(receipt.generation)
        directory.mkdir(parents=True)
        (directory / "receipt.json").write_text(
            json.dumps(receipt.as_dict()),
            encoding="utf-8",
        )
        backup = prefix / ".dbpm" / f"bin-generation-{receipt.generation}"
        backup.mkdir()
    for version in ("1.0.0", "2.0.0", "3.0.0", "orphan"):
        (prefix / "packages/demo" / version).mkdir(parents=True)

    removed = garbage_collect_application_runtime(prefix, retain_generations=1)

    assert not (prefix / "packages/demo/1.0.0").exists()
    assert not (prefix / "packages/demo/orphan").exists()
    assert (prefix / "packages/demo/2.0.0").is_dir()
    assert (prefix / "packages/demo/3.0.0").is_dir()
    assert not (prefix / ".dbpm/generations/1").exists()
    assert (prefix / ".dbpm/generations/2").is_dir()
    assert not (prefix / ".dbpm/bin-generation-1").exists()
    assert any(path.name == "1.0.0" for path in removed)


def test_garbage_collection_rejects_negative_retention(tmp_path: Path):
    with pytest.raises(ExecutionError, match="must not be negative"):
        garbage_collect_application_runtime(tmp_path, retain_generations=-1)


def test_rollback_reactivates_retained_graph_as_new_generation(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    active = _generation_receipt(2, "2.0.0")
    target = _generation_receipt(1, "1.0.0")
    write_application_runtime_receipt(prefix, active)
    target_dir = prefix / ".dbpm/generations/1"
    target_dir.mkdir(parents=True)
    (target_dir / "receipt.json").write_text(json.dumps(target.as_dict()))
    for version in ("1.0.0", "2.0.0"):
        executable = prefix / f"packages/demo/{version}/bin/demo"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
    (prefix / "bin").mkdir()
    (prefix / "bin/demo").symlink_to("../packages/demo/2.0.0/bin/demo")

    rolled_back = rollback_application_runtime(
        prefix,
        database_versions={"demo": "1.0.0"},
    )

    assert rolled_back.generation == 3
    assert rolled_back.application_version == "1.0.0"
    assert (prefix / "bin/demo").resolve() == (
        prefix / "packages/demo/1.0.0/bin/demo"
    ).resolve()


def test_rollback_rejects_incompatible_database_versions(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    write_application_runtime_receipt(prefix, _generation_receipt(2, "2.0.0"))
    target_dir = prefix / ".dbpm/generations/1"
    target_dir.mkdir(parents=True)
    (target_dir / "receipt.json").write_text(
        json.dumps(_generation_receipt(1, "1.0.0").as_dict())
    )

    with pytest.raises(ExecutionError, match="Database versions are incompatible"):
        rollback_application_runtime(
            prefix,
            database_versions={"demo": "2.0.0"},
        )


def _generation_receipt(generation: int, version: str) -> ApplicationRuntimeReceipt:
    return ApplicationRuntimeReceipt(
        application_name="demo",
        application_version=version,
        generation=generation,
        activated_at="2026-07-25T18:04:00Z",
        lock_schema=None,
        lock_checksum=None,
        packages=(
            ApplicationRuntimePackage(
                name="demo",
                version=version,
                path=f"packages/demo/{version}",
                commit="a" * 40,
                artifact_uri=f"https://example.invalid/demo-{version}.zip",
                artifact_checksum=None,
                artifact_checksum_alg=None,
            ),
        ),
        commands=(
            ActivatedRuntimeCommand(
                name="demo",
                package="demo",
                export="demo",
                target=f"packages/demo/{version}/bin/demo",
            ),
        ),
    )


def _graph(*, package_root: Path, script: Path) -> dict[str, object]:
    return {
        "root_package": "demo",
        "root_version": "1.0.0",
        "payloads": [
            {
                "package": "demo",
                "version": "1.0.0",
                "payload_path": "packages/demo/1.0.0",
                "package_root": str(package_root),
                "artifact": {
                    "uri": str(package_root),
                    "checksum": None,
                    "checksum_alg": "TREE-SHA-256",
                    "commit": "a" * 40,
                },
                "scripts": {
                    "install": {"path": "install.sh", "ref": str(script)},
                    "upgrade": {"path": None, "ref": None},
                    "validate": {"path": None, "ref": None},
                    "uninstall": {"path": None, "ref": None},
                },
                "exports": {
                    "commands": [
                        {
                            "name": "demo",
                            "target": "bin/demo",
                            "canonical": "demo.demo",
                        }
                    ]
                },
                "activation": {"commands": {"aliases": {}, "disabled": []}},
            }
        ],
        "commands": [
            {
                "name": "demo",
                "canonical": "demo.demo",
                "package": "demo",
                "export": "demo",
                "target": "packages/demo/1.0.0/bin/demo",
                "link": "bin/demo",
            }
        ],
    }
