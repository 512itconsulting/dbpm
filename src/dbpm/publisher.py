from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from .errors import PublishError
from .manifest import PackageManifest, PublishConfig
from .source import _artifact_cache_dir, _sha256, _tree_files


@dataclass(frozen=True)
class PublishReceipt:
    artifact_url: str
    checksum: str
    signature_url: str


def build_artifact(source_path: Path, manifest: PackageManifest, publish_config: PublishConfig) -> Path:
    artifact_id = publish_config.artifact_id or manifest.name
    version = manifest.version
    zip_name = f"{artifact_id}-{version}.zip"
    zip_root = f"{artifact_id}-{version}"

    output_dir = (
        _artifact_cache_dir()
        / "publish"
        / publish_config.group.replace(".", "/")
        / artifact_id
        / version
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / zip_name

    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    properties = _build_properties(
        group=publish_config.group,
        artifact_id=artifact_id,
        version=version,
        build_time=build_time,
        git_metadata=_git_metadata(source_path),
    )

    files = _tree_files(source_path)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            relative = file_path.relative_to(source_path).as_posix()
            archive.write(file_path, f"{zip_root}/{relative}")
        archive.writestr(f"{zip_root}/META-INF/{artifact_id}-build.properties", properties)

    return output_path


def generate_pom(manifest: PackageManifest, publish_config: PublishConfig) -> str:
    artifact_id = publish_config.artifact_id or manifest.name
    group = publish_config.group
    version = manifest.version

    deps_xml = ""
    for dep in manifest.dependencies:
        deps_xml += (
            f"    <dependency>\n"
            f"      <groupId>{_xml_escape(group)}</groupId>\n"
            f"      <artifactId>{_xml_escape(dep.name)}</artifactId>\n"
            f"      <version>{_xml_escape(dep.version)}</version>\n"
            f"    </dependency>\n"
        )

    description_block = (
        f"  <description>{_xml_escape(manifest.description)}</description>\n"
        if manifest.description
        else ""
    )
    deps_block = f"  <dependencies>\n{deps_xml}  </dependencies>\n" if deps_xml else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"  <groupId>{_xml_escape(group)}</groupId>\n"
        f"  <artifactId>{_xml_escape(artifact_id)}</artifactId>\n"
        f"  <version>{_xml_escape(version)}</version>\n"
        "  <packaging>zip</packaging>\n"
        + description_block
        + deps_block
        + "</project>\n"
    )


def sign_artifact(artifact_path: Path, key_id: str) -> Path:
    asc_path = artifact_path.with_suffix(artifact_path.suffix + ".asc")
    try:
        result = subprocess.run(
            [
                "gpg",
                "--batch",
                "--yes",
                "--detach-sign",
                "--armor",
                "--local-user",
                key_id,
                "--output",
                str(asc_path),
                str(artifact_path),
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise PublishError("GPG is not installed or not on PATH") from exc
    if result.returncode != 0:
        raise PublishError(f"GPG signing failed: {result.stderr.strip()}")
    return asc_path


def publish_to_repository(
    target: str,
    manifest: PackageManifest,
    publish_config: PublishConfig,
    artifact_path: Path,
    signing_key: str,
) -> PublishReceipt:
    target_info = _parse_publish_target(target)
    artifact_id = publish_config.artifact_id or manifest.name
    version = manifest.version
    repository_url = target_info["repository_url"]
    group_path = publish_config.group.replace(".", "/")
    base_url = f"{repository_url.rstrip('/')}/{group_path}/{artifact_id}/{version}"

    artifact_name = artifact_path.name
    artifact_url = f"{base_url}/{artifact_name}"
    signature_url = f"{artifact_url}.asc"

    sha256 = _sha256(artifact_path)
    sha1 = _sha1(artifact_path)

    asc_path = sign_artifact(artifact_path, signing_key)

    pom_content = generate_pom(manifest, publish_config)
    pom_name = f"{artifact_id}-{version}.pom"
    pom_url = f"{base_url}/{pom_name}"
    pom_bytes = pom_content.encode("utf-8")
    pom_sha256 = hashlib.sha256(pom_bytes).hexdigest()
    pom_sha1 = hashlib.sha1(pom_bytes).hexdigest()

    token = _resolve_token(target_info)

    _upload(artifact_url, artifact_path.read_bytes(), "application/zip", token)
    _upload(f"{artifact_url}.sha256", sha256.encode("utf-8"), "text/plain", token)
    _upload(f"{artifact_url}.sha1", sha1.encode("utf-8"), "text/plain", token)
    _upload(signature_url, asc_path.read_bytes(), "text/plain", token)

    _upload(pom_url, pom_bytes, "application/xml", token)
    _upload(f"{pom_url}.sha256", pom_sha256.encode("utf-8"), "text/plain", token)
    _upload(f"{pom_url}.sha1", pom_sha1.encode("utf-8"), "text/plain", token)

    metadata_url = f"{repository_url.rstrip('/')}/{group_path}/{artifact_id}/maven-metadata.xml"
    metadata_bytes = _build_updated_metadata(
        metadata_url, publish_config.group, artifact_id, version, token
    )
    metadata_sha256 = hashlib.sha256(metadata_bytes).hexdigest()
    metadata_sha1 = hashlib.sha1(metadata_bytes).hexdigest()
    _upload(metadata_url, metadata_bytes, "application/xml", token)
    _upload(f"{metadata_url}.sha256", metadata_sha256.encode("utf-8"), "text/plain", token)
    _upload(f"{metadata_url}.sha1", metadata_sha1.encode("utf-8"), "text/plain", token)

    return PublishReceipt(
        artifact_url=artifact_url,
        checksum=sha256,
        signature_url=signature_url,
    )


def verify_publish(
    target: str,
    manifest: PackageManifest,
    publish_config: PublishConfig,
    version: str,
    expected_checksum: str,
) -> None:
    target_info = _parse_publish_target(target)
    artifact_id = publish_config.artifact_id or manifest.name
    repository_url = target_info["repository_url"]
    group_path = publish_config.group.replace(".", "/")
    base_url = repository_url.rstrip("/")

    metadata_url = f"{base_url}/{group_path}/{artifact_id}/maven-metadata.xml"
    token = _resolve_token(target_info)
    try:
        metadata_text = _download_text(metadata_url, token)
    except PublishError as exc:
        raise PublishError(f"Post-publish verification failed: {exc}") from exc

    try:
        root = ElementTree.fromstring(metadata_text)
    except ElementTree.ParseError as exc:
        raise PublishError(f"Invalid maven-metadata.xml at {metadata_url}") from exc

    versions = [
        el.text
        for el in root.findall("./versioning/versions/version")
        if el.text
    ]
    if version not in versions:
        raise PublishError(
            f"Version {version} not found in maven-metadata.xml after publish"
        )

    artifact_name = f"{artifact_id}-{version}.zip"
    artifact_url = f"{base_url}/{group_path}/{artifact_id}/{version}/{artifact_name}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / artifact_name
        _download_to_file(artifact_url, tmp_path, token)
        actual = _sha256(tmp_path)

    if actual != expected_checksum:
        raise PublishError(
            f"Post-publish checksum mismatch for {artifact_name}: "
            f"expected {expected_checksum}, got {actual}"
        )


def _parse_publish_target(target: str) -> dict[str, str]:
    if target.startswith("gh-maven:"):
        value = target.removeprefix("gh-maven:")
        if "/" not in value:
            raise PublishError("GitHub Maven target must use gh-maven:owner/repo")
        owner, repo = value.split("/", 1)
        return {
            "type": "github",
            "owner": owner,
            "repo": repo,
            "repository_url": f"https://maven.pkg.github.com/{owner}/{repo}/",
        }
    if target.startswith("maven:"):
        value = target.removeprefix("maven:")
        if not value.startswith(("http://", "https://")):
            raise PublishError("Maven target URL must start with http:// or https://")
        return {
            "type": "maven",
            "repository_url": value if value.endswith("/") else value + "/",
        }
    raise PublishError(
        f"Unsupported publish target: {target!r}. "
        "Use gh-maven:owner/repo or maven:https://..."
    )


def _resolve_token(target_info: dict[str, str]) -> str | None:
    if target_info["type"] == "github":
        return os.environ.get("DBPM_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return os.environ.get("DBPM_MAVEN_TOKEN")


def _upload(url: str, data: bytes, content_type: str, token: str | None) -> None:
    request = urllib.request.Request(url, data=data, method="PUT")
    request.add_header("Content-Type", content_type)
    if token:
        user = os.environ.get("DBPM_MAVEN_USER") or os.environ.get("DBPM_GITHUB_USER") or "x-access-token"
        credential = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credential}")
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise PublishError(
            f"Upload failed: {url} (HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise PublishError(f"Upload failed: {url} ({exc})") from exc


def _fetch_text_or_none(url: str, token: str | None) -> str | None:
    """Fetch URL as text, returning None on 404. Raises PublishError for all other failures."""
    request = urllib.request.Request(url)
    if token:
        user = os.environ.get("DBPM_MAVEN_USER") or os.environ.get("DBPM_GITHUB_USER") or "x-access-token"
        credential = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credential}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise PublishError(
            f"Failed to fetch {url} (HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise PublishError(f"Failed to fetch {url} ({exc})") from exc


def _download_text(url: str, token: str | None) -> str:
    request = urllib.request.Request(url)
    if token:
        user = os.environ.get("DBPM_MAVEN_USER") or os.environ.get("DBPM_GITHUB_USER") or "x-access-token"
        credential = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credential}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise PublishError(
            f"Failed to fetch {url} (HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise PublishError(f"Failed to fetch {url} ({exc})") from exc


def _download_to_file(url: str, destination: Path, token: str | None) -> None:
    import shutil

    request = urllib.request.Request(url)
    if token:
        user = os.environ.get("DBPM_MAVEN_USER") or os.environ.get("DBPM_GITHUB_USER") or "x-access-token"
        credential = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credential}")
    try:
        with urllib.request.urlopen(request) as response:
            with destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise PublishError(
            f"Failed to download {url} (HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise PublishError(f"Failed to download {url} ({exc})") from exc


def _build_updated_metadata(
    metadata_url: str,
    group: str,
    artifact_id: str,
    version: str,
    token: str | None,
) -> bytes:
    last_updated = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    existing_text = _fetch_text_or_none(metadata_url, token)
    if existing_text is None:
        existing_versions = []
    else:
        try:
            root = ElementTree.fromstring(existing_text)
            versions_el = root.find("./versioning/versions")
            existing_versions = [
                el.text for el in (versions_el if versions_el is not None else []) if el.text  # type: ignore[arg-type]
            ]
        except ElementTree.ParseError as exc:
            raise PublishError(
                f"Failed to parse existing maven-metadata.xml at {metadata_url}"
            ) from exc

    if version not in existing_versions:
        existing_versions.append(version)

    versions_xml = "".join(f"      <version>{_xml_escape(v)}</version>\n" for v in existing_versions)
    release = existing_versions[-1]

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<metadata>\n"
        f"  <groupId>{_xml_escape(group)}</groupId>\n"
        f"  <artifactId>{_xml_escape(artifact_id)}</artifactId>\n"
        "  <versioning>\n"
        f"    <release>{_xml_escape(release)}</release>\n"
        "    <versions>\n"
        + versions_xml
        + "    </versions>\n"
        f"    <lastUpdated>{last_updated}</lastUpdated>\n"
        "  </versioning>\n"
        "</metadata>\n"
    )
    return content.encode("utf-8")


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_properties(
    *,
    group: str,
    artifact_id: str,
    version: str,
    build_time: str,
    git_metadata: dict[str, str],
) -> str:
    values = {
        "artifact.groupId": group,
        "artifact.artifactId": artifact_id,
        "artifact.version": version,
        "artifact.extension": "zip",
        "build.version": version,
        "build.time": build_time,
        "build.source": "dbpm",
        "git.commit.id": git_metadata.get("git.commit.id", ""),
        "git.commit.id.abbrev": git_metadata.get("git.commit.id.abbrev", ""),
        "git.branch": git_metadata.get("git.branch", ""),
        "git.dirty": git_metadata.get("git.dirty", ""),
    }
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _git_metadata(source_path: Path) -> dict[str, str]:
    commit = _git(source_path, "rev-parse", "HEAD")
    abbrev = _git(source_path, "rev-parse", "--short", "HEAD")
    branch = _git(source_path, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(source_path, "status", "--porcelain")
    if abbrev is None and commit:
        abbrev = commit[:7]
    return {
        "git.commit.id": commit or "",
        "git.commit.id.abbrev": abbrev or "",
        "git.branch": branch or "",
        "git.dirty": "" if status is None else str(bool(status)).lower(),
    }


def _git(source_path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_path), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
