from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from zipfile import ZipFile

import pytest

from dbpm.errors import SourceError
from dbpm.registry import (
    RegistryResolution,
    RegistrySource,
    normalize_sha256,
    parse_registry_source,
    resolve_registry_source,
)
from dbpm.source import load_package_source


class _Response:
    def __init__(self, payload: object):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def _write_zip(path: Path, name: str, version: str, dependencies: str = "") -> None:
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


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DBPM_CACHE_DIR", str(tmp_path / "cache"))


def test_parse_registry_source_accepts_package_and_constraint():
    parsed = parse_registry_source("registry:utl_interval@^1.0.0")

    assert parsed.package == "utl_interval"
    assert parsed.constraint == "^1.0.0"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("registry:utl_interval", "must use"),
        ("registry:@^1.0.0", "package is required"),
        ("registry:utl_interval@", "constraint is required"),
    ],
)
def test_parse_registry_source_rejects_invalid_values(raw: str, message: str):
    with pytest.raises(SourceError, match=message):
        parse_registry_source(raw)


def test_normalize_sha256_accepts_prefixed_and_raw_values():
    checksum = "a" * 64

    assert normalize_sha256(f"sha256:{checksum}") == checksum
    assert normalize_sha256(checksum.upper()) == checksum


def test_normalize_sha256_rejects_unsupported_checksum_format():
    with pytest.raises(SourceError, match="artifact_checksum must be SHA-256"):
        normalize_sha256("md5:abc")


def test_resolve_registry_source_success(monkeypatch):
    requests: list[str] = []

    def fake_urlopen(request):
        requests.append(request.full_url)
        return _Response(
            {
                "package": "utl_interval",
                "version": "1.2.3",
                "artifact_url": "https://repo.example/utl_interval-1.2.3.zip",
                "artifact_checksum": "sha256:" + "a" * 64,
                "artifact_signature_url": "https://repo.example/utl_interval-1.2.3.zip.asc",
                "publisher_key_fingerprint": "FINGERPRINT",
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    resolved = resolve_registry_source(
        "registry:utl_interval@^1.0.0",
        registry_url="https://registry.example/root/",
    )

    assert requests == ["https://registry.example/root/resolve?package=utl_interval&constraint=%5E1.0.0"]
    assert resolved.artifact_checksum == "a" * 64
    assert resolved.artifact_signature_url == "https://repo.example/utl_interval-1.2.3.zip.asc"
    assert resolved.publisher_key_fingerprint == "FINGERPRINT"


@pytest.mark.parametrize("status", [404, 409, 422, 500])
def test_resolve_registry_source_raises_for_registry_http_errors(monkeypatch, status: int):
    def fake_urlopen(request):
        body = json.dumps({"detail": {"code": "registry_error", "message": "Nope"}}).encode("utf-8")
        raise urllib.error.HTTPError(request.full_url, status, "Error", {}, _Response(body))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(SourceError, match=f"HTTP {status} Error: registry_error"):
        resolve_registry_source("registry:utl_interval@^1.0.0", registry_url="https://registry.example")


def test_resolve_registry_source_rejects_malformed_json(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request: _Response(b"not json"))

    with pytest.raises(SourceError, match="not valid JSON"):
        resolve_registry_source("registry:utl_interval@^1.0.0", registry_url="https://registry.example")


def test_load_registry_source_downloads_and_preserves_registry_metadata(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "utl_interval.zip"
    _write_zip(fixture, "utl_interval", "1.2.3")
    checksum = "sha256:" + __import__("hashlib").sha256(fixture.read_bytes()).hexdigest()

    monkeypatch.setattr(
        "dbpm.source.resolve_registry_source",
        lambda raw, registry_url=None: RegistryResolution(
            package="utl_interval",
            version="1.2.3",
            artifact_url="https://repo.example/utl_interval-1.2.3.zip",
            artifact_checksum=checksum.removeprefix("sha256:"),
            artifact_signature_url="https://repo.example/utl_interval-1.2.3.zip.asc",
            publisher_key_fingerprint="FINGERPRINT",
            registry_url="https://registry.example",
            source=RegistrySource("utl_interval", "^1.0.0"),
            warnings=[{"code": "yanked_version"}],
        ),
    )

    downloads: list[str] = []

    def fake_download(url: str, destination: Path) -> None:
        downloads.append(url)
        if url.endswith(".asc"):
            destination.write_bytes(b"sig")
        else:
            destination.write_bytes(fixture.read_bytes())

    monkeypatch.setattr("dbpm.source._download", fake_download)
    monkeypatch.setattr("dbpm.source._check_gpg_signature", lambda *args: None)

    source = load_package_source("registry:utl_interval@^1.0.0")

    assert downloads == [
        "https://repo.example/utl_interval-1.2.3.zip",
        "https://repo.example/utl_interval-1.2.3.zip.asc",
    ]
    assert source.manifest.name == "utl_interval"
    assert source.registry_url == "https://registry.example"
    assert source.registry_package == "utl_interval"
    assert source.registry_constraint == "^1.0.0"
    assert source.artifact_signature_url == "https://repo.example/utl_interval-1.2.3.zip.asc"
    assert source.publisher_key_fingerprint == "FINGERPRINT"
    assert source.warnings == [{"code": "yanked_version"}]


def test_load_registry_source_fails_on_checksum_mismatch(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "utl_interval.zip"
    _write_zip(fixture, "utl_interval", "1.2.3")

    monkeypatch.setattr(
        "dbpm.source.resolve_registry_source",
        lambda raw, registry_url=None: RegistryResolution(
            package="utl_interval",
            version="1.2.3",
            artifact_url="https://repo.example/utl_interval-1.2.3.zip",
            artifact_checksum="a" * 64,
            registry_url="https://registry.example",
            source=RegistrySource("utl_interval", "^1.0.0"),
        ),
    )
    monkeypatch.setattr(
        "dbpm.source._download",
        lambda url, destination: destination.write_bytes(fixture.read_bytes()),
    )

    with pytest.raises(SourceError, match="Checksum mismatch"):
        load_package_source("registry:utl_interval@^1.0.0")
