import json
from pathlib import Path

import pytest

from dbpm.environment import resolve_deployment_policy
from dbpm.errors import ExecutionError, ManifestError
from dbpm.executor import execute_plan
from dbpm.manifest import parse_manifest
from dbpm.planner import create_application_runtime_graph_plan, create_plan
from dbpm.provenance import resolve_provenance
from dbpm.source import load_package_source


def test_manifest_parses_runtime_exports_and_activation():
    manifest = parse_manifest(
        """
package:
  name: warehouse_app
  version: "2.0.0"

runtime:
  scripts:
    install: os/dbpm/install.sh
    validate: os/dbpm/validate.sh
  exports:
    commands:
      warehouse-run: bin/warehouse-run
  activation:
    commands:
      aliases:
        job_control.job-control: warehouse-jobs
      disabled:
        - warehouse_loads.load-now
""",
        "dbpm.yaml",
    )

    runtime = manifest.runtime
    assert runtime is not None
    assert runtime.install == "os/dbpm/install.sh"
    assert runtime.validate == "os/dbpm/validate.sh"
    assert [(item.name, item.target) for item in runtime.command_exports] == [
        ("warehouse-run", "bin/warehouse-run")
    ]
    assert [(item.export, item.name) for item in runtime.command_aliases] == [
        ("job_control.job-control", "warehouse-jobs")
    ]
    assert runtime.disabled_commands == ("warehouse_loads.load-now",)


def test_manifest_allows_activation_only_root_runtime():
    manifest = parse_manifest(
        """
package:
  name: warehouse_app
  version: "1.0.0"

runtime:
  activation:
    commands:
      aliases:
        job_control.job-control: warehouse-jobs
""",
        "dbpm.yaml",
    )

    assert manifest.runtime is not None
    assert manifest.runtime.install is None
    assert manifest.runtime.command_exports == ()


@pytest.mark.parametrize("removed_field", ["name", "home_env", "into", "layout"])
def test_manifest_rejects_removed_runtime_fields(removed_field: str):
    with pytest.raises(ManifestError, match=f"runtime.{removed_field}"):
        parse_manifest(
            f"""
package:
  name: demo
  version: "1.0.0"

runtime:
  {removed_field}: removed
""",
            "dbpm.yaml",
        )


def test_manifest_requires_install_script_for_command_exports():
    with pytest.raises(ManifestError, match="runtime.scripts.install"):
        parse_manifest(
            """
package:
  name: tools
  version: "1.0.0"

runtime:
  exports:
    commands:
      tool: bin/tool
""",
            "dbpm.yaml",
        )


@pytest.mark.parametrize("target", ["../bin/demo", "/opt/demo", "C:/demo"])
def test_manifest_rejects_unsafe_runtime_export_target(target: str):
    with pytest.raises(ManifestError, match="package-relative"):
        parse_manifest(
            json.dumps(
                {
                    "package": {"name": "demo", "version": "1.0.0"},
                    "runtime": {
                        "scripts": {"install": "install.sh"},
                        "exports": {"commands": {"demo": target}},
                    },
                }
            ),
            "dbpm.json",
        )


def test_manifest_rejects_invalid_canonical_activation_reference():
    with pytest.raises(ManifestError, match="canonical"):
        parse_manifest(
            """
package:
  name: demo
  version: "1.0.0"

runtime:
  activation:
    commands:
      disabled:
        - not-canonical
""",
            "dbpm.yaml",
        )


def test_manifest_rejects_command_that_is_aliased_and_disabled():
    with pytest.raises(ManifestError, match="both aliased and disabled"):
        parse_manifest(
            """
package:
  name: demo
  version: "1.0.0"

runtime:
  activation:
    commands:
      aliases:
        tools.tool: renamed-tool
      disabled:
        - tools.tool
""",
            "dbpm.yaml",
        )


def test_planner_includes_read_only_application_runtime_graph(tmp_path: Path):
    package = _write_runtime_package(
        tmp_path / "pkg",
        package="demo",
        version="1.0.0",
        command="demo",
    )
    source = load_package_source(str(package))

    plan = create_plan(
        mode="install",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_deployment_policy(None),
    )

    assert plan["runtime_package"]["payload_path"] == "packages/demo/1.0.0"
    assert plan["application_runtime"]["commands"] == [
        {
            "name": "demo",
            "canonical": "demo.demo",
            "package": "demo",
            "export": "demo",
            "target": "packages/demo/1.0.0/bin/demo",
            "link": "bin/demo",
        }
    ]

    with pytest.raises(ExecutionError, match="plan is read-only"):
        execute_plan(plan, connect=None, runner="sqlplus")


def test_application_runtime_graph_uses_root_aliases_and_disabled_exports():
    dependency = _runtime_package_plan(
        "job_control",
        "1.1.0",
        {"job-control": "bin/job-control", "jc-admin": "bin/jc-admin"},
    )
    root = _runtime_package_plan(
        "warehouse_app",
        "2.0.0",
        {"warehouse-run": "bin/warehouse-run"},
        aliases={"job_control.job-control": "warehouse-jobs"},
        disabled=["job_control.jc-admin"],
    )

    graph = create_application_runtime_graph_plan(
        [dependency, root],
        root_package_name="warehouse_app",
        root_package_version="2.0.0",
    )

    assert [command["name"] for command in graph["commands"]] == [
        "warehouse-jobs",
        "warehouse-run",
    ]
    assert graph["commands"][0]["target"] == (
        "packages/job_control/1.1.0/bin/job-control"
    )


def test_application_runtime_graph_rejects_command_collision():
    first = _runtime_package_plan("first", "1.0.0", {"run": "bin/run"})
    second = _runtime_package_plan("second", "1.0.0", {"run": "bin/run"})

    with pytest.raises(ManifestError, match="command name collision"):
        create_application_runtime_graph_plan(
            [first, second],
            root_package_name="second",
            root_package_version="1.0.0",
        )


def test_application_runtime_graph_rejects_unknown_activation_reference():
    root = _runtime_package_plan(
        "demo",
        "1.0.0",
        {"demo": "bin/demo"},
        aliases={"missing.command": "other"},
    )

    with pytest.raises(ManifestError, match="unknown command exports"):
        create_application_runtime_graph_plan(
            [root],
            root_package_name="demo",
            root_package_version="1.0.0",
        )


def _write_runtime_package(
    path: Path,
    *,
    package: str,
    version: str,
    command: str,
) -> Path:
    path.mkdir(parents=True)
    (path / "dbpm.yaml").write_text(
        f"""
package:
  name: {package}
  version: "{version}"

runtime:
  scripts:
    install: install.sh
  exports:
    commands:
      {command}: bin/{command}
""",
        encoding="utf-8",
    )
    install = path / "install.sh"
    install.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    install.chmod(0o755)
    return path


def _runtime_package_plan(
    package: str,
    version: str,
    commands: dict[str, str],
    *,
    aliases: dict[str, str] | None = None,
    disabled: list[str] | None = None,
) -> dict[str, object]:
    return {
        "package": {"name": package, "version": version},
        "runtime_package": {
            "package": package,
            "version": version,
            "payload_path": f"packages/{package}/{version}",
            "exports": {
                "commands": [
                    {
                        "name": name,
                        "target": target,
                        "canonical": f"{package}.{name}",
                    }
                    for name, target in commands.items()
                ]
            },
            "activation": {
                "commands": {
                    "aliases": aliases or {},
                    "disabled": disabled or [],
                }
            },
        },
    }
