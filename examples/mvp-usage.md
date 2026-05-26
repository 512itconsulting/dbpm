# MVP Usage Examples

These examples assume:

- dbpm is installed in the project virtual environment.
- SQLcl is available as `sql`.
- Core is already installed in the target schema.
- A local, uncommitted `setenv.ps1` or `setenv.sh` sets credentials.

Do not commit environment files that contain passwords.

## PowerShell Setup

Example local `setenv.ps1` shape:

```powershell
$env:DBPM_SQL_RUNNER = "sql"
$env:DBPM_CONNECT = "user/password@tns_alias_or_service"
```

Load it before running connected commands:

```powershell
. .\setenv.ps1
```

## Check Core

Verify Core is available and satisfies the minimum version:

```powershell
.\.venv\Scripts\dbpm.exe check-core --minimum-version 3.0.0
```

Expected output:

```text
CORE_VERSION=3.0.0
```

## Plan A Local Package Install

Generate a plan without connecting to the database:

```powershell
.\.venv\Scripts\dbpm.exe plan C:\Local_Exe\Repos\utl_interval --mode install --env development
```

Generate a connected plan that includes Core installed state and reverse dependencies:

```powershell
.\.venv\Scripts\dbpm.exe plan C:\Local_Exe\Repos\utl_interval --mode install --env development --connect $env:DBPM_CONNECT
```

## Install A Package

Install a package that is not already registered in Core:

```powershell
.\.venv\Scripts\dbpm.exe install C:\Local_Exe\Repos\utl_interval --env development
```

Before running the package deployment script, dbpm stages resolved provenance in Core with `pkg_application.stage_deployment_provenance_p`. The existing deploy script still receives the commit hash argument and calls `begin_deployment_p`; Core consumes the matching staged provenance when that deployment starts.

If the package is already installed, dbpm fails before running the deployment script:

```text
dbpm: UTL_INTERVAL is already installed; use reinstall or upgrade
```

## Reinstall A Package

Destructive reinstall requires explicit intent:

```powershell
.\.venv\Scripts\dbpm.exe reinstall C:\Local_Exe\Repos\utl_interval --env development --allow-destructive
```

If installed applications depend on the target, dbpm blocks before calling Core cleanup:

```text
dbpm: Cannot reinstall UTL_INTERVAL; installed applications depend on it: SIMPLE_SCHEDULER
```

## Resume A Failed Or Running Deployment

If a prior deployment left Core status as `R` or `F`, fix the deployment issue and resume:

```powershell
.\.venv\Scripts\dbpm.exe resume C:\Local_Exe\Repos\utl_interval --env development
```

If the package is already complete, resume is refused:

```text
dbpm: UTL_INTERVAL deployment status is C; resume requires R or F
```

## Validate A Package

Run the package validation script declared in `dbpm.yaml`:

```powershell
.\.venv\Scripts\dbpm.exe validate C:\Local_Exe\Repos\utl_interval --env development
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
