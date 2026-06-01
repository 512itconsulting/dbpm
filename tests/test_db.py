from dbpm.db import (
    ApplicationState,
    SqlResult,
    _application_state_sql,
    _core_check_sql,
    _delete_application_sql,
    _delete_system_sql,
    _deployment_provenance_sql,
    _parse_application_state,
    _parse_deployment_provenance,
    _parse_reverse_dependencies,
    _parse_semver,
    _record_deployment_provenance_sql,
    _reverse_dependencies_sql,
    _stage_deployment_provenance_sql,
    get_application_state,
    get_reverse_dependencies,
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


def test_delete_system_sql_uses_core_api():
    sql = _delete_system_sql()

    assert "pkg_application.delete_system_p" in sql
    assert "DELETED_SYSTEM=Y" in sql
    assert "WHENEVER SQLERROR EXIT FAILURE" in sql


def test_stage_deployment_provenance_sql_uses_core_api():
    sql = _stage_deployment_provenance_sql(
        {
            "application_name": "utl_interval",
            "version": "1.0.0",
            "deployment_type": "I",
            "deploy_commit_hash": "1234567890123456789012345678901234567890",
            "artifact_uri": "C:\\packages\\utl_interval.zip",
            "artifact_checksum": "abc123",
            "artifact_group_id": "com.example",
            "artifact_id": "utl_interval",
            "artifact_version": "1.0.0",
            "package_coordinate": "com.example:utl_interval:1.0.0",
            "build_metadata_json": {"source": "artifact-metadata"},
        }
    )

    assert "pkg_application.stage_deployment_provenance_p" in sql
    assert "ip_application_name         => 'UTL_INTERVAL'" in sql
    assert "ip_major_version            => 1" in sql
    assert "ip_minor_version            => 0" in sql
    assert "ip_patch_version            => 0" in sql
    assert "ip_deploy_commit_hash       => '1234567890123456789012345678901234567890'" in sql
    assert "ip_artifact_uri             => 'C:\\packages\\utl_interval.zip'" in sql
    assert "ip_artifact_checksum        => 'abc123'" in sql
    assert "ip_build_metadata_json      => '{\"source\":\"artifact-metadata\"}'" in sql
    assert "STAGED_DEPLOYMENT_PROVENANCE=" in sql


def test_record_deployment_provenance_sql_uses_core_api():
    sql = _record_deployment_provenance_sql(
        {
            "application_name": "core",
            "version": "3.4.0",
            "deployment_type": "I",
            "deploy_commit_hash": "1234567890123456789012345678901234567890",
            "artifact_uri": "C:\\packages\\core.zip",
            "artifact_checksum": "abc123",
            "build_metadata_json": {"source": "artifact-metadata"},
        }
    )

    assert "pkg_application.record_deployment_provenance_p" in sql
    assert "ip_application_name         => 'CORE'" in sql
    assert "ip_major_version            => 3" in sql
    assert "ip_minor_version            => 4" in sql
    assert "ip_patch_version            => 0" in sql
    assert "ip_deploy_commit_hash       => '1234567890123456789012345678901234567890'" in sql
    assert "ip_artifact_uri             => 'C:\\packages\\core.zip'" in sql
    assert "ip_artifact_checksum        => 'abc123'" in sql
    assert "RECORDED_DEPLOYMENT_PROVENANCE=" in sql


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


def test_get_application_state_treats_missing_core_registry_as_not_installed(monkeypatch):
    monkeypatch.setattr(
        "dbpm.db.run_sql_script",
        lambda **kwargs: SqlResult(
            returncode=2,
            stdout='SQL Error: ORA-00942: table or view "ADMIN"."APPLICATION" does not exist',
            stderr="",
        ),
    )

    assert get_application_state(connect="user/pass@db", runner="sql", application_name="CORE") is None


def test_reverse_dependencies_sql_queries_app_dependency():
    sql = _reverse_dependencies_sql("utl_interval")

    assert "DBPM_REVERSE_DEPENDENCY|" in sql
    assert "FROM app_dependency" in sql
    assert "WHERE depends_on = 'UTL_INTERVAL'" in sql


def test_deployment_provenance_sql_uses_core_api():
    sql = _deployment_provenance_sql("utl_interval", "1.2.3")

    assert "pkg_application.get_deployment_provenance_json_f" in sql
    assert "ip_application_name => 'UTL_INTERVAL'" in sql
    assert "ip_major_version    => 1" in sql
    assert "ip_minor_version    => 2" in sql
    assert "ip_patch_version    => 3" in sql
    assert "DBPM_DEPLOYMENT_PROVENANCE|" in sql


def test_parse_deployment_provenance():
    provenance = _parse_deployment_provenance(
        '\nDBPM_DEPLOYMENT_PROVENANCE|{"application_name":"UTL_INTERVAL","major_version":1}\n'
    )

    assert provenance == {"application_name": "UTL_INTERVAL", "major_version": 1}


def test_parse_deployment_provenance_not_found():
    assert _parse_deployment_provenance("") is None


def test_parse_reverse_dependencies():
    dependencies = _parse_reverse_dependencies(
        "\nDBPM_REVERSE_DEPENDENCY|JOB_CONTROL\nDBPM_REVERSE_DEPENDENCY|MY_APP\n"
    )

    assert dependencies == ["JOB_CONTROL", "MY_APP"]


def test_get_reverse_dependencies_treats_missing_core_registry_as_empty(monkeypatch):
    monkeypatch.setattr(
        "dbpm.db.run_sql_script",
        lambda **kwargs: SqlResult(
            returncode=2,
            stdout='SQL Error: ORA-00942: table or view "ADMIN"."APP_DEPENDENCY" does not exist',
            stderr="",
        ),
    )

    assert get_reverse_dependencies(connect="user/pass@db", runner="sql", application_name="DEMO") == []
