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


def test_initial_generation_includes_lowercase_scaffold_directories(tmp_path: Path):
    repo = tmp_path / "demo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _write(
        repo,
        "dbpm.yaml",
        """
package:
  name: demo
  version: "0.1.0"
scripts:
  install: deployment_manifests/deploy.sql
""".lstrip(),
    )
    _write(repo, "tables/REPLACEMENT_VARS.sql")
    _write(repo, "packages/PKG_REPLACEMENT_VAR.pks")
    _write(repo, "packages/PKG_REPLACEMENT_VAR.pkb")
    _write(repo, "metadata/REPLACEMENT_VARS.core.sql")
    _commit(repo, "lowercase scaffold")

    options = resolve_generation_options(repo)
    generate_scripts(options)
    install = (repo / "deployment_manifests/deploy.sql").read_text(encoding="utf-8")

    assert "@@../tables/REPLACEMENT_VARS.sql" in install
    assert "@@../packages/PKG_REPLACEMENT_VAR.pks" in install
    assert "@@../packages/PKG_REPLACEMENT_VAR.pkb" in install
    assert "@@../metadata/REPLACEMENT_VARS.core.sql" in install
    assert "ip_object_name => 'REPLACEMENT_VARS'" in install
    assert "ip_object_name => 'PKG_REPLACEMENT_VAR'" in install


def test_type_specs_generic_sql_and_bodies_are_ordered_in_install(tmp_path: Path):
    repo, _ = _repo(tmp_path)
    _write(repo, "Types/ADDRESS.tps")
    _write(repo, "Types/ADDRESS.tpb")
    _write(repo, "Types/COUNTRY.sql")
    _write(repo, "Views/V_ADDRESS.sql")
    _commit(repo, "add types")

    options = resolve_generation_options(repo)
    generate_scripts(options)
    install = (repo / "sql/install.sql").read_text(encoding="utf-8")

    type_spec = "@@../Types/ADDRESS.tps"
    generic_type = "@@../Types/COUNTRY.sql"
    type_body = "@@../Types/ADDRESS.tpb"
    view = "@@../Views/V_ADDRESS.sql"
    assert type_spec in install
    assert generic_type in install
    assert type_body in install
    assert install.index(type_spec) < install.index(generic_type)
    assert install.index(generic_type) < install.index(type_body)
    assert install.index(type_body) < install.index(view)
    assert "PROMPT Deploying Type Specifications" in install
    assert "PROMPT Deploying Type Bodies" in install
    assert "ip_object_name => 'ADDRESS'" in install
    assert "ip_object_name => 'COUNTRY'" in install


def test_initial_generation_check_ignores_stale_or_missing_update_outputs(tmp_path: Path):
    repo, _ = _repo(tmp_path)
    options = resolve_generation_options(repo)
    generate_scripts(options)
    _write(repo, "sql/update.sql", "stale update pointer\n")

    check_options = resolve_generation_options(repo, check=True)
    result = generate_scripts(check_options)

    assert result.changed == ()
    assert {path.relative_to(repo).as_posix() for path in result.outputs} == {"sql/install.sql"}


def test_changed_type_specs_and_bodies_are_included_in_update(tmp_path: Path):
    repo, baseline = _repo(tmp_path)
    _write(repo, "Types/ADDRESS.tps")
    _write(repo, "Types/ADDRESS.tpb")
    target = _commit(repo, "add type spec and body")

    options = resolve_generation_options(repo, from_ref=baseline, to_ref=target, version="1.5.0")
    generate_scripts(options)
    update = (repo / options.release_upgrade_output).read_text(encoding="utf-8")

    type_spec = "@@../../../Types/ADDRESS.tps"
    type_body = "@@../../../Types/ADDRESS.tpb"
    assert type_spec in update
    assert type_body in update
    assert update.index(type_spec) < update.index(type_body)
    assert "PROMPT Deploying Type Specifications" in update
    assert "PROMPT Deploying Type Bodies" in update
    assert "ip_object_name => 'ADDRESS'" in update
    assert "ip_object_type => pkg_application.c_object_type_type" in update


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


def test_generate_scripts_from_workspace_subdirectory(tmp_path: Path):
    # Git repo is the workspace root; package lives in a subdirectory.
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test User")

    pkg = workspace / "packages" / "demo"
    _write(workspace, "packages/demo/dbpm.yaml", "package:\n  name: demo\n  version: \"1.0.0\"\n")
    _write(workspace, "packages/demo/Packages/PKG_DEMO.pks")
    baseline = _commit(workspace, "baseline")

    _write(workspace, "packages/demo/Procedures/NEW_PROC.sql")
    target = _commit(workspace, "add procedure")

    # Source is the package subdirectory, not the workspace/git root.
    options = resolve_generation_options(pkg, from_ref=baseline, to_ref=target, version="1.1.0")

    # Outputs must be written under the package root, not the workspace root.
    assert options.root == pkg
    assert options.git_root == workspace

    result = generate_scripts(options)

    install_path = pkg / options.install_output
    assert install_path.exists(), f"Install script not found at {install_path}"
    assert not (workspace / options.install_output).exists(), (
        "Install script was incorrectly written to the workspace root"
    )
    install_sql = install_path.read_text()
    assert "NEW_PROC" in install_sql


_PARENT_DDL = """\
CREATE TABLE PARENT (
    ID NUMBER NOT NULL,
    CONSTRAINT PARENT_PK PRIMARY KEY (ID)
);
"""

_CHILD_DDL = """\
CREATE TABLE CHILD (
    ID NUMBER NOT NULL,
    PARENT_ID NUMBER NOT NULL,
    CONSTRAINT CHILD_PK PRIMARY KEY (ID),
    CONSTRAINT CHILD_FK1 FOREIGN KEY (PARENT_ID)
        REFERENCES PARENT (ID)
);
"""

_GRANDCHILD_DDL = """\
CREATE TABLE GRANDCHILD (
    ID NUMBER NOT NULL,
    CHILD_ID NUMBER NOT NULL,
    CONSTRAINT GRANDCHILD_PK PRIMARY KEY (ID),
    CONSTRAINT GRANDCHILD_FK1
        FOREIGN KEY (CHILD_ID)
        REFERENCES CHILD (ID)
);
"""


def _table_positions(sql: str) -> dict[str, int]:
    """Return {table_name: line_index} for @@...Tables/TABLE_NAME.sql lines."""
    positions = {}
    for i, line in enumerate(sql.splitlines()):
        for name in ("PARENT", "CHILD", "GRANDCHILD"):
            if f"Tables/{name}.sql" in line:
                positions[name] = i
    return positions


def test_tables_deployed_in_fk_dependency_order(tmp_path: Path):
    repo, _ = _repo(tmp_path, manifest=False)
    # Write tables out-of-alphabetical-order so alphabetical != dependency order
    _write(repo, "Tables/GRANDCHILD.sql", _GRANDCHILD_DDL)
    _write(repo, "Tables/CHILD.sql", _CHILD_DDL)
    _write(repo, "Tables/PARENT.sql", _PARENT_DDL)
    baseline = _commit(repo, "add tables")

    options = resolve_generation_options(repo, version="1.0.0")
    generate_scripts(options)

    install_sql = (repo / "Deployment_Manifests/deploy.sql").read_text()
    pos = _table_positions(install_sql)
    assert pos["PARENT"] < pos["CHILD"] < pos["GRANDCHILD"]


def test_tables_with_no_fk_retain_alphabetical_order(tmp_path: Path):
    repo, _ = _repo(tmp_path, manifest=False)
    _write(repo, "Tables/ZEBRA.sql", "CREATE TABLE ZEBRA (ID NUMBER);\n")
    _write(repo, "Tables/APPLE.sql", "CREATE TABLE APPLE (ID NUMBER);\n")
    _write(repo, "Tables/MANGO.sql", "CREATE TABLE MANGO (ID NUMBER);\n")
    _commit(repo, "add tables")

    options = resolve_generation_options(repo, version="1.0.0")
    generate_scripts(options)

    install_sql = (repo / "Deployment_Manifests/deploy.sql").read_text()
    lines = [l for l in install_sql.splitlines() if "Tables/" in l]
    names = [l.split("Tables/")[1].split(".sql")[0] for l in lines if l.split("Tables/")[1].split(".sql")[0] in {"APPLE", "MANGO", "ZEBRA"}]
    assert names == ["APPLE", "MANGO", "ZEBRA"]


def test_fk_referencing_external_table_is_ignored(tmp_path: Path):
    repo, _ = _repo(tmp_path, manifest=False)
    _write(repo, "Tables/LOCAL.sql", "CREATE TABLE LOCAL (ID NUMBER,\nFOREIGN KEY (ID) REFERENCES EXTERNAL_PKG.SOMETABLE (ID));\n")
    _commit(repo, "add table")

    # Should not raise even though EXTERNAL_PKG.SOMETABLE is not in the package
    options = resolve_generation_options(repo, version="1.0.0")
    generate_scripts(options)


def test_circular_fk_dependency_raises_error(tmp_path: Path):
    repo, _ = _repo(tmp_path, manifest=False)
    _write(repo, "Tables/A.sql", "CREATE TABLE A (ID NUMBER, CONSTRAINT FK1 FOREIGN KEY (ID) REFERENCES B (ID));\n")
    _write(repo, "Tables/B.sql", "CREATE TABLE B (ID NUMBER, CONSTRAINT FK2 FOREIGN KEY (ID) REFERENCES A (ID));\n")
    _commit(repo, "circular fk")

    options = resolve_generation_options(repo, version="1.0.0")
    with pytest.raises(DbpmError, match="Circular table FK dependency"):
        generate_scripts(options)


def test_metadata_inherits_table_dependency_order(tmp_path: Path):
    repo, _ = _repo(tmp_path, manifest=False)
    _write(repo, "Tables/PARENT.sql", _PARENT_DDL)
    _write(repo, "Tables/CHILD.sql", _CHILD_DDL)
    _write(repo, "Metadata/CHILD.seed_data.sql", "INSERT INTO CHILD VALUES (1, 1);\n")
    _write(repo, "Metadata/PARENT.seed_data.sql", "INSERT INTO PARENT VALUES (1);\n")
    _commit(repo, "tables and metadata")

    options = resolve_generation_options(repo, version="1.0.0")
    generate_scripts(options)

    install_sql = (repo / "Deployment_Manifests/deploy.sql").read_text()
    lines = [l for l in install_sql.splitlines() if "Metadata/" in l]
    names = [l.split("Metadata/")[1].split(".")[0] for l in lines]
    assert names.index("PARENT") < names.index("CHILD")
