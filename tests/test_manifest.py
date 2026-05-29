import pytest

from dbpm.errors import ManifestError
from dbpm.manifest import parse_manifest


def test_parse_manifest_with_dependencies():
    manifest = parse_manifest(
        """
package:
  name: job_control
  version: "1.0.0"
  description: Scheduling Package
  vendor: rsantmyer
  license: Apache-2.0

database:
  platform: oracle
  minimum_version: "19c"

core:
  minimum_version: "3.0.0"

dependencies:
  - name: utl_interval
    version: "^1.2.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/upgrade.sql
""",
        "dbpm.yaml",
    )

    assert manifest.name == "job_control"
    assert manifest.application_name == "JOB_CONTROL"
    assert manifest.version == "1.0.0"
    assert manifest.core_minimum_version == "3.0.0"
    assert manifest.dependencies[0].name == "utl_interval"
    assert manifest.scripts.install == "Deployment_Manifests/deploy.sql"


def test_parse_json_manifest():
    manifest = parse_manifest(
        """
{
  "package": {
    "name": "demo",
    "version": "0.1.0"
  },
  "scripts": {
    "install": "deploy.sql"
  }
}
""",
        "dbpm.json",
    )

    assert manifest.application_name == "DEMO"
    assert manifest.scripts.install == "deploy.sql"


def test_missing_package_name_fails():
    with pytest.raises(ManifestError, match="`name` is required"):
        parse_manifest(
            """
package:
  version: "0.1.0"
""",
            "dbpm.yaml",
        )


def test_upgrade_from_parses_from_yaml():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: Deployment_Manifests/upgrade.sql
  upgrade_from: "^1.2.0"
""",
        "dbpm.yaml",
    )

    assert manifest.scripts.upgrade_from == "^1.2.0"


def test_upgrade_from_parses_exact_version():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: Deployment_Manifests/upgrade.sql
  upgrade_from: "1.2.0"
""",
        "dbpm.yaml",
    )

    assert manifest.scripts.upgrade_from == "1.2.0"


def test_upgrade_from_absent_defaults_to_none():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: Deployment_Manifests/upgrade.sql
""",
        "dbpm.yaml",
    )

    assert manifest.scripts.upgrade_from is None


def test_upgrade_from_parses_from_json():
    manifest = parse_manifest(
        '{"package": {"name": "demo", "version": "1.3.0"}, "scripts": {"upgrade": "upgrade.sql", "upgrade_from": "^1.0.0"}}',
        "dbpm.json",
    )

    assert manifest.scripts.upgrade_from == "^1.0.0"


def test_upgrade_from_invalid_syntax_fails():
    with pytest.raises(ManifestError, match="upgrade_from"):
        parse_manifest(
            """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: upgrade.sql
  upgrade_from: "latest"
""",
            "dbpm.yaml",
        )


def test_upgrade_from_tilde_constraint_parses():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: upgrade.sql
  upgrade_from: "~1.2.0"
""",
        "dbpm.yaml",
    )

    assert manifest.scripts.upgrade_from == "~1.2.0"


def test_upgrade_from_tilde_invalid_base_fails():
    with pytest.raises(ManifestError, match="upgrade_from"):
        parse_manifest(
            """
package:
  name: demo
  version: "1.3.0"
scripts:
  upgrade: upgrade.sql
  upgrade_from: "~1.2"
""",
            "dbpm.yaml",
        )


def test_dependency_tilde_constraint_accepted():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "1.0.0"
dependencies:
  - name: utl_interval
    version: "~1.2.0"
""",
        "dbpm.yaml",
    )

    assert manifest.dependencies[0].version == "~1.2.0"


def test_invalid_dependency_shape_fails():
    with pytest.raises(ManifestError, match="dependencies"):
        parse_manifest(
            """
package:
  name: demo
  version: "0.1.0"

dependencies:
  name: utl_interval
""",
            "dbpm.yaml",
        )


# ---------------------------------------------------------------------------
# publish: section
# ---------------------------------------------------------------------------


def test_parse_manifest_with_publish_section():
    manifest = parse_manifest(
        """
package:
  name: utl_interval
  version: "1.0.0"

publish:
  group: com.example.database
  artifact_id: utl_interval
""",
        "dbpm.yaml",
    )

    assert manifest.publish is not None
    assert manifest.publish.group == "com.example.database"
    assert manifest.publish.artifact_id == "utl_interval"


def test_parse_manifest_publish_without_artifact_id():
    manifest = parse_manifest(
        """
package:
  name: utl_interval
  version: "1.0.0"

publish:
  group: com.example.database
""",
        "dbpm.yaml",
    )

    assert manifest.publish is not None
    assert manifest.publish.group == "com.example.database"
    assert manifest.publish.artifact_id is None


def test_parse_manifest_publish_absent():
    manifest = parse_manifest(
        """
package:
  name: utl_interval
  version: "1.0.0"
""",
        "dbpm.yaml",
    )

    assert manifest.publish is None


def test_parse_manifest_publish_missing_group_raises():
    from dbpm.errors import ManifestError

    with pytest.raises(ManifestError, match="group"):
        parse_manifest(
            """
package:
  name: utl_interval
  version: "1.0.0"

publish:
  artifact_id: utl_interval
""",
            "dbpm.yaml",
        )
