from __future__ import annotations

from pathlib import Path

import pytest

from dbpm.errors import WorkspaceError
from dbpm.workspace import load_workspace, select_workspace_package


def _write_package(path: Path, name: str = "demo", version: str = "0.1.0") -> None:
    path.mkdir(parents=True)
    (path / "dbpm.yaml").write_text(
        f"""
package:
  name: {name}
  version: "{version}"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )


def _write_workspace(path: Path, package_paths: list[str]) -> None:
    entries = "\n".join(f"    - {item}" for item in package_paths)
    (path / "dbpm-workspace.yaml").write_text(
        f"""
workspace:
  packages:
{entries}
""",
        encoding="utf-8",
    )


def test_load_workspace_reads_nested_package_roots(tmp_path: Path):
    _write_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    workspace = load_workspace(tmp_path)

    assert workspace.root == tmp_path
    assert [package.relative_path for package in workspace.packages] == [
        "database/utl_interval",
        "database/simple_scheduler",
    ]
    assert workspace.packages[1].manifest.application_name == "SIMPLE_SCHEDULER"


def test_load_workspace_rejects_top_level_packages_shape(tmp_path: Path):
    (tmp_path / "dbpm-workspace.yaml").write_text(
        """
packages:
  - database/demo
""",
        encoding="utf-8",
    )

    with pytest.raises(WorkspaceError, match="workspace` mapping"):
        load_workspace(tmp_path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("workspace: {}\n", "workspace.packages"),
        ("workspace:\n  packages: database/demo\n", "workspace.packages"),
        ("workspace:\n  packages: []\n", "at least one package"),
    ],
)
def test_load_workspace_rejects_invalid_package_list(tmp_path: Path, content: str, message: str):
    (tmp_path / "dbpm-workspace.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(WorkspaceError, match=message):
        load_workspace(tmp_path)


@pytest.mark.parametrize(
    ("package_path", "message"),
    [
        ("/absolute/path", "must be relative"),
        ("../demo", "must not contain"),
        ("database/../demo", "must not contain"),
    ],
)
def test_load_workspace_rejects_unsafe_package_paths(
    tmp_path: Path,
    package_path: str,
    message: str,
):
    _write_workspace(tmp_path, [package_path])

    with pytest.raises(WorkspaceError, match=message):
        load_workspace(tmp_path)


def test_load_workspace_rejects_duplicate_roots(tmp_path: Path):
    _write_package(tmp_path / "database" / "demo")
    _write_workspace(tmp_path, ["database/demo", "database/demo"])

    with pytest.raises(WorkspaceError, match="Duplicate"):
        load_workspace(tmp_path)


def test_load_workspace_rejects_missing_package_directory(tmp_path: Path):
    _write_workspace(tmp_path, ["database/demo"])

    with pytest.raises(WorkspaceError, match="does not exist"):
        load_workspace(tmp_path)


def test_load_workspace_rejects_package_without_manifest(tmp_path: Path):
    (tmp_path / "database" / "demo").mkdir(parents=True)
    _write_workspace(tmp_path, ["database/demo"])

    with pytest.raises(WorkspaceError, match="no dbpm manifest"):
        load_workspace(tmp_path)


def test_select_workspace_package_matches_name_and_application(tmp_path: Path):
    _write_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace(tmp_path, ["database/simple_scheduler"])
    workspace = load_workspace(tmp_path)

    assert select_workspace_package(workspace, "simple_scheduler").manifest.name == "simple_scheduler"
    assert select_workspace_package(workspace, "SIMPLE_SCHEDULER").manifest.name == "simple_scheduler"
