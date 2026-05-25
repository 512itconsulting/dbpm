from __future__ import annotations

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
