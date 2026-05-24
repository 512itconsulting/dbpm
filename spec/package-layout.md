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

## Compatibility

The exact object directories are package-specific. A package does not need every directory listed above, but deployment entry points should be declared in `dbpm.yaml` rather than inferred from directory names alone.
