# Deployment Provenance Specification

## Purpose

Deployment provenance connects an installed database application to the artifact and source revision that produced it.

## Preferred Source

For packaged deployments, dbpm should read provenance from immutable artifact metadata, for example:

```text
META-INF/<artifact>-build.properties
```

Expected fields include:

```properties
artifact.groupId=com.512itconsulting.database
artifact.artifactId=utl_interval
artifact.version=0.1.0
git.commit.id=<40-character-sha>
git.commit.id.abbrev=<short-sha>
git.branch=main
git.dirty=false
build.time=2026-05-22T20:13:18Z
```

## Local Development Source

For local source deployments, dbpm may derive provenance from repository state. This is useful during active development, but it should be visibly marked when the working tree is dirty.

Dirty local deployments should be allowed only when the selected environment policy permits them. Released artifact deployments should normally require `git.dirty=false`.

## Injection

Package deployment scripts should remain parameterized. dbpm should inject the resolved commit hash at execution time, typically by passing it as the first SQL*Plus/SQLcl argument:

```sql
@Deployment_Manifests/deploy.sql <git.commit.id>
```

Committed wrappers should not hard-code commit hashes.

Local convenience wrappers may exist, but they are not the authoritative dbpm execution path.

## Core Registry

For Core versions that support staged artifact provenance, dbpm should call `pkg_application.stage_deployment_provenance_p` before executing the package deployment script. The staged row must match the application name, semantic version, deployment type, and deploy commit hash that the script passes to `pkg_application.begin_deployment_p`.

When `begin_deployment_p` starts the deployment, Core consumes the matching pending provenance row into `APP_DEPLOY_PROVENANCE`. This keeps package deployment scripts unchanged for manual and dbpm-managed execution while allowing dbpm to persist artifact URI, artifact coordinates, source commit, build metadata, and related provenance.

dbpm should also retain resolved provenance in the deployment plan and execution logs.

For built ZIP artifacts, dbpm should calculate the SHA-256 checksum from the exact archive bytes and stage it with Core. For local directory deployments, dbpm should calculate a deterministic TREE-SHA-256 checksum over relative source file paths and file bytes, excluding local cache, VCS, build-output, virtual-environment, and log noise.

## Lockfile And Cache

When deploying from a lockfile, dbpm should verify that the artifact provenance and checksum match the locked artifact identity before execution.

Artifacts retrieved from a local cache or trusted mirror remain valid only when they match the locked checksum and provenance expectations. dbpm should not treat matching package names or versions alone as sufficient provenance.
