# Package Layout Specification

## Purpose

This document defines the expected directory structure for a dbpm package.

## Recommended Layout

dbpm packages should support the Oracle-native repository layout already used by Core-style projects:

```text
/
  dbpm.yaml
  README.md
  LICENSE
  Deployment_Manifests/
  Packages/
  Tables/
  Types/
  Functions/
  Procedures/
  Metadata/
  Tests/
  docs/
```

## Artifact Metadata

Built artifacts should include generated provenance metadata under `META-INF/`, for example:

```text
META-INF/<artifact>-build.properties
```

dbpm should read this metadata when deploying packaged artifacts.

The metadata file is part of the built artifact, not the source manifest. Source templates for build metadata may exist under `assembly/` or an equivalent build directory, but generated metadata should be what dbpm consumes from packaged artifacts.

## Artifact Distribution

The built package artifact should be a normal archive, such as a ZIP file, that dbpm can retrieve over HTTP(S) and unpack without invoking Maven.

Publishing workflows may place the archive in Maven-compatible repositories, GitHub Packages, static HTTP(S) storage, or other immutable artifact stores. Those repository formats should not change the internal package layout consumed by dbpm.

## SQLcl Project Artifacts

SQLcl `project` may be used as a producer-side workflow for database packages. A SQLcl project can create release folders and deployable artifacts from exported database objects, staged changes, custom SQL, and generated Liquibase changelogs.

dbpm may support SQLcl project artifacts as a compatible package artifact type when they include dbpm metadata. In that case:

- the artifact should still contain or be accompanied by a `dbpm.yaml` manifest
- dependencies should remain dbpm package dependencies beyond Core
- Core should remain a substrate prerequisite checked by dbpm
- generated Liquibase changelogs are deployment implementation details, not dbpm dependency declarations
- dbpm should inject provenance and environment-specific values at execution time
- dbpm should decide deployment mode before invoking SQLcl or any generated installer

When dbpm executes a SQLcl project artifact, it may run a manifest-declared SQLcl entry point such as `dist/install.sql` or a future SQLcl project deploy adapter. That execution should happen after artifact verification, dependency planning, Core checks, and environment policy evaluation.

## Compatibility

The exact object directories are package-specific. A package does not need every directory listed above, but deployment entry points should be declared in `dbpm.yaml` rather than inferred from directory names alone.

Committed `deploy_wrapper.sql` files may be kept as human convenience entry points, but dbpm should execute the manifest-declared scripts directly so it can inject provenance and enforce deployment policy.
