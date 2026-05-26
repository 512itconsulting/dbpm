# MVP Status

This document tracks what the current dbpm MVP can do and what remains before the MVP is considered complete enough for routine pre-production use.

## Done

- Python CLI project skeleton.
- `dbpm.yaml` parsing for YAML and JSON manifests.
- Local package directory support.
- Local built ZIP support.
- Direct GitHub Maven ZIP package download support.
- SHA-256 checksum capture for local built ZIP artifacts.
- Artifact metadata provenance from `META-INF/*-build.properties`.
- Local git provenance fallback.
- `dbpm.plan.v0` JSON plan generation.
- `dbpm.multi-plan.v0` JSON plan generation for local dependency-source planning.
- Ordered multi-package execution for local dependency-source installs.
- Environment policy evaluation for development, test, staging, and production classes.
- SQLcl/SQLPlus runner configuration through `--runner` or `DBPM_SQL_RUNNER`.
- Database connection configuration through `--connect` or `DBPM_CONNECT`.
- `check-core` command.
- Core installed-state lookup.
- Core reverse-dependency lookup.
- `install` command.
- `upgrade` command.
- `reinstall` command with explicit destructive pre-action.
- `resume` command for running or failed deployments.
- `validate` command for package smoke/validation scripts.
- Core provenance staging pre-action using `pkg_application.stage_deployment_provenance_p`.
- Install preflight blocks already-installed applications.
- Upgrade preflight blocks missing, incomplete, same-version, and downgrade targets.
- Reinstall preflight blocks applications with installed dependents.
- Local multi-package installs order dependency sources before consumers and fail clearly for missing, mismatched, unsupported, or cyclic dependencies.
- Opt-in live database integration test for Core.
- Dev database proof with `utl_interval` install, upgrade, reinstall, and validate.

## Current Commands

```text
dbpm check-core
dbpm plan
dbpm bootstrap-core
dbpm install
dbpm upgrade
dbpm reinstall
dbpm resume
dbpm validate
```

## Known Gaps

- Local directory deployments do not yet calculate a stable source-tree checksum.
- Multi-package dependency execution is install-only.
- Dependency resolution supports exact `major.minor.patch` and caret-compatible constraints.
- Lockfile generation and enforcement are not implemented.
- Remote retrieval is GitHub Maven ZIP-only.
- Local artifact cache exists for downloaded and extracted ZIP artifacts, but is not lockfile-aware.
- Execution logs are not yet captured into dbpm-managed log files.
- `bootstrap-core` exists as a command but has not been recently tested end-to-end against an empty schema.

## Next Recommended Work

1. Define lockfile generation and database reconciliation behavior.
2. Extend ordered multi-package execution beyond install.
3. Decide checksum strategy for local directory deployments.
4. Add dbpm-managed execution log capture.
5. Add generic Maven repository retrieval.
