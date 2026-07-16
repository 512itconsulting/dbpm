import json
import os
from pathlib import Path

import pytest

from dbpm import cli
from dbpm.environment import resolve_deployment_policy
from dbpm.errors import ExecutionError, ManifestError
from dbpm.executor import execute_plan
from dbpm.manifest import parse_manifest, _parse_simple_yaml
from dbpm.planner import create_plan
from dbpm.provenance import resolve_provenance
from dbpm.runtime import (
    RECEIPT_SCHEMA,
    execute_runtime_step,
    load_receipt,
    receipt_lock,
    receipt_path,
    resolve_runtime_prefix,
    write_receipt,
)
from dbpm.source import load_package_source


RUNTIME_ONLY_MANIFEST = """
package:
  name: jc_runtime
  version: "{version}"

runtime:
  name: job_control
  scripts:
    install: os/dbpm/install.sh
    validate: os/dbpm/health.sh
"""


def _write_runtime_package(
    path: Path,
    *,
    version: str = "1.0.0",
    install_body: str = "#!/bin/sh\nprintf '%s\\n' \"$DBPM_RUNTIME_MODE\" > \"$DBPM_RUNTIME_PREFIX/mode.txt\"\n",
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "dbpm.yaml").write_text(
        RUNTIME_ONLY_MANIFEST.format(version=version), encoding="utf-8"
    )
    scripts = path / "os" / "dbpm"
    scripts.mkdir(parents=True, exist_ok=True)
    install = scripts / "install.sh"
    install.write_text(install_body, encoding="utf-8")
    install.chmod(0o755)
    health = scripts / "health.sh"
    health.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    health.chmod(0o755)
    return path


def _runtime_plan(package: Path, mode: str = "install") -> dict[str, object]:
    source = load_package_source(str(package))
    return create_plan(
        mode=mode,
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_deployment_policy(None),
    )


def _prefix(tmp_path: Path) -> Path:
    prefix = tmp_path / "opt" / "job_control"
    prefix.mkdir(parents=True, exist_ok=True)
    return prefix


def test_manifest_parses_runtime_component():
    manifest = parse_manifest(
        """
package:
  name: job_control
  version: "1.1.0"

scripts:
  install: deployment_manifests/deploy.sql

runtime:
  name: job_control
  scripts:
    install: os/dbpm/install.sh
    upgrade: os/dbpm/upgrade.sh
    validate: os/dbpm/health.sh
    uninstall: os/dbpm/uninstall.sh
""",
        "dbpm.yaml",
    )
    runtime = manifest.runtime
    assert runtime is not None
    assert runtime.name == "job_control"
    assert runtime.home_env == "JOB_CONTROL_HOME"
    assert runtime.install == "os/dbpm/install.sh"
    assert runtime.upgrade == "os/dbpm/upgrade.sh"
    assert runtime.validate == "os/dbpm/health.sh"
    assert runtime.uninstall == "os/dbpm/uninstall.sh"
    assert manifest.has_database_component is True


def test_manifest_runtime_home_env_override_and_default():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: my-runtime
  home_env: CUSTOM_HOME
  scripts:
    install: install.sh
""",
        "dbpm.yaml",
    )
    assert manifest.runtime.home_env == "CUSTOM_HOME"
    assert manifest.has_database_component is False


def test_manifest_runtime_default_home_env_upcases_hyphens():
    manifest = parse_manifest(
        """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: my-runtime
  scripts:
    install: install.sh
""",
        "dbpm.yaml",
    )
    assert manifest.runtime.home_env == "MY_RUNTIME_HOME"


def test_manifest_runtime_into_is_rejected():
    with pytest.raises(ManifestError, match="runtime.into"):
        parse_manifest(
            """
package:
  name: demo
  version: "0.1.0"

runtime:
  into: job_control
  scripts:
    install: install.sh
""",
            "dbpm.yaml",
        )


def test_manifest_runtime_requires_install_script():
    with pytest.raises(ManifestError, match="runtime.scripts.install"):
        parse_manifest(
            """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: demo
  scripts:
    validate: health.sh
""",
            "dbpm.yaml",
        )


def test_manifest_runtime_rejects_bad_home_env():
    with pytest.raises(ManifestError, match="home_env"):
        parse_manifest(
            """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: demo
  home_env: not-valid
  scripts:
    install: install.sh
""",
            "dbpm.yaml",
        )


def test_manifest_runtime_rejects_unsafe_script_path():
    with pytest.raises(ManifestError, match="package-relative"):
        parse_manifest(
            """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: demo
  scripts:
    install: ../outside.sh
""",
            "dbpm.yaml",
        )


def test_simple_yaml_parser_supports_nested_runtime_scripts():
    data = _parse_simple_yaml(
        """
package:
  name: demo
  version: "0.1.0"

runtime:
  name: demo
  scripts:
    install: install.sh
    validate: health.sh
""",
        "dbpm.yaml",
    )
    assert data["runtime"]["name"] == "demo"
    assert data["runtime"]["scripts"] == {
        "install": "install.sh",
        "validate": "health.sh",
    }


def test_plan_includes_runtime_step(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    plan = _runtime_plan(package)

    runtime = plan["runtime"]
    assert runtime["name"] == "job_control"
    assert runtime["home_env"] == "JOB_CONTROL_HOME"
    assert runtime["script"] == "os/dbpm/install.sh"
    assert runtime["script_ref"] == str(package / "os" / "dbpm" / "install.sh")
    assert runtime["package_root"] == str(package)
    environment = runtime["environment"]
    assert environment["DBPM_RUNTIME_MODE"] == "install"
    assert environment["DBPM_PACKAGE_NAME"] == "jc_runtime"
    assert environment["DBPM_PACKAGE_VERSION"] == "1.0.0"
    assert len(environment["DBPM_COMMIT_HASH"]) == 40
    assert plan["execution"]["script"] is None
    assert plan["pre_actions"] == []
    assert plan["post_actions"] == []


def test_plan_upgrade_falls_back_to_runtime_install_script(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    plan = _runtime_plan(package, mode="upgrade")
    assert plan["runtime"]["script"] == "os/dbpm/install.sh"
    assert plan["runtime"]["environment"]["DBPM_RUNTIME_MODE"] == "upgrade"


def test_plan_validate_uses_runtime_validate_script(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    plan = _runtime_plan(package, mode="validate")
    assert plan["runtime"]["script"] == "os/dbpm/health.sh"


def test_plan_with_database_and_runtime_components(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "dbpm.yaml").write_text(
        """
package:
  name: job_control
  version: "1.1.0"

scripts:
  install: deploy.sql

runtime:
  name: job_control
  scripts:
    install: os/dbpm/install.sh
""",
        encoding="utf-8",
    )
    (package / "deploy.sql").write_text("PROMPT deploy\n", encoding="utf-8")
    scripts = package / "os" / "dbpm"
    scripts.mkdir(parents=True)
    (scripts / "install.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    plan = _runtime_plan(package)
    assert plan["execution"]["script"] == "deploy.sql"
    assert plan["runtime"]["script"] == "os/dbpm/install.sh"
    assert plan["pre_actions"][0]["type"] == "stage_deployment_provenance"


def test_resolve_runtime_prefix_prefers_override(tmp_path: Path, monkeypatch):
    prefix = _prefix(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("JOB_CONTROL_HOME", str(other))
    runtime = {"name": "job_control", "home_env": "JOB_CONTROL_HOME"}
    assert resolve_runtime_prefix(runtime, str(prefix)) == prefix
    assert resolve_runtime_prefix(runtime, None) == other


def test_resolve_runtime_prefix_requires_configuration(monkeypatch):
    monkeypatch.delenv("JOB_CONTROL_HOME", raising=False)
    runtime = {"name": "job_control", "home_env": "JOB_CONTROL_HOME"}
    with pytest.raises(ExecutionError, match="JOB_CONTROL_HOME"):
        resolve_runtime_prefix(runtime, None)


def test_resolve_runtime_prefix_requires_existing_directory(tmp_path: Path):
    runtime = {"name": "job_control", "home_env": "JOB_CONTROL_HOME"}
    with pytest.raises(ExecutionError, match="does not exist"):
        resolve_runtime_prefix(runtime, str(tmp_path / "missing"))


def test_receipt_roundtrip_and_owner_check(tmp_path: Path):
    prefix = _prefix(tmp_path)
    receipt = load_receipt(prefix, "job_control")
    assert receipt == {"schema": RECEIPT_SCHEMA, "runtime": "job_control", "packages": {}}

    receipt["packages"]["jc_runtime"] = {"role": "owner", "version": "1.0.0", "status": "complete"}
    write_receipt(prefix, receipt)
    loaded = load_receipt(prefix, "job_control")
    assert loaded["packages"]["jc_runtime"]["version"] == "1.0.0"

    with pytest.raises(ExecutionError, match="owned by runtime"):
        load_receipt(prefix, "other_runtime")


def test_receipt_lock_blocks_concurrent_deployment(tmp_path: Path):
    prefix = _prefix(tmp_path)
    with receipt_lock(prefix):
        with pytest.raises(ExecutionError, match="Another dbpm deployment"):
            with receipt_lock(prefix):
                pass
    # Lock is released after the context exits.
    with receipt_lock(prefix):
        pass


def test_execute_runtime_step_installs_and_writes_receipt(tmp_path: Path):
    package = _write_runtime_package(
        tmp_path / "pkg",
        install_body=(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$DBPM_RUNTIME_MODE\" > \"$DBPM_RUNTIME_PREFIX/mode.txt\"\n"
            "printf '%s\\n' \"$DBPM_INSTALLED_VERSION\" > \"$DBPM_RUNTIME_PREFIX/installed.txt\"\n"
        ),
    )
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)

    execute_runtime_step(
        plan["runtime"],
        log_file=tmp_path / "logs" / "runtime.log",
        prefix_override=str(prefix),
    )

    assert (prefix / "mode.txt").read_text(encoding="utf-8").strip() == "install"
    assert (prefix / "installed.txt").read_text(encoding="utf-8").strip() == ""
    receipt = json.loads(receipt_path(prefix).read_text(encoding="utf-8"))
    entry = receipt["packages"]["jc_runtime"]
    assert entry["role"] == "owner"
    assert entry["version"] == "1.0.0"
    assert entry["status"] == "complete"
    assert entry["mode"] == "install"
    assert len(entry["commit"]) == 40


def test_execute_runtime_step_marks_failure_and_raises(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg", install_body="#!/bin/sh\nexit 7\n")
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)

    with pytest.raises(ExecutionError, match="exit code 7"):
        execute_runtime_step(
            plan["runtime"],
            log_file=tmp_path / "logs" / "runtime.log",
            prefix_override=str(prefix),
        )

    receipt = json.loads(receipt_path(prefix).read_text(encoding="utf-8"))
    entry = receipt["packages"]["jc_runtime"]
    assert entry["status"] == "failed"
    assert entry["previous_version"] is None
    # The lock is released even when the script fails.
    assert not (prefix / ".dbpm" / "lock").exists()


def test_execute_runtime_step_blocks_reinstall_via_install_mode(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)
    log_dir = tmp_path / "logs"

    execute_runtime_step(plan["runtime"], log_file=log_dir / "a.log", prefix_override=str(prefix))
    with pytest.raises(ExecutionError, match="already installed"):
        execute_runtime_step(plan["runtime"], log_file=log_dir / "b.log", prefix_override=str(prefix))


def test_execute_runtime_step_resume_after_failure(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg", install_body="#!/bin/sh\nexit 1\n")
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)
    log_dir = tmp_path / "logs"

    with pytest.raises(ExecutionError):
        execute_runtime_step(plan["runtime"], log_file=log_dir / "a.log", prefix_override=str(prefix))

    install = package / "os" / "dbpm" / "install.sh"
    install.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    resume_plan = _runtime_plan(package, mode="resume")
    execute_runtime_step(resume_plan["runtime"], log_file=log_dir / "b.log", prefix_override=str(prefix))

    receipt = json.loads(receipt_path(prefix).read_text(encoding="utf-8"))
    assert receipt["packages"]["jc_runtime"]["status"] == "complete"
    assert receipt["packages"]["jc_runtime"]["mode"] == "resume"


def test_execute_runtime_step_upgrade_requires_completed_install(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package, mode="upgrade")

    with pytest.raises(ExecutionError, match="not installed"):
        execute_runtime_step(
            plan["runtime"],
            log_file=tmp_path / "logs" / "runtime.log",
            prefix_override=str(prefix),
        )


def test_execute_runtime_step_upgrade_sets_installed_version(tmp_path: Path):
    package = _write_runtime_package(
        tmp_path / "pkg",
        install_body=(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$DBPM_INSTALLED_VERSION\" > \"$DBPM_RUNTIME_PREFIX/installed.txt\"\n"
        ),
    )
    prefix = _prefix(tmp_path)
    log_dir = tmp_path / "logs"
    execute_runtime_step(
        _runtime_plan(package)["runtime"], log_file=log_dir / "a.log", prefix_override=str(prefix)
    )

    upgraded = _write_runtime_package(
        tmp_path / "pkg",
        version="1.1.0",
        install_body=(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$DBPM_INSTALLED_VERSION\" > \"$DBPM_RUNTIME_PREFIX/installed.txt\"\n"
        ),
    )
    plan = _runtime_plan(upgraded, mode="upgrade")
    execute_runtime_step(plan["runtime"], log_file=log_dir / "b.log", prefix_override=str(prefix))

    assert (prefix / "installed.txt").read_text(encoding="utf-8").strip() == "1.0.0"
    receipt = json.loads(receipt_path(prefix).read_text(encoding="utf-8"))
    assert receipt["packages"]["jc_runtime"]["version"] == "1.1.0"


def test_execute_runtime_step_blocks_same_version_upgrade_and_downgrade(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)
    log_dir = tmp_path / "logs"
    execute_runtime_step(
        _runtime_plan(package)["runtime"], log_file=log_dir / "a.log", prefix_override=str(prefix)
    )

    same = _runtime_plan(package, mode="upgrade")
    with pytest.raises(ExecutionError, match="already installed"):
        execute_runtime_step(same["runtime"], log_file=log_dir / "b.log", prefix_override=str(prefix))

    downgraded = _write_runtime_package(tmp_path / "pkg", version="0.9.0")
    plan = _runtime_plan(downgraded, mode="upgrade")
    with pytest.raises(ExecutionError, match="downgrade"):
        execute_runtime_step(plan["runtime"], log_file=log_dir / "c.log", prefix_override=str(prefix))


def test_execute_runtime_step_validate_requires_install_and_skips_receipt(tmp_path: Path):
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)
    log_dir = tmp_path / "logs"
    plan = _runtime_plan(package, mode="validate")

    with pytest.raises(ExecutionError, match="validate requires"):
        execute_runtime_step(plan["runtime"], log_file=log_dir / "a.log", prefix_override=str(prefix))

    execute_runtime_step(
        _runtime_plan(package)["runtime"], log_file=log_dir / "b.log", prefix_override=str(prefix)
    )
    before = receipt_path(prefix).read_text(encoding="utf-8")
    execute_runtime_step(plan["runtime"], log_file=log_dir / "c.log", prefix_override=str(prefix))
    assert receipt_path(prefix).read_text(encoding="utf-8") == before


def test_execute_plan_runs_runtime_only_plan_without_connect(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)

    execute_plan(plan, connect=None, runner="sqlplus", runtime_prefix=str(prefix))

    assert (prefix / "mode.txt").read_text(encoding="utf-8").strip() == "install"
    log_files = list((tmp_path / "logs").glob("*-runtime.log"))
    assert len(log_files) == 1


def test_execute_plan_restores_execute_bit_for_extracted_scripts(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    package = _write_runtime_package(tmp_path / "pkg")
    install = package / "os" / "dbpm" / "install.sh"
    install.chmod(0o644)
    prefix = _prefix(tmp_path)
    plan = _runtime_plan(package)

    execute_plan(plan, connect=None, runner="sqlplus", runtime_prefix=str(prefix))
    assert (prefix / "mode.txt").read_text(encoding="utf-8").strip() == "install"


def test_cli_install_upgrade_validate_runtime_only_package(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("DBPM_CONNECT", raising=False)
    monkeypatch.delenv("DBPM_CONNECT_NAME", raising=False)
    monkeypatch.delenv("JOB_CONTROL_HOME", raising=False)
    package = _write_runtime_package(tmp_path / "pkg")
    prefix = _prefix(tmp_path)

    assert cli.main(["install", str(package), "--runtime-prefix", str(prefix)]) == 0
    assert (prefix / "mode.txt").read_text(encoding="utf-8").strip() == "install"

    assert cli.main(["validate", str(package), "--runtime-prefix", str(prefix)]) == 0

    _write_runtime_package(tmp_path / "pkg", version="1.1.0")
    assert cli.main(["upgrade", str(package), "--runtime-prefix", str(prefix)]) == 0
    receipt = json.loads(receipt_path(prefix).read_text(encoding="utf-8"))
    assert receipt["packages"]["jc_runtime"]["version"] == "1.1.0"


def test_cli_install_runtime_only_requires_prefix(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("DBPM_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("DBPM_CONNECT", raising=False)
    monkeypatch.delenv("DBPM_CONNECT_NAME", raising=False)
    monkeypatch.delenv("JOB_CONTROL_HOME", raising=False)
    package = _write_runtime_package(tmp_path / "pkg")

    assert cli.main(["install", str(package)]) == 2
    captured = capsys.readouterr()
    assert "JOB_CONTROL_HOME" in captured.err


def test_cli_plan_shows_runtime_step(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("DBPM_CONNECT", raising=False)
    monkeypatch.delenv("DBPM_CONNECT_NAME", raising=False)
    package = _write_runtime_package(tmp_path / "pkg")

    assert cli.main(["plan", str(package)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["runtime"]["name"] == "job_control"
    assert plan["runtime"]["environment"]["DBPM_RUNTIME_MODE"] == "install"
