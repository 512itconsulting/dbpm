from dbpm.db import _core_check_sql, _parse_semver


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
