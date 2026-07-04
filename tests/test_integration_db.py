import os
import re

import pytest

from dbpm.connect import ConnectSpec, sqlcl_name
from dbpm.db import check_core, get_core_deployment_metadata


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
        pytest.skip("DBPM_CONNECT or DBPM_CONNECT_NAME is not set")

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
        pytest.skip("DBPM_CONNECT or DBPM_CONNECT_NAME is not set")

    core = check_core(connect=connect, runner=runner, minimum_version="3.5.0")
    assert "CORE_VERSION=" in core.stdout

    metadata = get_core_deployment_metadata(connect=connect, runner=runner)

    assert metadata.deploy_locked == "N"


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
    if connect and connect_name:
        raise RuntimeError(CONNECT_OPTIONS_CONFLICT_MESSAGE)
    if connect_name:
        return sqlcl_name(connect_name)
    if connect:
        return connect
    return None


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)
