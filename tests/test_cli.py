import json
from pathlib import Path

import pytest

from dbpm import cli
from dbpm.db import ApplicationState, SqlResult


def _write_package(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

core:
  minimum_version: "3.0.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  validate: Tests/smoke_test.sql
""",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _no_reverse_dependencies(monkeypatch):
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: [])


def test_plan_prints_json(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["plan", str(package), "--env", "development"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.plan.v0"
    assert output["package"]["application_name"] == "DEMO"


def test_plan_with_dependency_source_prints_multi_package_plan(tmp_path: Path, capsys):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base)
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "0.1.0"

dependencies:
  - name: demo
    version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "plan",
                str(consumer),
                "--dependency-source",
                str(base),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.multi-plan.v0"
    assert output["execution_order"] == ["DEMO", "CONSUMER"]


def test_plan_with_missing_dependency_source_fails(tmp_path: Path, capsys):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "0.1.0"

dependencies:
  - name: demo
    version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )

    assert cli.main(["plan", str(consumer)]) == 2

    assert "Missing dependency source for CONSUMER: DEMO 0.1.0" in capsys.readouterr().err


def test_lock_writes_lockfile(tmp_path: Path, capsys):
    package = tmp_path / "package"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_package(package)

    assert cli.main(["lock", str(package), "--output", str(lockfile)]) == 0

    output = json.loads(lockfile.read_text(encoding="utf-8"))
    assert output["schema_version"] == "dbpm.lock.v0"
    assert output["execution_order"] == ["DEMO"]
    assert f"WROTE_LOCKFILE={lockfile}" in capsys.readouterr().out


def test_lock_check_rejects_mismatch(tmp_path: Path, capsys):
    package = tmp_path / "package"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_package(package)

    assert cli.main(["lock", str(package), "--output", str(lockfile)]) == 0
    data = json.loads(lockfile.read_text(encoding="utf-8"))
    data["packages"][0]["version"] = "9.9.9"
    lockfile.write_text(json.dumps(data), encoding="utf-8")

    assert cli.main(["lock", str(package), "--output", str(lockfile), "--check"]) == 2

    assert "DEMO version mismatch" in capsys.readouterr().err


def test_lock_check_db_reconciles_installed_state(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_package(package)
    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["lock", str(package), "--output", str(lockfile)]) == 0
    locked = json.loads(lockfile.read_text(encoding="utf-8"))["packages"][0]
    monkeypatch.setattr(
        cli,
        "get_deployment_provenance",
        lambda **kwargs: {
            "major_version": 0,
            "minor_version": 1,
            "patch_version": 0,
            "artifact_uri": locked["artifact"]["uri"],
            "artifact_checksum": locked["artifact"]["checksum"],
            "artifact_checksum_alg": locked["artifact"]["checksum_alg"],
            "artifact_file_name": locked["artifact"]["file_name"],
            "artifact_repository_type": locked["artifact"]["repository_type"],
            "artifact_group_id": locked["artifact"]["group_id"],
            "artifact_id": locked["artifact"]["artifact_id"],
            "artifact_version": locked["artifact"]["artifact_version"],
            "artifact_classifier": locked["artifact"]["classifier"],
            "artifact_extension": locked["artifact"]["extension"],
            "package_coordinate": locked["artifact"]["coordinate"],
            "source_repository_url": locked["provenance"]["source_repository_url"],
            "source_commit_hash": locked["provenance"]["source_commit_hash"],
            "source_path": locked["artifact"]["uri"],
            "build_id": locked["provenance"]["build_id"],
            "build_url": locked["provenance"]["build_url"],
            "build_time": locked["provenance"]["build_time"],
        },
    )
    assert (
        cli.main(
            [
                "lock",
                str(package),
                "--output",
                str(lockfile),
                "--check",
                "--check-db",
                "--connect",
                "user/pass@db",
            ]
        )
        == 0
    )

    assert f"LOCKFILE_OK={lockfile}" in capsys.readouterr().out


def test_lock_check_db_requires_check(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["lock", str(package), "--check-db"]) == 2

    assert "--check-db requires --check" in capsys.readouterr().err


def test_install_with_dependency_source_executes_multi_package_plan(tmp_path: Path, monkeypatch):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package(base)
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "0.1.0"

dependencies:
  - name: demo
    version: "0.1.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )
    calls = {}

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)

    def fake_execute_plan(plan, *, connect: str, runner: str):
        calls["plan"] = plan
        calls["connect"] = connect
        calls["runner"] = runner
        return 0

    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    assert (
        cli.main(
            [
                "install",
                str(consumer),
                "--dependency-source",
                str(base),
                "--connect",
                "user/pass@db",
            ]
        )
        == 0
    )

    assert calls["connect"] == "user/pass@db"
    assert calls["plan"]["schema_version"] == "dbpm.multi-plan.v0"
    assert calls["plan"]["execution_order"] == ["DEMO", "CONSUMER"]


def test_install_from_lockfile_executes_locked_plan(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_package(package)
    calls = {}

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)

    def fake_execute_plan(plan, *, connect: str, runner: str):
        calls["plan"] = plan
        calls["connect"] = connect
        calls["runner"] = runner
        return 0

    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    assert cli.main(["lock", str(package), "--output", str(lockfile)]) == 0
    assert cli.main(["install", "--lockfile", str(lockfile), "--connect", "user/pass@db"]) == 0

    assert calls["connect"] == "user/pass@db"
    assert calls["plan"]["package"]["application_name"] == "DEMO"


def test_install_from_default_lockfile_path(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package(package)
    calls = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)
    monkeypatch.setattr(cli, "execute_plan", lambda plan, **kwargs: calls.setdefault("plan", plan))

    assert cli.main(["lock", str(package)]) == 0
    assert cli.main(["install", "--lockfile", "--connect", "user/pass@db"]) == 0

    assert calls["plan"]["package"]["application_name"] == "DEMO"


def test_install_from_lockfile_rejects_extra_sources(tmp_path: Path, capsys):
    package = tmp_path / "package"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_package(package)

    assert cli.main(["lock", str(package), "--output", str(lockfile)]) == 0
    assert (
        cli.main(
            [
                "install",
                str(package),
                "--lockfile",
                str(lockfile),
                "--connect",
                "user/pass@db",
            ]
        )
        == 2
    )

    assert "--lockfile cannot be combined with source or --dependency-source" in capsys.readouterr().err


def test_install_dry_run_prints_plan(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["install", str(package), "--dry-run"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "install"


def test_reinstall_dry_run_shows_required_destructive_flag(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["reinstall", str(package), "--dry-run"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["policy"]["result"] == "requires-approval"
    assert "`reinstall` requires --allow-destructive" in output["policy"]["required_approvals"]


def test_install_without_connect_fails(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["install", str(package)]) == 2

    assert "Database access requires --connect or DBPM_CONNECT" in capsys.readouterr().err


def test_install_blocks_when_package_already_installed(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO is already installed; use reinstall or upgrade" in capsys.readouterr().err


def test_install_blocks_incomplete_existing_deployment(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="R",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO deployment status is R; use resume or reinstall" in capsys.readouterr().err


def test_reinstall_allows_existing_complete_package(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: [])
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: 0)

    assert (
        cli.main(
            [
                "reinstall",
                str(package),
                "--connect",
                "user/pass@db",
                "--allow-destructive",
            ]
        )
        == 0
    )


def test_reinstall_allows_incomplete_existing_package(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="R",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: [])
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: 0)

    assert (
        cli.main(
            [
                "reinstall",
                str(package),
                "--connect",
                "user/pass@db",
                "--allow-destructive",
            ]
        )
        == 0
    )


def test_reinstall_blocks_when_dependents_exist(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: ["JOB_CONTROL", "MY_APP"])

    assert (
        cli.main(
            [
                "reinstall",
                str(package),
                "--connect",
                "user/pass@db",
                "--allow-destructive",
            ]
        )
        == 2
    )

    assert (
        "Cannot reinstall DEMO; installed applications depend on it: JOB_CONTROL, MY_APP"
        in capsys.readouterr().err
    )


def test_resume_allows_running_deployment(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="R",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: 0)

    assert cli.main(["resume", str(package), "--connect", "user/pass@db"]) == 0


def test_resume_blocks_complete_deployment(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["resume", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO deployment status is C; resume requires R or F" in capsys.readouterr().err


def test_validate_requires_complete_deployment(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: 0)

    assert cli.main(["validate", str(package), "--connect", "user/pass@db"]) == 0


def test_validate_blocks_running_deployment(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="0.1.0",
            deploy_status="R",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["validate", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO deployment status is R; validate requires C" in capsys.readouterr().err


def _write_package_with_upgrade(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "1.0.1"

core:
  minimum_version: "3.0.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/upgrade.sql
  validate: Tests/smoke_test.sql
""",
        encoding="utf-8",
    )


def _write_core_package_with_upgrade(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.3.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/update.sql
""",
        encoding="utf-8",
    )


def test_upgrade_allows_complete_installed_package(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="1.0.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: 0)

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 0


def test_core_upgrade_reads_installed_state_and_executes(tmp_path: Path, monkeypatch):
    package = tmp_path / "core"
    _write_core_package_with_upgrade(package)
    calls = {}

    def fake_get_application_state(**kwargs):
        calls["state_application_name"] = kwargs["application_name"]
        return ApplicationState(
            application_name="CORE",
            version="3.2.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        )

    def fake_execute_plan(plan, *, connect: str, runner: str):
        calls["plan"] = plan
        calls["connect"] = connect
        calls["runner"] = runner
        return 0

    monkeypatch.setattr(cli, "get_application_state", fake_get_application_state)
    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 0

    assert calls["state_application_name"] == "CORE"
    assert calls["connect"] == "user/pass@db"
    assert calls["plan"]["installed_state"]["version"] == "3.2.0"
    assert calls["plan"]["pre_actions"][0]["type"] == "stage_deployment_provenance"


def test_upgrade_blocks_when_not_installed(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO is not installed; use install" in capsys.readouterr().err


def test_upgrade_blocks_incomplete_deployment(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="1.0.0",
            deploy_status="R",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO deployment status is R; upgrade requires C" in capsys.readouterr().err


def test_upgrade_blocks_same_version(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="1.0.1",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2

    assert "DEMO version 1.0.1 is already installed; no upgrade needed" in capsys.readouterr().err


def test_upgrade_blocks_downgrade(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="2.0.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2

    assert "Cannot downgrade DEMO from 2.0.0 to 1.0.1" in capsys.readouterr().err


def test_upgrade_dry_run_prints_plan(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    assert cli.main(["upgrade", str(package), "--dry-run"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "upgrade"


def test_check_core_uses_environment_connect_and_runner(monkeypatch, capsys):
    calls = {}

    def fake_check_core(*, connect: str, runner: str, minimum_version: str | None):
        calls["connect"] = connect
        calls["runner"] = runner
        calls["minimum_version"] = minimum_version
        return SqlResult(returncode=0, stdout="CORE_VERSION=3.0.0\n", stderr="")

    monkeypatch.setenv("DBPM_CONNECT", "user/password@db")
    monkeypatch.setenv("DBPM_SQL_RUNNER", "sql")
    monkeypatch.setattr(cli, "check_core", fake_check_core)

    assert cli.main(["check-core", "--minimum-version", "3.0.0"]) == 0

    assert calls == {
        "connect": "user/password@db",
        "runner": "sql",
        "minimum_version": "3.0.0",
    }
    assert "CORE_VERSION=3.0.0" in capsys.readouterr().out
