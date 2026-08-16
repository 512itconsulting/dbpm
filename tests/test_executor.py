import io
import json
import subprocess
from unittest.mock import patch

import pytest

from dbpm.errors import ExecutionError
from dbpm.executor import execute_plan
from dbpm.connect import sqlcl_name
from dbpm.db import ApplicationState, OperationLease, OperationRecord


class _FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "ok\n"):
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)
        self.stdin = io.StringIO()

    def wait(self) -> int:
        return self.returncode


class _NonClosingStringIO(io.StringIO):
    def close(self) -> None:
        pass


class _CapturingProcess(_FakeProcess):
    def __init__(self, *, returncode: int = 0, stdout: str = "ok\n"):
        super().__init__(returncode=returncode, stdout=stdout)
        self.stdin = _NonClosingStringIO()


def _composite_plan() -> dict[str, object]:
    return {
        "mode": "install",
        "package": {"name": "demo", "application_name": "DEMO", "version": "1.0.0"},
        "execution": {"script": "deploy.sql", "script_ref": "deploy.sql", "arguments": []},
        "pre_actions": [],
        "post_actions": [],
        "application_runtime": {"root_package": "demo", "payloads": [], "commands": []},
        "operation": {"operation_id": "12345678-1234-1234-1234-123456789abc"},
    }


def test_runtime_failure_leaves_composite_operation_database_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "runtime"
    prefix.mkdir()
    plan = _composite_plan()
    record = OperationRecord(
        "12345678-1234-1234-1234-123456789abc", "DEMO", "INSTALL",
        "RESOLVED", 0, None, None,
    )
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    states: list[str] = []
    with patch("dbpm.executor.begin_operation", return_value=record), \
         patch("dbpm.executor.acquire_operation_lease", return_value=lease), \
         patch("dbpm.executor.renew_operation_lease", return_value=lease), \
         patch("dbpm.executor.release_operation_lease"), \
         patch("dbpm.executor.record_operation_step", side_effect=lambda **kw: states.append(kw["state"])), \
         patch("dbpm.executor._preflight_application_runtime"), \
         patch("dbpm.executor._execute_application_runtime", side_effect=ExecutionError("activation failed")), \
         patch("dbpm.executor.subprocess.Popen", return_value=_FakeProcess()):
        with pytest.raises(ExecutionError, match="activation failed"):
            execute_plan(plan, connect="user/pass@db", runner="sql", runtime_prefix=str(prefix))

    assert "DATABASE_COMPLETE" in states
    assert states[-1] == "DATABASE_COMPLETE"


def test_resume_from_database_complete_skips_database_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "runtime"
    prefix.mkdir()
    plan = _composite_plan()
    plan["mode"] = "resume"
    plan["operation"]["resume_existing"] = True
    record = OperationRecord(
        "12345678-1234-1234-1234-123456789abc", "DEMO", "INSTALL",
        "DATABASE_COMPLETE", 1, None, None,
    )
    lease = OperationLease(record.operation_id, 2, "token2", "expiry")
    receipt = type("Receipt", (), {"generation": 2})()
    with patch("dbpm.executor.get_current_operation", return_value=record), \
         patch("dbpm.executor.acquire_operation_lease", return_value=lease), \
         patch("dbpm.executor.renew_operation_lease", return_value=lease), \
         patch("dbpm.executor.release_operation_lease"), \
         patch("dbpm.executor.record_operation_step"), \
         patch("dbpm.executor.get_application_state", return_value=ApplicationState("DEMO", "1.0.0", "C", "abc")), \
         patch("dbpm.executor._preflight_application_runtime"), \
         patch("dbpm.executor._execute_application_runtime") as runtime, \
         patch("dbpm.executor.load_application_runtime_receipt", return_value=receipt), \
         patch("dbpm.executor.validate_application_runtime_graph"), \
         patch("dbpm.executor.subprocess.Popen") as popen:
        execute_plan(plan, connect="user/pass@db", runner="sql", runtime_prefix=str(prefix))

    popen.assert_not_called()
    runtime.assert_called_once()


def test_unreachable_runtime_is_recorded_after_database_completion(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = _composite_plan()
    record = OperationRecord(
        "12345678-1234-1234-1234-123456789abc", "DEMO", "INSTALL",
        "RESOLVED", 0, None, None,
    )
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    states: list[str] = []
    with patch("dbpm.executor.begin_operation", return_value=record), \
         patch("dbpm.executor.acquire_operation_lease", return_value=lease), \
         patch("dbpm.executor.renew_operation_lease", return_value=lease), \
         patch("dbpm.executor.release_operation_lease"), \
         patch("dbpm.executor.record_operation_step", side_effect=lambda **kw: states.append(kw["state"])), \
         patch("dbpm.executor.subprocess.Popen", return_value=_FakeProcess()):
        with pytest.raises(ExecutionError, match="database phase is complete"):
            execute_plan(
                plan, connect="user/pass@db", runner="sql",
                runtime_prefix=str(tmp_path / "offline-mount"),
            )

    assert "DATABASE_COMPLETE" in states
    assert states[-1] == "RUNTIME_UNREACHABLE"


def _write_runtime_receipt(prefix, *, application: str) -> None:
    metadata = prefix / ".dbpm"
    metadata.mkdir(parents=True)
    (metadata / "receipt.json").write_text(
        json.dumps(
            {
                "schema": "dbpm.application-runtime.v1",
                "application": {"name": application, "version": "1.0.0"},
                "generation": 1,
                "activated_at": "2026-08-10T00:00:00Z",
                "resolution": {"lock_schema": None, "lock_checksum": None},
                "packages": {
                    application: {
                        "version": "1.0.0",
                        "path": f"packages/{application}/1.0.0",
                        "commit": "",
                        "artifact": {
                            "uri": "",
                            "checksum": None,
                            "checksum_alg": None,
                        },
                    }
                },
                "commands": {},
            }
        ),
        encoding="utf-8",
    )


def test_execute_plan_runs_delete_pre_action_before_script(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    payload = {
        "application_name": "DEMO",
        "version": "0.1.0",
        "deploy_commit_hash": "123",
    }
    plan = {
        "pre_actions": [
            {
                "type": "delete_application",
                "application_name": "DEMO",
                "fail_on_not_found": "N",
            },
            {
                "type": "stage_deployment_provenance",
                "payload": payload,
            },
        ],
        "mode": "install",
        "package": {
            "application_name": "DEMO",
        },
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": ["123"],
        },
    }

    with patch("dbpm.executor.delete_application") as delete_application:
        with patch("dbpm.executor.stage_deployment_provenance") as stage:
            with patch("dbpm.executor.subprocess.Popen") as popen:
                popen.return_value = _FakeProcess(stdout="deployed\n")
                execute_plan(plan, connect="user/pass@db", runner="sql")

    delete_application.assert_called_once_with(
        connect="user/pass@db",
        runner="sql",
        application_name="DEMO",
        fail_on_not_found="N",
    )
    stage.assert_called_once_with(connect="user/pass@db", runner="sql", payload=payload)
    popen.assert_called_once()
    assert popen.call_args.args[0] == ["sql", "-L", "user/pass@db", "@deploy.sql", "123"]

    logs = list((tmp_path / "logs").glob("*-001-DEMO-install.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8") == "deployed\n"
    assert "dbpm: Deploying DEMO..." in capsys.readouterr().err


def test_execute_multi_package_plan_reports_package_progress(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "packages": [
            {
                "mode": "install",
                "package": {"name": "first", "version": "1.0.0"},
                "execution": {"script_ref": "first.sql", "arguments": []},
            },
            {
                "mode": "install",
                "package": {"name": "second", "version": "2.0.0"},
                "execution": {"script_ref": "second.sql", "arguments": []},
            },
        ],
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.side_effect = [_FakeProcess(), _FakeProcess()]
        execute_plan(plan, connect="user/pass@db", runner="sql")

    stderr = capsys.readouterr().err
    assert "dbpm: Deploying first 1.0.0 (1/2)..." in stderr
    assert "dbpm: Deploying second 2.0.0 (2/2)..." in stderr


def test_execute_plan_sends_fallback_exit_success(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "package": {
            "application_name": "DEMO",
        },
        "pre_actions": [],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": [],
        },
    }
    process = _CapturingProcess(stdout="deployed\n")

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.return_value = process
        execute_plan(plan, connect="user/pass@db", runner="sql")

    assert popen.call_args.kwargs["stdin"] == subprocess.PIPE
    assert process.stdin.getvalue() == "EXIT SUCCESS\n"


def test_execute_plan_sends_script_stdin_before_fallback_exit_success(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "bootstrap-core",
        "package": {
            "application_name": "CORE",
        },
        "pre_actions": [],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": [],
            "stdin": "N\nDEV\n",
        },
    }
    process = _CapturingProcess(stdout="deployed\n")

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.return_value = process
        execute_plan(plan, connect="user/pass@db", runner="sql")

    assert process.stdin.getvalue() == "N\nDEV\nEXIT SUCCESS\n"


def test_log_dir_expands_quoted_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DBPM_LOG_DIR", "~/.local/state/dbpm_logs")
    plan = {
        "mode": "install",
        "package": {
            "application_name": "DEMO",
        },
        "pre_actions": [],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": [],
        },
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.return_value = _FakeProcess(stdout="deployed\n")
        execute_plan(plan, connect="user/pass@db", runner="sql")

    logs = list((home / ".local" / "state" / "dbpm_logs").glob("*-001-DEMO-install.log"))
    assert len(logs) == 1


def test_execute_plan_runs_multi_package_children_in_order(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "packages": [
            {
                "mode": "validate",
                "package": {
                    "application_name": "BASE",
                },
                "pre_actions": [],
                "execution": {
                    "script_ref": "base.sql",
                    "arguments": [],
                },
            },
            {
                "mode": "validate",
                "package": {
                    "application_name": "CONSUMER",
                },
                "pre_actions": [],
                "execution": {
                    "script_ref": "consumer.sql",
                    "arguments": ["abc"],
                },
            },
        ]
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.side_effect = lambda *args, **kwargs: _FakeProcess(stdout="ok\n")
        assert execute_plan(plan, connect="user/pass@db", runner="sql") == 0

    assert popen.call_count == 2
    assert popen.call_args_list[0].args[0] == ["sql", "-L", "user/pass@db", "@base.sql"]
    assert popen.call_args_list[1].args[0] == [
        "sql",
        "-L",
        "user/pass@db",
        "@consumer.sql",
        "abc",
    ]
    logs = sorted(path.name for path in (tmp_path / "logs").glob("*.log"))
    assert len(logs) == 2
    assert logs[0].endswith("-001-BASE-validate.log")
    assert logs[1].endswith("-002-CONSUMER-validate.log")


def test_uninstall_health_preflight_runs_before_database_and_runtime_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "runtime"
    prefix.mkdir()
    graph = {"root_package": "demo"}
    plan = {
        "mode": "uninstall",
        "package": {"application_name": "DEMO"},
        "pre_actions": [],
        "execution": {"script_ref": "uninstall.sql", "arguments": []},
        "application_runtime": graph,
    }
    calls = []

    with patch("dbpm.executor.validate_application_runtime_graph") as validate:
        with patch("dbpm.executor.uninstall_application_runtime_graph") as uninstall:
            with patch("dbpm.executor.subprocess.Popen") as popen:
                validate.side_effect = lambda *args, **kwargs: calls.append("runtime-health")
                uninstall.side_effect = lambda *args, **kwargs: calls.append("runtime-cleanup")
                popen.side_effect = (
                    lambda *args, **kwargs: calls.append("database-uninstall")
                    or _FakeProcess(stdout="uninstalled\n")
                )

                execute_plan(
                    plan,
                    connect="user/pass@db",
                    runner="sql",
                    runtime_prefix=str(prefix),
                )

    assert calls == ["runtime-health", "database-uninstall", "runtime-cleanup"]
    validate.assert_called_once_with(
        graph,
        prefix=prefix.resolve(),
        log_dir=(tmp_path / "logs").resolve(),
    )


def test_multi_package_uninstall_health_preflight_runs_before_database_scripts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "runtime"
    prefix.mkdir()
    graph = {"root_package": "consumer"}
    plan = {
        "mode": "uninstall",
        "application_runtime": graph,
        "packages": [
            {
                "mode": "uninstall",
                "package": {"application_name": "CONSUMER"},
                "pre_actions": [],
                "execution": {"script_ref": "consumer-uninstall.sql", "arguments": []},
            },
            {
                "mode": "uninstall",
                "package": {"application_name": "BASE"},
                "pre_actions": [],
                "execution": {"script_ref": "base-uninstall.sql", "arguments": []},
            },
        ],
    }
    calls = []

    with patch("dbpm.executor.validate_application_runtime_graph") as validate:
        with patch("dbpm.executor.uninstall_application_runtime_graph") as uninstall:
            with patch("dbpm.executor.subprocess.Popen") as popen:
                validate.side_effect = lambda *args, **kwargs: calls.append("runtime-health")
                uninstall.side_effect = lambda *args, **kwargs: calls.append("runtime-cleanup")
                popen.side_effect = (
                    lambda command, **kwargs: calls.append(command[-1])
                    or _FakeProcess(stdout="uninstalled\n")
                )

                execute_plan(
                    plan,
                    connect="user/pass@db",
                    runner="sql",
                    runtime_prefix=str(prefix),
                )

    assert calls == [
        "runtime-health",
        "@consumer-uninstall.sql",
        "@base-uninstall.sql",
        "runtime-cleanup",
    ]
    validate.assert_called_once()


def test_runtime_install_requires_prefix_before_database_script(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "package": {"application_name": "DEMO"},
        "pre_actions": [],
        "execution": {"script_ref": "install.sql", "arguments": []},
        "application_runtime": {"root_package": "demo"},
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        with pytest.raises(ExecutionError, match="requires --runtime-prefix"):
            execute_plan(plan, connect="user/pass@db", runner="sql")

    popen.assert_not_called()


def test_runtime_install_requires_existing_prefix_before_database_script(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    missing_prefix = tmp_path / "missing-runtime"
    plan = {
        "mode": "install",
        "package": {"application_name": "DEMO"},
        "pre_actions": [],
        "execution": {"script_ref": "install.sql", "arguments": []},
        "application_runtime": {"root_package": "demo"},
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        with pytest.raises(ExecutionError, match="does not exist or is not a directory"):
            execute_plan(
                plan,
                connect="user/pass@db",
                runner="sql",
                runtime_prefix=str(missing_prefix),
            )

    popen.assert_not_called()


def test_multi_package_runtime_install_preflights_prefix_before_database_scripts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "application_runtime": {"root_package": "consumer"},
        "packages": [
            {
                "mode": "install",
                "package": {"application_name": "BASE"},
                "pre_actions": [],
                "execution": {"script_ref": "base-install.sql", "arguments": []},
            },
            {
                "mode": "install",
                "package": {"application_name": "CONSUMER"},
                "pre_actions": [],
                "execution": {"script_ref": "consumer-install.sql", "arguments": []},
            },
        ],
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        with pytest.raises(ExecutionError, match="does not exist or is not a directory"):
            execute_plan(
                plan,
                connect="user/pass@db",
                runner="sql",
                runtime_prefix=str(tmp_path / "missing-runtime"),
            )

    popen.assert_not_called()


def test_runtime_install_rejects_foreign_prefix_before_database_actions(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "app_x"
    prefix.mkdir()
    _write_runtime_receipt(prefix, application="universal_file_loader")
    plan = {
        "mode": "install",
        "package": {"application_name": "APP_X"},
        "pre_actions": [
            {
                "type": "stage_deployment_provenance",
                "payload": {"application_name": "APP_X"},
            }
        ],
        "execution": {"script_ref": "install.sql", "arguments": []},
        "application_runtime": {"root_package": "app_x"},
    }

    with patch("dbpm.executor.stage_deployment_provenance") as stage:
        with patch("dbpm.executor.subprocess.Popen") as popen:
            with pytest.raises(
                ExecutionError,
                match=r"belongs to `universal_file_loader`, not `app_x`",
            ):
                execute_plan(
                    plan,
                    connect="user/pass@db",
                    runner="sql",
                    runtime_prefix=str(prefix),
                )

    stage.assert_not_called()
    popen.assert_not_called()


def test_multi_package_install_rejects_foreign_prefix_before_database_scripts(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    prefix = tmp_path / "app_x"
    prefix.mkdir()
    _write_runtime_receipt(prefix, application="universal_file_loader")
    plan = {
        "mode": "install",
        "application_runtime": {"root_package": "app_x"},
        "packages": [
            {
                "mode": "install",
                "package": {"application_name": "UNIVERSAL_FILE_LOADER"},
                "pre_actions": [],
                "execution": {"script_ref": "ufl-install.sql", "arguments": []},
            },
            {
                "mode": "install",
                "package": {"application_name": "APP_X"},
                "pre_actions": [],
                "execution": {"script_ref": "app-x-install.sql", "arguments": []},
            },
        ],
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        with pytest.raises(
            ExecutionError,
            match=r"belongs to `universal_file_loader`, not `app_x`",
        ):
            execute_plan(
                plan,
                connect="user/pass@db",
                runner="sql",
                runtime_prefix=str(prefix),
            )

    popen.assert_not_called()


def test_execute_plan_uses_sqlcl_named_connection_as_single_argument(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "package": {
            "application_name": "DEMO",
        },
        "pre_actions": [],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": ["abc"],
        },
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.return_value = _FakeProcess(stdout="deployed\n")
        execute_plan(plan, connect=sqlcl_name("Development Database (APP_USER)"), runner="sql")

    assert popen.call_args.args[0] == [
        "sql",
        "-S",
        "-L",
        "-name",
        "Development Database (APP_USER)",
        "@deploy.sql",
        "abc",
    ]


def test_execute_plan_runs_core_teardown_before_reinstall_script(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "reinstall",
        "package": {
            "application_name": "CORE",
        },
        "pre_actions": [
            {
                "type": "delete_system",
            },
            {
                "type": "execute_script",
                "script_ref": "Deployment_Manifests/uninstall.core.sql",
                "arguments": [],
                "stdin": "YES\n",
            },
        ],
        "execution": {
            "script_ref": "Deployment_Manifests/deploy.sql",
            "arguments": ["abc"],
            "stdin": "N\nDEV\n",
        },
    }
    calls = []

    with patch("dbpm.executor.delete_system") as delete_system:
        with patch("dbpm.executor.subprocess.Popen") as popen:
            delete_system.side_effect = lambda **kwargs: calls.append(("delete_system", kwargs))
            popen.side_effect = (
                lambda *args, **kwargs: calls.append(("script", args[0], kwargs.get("stdin")))
                or _FakeProcess(stdout="ok\n")
            )
            execute_plan(plan, connect="user/pass@db", runner="sql")

    assert calls == [
        ("delete_system", {"connect": "user/pass@db", "runner": "sql"}),
        (
            "script",
            ["sql", "-L", "user/pass@db", "@Deployment_Manifests/uninstall.core.sql"],
            subprocess.PIPE,
        ),
        (
            "script",
            ["sql", "-L", "user/pass@db", "@Deployment_Manifests/deploy.sql", "abc"],
            subprocess.PIPE,
        ),
    ]
    logs = sorted(path.name for path in (tmp_path / "logs").glob("*.log"))
    assert len(logs) == 2
    assert logs[0].endswith("-001-CORE-reinstall.log")
    assert logs[1].endswith("-002-CORE-reinstall.log")


def test_graph_reinstall_deletes_consumer_first_before_any_install(tmp_path, monkeypatch):
    events = []
    plan = {
        "mode": "reinstall",
        "graph_reinstall": True,
        "package": {"application_name": "CONSUMER"},
        "removal_order": ["CONSUMER", "BASE"],
        "packages": [
            {
                "mode": "reinstall",
                "package": {"application_name": "BASE"},
                "execution": {"script_ref": "/tmp/base.sql", "arguments": [], "stdin": None},
                "pre_actions": [], "post_actions": [],
            },
            {
                "mode": "reinstall",
                "package": {"application_name": "CONSUMER"},
                "execution": {"script_ref": "/tmp/consumer.sql", "arguments": [], "stdin": None},
                "pre_actions": [], "post_actions": [],
            },
        ],
    }
    monkeypatch.setattr(
        "dbpm.executor.delete_application",
        lambda **kwargs: events.append(("delete", kwargs["application_name"])),
    )
    monkeypatch.setattr(
        "dbpm.executor._run_command",
        lambda command, **kwargs: events.append(("install", str(command[-1]))) or 0,
    )
    record = OperationRecord("op-1", "CONSUMER", "reinstall", "RESOLVED", 0, None, None)
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    monkeypatch.setattr("dbpm.executor.begin_operation", lambda **kwargs: record)
    monkeypatch.setattr("dbpm.executor.acquire_operation_lease", lambda **kwargs: lease)
    monkeypatch.setattr(
        "dbpm.executor.release_operation_lease",
        lambda **kwargs: events.append(("release", kwargs["lease"].operation_id)),
    )

    execute_plan(plan, connect="user/pass@db", runner="sql", context=None)

    assert events[:2] == [("delete", "CONSUMER"), ("delete", "BASE")]
    assert [kind for kind, _ in events[2:4]] == ["install", "install"]
    assert events[-1] == ("release", "op-1")


def test_graph_reinstall_releases_lease_when_delete_fails(monkeypatch):
    plan = {
        "mode": "reinstall",
        "graph_reinstall": True,
        "package": {"application_name": "CONSUMER"},
        "removal_order": ["CONSUMER"],
        "packages": [],
    }
    record = OperationRecord("op-graph", "CONSUMER", "reinstall", "RESOLVED", 0, None, None)
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    released = []
    monkeypatch.setattr("dbpm.executor.begin_operation", lambda **kwargs: record)
    monkeypatch.setattr("dbpm.executor.acquire_operation_lease", lambda **kwargs: lease)
    monkeypatch.setattr(
        "dbpm.executor.delete_application",
        lambda **kwargs: (_ for _ in ()).throw(ExecutionError("boom")),
    )
    monkeypatch.setattr(
        "dbpm.executor.release_operation_lease",
        lambda **kwargs: released.append(kwargs["lease"].operation_id),
    )

    with pytest.raises(ExecutionError, match="boom"):
        execute_plan(plan, connect="user/pass@db", runner="sql")

    assert released == ["op-graph"]


def test_graph_reinstall_reuses_outer_composite_lease(monkeypatch):
    plan = {
        "mode": "reinstall",
        "graph_reinstall": True,
        "package": {"application_name": "CONSUMER"},
        "removal_order": ["CONSUMER"],
        "packages": [],
    }
    monkeypatch.setattr(
        "dbpm.executor.begin_operation",
        lambda **kwargs: pytest.fail("outer composite lease should be reused"),
    )
    monkeypatch.setattr("dbpm.executor.delete_application", lambda **kwargs: None)
    from dbpm.executor import _new_execution_context
    context = _new_execution_context()
    context.defer_runtime = True

    assert execute_plan(
        plan, connect="user/pass@db", runner="sql", context=context
    ) == 0


def test_environment_reset_acquires_and_releases_operation_lease(tmp_path, monkeypatch):
    events = []
    plan = {
        "environment_reset": True,
        "removal_order": ["CONSUMER", "BASE"],
        "runtime_removals": [],
    }
    monkeypatch.setattr(
        "dbpm.executor.delete_application",
        lambda **kwargs: events.append(("delete", kwargs["application_name"])),
    )
    monkeypatch.setattr(
        "dbpm.executor.get_installed_application_graph",
        lambda **kwargs: (["CORE"], []),
    )
    record = OperationRecord("op-env", "CORE", "environment-reset", "RESOLVED", 0, None, None)
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    begin_calls = []
    monkeypatch.setattr(
        "dbpm.executor.begin_operation",
        lambda **kwargs: begin_calls.append(kwargs) or record,
    )
    monkeypatch.setattr("dbpm.executor.acquire_operation_lease", lambda **kwargs: lease)
    monkeypatch.setattr(
        "dbpm.executor.release_operation_lease",
        lambda **kwargs: events.append(("release", kwargs["lease"].operation_id)),
    )

    assert execute_plan(plan, connect="user/pass@db", runner="sql", context=None) == 0

    assert begin_calls[0]["application_name"] == "CORE"
    assert events == [("delete", "CONSUMER"), ("delete", "BASE"), ("release", "op-env")]


def test_environment_reset_releases_lease_even_when_delete_fails(tmp_path, monkeypatch):
    plan = {
        "environment_reset": True,
        "removal_order": ["CONSUMER"],
        "runtime_removals": [],
    }
    monkeypatch.setattr(
        "dbpm.executor.delete_application",
        lambda **kwargs: (_ for _ in ()).throw(ExecutionError("boom")),
    )
    record = OperationRecord("op-env", "CORE", "environment-reset", "RESOLVED", 0, None, None)
    lease = OperationLease(record.operation_id, 1, "token", "expiry")
    released = []
    monkeypatch.setattr("dbpm.executor.begin_operation", lambda **kwargs: record)
    monkeypatch.setattr("dbpm.executor.acquire_operation_lease", lambda **kwargs: lease)
    monkeypatch.setattr(
        "dbpm.executor.release_operation_lease",
        lambda **kwargs: released.append(kwargs["lease"].operation_id),
    )

    with pytest.raises(ExecutionError):
        execute_plan(plan, connect="user/pass@db", runner="sql", context=None)

    assert released == ["op-env"]


def test_execute_plan_runs_record_post_action_after_script(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    payload = {
        "application_name": "CORE",
        "version": "3.4.0",
        "deploy_commit_hash": "123",
    }
    plan = {
        "mode": "bootstrap-core",
        "package": {
            "application_name": "CORE",
        },
        "pre_actions": [],
        "post_actions": [
            {
                "type": "record_deployment_provenance",
                "payload": payload,
            }
        ],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": ["123"],
        },
    }
    calls = []

    with patch("dbpm.executor.record_deployment_provenance") as record:
        with patch("dbpm.executor.subprocess.Popen") as popen:
            record.side_effect = lambda **kwargs: calls.append(("record", kwargs))
            popen.side_effect = lambda *args, **kwargs: calls.append(("script", args[0])) or _FakeProcess(stdout="deployed\n")
            execute_plan(plan, connect="user/pass@db", runner="sql")

    assert calls[0] == ("script", ["sql", "-L", "user/pass@db", "@deploy.sql", "123"])
    assert calls[1] == (
        "record",
        {
            "connect": "user/pass@db",
            "runner": "sql",
            "payload": payload,
        },
    )


def test_execute_plan_failure_mentions_log_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    plan = {
        "mode": "install",
        "package": {
            "application_name": "DEMO",
        },
        "pre_actions": [],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": [],
        },
    }

    with patch("dbpm.executor.subprocess.Popen") as popen:
        popen.return_value = _FakeProcess(returncode=7, stdout="boom\n")
        with pytest.raises(ExecutionError, match=r"exit code 7; see .*DEMO-install\.log"):
            execute_plan(plan, connect="user/pass@db", runner="sql")

    logs = list((tmp_path / "logs").glob("*-001-DEMO-install.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8") == "boom\n"
