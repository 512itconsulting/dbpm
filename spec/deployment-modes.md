# Deployment Modes Specification

## Purpose

Deployment mode describes operator intent. It is separate from Core's deployment type constants, which describe [semantic version](https://semver.org/) movement for an application.

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
- For end-user applications, may install the application package and its locked dependency graph through dbpm.

### `upgrade`

Move an installed package to a newer semantic version.

- Requires an existing complete application registration.
- Uses Core's major, minor, or patch deployment type as appropriate.
- Should prefer additive schema evolution and forward-only migration scripts.
- Must not delete and recreate the application registration.
- For end-user applications, should patch the application and required dependency upgrades through the resolved or locked deployment plan.
- For Maven sources, dbpm automatically chains through published minor-version milestones when a direct upgrade is not safe. The chain respects the `scripts.upgrade_from` constraint declared in the package manifest: if the constraint is satisfied by the installed version, the upgrade runs directly; otherwise dbpm resolves intermediate versions from the Maven repository's published version list.
- Package upgrade scripts should be idempotent. On failure, `resume` re-runs the full upgrade from the beginning.
- Major version upgrades are blocked when installed dependents may have incompatible constraints. Use `--dependency-source` to supply updated dependent versions, or `--allow-dependent-break` to override.

### `reinstall`

Perform a destructive full reinstall.

- May call `pkg_application.delete_application_p` before running an initial deployment.
- Intended for active development and pre-production environments.
- Requires explicit operator intent.
- Should be blocked by default in production-like environments.

### `resume`

Re-run deployment steps for an application that is in a running (`R`) or failed (`F`) Core deployment status, without deleting registered application state.

- Intended for interrupted or failed deployments.
- Requires the application to already be registered in Core with status `R` or `F`.
- Should preserve data and registry history.
- Requires careful package support because not every deployment script is idempotent.

## Environment Policy

dbpm should evaluate Core deployment-lock policy before executing destructive modes. Policy rules are defined in `environment-policy.md`.

## Relationship To Core

dbpm chooses the deployment mode and then calls Core APIs accordingly. Core remains the source of truth for deployed state and deployment status.

Core deployment type constants should be selected from the requested target version and the currently installed version. They should not be used as a substitute for dbpm's operator-facing deployment mode.

End-user applications are ordinary dbpm deployment targets from Core's perspective. dbpm verifies Core as the substrate prerequisite, plans dependencies beyond Core, and executes the application-owned manifest entry points.
