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

Dependency declarations are read from package manifests and artifact metadata. Core's registry is used to determine what is already installed in the target schema and whether a dependency is already satisfied.

End-user applications should declare dependencies on reusable dbpm packages instead of copying dependent repositories into the application. For release-oriented workflows, dependency resolution should produce or consume a lockfile that pins the exact artifacts selected for deployment.

## Installed State

Installed state should be read from Core's registry, not from local files. dbpm should use Core as the source of truth for:

- installed application names
- installed semantic versions
- deployment status
- deployment commit hash
- dependency records

Core dependency records reflect what installed applications declared during deployment. They are useful for audit and validation, but dbpm should plan from package manifests before execution so it can resolve dependencies prior to installing the package.

## Version Constraints

Initial version constraint support should be intentionally small and semver-oriented:

- exact versions, such as `1.2.3`
- compatible ranges, such as `^1.2.0`
- minimum versions, such as `>=1.2.0`

The resolver should reject ambiguous or unsupported constraints until the syntax is formally specified.

The MVP resolver supports exact `major.minor.patch` versions and caret-compatible ranges such as `^1.0.0`. Minimum-version constraints remain specified direction but should fail clearly until implemented.

## Lockfile Resolution

When a lockfile is present and the selected workflow requires locked deployments, dbpm should install or upgrade using the exact artifact identities recorded in the lockfile.

The resolver may still validate that the locked graph satisfies the manifest constraints, Core requirement, and environment policy, but it must not silently choose different package versions or rebuilt artifacts.

When a lockfile is absent in a development workflow, dbpm may resolve dependency constraints from configured sources and then write or update a lockfile. CI and production-oriented workflows should require a lockfile for applications with dependencies.

## Conflicts And Cycles

The resolver should fail the plan when:

- no available package version satisfies all constraints
- two packages require incompatible versions of the same dependency
- dependency declarations contain a cycle that cannot be reduced to already-installed packages
- an installed package is present but its Core deployment status is not complete

## Planning

A deployment plan should include:

- packages to install
- packages to upgrade
- packages already satisfied
- lockfile status for each package
- artifact source selected for each package
- artifact checksum for each package
- detected conflicts
- execution order
- required Core version
- provenance source for each package
- deployment mode for each package

The plan should be visible before destructive or production-oriented execution.
