import io
from unittest.mock import patch

import pytest

from dbpm.errors import ExecutionError
from dbpm.executor import execute_plan


class _FakeProcess:
    def __init__(self, *, returncode: int = 0, stdout: str = "ok\n"):
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)

    def wait(self) -> int:
        return self.returncode


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
        popen.return_value = _FakeProcess(stdout="ok\n")
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
