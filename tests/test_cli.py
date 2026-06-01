import json
import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm import cli
from dbpm.db import ApplicationState, SqlResult
from dbpm.registry import RegistryResolution, RegistrySource


def _write_package(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  validate: Tests/smoke_test.sql
""",
        encoding="utf-8",
    )


def _write_workspace_package(
    path: Path,
    name: str,
    version: str = "0.1.0",
    *,
    dependencies: str = "",
    publish: str = "",
) -> None:
    path.mkdir(parents=True)
    (path / "dbpm.yaml").write_text(
        f"""
package:
  name: {name}
  version: "{version}"

{dependencies}
{publish}
scripts:
  install: deploy.sql
  validate: validate.sql
""",
        encoding="utf-8",
    )
    (path / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    (path / "validate.sql").write_text("PROMPT validate\n", encoding="utf-8")


def _write_workspace_manifest(path: Path, package_paths: list[str]) -> None:
    entries = "\n".join(f"    - {item}" for item in package_paths)
    (path / "dbpm-workspace.yaml").write_text(
        f"""
workspace:
  packages:
{entries}
""",
        encoding="utf-8",
    )


def _write_registry_zip(
    path: Path,
    name: str,
    version: str,
    *,
    dependencies: str = "",
) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            f"{name}/dbpm.yaml",
            f"""
package:
  name: {name}
  version: "{version}"

{dependencies}
scripts:
  install: deploy.sql
""",
        )
        archive.writestr(f"{name}/deploy.sql", "PROMPT deploy\n")


def _registry_resolution(
    package: str,
    version: str,
    artifact_url: str,
    checksum: str,
    constraint: str,
    *,
    warning: dict[str, object] | None = None,
) -> RegistryResolution:
    warnings = [warning] if warning else []
    return RegistryResolution(
        package=package,
        version=version,
        artifact_url=artifact_url,
        artifact_checksum=checksum,
        artifact_signature_url=f"{artifact_url}.asc",
        publisher_key_fingerprint="FINGERPRINT",
        registry_url="https://registry.example",
        source=RegistrySource(package, constraint),
        warning=warning,
        warnings=warnings,
    )


@pytest.fixture(autouse=True)
def _no_reverse_dependencies(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
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


def test_workspace_list_prints_package_summaries(tmp_path: Path, capsys):
    _write_workspace_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_workspace_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert cli.main(["workspace", "list", str(tmp_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["workspace_root"] == str(tmp_path)
    assert [package["name"] for package in output["packages"]] == [
        "utl_interval",
        "simple_scheduler",
    ]


def test_plan_workspace_root_selects_package(tmp_path: Path, capsys):
    _write_workspace_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_workspace_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert cli.main(["plan", str(tmp_path), "--package", "simple_scheduler"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.plan.v0"
    assert output["package"]["application_name"] == "SIMPLE_SCHEDULER"
    assert output["source"]["path"].endswith("database/simple_scheduler")


def test_plan_workspace_root_without_package_fails_when_ambiguous(tmp_path: Path, capsys):
    _write_workspace_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_workspace_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert cli.main(["plan", str(tmp_path)]) == 2

    assert "Workspace contains multiple packages" in capsys.readouterr().err


def test_plan_workspace_root_auto_uses_sibling_dependency(tmp_path: Path, capsys):
    _write_workspace_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_workspace_package(
        tmp_path / "database" / "simple_scheduler",
        "simple_scheduler",
        "1.1.0",
        dependencies="""
dependencies:
  - name: utl_interval
    version: "1.0.0"
""",
    )
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert cli.main(["plan", str(tmp_path), "--package", "simple_scheduler"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.multi-plan.v0"
    assert output["execution_order"] == ["UTL_INTERVAL", "SIMPLE_SCHEDULER"]


def test_explicit_dependency_source_overrides_workspace_sibling(tmp_path: Path, capsys):
    explicit = tmp_path / "explicit_interval"
    _write_workspace_package(tmp_path / "database" / "utl_interval", "utl_interval", "1.0.0")
    _write_workspace_package(
        tmp_path / "database" / "simple_scheduler",
        "simple_scheduler",
        "1.1.0",
        dependencies="""
dependencies:
  - name: utl_interval
    version: "2.0.0"
""",
    )
    _write_workspace_package(explicit, "utl_interval", "2.0.0")
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert (
        cli.main(
            [
                "plan",
                str(tmp_path),
                "--package",
                "simple_scheduler",
                "--dependency-source",
                str(explicit),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["execution_order"] == ["UTL_INTERVAL", "SIMPLE_SCHEDULER"]
    dep_plan = output["packages"][0]
    assert dep_plan["package"]["version"] == "2.0.0"


def test_publish_workspace_root_dry_run_selects_package(tmp_path: Path, capsys):
    _write_workspace_package(
        tmp_path / "database" / "utl_interval",
        "utl_interval",
        "1.0.0",
        publish="""
publish:
  group: com.example.database
""",
    )
    _write_workspace_package(tmp_path / "database" / "simple_scheduler", "simple_scheduler", "1.1.0")
    _write_workspace_manifest(
        tmp_path,
        ["database/utl_interval", "database/simple_scheduler"],
    )

    assert (
        cli.main(
            [
                "publish",
                str(tmp_path),
                "--package",
                "utl_interval",
                "--target",
                "maven:https://repo.example.test/releases",
                "--signing-key",
                "signing@example.test",
                "--dry-run",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "DRY_RUN: would publish utl_interval-1.0.0.zip" in output
    assert "group:     com.example.database" in output


def test_plan_registry_source_auto_resolves_dependencies(tmp_path: Path, monkeypatch, capsys):
    scheduler = tmp_path / "simple_scheduler.zip"
    interval = tmp_path / "utl_interval.zip"
    _write_registry_zip(
        scheduler,
        "simple_scheduler",
        "1.1.0",
        dependencies="""
dependencies:
  - name: utl_interval
    version: "^1.0.0"
""",
    )
    _write_registry_zip(interval, "utl_interval", "1.0.0")
    artifacts = {
        "https://repo.example/simple_scheduler-1.1.0.zip": scheduler,
        "https://repo.example/utl_interval-1.0.0.zip": interval,
    }
    checksums = {
        url: hashlib.sha256(path.read_bytes()).hexdigest()
        for url, path in artifacts.items()
    }
    resolved = {
        "registry:simple_scheduler@^1.1.0": _registry_resolution(
            "simple_scheduler",
            "1.1.0",
            "https://repo.example/simple_scheduler-1.1.0.zip",
            checksums["https://repo.example/simple_scheduler-1.1.0.zip"],
            "^1.1.0",
            warning={"code": "yanked_version", "message": "Yanked"},
        ),
        "registry:utl_interval@^1.0.0": _registry_resolution(
            "utl_interval",
            "1.0.0",
            "https://repo.example/utl_interval-1.0.0.zip",
            checksums["https://repo.example/utl_interval-1.0.0.zip"],
            "^1.0.0",
        ),
    }

    monkeypatch.setattr("dbpm.source.resolve_registry_source", lambda raw, registry_url=None: resolved[raw])
    monkeypatch.setattr("dbpm.source._check_gpg_signature", lambda *args: None)

    def fake_download(url: str, destination: Path) -> None:
        if url.endswith(".asc"):
            destination.write_bytes(b"sig")
        else:
            destination.write_bytes(artifacts[url].read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    assert (
        cli.main(
            [
                "plan",
                "registry:simple_scheduler@^1.1.0",
                "--registry-url",
                "https://registry.example",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.multi-plan.v0"
    assert output["execution_order"] == ["UTL_INTERVAL", "SIMPLE_SCHEDULER"]
    assert output["packages"][1]["warnings"] == [{"code": "yanked_version", "message": "Yanked"}]


def test_explicit_dependency_source_wins_over_registry_auto_resolution(tmp_path: Path, monkeypatch, capsys):
    scheduler = tmp_path / "simple_scheduler.zip"
    explicit = tmp_path / "explicit_interval"
    _write_registry_zip(
        scheduler,
        "simple_scheduler",
        "1.1.0",
        dependencies="""
dependencies:
  - name: utl_interval
    version: "1.0.0"
""",
    )
    explicit.mkdir()
    (explicit / "dbpm.yaml").write_text(
        """
package:
  name: utl_interval
  version: "1.0.0"

scripts:
  install: deploy.sql
""",
        encoding="utf-8",
    )
    (explicit / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    checksum = hashlib.sha256(scheduler.read_bytes()).hexdigest()

    def fake_resolve(raw: str, registry_url: str | None = None) -> RegistryResolution:
        if raw != "registry:simple_scheduler@^1.1.0":
            pytest.fail(f"unexpected registry dependency lookup: {raw}")
        return _registry_resolution(
            "simple_scheduler",
            "1.1.0",
            "https://repo.example/simple_scheduler-1.1.0.zip",
            checksum,
            "^1.1.0",
        )

    monkeypatch.setattr("dbpm.source.resolve_registry_source", fake_resolve)
    monkeypatch.setattr("dbpm.source._check_gpg_signature", lambda *args: None)
    monkeypatch.setattr(
        "dbpm.source._download",
        lambda url, destination: destination.write_bytes(b"sig" if url.endswith(".asc") else scheduler.read_bytes()),
    )

    assert (
        cli.main(
            [
                "plan",
                "registry:simple_scheduler@^1.1.0",
                "--dependency-source",
                str(explicit),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["execution_order"] == ["UTL_INTERVAL", "SIMPLE_SCHEDULER"]


def test_install_from_registry_lockfile_does_not_call_registry(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "utl_interval.zip"
    lockfile = tmp_path / "dbpm-lock.json"
    _write_registry_zip(package, "utl_interval", "1.0.0")
    artifact_url = "https://repo.example/utl_interval-1.0.0.zip"
    checksum = hashlib.sha256(package.read_bytes()).hexdigest()

    monkeypatch.setattr(
        "dbpm.source.resolve_registry_source",
        lambda raw, registry_url=None: _registry_resolution(
            "utl_interval",
            "1.0.0",
            artifact_url,
            checksum,
            "1.0.0",
        ),
    )
    monkeypatch.setattr("dbpm.source._check_gpg_signature", lambda *args: None)

    def fake_download(url: str, destination: Path) -> None:
        destination.write_bytes(b"sig" if url.endswith(".asc") else package.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)

    assert cli.main(["lock", "registry:utl_interval@1.0.0", "--output", str(lockfile)]) == 0
    locked = json.loads(lockfile.read_text(encoding="utf-8"))["packages"][0]
    assert locked["artifact"]["uri"] == artifact_url
    assert locked["artifact"]["signature_url"] == f"{artifact_url}.asc"
    assert locked["artifact"]["publisher_key_fingerprint"] == "FINGERPRINT"
    capsys.readouterr()

    def fail_registry_lookup(raw: str, registry_url: str | None = None) -> RegistryResolution:
        pytest.fail("locked install should not call registry")

    monkeypatch.setattr("dbpm.source.resolve_registry_source", fail_registry_lookup)

    assert cli.main(["install", "--lockfile", str(lockfile), "--dry-run"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["package"]["application_name"] == "UTL_INTERVAL"


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


def test_lock_check_db_keeps_dependency_sources_when_dependency_is_installed(
    tmp_path: Path,
    monkeypatch,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    lockfile = tmp_path / "dbpm-lock.json"
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

    def fake_get_application_state(**kwargs):
        return ApplicationState(
            application_name=kwargs["application_name"],
            version="0.1.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        )

    monkeypatch.setattr(cli, "get_application_state", fake_get_application_state)
    monkeypatch.setattr(cli, "get_deployment_provenance", lambda **kwargs: _matching_provenance_from_lock(lockfile, kwargs["application_name"]))

    assert (
        cli.main(
            [
                "lock",
                str(consumer),
                "--dependency-source",
                str(base),
                "--output",
                str(lockfile),
            ]
        )
        == 0
    )

    output = json.loads(lockfile.read_text(encoding="utf-8"))
    assert output["execution_order"] == ["DEMO", "CONSUMER"]
    assert (
        cli.main(
            [
                "lock",
                str(consumer),
                "--dependency-source",
                str(base),
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


def _matching_provenance_from_lock(lockfile: Path, application_name: str) -> dict[str, object]:
    data = json.loads(lockfile.read_text(encoding="utf-8"))
    package = next(item for item in data["packages"] if item["application_name"] == application_name)
    major, minor, patch = package["version"].split(".")
    return {
        "major_version": int(major),
        "minor_version": int(minor),
        "patch_version": int(patch),
        "artifact_uri": package["artifact"]["uri"],
        "artifact_checksum": package["artifact"]["checksum"],
        "artifact_checksum_alg": package["artifact"]["checksum_alg"],
        "artifact_file_name": package["artifact"]["file_name"],
        "artifact_repository_type": package["artifact"]["repository_type"],
        "artifact_group_id": package["artifact"]["group_id"],
        "artifact_id": package["artifact"]["artifact_id"],
        "artifact_version": package["artifact"]["artifact_version"],
        "artifact_classifier": package["artifact"]["classifier"],
        "artifact_extension": package["artifact"]["extension"],
        "package_coordinate": package["artifact"]["coordinate"],
        "source_repository_url": package["provenance"]["source_repository_url"],
        "source_commit_hash": package["provenance"]["source_commit_hash"],
        "source_path": package["artifact"]["uri"],
        "build_id": package["provenance"]["build_id"],
        "build_url": package["provenance"]["build_url"],
        "build_time": package["provenance"]["build_time"],
    }


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


def _write_core_reinstall_package(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.4.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        encoding="utf-8",
    )


def test_core_reinstall_dry_run_shows_delete_system_confirmation(tmp_path: Path, capsys):
    package = tmp_path / "core"
    _write_core_reinstall_package(package)

    assert (
        cli.main(
            [
                "reinstall",
                str(package),
                "--allow-destructive",
                "--dry-run",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["policy"]["result"] == "requires-approval"
    assert "Core reinstall requires --confirm-delete-system CORE" in output["policy"]["required_approvals"]


def test_core_reinstall_blocks_without_delete_system_confirmation(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    package = tmp_path / "core"
    _write_core_reinstall_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("CORE", "3.4.0", "C", "abc"),
    )
    monkeypatch.setattr(cli, "execute_plan", lambda *args, **kwargs: pytest.fail("should not execute"))

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

    assert "Core reinstall requires --confirm-delete-system CORE" in capsys.readouterr().err


def test_core_reinstall_allows_delete_system_confirmation(tmp_path: Path, monkeypatch):
    package = tmp_path / "core"
    _write_core_reinstall_package(package)
    calls = {}

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("CORE", "3.4.0", "C", "abc"),
    )

    def fake_execute_plan(plan, *, connect: str, runner: str):
        calls["policy"] = plan["policy"]
        return 0

    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    assert (
        cli.main(
            [
                "reinstall",
                str(package),
                "--connect",
                "user/pass@db",
                "--allow-destructive",
                "--confirm-delete-system",
                "CORE",
            ]
        )
        == 0
    )

    assert calls["policy"]["result"] == "allowed"


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


def test_validate_with_dependency_source_executes_multi_package_plan(
    tmp_path: Path,
    monkeypatch,
):
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
  validate: smoke.sql
""",
        encoding="utf-8",
    )
    calls = {}

    def fake_get_application_state(**kwargs):
        return ApplicationState(
            application_name=kwargs["application_name"],
            version="0.1.0",
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

    assert (
        cli.main(
            [
                "validate",
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
    assert [item["mode"] for item in calls["plan"]["packages"]] == ["validate", "validate"]


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


def test_upgrade_with_dependency_source_executes_multi_package_plan(
    tmp_path: Path,
    monkeypatch,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package_with_upgrade(base)
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "1.0.1"

dependencies:
  - name: demo
    version: "^1.0.0"

scripts:
  install: deploy.sql
  upgrade: upgrade.sql
  validate: smoke.sql
""",
        encoding="utf-8",
    )
    calls = {}

    def fake_get_application_state(**kwargs):
        version = "1.0.0"
        return ApplicationState(
            application_name=kwargs["application_name"],
            version=version,
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

    assert (
        cli.main(
            [
                "upgrade",
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
    assert [item["mode"] for item in calls["plan"]["packages"]] == ["upgrade", "upgrade"]


def test_upgrade_with_missing_dependency_source_fails_instead_of_installing(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "1.0.1"

dependencies:
  - name: demo
    version: "1.0.1"

scripts:
  install: deploy.sql
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    def fake_get_application_state(**kwargs):
        if kwargs["application_name"] == "CONSUMER":
            return ApplicationState(
                application_name="CONSUMER",
                version="1.0.0",
                deploy_status="C",
                deploy_commit_hash="abc",
            )
        return None

    monkeypatch.setattr(cli, "get_application_state", fake_get_application_state)

    assert cli.main(["upgrade", str(consumer), "--connect", "user/pass@db"]) == 2

    assert "Missing dependency source for CONSUMER: DEMO 1.0.1" in capsys.readouterr().err


def test_upgrade_with_uninstalled_dependency_source_fails_instead_of_installing(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    base = tmp_path / "base"
    consumer = tmp_path / "consumer"
    _write_package_with_upgrade(base)
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "1.0.1"

dependencies:
  - name: demo
    version: "^1.0.0"

scripts:
  install: deploy.sql
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    def fake_get_application_state(**kwargs):
        if kwargs["application_name"] == "CONSUMER":
            return ApplicationState(
                application_name="CONSUMER",
                version="1.0.0",
                deploy_status="C",
                deploy_commit_hash="abc",
            )
        return None

    monkeypatch.setattr(cli, "get_application_state", fake_get_application_state)

    assert (
        cli.main(
            [
                "upgrade",
                str(consumer),
                "--dependency-source",
                str(base),
                "--connect",
                "user/pass@db",
            ]
        )
        == 2
    )

    assert "Cannot upgrade dependency DEMO; it is not installed; use install first" in capsys.readouterr().err


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


# ── upgrade chain ────────────────────────────────────────────────────────────


def _write_maven_upgrade_package(path: Path, *, version: str, upgrade_from: str | None = None) -> None:
    from zipfile import ZipFile

    upgrade_from_line = f"  upgrade_from: \"{upgrade_from}\"\n" if upgrade_from else ""
    manifest = (
        f"package:\n  name: demo\n  version: \"{version}\"\n"
        f"scripts:\n  install: deploy.sql\n  upgrade: upgrade.sql\n{upgrade_from_line}"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(f"demo/dbpm.yaml", manifest)
        archive.writestr(f"demo/upgrade.sql", "PROMPT upgrade\n")
        archive.writestr(f"demo/deploy.sql", "PROMPT deploy\n")


def test_major_upgrade_with_dependents_is_blocked(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("DEMO", "1.0.0", "C", "abc"),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: ["CONSUMER"])

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2

    err = capsys.readouterr().err
    assert "Cannot upgrade DEMO from 1.0.0 to 1.0.1" not in err  # minor bump — would not fire
    # rewrite package with major bump
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "2.0.0"
scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/upgrade.sql
""",
        encoding="utf-8",
    )

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 2
    err = capsys.readouterr().err
    assert "Cannot upgrade DEMO from 1.0.0 to 2.0.0" in err
    assert "CONSUMER" in err
    assert "--allow-dependent-break" in err


def test_major_upgrade_allow_dependent_break_proceeds(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "2.0.0"
scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/upgrade.sql
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("DEMO", "1.0.0", "C", "abc"),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: ["CONSUMER"])
    monkeypatch.setattr(cli, "execute_plan", lambda *a, **kw: 0)

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db", "--allow-dependent-break"]) == 0


def test_minor_upgrade_with_dependents_is_not_blocked(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package_with_upgrade(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("DEMO", "1.0.0", "C", "abc"),
    )
    monkeypatch.setattr(cli, "get_reverse_dependencies", lambda **kwargs: ["CONSUMER"])
    monkeypatch.setattr(cli, "execute_plan", lambda *a, **kw: 0)

    assert cli.main(["upgrade", str(package), "--connect", "user/pass@db"]) == 0


def test_major_upgrade_with_dependents_is_blocked_for_multi_package_plan(
    tmp_path: Path, monkeypatch, capsys
):
    dep = tmp_path / "dep"
    consumer = tmp_path / "consumer"
    _write_package_with_upgrade(dep)
    consumer.mkdir()
    (consumer / "dbpm.yaml").write_text(
        """
package:
  name: consumer
  version: "2.0.0"

dependencies:
  - name: demo
    version: "^1.0.0"

scripts:
  install: deploy.sql
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(kwargs["application_name"], "1.0.0", "C", "abc"),
    )

    def fake_reverse_deps(**kwargs):
        if kwargs.get("application_name") == "CONSUMER":
            return ["DOWNSTREAM"]
        return []

    monkeypatch.setattr(cli, "get_reverse_dependencies", fake_reverse_deps)

    assert (
        cli.main(
            [
                "upgrade",
                str(consumer),
                "--dependency-source",
                str(dep),
                "--connect",
                "user/pass@db",
            ]
        )
        == 2
    )

    err = capsys.readouterr().err
    assert "Cannot upgrade CONSUMER from 1.0.0 to 2.0.0" in err
    assert "DOWNSTREAM" in err


# ---------------------------------------------------------------------------
# Core minimum version preflight
# ---------------------------------------------------------------------------


def _write_package_requiring_core(path: Path, core_version: str = "3.4.0") -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        f"""
package:
  name: demo
  version: "1.0.1"

core:
  minimum_version: "{core_version}"

scripts:
  install: deploy.sql
  upgrade: upgrade.sql
""",
        encoding="utf-8",
    )


def test_install_blocked_when_core_too_old(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_requiring_core(package, core_version="3.4.0")

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: (
        None if kwargs["application_name"] != "CORE"
        else ApplicationState("CORE", "3.2.0", "C", "abc")
    ))

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 2

    err = capsys.readouterr().err
    assert "Core 3.4.0" in err
    assert "3.2.0" in err
    assert "Upgrade Core first" in err


def test_install_proceeds_when_core_meets_requirement(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package_requiring_core(package, core_version="3.2.0")

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: (
        None if kwargs["application_name"] != "CORE"
        else ApplicationState("CORE", "3.4.0", "C", "abc")
    ))
    monkeypatch.setattr(cli, "execute_plan", lambda *a, **kw: 0)

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 0


def test_install_blocked_when_core_not_installed(tmp_path: Path, monkeypatch, capsys):
    package = tmp_path / "package"
    _write_package_requiring_core(package, core_version="3.4.0")

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 2

    err = capsys.readouterr().err
    assert "Core is not installed" in err
    assert "bootstrap-core" in err


def test_install_blocked_when_core_deployment_is_not_complete(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    package = tmp_path / "package"
    _write_package_requiring_core(package, core_version="3.4.0")

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: (
        None if kwargs["application_name"] != "CORE"
        else ApplicationState("CORE", "3.4.0", "F", "abc")
    ))

    assert cli.main(["install", str(package), "--connect", "user/pass@db"]) == 2

    err = capsys.readouterr().err
    assert "Core deployment status is F" in err
    assert "resume or reinstall Core" in err


def _write_core_bootstrap_package(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: core
  version: "3.4.0"

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        encoding="utf-8",
    )


def test_bootstrap_core_blocks_when_core_is_already_installed(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    package = tmp_path / "core"
    _write_core_bootstrap_package(package)

    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState("CORE", "3.4.0", "C", "abc"),
    )

    def fail_execute_plan(*args, **kwargs):
        raise AssertionError("bootstrap-core should not execute when Core is already installed")

    monkeypatch.setattr(cli, "execute_plan", fail_execute_plan)

    assert cli.main(["bootstrap-core", str(package), "--connect", "user/pass@db"]) == 2

    err = capsys.readouterr().err
    assert "CORE is already installed with status C" in err
    assert "instead of bootstrap-core" in err


def test_bootstrap_core_runs_when_core_is_not_installed(tmp_path: Path, monkeypatch):
    package = tmp_path / "core"
    _write_core_bootstrap_package(package)
    calls = {}

    def fake_get_application_state(**kwargs):
        calls["application_name"] = kwargs["application_name"]
        return None

    def fake_execute_plan(plan, *, connect: str, runner: str):
        calls["plan"] = plan
        return 0

    monkeypatch.setattr(cli, "get_application_state", fake_get_application_state)
    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    assert cli.main(["bootstrap-core", str(package), "--connect", "user/pass@db"]) == 0

    assert calls["application_name"] == "CORE"
    assert calls["plan"]["installed_state"] is None


def test_bootstrap_core_skips_core_version_check(tmp_path: Path, monkeypatch):
    package = tmp_path / "package"
    _write_package_requiring_core(package, core_version="3.4.0")

    monkeypatch.setattr(cli, "get_application_state", lambda **kwargs: None)
    monkeypatch.setattr(cli, "execute_plan", lambda *a, **kw: 0)

    assert cli.main(["bootstrap-core", str(package), "--connect", "user/pass@db"]) == 0


def _version_aware_cli_download(tmp_path: Path, name: str):
    import re

    def _download(url: str, dest: Path) -> None:
        match = re.search(r"/(\d+\.\d+\.\d+)/", url)
        version = match.group(1) if match else "1.0.0"
        buf = tmp_path / f"_buf_{version}.zip"
        _write_maven_upgrade_package(buf, version=version)
        dest.write_bytes(buf.read_bytes())

    return _download


def test_upgrade_chain_dry_run_outputs_chain_plan(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    monkeypatch.setattr(
        "dbpm.chain._maven_version_list",
        lambda repo, coord: ["1.0.0", "1.1.0", "1.2.0", "1.3.0"],
    )
    monkeypatch.setattr("dbpm.source._download", _version_aware_cli_download(tmp_path, "demo"))
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

    raw = "gh-maven:rsantmyer/demo:com.example:demo:1.3.0"
    assert cli.main(["upgrade", raw, "--dry-run", "--connect", "user/pass@db"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == "dbpm.upgrade-chain.v0"
    assert output["installed_version"] == "1.0.0"
    assert len(output["steps"]) == 3
    assert [s["package"]["version"] for s in output["steps"]] == ["1.1.0", "1.2.0", "1.3.0"]


def test_upgrade_chain_maven_with_satisfied_upgrade_from_is_direct(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    def _download(url: str, dest: Path) -> None:
        buf = tmp_path / "_buf_1.3.0.zip"
        _write_maven_upgrade_package(buf, version="1.3.0", upgrade_from="^1.0.0")
        dest.write_bytes(buf.read_bytes())

    monkeypatch.setattr("dbpm.source._download", _download)
    monkeypatch.setattr(
        cli,
        "get_application_state",
        lambda **kwargs: ApplicationState(
            application_name="DEMO",
            version="1.2.0",
            deploy_status="C",
            deploy_commit_hash="abc",
        ),
    )
    monkeypatch.setattr(cli, "execute_plan", lambda *a, **kw: 0)

    raw = "gh-maven:rsantmyer/demo:com.example:demo:1.3.0"
    assert cli.main(["upgrade", raw, "--connect", "user/pass@db"]) == 0

    out = capsys.readouterr()
    assert out.err == ""


def test_upgrade_chain_executes_steps_in_order(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    versions_returned = ["1.0.0"]

    def fake_get_state(**kwargs):
        return ApplicationState(
            application_name="DEMO",
            version=versions_returned[-1],
            deploy_status="C",
            deploy_commit_hash="abc",
        )

    executed_versions = []

    def fake_execute_plan(plan, *, connect, runner):
        package = plan.get("package", {})
        executed_versions.append(package.get("version"))
        versions_returned.append(package.get("version"))

    monkeypatch.setattr(
        "dbpm.chain._maven_version_list",
        lambda repo, coord: ["1.0.0", "1.1.0", "1.2.0", "1.3.0"],
    )
    monkeypatch.setattr("dbpm.source._download", _version_aware_cli_download(tmp_path, "demo"))
    monkeypatch.setattr(cli, "get_application_state", fake_get_state)
    monkeypatch.setattr(cli, "execute_plan", fake_execute_plan)

    raw = "gh-maven:rsantmyer/demo:com.example:demo:1.3.0"
    assert cli.main(["upgrade", raw, "--connect", "user/pass@db"]) == 0

    assert executed_versions == ["1.1.0", "1.2.0", "1.3.0"]


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


def _write_publish_package(path: Path) -> None:
    path.mkdir()
    (path / "dbpm.yaml").write_text(
        """
package:
  name: demo
  version: "0.1.0"

publish:
  group: com.example.database
  artifact_id: demo

scripts:
  install: Deployment_Manifests/deploy.sql
""",
        encoding="utf-8",
    )


def test_publish_dry_run(tmp_path: Path, capsys, monkeypatch):
    package = tmp_path / "package"
    _write_publish_package(package)
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    ret = cli.main([
        "publish",
        str(package),
        "--target", "gh-maven:acme/myrepo",
        "--signing-key", "test@example.com",
        "--dry-run",
    ])

    assert ret == 0
    out = capsys.readouterr().out
    assert "DRY_RUN" in out
    assert "demo-0.1.0.zip" in out
    assert "demo-0.1.0.pom" in out
    assert "gh-maven:acme/myrepo" in out


def test_publish_requires_target(tmp_path: Path):
    package = tmp_path / "package"
    _write_publish_package(package)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["publish", str(package), "--signing-key", "key"])

    assert exc_info.value.code != 0


def test_publish_missing_signing_key_fails(tmp_path: Path, capsys, monkeypatch):
    package = tmp_path / "package"
    _write_publish_package(package)
    monkeypatch.delenv("DBPM_SIGNING_KEY", raising=False)
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    ret = cli.main(["publish", str(package), "--target", "gh-maven:acme/myrepo"])

    assert ret == 2
    assert "signing key" in capsys.readouterr().err.lower()


def test_publish_no_publish_config_fails(tmp_path: Path, capsys, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        "package:\n  name: demo\n  version: '0.1.0'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    ret = cli.main([
        "publish",
        str(package),
        "--target", "gh-maven:acme/myrepo",
        "--signing-key", "key",
    ])

    assert ret == 2
    err = capsys.readouterr().err
    assert "publish" in err.lower()


def test_publish_group_override(tmp_path: Path, capsys, monkeypatch):
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        "package:\n  name: demo\n  version: '0.1.0'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))

    ret = cli.main([
        "publish",
        str(package),
        "--target", "gh-maven:acme/myrepo",
        "--group", "com.override",
        "--signing-key", "key",
        "--dry-run",
    ])

    assert ret == 0
    out = capsys.readouterr().out
    assert "com.override" in out
