# Dependency Resolution Specification

## Purpose

This document defines how dbpm should resolve package dependencies before deployment.

## Core Substrate

Core is an implicit substrate prerequisite for dbpm-managed deployments. It should not be added as a normal dependency edge for every application.

Before executing a package deployment, dbpm must verify:

- Core is installed in the target schema.
- Core meets the package's declared `core.minimum_version`.
- Core exposes the required registry API, especially `pkg_application`.

If Core is missing, dbpm should require a bootstrap/install-Core workflow before installing ordinary packages.

## Package Dependencies

Package manifests declare dependencies beyond Core:

```yaml
dependencies:
  - name: utl_interval
    version: "^1.2.0"
```

dbpm resolves these dependencies into a deployment plan ordered so each dependency is installed or upgraded before packages that require it.

## Installed State

Installed state should be read from Core's registry, not from local files. dbpm should use Core as the source of truth for:

- installed application names
- installed semantic versions
- deployment status
- deployment commit hash
- dependency records

## Version Constraints

Initial version constraint support should be intentionally small and semver-oriented:

- exact versions, such as `1.2.3`
- compatible ranges, such as `^1.2.0`
- minimum versions, such as `>=1.2.0`

The resolver should reject ambiguous or unsupported constraints until the syntax is formally specified.

## Planning

A deployment plan should include:

- packages to install
- packages to upgrade
- packages already satisfied
- detected conflicts
- execution order
- required Core version
- provenance source for each package
- deployment mode for each package

The plan should be visible before destructive or production-oriented execution.
