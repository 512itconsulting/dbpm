from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from .connect import ConnectSpec, build_sql_command
from .db import (
    acquire_operation_lease,
    begin_operation,
    delete_application,
    delete_system,
    get_current_operation,
    get_application_state,
    get_installed_application_graph,
    record_deployment_provenance,
    record_operation_step,
    renew_operation_lease,
    release_operation_lease,
    stage_deployment_provenance,
)
from .errors import ExecutionError
from .progress import report_progress
from .application_runtime import (
    activate_staged_application_runtime,
    stage_application_runtime_graph,
    validate_application_runtime_graph,
    resume_application_runtime_graph,
    garbage_collect_application_runtime,
    load_application_runtime_receipt,
    purge_classified_state,
    uninstall_application_runtime_graph,
    validate_application_runtime_prefix,
    validate_application_runtime_collisions,
)


FALLBACK_EXIT_COMMAND = "EXIT SUCCESS\n"


@dataclass
class _ExecutionContext:
    run_id: str
    log_dir: Path
    sequence: int = 0
    package_index: int = 0
    package_total: int = 0
    defer_runtime: bool = False


def execute_plan(
    plan: dict[str, object],
    *,
    connect: str | ConnectSpec | None,
    runner: str,
    runtime_prefix: str | None = None,
    context: _ExecutionContext | None = None,
) -> int:
    if context is None and plan.get("environment_reset") is True:
        if connect is None:
            raise ExecutionError("Environment reset requires a Core connection")
        context = _new_execution_context()
        record = begin_operation(
            connect=connect, runner=runner, operation_id=str(uuid.uuid4()),
            application_name="CORE", mode="environment-reset",
        )
        lease = acquire_operation_lease(
            connect=connect, runner=runner, operation_id=record.operation_id,
            lease_token=uuid.uuid4().hex,
        )
        try:
            runtime_removals = plan.get("runtime_removals", [])
            if not isinstance(runtime_removals, list):
                raise ExecutionError("Environment reset runtime_removals must be a list")
            purge_categories = set(plan.get("purge_categories") or [])
            for item in runtime_removals:
                if not isinstance(item, dict) or not isinstance(item.get("graph"), dict):
                    raise ExecutionError("Environment reset runtime removal must contain a graph")
                prefix = Path(str(item.get("prefix"))).expanduser().resolve()
                report_progress(f"Removing application runtime at {prefix}...")
                uninstall_application_runtime_graph(
                    item["graph"], prefix=prefix, log_dir=context.log_dir
                )
                if purge_categories:
                    classification = item.get("classification")
                    deleted = purge_classified_state(
                        prefix,
                        classification if isinstance(classification, dict) else {},
                        purge_categories,
                    )
                    if deleted:
                        report_progress(
                            f"Purged {len(deleted)} {'/'.join(sorted(purge_categories))} "
                            f"path(s) under {prefix}"
                        )
            removal_order = plan.get("removal_order")
            if not isinstance(removal_order, list):
                raise ExecutionError("Environment reset requires a removal_order")
            for application_name in removal_order:
                report_progress(f"Removing {application_name}...")
                delete_application(
                    connect=connect, runner=runner, application_name=str(application_name),
                    fail_on_not_found="Y",
                )
            remaining, _ = get_installed_application_graph(connect=connect, runner=runner)
            unexpected = [name for name in remaining if name.upper() != "CORE"]
            if unexpected:
                raise ExecutionError(
                    "Environment reset audit found registered applications: "
                    + ", ".join(sorted(unexpected))
                )
        finally:
            release_operation_lease(connect=connect, runner=runner, lease=lease)
        return 0
    if context is None and isinstance(plan.get("operation"), dict):
        return _execute_composite_operation(
            plan, connect=connect, runner=runner, runtime_prefix=runtime_prefix
        )
    context = context or _new_execution_context()
    application_runtime = plan.get("application_runtime")
    if application_runtime is not None and not isinstance(application_runtime, dict):
        raise ExecutionError("Application runtime plan must be an object")
    packages = plan.get("packages")
    if packages is not None:
        if not isinstance(packages, list):
            raise ExecutionError("Multi-package plan packages must be a list")
        context.package_total = len(packages)
        if application_runtime is not None and not context.defer_runtime:
            report_progress("Validating application runtime prefix...")
        if not context.defer_runtime:
            _preflight_application_runtime(
                application_runtime,
                mode=str(plan.get("mode") or "install"),
                runtime_prefix=runtime_prefix,
                context=context,
            )
        graph_reinstall_lease = None
        if plan.get("graph_reinstall") is True:
            if connect is None:
                raise ExecutionError("Graph reinstall requires a Core connection")
            removal_order = plan.get("removal_order")
            if not isinstance(removal_order, list):
                raise ExecutionError("Graph reinstall requires a removal_order")
            # Runtime-backed graph reinstalls are already fenced by the outer
            # composite operation. Database-only plans need their own lease.
            if not context.defer_runtime:
                package = plan.get("package")
                root_application_name = (
                    str(package.get("application_name"))
                    if isinstance(package, dict) else ""
                )
                if not root_application_name:
                    raise ExecutionError(
                        "Graph reinstall requires a root package application_name"
                    )
                record = begin_operation(
                    connect=connect, runner=runner, operation_id=str(uuid.uuid4()),
                    application_name=root_application_name, mode="reinstall",
                )
                graph_reinstall_lease = acquire_operation_lease(
                    connect=connect, runner=runner, operation_id=record.operation_id,
                    lease_token=uuid.uuid4().hex,
                )
        try:
            if plan.get("graph_reinstall") is True:
                removal_order = plan.get("removal_order")
                assert isinstance(removal_order, list)
                for application_name in removal_order:
                    report_progress(
                        f"Removing {application_name} before graph reinstall..."
                    )
                    delete_application(
                        connect=connect,
                        runner=runner,
                        application_name=str(application_name),
                        fail_on_not_found="N",
                    )
            for child_plan in packages:
                if not isinstance(child_plan, dict):
                    raise ExecutionError("Multi-package plan entries must be objects")
                execute_plan(
                    child_plan,
                    connect=connect,
                    runner=runner,
                    runtime_prefix=runtime_prefix,
                    context=context,
                )
            if application_runtime is not None:
                _execute_application_runtime(
                    application_runtime,
                    mode=str(plan.get("mode") or "install"),
                    runtime_prefix=runtime_prefix,
                    context=context,
                )
        finally:
            if graph_reinstall_lease is not None:
                release_operation_lease(connect=connect, runner=runner, lease=graph_reinstall_lease)
        return 0

    execution = plan.get("execution")
    if not isinstance(execution, dict):
        raise ExecutionError("Plan does not contain execution details")

    script_ref = execution.get("script_ref")
    arguments = execution.get("arguments", [])
    input_text = execution.get("stdin")
    if not script_ref and application_runtime is None and plan.get("runtime_package") is None:
        raise ExecutionError("Plan does not contain an executable script")
    if not isinstance(arguments, list):
        raise ExecutionError("Plan execution arguments must be a list")
    if input_text is not None and not isinstance(input_text, str):
        raise ExecutionError("Plan execution stdin must be a string")

    if not context.defer_runtime:
        _preflight_application_runtime(
            application_runtime,
            mode=str(plan.get("mode") or "install"),
            runtime_prefix=runtime_prefix,
            context=context,
        )

    if script_ref:
        if connect is None:
            raise ExecutionError("Database deployment requires a connect specification")
        context.package_index += 1
        identity = _package_progress_identity(plan)
        position = (
            f" ({context.package_index}/{context.package_total})"
            if context.package_total
            else ""
        )
        report_progress(f"Deploying {identity}{position}...")
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

    if application_runtime is not None and not context.defer_runtime:
        _execute_application_runtime(
            application_runtime,
            mode=str(plan.get("mode") or "install"),
            runtime_prefix=runtime_prefix,
            context=context,
        )
    return 0


def _execute_composite_operation(
    plan: dict[str, object], *, connect: str | ConnectSpec | None,
    runner: str, runtime_prefix: str | None,
) -> int:
    if connect is None:
        raise ExecutionError("Composite operations require a Core connection")
    operation = plan.get("operation")
    assert isinstance(operation, dict)
    package = plan.get("package")
    if not isinstance(package, dict):
        raise ExecutionError("Composite operation requires a root package")
    application_name = str(package.get("application_name") or package.get("name") or "")
    mode = str(plan.get("mode") or "install")
    operation_id = str(operation.get("operation_id") or uuid.uuid4())
    resume_existing = bool(operation.get("resume_existing"))
    record = (
        get_current_operation(
            connect=connect, runner=runner, application_name=application_name
        )
        if resume_existing
        else begin_operation(
            connect=connect, runner=runner, operation_id=operation_id,
            application_name=application_name, mode=mode,
        )
    )
    if record is None:
        raise ExecutionError(f"No recoverable operation exists for {application_name}")
    lease = acquire_operation_lease(
        connect=connect, runner=runner, operation_id=record.operation_id,
        lease_token=uuid.uuid4().hex,
    )
    context = _new_execution_context()
    context.defer_runtime = True
    graph = plan.get("application_runtime")
    assert isinstance(graph, dict)
    prefix = Path(runtime_prefix).expanduser().resolve() if runtime_prefix else None
    database_complete = record.state in {
        "DATABASE_COMPLETE", "RUNTIME_UNREACHABLE", "RUNTIME_ACTIVE", "VALIDATED"
    }
    if resume_existing and not database_complete:
        # The recorded operation state is the authoritative evidence of what
        # completed. Only fall back to a live Core status check when that
        # evidence doesn't already show the database phase finished — this
        # covers a crash between database completion and the step-evidence
        # write, without ever discarding evidence that already says "done".
        database_complete = _database_evidence_valid(
            plan, connect=connect, runner=runner
        )
    try:
        if not database_complete:
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="resolved", state="RESOLVED",
                content_ref=str(operation.get("plan_digest") or ""),
            )
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="policy_evaluated", state="RESOLVED",
                content_ref=str(operation.get("plan_digest") or ""),
            )
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="initiating_surface", state="RESOLVED",
                content_ref=str(operation.get("initiating_surface") or mode),
            )
        else:
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="database_reverified", state="DATABASE_COMPLETE",
                content_ref=application_name,
            )
        reachable = bool(prefix and prefix.is_dir() and os.access(prefix, os.W_OK))
        if reachable:
            _preflight_application_runtime(
                graph,
                mode=(
                    "reinstall" if plan.get("runtime_reconcile_replace") is True
                    else "resume" if database_complete else mode
                ),
                runtime_prefix=runtime_prefix, context=context,
            )
            if not database_complete:
                record_operation_step(
                    connect=connect, runner=runner, lease=lease,
                    step="runtime_staged", state="RUNTIME_STAGED", content_ref=str(prefix),
                )
                record_operation_step(
                    connect=connect, runner=runner, lease=lease,
                    step="collisions_validated", state="RUNTIME_STAGED",
                    content_ref=str(prefix),
                )
        if not database_complete:
            lease = renew_operation_lease(connect=connect, runner=runner, lease=lease)
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="database_started", state="RUNTIME_STAGED", content_ref=application_name,
            )
            try:
                execute_plan(
                    plan, connect=connect, runner=runner,
                    runtime_prefix=runtime_prefix, context=context,
                )
            except Exception:
                record_operation_step(
                    connect=connect, runner=runner, lease=lease,
                    step="database", state="FAILED", content_ref="database",
                )
                raise
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="database", state="DATABASE_COMPLETE", content_ref=application_name,
            )
        if not reachable:
            record_operation_step(
                connect=connect, runner=runner, lease=lease,
                step="runtime_reachability", state="RUNTIME_UNREACHABLE",
                content_ref=str(operation.get("receipt_checksum") or ""),
            )
            raise ExecutionError(
                f"Runtime prefix is unreachable: {runtime_prefix}; database phase is complete. "
                "Run `dbpm runtime reconcile` when it is reachable."
            )
        lease = renew_operation_lease(connect=connect, runner=runner, lease=lease)
        try:
            _execute_application_runtime(
                graph, mode="resume" if database_complete else mode,
                runtime_prefix=runtime_prefix, context=context,
                recovery_mode=(
                    "reinstall" if plan.get("runtime_reconcile_replace") is True
                    else record.mode.lower() if database_complete else None
                ),
            )
            receipt = load_application_runtime_receipt(
                prefix, expected_application=str(graph.get("root_package") or "")
            )
        except Exception:
            if not prefix.is_dir() or not os.access(prefix, os.W_OK):
                record_operation_step(
                    connect=connect, runner=runner, lease=lease,
                    step="runtime_reachability", state="RUNTIME_UNREACHABLE",
                    content_ref=str(operation.get("receipt_checksum") or ""),
                )
            raise
        record_operation_step(
            connect=connect, runner=runner, lease=lease,
            step="runtime_active", state="RUNTIME_ACTIVE",
            content_ref=str(receipt.generation),
        )
        validate_application_runtime_graph(graph, prefix=prefix, log_dir=context.log_dir)
        record_operation_step(
            connect=connect, runner=runner, lease=lease,
            step="validated", state="VALIDATED", content_ref=str(receipt.generation),
        )
        record_operation_step(
            connect=connect, runner=runner, lease=lease,
            step="composite_complete", state="VALIDATED",
            content_ref=str(receipt.generation),
        )
        return 0
    finally:
        release_operation_lease(connect=connect, runner=runner, lease=lease)


def _database_evidence_valid(
    plan: dict[str, object], *, connect: str | ConnectSpec, runner: str,
) -> bool:
    packages = plan.get("packages")
    items = packages if isinstance(packages, list) else [plan]
    checked = False
    for item in items:
        if not isinstance(item, dict):
            continue
        execution = item.get("execution")
        package = item.get("package")
        if not isinstance(execution, dict) or not execution.get("script"):
            continue
        if not isinstance(package, dict):
            return False
        app_name = package.get("application_name")
        if not isinstance(app_name, str):
            return False
        checked = True
        state = get_application_state(
            connect=connect, runner=runner, application_name=app_name
        )
        if state is None or state.deploy_status != "C":
            return False
    return checked or all(
        isinstance(item, dict)
        and isinstance(item.get("execution"), dict)
        and not item["execution"].get("script")
        for item in items
    )


def _preflight_application_runtime(
    graph: dict[str, object] | None,
    *,
    mode: str,
    runtime_prefix: str | None,
    context: _ExecutionContext,
) -> None:
    if graph is None:
        return
    if not runtime_prefix:
        raise ExecutionError("Application runtime requires --runtime-prefix")
    root_package = graph.get("root_package")
    if not isinstance(root_package, str) or not root_package:
        raise ExecutionError("Application runtime graph root_package must be a non-empty string")
    prefix = Path(runtime_prefix).expanduser().resolve()
    validate_application_runtime_prefix(
        prefix,
        expected_application=root_package,
    )
    if mode == "uninstall":
        validate_application_runtime_graph(
            graph,
            prefix=prefix,
            log_dir=context.log_dir,
        )
    elif mode in {"install", "upgrade", "reinstall", "resume"}:
        validate_application_runtime_collisions(graph, prefix=prefix, mode=mode)


def _execute_application_runtime(
    graph: dict[str, object],
    *,
    mode: str,
    runtime_prefix: str | None,
    context: _ExecutionContext,
    recovery_mode: str | None = None,
) -> None:
    if not runtime_prefix:
        raise ExecutionError("Application runtime requires --runtime-prefix")
    prefix = Path(runtime_prefix).expanduser().resolve()
    if mode == "validate":
        report_progress("Validating application runtime...")
        validate_application_runtime_graph(
            graph,
            prefix=prefix,
            log_dir=context.log_dir,
        )
        return
    if mode == "uninstall":
        report_progress("Removing application runtime...")
        uninstall_application_runtime_graph(
            graph,
            prefix=prefix,
            log_dir=context.log_dir,
        )
        return
    if mode == "resume":
        report_progress("Resuming application runtime staging...")
        staged = resume_application_runtime_graph(
            graph,
            prefix=prefix,
            log_dir=context.log_dir,
            recovery_mode=recovery_mode,
        )
        report_progress("Activating application runtime...")
        activate_staged_application_runtime(
            graph, staged, prefix=prefix, mode=recovery_mode or mode
        )
        report_progress("Cleaning retained runtime generations...")
        garbage_collect_application_runtime(prefix, retain_generations=1)
        return
    if mode not in {"install", "upgrade", "reinstall"}:
        raise ExecutionError(
            f"Application runtime activation currently supports install only, not `{mode}`"
        )
    report_progress("Staging application runtime packages...")
    staged = stage_application_runtime_graph(
        graph,
        prefix=prefix,
        mode=mode,
        log_dir=context.log_dir,
    )
    report_progress("Activating application runtime...")
    activate_staged_application_runtime(graph, staged, prefix=prefix, mode=mode)
    report_progress("Cleaning retained runtime generations...")
    garbage_collect_application_runtime(prefix, retain_generations=1)


def _new_execution_context() -> _ExecutionContext:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_dir = Path(os.environ.get("DBPM_LOG_DIR", ".dbpm-logs")).expanduser().resolve()
    return _ExecutionContext(run_id=run_id, log_dir=log_dir)


def _next_log_file(context: _ExecutionContext, plan: dict[str, object], suffix: str | None = None) -> Path:
    context.sequence += 1
    package = plan.get("package")
    app_name = "package"
    if isinstance(package, dict):
        app_name = str(package.get("application_name") or package.get("name") or app_name)
    mode = str(plan.get("mode") or "execute")
    if suffix:
        mode = f"{mode}-{suffix}"
    file_name = f"{context.run_id}-{context.sequence:03d}-{_safe_name(app_name)}-{_safe_name(mode)}.log"
    context.log_dir.mkdir(parents=True, exist_ok=True)
    return context.log_dir / file_name


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)


def _package_progress_identity(plan: dict[str, object]) -> str:
    package = plan.get("package")
    if not isinstance(package, dict):
        return "package"
    name = package.get("name") or package.get("application_name") or "package"
    version = package.get("version")
    return f"{name} {version}" if isinstance(version, str) and version else str(name)


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
