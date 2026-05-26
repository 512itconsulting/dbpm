import subprocess
from unittest.mock import patch

from dbpm.executor import execute_plan


def test_execute_plan_runs_delete_pre_action_before_script():
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
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": ["123"],
        },
    }

    with patch("dbpm.executor.delete_application") as delete_application:
        with patch("dbpm.executor.stage_deployment_provenance") as stage:
            with patch("dbpm.executor.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                execute_plan(plan, connect="user/pass@db", runner="sql")

    delete_application.assert_called_once_with(
        connect="user/pass@db",
        runner="sql",
        application_name="DEMO",
        fail_on_not_found="N",
    )
    stage.assert_called_once_with(connect="user/pass@db", runner="sql", payload=payload)
    run.assert_called_once()
    assert run.call_args.args[0] == ["sql", "-L", "user/pass@db", "@deploy.sql", "123"]


def test_execute_plan_runs_multi_package_children_in_order():
    plan = {
        "packages": [
            {
                "pre_actions": [],
                "execution": {
                    "script_ref": "base.sql",
                    "arguments": [],
                },
            },
            {
                "pre_actions": [],
                "execution": {
                    "script_ref": "consumer.sql",
                    "arguments": ["abc"],
                },
            },
        ]
    }

    with patch("dbpm.executor.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        assert execute_plan(plan, connect="user/pass@db", runner="sql") == 0

    assert run.call_count == 2
    assert run.call_args_list[0].args[0] == ["sql", "-L", "user/pass@db", "@base.sql"]
    assert run.call_args_list[1].args[0] == [
        "sql",
        "-L",
        "user/pass@db",
        "@consumer.sql",
        "abc",
    ]
