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

dbpm should pass the resolved 40-character source commit hash to Core through `pkg_application.begin_deployment_p`.

Future Core/dbpm integration may record richer artifact metadata beyond the commit hash, including artifact coordinates, build time, and dirty-state policy.

Until Core stores richer artifact metadata, dbpm should retain it in the deployment plan and execution logs.

## Lockfile And Cache

When deploying from a lockfile, dbpm should verify that the artifact provenance and checksum match the locked artifact identity before execution.

Artifacts retrieved from a local cache or trusted mirror remain valid only when they match the locked checksum and provenance expectations. dbpm should not treat matching package names or versions alone as sufficient provenance.
