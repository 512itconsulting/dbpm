import io
import json
import subprocess
from unittest.mock import patch

import pytest

from dbpm.errors import ExecutionError
from dbpm.executor import execute_plan
from dbpm.connect import sqlcl_name


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


def test_execute_plan_runs_delete_pre_action_before_script(tmp_path, monkeypatch):
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
