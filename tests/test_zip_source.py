import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm.errors import SourceError
from dbpm.source import load_package_source


def test_load_package_from_zip(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "demo-0.1.0/dbpm.yaml",
            """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        )
        archive.writestr(
            "demo-0.1.0/META-INF/demo-build.properties",
            "git.commit.id=abcdefabcdefabcdefabcdefabcdefabcdefabcd\n",
        )

    source = load_package_source(str(archive_path))

    assert source.is_zip
    assert source.root == "demo-0.1.0"
    assert source.manifest.name == "demo"
    assert source.metadata["git.commit.id"] == "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert source.artifact_checksum == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert source.artifact_checksum_alg == "SHA-256"
    assert (
        source.resolve_script_path("Deployment_Manifests/deploy.sql")
        == "demo-0.1.0/Deployment_Manifests/deploy.sql"
    )


def test_load_package_from_zip_without_base_directory(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "dbpm.yaml",
            """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
""",
        )

    source = load_package_source(str(archive_path))

    assert source.root is None
    assert source.resolve_script_path("deploy.sql") == "deploy.sql"


def test_directory_source_does_not_claim_artifact_checksum(tmp_path: Path):
    package = tmp_path / "package"
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

    assert source.artifact_checksum is None
    assert source.artifact_checksum_alg is None


def test_missing_manifest_fails(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()

    with pytest.raises(SourceError, match="No dbpm manifest"):
        load_package_source(str(package))
