from pathlib import Path

import pytest

from dbpm.environment import resolve_deployment_policy
from dbpm.errors import DependencyError
from dbpm.resolver import create_multi_package_plan, version_satisfies
from dbpm.source import load_package_source


# ── tilde constraint tests ───────────────────────────────────────────────────

def test_tilde_satisfies_same_version():
    assert version_satisfies("1.2.3", "~1.2.3") is True


def test_tilde_satisfies_higher_patch():
    assert version_satisfies("1.2.9", "~1.2.3") is True


def test_tilde_does_not_satisfy_lower_patch():
    assert version_satisfies("1.2.2", "~1.2.3") is False


def test_tilde_does_not_satisfy_next_minor():
    assert version_satisfies("1.3.0", "~1.2.3") is False


def test_tilde_does_not_satisfy_different_major():
    assert version_satisfies("2.2.3", "~1.2.3") is False


def test_tilde_zero_patch_covers_full_minor():
    assert version_satisfies("1.2.0", "~1.2.0") is True
    assert version_satisfies("1.2.99", "~1.2.0") is True
    assert version_satisfies("1.3.0", "~1.2.0") is False


def test_tilde_invalid_base_raises():
    with pytest.raises(DependencyError):
        version_satisfies("1.2.3", "~1.2")


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
  upgrade: upgrade.sql
  validate: smoke.sql
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
        environment=resolve_deployment_policy(None),
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
        environment=resolve_deployment_policy(None),
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
            environment=resolve_deployment_policy(None),
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
            environment=resolve_deployment_policy(None),
        )


def test_multi_package_plan_supports_caret_dependency_constraint(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", version="1.2.3")
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "^1.0.0"))

    plan = create_multi_package_plan(
        mode="install",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_deployment_policy(None),
    )

    assert plan["execution_order"] == ["FIXTURE_BASE", "FIXTURE_CONSUMER"]


def test_multi_package_validate_runs_dependency_sources_as_validate(tmp_path: Path):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base")
    _write_package(consumer, name="fixture_consumer", dependency=("fixture_base", "1.0.0"))

    plan = create_multi_package_plan(
        mode="validate",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_deployment_policy(None),
        installed_states={
            "FIXTURE_BASE": {
                "application_name": "FIXTURE_BASE",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "abc",
            },
            "FIXTURE_CONSUMER": {
                "application_name": "FIXTURE_CONSUMER",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "def",
            },
        },
    )

    assert plan["execution_order"] == ["FIXTURE_BASE", "FIXTURE_CONSUMER"]
    assert [item["mode"] for item in plan["packages"]] == ["validate", "validate"]
    assert [item["execution"]["arguments"] for item in plan["packages"]] == [[], []]


def test_multi_package_upgrade_runs_newer_installed_dependency_sources_as_upgrade(
    tmp_path: Path,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", version="1.1.0")
    _write_package(consumer, name="fixture_consumer", version="1.1.0", dependency=("fixture_base", "^1.0.0"))

    plan = create_multi_package_plan(
        mode="upgrade",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_deployment_policy(None),
        installed_states={
            "FIXTURE_BASE": {
                "application_name": "FIXTURE_BASE",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "abc",
            },
            "FIXTURE_CONSUMER": {
                "application_name": "FIXTURE_CONSUMER",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "def",
            },
        },
    )

    assert plan["execution_order"] == ["FIXTURE_BASE", "FIXTURE_CONSUMER"]
    assert [item["mode"] for item in plan["packages"]] == ["upgrade", "upgrade"]


def test_multi_package_upgrade_skips_dependency_source_when_installed_version_matches(
    tmp_path: Path,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", version="1.1.0")
    _write_package(consumer, name="fixture_consumer", version="1.1.0", dependency=("fixture_base", "^1.0.0"))

    plan = create_multi_package_plan(
        mode="upgrade",
        source=load_package_source(str(consumer)),
        dependency_sources=[load_package_source(str(base))],
        environment=resolve_deployment_policy(None),
        installed_states={
            "FIXTURE_BASE": {
                "application_name": "FIXTURE_BASE",
                "version": "1.1.0",
                "deploy_status": "C",
                "deploy_commit_hash": "abc",
            },
            "FIXTURE_CONSUMER": {
                "application_name": "FIXTURE_CONSUMER",
                "version": "1.0.0",
                "deploy_status": "C",
                "deploy_commit_hash": "def",
            },
        },
    )

    assert plan["execution_order"] == ["FIXTURE_CONSUMER"]
    assert plan["satisfied_dependencies"][0]["application_name"] == "FIXTURE_BASE"


def test_multi_package_upgrade_fails_when_dependency_source_is_not_installed(
    tmp_path: Path,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base, name="fixture_base", version="1.1.0")
    _write_package(consumer, name="fixture_consumer", version="1.1.0", dependency=("fixture_base", "^1.0.0"))

    with pytest.raises(DependencyError, match="Cannot upgrade dependency FIXTURE_BASE"):
        create_multi_package_plan(
            mode="upgrade",
            source=load_package_source(str(consumer)),
            dependency_sources=[load_package_source(str(base))],
            environment=resolve_deployment_policy(None),
            installed_states={
                "FIXTURE_CONSUMER": {
                    "application_name": "FIXTURE_CONSUMER",
                    "version": "1.0.0",
                    "deploy_status": "C",
                    "deploy_commit_hash": "def",
                },
            },
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
            environment=resolve_deployment_policy(None),
        )
