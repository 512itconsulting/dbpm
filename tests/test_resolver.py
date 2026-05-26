from pathlib import Path

import pytest

from dbpm.environment import resolve_environment
from dbpm.errors import DependencyError
from dbpm.resolver import create_multi_package_plan
from dbpm.source import load_package_source


def _write_package(
    path: Path,
    *,
    name: str,
    version: str = "1.0.0",
    dependency: tuple[str, str] | None = None,
) -> None:
    path.mkdir()
    dependencies = ""
    if dependency:
        dependencies = f"""
dependencies:
  - name: {dependency[0]}
    version: "{dependency[1]}"
"""
    (path / "dbpm.yaml").write_text(
        f"""
package:
  name: {name}
  version: "{version}"

scripts:
  install: deploy.sql
{dependencies}
""",
        encoding="utf-8",
    )


def test_multi_package_plan_orders_dependencies_first(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base")
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    plan = create_multi_package_plan(
        mode="install",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_environment("development"),
    )

    assert plan["schema_version"] == "dbpm.multi-plan.v0"
    assert plan["execution_order"] == ["FIXTURE_BASE", "FIXTURE_CONSUMER"]
    assert [item["mode"] for item in plan["packages"]] == ["install", "install"]


def test_multi_package_plan_skips_satisfied_installed_dependency(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base")
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    plan = create_multi_package_plan(
        mode="install",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_environment("development"),
        installed_states={
            "FIXTURE_BASE": {
                "application_name": "FIXTURE_BASE",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "abc",
            }
        },
    )

    assert plan["execution_order"] == ["FIXTURE_CONSUMER"]
    assert plan["satisfied_dependencies"][0]["application_name"] == "FIXTURE_BASE"


def test_multi_package_plan_fails_for_missing_dependency_source(tmp_path: Path):
    consumer = tmp_path / "consumer"
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    with pytest.raises(DependencyError, match="Missing dependency source"):
        create_multi_package_plan(
            mode="install",
            source=load_package_source(str(consumer)),
            dependency_sources=[],
            environment=resolve_environment("development"),
        )


def test_multi_package_plan_fails_for_version_mismatch(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", version="1.0.1")
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    with pytest.raises(DependencyError, match="does not satisfy required version"):
        create_multi_package_plan(
            mode="install",
            source=load_package_source(str(consumer)),
            dependency_sources=[load_package_source(str(base))],
            environment=resolve_environment("development"),
        )


def test_multi_package_plan_detects_cycles(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", dependency=("fixture_consumer", "1.0.0"))
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    with pytest.raises(DependencyError, match="Dependency cycle detected"):
        create_multi_package_plan(
            mode="install",
            source=load_package_source(str(consumer)),
            dependency_sources=[load_package_source(str(base))],
            environment=resolve_environment("development"),
        )
