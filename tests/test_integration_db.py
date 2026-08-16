import os
import re
import uuid

import pytest

from dbpm.connect import ConnectSpec, sqlcl_name
from dbpm.errors import ExecutionError
from dbpm.db import (
    acquire_operation_lease,
    begin_operation,
    check_core,
    get_core_deployment_metadata,
    get_current_operation,
    record_operation_step,
    release_operation_lease,
    run_sql_script,
)


CONNECT_OPTIONS_CONFLICT_MESSAGE = (
    "DBPM_CONNECT and DBPM_CONNECT_NAME are mutually exclusive. "
    "Use DBPM_CONNECT for raw Oracle connect strings such as user/pass@service. "
    "Use DBPM_CONNECT_NAME for SQLcl saved connections, and unset DBPM_CONNECT "
    "when using DBPM_CONNECT_NAME."
)


@pytest.mark.skipif(
    os.environ.get("DBPM_RUN_DB_TESTS") != "1",
    reason="set DBPM_RUN_DB_TESTS=1 to run database integration tests",
)
def test_check_core_against_development_database():
    connect = _integration_connect_spec()
    runner = os.environ.get("DBPM_SQL_RUNNER", "sql")
    if not connect:
        pytest.skip("No dbpm database connection environment is set")

    result = check_core(connect=connect, runner=runner, minimum_version="3.0.0")

    match = re.search(r"CORE_VERSION=(\d+\.\d+\.\d+)", result.stdout)
    assert match is not None
    assert _version_tuple(match.group(1)) >= (3, 0, 0)


@pytest.mark.skipif(
    os.environ.get("DBPM_RUN_DB_TESTS") != "1",
    reason="set DBPM_RUN_DB_TESTS=1 to run database integration tests",
)
def test_core_deployment_metadata_against_development_database():
    connect = _integration_connect_spec()
    runner = os.environ.get("DBPM_SQL_RUNNER", "sql")
    if not connect:
        pytest.skip("No dbpm database connection environment is set")

    core = check_core(connect=connect, runner=runner, minimum_version="3.5.0")
    assert "CORE_VERSION=" in core.stdout

    metadata = get_core_deployment_metadata(connect=connect, runner=runner)

    assert metadata.deploy_locked == "N"


@pytest.mark.skipif(
    os.environ.get("DBPM_RUN_DB_TESTS") != "1",
    reason="set DBPM_RUN_DB_TESTS=1 to run database integration tests",
)
def test_composite_operation_lease_and_evidence_against_development_database():
    connect = _integration_connect_spec()
    runner = os.environ.get("DBPM_SQL_RUNNER", "sql")
    if not connect:
        pytest.skip("No dbpm database connection environment is set")
    operation_id = str(uuid.uuid4())
    application_name = "DBPM_PHASE2_TEST"
    normalized = operation_id.replace("-", "").upper()
    try:
        record = begin_operation(
            connect=connect, runner=runner, operation_id=operation_id,
            application_name=application_name, mode="INSTALL",
        )
        lease = acquire_operation_lease(
            connect=connect, runner=runner, operation_id=operation_id,
            lease_token=uuid.uuid4().hex,
        )
        with pytest.raises(ExecutionError, match="held by attempt 1 until"):
            acquire_operation_lease(
                connect=connect, runner=runner, operation_id=operation_id,
                lease_token=uuid.uuid4().hex,
            )
        record_operation_step(
            connect=connect, runner=runner, lease=lease,
            step="database", state="DATABASE_COMPLETE", content_ref=application_name,
        )
        current = get_current_operation(
            connect=connect, runner=runner, application_name=application_name,
        )
        assert record.operation_id == operation_id
        assert lease.attempt_number == 1
        assert current is not None and current.state == "DATABASE_COMPLETE"
        release_operation_lease(connect=connect, runner=runner, lease=lease)
    finally:
        cleanup = run_sql_script(
            connect=connect, runner=runner, label="dbpm-operation-test-cleanup",
            sql=f"""
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
DELETE FROM app_dictionary
 WHERE application_name = 'CORE'
   AND (key LIKE 'DBPM_OP_{normalized}_%'
        OR key = 'DBPM_CURRENT_OP_{application_name}');
COMMIT;
EXIT SUCCESS
""",
        )
        assert cleanup.returncode == 0


def test_integration_connect_spec_uses_raw_connect_string(monkeypatch):
    monkeypatch.setenv("DBPM_CONNECT", "user/password@db")
    monkeypatch.delenv("DBPM_CONNECT_NAME", raising=False)

    assert _integration_connect_spec() == "user/password@db"


def test_integration_connect_spec_uses_sqlcl_saved_connection(monkeypatch):
    monkeypatch.delenv("DBPM_CONNECT", raising=False)
    monkeypatch.setenv("DBPM_CONNECT_NAME", "Development Database (APP_USER)")

    connect = _integration_connect_spec()

    assert isinstance(connect, ConnectSpec)
    assert connect.kind == "sqlcl-name"
    assert connect.value == "Development Database (APP_USER)"


def test_integration_connect_spec_rejects_ambiguous_connection_env(monkeypatch):
    monkeypatch.setenv("DBPM_CONNECT", "dev_database")
    monkeypatch.setenv("DBPM_CONNECT_NAME", "Development Database (APP_USER)")

    with pytest.raises(RuntimeError, match="raw Oracle connect strings"):
        _integration_connect_spec()


def _integration_connect_spec() -> str | ConnectSpec | None:
    connect = os.environ.get("DBPM_CONNECT")
    connect_name = os.environ.get("DBPM_CONNECT_NAME")
    database_values = [
        os.environ.get("DBPM_DB_USER"),
        os.environ.get("DBPM_DB_PASSWORD"),
        os.environ.get("DBPM_DB_DSN"),
    ]
    if any(database_values) and not all(database_values):
        raise RuntimeError("DBPM_DB_USER, DBPM_DB_PASSWORD, and DBPM_DB_DSN must be set together")
    if sum(bool(value) for value in (connect, connect_name, all(database_values))) > 1:
        raise RuntimeError(CONNECT_OPTIONS_CONFLICT_MESSAGE)
    if connect_name:
        return sqlcl_name(connect_name)
    if connect:
        return connect
    if all(database_values):
        user, password, dsn = database_values
        return f"{user}/{password}@{dsn}"
    return None


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)
