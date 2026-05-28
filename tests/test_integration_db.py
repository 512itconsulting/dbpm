import os
import re

import pytest

from dbpm.db import check_core


pytestmark = pytest.mark.skipif(
    os.environ.get("DBPM_RUN_DB_TESTS") != "1",
    reason="set DBPM_RUN_DB_TESTS=1 to run database integration tests",
)


def test_check_core_against_development_database():
    connect = os.environ.get("DBPM_CONNECT")
    runner = os.environ.get("DBPM_SQL_RUNNER", "sql")
    if not connect:
        pytest.skip("DBPM_CONNECT is not set")

    result = check_core(connect=connect, runner=runner, minimum_version="3.0.0")

    match = re.search(r"CORE_VERSION=(\d+\.\d+\.\d+)", result.stdout)
    assert match is not None
    assert _version_tuple(match.group(1)) >= (3, 0, 0)


def _version_tuple(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)
