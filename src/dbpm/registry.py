from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import SourceError
from .manifest import PackageManifest


DEFAULT_REGISTRY_URL = "https://dbpm.io"
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
PUBLISH_RECEIPT_SCHEMA_VERSION = "dbpm.publish-receipt.v1"


@dataclass(frozen=True)
class RegistrySource:
    package: str
    constraint: str


@dataclass(frozen=True)
class RegistryResolution:
    package: str
    version: str
    artifact_url: str
    artifact_checksum: str
    artifact_signature_url: str | None = None
    publisher_key_fingerprint: str | None = None
    core_minimum_version: str | None = None
    oracle_minimum_version: str | None = None
    warning: dict[str, Any] | None = None
    registry_url: str = DEFAULT_REGISTRY_URL
    source: RegistrySource | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


def registry_base_url(value: str | None = None) -> str:
    raw = value or os.environ.get("DBPM_REGISTRY_URL") or DEFAULT_REGISTRY_URL
    raw = raw.strip()
    if not raw:
        raise SourceError("Registry URL cannot be empty")
    if not raw.startswith(("http://", "https://")):
        raise SourceError("Registry URL must start with http:// or https://")
    return raw.rstrip("/")


def parse_registry_source(raw_source: str) -> RegistrySource:
    value = raw_source.removeprefix("registry:")
    if "@" not in value:
        raise SourceError(
            "Registry sources must use registry:<package>@<constraint>"
        )
    package, constraint = value.split("@", 1)
    if not package:
        raise SourceError("Registry source package is required")
    if not constraint:
        raise SourceError("Registry source constraint is required")
    return RegistrySource(package=package, constraint=constraint)


def resolve_registry_source(
    raw_source: str,
    *,
    registry_url: str | None = None,
) -> RegistryResolution:
    source = parse_registry_source(raw_source)
    base_url = registry_base_url(registry_url)
    query = urllib.parse.urlencode(
        {
            "package": source.package,
            "constraint": source.constraint,
        }
    )
    url = f"{base_url}/resolve?{query}"
    payload = _get_json(url)
    return _resolution_from_payload(
        payload,
        registry_url=base_url,
        source=source,
    )


def load_publish_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceError(f"Publish receipt does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SourceError(f"Invalid publish receipt JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PUBLISH_RECEIPT_SCHEMA_VERSION:
        raise SourceError(f"Unsupported publish receipt schema: {path}")
    return payload


def create_registry_index_payload(
    manifest: PackageManifest,
    *,
    receipt: dict[str, Any] | None = None,
    publisher: str | None = None,
    description: str | None = None,
    artifact_url: str | None = None,
    artifact_checksum: str | None = None,
    artifact_signature_url: str | None = None,
    publisher_key_fingerprint: str | None = None,
) -> dict[str, object]:
    receipt = receipt or {}
    package = _mapping(receipt.get("package"))
    artifact = _mapping(receipt.get("artifact"))
    if package:
        if package.get("name") != manifest.name or package.get("version") != manifest.version:
            raise SourceError(
                "Publish receipt package identity does not match the current manifest"
            )

    resolved_publisher = publisher or os.environ.get("DBPM_REGISTRY_PUBLISHER") or manifest.vendor
    resolved_description = (
        description or os.environ.get("DBPM_REGISTRY_DESCRIPTION") or manifest.description
    )
    resolved_url = artifact_url or _string(artifact.get("url"))
    resolved_checksum = artifact_checksum or _string(artifact.get("checksum"))
    resolved_signature = artifact_signature_url or _string(artifact.get("signature_url"))
    resolved_fingerprint = (
        publisher_key_fingerprint or _string(artifact.get("publisher_key_fingerprint"))
    )

    missing = [
        name
        for name, value in (
            ("publisher", resolved_publisher),
            ("description", resolved_description),
            ("artifact_url", resolved_url),
            ("artifact_checksum", resolved_checksum),
        )
        if not value
    ]
    if missing:
        raise SourceError(f"Registry index metadata is missing: {', '.join(missing)}")
    if not str(resolved_url).startswith(("http://", "https://")):
        raise SourceError("Registry index artifact_url must start with http:// or https://")
    checksum = normalize_sha256(resolved_checksum)
    if bool(resolved_signature) != bool(resolved_fingerprint):
        raise SourceError(
            "artifact_signature_url and publisher_key_fingerprint must be supplied together"
        )

    payload: dict[str, object] = {
        "publisher": resolved_publisher,
        "description": resolved_description,
        "version": manifest.version,
        "artifact_url": resolved_url,
        "artifact_checksum": f"sha256:{checksum}",
        "status": "active",
        "dependencies": [
            {"name": dependency.name, "constraint": dependency.version}
            for dependency in manifest.dependencies
            if dependency.name.casefold() != "core"
        ],
    }
    optional = {
        "artifact_signature_url": resolved_signature,
        "publisher_key_fingerprint": resolved_fingerprint,
        "core_minimum_version": manifest.core_minimum_version,
        "oracle_minimum_version": manifest.database_minimum_version,
        "published_at": _string(receipt.get("published_at")),
    }
    payload.update({key: value for key, value in optional.items() if value is not None})
    return payload


def index_registry_version(
    package_name: str,
    payload: dict[str, object],
    *,
    registry_url: str | None = None,
    token: str,
) -> dict[str, Any]:
    url = f"{registry_base_url(registry_url)}/packages/{urllib.parse.quote(package_name)}/versions/index"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _registry_http_error(exc) from exc
    except OSError as exc:
        raise SourceError(f"Registry index failed: {url} ({exc})") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceError(f"Registry index response was not valid JSON: {url}") from exc
    if not isinstance(result, dict):
        raise SourceError(f"Registry index response must be a JSON object: {url}")
    return result


def normalize_sha256(value: object) -> str:
    if not isinstance(value, str):
        raise SourceError("Registry resolve response is missing artifact_checksum")
    match = _SHA256_RE.match(value)
    if match is None:
        raise SourceError(
            "Registry resolve response artifact_checksum must be SHA-256 "
            "as sha256:<hex> or raw 64-character hex"
        )
    return match.group(1).lower()


def _get_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url)) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise _registry_http_error(exc) from exc
    except OSError as exc:
        raise SourceError(f"Failed to resolve registry source: {url} ({exc})") from exc

    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise SourceError(f"Registry resolve response was not valid JSON: {url}") from exc
    if not isinstance(payload, dict):
        raise SourceError(f"Registry resolve response must be a JSON object: {url}")
    return payload


def _registry_http_error(exc: urllib.error.HTTPError) -> SourceError:
    detail = None
    try:
        body = exc.read().decode("utf-8")
        payload = json.loads(body)
        if isinstance(payload, dict):
            detail = payload.get("detail")
    except Exception:
        detail = None

    code = None
    message = None
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message") or detail.get("detail")
    elif isinstance(detail, str):
        message = detail

    suffix = f": {code}" if isinstance(code, str) else ""
    if isinstance(message, str) and message:
        suffix = f"{suffix} ({message})"
    return SourceError(f"Registry request failed with HTTP {exc.code} {exc.reason}{suffix}")


def _resolution_from_payload(
    payload: dict[str, Any],
    *,
    registry_url: str,
    source: RegistrySource | None,
) -> RegistryResolution:
    package = _required_str(payload, "package")
    version = _required_str(payload, "version")
    artifact_url = _required_str(payload, "artifact_url")
    artifact_checksum = normalize_sha256(payload.get("artifact_checksum"))
    if not artifact_url.startswith(("http://", "https://")):
        raise SourceError("Registry resolve response artifact_url must start with http:// or https://")

    warning = payload.get("warning")
    warnings = [warning] if isinstance(warning, dict) else []
    return RegistryResolution(
        package=package,
        version=version,
        artifact_url=artifact_url,
        artifact_checksum=artifact_checksum,
        artifact_signature_url=_optional_str(payload, "artifact_signature_url"),
        publisher_key_fingerprint=_optional_str(payload, "publisher_key_fingerprint"),
        core_minimum_version=_optional_str(payload, "core_minimum_version"),
        oracle_minimum_version=_optional_str(payload, "oracle_minimum_version"),
        warning=warning if isinstance(warning, dict) else None,
        registry_url=registry_url,
        source=source,
        warnings=warnings,
    )


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SourceError(f"Registry resolve response is missing {key}")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
