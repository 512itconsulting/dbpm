import subprocess
from unittest.mock import patch

from dbpm.executor import execute_plan


def test_execute_plan_runs_delete_pre_action_before_script():
    plan = {
        "pre_actions": [
            {
                "type": "delete_application",
                "application_name": "DEMO",
                "fail_on_not_found": "N",
            }
        ],
        "execution": {
            "script_ref": "deploy.sql",
            "arguments": ["123"],
        },
    }

    with patch("dbpm.executor.delete_application") as delete_application:
        with patch("dbpm.executor.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            execute_plan(plan, connect="user/pass@db", runner="sql")

    delete_application.assert_called_once_with(
        connect="user/pass@db",
        runner="sql",
        application_name="DEMO",
        fail_on_not_found="N",
    )
    run.assert_called_once()
    assert run.call_args.args[0] == ["sql", "-L", "user/pass@db", "@deploy.sql", "123"]
