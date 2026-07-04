# Dependency Lockfile Specification

## Purpose

The dependency lockfile records the exact package artifacts selected for a deployment so the same application can be installed or upgraded repeatably across environments.

End-user applications should commit a lockfile when they depend on dbpm packages. Reusable packages may also use a lockfile for integration tests, examples, and release validation, but their published manifests should continue to declare dependency constraints rather than vendoring dependent repositories.

## Relationship To Manifests

The manifest declares intent:

- package identity
- package version
- supported database and Core requirements
- dependency constraints beyond Core
- deployment entry points

The lockfile records resolution:

- exact artifact coordinates
- exact artifact version
- checksum
- resolved source URL or repository coordinate
- provenance metadata used for deployment
- transitive dependency graph

dbpm should resolve from the manifest, write or update the lockfile during development and release workflows, and deploy from the lockfile in CI and production-oriented workflows.

## Current MVP Shape

The MVP writes `dbpm-lock.json` with schema version `dbpm.lock.v0`.

The current command is:

```text
dbpm lock <source> [--dependency-source <source>] [--output dbpm-lock.json]
```

Verification commands:

```text
dbpm lock <source> [--dependency-source <source>] --check
dbpm lock <source> [--dependency-source <source>] --check --check-db
```

Lockfile install command:

```text
dbpm install --lockfile [dbpm-lock.json]
```

`--check` fails when the current resolution differs from the lockfile. It compares package identity, version, execution order, artifact URI, checksum, checksum algorithm, and package coordinate.

`--check-db` also reads Core installed state for the locked packages and fails when a package is missing, has a non-complete deployment status, or has a different installed version. With Core 3.3.0 or newer, it also reads `pkg_application.get_deployment_provenance_json_f` and compares the recorded artifact/provenance fields against the lockfile.

`install --lockfile` reconstructs the ordered install plan from the package sources recorded in the lockfile. For remote artifacts, the MVP loads the locked HTTPS ZIP artifact URL directly, verifies the resulting plan still matches the lockfile, then executes the normal install path.

## Artifact Identity

Each locked package should include an immutable artifact identity. At minimum, this should include:

- package name
- version
- artifact coordinate or URL
- cryptographic checksum, using archive SHA-256 for ZIP artifacts or TREE-SHA-256 for local directory sources
- packaging format
- provenance metadata location or extracted provenance fields

dbpm must not silently replace a locked artifact with another artifact that merely has the same package name and version. If the checksum or immutable identity does not match, the deployment should fail.

## Source Priority

When deploying from a lockfile, dbpm may retrieve the locked artifact from any configured trusted source that can provide the exact artifact by checksum:

- local artifact cache
- organization-controlled mirror or registry
- bundled release artifact repository
- original upstream registry

The original upstream source is not the only valid source once the artifact identity is locked. This allows deployments to survive upstream deletion or registry outages without weakening reproducibility.

## Deletion And Unavailability

If a publisher deletes a package version from the original registry, dbpm should still be able to deploy it when the exact locked artifact is available from a trusted cache or mirror.

If no configured trusted source can provide the locked artifact with the expected checksum, dbpm must fail loudly. It should not automatically choose a newer version, a rebuilt artifact, or a different source artifact.

## Local Development Overrides

Development workflows may allow local workspace or repository overrides for convenience.

Such overrides should be visibly marked in the deployment plan and subject to deployment lock policy. Production-oriented workflows should prefer locked immutable artifacts from trusted artifact sources.
