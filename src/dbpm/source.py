from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from xml.etree import ElementTree

from .errors import SourceError
from .manifest import MANIFEST_NAMES, PackageManifest, parse_manifest


TREE_CHECKSUM_ALG = "TREE-SHA-256"
TREE_CHECKSUM_EXCLUDES = (
    ".git",
    ".hg",
    ".svn",
    ".dbpm-cache*",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "target",
    "*.egg-info",
    "*.log",
)


@dataclass(frozen=True)
class PackageSource:
    path: Path
    source_type: str
    root: str | None
    manifest_name: str
    manifest: PackageManifest
    metadata: dict[str, str]
    artifact_checksum: str | None = None
    artifact_checksum_alg: str | None = None
    artifact_uri: str | None = None
    work_path: Path | None = None

    @property
    def display_path(self) -> str:
        return self.artifact_uri or str(self.path)

    @property
    def is_directory(self) -> bool:
        return self.source_type == "directory"

    @property
    def is_zip(self) -> bool:
        return self.source_type == "zip"

    def resolve_script_path(self, script_path: str) -> Path | str:
        if self.is_directory:
            return self.path / script_path
        if self.work_path is None:
            return f"{self.root.rstrip('/') + '/' if self.root else ''}{script_path}"
        return self.work_path / script_path


def load_package_source(
    raw_path: str,
    *,
    expected_checksum: str | None = None,
    expected_checksum_alg: str | None = None,
    expected_signature_url: str | None = None,
) -> PackageSource:
    sha256_expected = expected_checksum if expected_checksum_alg == "SHA-256" else None

    if raw_path.startswith("gh-maven:"):
        return _load_github_maven_source(
            raw_path, expected_checksum=sha256_expected, expected_signature_url=expected_signature_url
        )
    if raw_path.startswith("maven:"):
        return _load_maven_source(
            raw_path, expected_checksum=sha256_expected, expected_signature_url=expected_signature_url
        )
    if raw_path.startswith(("http://", "https://")):
        return _load_url_zip_source(
            raw_path, expected_checksum=sha256_expected, expected_signature_url=expected_signature_url
        )

    path = Path(raw_path).resolve()
    if path.is_dir():
        source = _load_directory_source(path)
    elif path.is_file() and path.suffix.lower() == ".zip":
        source = _load_zip_source(path)
    else:
        raise SourceError(f"Unsupported package source: {path}")

    if expected_checksum and source.artifact_checksum_alg == expected_checksum_alg:
        if source.artifact_checksum != expected_checksum:
            raise SourceError(
                f"Checksum mismatch for {path.name}: "
                f"expected {expected_checksum}, got {source.artifact_checksum}"
            )
    return source


def _load_directory_source(path: Path) -> PackageSource:
    manifest_path = next((path / name for name in MANIFEST_NAMES if (path / name).exists()), None)
    if manifest_path is None:
        raise SourceError(f"No dbpm manifest found in {path}")

    text = manifest_path.read_text(encoding="utf-8")
    manifest = parse_manifest(text, manifest_path.name)
    metadata = _read_directory_metadata(path)
    artifact_checksum = _tree_sha256(path)
    return PackageSource(
        path=path,
        source_type="directory",
        root=None,
        manifest_name=manifest_path.name,
        manifest=manifest,
        metadata=metadata,
        artifact_checksum=artifact_checksum,
        artifact_checksum_alg=TREE_CHECKSUM_ALG,
    )


def _load_zip_source(path: Path) -> PackageSource:
    artifact_checksum = _sha256(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest_member = _find_zip_manifest(names)
        if manifest_member is None:
            manifest_member = _find_zip_pom(names)
            if manifest_member is None:
                raise SourceError(f"No dbpm manifest found in {path}")
            manifest = _manifest_from_pom(
                archive.read(manifest_member).decode("utf-8"),
                manifest_member,
                names,
            )
        else:
            text = archive.read(manifest_member).decode("utf-8")
            manifest = parse_manifest(text, Path(manifest_member).name)
        metadata = _read_zip_metadata(archive)
        root = _zip_root(manifest_member)
        work_path = _extract_zip(archive, artifact_checksum, root)

    return PackageSource(
        path=path,
        source_type="zip",
        root=root,
        manifest_name=manifest_member,
        manifest=manifest,
        metadata=metadata,
        artifact_checksum=artifact_checksum,
        artifact_checksum_alg="SHA-256",
        work_path=work_path,
    )


def _load_github_maven_source(
    raw_source: str,
    *,
    expected_checksum: str | None = None,
    expected_signature_url: str | None = None,
) -> PackageSource:
    coordinate = _parse_github_maven_source(raw_source)
    repository_url = f"https://maven.pkg.github.com/{coordinate['owner']}/{coordinate['repo']}/"
    artifact_url = _maven_artifact_url(repository_url, coordinate)
    coord_cache = _artifact_cache_dir() / "maven" / coordinate["owner"] / coordinate["repo"]
    coord_cache = coord_cache / coordinate["group"].replace(".", "/") / coordinate["artifact"]
    artifact_file_name = Path(urllib.parse.urlparse(artifact_url).path).name
    coord_cache = coord_cache / coordinate["version"] / artifact_file_name
    zip_path = _resolve_remote_zip(artifact_url, coord_cache, expected_checksum, expected_signature_url)

    source = _load_zip_source(zip_path)
    return PackageSource(
        path=source.path,
        source_type=source.source_type,
        root=source.root,
        manifest_name=source.manifest_name,
        manifest=source.manifest,
        metadata=source.metadata,
        artifact_checksum=source.artifact_checksum,
        artifact_checksum_alg=source.artifact_checksum_alg,
        artifact_uri=artifact_url,
        work_path=source.work_path,
    )


def _load_maven_source(
    raw_source: str,
    *,
    expected_checksum: str | None = None,
    expected_signature_url: str | None = None,
) -> PackageSource:
    coordinate = _parse_maven_source(raw_source)
    artifact_url = _maven_artifact_url(coordinate["repository_url"], coordinate)
    repository_hash = hashlib.sha256(coordinate["repository_url"].encode("utf-8")).hexdigest()
    coord_cache = _artifact_cache_dir() / "maven-url" / repository_hash
    coord_cache = coord_cache / coordinate["group"].replace(".", "/") / coordinate["artifact"]
    artifact_file_name = Path(urllib.parse.urlparse(artifact_url).path).name
    coord_cache = coord_cache / coordinate["version"] / artifact_file_name
    zip_path = _resolve_remote_zip(artifact_url, coord_cache, expected_checksum, expected_signature_url)

    source = _load_zip_source(zip_path)
    return PackageSource(
        path=source.path,
        source_type=source.source_type,
        root=source.root,
        manifest_name=source.manifest_name,
        manifest=source.manifest,
        metadata=source.metadata,
        artifact_checksum=source.artifact_checksum,
        artifact_checksum_alg=source.artifact_checksum_alg,
        artifact_uri=artifact_url,
        work_path=source.work_path,
    )


def _load_url_zip_source(
    url: str,
    *,
    expected_checksum: str | None = None,
    expected_signature_url: str | None = None,
) -> PackageSource:
    artifact_file_name = Path(urllib.parse.urlparse(url).path).name
    if not artifact_file_name.lower().endswith(".zip"):
        raise SourceError(f"URL package sources must reference a ZIP artifact: {url}")
    coord_cache = _artifact_cache_dir() / "url" / hashlib.sha256(url.encode("utf-8")).hexdigest()
    coord_cache = coord_cache / artifact_file_name
    zip_path = _resolve_remote_zip(url, coord_cache, expected_checksum, expected_signature_url)

    source = _load_zip_source(zip_path)
    return PackageSource(
        path=source.path,
        source_type=source.source_type,
        root=source.root,
        manifest_name=source.manifest_name,
        manifest=source.manifest,
        metadata=source.metadata,
        artifact_checksum=source.artifact_checksum,
        artifact_checksum_alg=source.artifact_checksum_alg,
        artifact_uri=url,
        work_path=source.work_path,
    )


def _parse_github_maven_source(raw_source: str) -> dict[str, str]:
    value = raw_source.removeprefix("gh-maven:")
    parts = value.split(":")
    if len(parts) not in {4, 5}:
        raise SourceError(
            "GitHub Maven sources must use "
            "gh-maven:owner/repo:group:artifact:version[:extension]"
        )
    owner_repo, group, artifact, version = parts[:4]
    if "/" not in owner_repo:
        raise SourceError("GitHub Maven source owner/repo is required")
    owner, repo = owner_repo.split("/", 1)
    extension = parts[4] if len(parts) == 5 else "zip"
    return {
        "owner": owner,
        "repo": repo,
        "repository_url": f"https://maven.pkg.github.com/{owner}/{repo}/",
        "group": group,
        "artifact": artifact,
        "version": version,
        "extension": extension,
    }


def _parse_maven_source(raw_source: str) -> dict[str, str]:
    value = raw_source.removeprefix("maven:")
    if "::" not in value:
        raise SourceError(
            "Maven sources must use "
            "maven:repository-url::group:artifact:version[:extension]"
        )
    repository_url, coordinate_text = value.split("::", 1)
    if not repository_url.startswith(("http://", "https://")):
        raise SourceError("Maven source repository URL must start with http:// or https://")
    parts = coordinate_text.split(":")
    if len(parts) not in {3, 4}:
        raise SourceError(
            "Maven sources must use "
            "maven:repository-url::group:artifact:version[:extension]"
        )
    group, artifact, version = parts[:3]
    extension = parts[3] if len(parts) == 4 else "zip"
    return {
        "repository_url": repository_url,
        "group": group,
        "artifact": artifact,
        "version": version,
        "extension": extension,
    }


def _maven_artifact_url(repository_url: str, coordinate: dict[str, str]) -> str:
    group_path = coordinate["group"].replace(".", "/")
    artifact_version = coordinate["version"]
    if coordinate["version"].endswith("-SNAPSHOT"):
        artifact_version = _maven_snapshot_version(repository_url, coordinate, group_path)
    file_name = f"{coordinate['artifact']}-{artifact_version}.{coordinate['extension']}"
    base_url = repository_url.rstrip("/")
    return (
        f"{base_url}/{group_path}/{coordinate['artifact']}/"
        f"{coordinate['version']}/{file_name}"
    )


def _maven_version_list(repository_url: str, coordinate: dict[str, str]) -> list[str]:
    group_path = coordinate["group"].replace(".", "/")
    base_url = repository_url.rstrip("/")
    metadata_url = f"{base_url}/{group_path}/{coordinate['artifact']}/maven-metadata.xml"
    metadata = _download_text(metadata_url)
    try:
        root = ElementTree.fromstring(metadata)
    except ElementTree.ParseError as exc:
        raise SourceError(f"Invalid Maven artifact metadata: {metadata_url}") from exc
    return [
        version.text
        for version in root.findall("./versioning/versions/version")
        if version.text
    ]


def _source_at_version(raw_source: str, version: str) -> str:
    if raw_source.startswith("gh-maven:"):
        coordinate = _parse_github_maven_source(raw_source)
        ext = f":{coordinate['extension']}" if coordinate["extension"] != "zip" else ""
        return (
            f"gh-maven:{coordinate['owner']}/{coordinate['repo']}:"
            f"{coordinate['group']}:{coordinate['artifact']}:{version}{ext}"
        )
    if raw_source.startswith("maven:"):
        coordinate = _parse_maven_source(raw_source)
        ext = f":{coordinate['extension']}" if coordinate["extension"] != "zip" else ""
        return (
            f"maven:{coordinate['repository_url']}::"
            f"{coordinate['group']}:{coordinate['artifact']}:{version}{ext}"
        )
    raise SourceError(f"_source_at_version requires a Maven source: {raw_source}")


def _maven_snapshot_version(repository_url: str, coordinate: dict[str, str], group_path: str) -> str:
    base_url = repository_url.rstrip("/")
    metadata_url = (
        f"{base_url}/{group_path}/{coordinate['artifact']}/"
        f"{coordinate['version']}/maven-metadata.xml"
    )
    metadata = _download_text(metadata_url)
    try:
        root = ElementTree.fromstring(metadata)
    except ElementTree.ParseError as exc:
        raise SourceError(f"Invalid Maven snapshot metadata: {metadata_url}") from exc

    extension = coordinate["extension"]
    for snapshot_version in root.findall("./versioning/snapshotVersions/snapshotVersion"):
        version_extension = snapshot_version.findtext("extension")
        value = snapshot_version.findtext("value")
        if version_extension == extension and value:
            return value
    raise SourceError(
        f"No Maven snapshot artifact found for extension {extension}: {metadata_url}"
    )


def _find_zip_manifest(names: list[str]) -> str | None:
    candidates = [name for name in names if Path(name).name in MANIFEST_NAMES]
    if not candidates:
        return None
    candidates.sort(key=lambda name: (name.count("/"), name))
    return candidates[0]


def _find_zip_pom(names: list[str]) -> str | None:
    candidates = [name for name in names if Path(name).name == "pom.xml"]
    if not candidates:
        return None
    candidates.sort(key=lambda name: (name.count("/"), name))
    return candidates[0]


def _manifest_from_pom(pom_text: str, pom_member: str, names: list[str]) -> PackageManifest:
    try:
        root = ElementTree.fromstring(pom_text)
    except ElementTree.ParseError as exc:
        raise SourceError(f"Invalid pom.xml in {pom_member}") from exc

    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}

    def text(path: str) -> str | None:
        value = root.findtext(path, namespaces=namespace)
        return value.strip() if value and value.strip() else None

    artifact_id = text("m:artifactId")
    version = text("m:version")
    if not artifact_id or not version:
        raise SourceError(f"pom.xml is missing artifactId or version: {pom_member}")

    base = _zip_root(pom_member)

    def has_member(relative_path: str) -> bool:
        return f"{base.rstrip('/') + '/' if base else ''}{relative_path}" in names

    install = "Deployment_Manifests/deploy.sql" if has_member("Deployment_Manifests/deploy.sql") else None
    upgrade = "Deployment_Manifests/upgrade.sql" if has_member("Deployment_Manifests/upgrade.sql") else None
    validate = "Tests/smoke_test.sql" if has_member("Tests/smoke_test.sql") else None

    dependencies = []
    for dependency in root.findall("m:dependencies/m:dependency", namespace):
        dep_artifact = dependency.findtext("m:artifactId", namespaces=namespace)
        dep_version = dependency.findtext("m:version", namespaces=namespace)
        if dep_artifact and dep_version and dep_artifact.strip().lower() != "core":
            dependencies.append(
                {
                    "name": dep_artifact.strip(),
                    "version": dep_version.strip(),
                }
            )

    manifest_text = {
        "package": {
            "name": artifact_id,
            "version": version,
            "description": text("m:description"),
        },
        "scripts": {
            "install": install,
            "upgrade": upgrade,
            "validate": validate,
        },
        "dependencies": dependencies,
    }
    return parse_manifest(_json_dump_manifest(manifest_text), "pom-derived.dbpm.json")


def _json_dump_manifest(value: dict[str, object]) -> str:
    return json.dumps(value)


def _zip_root(member: str) -> str | None:
    parts = member.split("/")
    return None if len(parts) == 1 else "/".join(parts[:-1])


def _extract_zip(
    archive: zipfile.ZipFile,
    artifact_checksum: str,
    root: str | None,
) -> Path:
    extract_root = _artifact_cache_dir() / "extract" / artifact_checksum
    script_root = extract_root / root if root else extract_root
    if not script_root.exists():
        temp_root = extract_root.with_name(f"{extract_root.name}.tmp")
        if temp_root.exists():
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        archive.extractall(temp_root)
        if extract_root.exists():
            shutil.rmtree(extract_root)
        temp_root.rename(extract_root)
    return script_root


def _read_directory_metadata(path: Path) -> dict[str, str]:
    meta_dir = path / "META-INF"
    if not meta_dir.exists():
        generated = path / "target" / "generated-build-metadata" / "META-INF"
        meta_dir = generated if generated.exists() else meta_dir
    if not meta_dir.exists():
        return {}

    for item in meta_dir.glob("*-build.properties"):
        return _parse_properties(item.read_text(encoding="utf-8"))
    return {}


def _read_zip_metadata(archive: zipfile.ZipFile) -> dict[str, str]:
    for name in archive.namelist():
        if "/META-INF/" in f"/{name}" and name.endswith("-build.properties"):
            return _parse_properties(archive.read(name).decode("utf-8"))
    return {}


def _parse_properties(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in _tree_files(path):
        relative_path = item.relative_to(path).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _tree_files(path: Path) -> list[Path]:
    files: list[Path] = []
    for item in path.rglob("*"):
        relative_parts = item.relative_to(path).parts
        if _tree_path_excluded(relative_parts):
            continue
        if item.is_file():
            files.append(item)
    return sorted(files, key=lambda item: item.relative_to(path).as_posix())


def _tree_path_excluded(relative_parts: tuple[str, ...]) -> bool:
    return any(
        fnmatch(part, pattern)
        for part in relative_parts
        for pattern in TREE_CHECKSUM_EXCLUDES
    )


def _checksum_cache_path(checksum: str, file_name: str) -> Path:
    return _artifact_cache_dir() / "by-checksum" / "sha256" / checksum / file_name


def _resolve_remote_zip(
    artifact_url: str,
    coord_cache_path: Path,
    expected_checksum: str | None,
    expected_signature_url: str | None = None,
) -> Path:
    artifact_file_name = coord_cache_path.name

    # Content-addressed cache hit — no download or re-verification needed
    if expected_checksum:
        csum_path = _checksum_cache_path(expected_checksum, artifact_file_name)
        if csum_path.exists():
            _check_or_skip_signature(artifact_url, csum_path, expected_signature_url)
            return csum_path

    # Download if not in coordinate cache
    if not coord_cache_path.exists():
        coord_cache_path.parent.mkdir(parents=True, exist_ok=True)
        _download(artifact_url, coord_cache_path)

    # Verify against lockfile checksum and populate content-addressed cache
    if expected_checksum:
        actual = _sha256(coord_cache_path)
        if actual != expected_checksum:
            raise SourceError(
                f"Checksum mismatch for {artifact_file_name}: "
                f"expected {expected_checksum}, got {actual}. "
                f"Remove the cached file to re-download: {coord_cache_path}"
            )
        csum_path = _checksum_cache_path(expected_checksum, artifact_file_name)
        if not csum_path.exists():
            csum_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(coord_cache_path, csum_path)
        _check_or_skip_signature(artifact_url, csum_path, expected_signature_url)
        return csum_path

    _check_or_skip_signature(artifact_url, coord_cache_path, expected_signature_url)
    return coord_cache_path


def _check_or_skip_signature(
    artifact_url: str,
    zip_path: Path,
    expected_signature_url: str | None,
) -> None:
    if not expected_signature_url:
        return
    asc_cache = zip_path.with_name(zip_path.name + ".asc")
    if not asc_cache.exists():
        try:
            _download(expected_signature_url, asc_cache)
        except SourceError:
            raise SourceError(
                f"Signature required but not found for {zip_path.name}"
            )
    _check_gpg_signature(zip_path, asc_cache, zip_path.name)


def _check_gpg_signature(artifact_path: Path, asc_path: Path, artifact_file_name: str) -> None:
    try:
        result = subprocess.run(
            ["gpg", "--verify", str(asc_path), str(artifact_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SourceError("GPG is not installed; cannot verify artifact signature") from exc
    if result.returncode != 0:
        raise SourceError(f"GPG signature verification failed for {artifact_file_name}")


def _artifact_cache_dir() -> Path:
    return Path(os.environ.get("DBPM_CACHE_DIR", Path.home() / ".dbpm" / "cache")).resolve()


def _download(url: str, destination: Path) -> None:
    request = _github_request(url)
    try:
        with urllib.request.urlopen(request) as response:
            with destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise SourceError(
            f"Failed to download package artifact: {url} "
            f"(HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise SourceError(f"Failed to download package artifact: {url} ({exc})") from exc


def _download_text(url: str) -> str:
    request = _github_request(url)
    try:
        with urllib.request.urlopen(request) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise SourceError(
            f"Failed to download package metadata: {url} "
            f"(HTTP {exc.code} {exc.reason})"
        ) from exc
    except OSError as exc:
        raise SourceError(f"Failed to download package metadata: {url} ({exc})") from exc


def _github_request(url: str) -> urllib.request.Request:
    request = urllib.request.Request(url)
    token = os.environ.get("DBPM_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        user = os.environ.get("DBPM_GITHUB_USER") or os.environ.get("GITHUB_ACTOR") or "x-access-token"
        credential = base64.b64encode(f"{user}:{token}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {credential}")
    return request
