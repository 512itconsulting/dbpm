from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dbpm.errors import PublishError
from dbpm.manifest import Dependency, PackageManifest, PublishConfig, ScriptSet
from dbpm.publisher import (
    PublishReceipt,
    _parse_publish_target,
    _xml_escape,
    build_artifact,
    generate_pom,
    sign_artifact,
)


@pytest.fixture
def manifest() -> PackageManifest:
    return PackageManifest(
        name="utl_interval",
        version="1.2.3",
        application_name="UTL_INTERVAL",
        description="Interval utilities",
        vendor="rsantmyer",
        license="Apache-2.0",
        database_platform="oracle",
        database_minimum_version=None,
        core_minimum_version="3.0.0",
        dependencies=(Dependency(name="utl_file", version="1.0.0"),),
        scripts=ScriptSet(),
    )


@pytest.fixture
def publish_config() -> PublishConfig:
    return PublishConfig(group="com.example.database", artifact_id="utl_interval")


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))


# ---------------------------------------------------------------------------
# build_artifact
# ---------------------------------------------------------------------------


def test_build_artifact_creates_zip(tmp_path: Path, manifest: PackageManifest, publish_config: PublishConfig):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")
    (pkg / "deploy.sql").write_text("PROMPT deploy;\n")

    with patch("dbpm.publisher._git_commit_id", return_value="abc123"):
        artifact_path = build_artifact(pkg, manifest, publish_config)

    assert artifact_path.exists()
    assert artifact_path.name == "utl_interval-1.2.3.zip"

    with zipfile.ZipFile(artifact_path) as archive:
        names = archive.namelist()

    assert any(n.startswith("utl_interval-1.2.3/") for n in names)
    assert any("META-INF/utl_interval-build.properties" in n for n in names)


def test_build_artifact_uses_manifest_name_when_artifact_id_absent(
    tmp_path: Path,
    manifest: PackageManifest,
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")

    config = PublishConfig(group="com.example")

    with patch("dbpm.publisher._git_commit_id", return_value=""):
        artifact_path = build_artifact(pkg, manifest, config)

    assert artifact_path.name == "utl_interval-1.2.3.zip"


def test_build_artifact_build_properties_content(
    tmp_path: Path,
    manifest: PackageManifest,
    publish_config: PublishConfig,
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")

    with patch("dbpm.publisher._git_commit_id", return_value="deadbeef"):
        artifact_path = build_artifact(pkg, manifest, publish_config)

    with zipfile.ZipFile(artifact_path) as archive:
        props = archive.read("utl_interval-1.2.3/META-INF/utl_interval-build.properties").decode()

    assert "build.version=1.2.3" in props
    assert "build.source=dbpm" in props
    assert "git.commit.id=deadbeef" in props


# ---------------------------------------------------------------------------
# generate_pom
# ---------------------------------------------------------------------------


def test_generate_pom_basic_structure(manifest: PackageManifest, publish_config: PublishConfig):
    pom = generate_pom(manifest, publish_config)

    assert "<groupId>com.example.database</groupId>" in pom
    assert "<artifactId>utl_interval</artifactId>" in pom
    assert "<version>1.2.3</version>" in pom
    assert "<packaging>zip</packaging>" in pom
    assert "<description>Interval utilities</description>" in pom


def test_generate_pom_includes_core_dependency(manifest: PackageManifest, publish_config: PublishConfig):
    pom = generate_pom(manifest, publish_config)

    assert "<artifactId>core</artifactId>" in pom
    assert "<version>3.0.0</version>" in pom


def test_generate_pom_includes_manifest_dependencies(manifest: PackageManifest, publish_config: PublishConfig):
    pom = generate_pom(manifest, publish_config)

    assert "<artifactId>utl_file</artifactId>" in pom
    assert "<version>1.0.0</version>" in pom


def test_generate_pom_no_description_block_when_absent(publish_config: PublishConfig):
    m = PackageManifest(
        name="pkg",
        version="1.0.0",
        application_name="PKG",
        description=None,
        vendor=None,
        license=None,
        database_platform="oracle",
        database_minimum_version=None,
        core_minimum_version=None,
        dependencies=(),
        scripts=ScriptSet(),
    )
    pom = generate_pom(m, publish_config)

    assert "<description>" not in pom
    assert "<dependencies>" not in pom


def test_generate_pom_xml_escaping():
    m = PackageManifest(
        name="pkg",
        version="1.0.0",
        application_name="PKG",
        description="A & B <test>",
        vendor=None,
        license=None,
        database_platform="oracle",
        database_minimum_version=None,
        core_minimum_version=None,
        dependencies=(),
        scripts=ScriptSet(),
    )
    config = PublishConfig(group="com.example")
    pom = generate_pom(m, config)

    assert "A &amp; B &lt;test&gt;" in pom


# ---------------------------------------------------------------------------
# sign_artifact
# ---------------------------------------------------------------------------


def test_sign_artifact_success(tmp_path: Path):
    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"fake zip content")
    asc_file = tmp_path / "artifact.zip.asc"

    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        asc_path = sign_artifact(artifact, "test@example.com")

    assert asc_path == asc_file
    args = mock_run.call_args[0][0]
    assert "gpg" in args
    assert "--local-user" in args
    assert "test@example.com" in args


def test_sign_artifact_gpg_not_installed(tmp_path: Path):
    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"data")

    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(PublishError, match="GPG is not installed"):
            sign_artifact(artifact, "key")


def test_sign_artifact_gpg_fails(tmp_path: Path):
    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"data")

    mock_result = MagicMock()
    mock_result.returncode = 2
    mock_result.stderr = "secret key not available"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(PublishError, match="GPG signing failed"):
            sign_artifact(artifact, "badkey")


# ---------------------------------------------------------------------------
# _parse_publish_target
# ---------------------------------------------------------------------------


def test_parse_github_target():
    info = _parse_publish_target("gh-maven:acme/myrepo")
    assert info["type"] == "github"
    assert info["owner"] == "acme"
    assert info["repo"] == "myrepo"
    assert info["repository_url"] == "https://maven.pkg.github.com/acme/myrepo/"


def test_parse_maven_target():
    info = _parse_publish_target("maven:https://repo.example.com/maven2")
    assert info["type"] == "maven"
    assert info["repository_url"] == "https://repo.example.com/maven2/"


def test_parse_maven_target_trailing_slash_preserved():
    info = _parse_publish_target("maven:https://repo.example.com/maven2/")
    assert info["repository_url"] == "https://repo.example.com/maven2/"


def test_parse_publish_target_invalid():
    with pytest.raises(PublishError, match="Unsupported publish target"):
        _parse_publish_target("s3://bucket/path")


def test_parse_github_target_missing_slash():
    with pytest.raises(PublishError, match="gh-maven:owner/repo"):
        _parse_publish_target("gh-maven:noslash")


# ---------------------------------------------------------------------------
# _xml_escape
# ---------------------------------------------------------------------------


def test_xml_escape():
    assert _xml_escape("a & b") == "a &amp; b"
    assert _xml_escape("<tag>") == "&lt;tag&gt;"
    assert _xml_escape('"quoted"') == "&quot;quoted&quot;"
    assert _xml_escape("plain") == "plain"
