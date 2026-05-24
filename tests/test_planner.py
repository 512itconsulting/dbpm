from pathlib import Path

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
    )

    assert plan["schema_version"] == "dbpm.plan.v0"
    assert plan["package"]["application_name"] == "UTL_INTERVAL"
    assert plan["core"]["required"] is True
    assert plan["provenance"]["source"] == "artifact-metadata"
    assert plan["policy"]["result"] == "allowed"
    assert plan["execution"]["arguments"] == ["1234567890123456789012345678901234567890"]


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
