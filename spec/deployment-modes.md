# Deployment Modes Specification

## Purpose

Deployment mode describes operator intent. It is separate from Core's deployment type constants, which describe semantic version movement for an application.

## Modes

### `bootstrap-core`

Install or initialize Core, the dbpm substrate.

- Used before ordinary package deployments can run.
- May use Core-specific bootstrap manifests because Core cannot rely on `pkg_application` until after its objects exist.
- Should be rare compared with ordinary package installs and upgrades.

### `install`

Install a package that is not already registered in Core.

- Requires no existing application registration.
- Uses Core's initial deployment type.
- Must not call `pkg_application.delete_application_p` first.

### `upgrade`

Move an installed package to a newer semantic version.

- Requires an existing complete application registration.
- Uses Core's major, minor, or patch deployment type as appropriate.
- Should prefer additive schema evolution and forward-only migration scripts.
- Must not delete and recreate the application registration.

### `reinstall`

Perform a destructive full reinstall.

- May call `pkg_application.delete_application_p` before running an initial deployment.
- Intended for active development and pre-production environments.
- Requires explicit operator intent.
- Should be blocked by default in production-like environments.

### `repair`

Re-run deployment steps for the currently installed version without deleting registered application state.

- Intended for interrupted deployments or object recompilation/replacement.
- Should preserve data and registry history.
- Requires careful package support because not every deployment script is idempotent.

## Environment Policy

dbpm should evaluate environment policy before executing destructive modes. Environment rules are defined in `environment-policy.md`.

## Relationship To Core

dbpm chooses the deployment mode and then calls Core APIs accordingly. Core remains the source of truth for deployed state and deployment status.

Core deployment type constants should be selected from the requested target version and the currently installed version. They should not be used as a substitute for dbpm's operator-facing deployment mode.
