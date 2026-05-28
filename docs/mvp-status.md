# MVP Status

This document tracks what the current dbpm MVP can do and what remains before the MVP is considered complete enough for routine pre-production use.

## Done

- Python CLI project skeleton.
- `dbpm.yaml` parsing for YAML and JSON manifests.
- Local package directory support.
- Local built ZIP support.
- Direct GitHub Maven ZIP package download support.
- Generic Maven-compatible ZIP package download support.
- Direct HTTPS ZIP artifact download support for locked artifact URLs.
- SHA-256 checksum capture for local built ZIP artifacts.
- Deterministic TREE-SHA-256 checksum capture for local package directory sources.
- Artifact metadata provenance from `META-INF/*-build.properties`.
- Local git provenance fallback.
- `dbpm.plan.v0` JSON plan generation.
- `dbpm.multi-plan.v0` JSON plan generation for local dependency-source planning.
- Ordered multi-package execution for local dependency-source installs.
- Ordered conservative multi-package execution for local dependency-source upgrades.
- Ordered multi-package execution for local dependency-source validation.
- `dbpm-lock.json` generation for resolved install plans.
- Lockfile verification against the current source resolution.
- Lockfile/database reconciliation for installed package versions and complete Core status.
- Lockfile/database reconciliation for Core deployment provenance rows through `pkg_application.get_deployment_provenance_json_f`.
- Lockfile-driven install without restating package sources.
- Environment policy evaluation for development, test, staging, and production classes.
- SQLcl/SQLPlus runner configuration through `--runner` or `DBPM_SQL_RUNNER`.
- Database connection configuration through `--connect` or `DBPM_CONNECT`.
- dbpm-managed per-package script execution log files through `DBPM_LOG_DIR` or `.dbpm-logs`.
- `check-core` command.
- Core installed-state lookup.
- Core reverse-dependency lookup.
- `install` command.
- `upgrade` command.
- `reinstall` command with explicit destructive pre-action.
- `resume` command for running or failed deployments.
- `validate` command for package smoke/validation scripts.
- Core provenance staging pre-action using `pkg_application.stage_deployment_provenance_p`.
- Core upgrade planning/execution reads installed Core state and stages provenance when installed Core is 3.2.0 or newer.
- Install preflight blocks already-installed applications.
- Upgrade preflight blocks missing, incomplete, same-version, and downgrade targets.
- Multi-package upgrade preflight refuses to install missing dependency sources.
- Reinstall preflight blocks applications with installed dependents.
- Local multi-package installs, upgrades, and validations order dependency sources before consumers and fail clearly for missing, mismatched, unsupported, or cyclic dependencies.
- Opt-in live database integration test for Core.
- Unit-test wrapper that unsets live database variables before running pytest.
- Dev database proof with `utl_interval` install, upgrade, reinstall, and validate.
- WSL dev database proof with `bootstrap-core` installing Core 3.4.0 into an empty schema from a GitHub Maven artifact.

## Current Commands

```text
dbpm check-core
dbpm plan
dbpm lock
dbpm bootstrap-core
dbpm install
dbpm upgrade
dbpm reinstall
dbpm resume
dbpm validate
```

## Known Gaps

- Multi-package dependency execution does not yet support reinstall.
- Dependency resolution supports exact `major.minor.patch` and caret-compatible constraints.
- Upgrade execution does not yet resolve or run intermediate package versions. Target upgrade scripts must handle the installed-to-target version transition, such as `1.0.0` directly to `1.3.0`.
- Lockfile database provenance reconciliation requires Core 3.3.0 or newer.
- Local artifact cache exists for downloaded and extracted ZIP artifacts, but is not lockfile-aware.

## Next Recommended Work

1. Add lockfile-aware trusted artifact mirrors.
2. Add stepwise upgrade chain planning for ordered version-to-version migrations.
