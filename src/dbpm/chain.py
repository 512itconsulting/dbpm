from __future__ import annotations

from .errors import DbpmError
from .resolver import parse_version, version_satisfies
from .source import PackageSource, _maven_version_list, _parse_github_maven_source, _parse_maven_source, _source_at_version, load_package_source


class ChainError(DbpmError):
    """Raised when a stepwise upgrade chain cannot be resolved."""


def resolve_upgrade_chain(
    source: PackageSource,
    raw_source: str,
    installed_version: str,
) -> list[PackageSource]:
    """Return ordered PackageSources for each upgrade step.

    Returns [source] (direct upgrade) when:
    - upgrade_from is present and satisfied by the installed version, OR
    - the source is not a Maven coordinate and upgrade_from is absent, OR
    - no intermediate versions exist between installed and target.

    For Maven sources where upgrade_from is absent or not satisfied, builds a
    full chain through every published intermediate version.

    Raises ChainError when a local/ZIP source has an upgrade_from constraint
    that the installed version does not satisfy.
    """
    upgrade_from = source.manifest.scripts.upgrade_from

    if upgrade_from is not None and version_satisfies(installed_version, upgrade_from):
        return [source]

    if not _is_maven_source(raw_source):
        if upgrade_from is None:
            return [source]
        raise ChainError(
            f"upgrade_from constraint '{upgrade_from}' is not satisfied by installed "
            f"version {installed_version} for {source.manifest.application_name}. "
            f"Chain required but source is not a Maven coordinate. "
            f"Upgrade through each intermediate version manually."
        )

    repository_url, coordinate = _maven_repo_and_coordinate(raw_source)
    available = _maven_version_list(repository_url, coordinate)
    intermediates = _minor_boundary_intermediates(available, installed_version, source.manifest.version)

    if not intermediates:
        return [source]

    chain: list[PackageSource] = [
        load_package_source(_source_at_version(raw_source, v))
        for v in intermediates
    ]
    chain.append(source)
    return chain


def _minor_boundary_intermediates(
    available: list[str],
    installed_version: str,
    target_version: str,
) -> list[str]:
    """Return one milestone version per intermediate minor between installed and target.

    Patches within a minor are cumulative by semver convention, so only the
    lowest published patch of each intermediate minor is included. Patches in
    the installed minor and the target minor are skipped entirely.
    """
    installed_v = parse_version(installed_version)
    target_v = parse_version(target_version)
    installed_minor = (installed_v[0], installed_v[1])
    target_minor = (target_v[0], target_v[1])

    by_minor: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for raw in available:
        try:
            pv = parse_version(raw)
        except Exception:
            continue
        key = (pv[0], pv[1])
        by_minor.setdefault(key, []).append(pv)

    milestones = []
    for key in sorted(by_minor):
        if key <= installed_minor or key >= target_minor:
            continue
        lowest = min(by_minor[key])
        milestones.append(f"{lowest[0]}.{lowest[1]}.{lowest[2]}")

    return milestones


def _is_maven_source(raw_source: str) -> bool:
    return raw_source.startswith("gh-maven:") or raw_source.startswith("maven:")


def _maven_repo_and_coordinate(raw_source: str) -> tuple[str, dict[str, str]]:
    if raw_source.startswith("gh-maven:"):
        coordinate = _parse_github_maven_source(raw_source)
        repository_url = f"https://maven.pkg.github.com/{coordinate['owner']}/{coordinate['repo']}/"
        return repository_url, coordinate
    coordinate = _parse_maven_source(raw_source)
    return coordinate["repository_url"], coordinate
