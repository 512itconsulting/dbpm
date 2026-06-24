import pytest

from dbpm.connect import build_sql_command, connect_string, sqlcl_name, validate_connect_spec
from dbpm.errors import DbpmError


def test_build_sql_command_preserves_connect_string_vector():
    assert build_sql_command(
        runner="sql",
        connect="user/pass@db",
        script_ref="deploy.sql",
        arguments=["abc"],
    ) == ["sql", "-L", "user/pass@db", "@deploy.sql", "abc"]


def test_build_sql_command_can_add_silent_for_connect_strings():
    assert build_sql_command(
        runner="sql",
        connect=connect_string("user/pass@db"),
        script_ref="/tmp/check.sql",
        silent=True,
    ) == ["sql", "-L", "-S", "user/pass@db", "@/tmp/check.sql"]


def test_build_sql_command_uses_single_argument_for_sqlcl_name():
    assert build_sql_command(
        runner="sql",
        connect=sqlcl_name("Development Database (APP_USER)"),
        script_ref="deploy.sql",
        arguments=["abc"],
    ) == [
        "sql",
        "-S",
        "-L",
        "-name",
        "Development Database (APP_USER)",
        "@deploy.sql",
        "abc",
    ]


def test_sqlcl_name_rejects_default_sqlplus_runner():
    with pytest.raises(DbpmError, match="SQLcl named connections require a SQLcl runner"):
        validate_connect_spec(connect=sqlcl_name("Development Database (APP_USER)"), runner="sqlplus")
