from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import SourceError
from .manifest import MANIFEST_NAMES, PackageManifest, parse_manifest


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

    @property
    def display_path(self) -> str:
        return str(self.path)

    @property
    def is_directory(self) -> bool:
        return self.source_type == "directory"

    @property
    def is_zip(self) -> bool:
        return self.source_type == "zip"

    def resolve_script_path(self, script_path: str) -> Path | str:
        if self.is_directory:
            return self.path / script_path
        return f"{self.root.rstrip('/') + '/' if self.root else ''}{script_path}"


def load_package_source(raw_path: str) -> PackageSource:
    path = Path(raw_path).resolve()
    if path.is_dir():
        return _load_directory_source(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        return _load_zip_source(path)
    raise SourceError(f"Unsupported package source: {path}")


def _load_directory_source(path: Path) -> PackageSource:
    manifest_path = next((path / name for name in MANIFEST_NAMES if (path / name).exists()), None)
    if manifest_path is None:
        raise SourceError(f"No dbpm manifest found in {path}")

    text = manifest_path.read_text(encoding="utf-8")
    manifest = parse_manifest(text, manifest_path.name)
    metadata = _read_directory_metadata(path)
    return PackageSource(
        path=path,
        source_type="directory",
        root=None,
        manifest_name=manifest_path.name,
        manifest=manifest,
        metadata=metadata,
    )


def _load_zip_source(path: Path) -> PackageSource:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest_member = _find_zip_manifest(names)
        if manifest_member is None:
            raise SourceError(f"No dbpm manifest found in {path}")
        text = archive.read(manifest_member).decode("utf-8")
        manifest = parse_manifest(text, Path(manifest_member).name)
        metadata = _read_zip_metadata(archive)
        root = _zip_root(manifest_member)

    return PackageSource(
        path=path,
        source_type="zip",
        root=root,
        manifest_name=manifest_member,
        manifest=manifest,
        metadata=metadata,
        artifact_checksum=_sha256(path),
        artifact_checksum_alg="SHA-256",
    )


def _find_zip_manifest(names: list[str]) -> str | None:
    candidates = [name for name in names if Path(name).name in MANIFEST_NAMES]
    if not candidates:
        return None
    candidates.sort(key=lambda name: (name.count("/"), name))
    return candidates[0]


def _zip_root(member: str) -> str | None:
    parts = member.split("/")
    return None if len(parts) == 1 else "/".join(parts[:-1])


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
