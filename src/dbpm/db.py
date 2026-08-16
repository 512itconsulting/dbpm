from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .connect import ConnectSpec, build_sql_command
from .errors import ExecutionError


DELETE_SYSTEM_CONFIRMATION = "DELETE ALL NON-CORE APPLICATIONS"
_TIMESTAMP_TZ_FORMAT = 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM'


@dataclass(frozen=True)
class SqlResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ApplicationState:
    application_name: str
    version: str
    deploy_status: str
    deploy_commit_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "application_name": self.application_name,
            "version": self.version,
            "deploy_status": self.deploy_status,
            "deploy_commit_hash": self.deploy_commit_hash,
        }


@dataclass(frozen=True)
class DeploymentMetadata:
    deploy_locked: str | None
    deploy_environment: str | None = None


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    application_name: str
    mode: str
    state: str
    attempt_number: int
    lease_token: str | None
    lease_expiry: str | None


@dataclass(frozen=True)
class OperationLease:
    operation_id: str
    attempt_number: int
    lease_token: str
    lease_expiry: str


def run_sql_script(
    *,
    sql: str,
    connect: str | ConnectSpec,
    runner: str,
    label: str = "dbpm",
) -> SqlResult:
    script_path = _write_temp_script(sql, label)
    try:
        result = subprocess.run(
            build_sql_command(runner=runner, connect=connect, script_ref=script_path, silent=True),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ExecutionError(f"SQL runner not found: {runner}") from exc
    finally:
        try:
            script_path.unlink()
        except OSError:
            pass

    return SqlResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def check_core(*, connect: str | ConnectSpec, runner: str, minimum_version: str | None = None) -> SqlResult:
    sql = _core_check_sql(minimum_version)
    result = run_sql_script(sql=sql, connect=connect, runner=runner, label="dbpm-check-core")
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Core check failed", result))
    return result


def delete_application(
    *,
    connect: str | ConnectSpec,
    runner: str,
    application_name: str,
    fail_on_not_found: str = "N",
) -> SqlResult:
    sql = _delete_application_sql(application_name, fail_on_not_found)
    result = run_sql_script(sql=sql, connect=connect, runner=runner, label="dbpm-delete-application")
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Delete application failed for {application_name}", result))
    return result


def delete_system(
    *,
    connect: str | ConnectSpec,
    runner: str,
) -> SqlResult:
    result = run_sql_script(sql=_delete_system_sql(), connect=connect, runner=runner, label="dbpm-delete-system")
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Delete Core system failed", result))
    return result


def stage_deployment_provenance(
    *,
    connect: str | ConnectSpec,
    runner: str,
    payload: dict[str, object],
) -> SqlResult:
    sql = _stage_deployment_provenance_sql(payload)
    application_name = str(payload.get("application_name", ""))
    result = run_sql_script(
        sql=sql,
        connect=connect,
        runner=runner,
        label="dbpm-stage-provenance",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Stage provenance failed for {application_name}", result))
    return result


def record_deployment_provenance(
    *,
    connect: str | ConnectSpec,
    runner: str,
    payload: dict[str, object],
) -> SqlResult:
    sql = _record_deployment_provenance_sql(payload)
    application_name = str(payload.get("application_name", ""))
    result = run_sql_script(
        sql=sql,
        connect=connect,
        runner=runner,
        label="dbpm-record-provenance",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Record provenance failed for {application_name}", result))
    return result


def get_application_state(
    *,
    connect: str | ConnectSpec,
    runner: str,
    application_name: str,
) -> ApplicationState | None:
    result = run_sql_script(
        sql=_application_state_sql(application_name),
        connect=connect,
        runner=runner,
        label="dbpm-application-state",
    )
    if result.returncode != 0:
        if _is_missing_core_registry_table(result):
            return None
        raise ExecutionError(_format_sql_failure(f"Application state query failed for {application_name}", result))
    return _parse_application_state(result.stdout)


def get_reverse_dependencies(
    *,
    connect: str | ConnectSpec,
    runner: str,
    application_name: str,
) -> list[str]:
    result = run_sql_script(
        sql=_reverse_dependencies_sql(application_name),
        connect=connect,
        runner=runner,
        label="dbpm-reverse-dependencies",
    )
    if result.returncode != 0:
        if _is_missing_core_registry_table(result):
            return []
        raise ExecutionError(_format_sql_failure(f"Reverse dependency query failed for {application_name}", result))
    return _parse_reverse_dependencies(result.stdout)


def get_deployment_provenance(
    *,
    connect: str | ConnectSpec,
    runner: str,
    application_name: str,
    version: str,
) -> dict[str, object] | None:
    result = run_sql_script(
        sql=_deployment_provenance_sql(application_name, version),
        connect=connect,
        runner=runner,
        label="dbpm-deployment-provenance",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Deployment provenance query failed for {application_name}", result))
    return _parse_deployment_provenance(result.stdout)


def get_core_deployment_metadata(
    *,
    connect: str | ConnectSpec,
    runner: str,
) -> DeploymentMetadata:
    result = run_sql_script(
        sql=_core_deployment_metadata_sql(),
        connect=connect,
        runner=runner,
        label="dbpm-core-deployment-metadata",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Core deployment metadata query failed", result))
    return _parse_core_deployment_metadata(result.stdout)


def begin_operation(
    *, connect: str | ConnectSpec, runner: str, operation_id: str,
    application_name: str, mode: str,
) -> OperationRecord:
    result = run_sql_script(
        sql=_begin_operation_sql(operation_id, application_name, mode),
        connect=connect, runner=runner, label="dbpm-begin-operation",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Begin operation failed", result))
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("DBPM_OPERATION_BUSY|"):
            _, previous_id, expiry = line.split("|", 2)
            raise ExecutionError(
                f"A composite operation ({previous_id}) is already in progress for "
                f"{application_name} until {expiry}; use resume or runtime reconcile "
                "instead of starting a new operation"
            )
    record = _parse_operation_record(result.stdout)
    if record is None:
        raise ExecutionError("Core did not return the new operation record")
    return record


def get_current_operation(
    *, connect: str | ConnectSpec, runner: str, application_name: str,
) -> OperationRecord | None:
    result = run_sql_script(
        sql=_current_operation_sql(application_name), connect=connect,
        runner=runner, label="dbpm-current-operation",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Operation lookup failed", result))
    return _parse_operation_record(result.stdout)


def acquire_operation_lease(
    *, connect: str | ConnectSpec, runner: str, operation_id: str,
    lease_token: str, lease_seconds: int = 3600,
) -> OperationLease:
    result = run_sql_script(
        sql=_acquire_operation_lease_sql(operation_id, lease_token, lease_seconds),
        connect=connect, runner=runner, label="dbpm-acquire-operation-lease",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Operation lease acquisition failed", result))
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("DBPM_OPERATION_BUSY|"):
            _, attempt, expiry = line.split("|", 2)
            raise ExecutionError(
                f"Operation lease is held by attempt {attempt} until {expiry}"
            )
        if line.startswith("DBPM_OPERATION_LEASE|"):
            _, attempt, expiry = line.split("|", 2)
            return OperationLease(operation_id, int(attempt), lease_token, expiry)
    raise ExecutionError("Core did not return an operation lease")


def record_operation_step(
    *, connect: str | ConnectSpec, runner: str, lease: OperationLease,
    step: str, state: str, content_ref: str = "",
) -> None:
    result = run_sql_script(
        sql=_record_operation_step_sql(lease, step, state, content_ref),
        connect=connect, runner=runner, label="dbpm-record-operation-step",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Recording operation step {step} failed", result))


def renew_operation_lease(
    *, connect: str | ConnectSpec, runner: str, lease: OperationLease,
    lease_seconds: int = 3600,
) -> OperationLease:
    result = run_sql_script(
        sql=_renew_operation_lease_sql(lease, lease_seconds), connect=connect,
        runner=runner, label="dbpm-renew-operation-lease",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Operation lease renewal failed", result))
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if line.startswith("DBPM_OPERATION_LEASE|"):
            _, attempt, expiry = line.split("|", 2)
            return OperationLease(lease.operation_id, int(attempt), lease.lease_token, expiry)
    raise ExecutionError("Core did not return the renewed operation lease")


def release_operation_lease(
    *, connect: str | ConnectSpec, runner: str, lease: OperationLease,
) -> None:
    result = run_sql_script(
        sql=_release_operation_lease_sql(lease), connect=connect,
        runner=runner, label="dbpm-release-operation-lease",
    )
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Operation lease release failed", result))


def _write_temp_script(sql: str, label: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sql",
        prefix=f"{label}-",
        delete=False,
    )
    with handle:
        handle.write(sql)
    return Path(handle.name)


def _core_check_sql(minimum_version: str | None) -> str:
    version_block = ""
    if minimum_version:
        major, minor, patch = _parse_semver(minimum_version)
        version_block = f"""
BEGIN
   pkg_application.check_min_app_version_p(
      ip_application_name  => 'CORE',
      ip_min_major_version => {major},
      ip_min_minor_version => {minor},
      ip_min_patch_version => {patch}
   );
END;
/
"""

    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

DECLARE
   l_version VARCHAR2(100);
BEGIN
   l_version := pkg_application.get_current_version_f('CORE');
   DBMS_OUTPUT.PUT_LINE('CORE_VERSION=' || l_version);
END;
/
{version_block}
EXIT SUCCESS
"""


def _delete_application_sql(application_name: str, fail_on_not_found: str) -> str:
    if fail_on_not_found not in {"Y", "N"}:
        raise ExecutionError("fail_on_not_found must be Y or N")
    app_name = _sql_literal(application_name.upper())
    fail_flag = _sql_literal(fail_on_not_found)
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

BEGIN
   pkg_application.delete_application_p(
      ip_application_name    => {app_name},
      ip_fail_on_not_found  => {fail_flag}
   );
   DBMS_OUTPUT.PUT_LINE('DELETED_APPLICATION=' || {app_name});
END;
/
EXIT SUCCESS
"""


def _delete_system_sql() -> str:
    confirm = _sql_literal(DELETE_SYSTEM_CONFIRMATION)
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

BEGIN
   pkg_application.delete_system_p(
      ip_confirm => {confirm}
   );
   DBMS_OUTPUT.PUT_LINE('DELETED_SYSTEM=Y');
END;
/
EXIT SUCCESS
"""


def _stage_deployment_provenance_sql(payload: dict[str, object]) -> str:
    return _deployment_provenance_write_sql(
        payload,
        procedure_name="stage_deployment_provenance_p",
        output_name="STAGED_DEPLOYMENT_PROVENANCE",
    )


def _record_deployment_provenance_sql(payload: dict[str, object]) -> str:
    return _deployment_provenance_write_sql(
        payload,
        procedure_name="record_deployment_provenance_p",
        output_name="RECORDED_DEPLOYMENT_PROVENANCE",
    )


def _deployment_provenance_write_sql(
    payload: dict[str, object],
    *,
    procedure_name: str,
    output_name: str,
) -> str:
    application_name = _required_payload_str(payload, "application_name").upper()
    major, minor, patch = _parse_semver(_required_payload_str(payload, "version"))
    deployment_type = str(payload.get("deployment_type", "I"))
    deploy_commit_hash = _required_payload_str(payload, "deploy_commit_hash")
    build_metadata_json = payload.get("build_metadata_json")
    if build_metadata_json is not None and not isinstance(build_metadata_json, str):
        build_metadata_json = json.dumps(build_metadata_json, sort_keys=True, separators=(",", ":"))

    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

BEGIN
   pkg_application.{procedure_name}(
      ip_application_name         => {_sql_literal(application_name)},
      ip_major_version            => {major},
      ip_minor_version            => {minor},
      ip_patch_version            => {patch},
      ip_deployment_type          => {_sql_literal(deployment_type)},
      ip_deploy_commit_hash       => {_sql_literal(deploy_commit_hash)},
      ip_artifact_uri             => {_nullable_sql_literal(payload.get("artifact_uri"))},
      ip_artifact_checksum        => {_nullable_sql_literal(payload.get("artifact_checksum"))},
      ip_artifact_checksum_alg    => {_nullable_sql_literal(payload.get("artifact_checksum_alg", "SHA-256"))},
      ip_artifact_file_name       => {_nullable_sql_literal(payload.get("artifact_file_name"))},
      ip_artifact_repository_type => {_nullable_sql_literal(payload.get("artifact_repository_type"))},
      ip_artifact_group_id        => {_nullable_sql_literal(payload.get("artifact_group_id"))},
      ip_artifact_id              => {_nullable_sql_literal(payload.get("artifact_id"))},
      ip_artifact_version         => {_nullable_sql_literal(payload.get("artifact_version"))},
      ip_artifact_classifier      => {_nullable_sql_literal(payload.get("artifact_classifier"))},
      ip_artifact_extension       => {_nullable_sql_literal(payload.get("artifact_extension"))},
      ip_package_coordinate       => {_nullable_sql_literal(payload.get("package_coordinate"))},
      ip_source_repository_url    => {_nullable_sql_literal(payload.get("source_repository_url"))},
      ip_source_commit_hash       => {_nullable_sql_literal(payload.get("source_commit_hash"))},
      ip_source_path              => {_nullable_sql_literal(payload.get("source_path"))},
      ip_build_id                 => {_nullable_sql_literal(payload.get("build_id"))},
      ip_build_url                => {_nullable_sql_literal(payload.get("build_url"))},
      ip_build_time               => {_nullable_sql_literal(payload.get("build_time"))},
      ip_build_metadata_json      => {_nullable_sql_literal(build_metadata_json)}
   );
   DBMS_OUTPUT.PUT_LINE('{output_name}=' || {_sql_literal(application_name)});
END;
/
EXIT SUCCESS
"""


def _application_state_sql(application_name: str) -> str:
    app_name = _sql_literal(application_name.upper())
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

SELECT 'DBPM_APPLICATION_STATE|'
       || application_name || '|'
       || major_version || '.' || minor_version || '.' || patch_version || '|'
       || deploy_status || '|'
       || deploy_commit_hash
  FROM application
 WHERE application_name = {app_name};
EXIT SUCCESS
"""


def _reverse_dependencies_sql(application_name: str) -> str:
    app_name = _sql_literal(application_name.upper())
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

SELECT 'DBPM_REVERSE_DEPENDENCY|' || application_name
  FROM app_dependency
 WHERE depends_on = {app_name}
 ORDER BY application_name;
EXIT SUCCESS
"""


def _deployment_provenance_sql(application_name: str, version: str) -> str:
    app_name = _sql_literal(application_name.upper())
    major, minor, patch = _parse_semver(version)
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

DECLARE
   l_json CLOB;
BEGIN
   l_json := pkg_application.get_deployment_provenance_json_f(
      ip_application_name => {app_name},
      ip_major_version    => {major},
      ip_minor_version    => {minor},
      ip_patch_version    => {patch}
   );
   IF l_json IS NOT NULL THEN
      DBMS_OUTPUT.PUT_LINE('DBPM_DEPLOYMENT_PROVENANCE|' || DBMS_LOB.SUBSTR(l_json, 32767, 1));
   END IF;
END;
/
EXIT SUCCESS
"""


def _core_deployment_metadata_sql() -> str:
    return """
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE

SELECT 'DBPM_CORE_METADATA|' || key || '|' || pkg_app_dict.get_val_f('CORE', key)
  FROM (
        SELECT 'DEPLOY_LOCKED' AS key FROM dual
        UNION ALL
        SELECT 'DEPLOY_ENVIRONMENT' AS key FROM dual
       )
 ORDER BY key;
EXIT SUCCESS
"""


def _operation_key(operation_id: str, field: str) -> str:
    normalized = operation_id.replace("-", "").upper()
    if len(normalized) != 32 or any(char not in "0123456789ABCDEF" for char in normalized):
        raise ExecutionError("operation_id must be a UUID")
    return f"DBPM_OP_{normalized}_{field}"


def _current_operation_key(application_name: str) -> str:
    return f"DBPM_CURRENT_OP_{application_name.upper()}"


def _operation_output_sql(operation_id_expr: str) -> str:
    return f"""
   DBMS_OUTPUT.PUT_LINE(
      'DBPM_OPERATION|' || {operation_id_expr} || '|'
      || pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_APP') || '|'
      || pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_MODE') || '|'
      || pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_STATE') || '|'
      || pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_ATTEMPT') || '|'
      || NVL(pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_TOKEN'), '') || '|'
      || NVL(pkg_app_dict.get_val_f('CORE', 'DBPM_OP_' || REPLACE(UPPER({operation_id_expr}), '-', '') || '_EXPIRY'), '')
   );
"""


def _begin_operation_sql(operation_id: str, application_name: str, mode: str) -> str:
    # Known gap: this locks the CURRENT_OP pointer and checks the previous
    # operation's lease, but begin_operation and acquire_operation_lease are
    # still separate round-trips. Two concurrent first-ever begin_operation
    # calls for the same not-yet-installed application can both see the
    # other's operation as unleased ("not busy") and delete it out from under
    # the caller. The loser's subsequent acquire_operation_lease then fails
    # loudly (NO_DATA_FOUND -> non-zero exit -> ExecutionError) rather than
    # corrupting state, so this is a spurious-failure risk, not a
    # correctness one. Closing it fully needs begin+acquire merged into one
    # atomic statement.
    fields = {
        "APP": application_name.upper(), "MODE": mode.upper(), "STATE": "RESOLVED",
        "ATTEMPT": "0", "TOKEN": "", "EXPIRY": "",
    }
    inserts = "\n".join(
        f"   INSERT INTO app_dictionary(application_name, key, value) VALUES "
        f"('CORE', {_sql_literal(_operation_key(operation_id, field))}, {_sql_literal(value or '-')} );"
        for field, value in fields.items()
    )
    pointer = _current_operation_key(application_name)
    output = _operation_output_sql(_sql_literal(operation_id))
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
WHENEVER OSERROR EXIT FAILURE ROLLBACK
DECLARE
   l_previous_id app_dictionary.value%TYPE;
   l_previous_prefix VARCHAR2(200);
   l_token app_dictionary.value%TYPE;
   l_expiry app_dictionary.value%TYPE;
BEGIN
   MERGE INTO app_dictionary d
   USING (SELECT 'CORE' application_name, {_sql_literal(pointer)} key FROM dual) s
      ON (d.application_name = s.application_name AND d.key = s.key)
   WHEN NOT MATCHED THEN INSERT(application_name, key, value)
      VALUES('CORE', {_sql_literal(pointer)}, '-');
   SELECT value INTO l_previous_id FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(pointer)} FOR UPDATE;
   IF l_previous_id <> '-' THEN
      l_previous_prefix := 'DBPM_OP_' || REPLACE(UPPER(l_previous_id), '-', '') || '_';
      BEGIN
         SELECT value INTO l_token FROM app_dictionary
          WHERE application_name = 'CORE' AND key = l_previous_prefix || 'TOKEN';
         SELECT value INTO l_expiry FROM app_dictionary
          WHERE application_name = 'CORE' AND key = l_previous_prefix || 'EXPIRY';
      EXCEPTION WHEN NO_DATA_FOUND THEN
         l_token := '-';
         l_expiry := '-';
      END;
      IF l_token <> '-' AND l_expiry <> '-'
         AND TO_TIMESTAMP_TZ(l_expiry, {_sql_literal(_TIMESTAMP_TZ_FORMAT)}) > SYSTIMESTAMP THEN
         DBMS_OUTPUT.PUT_LINE('DBPM_OPERATION_BUSY|' || l_previous_id || '|' || l_expiry);
         ROLLBACK;
         RETURN;
      END IF;
      DELETE FROM app_dictionary
       WHERE application_name = 'CORE' AND key LIKE l_previous_prefix || '%';
   END IF;
{inserts}
   UPDATE app_dictionary SET value = {_sql_literal(operation_id)}
    WHERE application_name = 'CORE' AND key = {_sql_literal(pointer)};
   COMMIT;
{output}
END;
/
EXIT SUCCESS
"""


def _current_operation_sql(application_name: str) -> str:
    pointer = _current_operation_key(application_name)
    output = _operation_output_sql("l_operation_id")
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET PAGESIZE 0
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE
WHENEVER OSERROR EXIT FAILURE
DECLARE
   l_operation_id app_dictionary.value%TYPE;
BEGIN
   SELECT MAX(value) INTO l_operation_id FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(pointer)};
   IF l_operation_id IS NOT NULL THEN
{output}
   END IF;
END;
/
EXIT SUCCESS
"""


def _acquire_operation_lease_sql(operation_id: str, lease_token: str, lease_seconds: int) -> str:
    if lease_seconds < 30 or lease_seconds > 3600:
        raise ExecutionError("operation lease duration must be between 30 and 3600 seconds")
    attempt_key = _operation_key(operation_id, "ATTEMPT")
    token_key = _operation_key(operation_id, "TOKEN")
    expiry_key = _operation_key(operation_id, "EXPIRY")
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
WHENEVER OSERROR EXIT FAILURE ROLLBACK
DECLARE
   l_attempt NUMBER;
   l_token VARCHAR2(100);
   l_expiry VARCHAR2(100);
   l_new_expiry VARCHAR2(100);
BEGIN
   SELECT TO_NUMBER(value) INTO l_attempt FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(attempt_key)} FOR UPDATE;
   SELECT value INTO l_token FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(token_key)};
   SELECT value INTO l_expiry FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(expiry_key)};
   IF l_token <> '-' AND l_expiry <> '-'
      AND TO_TIMESTAMP_TZ(l_expiry, {_sql_literal(_TIMESTAMP_TZ_FORMAT)}) > SYSTIMESTAMP THEN
      DBMS_OUTPUT.PUT_LINE('DBPM_OPERATION_BUSY|' || l_attempt || '|' || l_expiry);
      ROLLBACK;
      RETURN;
   END IF;
   l_attempt := l_attempt + 1;
   l_new_expiry := TO_CHAR(SYSTIMESTAMP + NUMTODSINTERVAL({lease_seconds}, 'SECOND'), {_sql_literal(_TIMESTAMP_TZ_FORMAT)});
   UPDATE app_dictionary SET value = TO_CHAR(l_attempt)
    WHERE application_name = 'CORE' AND key = {_sql_literal(attempt_key)};
   UPDATE app_dictionary SET value = {_sql_literal(lease_token)}
    WHERE application_name = 'CORE' AND key = {_sql_literal(token_key)};
   UPDATE app_dictionary SET value = l_new_expiry
    WHERE application_name = 'CORE' AND key = {_sql_literal(expiry_key)};
   COMMIT;
   DBMS_OUTPUT.PUT_LINE('DBPM_OPERATION_LEASE|' || l_attempt || '|' || l_new_expiry);
END;
/
EXIT SUCCESS
"""


def _record_operation_step_sql(
    lease: OperationLease, step: str, state: str, content_ref: str,
) -> str:
    allowed_states = {"RESOLVED", "RUNTIME_STAGED", "DATABASE_COMPLETE", "RUNTIME_UNREACHABLE", "RUNTIME_ACTIVE", "VALIDATED", "FAILED"}
    if state not in allowed_states:
        raise ExecutionError(f"Unknown operation state: {state}")
    normalized_step = "".join(char if char.isalnum() else "_" for char in step.upper())
    evidence_key = _operation_key(lease.operation_id, f"EV_{normalized_step}")
    state_key = _operation_key(lease.operation_id, "STATE")
    token_key = _operation_key(lease.operation_id, "TOKEN")
    expiry_key = _operation_key(lease.operation_id, "EXPIRY")
    evidence = f"{lease.attempt_number}:{content_ref}"[:100]
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
WHENEVER OSERROR EXIT FAILURE ROLLBACK
DECLARE
   l_token app_dictionary.value%TYPE;
   l_expiry app_dictionary.value%TYPE;
BEGIN
   SELECT value INTO l_token FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(token_key)} FOR UPDATE;
   SELECT value INTO l_expiry FROM app_dictionary
    WHERE application_name = 'CORE' AND key = {_sql_literal(expiry_key)};
   IF l_token <> {_sql_literal(lease.lease_token)} OR l_expiry = '-'
      OR TO_TIMESTAMP_TZ(l_expiry, {_sql_literal(_TIMESTAMP_TZ_FORMAT)}) <= SYSTIMESTAMP THEN
      RAISE_APPLICATION_ERROR(-20001, 'DBPM operation lease was fenced by a newer attempt');
   END IF;
   UPDATE app_dictionary SET value = {_sql_literal(state)}
    WHERE application_name = 'CORE' AND key = {_sql_literal(state_key)};
   MERGE INTO app_dictionary d
   USING (SELECT 'CORE' application_name, {_sql_literal(evidence_key)} key FROM dual) s
      ON (d.application_name = s.application_name AND d.key = s.key)
   WHEN MATCHED THEN UPDATE SET d.value = {_sql_literal(evidence)}, d.note = TO_CHAR(SYSTIMESTAMP, {_sql_literal(_TIMESTAMP_TZ_FORMAT)})
   WHEN NOT MATCHED THEN INSERT(application_name, key, value, note)
      VALUES('CORE', {_sql_literal(evidence_key)}, {_sql_literal(evidence)}, TO_CHAR(SYSTIMESTAMP, {_sql_literal(_TIMESTAMP_TZ_FORMAT)}));
   COMMIT;
END;
/
EXIT SUCCESS
"""


def _renew_operation_lease_sql(lease: OperationLease, lease_seconds: int) -> str:
    if lease_seconds < 30 or lease_seconds > 3600:
        raise ExecutionError("operation lease duration must be between 30 and 3600 seconds")
    token_key = _operation_key(lease.operation_id, "TOKEN")
    expiry_key = _operation_key(lease.operation_id, "EXPIRY")
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
WHENEVER OSERROR EXIT FAILURE ROLLBACK
DECLARE
   l_new_expiry VARCHAR2(100);
BEGIN
   l_new_expiry := TO_CHAR(SYSTIMESTAMP + NUMTODSINTERVAL({lease_seconds}, 'SECOND'), {_sql_literal(_TIMESTAMP_TZ_FORMAT)});
   UPDATE app_dictionary SET value = l_new_expiry
    WHERE application_name = 'CORE' AND key = {_sql_literal(expiry_key)}
      AND value <> '-'
      AND TO_TIMESTAMP_TZ(value, {_sql_literal(_TIMESTAMP_TZ_FORMAT)}) > SYSTIMESTAMP
      AND EXISTS (
          SELECT 1 FROM app_dictionary
           WHERE application_name = 'CORE' AND key = {_sql_literal(token_key)}
             AND value = {_sql_literal(lease.lease_token)}
      );
   IF SQL%ROWCOUNT = 0 THEN
      RAISE_APPLICATION_ERROR(-20001, 'DBPM operation lease was fenced by a newer attempt');
   END IF;
   COMMIT;
   DBMS_OUTPUT.PUT_LINE('DBPM_OPERATION_LEASE|{lease.attempt_number}|' || l_new_expiry);
END;
/
EXIT SUCCESS
"""


def _release_operation_lease_sql(lease: OperationLease) -> str:
    token_key = _operation_key(lease.operation_id, "TOKEN")
    expiry_key = _operation_key(lease.operation_id, "EXPIRY")
    return f"""
SET HEADING OFF
SET FEEDBACK OFF
SET VERIFY OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
BEGIN
   UPDATE app_dictionary SET value = '-'
    WHERE application_name = 'CORE' AND key = {_sql_literal(token_key)}
      AND value = {_sql_literal(lease.lease_token)};
   IF SQL%ROWCOUNT = 0 THEN
      RAISE_APPLICATION_ERROR(-20001, 'DBPM operation lease was fenced by a newer attempt');
   END IF;
   UPDATE app_dictionary SET value = '-'
    WHERE application_name = 'CORE' AND key = {_sql_literal(expiry_key)};
   COMMIT;
END;
/
EXIT SUCCESS
"""


def _parse_application_state(output: str) -> ApplicationState | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("DBPM_APPLICATION_STATE|"):
            continue
        parts = line.split("|")
        if len(parts) != 5:
            raise ExecutionError(f"Unexpected application state output: {line}")
        return ApplicationState(
            application_name=parts[1],
            version=parts[2],
            deploy_status=parts[3],
            deploy_commit_hash=parts[4],
        )
    return None


def _parse_core_deployment_metadata(output: str) -> DeploymentMetadata:
    values: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("DBPM_CORE_METADATA|"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise ExecutionError(f"Unexpected Core deployment metadata output: {line}")
        values[parts[1]] = parts[2]
    return DeploymentMetadata(
        deploy_locked=values.get("DEPLOY_LOCKED"),
        deploy_environment=values.get("DEPLOY_ENVIRONMENT"),
    )


def _parse_operation_record(output: str) -> OperationRecord | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("DBPM_OPERATION|"):
            continue
        parts = line.split("|", 7)
        if len(parts) != 8:
            raise ExecutionError(f"Unexpected operation output: {line}")
        return OperationRecord(
            operation_id=parts[1], application_name=parts[2], mode=parts[3],
            state=parts[4], attempt_number=int(parts[5]),
            lease_token=None if parts[6] in {"", "-"} else parts[6],
            lease_expiry=None if parts[7] in {"", "-"} else parts[7],
        )
    return None


def _parse_reverse_dependencies(output: str) -> list[str]:
    dependencies: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("DBPM_REVERSE_DEPENDENCY|"):
            dependencies.append(line.split("|", 1)[1])
    return dependencies


def _parse_deployment_provenance(output: str) -> dict[str, object] | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("DBPM_DEPLOYMENT_PROVENANCE|"):
            continue
        raw_json = line.split("|", 1)[1]
        try:
            value = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ExecutionError(f"Unexpected deployment provenance output: {line}") from exc
        if not isinstance(value, dict):
            raise ExecutionError(f"Unexpected deployment provenance output: {line}")
        return value
    return None


def _parse_semver(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3:
        raise ExecutionError(f"Core minimum version must be major.minor.patch: {value}")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise ExecutionError(f"Core minimum version must be numeric: {value}") from exc


def _format_sql_failure(message: str, result: SqlResult) -> str:
    details = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    return f"{message} with exit code {result.returncode}" + (f":\n{details}" if details else "")


def _is_missing_core_registry_table(result: SqlResult) -> bool:
    text = f"{result.stdout}\n{result.stderr}".upper()
    return "ORA-00942" in text and (
        '"APPLICATION"' in text
        or " FROM APPLICATION" in text
        or '"APP_DEPENDENCY"' in text
        or " FROM APP_DEPENDENCY" in text
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _nullable_sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    if text == "":
        return "NULL"
    return _sql_literal(text)


def _required_payload_str(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value).strip() == "":
        raise ExecutionError(f"stage_deployment_provenance requires {key}")
    return str(value)
