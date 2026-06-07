from __future__ import annotations

from pathlib import Path

import pytest

from dbpm.cli import main
from dbpm.errors import DbpmError
from dbpm.initializer import (
    PACKAGE_DIRS,
    init_package,
    init_workspace,
    validate_package_name,
)


# ---------------------------------------------------------------------------
# validate_package_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["my_package", "core", "utl-bs-numeric", "a1b2"])
def test_validate_package_name_accepts_valid(name: str):
    validate_package_name(name)  # must not raise


@pytest.mark.parametrize("name", ["BadName", "123start", "_leading", "", "-dash"])
def test_validate_package_name_rejects_invalid(name: str):
    with pytest.raises(DbpmError, match="Invalid package name"):
        validate_package_name(name)


# ---------------------------------------------------------------------------
# init_package — directory structure
# ---------------------------------------------------------------------------


def test_init_package_creates_all_dirs(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    for dir_name in PACKAGE_DIRS:
        assert (tmp_path / dir_name).is_dir(), f"missing directory: {dir_name}"


def test_init_package_gitkeep_in_non_manifest_dirs(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    for dir_name in PACKAGE_DIRS:
        if dir_name == "deployment_manifests":
            continue
        assert (tmp_path / dir_name / ".gitkeep").is_file(), f"missing .gitkeep in {dir_name}"


def test_init_package_deployment_manifests_gitignore(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    gitignore = (tmp_path / "deployment_manifests" / ".gitignore").read_text(encoding="utf-8")
    assert "*.log" in gitignore
    assert "*.lst" in gitignore


def test_init_package_root_gitignore(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "*.log" in gitignore
    assert "dbpm-lock.json" in gitignore


# ---------------------------------------------------------------------------
# init_package — manifest
# ---------------------------------------------------------------------------


def test_init_package_creates_manifest(tmp_path: Path):
    init_package(tmp_path, name="my_pkg", version="1.2.3", description="A test package", force=False)
    text = (tmp_path / "dbpm.yaml").read_text(encoding="utf-8")
    assert "name: my_pkg" in text
    assert '"1.2.3"' in text
    assert "A test package" in text
    assert "deployment_manifests/deploy.sql" in text
    assert "deployment_manifests/update.sql" in text


def test_init_package_manifest_no_description(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    text = (tmp_path / "dbpm.yaml").read_text(encoding="utf-8")
    assert 'description: ""' in text


# ---------------------------------------------------------------------------
# init_package — README and LICENSE
# ---------------------------------------------------------------------------


def test_init_package_creates_readme(tmp_path: Path):
    init_package(tmp_path, name="my_pkg", version="0.1.0", description="Hello world", force=False)
    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "my_pkg" in text
    assert "Hello world" in text


def test_init_package_creates_license(tmp_path: Path):
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    text = (tmp_path / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright" in text


# ---------------------------------------------------------------------------
# init_package — default name from dirname
# ---------------------------------------------------------------------------


def test_init_package_default_name_inferred_from_cli(tmp_path: Path):
    pkg_dir = tmp_path / "my_project"
    pkg_dir.mkdir()
    result = main(["init", "package", str(pkg_dir)])
    assert result == 0
    text = (pkg_dir / "dbpm.yaml").read_text(encoding="utf-8")
    assert "name: my_project" in text


# ---------------------------------------------------------------------------
# init_package — non-empty guard
# ---------------------------------------------------------------------------


def test_init_package_rejects_nonempty_without_force(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DbpmError, match="not empty"):
        init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)


def test_init_package_force_succeeds_in_nonempty(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("keep me", encoding="utf-8")
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=True)
    assert (tmp_path / "dbpm.yaml").is_file()
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "keep me"


def test_init_package_force_does_not_overwrite_existing_manifest(tmp_path: Path):
    original = "# original\n"
    (tmp_path / "dbpm.yaml").write_text(original, encoding="utf-8")
    init_package(tmp_path, name="demo", version="0.1.0", description="", force=True)
    assert (tmp_path / "dbpm.yaml").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# init_package — returns created paths
# ---------------------------------------------------------------------------


def test_init_package_returns_created_paths(tmp_path: Path):
    created = init_package(tmp_path, name="demo", version="0.1.0", description="", force=False)
    assert len(created) > 0
    for path in created:
        assert path.exists()


# ---------------------------------------------------------------------------
# init_workspace — root structure
# ---------------------------------------------------------------------------


def test_init_workspace_creates_root_dirs(tmp_path: Path):
    init_workspace(tmp_path, package_names=["my_package"], force=False)
    assert (tmp_path / "helper_scripts").is_dir()
    assert (tmp_path / "os").is_dir()
    assert (tmp_path / "database").is_dir()


def test_init_workspace_creates_manifest(tmp_path: Path):
    init_workspace(tmp_path, package_names=["billing", "orders"], force=False)
    text = (tmp_path / "dbpm-workspace.yaml").read_text(encoding="utf-8")
    assert "database/billing" in text
    assert "database/orders" in text


def test_init_workspace_root_gitignore(tmp_path: Path):
    init_workspace(tmp_path, package_names=["my_package"], force=False)
    assert (tmp_path / ".gitignore").is_file()


def test_init_workspace_root_readme(tmp_path: Path):
    init_workspace(tmp_path, package_names=["my_package"], force=False)
    assert (tmp_path / "README.md").is_file()


def test_init_workspace_root_license(tmp_path: Path):
    init_workspace(tmp_path, package_names=["my_package"], force=False)
    assert (tmp_path / "LICENSE").is_file()


# ---------------------------------------------------------------------------
# init_workspace — default package
# ---------------------------------------------------------------------------


def test_init_workspace_default_package_via_cli(tmp_path: Path):
    result = main(["init", "workspace", str(tmp_path)])
    assert result == 0
    assert (tmp_path / "database" / "my_package").is_dir()
    text = (tmp_path / "dbpm-workspace.yaml").read_text(encoding="utf-8")
    assert "database/my_package" in text


# ---------------------------------------------------------------------------
# init_workspace — package scaffolding
# ---------------------------------------------------------------------------


def test_init_workspace_package_has_manifest(tmp_path: Path):
    init_workspace(tmp_path, package_names=["billing"], force=False)
    text = (tmp_path / "database" / "billing" / "dbpm.yaml").read_text(encoding="utf-8")
    assert "name: billing" in text


def test_init_workspace_multiple_packages(tmp_path: Path):
    init_workspace(tmp_path, package_names=["billing", "orders"], force=False)
    assert (tmp_path / "database" / "billing" / "dbpm.yaml").is_file()
    assert (tmp_path / "database" / "orders" / "dbpm.yaml").is_file()


def test_init_workspace_package_dirs_scaffolded(tmp_path: Path):
    init_workspace(tmp_path, package_names=["my_package"], force=False)
    pkg_root = tmp_path / "database" / "my_package"
    for dir_name in PACKAGE_DIRS:
        assert (pkg_root / dir_name).is_dir(), f"missing dir in workspace package: {dir_name}"


def test_init_workspace_rejects_nonempty_without_force(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DbpmError, match="not empty"):
        init_workspace(tmp_path, package_names=["my_package"], force=False)


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_init_package(tmp_path: Path):
    pkg_dir = tmp_path / "new_pkg"
    pkg_dir.mkdir()
    result = main(["init", "package", str(pkg_dir), "--name", "new_pkg", "--version", "2.0.0"])
    assert result == 0
    assert (pkg_dir / "dbpm.yaml").is_file()


def test_cli_init_package_invalid_name(tmp_path: Path):
    # main() catches DbpmError and returns exit code 2
    result = main(["init", "package", str(tmp_path), "--name", "BadName"])
    assert result == 2


def test_cli_init_workspace_named_packages(tmp_path: Path):
    result = main(["init", "workspace", str(tmp_path), "--package", "billing", "--package", "orders"])
    assert result == 0
    text = (tmp_path / "dbpm-workspace.yaml").read_text(encoding="utf-8")
    assert "database/billing" in text
    assert "database/orders" in text


def test_cli_init_workspace_invalid_package_name(tmp_path: Path):
    # main() catches DbpmError and returns exit code 2
    result = main(["init", "workspace", str(tmp_path), "--package", "BadName"])
    assert result == 2
