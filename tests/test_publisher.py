from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dbpm.environment import resolve_environment
from dbpm.errors import PublishError
from dbpm.manifest import Dependency, PackageManifest, PublishConfig, ScriptSet
import urllib.error
from dbpm.planner import create_plan
from dbpm.provenance import resolve_provenance

from dbpm.publisher import (
    PUBLISH_RECEIPT_NAME,
    PublishReceipt,
    _build_updated_metadata,
    _fetch_text_or_none,
    _parse_publish_target,
    _xml_escape,
    build_artifact,
    create_publish_receipt,
    generate_pom,
    resolve_signing_key_fingerprint,
    sign_artifact,
    write_publish_receipt,
)
from dbpm.source import load_package_source


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


def _git_metadata(
    *,
    commit: str = "abc123abc123abc123abc123abc123abc123abcd",
    abbrev: str = "abc123a",
    branch: str = "main",
    dirty: str = "false",
) -> dict[str, str]:
    return {
        "git.commit.id": commit,
        "git.commit.id.abbrev": abbrev,
        "git.branch": branch,
        "git.dirty": dirty,
    }


def _parse_properties(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        key, value = raw_line.split("=", 1)
        values[key] = value
    return values


def _write_installable_package(tmp_path: Path) -> Path:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: utl_interval
  version: "1.2.3"

core:
  minimum_version: "3.0.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )
    (package / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    return package


# ---------------------------------------------------------------------------
# build_artifact
# ---------------------------------------------------------------------------


def test_build_artifact_creates_zip(tmp_path: Path, manifest: PackageManifest, publish_config: PublishConfig):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")
    (pkg / "deploy.sql").write_text("PROMPT deploy;\n")

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata()):
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

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata(commit="")):
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

    with patch(
        "dbpm.publisher._git_metadata",
        return_value=_git_metadata(
            commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            abbrev="deadbee",
            branch="main",
            dirty="true",
        ),
    ):
        artifact_path = build_artifact(pkg, manifest, publish_config)

    with zipfile.ZipFile(artifact_path) as archive:
        props = archive.read("utl_interval-1.2.3/META-INF/utl_interval-build.properties").decode()
    parsed = _parse_properties(props)

    assert parsed["artifact.groupId"] == "com.example.database"
    assert parsed["artifact.artifactId"] == "utl_interval"
    assert parsed["artifact.version"] == "1.2.3"
    assert parsed["artifact.extension"] == "zip"
    assert parsed["build.version"] == "1.2.3"
    assert parsed["build.source"] == "dbpm"
    assert parsed["build.time"]
    assert parsed["git.commit.id"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert parsed["git.commit.id.abbrev"] == "deadbee"
    assert parsed["git.branch"] == "main"
    assert parsed["git.dirty"] == "true"


def test_build_artifact_metadata_uses_publish_config_override(
    tmp_path: Path,
    manifest: PackageManifest,
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")
    config = PublishConfig(group="com.override.database", artifact_id="core")

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata()):
        artifact_path = build_artifact(pkg, manifest, config)

    with zipfile.ZipFile(artifact_path) as archive:
        props = archive.read("core-1.2.3/META-INF/core-build.properties").decode()
    parsed = _parse_properties(props)

    assert artifact_path.name == "core-1.2.3.zip"
    assert parsed["artifact.groupId"] == "com.override.database"
    assert parsed["artifact.artifactId"] == "core"
    assert parsed["artifact.version"] == "1.2.3"


def test_build_artifact_honors_dbpmignore(
    tmp_path: Path,
    manifest: PackageManifest,
    publish_config: PublishConfig,
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")
    (pkg / "deploy.sql").write_text("PROMPT deploy;\n")
    (pkg / ".dbpmignore").write_text("pom.xml\nassembly/\n")
    (pkg / "pom.xml").write_text("<project />\n")
    (pkg / "assembly").mkdir()
    (pkg / "assembly" / "package.xml").write_text("ignored\n")

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata()):
        artifact_path = build_artifact(pkg, manifest, publish_config)

    with zipfile.ZipFile(artifact_path) as archive:
        names = archive.namelist()

    assert "utl_interval-1.2.3/pom.xml" not in names
    assert "utl_interval-1.2.3/assembly/package.xml" not in names
    assert "utl_interval-1.2.3/.dbpmignore" in names


def test_build_artifact_excludes_default_publish_receipt(
    tmp_path: Path, manifest: PackageManifest, publish_config: PublishConfig
):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "dbpm.yaml").write_text("package:\n  name: utl_interval\n  version: 1.2.3\n")
    (pkg / PUBLISH_RECEIPT_NAME).write_text('{"secret": false}\n')

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata()):
        artifact_path = build_artifact(pkg, manifest, publish_config)

    with zipfile.ZipFile(artifact_path) as archive:
        assert not any(name.endswith(PUBLISH_RECEIPT_NAME) for name in archive.namelist())


def test_create_and_write_publish_receipt(
    tmp_path: Path, manifest: PackageManifest, publish_config: PublishConfig
):
    receipt = create_publish_receipt(
        manifest=manifest,
        publish_config=publish_config,
        target="gh-maven:acme/repo",
        receipt=PublishReceipt(
            artifact_url="https://repo.example/utl_interval-1.2.3.zip",
            checksum="a" * 64,
            signature_url="https://repo.example/utl_interval-1.2.3.zip.asc",
        ),
        publisher_key_fingerprint="FINGERPRINT",
        published_at="2026-06-04T12:00:00Z",
    )
    output = tmp_path / "receipt.json"

    write_publish_receipt(receipt, output)

    assert receipt["schema_version"] == "dbpm.publish-receipt.v1"
    assert receipt["artifact"]["checksum"] == "sha256:" + "a" * 64
    assert "token" not in output.read_text(encoding="utf-8").lower()


def test_resolve_signing_key_fingerprint_uses_primary_secret_key(monkeypatch):
    result = MagicMock(
        returncode=0,
        stdout=(
            "sec:u:255:22:KEYID:0:0::::::\n"
            "fpr:::::::::PRIMARYFINGERPRINT:\n"
            "ssb:u:255:18:SUBKEY:0:0::::::\n"
            "fpr:::::::::SUBKEYFINGERPRINT:\n"
        ),
        stderr="",
    )
    monkeypatch.setattr("dbpm.publisher.subprocess.run", lambda *args, **kwargs: result)

    assert resolve_signing_key_fingerprint("signing@example.test") == "PRIMARYFINGERPRINT"


def test_resolve_signing_key_fingerprint_rejects_ambiguous_selector(monkeypatch):
    result = MagicMock(
        returncode=0,
        stdout=(
            "sec:u:255:22:ONE:0:0::::::\nfpr:::::::::FIRST:\n"
            "sec:u:255:22:TWO:0:0::::::\nfpr:::::::::SECOND:\n"
        ),
        stderr="",
    )
    monkeypatch.setattr("dbpm.publisher.subprocess.run", lambda *args, **kwargs: result)

    with pytest.raises(PublishError, match="ambiguous"):
        resolve_signing_key_fingerprint("shared@example.test")


def test_dbpm_built_zip_populates_plan_artifact_provenance(tmp_path: Path):
    package = _write_installable_package(tmp_path)
    manifest = PackageManifest(
        name="utl_interval",
        version="1.2.3",
        application_name="UTL_INTERVAL",
        description=None,
        vendor=None,
        license=None,
        database_platform="oracle",
        database_minimum_version=None,
        core_minimum_version="3.0.0",
        dependencies=(),
        scripts=ScriptSet(install="deploy.sql"),
    )
    config = PublishConfig(group="com.example.database", artifact_id="utl_interval")

    with patch(
        "dbpm.publisher._git_metadata",
        return_value=_git_metadata(
            commit="1234567890123456789012345678901234567890",
            abbrev="1234567",
            branch="main",
            dirty="false",
        ),
    ):
        artifact_path = build_artifact(package, manifest, config)

    source = load_package_source(str(artifact_path))
    provenance = resolve_provenance(source)
    plan = create_plan(
        mode="install",
        source=source,
        provenance=provenance,
        environment=resolve_environment("development"),
    )

    payload = plan["pre_actions"][0]["payload"]
    assert payload["artifact_group_id"] == "com.example.database"
    assert payload["artifact_id"] == "utl_interval"
    assert payload["artifact_version"] == "1.2.3"
    assert payload["artifact_extension"] == "zip"
    assert payload["package_coordinate"] == "com.example.database:utl_interval:1.2.3"
    assert payload["build_metadata_json"]["artifact"]["build.source"] == "dbpm"
    assert provenance.dirty is False


def test_dbpm_built_github_maven_zip_populates_plan_artifact_provenance(
    tmp_path: Path,
    monkeypatch,
):
    package = _write_installable_package(tmp_path)
    manifest = PackageManifest(
        name="utl_interval",
        version="1.2.3",
        application_name="UTL_INTERVAL",
        description=None,
        vendor=None,
        license=None,
        database_platform="oracle",
        database_minimum_version=None,
        core_minimum_version="3.0.0",
        dependencies=(),
        scripts=ScriptSet(install="deploy.sql"),
    )
    config = PublishConfig(group="com.example.database", artifact_id="utl_interval")

    with patch("dbpm.publisher._git_metadata", return_value=_git_metadata()):
        artifact_path = build_artifact(package, manifest, config)

    def fake_download(url: str, destination: Path) -> None:
        destination.write_bytes(artifact_path.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    source = load_package_source(
        "gh-maven:acme/core:com.example.database:utl_interval:1.2.3"
    )
    provenance = resolve_provenance(source)
    plan = create_plan(
        mode="install",
        source=source,
        provenance=provenance,
        environment=resolve_environment("development"),
    )

    payload = plan["pre_actions"][0]["payload"]
    assert payload["artifact_group_id"] == "com.example.database"
    assert payload["artifact_id"] == "utl_interval"
    assert payload["artifact_version"] == "1.2.3"
    assert payload["package_coordinate"] == "com.example.database:utl_interval:1.2.3"
    assert payload["artifact_uri"] == (
        "https://maven.pkg.github.com/acme/core/"
        "com/example/database/utl_interval/1.2.3/utl_interval-1.2.3.zip"
    )


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


def test_generate_pom_excludes_core_dependency(manifest: PackageManifest, publish_config: PublishConfig):
    pom = generate_pom(manifest, publish_config)

    assert "<artifactId>core</artifactId>" not in pom


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


# ---------------------------------------------------------------------------
# _fetch_text_or_none
# ---------------------------------------------------------------------------


def test_fetch_text_or_none_returns_none_on_404(monkeypatch):
    def fake_urlopen(req):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert _fetch_text_or_none("http://example.com/file.xml", None) is None


def test_fetch_text_or_none_raises_on_non_404(monkeypatch):
    def fake_urlopen(req):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(PublishError, match="403"):
        _fetch_text_or_none("http://example.com/file.xml", None)


# ---------------------------------------------------------------------------
# _build_updated_metadata
# ---------------------------------------------------------------------------


def test_build_updated_metadata_starts_fresh_on_404(monkeypatch):
    monkeypatch.setattr("dbpm.publisher._fetch_text_or_none", lambda *a, **kw: None)
    result = _build_updated_metadata("http://x/maven-metadata.xml", "com.example", "pkg", "1.0.0", None)
    xml = result.decode("utf-8")
    assert "<version>1.0.0</version>" in xml
    assert xml.count("<version>") == 1


def test_build_updated_metadata_appends_to_existing(monkeypatch):
    existing = (
        '<?xml version="1.0"?><metadata>'
        "<versioning><versions>"
        "<version>1.0.0</version>"
        "</versions></versioning>"
        "</metadata>"
    )
    monkeypatch.setattr("dbpm.publisher._fetch_text_or_none", lambda *a, **kw: existing)
    result = _build_updated_metadata("http://x/maven-metadata.xml", "com.example", "pkg", "1.1.0", None)
    xml = result.decode("utf-8")
    assert "<version>1.0.0</version>" in xml
    assert "<version>1.1.0</version>" in xml


def test_build_updated_metadata_raises_on_fetch_error(monkeypatch):
    def fail(*a, **kw):
        raise PublishError("HTTP 503 Service Unavailable")

    monkeypatch.setattr("dbpm.publisher._fetch_text_or_none", fail)
    with pytest.raises(PublishError, match="503"):
        _build_updated_metadata("http://x/maven-metadata.xml", "com.example", "pkg", "1.0.0", None)


def test_build_updated_metadata_raises_on_parse_error(monkeypatch):
    monkeypatch.setattr("dbpm.publisher._fetch_text_or_none", lambda *a, **kw: "not xml {{{{")
    with pytest.raises(PublishError, match="parse"):
        _build_updated_metadata("http://x/maven-metadata.xml", "com.example", "pkg", "1.0.0", None)
