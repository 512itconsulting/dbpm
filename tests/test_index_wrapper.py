from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "index-package.sh"


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    (package / "dbpm-publish-receipt.json").write_text("{}\n", encoding="utf-8")
    return package


def _fake_dbpm(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "dbpm"
    executable.write_text(
        "#!/usr/bin/env sh\nprintf 'ARGS=%s\\n' \"$*\"\nprintf 'URL=%s\\n' \"$DBPM_REGISTRY_URL\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return bin_dir


def test_index_wrapper_requires_registry_token(tmp_path: Path):
    package = _package(tmp_path)
    env = {**os.environ, "PATH": f"{_fake_dbpm(tmp_path)}:{os.environ['PATH']}"}
    env.pop("DBPM_REGISTRY_TOKEN", None)

    result = subprocess.run([str(SCRIPT), str(package)], capture_output=True, text=True, env=env)

    assert result.returncode == 2
    assert "DBPM_REGISTRY_TOKEN is not set" in result.stderr


def test_index_wrapper_defaults_registry_and_forwards_arguments(tmp_path: Path):
    package = _package(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{_fake_dbpm(tmp_path)}:{os.environ['PATH']}",
        "DBPM_REGISTRY_TOKEN": "top-secret",
    }
    env.pop("DBPM_REGISTRY_URL", None)

    result = subprocess.run(
        [str(SCRIPT), str(package), "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert f"ARGS=registry index {package} --dry-run" in result.stdout
    assert "URL=https://dbpm.io" in result.stdout
    assert "top-secret" not in result.stdout + result.stderr
