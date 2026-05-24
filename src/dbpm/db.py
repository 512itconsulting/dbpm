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
