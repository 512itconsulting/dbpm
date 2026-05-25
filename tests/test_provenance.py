from pathlib import Path
from unittest.mock import patch

from dbpm.provenance import UNKNOWN_COMMIT, resolve_provenance
from dbpm.source import load_package_source


def _write_manifest(path: Path) -> None:
    (path / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )


def test_artifact_metadata_wins_over_local_git(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package)
    meta = package / "META-INF"
    meta.mkdir()
    (meta / "demo-build.properties").write_text(
        "git.commit.id=1111111111111111111111111111111111111111\ngit.dirty=false\n",
        encoding="utf-8",
    )

    with patch("dbpm.provenance._git", return_value="2222222222222222222222222222222222222222"):
        provenance = resolve_provenance(load_package_source(str(package)))

    assert provenance.source == "artifact-metadata"
    assert provenance.commit == "1111111111111111111111111111111111111111"
    assert provenance.dirty is False


def test_unknown_provenance_uses_zero_commit(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package)

    with patch("dbpm.provenance._git", return_value=None):
        provenance = resolve_provenance(load_package_source(str(package)))

    assert provenance.source == "unknown"
    assert provenance.commit == UNKNOWN_COMMIT
    assert provenance.dirty is None


def test_local_git_dirty_detection(tmp_path: Path):
    package = tmp_path / "package"
    package.mkdir()
    _write_manifest(package)

    def fake_git(path: Path, *args: str) -> str | None:
        if args == ("rev-parse", "HEAD"):
            return "3333333333333333333333333333333333333333"
        if args == ("status", "--porcelain"):
            return " M dbpm.yaml"
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        return None

    with patch("dbpm.provenance._git", side_effect=fake_git):
        provenance = resolve_provenance(load_package_source(str(package)))

    assert provenance.source == "local-git"
    assert provenance.commit == "3333333333333333333333333333333333333333"
    assert provenance.dirty is True
    assert provenance.artifact["git.branch"] == "main"
