from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from dbpm.lockfile import (
    assert_database_matches_lockfile,
    assert_database_provenance_matches_lockfile,
    assert_database_states_match_lockfile,
    assert_lockfile_matches_plan,
    create_lockfile,
    deployment_provenance_requests,
    load_lockfile,
    write_lockfile,
)
from dbpm.planner import create_plan
from dbpm.provenance import resolve_provenance
from dbpm.source import load_package_source
from dbpm.environment import resolve_environment


def _write_zip(path: Path, *, version: str = "0.1.0") -> None:
    manifest = f"""
package:
  name: demo
  version: "{version}"

core:
  minimum_version: "3.0.0"

scripts:
  install: deploy.sql
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dbpm.yaml", manifest)
        archive.writestr("deploy.sql", "prompt deploy\n")


def _plan_for_zip(path: Path, *, installed_state: dict[str, str] | None = None) -> dict[str, object]:
    source = load_package_source(str(path))
    return create_plan(
        mode="install",
        source=source,
        provenance=resolve_provenance(source),
        environment=resolve_environment("development"),
        installed_state=installed_state,
    )


def test_create_lockfile_records_artifact_checksum(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)

    lockfile = create_lockfile(_plan_for_zip(artifact))

    package = lockfile["packages"][0]
    assert lockfile["schema_version"] == "dbpm.lock.v0"
    assert lockfile["execution_order"] == ["DEMO"]
    assert package["application_name"] == "DEMO"
    assert package["artifact"]["checksum_alg"] == "SHA-256"
    assert len(package["artifact"]["checksum"]) == 64


def test_write_load_and_check_lockfile(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    lock_path = tmp_path / "dbpm-lock.json"
    _write_zip(artifact)
    plan = _plan_for_zip(artifact)
    lockfile = create_lockfile(plan)

    write_lockfile(lockfile, lock_path)

    assert_lockfile_matches_plan(load_lockfile(lock_path), plan)


def test_check_lockfile_rejects_changed_artifact(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))
    artifact.unlink()
    _write_zip(artifact, version="0.1.1")

    with pytest.raises(Exception, match="version mismatch|checksum mismatch"):
        assert_lockfile_matches_plan(lockfile, _plan_for_zip(artifact))


def test_database_match_requires_complete_installed_version(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))
    plan = _plan_for_zip(
        artifact,
        installed_state={
            "application_name": "DEMO",
            "version": "0.1.0",
            "deploy_status": "C",
            "deploy_commit_hash": "abc",
        },
    )

    assert_database_matches_lockfile(lockfile, plan)


def test_database_match_rejects_missing_install(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    plan = _plan_for_zip(artifact)
    lockfile = create_lockfile(plan)

    with pytest.raises(Exception, match="DEMO is not installed"):
        assert_database_matches_lockfile(lockfile, plan)


def test_database_states_match_lockfile(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))

    assert_database_states_match_lockfile(
        lockfile,
        {
            "DEMO": {
                "application_name": "DEMO",
                "version": "0.1.0",
                "deploy_status": "C",
                "deploy_commit_hash": "abc",
            }
        },
    )


def test_database_states_match_lockfile_rejects_missing_install(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))

    with pytest.raises(Exception, match="DEMO is not installed"):
        assert_database_states_match_lockfile(lockfile, {"DEMO": None})


def test_deployment_provenance_requests(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))

    assert deployment_provenance_requests(lockfile) == [("DEMO", "0.1.0")]


def test_database_provenance_match_accepts_matching_row(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))
    package = lockfile["packages"][0]

    assert_database_provenance_matches_lockfile(
        lockfile,
        {
            "DEMO": {
                "major_version": 0,
                "minor_version": 1,
                "patch_version": 0,
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
        },
    )


def test_database_provenance_match_rejects_mismatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))
    artifact = tmp_path / "demo.zip"
    _write_zip(artifact)
    lockfile = create_lockfile(_plan_for_zip(artifact))

    with pytest.raises(Exception, match="DEMO provenance artifact_checksum mismatch"):
        assert_database_provenance_matches_lockfile(
            lockfile,
            {
                "DEMO": {
                    "major_version": 0,
                    "minor_version": 1,
                    "patch_version": 0,
                    "artifact_checksum": "not-the-checksum",
                }
            },
        )
