from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from .connect import ConnectSpec, build_sql_command
from .db import delete_application, delete_system, record_deployment_provenance, stage_deployment_provenance
from .errors import ExecutionError


FALLBACK_EXIT_COMMAND = "EXIT SUCCESS\n"


@dataclass
class _ExecutionContext:
    run_id: str
    log_dir: Path
    sequence: int = 0


def execute_plan(
    plan: dict[str, object],
    *,
    connect: str | ConnectSpec,
    runner: str,
    context: _ExecutionContext | None = None,
) -> int:
    context = context or _new_execution_context()
    packages = plan.get("packages")
    if packages is not None:
        if not isinstance(packages, list):
            raise ExecutionError("Multi-package plan packages must be a list")
        for child_plan in packages:
            if not isinstance(child_plan, dict):
                raise ExecutionError("Multi-package plan entries must be objects")
            execute_plan(child_plan, connect=connect, runner=runner, context=context)
        return 0

    execution = plan.get("execution")
    if not isinstance(execution, dict):
        raise ExecutionError("Plan does not contain execution details")

    script_ref = execution.get("script_ref")
    arguments = execution.get("arguments", [])
    input_text = execution.get("stdin")
    if not script_ref:
        raise ExecutionError("Plan does not contain an executable script")
    if not isinstance(arguments, list):
        raise ExecutionError("Plan execution arguments must be a list")
    if input_text is not None and not isinstance(input_text, str):
        raise ExecutionError("Plan execution stdin must be a string")

    _execute_pre_actions(plan, connect=connect, runner=runner, context=context)

    command = build_sql_command(runner=runner, connect=connect, script_ref=script_ref, arguments=arguments)
    log_file = _next_log_file(context, plan)
    try:
        returncode = _run_command(
            command,
            cwd=_cwd_for_script(script_ref),
            log_file=log_file,
            input_text=input_text,
        )
    except FileNotFoundError as exc:
        raise ExecutionError(f"SQL runner not found: {runner}") from exc
    if returncode != 0:
        raise ExecutionError(f"Deployment command failed with exit code {returncode}; see {log_file}")
    _execute_post_actions(plan, connect=connect, runner=runner)
    return returncode


def _new_execution_context() -> _ExecutionContext:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_dir = Path(os.environ.get("DBPM_LOG_DIR", ".dbpm-logs")).expanduser().resolve()
    return _ExecutionContext(run_id=run_id, log_dir=log_dir)


def _next_log_file(context: _ExecutionContext, plan: dict[str, object]) -> Path:
    context.sequence += 1
    package = plan.get("package")
    app_name = "package"
    if isinstance(package, dict):
        app_name = str(package.get("application_name") or package.get("name") or app_name)
    mode = str(plan.get("mode") or "execute")
    file_name = f"{context.run_id}-{context.sequence:03d}-{_safe_name(app_name)}-{_safe_name(mode)}.log"
    context.log_dir.mkdir(parents=True, exist_ok=True)
    return context.log_dir / file_name


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)


def _run_command(command: list[str], *, cwd: str | None, log_file: Path, input_text: str | None = None) -> int:
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if process.stdin is not None:
            process.stdin.write(_runner_stdin(input_text))
            process.stdin.close()
        if process.stdout is not None:
            _tee_output(process.stdout, log)
        return process.wait()


def _runner_stdin(input_text: str | None) -> str:
    if not input_text:
        return FALLBACK_EXIT_COMMAND
    separator = "" if input_text.endswith("\n") else "\n"
    return f"{input_text}{separator}{FALLBACK_EXIT_COMMAND}"


def _tee_output(source: TextIO, log: TextIO) -> None:
    for line in source:
        sys.stdout.write(line)
        sys.stdout.flush()
        log.write(line)
        log.flush()


def _execute_pre_actions(
    plan: dict[str, object],
    *,
    connect: str | ConnectSpec,
    runner: str,
    context: _ExecutionContext,
) -> None:
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
        elif action_type == "delete_system":
            delete_system(connect=connect, runner=runner)
        elif action_type == "execute_script":
            script_ref = action.get("script_ref")
            arguments = action.get("arguments", [])
            input_text = action.get("stdin")
            if not script_ref:
                raise ExecutionError("execute_script pre-action requires script_ref")
            if not isinstance(arguments, list):
                raise ExecutionError("execute_script pre-action arguments must be a list")
            if input_text is not None and not isinstance(input_text, str):
                raise ExecutionError("execute_script pre-action stdin must be a string")
            command = build_sql_command(runner=runner, connect=connect, script_ref=script_ref, arguments=arguments)
            log_file = _next_log_file(context, plan)
            try:
                returncode = _run_command(
                    command,
                    cwd=_cwd_for_script(script_ref),
                    log_file=log_file,
                    input_text=input_text,
                )
            except FileNotFoundError as exc:
                raise ExecutionError(f"SQL runner not found: {runner}") from exc
            if returncode != 0:
                raise ExecutionError(f"Pre-action script failed with exit code {returncode}; see {log_file}")
        elif action_type == "stage_deployment_provenance":
            payload = action.get("payload")
            if not isinstance(payload, dict):
                raise ExecutionError("stage_deployment_provenance pre-action requires payload")
            stage_deployment_provenance(connect=connect, runner=runner, payload=payload)
        else:
            raise ExecutionError(f"Unsupported pre-action: {action_type}")


def _execute_post_actions(plan: dict[str, object], *, connect: str | ConnectSpec, runner: str) -> None:
    post_actions = plan.get("post_actions", [])
    if not isinstance(post_actions, list):
        raise ExecutionError("Plan post_actions must be a list")

    for action in post_actions:
        if not isinstance(action, dict):
            raise ExecutionError("Plan post_actions entries must be objects")
        action_type = action.get("type")
        if action_type == "record_deployment_provenance":
            payload = action.get("payload")
            if not isinstance(payload, dict):
                raise ExecutionError("record_deployment_provenance post-action requires payload")
            record_deployment_provenance(connect=connect, runner=runner, payload=payload)
        else:
            raise ExecutionError(f"Unsupported post-action: {action_type}")


def _cwd_for_script(script_ref: object) -> str | None:
    path = Path(str(script_ref))
    if path.exists():
        return str(path.parent)
    return None
