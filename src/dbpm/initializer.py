from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .errors import DbpmError


PACKAGE_DIRS = [
    "deployment_manifests",
    "docs",
    "examples",
    "helper_scripts",
    "metadata",
    "packages",
    "functions",
    "procedures",
    "tables",
    "tests",
    "types",
]

WORKSPACE_ROOT_DIRS = ["helper_scripts", "os"]

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

_ROOT_GITIGNORE = """\
# dbpm artifacts
dbpm-lock.json
*.dbpm.receipt.json

# SQL*Plus / SQLcl logs
*.log
*.lst
"""

_DEPLOYMENT_MANIFESTS_GITIGNORE = """\
*.log
*.lst
"""


def validate_package_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise DbpmError(
            f"Invalid package name {name!r}: must start with a lowercase letter "
            f"and contain only lowercase letters, digits, underscores, or hyphens"
        )


def init_package(
    root: Path,
    name: str,
    version: str,
    description: str,
    force: bool,
) -> list[Path]:
    _assert_empty_or_force(root, force)
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    _collect(_write_if_missing(root / "dbpm.yaml", _package_manifest(name, version, description)), created)
    _collect(_write_if_missing(root / "README.md", _readme(name, description)), created)
    _collect(_write_if_missing(root / "LICENSE", _license()), created)
    _collect(_write_if_missing(root / ".gitignore", _ROOT_GITIGNORE), created)
    created.extend(_scaffold_package_dirs(root))
    return created


def init_workspace(
    root: Path,
    package_names: list[str],
    force: bool,
) -> list[Path]:
    _assert_empty_or_force(root, force)
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    workspace_manifest_lines = ["workspace:", "  packages:"]
    for name in package_names:
        workspace_manifest_lines.append(f"    - database/{name}")
    workspace_manifest = "\n".join(workspace_manifest_lines) + "\n"

    _collect(_write_if_missing(root / "dbpm-workspace.yaml", workspace_manifest), created)
    _collect(_write_if_missing(root / "README.md", _readme(root.name, "")), created)
    _collect(_write_if_missing(root / "LICENSE", _license()), created)
    _collect(_write_if_missing(root / ".gitignore", _ROOT_GITIGNORE), created)

    for dir_name in WORKSPACE_ROOT_DIRS:
        d = root / dir_name
        d.mkdir(exist_ok=True)
        _collect(_write_if_missing(d / ".gitkeep", ""), created)

    database_dir = root / "database"
    database_dir.mkdir(exist_ok=True)

    for name in package_names:
        pkg_root = database_dir / name
        pkg_root.mkdir(exist_ok=True)
        _collect(
            _write_if_missing(
                pkg_root / "dbpm.yaml",
                _package_manifest(name, "0.1.0", ""),
            ),
            created,
        )
        created.extend(_scaffold_package_dirs(pkg_root))

    return created


def _scaffold_package_dirs(root: Path) -> list[Path]:
    created: list[Path] = []
    for dir_name in PACKAGE_DIRS:
        d = root / dir_name
        d.mkdir(exist_ok=True)
        if dir_name == "deployment_manifests":
            _collect(_write_if_missing(d / ".gitignore", _DEPLOYMENT_MANIFESTS_GITIGNORE), created)
        else:
            _collect(_write_if_missing(d / ".gitkeep", ""), created)
    return created


def _package_manifest(name: str, version: str, description: str) -> str:
    desc_line = f'  description: "{description}"' if description else '  description: ""'
    return (
        f"package:\n"
        f'  name: {name}\n'
        f'  version: "{version}"\n'
        f"{desc_line}\n"
        f"\n"
        f"database:\n"
        f"  platform: oracle\n"
        f"\n"
        f"scripts:\n"
        f"  install: deployment_manifests/deploy.sql\n"
        f"  upgrade: deployment_manifests/update.sql\n"
    )


def _readme(name: str, description: str) -> str:
    desc_section = f"\n{description}\n" if description else ""
    return (
        f"# {name}\n"
        f"{desc_section}\n"
        f"## Requirements\n"
        f"\n"
        f"- Oracle Database 19c or later\n"
        f"- dbpm\n"
        f"\n"
        f"## Installation\n"
        f"\n"
        f"```\n"
        f"dbpm install .\n"
        f"```\n"
    )


def _license() -> str:
    year = date.today().year
    return (
        f"Copyright (c) {year} <owner>\n"
        f"\n"
        f"License terms TBD.\n"
    )


def _assert_empty_or_force(root: Path, force: bool) -> None:
    if force or not root.exists():
        return
    contents = list(root.iterdir())
    if contents:
        raise DbpmError(
            f"Directory is not empty: {root}\n"
            f"Use --force to initialize anyway (existing files will not be overwritten)"
        )


def _write_if_missing(path: Path, content: str) -> Path | None:
    if path.exists():
        return None
    path.write_text(content, encoding="utf-8")
    return path


def _collect(path: Path | None, lst: list[Path]) -> None:
    if path is not None:
        lst.append(path)
