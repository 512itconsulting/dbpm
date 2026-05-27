from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import ExecutionError


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


def run_sql_script(
    *,
    sql: str,
    connect: str,
    runner: str,
    label: str = "dbpm",
) -> SqlResult:
    script_path = _write_temp_script(sql, label)
    try:
        result = subprocess.run(
            [runner, "-L", "-S", connect, f"@{script_path}"],
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


def check_core(*, connect: str, runner: str, minimum_version: str | None = None) -> SqlResult:
    sql = _core_check_sql(minimum_version)
    result = run_sql_script(sql=sql, connect=connect, runner=runner, label="dbpm-check-core")
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure("Core check failed", result))
    return result


def delete_application(
    *,
    connect: str,
    runner: str,
    application_name: str,
    fail_on_not_found: str = "N",
) -> SqlResult:
    sql = _delete_application_sql(application_name, fail_on_not_found)
    result = run_sql_script(sql=sql, connect=connect, runner=runner, label="dbpm-delete-application")
    if result.returncode != 0:
        raise ExecutionError(_format_sql_failure(f"Delete application failed for {application_name}", result))
    return result


def stage_deployment_provenance(
    *,
    connect: str,
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
    connect: str,
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
    connect: str,
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
        raise ExecutionError(_format_sql_failure(f"Application state query failed for {application_name}", result))
    return _parse_application_state(result.stdout)


def get_reverse_dependencies(
    *,
    connect: str,
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
        raise ExecutionError(_format_sql_failure(f"Reverse dependency query failed for {application_name}", result))
    return _parse_reverse_dependencies(result.stdout)


def get_deployment_provenance(
    *,
    connect: str,
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
