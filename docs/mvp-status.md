# MVP Status

This document tracks what the current dbpm MVP can do and what remains before the MVP is considered complete enough for routine pre-production use.

## Done

- Python CLI project skeleton.
- `dbpm.yaml` parsing for YAML and JSON manifests.
- Local package directory support.
- Local built ZIP support.
- Artifact metadata provenance from `META-INF/*-build.properties`.
- Local git provenance fallback.
- `dbpm.plan.v0` JSON plan generation.
- Environment policy evaluation for development, test, staging, and production classes.
- SQLcl/SQLPlus runner configuration through `--runner` or `DBPM_SQL_RUNNER`.
- Database connection configuration through `--connect` or `DBPM_CONNECT`.
- `check-core` command.
- Core installed-state lookup.
- Core reverse-dependency lookup.
- `install` command.
- `reinstall` command with explicit destructive pre-action.
- `resume` command for running or failed deployments.
- `validate` command for package smoke/validation scripts.
- Core provenance staging pre-action using `pkg_application.stage_deployment_provenance_p`.
- Install preflight blocks already-installed applications.
- Reinstall preflight blocks applications with installed dependents.
- Opt-in live database integration test for Core.
- Dev database proof with `utl_interval` install, reinstall, and validate.

## Current Commands

```text
dbpm check-core
dbpm plan
dbpm bootstrap-core
dbpm install
dbpm reinstall
dbpm resume
dbpm validate
```

## Known Gaps

- Local directory deployments do not yet calculate a stable source-tree checksum.
- `upgrade` is not implemented.
- Multi-package dependency resolution is not implemented.
- Lockfile generation and enforcement are not implemented.
- Remote artifact retrieval is not implemented.
- Local artifact cache is not implemented.
- Execution logs are not yet captured into dbpm-managed log files.
- `bootstrap-core` exists as a command but has not been recently tested end-to-end against an empty schema.

## Next Recommended Work

1. Deploy the latest Core provenance-staging change to the development database.
2. Verify `APP_DEPLOY_PROVENANCE` records dbpm-managed deployments through staged provenance.
3. Add minimal `upgrade` support.
4. Add a small multi-package fixture for dependency ordering.
5. Define lockfile generation and database reconciliation behavior.
