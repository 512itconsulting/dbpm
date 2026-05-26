# MVP Usage Examples

These examples assume:

- commands are run from the dbpm project with `uv run dbpm`.
- SQLcl is available as `sql`.
- Core is already installed in the target schema.
- A local, uncommitted `setenv.ps1` or `setenv.sh` sets credentials.

Do not commit environment files that contain passwords.

## Environment Setup

Keep local environment scripts uncommitted. They may contain database passwords and GitHub tokens.

Required for database commands:

- `DBPM_SQL_RUNNER`: SQLcl or SQLPlus executable.
- `DBPM_CONNECT`: Oracle connect string.

Required for private GitHub Packages:

- `DBPM_GITHUB_TOKEN`: GitHub token with package read access.
- `DBPM_CACHE_DIR`: local cache for downloaded and extracted package artifacts.

Optional:

- `DBPM_GITHUB_USER`: GitHub username used with `DBPM_GITHUB_TOKEN`. If omitted, dbpm falls back to `GITHUB_ACTOR` or `x-access-token`.
- `DBPM_RUN_DB_TESTS`: set to `1` to enable opt-in live database pytest tests.

Example local `setenv.ps1`:

```powershell
$env:DBPM_SQL_RUNNER = "sql.exe"
$env:DBPM_CONNECT = "user/password@tns_alias_or_service"
$env:DBPM_GITHUB_TOKEN = "github_token_with_package_read_access"
$env:DBPM_CACHE_DIR = ".\.dbpm-cache"

# Optional
$env:DBPM_GITHUB_USER = "github_username"
# $env:DBPM_RUN_DB_TESTS = "1"
```

Example local `setenv.sh`:

```sh
export DBPM_SQL_RUNNER="sql"
export DBPM_CONNECT="user/password@tns_alias_or_service"
export DBPM_GITHUB_TOKEN="github_token_with_package_read_access"
export DBPM_CACHE_DIR="./.dbpm-cache"

# Optional
export DBPM_GITHUB_USER="github_username"
# export DBPM_RUN_DB_TESTS="1"
```

Load the environment before running connected or remote package commands:

```powershell
. .\setenv.ps1
```

```sh
. ./setenv.sh
```

## Check Core

Verify Core is available and satisfies the minimum version:

```powershell
uv run dbpm check-core --minimum-version 3.2.0
```

Expected output:

```text
CORE_VERSION=3.2.0
```

## Plan A Local Package Install

Generate a plan without connecting to the database:

```powershell
uv run dbpm plan C:\Local_Exe\Repos\utl_interval --mode install --env development
```

Generate a connected plan that includes Core installed state and reverse dependencies:

```powershell
uv run dbpm plan C:\Local_Exe\Repos\utl_interval --mode install --env development --connect $env:DBPM_CONNECT
```

## Plan Local Dependencies

When a package manifest declares dependencies, provide local package sources that may satisfy them:

```powershell
uv run dbpm plan C:\path\to\consumer --mode install --dependency-source C:\path\to\dependency
```

The resulting multi-package plan orders dependencies before consumers. If a required dependency is not already installed in Core and no matching local source is provided, planning fails before deployment.

GitHub Maven ZIP artifacts can be used as package sources:

```powershell
$env:DBPM_GITHUB_TOKEN = "<token-if-required>"
uv run dbpm plan gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --mode install --dependency-source gh-maven:rsantmyer/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

The coordinate format is:

```text
gh-maven:owner/repo:group:artifact:version[:extension]
```

## Lock Resolved Artifacts

Write a lockfile for an install resolution:

```powershell
uv run dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:rsantmyer/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

This writes `dbpm-lock.json` with the ordered package list, resolved artifact URLs, SHA-256 checksums for ZIP artifacts, provenance fields, and dependency metadata.

Verify that the current resolution still matches the lockfile:

```powershell
uv run dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:rsantmyer/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 --check
```

Verify that the connected database has the locked package versions installed with complete Core deployment status and matching Core provenance rows:

```powershell
uv run dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:rsantmyer/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 --check --check-db
```

## Install A Package

Install a package that is not already registered in Core:

```powershell
uv run dbpm install C:\Local_Exe\Repos\utl_interval --env development
```

Before running the package deployment script, dbpm stages resolved provenance in Core with `pkg_application.stage_deployment_provenance_p`. The existing deploy script still receives the commit hash argument and calls `begin_deployment_p`; Core consumes the matching staged provenance when that deployment starts.

If the package is already installed, dbpm fails before running the deployment script:

```text
dbpm: UTL_INTERVAL is already installed; use reinstall or upgrade
```

Install can use the same local dependency sources:

```powershell
uv run dbpm install C:\path\to\consumer --env development --dependency-source C:\path\to\dependency
```

dbpm executes each package in dependency order and stops on the first failed package.

Install can also use a previously written lockfile without restating the root package or dependency sources:

```powershell
uv run dbpm install --lockfile dbpm-lock.json --env development
```

When no lockfile path is provided, `--lockfile` defaults to `dbpm-lock.json`:

```powershell
uv run dbpm install --lockfile --env development
```

dbpm reloads the locked artifact URLs or local paths, verifies the resolved artifacts still match the lockfile, and then executes the ordered install plan.

## Upgrade Core

Core initial deployment is a bootstrap exception, but Core upgrades can use the normal dbpm upgrade flow once Core is installed:

```powershell
uv run dbpm upgrade C:\Local_Exe\Repos\core --env development
```

For installed Core `3.2.0` or newer, dbpm stages resolved provenance before running the manifest-declared update script.

## Reinstall A Package

Destructive reinstall requires explicit intent:

```powershell
uv run dbpm reinstall C:\Local_Exe\Repos\utl_interval --env development --allow-destructive
```

If installed applications depend on the target, dbpm blocks before calling Core cleanup:

```text
dbpm: Cannot reinstall UTL_INTERVAL; installed applications depend on it: SIMPLE_SCHEDULER
```

## Resume A Failed Or Running Deployment

If a prior deployment left Core status as `R` or `F`, fix the deployment issue and resume:

```powershell
uv run dbpm resume C:\Local_Exe\Repos\utl_interval --env development
```

If the package is already complete, resume is refused:

```text
dbpm: UTL_INTERVAL deployment status is C; resume requires R or F
```

## Validate A Package

Run the package validation script declared in `dbpm.yaml`:

```powershell
uv run dbpm validate C:\Local_Exe\Repos\utl_interval --env development
```

For `utl_interval`, this runs:

```text
Tests/smoke_test.sql
```

## Run Tests

Unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Opt-in database integration test:

```powershell
. .\setenv.ps1
$env:DBPM_RUN_DB_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_integration_db.py -q
```
