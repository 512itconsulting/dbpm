# Common dbpm Workflows

These examples assume:

- commands run on Linux or another Unix-like shell
- `dbpm` is installed on `PATH`
- SQLcl is available as `sql`, or `DBPM_SQL_RUNNER` points to SQL*Plus
- Core is already installed in the target schema
- a local, uncommitted `dbpm-env.sh` sets database and artifact credentials

Do not commit environment files that contain passwords or tokens.

## Environment Setup

Keep local environment scripts uncommitted. Start from the committed shell
template:

```sh
cp ./dbpm-env.sh.example ./dbpm-env.sh
chmod 600 ./dbpm-env.sh
```

Required for database commands:

- `DBPM_SQL_RUNNER`: SQLcl or SQL*Plus executable
- `DBPM_CONNECT`: raw Oracle connect string
- `DBPM_CONNECT_NAME`: SQLcl saved connection name, used instead of `DBPM_CONNECT`

Required for private GitHub Packages:

- `DBPM_GITHUB_TOKEN`: GitHub token with package read access

Optional:

- `DBPM_GITHUB_USER`: GitHub username used with `DBPM_GITHUB_TOKEN`. If omitted, dbpm falls back to `GITHUB_ACTOR` or `x-access-token`.
- `DBPM_CACHE_DIR`: local cache for downloaded and extracted package artifacts. Defaults to `~/.dbpm/cache`.
- `DBPM_LOG_DIR`: execution log directory. If omitted, dbpm writes logs under `.dbpm-logs` in the current working directory.
- `DBPM_RUN_DB_TESTS`: set to `1` to enable opt-in live database pytest tests.

Load the environment before running connected or remote package commands:

```sh
. ./dbpm-env.sh
```

## Check Core

Verify Core is available and satisfies the minimum version:

```sh
dbpm check-core --minimum-version 3.2.0
```

Expected output:

```text
CORE_VERSION=3.2.0
```

## Plan A Local Package Install

Generate a plan without connecting to the database:

```sh
dbpm plan ~/repos/utl_interval --mode install
```

Generate a connected plan that includes Core installed state and reverse dependencies:

```sh
dbpm plan ~/repos/utl_interval --mode install
```

## Plan Local Dependencies

When a package manifest declares dependencies, provide local package sources that may satisfy them:

```sh
dbpm plan ~/repos/consumer --mode install --dependency-source ~/repos/dependency
```

The resulting multi-package plan orders dependencies before consumers. If a
required dependency is not already installed in Core and no matching local
source is provided, planning fails before deployment.

Maven-compatible ZIP artifacts can be used as package sources. GitHub Packages
has a convenience source form:

```sh
export DBPM_GITHUB_TOKEN="<token-if-required>"
dbpm plan gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --mode install --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

The coordinate format is:

```text
gh-maven:owner/repo:group:artifact:version[:extension]
```

Generic Maven-compatible repositories use an explicit repository base URL:

```text
maven:repository-url::group:artifact:version[:extension]
```

For example:

```sh
dbpm plan maven:https://maven.pkg.github.com/512itconsulting/utl_interval::com.512itconsulting.database:utl_interval:1.0.0 --mode install
```

## Lock Resolved Artifacts

Write a lockfile for an install resolution:

```sh
dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

This writes `dbpm-lock.json` with the ordered package list, resolved artifact
URLs, SHA-256 checksums for ZIP artifacts, provenance fields, and dependency
metadata.

Local package directory sources record deterministic `TREE-SHA-256` checksums
instead of ZIP archive checksums. The tree checksum is based on relative source
paths and file bytes, while ignoring local cache, VCS, build-output,
virtual-environment, and log noise.

Verify that the current resolution still matches the lockfile:

```sh
dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 --check
```

Verify that the connected database has the locked package versions installed
with complete Core deployment status and matching Core provenance rows:

```sh
dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 --check --check-db
```

## Install A Package

Install a package that is not already registered in Core:

```sh
dbpm install ~/repos/utl_interval
```

Before running the package deployment script, dbpm stages resolved provenance
in Core with `pkg_application.stage_deployment_provenance_p`. The existing
deploy script still receives the commit hash argument and calls
`begin_deployment_p`; Core consumes the matching staged provenance when that
deployment starts.

If the package is already installed, dbpm fails before running the deployment script:

```text
dbpm: UTL_INTERVAL is already installed; use reinstall or upgrade
```

Install can use the same local dependency sources:

```sh
dbpm install ~/repos/consumer --dependency-source ~/repos/dependency
```

dbpm executes each package in dependency order and stops on the first failed package.

Install can also use a previously written lockfile without restating the root
package or dependency sources:

```sh
dbpm install --lockfile dbpm-lock.json
```

When no lockfile path is provided, `--lockfile` defaults to `dbpm-lock.json`:

```sh
dbpm install --lockfile
```

dbpm reloads the locked artifact URLs or local paths, verifies each artifact's
SHA-256 checksum against the lockfile, and then executes the ordered install
plan. A content-addressed cache (`~/.dbpm/cache/by-checksum/`) means subsequent
lockfile installs of the same artifact skip the network entirely.

Each package script execution streams output to the console and writes the same
output to a log file. By default, logs are written under `.dbpm-logs` in the
current working directory. Set `DBPM_LOG_DIR` to choose a different location.

## Upgrade Core

Core initial deployment is a bootstrap exception, but Core upgrades can use the
normal dbpm upgrade flow once Core is installed:

```sh
dbpm upgrade ~/repos/core
```

For installed Core `3.2.0` or newer, dbpm stages resolved provenance before
running the manifest-declared update script.

## Upgrade With Local Dependencies

Upgrade can use dependency sources conservatively. Supplied dependency sources
are upgraded before the consuming package only when the dependency is already
installed, complete, and lower than the supplied source version:

```sh
dbpm upgrade ~/repos/consumer --dependency-source ~/repos/dependency
```

If a supplied dependency source is not installed, dbpm refuses the upgrade and
tells you to install first rather than turning the upgrade into an implicit
install.

## Reinstall A Package

Destructive reinstall requires explicit intent:

```sh
dbpm reinstall ~/repos/utl_interval --allow-destructive
```

If installed applications depend on the target, dbpm blocks before calling Core cleanup:

```text
dbpm: Cannot reinstall UTL_INTERVAL; installed applications depend on it: SIMPLE_SCHEDULER
```

## Resume A Failed Or Running Deployment

If a prior deployment left Core status as `R` or `F`, fix the deployment issue and resume:

```sh
dbpm resume ~/repos/utl_interval
```

If the package is already complete, resume is refused:

```text
dbpm: UTL_INTERVAL deployment status is C; resume requires R or F
```

## Validate A Package

Run the package validation script declared in `dbpm.yaml`:

```sh
dbpm validate ~/repos/utl_interval
```

For `utl_interval`, this runs:

```text
Tests/smoke_test.sql
```

Validation can use dependency sources too. dbpm validates supplied dependency
sources before the consuming package:

```sh
dbpm validate ~/repos/consumer --dependency-source ~/repos/dependency
```

## Run Tests

Unit tests should run without live database environment variables. If
`DBPM_CONNECT` or `DBPM_CONNECT_NAME` is set, some CLI tests will correctly
attempt connected planning or preflight checks, which makes the unit suite
depend on Oracle network access.

Use the helper script:

```sh
./scripts/test-unit.sh
```

Equivalent manual form:

```sh
unset DBPM_CONNECT
unset DBPM_CONNECT_NAME
unset DBPM_RUN_DB_TESTS
python -m pytest
```

Opt-in database integration tests should be run separately after loading the
local database environment:

```sh
. ./dbpm-env.sh
export DBPM_RUN_DB_TESTS="1"
python -m pytest tests/test_integration_db.py
```
