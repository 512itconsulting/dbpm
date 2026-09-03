import json
from pathlib import Path

import pytest
import errno
import os

import dbpm.application_runtime as application_runtime_module
from dbpm.application_runtime import (
    APPLICATION_RECEIPT_SCHEMA,
    ActivatedRuntimeCommand,
    ApplicationRuntimePackage,
    ApplicationRuntimeReceipt,
    activate_staged_application_runtime,
    application_receipt_path,
    application_runtime_lock,
    classify_preserved_state,
    garbage_collect_application_runtime,
    load_application_runtime_receipt,
    parse_application_runtime_receipt,
    purge_classified_state,
    resume_application_runtime_graph,
    rollback_application_runtime,
    recover_application_runtime_activation,
    stage_application_runtime_graph,
    uninstall_application_runtime_graph,
    validate_application_runtime_graph,
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


def test_application_runtime_receipt_allows_database_only_root():
    value = _receipt().as_dict()
    value["packages"].pop("warehouse_app")

    receipt = parse_application_runtime_receipt(value)

    assert receipt.application_name == "warehouse_app"
    assert [package.name for package in receipt.packages] == ["job_control"]


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


@pytest.mark.parametrize("mode", ["install", "upgrade", "reinstall", "resume"])
def test_runtime_staging_inherits_database_environment_without_persisting_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    script = package_root / "install.sh"
    script.write_text(
        "#!/bin/sh\n"
        "[ \"$DBPM_DB_USER\" = runtime_user ] || exit 11\n"
        "[ \"$DBPM_DB_PASSWORD\" = runtime_password_sentinel ] || exit 12\n"
        "[ \"$DBPM_DB_DSN\" = db.example.invalid/service ] || exit 13\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "printf 'environment inherited\\n'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    graph = _graph(package_root=package_root, script=script)
    if mode == "upgrade":
        graph["payloads"][0]["scripts"]["upgrade"] = {
            "path": "install.sh",
            "ref": str(script),
        }
    monkeypatch.setenv("DBPM_DB_USER", "runtime_user")
    monkeypatch.setenv("DBPM_DB_PASSWORD", "runtime_password_sentinel")
    monkeypatch.setenv("DBPM_DB_DSN", "db.example.invalid/service")

    staged = stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode=mode,
        log_dir=tmp_path / "logs",
    )

    assert staged.log_files[0].read_text(encoding="utf-8") == "environment inherited\n"
    persisted = [
        staged.path / "graph.json",
        staged.path / "status.json",
        *staged.log_files,
    ]
    for path in persisted:
        assert "runtime_password_sentinel" not in path.read_text(encoding="utf-8")


def test_runtime_validate_and_uninstall_inherit_oracle_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    install = package_root / "install.sh"
    install.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n",
        encoding="utf-8",
    )
    check = package_root / "check.sh"
    check.write_text(
        "#!/bin/sh\n"
        "[ \"$DBPM_DB_USER\" = runtime_user ] || exit 11\n"
        "[ \"$DBPM_DB_PASSWORD\" = runtime_password_sentinel ] || exit 12\n"
        "[ \"$DBPM_DB_DSN\" = db.example.invalid/service ] || exit 13\n"
        "printf '%s environment inherited\\n' \"$DBPM_RUNTIME_MODE\"\n",
        encoding="utf-8",
    )
    install.chmod(0o755)
    check.chmod(0o755)
    graph = _graph(package_root=package_root, script=install)
    graph["payloads"][0]["scripts"]["validate"] = {
        "path": "check.sh",
        "ref": str(check),
    }
    graph["payloads"][0]["scripts"]["uninstall"] = {
        "path": "check.sh",
        "ref": str(check),
    }
    graph["payloads"][0]["artifact"]["checksum_alg"] = None
    monkeypatch.setenv("DBPM_DB_USER", "runtime_user")
    monkeypatch.setenv("DBPM_DB_PASSWORD", "runtime_password_sentinel")
    monkeypatch.setenv("DBPM_DB_DSN", "db.example.invalid/service")
    logs = tmp_path / "logs"

    staged = stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode="install",
        log_dir=logs,
    )
    activate_staged_application_runtime(graph, staged, prefix=prefix)
    validate_application_runtime_graph(graph, prefix=prefix, log_dir=logs)
    assert "runtime_password_sentinel" not in application_receipt_path(prefix).read_text(
        encoding="utf-8"
    )
    uninstall_application_runtime_graph(graph, prefix=prefix, log_dir=logs)

    assert (logs / "001-demo-runtime-validate.log").read_text() == (
        "validate environment inherited\n"
    )
    assert (logs / "001-demo-runtime-uninstall.log").read_text() == (
        "uninstall environment inherited\n"
    )
    for path in logs.iterdir():
        assert "runtime_password_sentinel" not in path.read_text(encoding="utf-8")


def test_runtime_cleanup_does_not_rerun_health_after_database_uninstall(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    database_marker = tmp_path / "database-objects-exist"
    database_marker.touch()
    install = package_root / "install.sh"
    install.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n",
        encoding="utf-8",
    )
    health = package_root / "health.sh"
    health.write_text(
        f"#!/bin/sh\ntest -f {database_marker}\n",
        encoding="utf-8",
    )
    install.chmod(0o755)
    health.chmod(0o755)
    graph = _graph(package_root=package_root, script=install)
    graph["payloads"][0]["scripts"]["validate"] = {
        "path": "health.sh",
        "ref": str(health),
    }
    graph["payloads"][0]["artifact"]["checksum_alg"] = None
    logs = tmp_path / "logs"

    staged = stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode="install",
        log_dir=logs,
    )
    activate_staged_application_runtime(graph, staged, prefix=prefix)
    validate_application_runtime_graph(graph, prefix=prefix, log_dir=logs)

    database_marker.unlink()
    uninstall_application_runtime_graph(graph, prefix=prefix, log_dir=logs)

    assert not application_receipt_path(prefix).exists()
    assert (prefix / ".dbpm/uninstalled-receipt.json").is_file()
    assert len(list(logs.glob("*-runtime-validate.log"))) == 1


def test_stage_application_runtime_graph_restricts_receipt_backed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    install = package_root / "install.sh"
    install.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "printf '#!/bin/sh\\nexit 0\\n' > \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "printf 'SENTINEL=%s\\n' \"${DBPM_DB_PASSWORD:-unset}\"\n",
        encoding="utf-8",
    )
    install.chmod(0o755)
    graph = _graph(package_root=package_root, script=install)
    graph["receipt_backed"] = True
    monkeypatch.setenv("DBPM_DB_PASSWORD", "runtime_password_sentinel")
    logs = tmp_path / "logs"

    stage_application_runtime_graph(graph, prefix=prefix, mode="install", log_dir=logs)

    log_text = (logs / "001-demo-runtime-stage.log").read_text(encoding="utf-8")
    assert "SENTINEL=unset" in log_text
    assert "runtime_password_sentinel" not in log_text


def test_uninstall_application_runtime_graph_tolerates_missing_receipt(tmp_path: Path):
    # The package's runtime was declared but never activated (e.g. install
    # crashed during runtime staging), so there is no receipt.json to load.
    # Uninstall should treat this as "nothing to remove" instead of raising.
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    install = package_root / "install.sh"
    install.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    install.chmod(0o755)
    graph = _graph(package_root=package_root, script=install)
    logs = tmp_path / "logs"

    assert not application_receipt_path(prefix).exists()

    uninstall_application_runtime_graph(graph, prefix=prefix, log_dir=logs)

    assert not application_receipt_path(prefix).exists()


def test_validate_application_runtime_graph_returns_none_for_missing_receipt(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    install = package_root / "install.sh"
    install.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    install.chmod(0o755)
    graph = _graph(package_root=package_root, script=install)
    logs = tmp_path / "logs"

    result = validate_application_runtime_graph(
        graph, prefix=prefix, log_dir=logs, allow_missing_receipt=True,
    )

    assert result is None

    with pytest.raises(ExecutionError, match="Application runtime receipt does not exist"):
        validate_application_runtime_graph(graph, prefix=prefix, log_dir=logs)


def test_staged_runtime_relocates_text_launchers_before_activation(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    package_root = tmp_path / "artifact"
    package_root.mkdir()
    script = package_root / "install.sh"
    script.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin\"\n"
        "cp /bin/sh \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/python\"\n"
        "printf '#!%s/bin/python\\necho relocated\\n' "
        "\"$DBPM_RUNTIME_PACKAGE_PREFIX\" > "
        "\"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n"
        "chmod +x \"$DBPM_RUNTIME_PACKAGE_PREFIX/bin/demo\"\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    graph = _graph(package_root=package_root, script=script)

    staged = stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode="install",
        log_dir=tmp_path / "logs",
    )
    launcher = staged.path / "packages/demo/1.0.0/bin/demo"
    assert launcher.read_text().startswith(
        f"#!{prefix.resolve()}/packages/demo/1.0.0/bin/python\n"
    )

    activate_staged_application_runtime(graph, staged, prefix=prefix)

    result = os.popen(str(prefix / "bin/demo")).read()
    assert result == "relocated\n"


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


def test_resume_recovery_can_restage_when_no_generation_survived(
    tmp_path: Path, monkeypatch,
):
    prefix = tmp_path / "app"
    prefix.mkdir()
    graph = {"root_package": "demo", "root_version": "1.0.0", "payloads": [], "commands": []}
    expected = application_runtime_module.StagedApplicationRuntime(
        path=prefix / ".dbpm/staging/new",
        payload_root=prefix / ".dbpm/staging/new/packages",
        log_files=(),
    )
    captured: dict[str, object] = {}

    def fake_stage(*args, **kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(application_runtime_module, "stage_application_runtime_graph", fake_stage)
    resumed = resume_application_runtime_graph(
        graph, prefix=prefix, log_dir=tmp_path / "logs", recovery_mode="upgrade"
    )

    assert resumed is expected
    assert captured["mode"] == "upgrade"


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


def test_garbage_collection_accepts_database_only_root_receipt(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    base = _receipt()
    receipt = ApplicationRuntimeReceipt(
        application_name=base.application_name,
        application_version=base.application_version,
        generation=base.generation,
        activated_at=base.activated_at,
        lock_schema=base.lock_schema,
        lock_checksum=base.lock_checksum,
        packages=(base.packages[1],),
        commands=base.commands,
    )
    write_application_runtime_receipt(prefix, receipt)
    (prefix / "packages/job_control/1.1.0").mkdir(parents=True)
    (prefix / "packages/job_control/orphan").mkdir(parents=True)

    removed = garbage_collect_application_runtime(prefix)

    assert (prefix / "packages/job_control/1.1.0").is_dir()
    assert not (prefix / "packages/job_control/orphan").exists()
    assert any(path.name == "orphan" for path in removed)


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


def test_activation_journal_recovers_interrupted_bin_switch(tmp_path: Path):
    prefix = tmp_path / "app"
    prefix.mkdir()
    staging = prefix / ".dbpm/staging/generation-test"
    staging.mkdir(parents=True)
    promoted = prefix / "packages/demo/2.0.0"
    promoted.mkdir(parents=True)
    (promoted / "new").write_text("new")
    current_bin = prefix / "bin"
    current_bin.mkdir()
    (current_bin / "new").write_text("new")
    backup = prefix / ".dbpm/bin-generation-1"
    backup.mkdir()
    (backup / "old").write_text("old")
    journal = {
        "generation": 2,
        "phase": "bin-activated",
        "staged_path": str(staging),
        "promoted": ["packages/demo/2.0.0"],
        "replaced": [],
        "bin_backup": ".dbpm/bin-generation-1",
    }
    (prefix / ".dbpm/activation.json").write_text(json.dumps(journal))

    recover_application_runtime_activation(prefix)

    assert (prefix / "bin/old").read_text() == "old"
    assert (staging / "bin/new").read_text() == "new"
    assert (staging / "packages/demo/2.0.0/new").read_text() == "new"
    assert not (prefix / ".dbpm/activation.json").exists()


def test_command_publication_falls_back_to_hard_link(monkeypatch, tmp_path: Path):
    target = tmp_path / "target"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    link = tmp_path / "command"

    def deny_symlink(*args, **kwargs):
        raise OSError(errno.EPERM, "symlinks unavailable")

    monkeypatch.setattr(application_runtime_module.os, "symlink", deny_symlink)
    application_runtime_module._create_command_link(
        link,
        target,
        relative_target="../target",
    )

    assert not link.is_symlink()
    assert os.path.samefile(link, target)


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


# ---------------------------------------------------------------------------
# preserved-state classification and purge
# ---------------------------------------------------------------------------


_STATE_RULES = [
    {"path": "var/cache/**", "category": "cache"},
    {"path": "var/queue/**", "category": "work_state"},
    {"path": "etc/secrets.conf", "category": "secret"},
]


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_classify_preserved_state_splits_declared_and_unclassified(tmp_path: Path):
    _write(tmp_path / "var" / "cache" / "a.tmp")
    _write(tmp_path / "var" / "queue" / "job.json")
    _write(tmp_path / "etc" / "secrets.conf")
    _write(tmp_path / "etc" / "unknown.conf")

    result = classify_preserved_state(tmp_path, _STATE_RULES)

    assert result["categories"]["cache"] == ["var/cache/a.tmp"]
    assert result["categories"]["work_state"] == ["var/queue/job.json"]
    assert result["categories"]["secret"] == ["etc/secrets.conf"]
    assert result["unclassified"] == ["etc/unknown.conf"]


def test_classify_preserved_state_handles_missing_etc_and_var(tmp_path: Path):
    result = classify_preserved_state(tmp_path, _STATE_RULES)

    assert result["categories"] == {}
    assert result["unclassified"] == []


def test_purge_classified_state_deletes_only_selected_category(tmp_path: Path):
    _write(tmp_path / "var" / "cache" / "a.tmp")
    _write(tmp_path / "var" / "queue" / "job.json")
    classification = classify_preserved_state(tmp_path, _STATE_RULES)

    deleted = purge_classified_state(tmp_path, classification, {"cache"})

    assert deleted == ["var/cache/a.tmp"]
    assert not (tmp_path / "var" / "cache" / "a.tmp").exists()
    assert (tmp_path / "var" / "queue" / "job.json").exists()


def test_purge_classified_state_never_deletes_secret_or_config(tmp_path: Path):
    _write(tmp_path / "etc" / "secrets.conf")
    classification = classify_preserved_state(tmp_path, _STATE_RULES)

    deleted = purge_classified_state(tmp_path, classification, {"secret", "config"})

    assert deleted == []
    assert (tmp_path / "etc" / "secrets.conf").exists()


def test_purge_classified_state_never_deletes_unclassified_paths(tmp_path: Path):
    _write(tmp_path / "var" / "cache" / "a.tmp")
    _write(tmp_path / "var" / "mystery.dat")
    classification = classify_preserved_state(tmp_path, _STATE_RULES)

    deleted = purge_classified_state(
        tmp_path, classification, {"cache", "work_state", "log", "business_data"}
    )

    assert deleted == ["var/cache/a.tmp"]
    assert (tmp_path / "var" / "mystery.dat").exists()


def test_purge_classified_state_ignores_files_created_after_classification(tmp_path: Path):
    _write(tmp_path / "var" / "cache" / "a.tmp")
    classification = classify_preserved_state(tmp_path, _STATE_RULES)
    _write(tmp_path / "var" / "cache" / "b.tmp")

    deleted = purge_classified_state(tmp_path, classification, {"cache"})

    assert deleted == ["var/cache/a.tmp"]
    assert (tmp_path / "var" / "cache" / "b.tmp").exists()


def test_classify_preserved_state_treats_ambiguous_overlap_as_unclassified(tmp_path: Path):
    _write(tmp_path / "var" / "business" / "record.dat")
    rules = [
        {"path": "var/**", "category": "cache"},
        {"path": "var/business/**", "category": "business_data"},
    ]

    result = classify_preserved_state(tmp_path, rules)

    assert result["categories"] == {}
    assert result["unclassified"] == ["var/business/record.dat"]
