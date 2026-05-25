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
