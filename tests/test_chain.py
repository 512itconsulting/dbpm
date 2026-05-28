from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm.chain import ChainError, resolve_upgrade_chain
from dbpm.source import load_package_source


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))


def _make_zip(path: Path, *, name: str, version: str, upgrade_from: str | None = None) -> None:
    upgrade_from_line = f"  upgrade_from: \"{upgrade_from}\"\n" if upgrade_from else ""
    manifest = (
        f"package:\n  name: {name}\n  version: \"{version}\"\n"
        f"scripts:\n  upgrade: upgrade.sql\n{upgrade_from_line}"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{name}/dbpm.yaml", manifest)
        archive.writestr(f"{name}/upgrade.sql", "PROMPT upgrade\n")


def _fake_download(fixture: Path):
    def _download(url: str, destination: Path) -> None:
        destination.write_bytes(fixture.read_bytes())
    return _download


# ── direct upgrade cases ────────────────────────────────────────────────────


def test_upgrade_from_satisfied_returns_direct(tmp_path):
    archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(archive, name="pkg", version="1.3.0", upgrade_from="^1.2.0")
    source = load_package_source(str(archive))

    result = resolve_upgrade_chain(source, str(archive), installed_version="1.2.5")

    assert result == [source]


def test_upgrade_from_exact_match_returns_direct(tmp_path):
    archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(archive, name="pkg", version="1.3.0", upgrade_from="1.2.0")
    source = load_package_source(str(archive))

    result = resolve_upgrade_chain(source, str(archive), installed_version="1.2.0")

    assert result == [source]


# ── local source — no upgrade_from means direct ────────────────────────────


def test_no_upgrade_from_local_source_returns_direct(tmp_path):
    archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(archive, name="pkg", version="1.3.0")
    source = load_package_source(str(archive))

    result = resolve_upgrade_chain(source, str(archive), installed_version="1.0.0")

    assert result == [source]


def test_upgrade_from_not_satisfied_local_raises_chain_error(tmp_path):
    archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(archive, name="pkg", version="1.3.0", upgrade_from="^1.2.0")
    source = load_package_source(str(archive))

    with pytest.raises(ChainError, match="not a Maven coordinate"):
        resolve_upgrade_chain(source, str(archive), installed_version="1.0.0")


# ── Maven chain resolution ──────────────────────────────────────────────────


def _maven_metadata(versions: list[str]) -> str:
    version_tags = "\n".join(f"      <version>{v}</version>" for v in versions)
    return f"""<metadata>
  <versioning>
    <versions>
{version_tags}
    </versions>
  </versioning>
</metadata>"""


def _version_from_url(url: str) -> str:
    """Extract version string from a Maven artifact URL."""
    import re
    match = re.search(r"/(\d+\.\d+\.\d+)/", url)
    return match.group(1) if match else "1.0.0"


def _version_aware_download(tmp_path: Path, name: str):
    def _download(url: str, destination: Path) -> None:
        version = _version_from_url(url)
        buf = tmp_path / f"_buf_{version}.zip"
        _make_zip(buf, name=name, version=version)
        destination.write_bytes(buf.read_bytes())
    return _download


def test_maven_no_upgrade_from_builds_full_chain(tmp_path, monkeypatch):
    monkeypatch.setattr("dbpm.source._download", _version_aware_download(tmp_path, "pkg"))
    monkeypatch.setattr("dbpm.chain._maven_version_list", lambda repo, coord: ["1.0.0", "1.1.0", "1.2.0", "1.3.0"])

    target_archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(target_archive, name="pkg", version="1.3.0")
    target_source = load_package_source(str(target_archive))

    raw = "gh-maven:rsantmyer/pkg:com.example:pkg:1.3.0"
    result = resolve_upgrade_chain(target_source, raw, installed_version="1.0.0")

    assert len(result) == 3
    assert result[-1] is target_source
    assert [s.manifest.version for s in result] == ["1.1.0", "1.2.0", "1.3.0"]


def test_maven_upgrade_from_not_satisfied_builds_chain(tmp_path, monkeypatch):
    monkeypatch.setattr("dbpm.source._download", _version_aware_download(tmp_path, "pkg"))
    monkeypatch.setattr("dbpm.chain._maven_version_list", lambda repo, coord: ["1.0.0", "1.1.0", "1.2.0", "1.3.0"])

    target_archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(target_archive, name="pkg", version="1.3.0", upgrade_from="^1.2.0")
    target_source = load_package_source(str(target_archive))

    raw = "gh-maven:rsantmyer/pkg:com.example:pkg:1.3.0"
    result = resolve_upgrade_chain(target_source, raw, installed_version="1.0.0")

    assert len(result) == 3
    assert [s.manifest.version for s in result] == ["1.1.0", "1.2.0", "1.3.0"]


def test_maven_no_intermediate_versions_returns_direct(tmp_path, monkeypatch):
    monkeypatch.setattr("dbpm.chain._maven_version_list", lambda repo, coord: ["1.0.0", "1.3.0"])

    archive = tmp_path / "pkg-1.3.0.zip"
    _make_zip(archive, name="pkg", version="1.3.0")
    source = load_package_source(str(archive))

    raw = "gh-maven:rsantmyer/pkg:com.example:pkg:1.3.0"
    result = resolve_upgrade_chain(source, raw, installed_version="1.0.0")

    assert result == [source]


def test_source_at_version_github_maven(tmp_path, monkeypatch):
    from dbpm.source import _source_at_version

    result = _source_at_version(
        "gh-maven:rsantmyer/pkg:com.example:pkg:1.3.0",
        "1.1.0",
    )

    assert result == "gh-maven:rsantmyer/pkg:com.example:pkg:1.1.0"


def test_source_at_version_generic_maven():
    from dbpm.source import _source_at_version

    result = _source_at_version(
        "maven:https://repo.example.test/releases::com.example:pkg:1.3.0",
        "1.1.0",
    )

    assert result == "maven:https://repo.example.test/releases::com.example:pkg:1.1.0"


def test_maven_version_list_parses_metadata(tmp_path, monkeypatch):
    from dbpm.source import _maven_version_list

    monkeypatch.setattr(
        "dbpm.source._download_text",
        lambda url: _maven_metadata(["1.0.0", "1.1.0", "1.2.0"]),
    )

    result = _maven_version_list(
        "https://maven.pkg.github.com/rsantmyer/pkg/",
        {"group": "com.example", "artifact": "pkg"},
    )

    assert result == ["1.0.0", "1.1.0", "1.2.0"]
