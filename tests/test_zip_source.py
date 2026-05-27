import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm.errors import SourceError
from dbpm.source import load_package_source


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))


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
        archive.writestr(
            "demo-0.1.0/Deployment_Manifests/deploy.sql",
            "PROMPT deploy\n",
        )

    source = load_package_source(str(archive_path))

    assert source.is_zip
    assert source.root == "demo-0.1.0"
    assert source.manifest.name == "demo"
    assert source.metadata["git.commit.id"] == "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
    assert source.artifact_checksum == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert source.artifact_checksum_alg == "SHA-256"
    script_path = source.resolve_script_path("Deployment_Manifests/deploy.sql")
    assert isinstance(script_path, Path)
    assert script_path.name == "deploy.sql"
    assert script_path.parent.name == "Deployment_Manifests"
    assert script_path.exists()


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
    assert source.resolve_script_path("deploy.sql") == source.work_path / "deploy.sql"


def test_load_github_maven_package_downloads_zip(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
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

    downloads = {}

    def fake_download(url: str, destination: Path) -> None:
        downloads["url"] = url
        destination.write_bytes(fixture_archive.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    source = load_package_source(
        "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0"
    )

    assert downloads["url"] == (
        "https://maven.pkg.github.com/rsantmyer/demo/"
        "com/512itconsulting/database/demo/0.1.0/demo-0.1.0.zip"
    )
    assert source.display_path == downloads["url"]
    assert source.manifest.name == "demo"
    assert source.resolve_script_path("deploy.sql") == source.work_path / "deploy.sql"
    assert (source.work_path / "deploy.sql").exists()


def test_load_url_zip_package_downloads_zip(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
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

    downloads = {}

    def fake_download(url: str, destination: Path) -> None:
        downloads["url"] = url
        destination.write_bytes(fixture_archive.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    source = load_package_source("https://example.test/packages/demo-0.1.0.zip")

    assert downloads["url"] == "https://example.test/packages/demo-0.1.0.zip"
    assert source.display_path == downloads["url"]
    assert source.manifest.name == "demo"
    assert source.artifact_checksum == hashlib.sha256(fixture_archive.read_bytes()).hexdigest()


def test_load_github_maven_snapshot_resolves_timestamped_zip(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
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

    metadata = """
<metadata>
  <versioning>
    <snapshotVersions>
      <snapshotVersion>
        <extension>zip</extension>
        <value>0.1.0-20260522.201317-1</value>
      </snapshotVersion>
    </snapshotVersions>
  </versioning>
</metadata>
"""
    downloads = {}

    monkeypatch.setattr("dbpm.source._download_text", lambda url: metadata)

    def fake_download(url: str, destination: Path) -> None:
        downloads["url"] = url
        destination.write_bytes(fixture_archive.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    source = load_package_source(
        "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0-SNAPSHOT"
    )

    assert downloads["url"].endswith(
        "/0.1.0-SNAPSHOT/demo-0.1.0-20260522.201317-1.zip"
    )
    assert source.manifest.name == "demo"


def test_zip_without_dbpm_manifest_can_derive_manifest_from_pom(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "demo/pom.xml",
            """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>0.1.0-SNAPSHOT</version>
  <description>Demo package</description>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>core</artifactId>
      <version>0.1.0-SNAPSHOT</version>
      <type>pom</type>
    </dependency>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>demo_base</artifactId>
      <version>0.1.0-SNAPSHOT</version>
      <type>pom</type>
    </dependency>
  </dependencies>
</project>
""",
        )
        archive.writestr("demo/Deployment_Manifests/deploy.sql", "PROMPT deploy\n")
        archive.writestr("demo/Tests/smoke_test.sql", "PROMPT test\n")

    source = load_package_source(str(archive_path))

    assert source.manifest_name == "demo/pom.xml"
    assert source.manifest.name == "demo"
    assert source.manifest.version == "0.1.0-SNAPSHOT"
    assert source.manifest.description == "Demo package"
    assert source.manifest.scripts.install == "Deployment_Manifests/deploy.sql"
    assert source.manifest.scripts.validate == "Tests/smoke_test.sql"
    assert len(source.manifest.dependencies) == 1
    assert source.manifest.dependencies[0].name == "demo_base"


def test_directory_source_claims_tree_artifact_checksum(tmp_path: Path):
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

    assert source.artifact_checksum is not None
    assert len(source.artifact_checksum) == 64
    assert source.artifact_checksum_alg == "TREE-SHA-256"


def test_directory_tree_checksum_ignores_local_noise(tmp_path: Path):
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
    (package / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    baseline = load_package_source(str(package)).artifact_checksum

    (package / ".dbpm-cache-refresh").mkdir()
    (package / ".dbpm-cache-refresh" / "artifact.zip").write_text("ignored", encoding="utf-8")
    (package / "target").mkdir()
    (package / "target" / "generated.txt").write_text("ignored", encoding="utf-8")
    (package / "deploy.log").write_text("ignored", encoding="utf-8")

    assert load_package_source(str(package)).artifact_checksum == baseline


def test_directory_tree_checksum_is_stable_across_root_paths(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for package in (first, second):
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
        (package / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")

    assert load_package_source(str(first)).artifact_checksum == load_package_source(
        str(second)
    ).artifact_checksum


def test_directory_tree_checksum_changes_when_source_changes(tmp_path: Path):
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
    (package / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    baseline = load_package_source(str(package)).artifact_checksum

    (package / "deploy.sql").write_text("PROMPT changed\n", encoding="utf-8")

    assert load_package_source(str(package)).artifact_checksum != baseline


def test_missing_manifest_fails(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()

    with pytest.raises(SourceError, match="No dbpm manifest"):
        load_package_source(str(package))
