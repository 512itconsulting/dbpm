# Package Retrieval Specification

## Purpose

This document defines the intended direction for retrieving dbpm package artifacts.

## User Classes

dbpm should distinguish between two broad classes of users:

- package producers, who build and publish reusable database packages
- package consumers, who install packages into Oracle environments

Consumers are expected to be the larger audience. The consumer workflow should therefore minimize external tooling assumptions.

## Consumer Requirements

Consumers should install packages through dbpm, not through Maven directly.

dbpm should retrieve package archives over HTTP(S) where possible, using a built-in downloader or a ubiquitous platform tool such as `curl`.

Consumer machines should not require Maven or a JDK solely to resolve and download dbpm packages.

End-user applications should normally install and patch through dbpm when they depend on dbpm packages. The application owns its deployment entry points and lifecycle semantics, while dbpm owns artifact resolution, dependency planning, provenance injection, Core checks, deployment lock policy evaluation, and execution orchestration.

End-user applications should not normally vendor live dependent repositories. They should declare dependencies in the manifest, commit a dependency lockfile for release-oriented workflows, and rely on immutable package artifacts.

## Repository Compatibility

Maven-compatible repositories remain useful as an artifact publishing and hosting format because they provide:

- immutable versioned coordinates
- checksum and metadata conventions
- compatibility with Nexus, Artifactory, GitHub Packages, and similar systems
- familiar CI/CD publishing paths for producers

dbpm may support Maven-style coordinates and repository layouts by resolving them to HTTP(S) artifact URLs internally.

## Local Artifact Cache

dbpm should maintain a local artifact cache for resolved package archives.

The cache should be keyed by immutable artifact identity and checksum, not only by package name and version. Cached artifacts may satisfy future deployments when the lockfile requires the same checksum.

The cache improves repeatability and resilience against network outages, but production-oriented workflows should still prefer artifacts that are either already mirrored into an organization-controlled source or verified against a committed lockfile.

## Trusted Mirrors

Production and CI deployments should be able to use organization-controlled mirrors or registries.

When a locked artifact is available from a trusted mirror and its checksum matches the lockfile, dbpm may use the mirror even if the original upstream registry is unavailable or the publisher deleted the version.

If no configured trusted source can provide the locked artifact with the expected checksum, dbpm should fail rather than substituting another artifact.

## Producer Flexibility

Package producers may use Maven, Gradle, GitHub Actions, SQLcl `project`, dbpm-native publishing, or another build workflow to publish immutable package archives.

Producer tooling should create artifacts with stable dbpm manifests and generated provenance metadata. It should not force Maven concepts into the package manifest beyond optional repository coordinates and artifact metadata.

SQLcl project artifacts should be treated as producer output, not as a replacement for dbpm package metadata. If a producer uses SQLcl `project gen-artifact`, dbpm should still require enough metadata to resolve package identity, version, Core requirements, dependencies beyond Core, provenance, and deployment entry points.

## MVP Status

The MVP supports local package directories, local built ZIP files, direct GitHub Maven package downloads, and generic Maven-compatible repository downloads for ZIP artifacts.

GitHub Maven package sources use this form:

```text
gh-maven:owner/repo:group:artifact:version[:extension]
```

For example:

```text
gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

The default extension is `zip`. dbpm resolves the coordinate to the standard Maven repository path under `https://maven.pkg.github.com/<owner>/<repo>/`, downloads the archive over HTTP(S), calculates its SHA-256 checksum, extracts it into the local dbpm cache, and then treats it like any other ZIP source.

Generic Maven package sources use this form:

```text
maven:repository-url::group:artifact:version[:extension]
```

For example:

```text
maven:https://repo.example.com/releases::com.512itconsulting.database:utl_interval:1.0.0
```

The repository URL is the Maven repository base URL. dbpm appends the group path, artifact id, version, and artifact filename using the standard Maven repository layout.

For `-SNAPSHOT` versions, dbpm reads the version-level `maven-metadata.xml` and resolves the requested extension to the timestamped artifact filename before downloading.

If GitHub Packages requires authentication, dbpm reads `DBPM_GITHUB_TOKEN` or `GITHUB_TOKEN`. The username comes from `DBPM_GITHUB_USER`, `GITHUB_ACTOR`, or `x-access-token`.
