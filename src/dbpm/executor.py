from __future__ import annotations

import subprocess
from pathlib import Path

from .db import delete_application
from .errors import ExecutionError


def execute_plan(plan: dict[str, object], *, connect: str, runner: str) -> int:
    execution = plan.get("execution")
    if not isinstance(execution, dict):
        raise ExecutionError("Plan does not contain execution details")

    script_ref = execution.get("script_ref")
    arguments = execution.get("arguments", [])
    if not script_ref:
        raise ExecutionError("Plan does not contain an executable script")
    if not isinstance(arguments, list):
        raise ExecutionError("Plan execution arguments must be a list")

    _execute_pre_actions(plan, connect=connect, runner=runner)

    command = [runner, "-L", connect, f"@{script_ref}", *[str(arg) for arg in arguments]]
    try:
        result = subprocess.run(command, cwd=_cwd_for_script(script_ref))
    except FileNotFoundError as exc:
        raise ExecutionError(f"SQL runner not found: {runner}") from exc
    if result.returncode != 0:
        raise ExecutionError(f"Deployment command failed with exit code {result.returncode}")
    return result.returncode


def _execute_pre_actions(plan: dict[str, object], *, connect: str, runner: str) -> None:
    pre_actions = plan.get("pre_actions", [])
    if not isinstance(pre_actions, list):
        raise ExecutionError("Plan pre_actions must be a list")

    for action in pre_actions:
        if not isinstance(action, dict):
            raise ExecutionError("Plan pre_actions entries must be objects")
        action_type = action.get("type")
        if action_type == "delete_application":
            application_name = action.get("application_name")
            if not application_name:
                raise ExecutionError("delete_application pre-action requires application_name")
            delete_application(
                connect=connect,
                runner=runner,
                application_name=str(application_name),
                fail_on_not_found=str(action.get("fail_on_not_found", "N")),
            )
        else:
            raise ExecutionError(f"Unsupported pre-action: {action_type}")


def _cwd_for_script(script_ref: object) -> str | None:
    path = Path(str(script_ref))
    if path.exists():
        return str(path.parent)
    return None
