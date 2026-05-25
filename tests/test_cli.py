import json
from pathlib import Path

from dbpm import cli
from dbpm.db import SqlResult


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
""",
        encoding="utf-8",
    )


def test_plan_prints_json(tmp_path: Path, capsys):
    package = tmp_path / "package"
    _write_package(package)

    assert cli.main(["plan", str(package), "--env", "development"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.plan.v0"
    assert output["package"]["application_name"] == "DEMO"


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
