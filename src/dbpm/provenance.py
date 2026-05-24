from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .source import PackageSource


UNKNOWN_COMMIT = "0000000000000000000000000000000000000000"


@dataclass(frozen=True)
class Provenance:
    source: str
    commit: str
    dirty: bool | None
    artifact: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "commit": self.commit,
            "dirty": self.dirty,
            "artifact": self.artifact,
        }


def resolve_provenance(source: PackageSource) -> Provenance:
    metadata = source.metadata
    commit = metadata.get("git.commit.id")
    if commit:
        return Provenance(
            source="artifact-metadata",
            commit=commit,
            dirty=_parse_bool(metadata.get("git.dirty")),
            artifact=_artifact_metadata(metadata),
        )

    if source.is_directory:
        git_provenance = _git_provenance(source.path)
        if git_provenance is not None:
            return git_provenance

    return Provenance(source="unknown", commit=UNKNOWN_COMMIT, dirty=None, artifact={})


def _git_provenance(path: Path) -> Provenance | None:
    commit = _git(path, "rev-parse", "HEAD")
    if commit is None:
        return None
    dirty = _git(path, "status", "--porcelain")
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    artifact = {"git.branch": branch} if branch else {}
    return Provenance(
        source="local-git",
        commit=commit,
        dirty=bool(dirty),
        artifact=artifact,
    )


def _git(path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return None


def _artifact_metadata(metadata: dict[str, str]) -> dict[str, str]:
    keys = (
        "artifact.groupId",
        "artifact.artifactId",
        "artifact.version",
        "git.commit.id.abbrev",
        "git.branch",
        "build.time",
    )
    return {key: metadata[key] for key in keys if key in metadata}
