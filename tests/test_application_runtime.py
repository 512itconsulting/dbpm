import json
from pathlib import Path

import pytest

from dbpm.application_runtime import (
    APPLICATION_RECEIPT_SCHEMA,
    ActivatedRuntimeCommand,
    ApplicationRuntimePackage,
    ApplicationRuntimeReceipt,
    application_receipt_path,
    load_application_runtime_receipt,
    parse_application_runtime_receipt,
    write_application_runtime_receipt,
)
from dbpm.errors import ExecutionError


def _receipt() -> ApplicationRuntimeReceipt:
    return ApplicationRuntimeReceipt(
        application_name="warehouse_app",
        application_version="2.0.0",
        generation=3,
        activated_at="2026-07-25T18:04:00Z",
        lock_schema="dbpm.lock.v0",
        lock_checksum="sha256:abc123",
        packages=(
            ApplicationRuntimePackage(
                name="warehouse_app",
                version="2.0.0",
                path="packages/warehouse_app/2.0.0",
                commit="a" * 40,
                artifact_uri="https://example.invalid/warehouse_app.zip",
                artifact_checksum="abc123",
                artifact_checksum_alg="SHA-256",
            ),
            ApplicationRuntimePackage(
                name="job_control",
                version="1.1.0",
                path="packages/job_control/1.1.0",
                commit="b" * 40,
                artifact_uri="https://example.invalid/job_control.zip",
                artifact_checksum="def456",
                artifact_checksum_alg="SHA-256",
            ),
        ),
        commands=(
            ActivatedRuntimeCommand(
                name="job-control",
                package="job_control",
                export="job-control",
                target="packages/job_control/1.1.0/bin/job-control",
            ),
        ),
    )


def test_application_runtime_receipt_roundtrip(tmp_path: Path):
    receipt = _receipt()

    write_application_runtime_receipt(tmp_path, receipt)
    loaded = load_application_runtime_receipt(
        tmp_path,
        expected_application="warehouse_app",
    )

    assert loaded.as_dict() == receipt.as_dict()
    raw = json.loads(application_receipt_path(tmp_path).read_text(encoding="utf-8"))
    assert raw["schema"] == APPLICATION_RECEIPT_SCHEMA
    assert raw["generation"] == 3
    assert raw["commands"]["job-control"]["package"] == "job_control"


def test_application_runtime_receipt_rejects_wrong_application(tmp_path: Path):
    write_application_runtime_receipt(tmp_path, _receipt())

    with pytest.raises(ExecutionError, match="belongs to `warehouse_app`"):
        load_application_runtime_receipt(
            tmp_path,
            expected_application="another_app",
        )


def test_application_runtime_receipt_requires_root_in_packages():
    value = _receipt().as_dict()
    value["packages"].pop("warehouse_app")

    with pytest.raises(ExecutionError, match="do not contain root application"):
        parse_application_runtime_receipt(value)


def test_application_runtime_receipt_rejects_command_for_missing_package():
    value = _receipt().as_dict()
    value["commands"]["job-control"]["package"] = "missing"

    with pytest.raises(ExecutionError, match="references missing package"):
        parse_application_runtime_receipt(value)


def test_application_runtime_receipt_rejects_command_outside_package_payload():
    value = _receipt().as_dict()
    value["commands"]["job-control"]["target"] = (
        "packages/warehouse_app/2.0.0/bin/job-control"
    )

    with pytest.raises(ExecutionError, match="outside package"):
        parse_application_runtime_receipt(value)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("generation", 0, "positive integer"),
        ("generation", True, "positive integer"),
        ("schema", "dbpm.receipt.v0", "Unsupported"),
    ],
)
def test_application_runtime_receipt_rejects_invalid_top_level_fields(
    field: str,
    value: object,
    match: str,
):
    receipt = _receipt().as_dict()
    receipt[field] = value

    with pytest.raises(ExecutionError, match=match):
        parse_application_runtime_receipt(receipt)


def test_application_runtime_receipt_requires_complete_lock_identity():
    receipt = _receipt().as_dict()
    receipt["resolution"]["lock_checksum"] = None

    with pytest.raises(ExecutionError, match="both lock_schema and lock_checksum"):
        parse_application_runtime_receipt(receipt)


def test_application_runtime_receipt_rejects_unsafe_package_path():
    receipt = _receipt().as_dict()
    receipt["packages"]["job_control"]["path"] = "../job_control"

    with pytest.raises(ExecutionError, match="safe relative path"):
        parse_application_runtime_receipt(receipt)
