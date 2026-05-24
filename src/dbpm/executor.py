from __future__ import annotations

import subprocess
from pathlib import Path

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

    command = [runner, "-L", connect, f"@{script_ref}", *[str(arg) for arg in arguments]]
    try:
        result = subprocess.run(command, cwd=_cwd_for_script(script_ref))
    except FileNotFoundError as exc:
        raise ExecutionError(f"SQL runner not found: {runner}") from exc
    if result.returncode != 0:
        raise ExecutionError(f"Deployment command failed with exit code {result.returncode}")
    return result.returncode


def _cwd_for_script(script_ref: object) -> str | None:
    path = Path(str(script_ref))
    if path.exists():
        return str(path.parent)
    return None
