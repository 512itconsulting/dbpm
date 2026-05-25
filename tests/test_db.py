from dbpm.db import (
    ApplicationState,
    _application_state_sql,
    _core_check_sql,
    _delete_application_sql,
    _parse_application_state,
    _parse_semver,
)


def test_core_check_sql_includes_version_check():
    sql = _core_check_sql("3.0.0")

    assert "pkg_application.get_current_version_f('CORE')" in sql
    assert "pkg_application.check_min_app_version_p" in sql
    assert "ip_min_major_version => 3" in sql
    assert "ip_min_minor_version => 0" in sql
    assert "ip_min_patch_version => 0" in sql
    assert "WHENEVER SQLERROR EXIT FAILURE" in sql


def test_parse_semver():
    assert _parse_semver("1.2.3") == (1, 2, 3)


def test_delete_application_sql_uses_core_api():
    sql = _delete_application_sql("utl_interval", "N")

    assert "pkg_application.delete_application_p" in sql
    assert "ip_application_name    => 'UTL_INTERVAL'" in sql
    assert "ip_fail_on_not_found  => 'N'" in sql
    assert "DELETED_APPLICATION=" in sql


def test_application_state_sql_queries_application_table():
    sql = _application_state_sql("utl_interval")

    assert "DBPM_APPLICATION_STATE|" in sql
    assert "FROM application" in sql
    assert "WHERE application_name = 'UTL_INTERVAL'" in sql


def test_parse_application_state():
    state = _parse_application_state(
        "\nDBPM_APPLICATION_STATE|UTL_INTERVAL|1.0.0|C|abcdef\n"
    )

    assert state == ApplicationState(
        application_name="UTL_INTERVAL",
        version="1.0.0",
        deploy_status="C",
        deploy_commit_hash="abcdef",
    )


def test_parse_application_state_not_found():
    assert _parse_application_state("") is None
