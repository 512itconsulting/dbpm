from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dbpm.errors import DbpmError
from dbpm.script_generator import generate_scripts, resolve_generation_options


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, text: str = "PROMPT object\n") -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path, *, manifest: bool = True) -> tuple[Path, str]:
    repo = tmp_path / "demo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    if manifest:
        _write(
            repo,
            "dbpm.yaml",
            """
package:
  name: demo
  version: "1.4.0"
scripts:
  install: sql/install.sql
  upgrade: sql/update.sql
generation:
  release_upgrade_output: sql/releases/1.5.0/update.sql
""".lstrip(),
        )
    _write(repo, "Tables/ORDERS.sql")
    _write(repo, "Tables/OLD_ORDERS.sql")
    _write(repo, "Packages/PKG_DEMO.pks")
    _write(repo, "Packages/PKG_DEMO.pkb")
    return repo, _commit(repo, "baseline")


def test_generates_install_release_update_and_pointer_from_git_diff(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(
        repo,
        "dbpm.yaml",
        """
package:
  name: demo
  version: "1.5.0"
scripts:
  install: sql/install.sql
  upgrade: sql/update.sql
generation:
  release_upgrade_output: sql/releases/1.5.0/update.sql
""".lstrip(),
    )
    _write(repo, "Tables/ORDERS.sql", "CREATE TABLE ORDERS (ID NUMBER, NOTE VARCHAR2(30));\n")
    _write(repo, "Tables/ORDERS.alter.1.5.0.sql", "ALTER TABLE ORDERS ADD NOTE VARCHAR2(30);\n")
    _write(repo, "Tables/NEW_ORDERS.sql")
    (repo / "Tables/OLD_ORDERS.sql").unlink()
    _write(repo, "Tables/OLD_ORDERS.drop.1.5.0.sql", "EXEC pkg_application.drop_and_forget_object_p('TABLE', 'OLD_ORDERS');\n")
    _write(repo, "Packages/PKG_DEMO.pkb", "PROMPT changed body\n")
    target = _commit(repo, "release")

    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target)
    result = generate_scripts(options)

    assert {path.relative_to(repo).as_posix() for path in result.changed} == {
        "sql/install.sql",
        "sql/releases/1.5.0/update.sql",
        "sql/update.sql",
    }
    install = (repo / "sql/install.sql").read_text(encoding="utf-8")
    update = (repo / "sql/releases/1.5.0/update.sql").read_text(encoding="utf-8")
    pointer = (repo / "sql/update.sql").read_text(encoding="utf-8")

    assert "ORDERS.alter.1.5.0.sql" not in install
    assert "OLD_ORDERS.drop.1.5.0.sql" not in install
    assert "@@../Tables/ORDERS.sql" in install
    assert "@@../../../Tables/ORDERS.alter.1.5.0.sql" in update
    assert "@@../../../Tables/ORDERS.sql" not in update
    assert "@@../../../Tables/NEW_ORDERS.sql" in update
    assert "@@../../../Tables/OLD_ORDERS.drop.1.5.0.sql" in update
    assert "ip_object_name => 'ORDERS'" in update
    assert "ip_object_name => 'NEW_ORDERS'" in update
    assert "ip_object_name => 'PKG_DEMO'" in update
    assert "ip_object_name => 'OLD_ORDERS'" not in update
    assert "@@releases/1.5.0/update.sql &&1" in pointer


def test_initial_generation_without_from_writes_only_install(tmp_path: Path):
    repo, _ = _repo(tmp_path)

    options = resolve_generation_options(repo)
    result = generate_scripts(options)

    assert options.from_ref is None
    assert options.release_upgrade_output is None
    assert options.upgrade_pointer_output is None
    assert {path.relative_to(repo).as_posix() for path in result.outputs} == {"sql/install.sql"}
    assert {path.relative_to(repo).as_posix() for path in result.changed} == {"sql/install.sql"}
    assert (repo / "sql/install.sql").exists()
    assert not (repo / "sql/releases/1.5.0/update.sql").exists()
    assert not (repo / "sql/update.sql").exists()


def test_initial_generation_check_ignores_stale_or_missing_update_outputs(tmp_path: Path):
    repo, _ = _repo(tmp_path)
    options = resolve_generation_options(repo)
    generate_scripts(options)
    _write(repo, "sql/update.sql", "stale update pointer\n")

    check_options = resolve_generation_options(repo, check=True)
    result = generate_scripts(check_options)

    assert result.changed == ()
    assert {path.relative_to(repo).as_posix() for path in result.outputs} == {"sql/install.sql"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"deployment_type": "major"}, "--deployment-type requires --from"),
        (
            {"release_upgrade_output": "sql/releases/{version}/update.sql"},
            "--release-upgrade-output requires --from",
        ),
        ({"upgrade_pointer_output": "sql/update.sql"}, "--upgrade-pointer-output requires --from"),
    ],
)
def test_initial_generation_rejects_explicit_upgrade_options(
    tmp_path: Path,
    kwargs: dict[str, str],
    message: str,
):
    repo, _ = _repo(tmp_path)

    with pytest.raises(DbpmError, match=message):
        resolve_generation_options(repo, **kwargs)


def test_recreate_runs_immediately_before_canonical_ddl(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(repo, "Tables/ORDERS.sql", "CREATE TABLE ORDERS (NEW_ID NUMBER);\n")
    _write(repo, "Tables/ORDERS.recreate.3.10.0.sql", "PROMPT drop orders\n")
    target = _commit(repo, "recreate")

    options = resolve_generation_options(
        repo,
        from_ref=baseline,
        to_ref=target,
        version="3.10.0",
        release_upgrade_output="Deployment_Manifests/releases/3.10.0/update.sql",
    )
    generate_scripts(options)
    update = (repo / options.release_upgrade_output).read_text(encoding="utf-8")

    recreate = "@@../../../Tables/ORDERS.recreate.3.10.0.sql"
    canonical = "@@../../../Tables/ORDERS.sql"
    assert update.index(recreate) < update.index(canonical)
    assert update[update.index(recreate) :].splitlines()[1] == canonical


def test_unexplained_table_change_warns_and_comments_canonical_ddl(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(repo, "Tables/ORDERS.sql", "CREATE TABLE ORDERS (UNEXPLAINED NUMBER);\n")
    target = _commit(repo, "canonical only")

    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target, version="1.5.0")
    result = generate_scripts(options)
    update = (repo / options.release_upgrade_output).read_text(encoding="utf-8")

    assert result.warnings == (
        "Tables/ORDERS.sql changed without a matching alter or recreate script",
    )
    assert "-- @@../../../Tables/ORDERS.sql -- WARNING: missing alter or recreate script" in update
    assert "ip_object_name => 'ORDERS'" not in update


def test_zero_config_cli_values_and_default_to_head(tmp_path: Path):
    repo, baseline = _repo(tmp_path, manifest=False)
    _write(repo, "Tables/NEW_TABLE.sql")
    _commit(repo, "new table")

    options = resolve_generation_options(
        repo,
        from_ref=baseline,
        version="2.0.0",
        application_name="my_app",
    )

    assert options.to_ref == "HEAD"
    assert options.application_name == "MY_APP"
    assert options.install_output == "Deployment_Manifests/deploy.sql"
    assert options.release_upgrade_output == "Deployment_Manifests/releases/2.0.0/update.sql"
    assert options.upgrade_pointer_output == "Deployment_Manifests/update.sql"


def test_cli_values_override_manifest_and_deployment_type(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    options = resolve_generation_options(
        repo,
        from_ref=baseline,
        version="2.1.0",
        application_name="my-app",
        install_output="generated/install.sql",
        release_upgrade_output="generated/releases/{version}.sql",
        upgrade_pointer_output="generated/update.sql",
        deployment_type="major",
    )

    assert options.application_name == "MY_APP"
    assert options.install_output == "generated/install.sql"
    assert options.release_upgrade_output == "generated/releases/2.1.0.sql"
    assert options.upgrade_pointer_output == "generated/update.sql"
    assert options.deployment_type == "pkg_application.c_deploy_type_major"


def test_deployment_type_uses_manifest_version_delta(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(
        repo,
        "dbpm.yaml",
        """
package:
  name: demo
  version: "2.1.0"
""".lstrip(),
    )
    target = _commit(repo, "major release")

    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target)

    assert options.deployment_type == "pkg_application.c_deploy_type_major"


def test_check_detects_stale_outputs(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(repo, "Tables/NEW_TABLE.sql")
    target = _commit(repo, "new table")
    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target, version="1.5.0")
    generate_scripts(options)

    check_options = resolve_generation_options(
        repo,
        from_ref=baseline,
        to_ref=target,
        version="1.5.0",
        check=True,
    )
    generate_scripts(check_options)
    (repo / check_options.upgrade_pointer_output).write_text("stale\n", encoding="utf-8")
    with pytest.raises(DbpmError, match="stale or missing"):
        generate_scripts(check_options)


def test_core_generation_is_rejected(tmp_path: Path):
    repo, baseline = _repo(tmp_path, manifest=False)
    with pytest.raises(DbpmError, match="Core script generation is not supported"):
        resolve_generation_options(
            repo,
            from_ref=baseline,
            version="1.0.0",
            application_name="CORE",
        )


def test_new_table_with_evolution_script_is_rejected(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(repo, "Tables/NEW_TABLE.sql")
    _write(repo, "Tables/NEW_TABLE.alter.1.5.0.sql")
    target = _commit(repo, "ambiguous new table")
    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target, version="1.5.0")

    with pytest.raises(DbpmError, match="New table NEW_TABLE"):
        generate_scripts(options)
