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


def test_cache_dir_expands_quoted_home(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DBPM_CACHE_DIR", "~/.local/cache/dbpm")
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

    assert source.work_path.is_relative_to(home / ".local" / "cache" / "dbpm")


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


@pytest.mark.parametrize(
    "member",
    [
        "../outside.txt",
        "demo/../../outside.txt",
        "/absolute.txt",
        "C:/absolute.txt",
        "demo\\..\\outside.txt",
    ],
)
def test_zip_source_rejects_unsafe_member_paths(tmp_path: Path, member: str):
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
        archive.writestr(member, "nope\n")

    with pytest.raises(SourceError, match="Unsafe ZIP member path"):
        load_package_source(str(archive_path))


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


def test_load_generic_maven_package_downloads_zip(tmp_path: Path, monkeypatch):
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
        "maven:https://repo.example.test/releases::com.512itconsulting.database:demo:0.1.0"
    )

    assert downloads["url"] == (
        "https://repo.example.test/releases/"
        "com/512itconsulting/database/demo/0.1.0/demo-0.1.0.zip"
    )
    assert source.display_path == downloads["url"]
    assert source.manifest.name == "demo"
    assert source.resolve_script_path("deploy.sql") == source.work_path / "deploy.sql"


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


def test_load_generic_maven_snapshot_resolves_timestamped_zip(tmp_path: Path, monkeypatch):
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
    metadata_urls = []

    def fake_download_text(url: str) -> str:
        metadata_urls.append(url)
        return metadata

    monkeypatch.setattr("dbpm.source._download_text", fake_download_text)

    def fake_download(url: str, destination: Path) -> None:
        downloads["url"] = url
        destination.write_bytes(fixture_archive.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    source = load_package_source(
        "maven:https://repo.example.test/snapshots/::"
        "com.512itconsulting.database:demo:0.1.0-SNAPSHOT"
    )

    assert metadata_urls == [
        "https://repo.example.test/snapshots/"
        "com/512itconsulting/database/demo/0.1.0-SNAPSHOT/maven-metadata.xml"
    ]
    assert downloads["url"] == (
        "https://repo.example.test/snapshots/"
        "com/512itconsulting/database/demo/0.1.0-SNAPSHOT/"
        "demo-0.1.0-20260522.201317-1.zip"
    )
    assert source.manifest.name == "demo"


def test_generic_maven_source_rejects_missing_separator():
    with pytest.raises(SourceError, match="Maven sources must use"):
        load_package_source(
            "maven:https://repo.example.test/releases:com.512itconsulting.database:demo:0.1.0"
        )


def test_generic_maven_source_rejects_non_http_repository():
    with pytest.raises(SourceError, match="repository URL must start"):
        load_package_source("maven:file:///repo::com.512itconsulting.database:demo:0.1.0")


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


def test_directory_tree_checksum_honors_dbpmignore(tmp_path: Path):
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
    (package / ".dbpmignore").write_text(
        """
# legacy Maven inputs
pom.xml
assembly/
docs/maven/**
""",
        encoding="utf-8",
    )
    (package / "pom.xml").write_text("<project />\n", encoding="utf-8")
    (package / "assembly").mkdir()
    (package / "assembly" / "package.xml").write_text("ignored\n", encoding="utf-8")
    (package / "docs" / "maven").mkdir(parents=True)
    (package / "docs" / "maven" / "legacy.md").write_text("ignored\n", encoding="utf-8")

    baseline = load_package_source(str(package)).artifact_checksum

    (package / "pom.xml").write_text("<project>changed</project>\n", encoding="utf-8")
    (package / "assembly" / "package.xml").write_text("changed\n", encoding="utf-8")
    (package / "docs" / "maven" / "legacy.md").write_text("changed\n", encoding="utf-8")

    assert load_package_source(str(package)).artifact_checksum == baseline


def test_directory_tree_checksum_keeps_dbpmignore_by_default(tmp_path: Path):
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
    (package / ".dbpmignore").write_text("pom.xml\n", encoding="utf-8")

    baseline = load_package_source(str(package)).artifact_checksum

    (package / ".dbpmignore").write_text("pom.xml\nassembly/\n", encoding="utf-8")

    assert load_package_source(str(package)).artifact_checksum != baseline


def test_dbpmignore_negation_fails_clearly(tmp_path: Path):
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
    (package / ".dbpmignore").write_text("*.sql\n!deploy.sql\n", encoding="utf-8")

    with pytest.raises(SourceError, match="negation patterns are not supported"):
        load_package_source(str(package))


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


def test_load_zip_with_correct_expected_checksum_passes(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    source = load_package_source(str(archive_path), expected_checksum=checksum, expected_checksum_alg="SHA-256")

    assert source.artifact_checksum == checksum


def test_load_zip_with_wrong_expected_checksum_fails(tmp_path: Path):
    archive_path = tmp_path / "demo.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")

    with pytest.raises(SourceError, match="Checksum mismatch"):
        load_package_source(str(archive_path), expected_checksum="a" * 64, expected_checksum_alg="SHA-256")


def test_load_directory_with_correct_expected_checksum_passes(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n", encoding="utf-8"
    )
    source = load_package_source(str(package))
    tree_checksum = source.artifact_checksum

    source2 = load_package_source(str(package), expected_checksum=tree_checksum, expected_checksum_alg="TREE-SHA-256")

    assert source2.artifact_checksum == tree_checksum


def test_load_directory_with_wrong_expected_checksum_fails(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n", encoding="utf-8"
    )

    with pytest.raises(SourceError, match="Checksum mismatch"):
        load_package_source(str(package), expected_checksum="b" * 64, expected_checksum_alg="TREE-SHA-256")


def test_maven_download_with_correct_checksum_passes(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")

    monkeypatch.setattr(
        "dbpm.source._download",
        lambda url, destination: destination.write_bytes(fixture_archive.read_bytes()),
    )
    expected = hashlib.sha256(fixture_archive.read_bytes()).hexdigest()

    source = load_package_source(
        "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0",
        expected_checksum=expected,
        expected_checksum_alg="SHA-256",
    )

    assert source.artifact_checksum == expected


def test_maven_download_with_wrong_checksum_fails(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")

    monkeypatch.setattr(
        "dbpm.source._download",
        lambda url, destination: destination.write_bytes(fixture_archive.read_bytes()),
    )

    with pytest.raises(SourceError, match="Checksum mismatch"):
        load_package_source(
            "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0",
            expected_checksum="c" * 64,
            expected_checksum_alg="SHA-256",
        )


def test_checksum_cache_is_populated_after_download(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")

    monkeypatch.setattr(
        "dbpm.source._download",
        lambda url, destination: destination.write_bytes(fixture_archive.read_bytes()),
    )
    expected = hashlib.sha256(fixture_archive.read_bytes()).hexdigest()

    load_package_source(
        "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0",
        expected_checksum=expected,
        expected_checksum_alg="SHA-256",
    )

    cache_dir = tmp_path / "cache" / "by-checksum" / "sha256" / expected
    assert cache_dir.exists()
    assert list(cache_dir.iterdir())


def test_checksum_cache_hit_skips_download(tmp_path: Path, monkeypatch):
    fixture_archive = tmp_path / "fixture.zip"
    with ZipFile(fixture_archive, "w") as archive:
        archive.writestr("demo/dbpm.yaml", "package:\n  name: demo\n  version: '0.1.0'\nscripts:\n  install: deploy.sql\n")

    download_calls: list[str] = []

    def fake_download(url: str, destination: Path) -> None:
        download_calls.append(url)
        destination.write_bytes(fixture_archive.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)
    expected = hashlib.sha256(fixture_archive.read_bytes()).hexdigest()
    coord = "gh-maven:rsantmyer/demo:com.512itconsulting.database:demo:0.1.0"

    # First load populates the checksum cache
    load_package_source(coord, expected_checksum=expected, expected_checksum_alg="SHA-256")
    assert len(download_calls) == 1

    # Second load hits the checksum cache — no download
    load_package_source(coord, expected_checksum=expected, expected_checksum_alg="SHA-256")
    assert len(download_calls) == 1


def test_signature_verification_uses_expected_url_even_with_stale_colocated_signature(
    tmp_path: Path,
    monkeypatch,
):
    from dbpm.source import _check_or_skip_signature

    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"zip")
    (tmp_path / "artifact.zip.asc").write_bytes(b"stale signature")
    signature_url = "https://repo.example.test/signatures/artifact.zip.asc"
    downloaded: list[str] = []
    verified: list[Path] = []

    def fake_download(url: str, destination: Path) -> None:
        downloaded.append(url)
        destination.write_bytes(b"expected signature")

    def fake_check_gpg_signature(artifact_path: Path, asc_path: Path, artifact_file_name: str) -> None:
        verified.append(asc_path)
        assert asc_path.read_bytes() == b"expected signature"

    monkeypatch.setattr("dbpm.source._download", fake_download)
    monkeypatch.setattr("dbpm.source._check_gpg_signature", fake_check_gpg_signature)

    _check_or_skip_signature(
        "https://repo.example.test/artifacts/artifact.zip",
        artifact,
        signature_url,
    )

    assert downloaded == [signature_url]
    assert verified
    assert verified[0].name != "artifact.zip.asc"


def test_directory_tree_checksum_keeps_nested_dist_payload(tmp_path: Path):
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

    # Root-level build outputs stay excluded from the tree checksum.
    (package / "dist").mkdir()
    (package / "dist" / "demo-0.1.0.zip").write_text("ignored", encoding="utf-8")
    assert load_package_source(str(package)).artifact_checksum == baseline

    # Nested dist directories are payload, such as bundled runtime wheels.
    payload = package / "os" / "dist"
    payload.mkdir(parents=True)
    (payload / "runner-0.1.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")
    assert load_package_source(str(package)).artifact_checksum != baseline
