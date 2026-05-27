from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm.errors import ManifestError
from dbpm.environment import resolve_environment
from dbpm.planner import create_plan
from dbpm.provenance import resolve_provenance
from dbpm.source import load_package_source


def test_directory_plan_uses_artifact_metadata(tmp_path: Path):
    package = tmp_path / "utl_interval"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: utl_interval
  version: "1.0.0"

database:
  platform: oracle

core:
  minimum_version: "3.0.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  validate: Tests/smoke_test.sql
""",
        encoding="utf-8",
    )
    meta = package / "META-INF"
    meta.mkdir()
    (meta / "utl_interval-build.properties").write_text(
        "\n".join(
            [
                "artifact.groupId=com.512itconsulting.database",
                "artifact.artifactId=utl_interval",
                "artifact.version=1.0.0",
                "git.commit.id=1234567890123456789012345678901234567890",
                "git.dirty=false",
            ]
        ),
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    provenance = resolve_provenance(source)
    plan = create_plan(
        mode="install",
        source=source,
        provenance=provenance,
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "UTL_INTERVAL",
            "version": "1.0.0",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
        reverse_dependencies=["JOB_CONTROL"],
    )

    assert plan["schema_version"] == "dbpm.plan.v0"
    assert plan["package"]["application_name"] == "UTL_INTERVAL"
    assert plan["core"]["required"] is True
    assert plan["provenance"]["source"] == "artifact-metadata"
    assert plan["installed_state"]["application_name"] == "UTL_INTERVAL"
    assert plan["reverse_dependencies"] == ["JOB_CONTROL"]
    assert plan["policy"]["result"] == "allowed"
    assert plan["execution"]["arguments"] == ["1234567890123456789012345678901234567890"]
    assert plan["pre_actions"][0]["type"] == "stage_deployment_provenance"
    payload = plan["pre_actions"][0]["payload"]
    assert payload["application_name"] == "UTL_INTERVAL"
    assert payload["version"] == "1.0.0"
    assert payload["deployment_type"] == "I"
    assert payload["deploy_commit_hash"] == "1234567890123456789012345678901234567890"
    assert payload["artifact_group_id"] == "com.512itconsulting.database"
    assert payload["artifact_id"] == "utl_interval"
    assert payload["artifact_version"] == "1.0.0"
    assert payload["package_coordinate"] == "com.512itconsulting.database:utl_interval:1.0.0"


def test_resume_uses_install_script(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="resume",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
    )

    assert plan["execution"]["script"] == "deploy.sql"
    assert plan["pre_actions"][0]["type"] == "stage_deployment_provenance"


def test_zip_plan_stages_artifact_checksum(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "demo/dbpm.yaml",
            """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
""",
        )
        archive.writestr("demo/deploy.sql", "PROMPT deploy\n")

    source = load_package_source(str(archive_path))
    plan = create_plan(
        mode="install",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
    )

    payload = plan["pre_actions"][0]["payload"]
    assert payload["artifact_checksum"] == source.artifact_checksum
    assert payload["artifact_checksum_alg"] == "SHA-256"
    assert payload["artifact_file_name"] == "demo.zip"
    assert payload["artifact_extension"] == "zip"


def test_validate_uses_validate_script_without_commit_argument(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
  validate: smoke.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="validate",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
    )

    assert plan["execution"]["script"] == "smoke.sql"
    assert plan["execution"]["arguments"] == []


def test_upgrade_deployment_type_uses_version_delta(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "2.0.0"

scripts:
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="upgrade",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "DEMO",
            "version": "1.9.9",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert plan["pre_actions"][0]["payload"]["deployment_type"] == "V"


def test_upgrade_deployment_type_detects_minor_delta(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "1.2.0"

scripts:
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="upgrade",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "DEMO",
            "version": "1.1.9",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert plan["pre_actions"][0]["payload"]["deployment_type"] == "M"


def test_upgrade_deployment_type_detects_patch_delta(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "1.2.3"

scripts:
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="upgrade",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "DEMO",
            "version": "1.2.2",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert plan["pre_actions"][0]["payload"]["deployment_type"] == "P"


def test_reinstall_requires_destructive_flag(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    provenance = resolve_provenance(source)
    plan = create_plan(
        mode="reinstall",
        source=source,
        provenance=provenance,
        environment=resolve_environment("development"),
    )

    assert plan["policy"]["result"] == "requires-approval"
    assert "`reinstall` requires --allow-destructive" in plan["policy"]["required_approvals"]
    assert plan["pre_actions"] == [
        {
            "type": "delete_application",
            "application_name": "DEMO",
            "fail_on_not_found": "N",
        },
        {
            "type": "stage_deployment_provenance",
            "payload": plan["pre_actions"][1]["payload"],
        },
    ]
    assert plan["pre_actions"][1]["payload"]["application_name"] == "DEMO"


def test_bootstrap_core_does_not_require_core(tmp_path: Path):
    package = tmp_path / "core"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.0.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="bootstrap-core",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
    )

    assert plan["core"]["required"] is False
    assert plan["core"]["bootstrap"] is True
    assert plan["pre_actions"] == []
    assert plan["post_actions"] == []


def test_bootstrap_core_34_records_provenance_after_deploy(tmp_path: Path):
    package = tmp_path / "core"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.4.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="bootstrap-core",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
    )

    assert plan["core"]["required"] is False
    assert plan["pre_actions"] == []
    assert plan["post_actions"][0]["type"] == "record_deployment_provenance"
    assert plan["post_actions"][0]["payload"]["application_name"] == "CORE"
    assert plan["post_actions"][0]["payload"]["version"] == "3.4.0"
    assert plan["post_actions"][0]["payload"]["deployment_type"] == "I"


def test_core_upgrade_stages_provenance_when_installed_core_supports_it(tmp_path: Path):
    package = tmp_path / "core"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.3.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/update.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="upgrade",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "CORE",
            "version": "3.2.0",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert plan["core"]["required"] is False
    assert plan["execution"]["script"] == "Deployment_Manifests/update.sql"
    assert plan["pre_actions"][0]["type"] == "stage_deployment_provenance"
    assert plan["pre_actions"][0]["payload"]["application_name"] == "CORE"
    assert plan["pre_actions"][0]["payload"]["deployment_type"] == "M"


def test_core_upgrade_skips_provenance_when_installed_core_is_too_old(tmp_path: Path):
    package = tmp_path / "core"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.2.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/update.sql
""",
        encoding="utf-8",
    )

    source = load_package_source(str(package))
    plan = create_plan(
        mode="upgrade",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state={
            "application_name": "CORE",
            "version": "3.1.0",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert plan["pre_actions"] == []


def test_missing_install_script_fails(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"
""",
        encoding="utf-8",
    )
    source = load_package_source(str(package))

    with pytest.raises(ManifestError, match="No script"):
        create_plan(
            mode="install",
            source=source,
            provenance=resolve_provenance(source),
            environment=resolve_environment("development"),
        )
