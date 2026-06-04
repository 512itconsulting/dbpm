# Getting Started with dbpm

This guide walks through installing the dbpm CLI, configuring a Linux environment, bootstrapping Core, installing a package, and publishing a package artifact.

dbpm is an Oracle database package manager. It resolves package artifacts, plans dependency order, executes package manifests through SQL*Plus or SQLcl, and records deployment state in Core. Core is the in-database substrate for dbpm-managed deployments; ordinary packages depend on Core being present, but they should not list Core as a normal package dependency.

## Prerequisites

You need:

- Linux or another Unix-like shell environment.
- Python 3.11 or newer.
- `uv` for installing or running the Python CLI.
- Oracle SQLcl or SQL*Plus on the machine where dbpm runs.
- A target Oracle schema and connect string.
- A GitHub token if you consume private GitHub Packages artifacts.
- GPG if you publish packages with `dbpm publish`.

Install `uv` if needed:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Confirm the basic tools:

```sh
python3 --version
uv --version
sql -version
```

If you use SQL*Plus instead of SQLcl, confirm `sqlplus` is on your `PATH` or set `DBPM_SQL_RUNNER` to its full path.

## Install dbpm

Install dbpm as a user-level CLI tool:

```sh
uv tool install git+https://github.com/512itconsulting/dbpm.git
dbpm --help
```

For development from a local checkout:

```sh
git clone https://github.com/512itconsulting/dbpm.git
cd dbpm
uv sync
uv run dbpm --help
```

The examples below use `dbpm` directly. If you are working from a local checkout without installing the tool, replace `dbpm` with `uv run dbpm`.

## Configure Environment

Create a local environment file. Do not commit this file; it can contain credentials.

```sh
cp dbpm-env.sh.example dbpm-env.sh
```

Edit `dbpm-env.sh`:

```sh
export TNS_ADMIN="$HOME/.oracle/tns_admin"
export DBPM_SQL_RUNNER="$HOME/opt/sqlcl/bin/sql"
export DBPM_CONNECT="user/password@service_name"

# Required for private GitHub Packages.
export DBPM_GITHUB_TOKEN="github_token_with_package_read_access"
export DBPM_GITHUB_USER="github_username"

# Runtime directories.
export DBPM_CACHE_DIR="$HOME/.local/cache/dbpm"
export DBPM_LOG_DIR="$HOME/.local/state/dbpm_logs"
```

Load it before running dbpm:

```sh
source ./dbpm-env.sh
```

Check that dbpm can find the SQL runner and connect string:

```sh
printf '%s\n' "$DBPM_SQL_RUNNER"
printf '%s\n' "$DBPM_CONNECT"
```

## Understand Package Sources

dbpm accepts several source formats:

- A local package directory containing `dbpm.yaml`, `dbpm.yml`, `dbpm.json`, or `package.dbpm.yaml`.
- A local ZIP package.
- A GitHub Packages Maven coordinate.
- A generic Maven coordinate.
- A direct HTTPS ZIP URL for lockfile-driven installs.

Common GitHub Packages source form:

```text
gh-maven:owner/repo:group:artifact:version[:extension]
```

Example:

```text
gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0
```

See [source types](commands/source-types.md) for the full syntax.

## Bootstrap Core

Core must be installed before dbpm can run ordinary package deployments.

Preview the bootstrap plan:

```sh
dbpm bootstrap-core \
  gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0 \
  --dry-run
```

Bootstrap Core into an empty or prepared schema:

```sh
dbpm bootstrap-core \
  gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0
```

Verify Core:

```sh
dbpm check-core --minimum-version 3.4.0
```

Use `bootstrap-core` only for the initial Core installation. If Core already exists, dbpm will block bootstrap and tell you to use `upgrade`, `resume`, or an explicit destructive reinstall path.

## Install a Package

Preview a package install:

```sh
dbpm plan \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 \
  --mode install
```

Install the package:

```sh
dbpm install \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

Validate it if the package declares a validation script:

```sh
dbpm validate \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

## Install With Dependencies

When dependencies are declared and all sources are known, provide dependency sources so dbpm can resolve the full graph before any script runs.

```sh
dbpm plan \
  gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 \
  --mode install \
  --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

```sh
dbpm install \
  gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 \
  --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

Dependencies are installed before consumers. Core remains an implicit substrate prerequisite, not a normal dependency to resolve and install as part of every package graph.

## Use Lockfiles

For repeatable deployments, create a lockfile:

```sh
dbpm lock \
  gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 \
  --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

Install from the lockfile:

```sh
dbpm install --lockfile dbpm-lock.json
```

Check that a lockfile still matches package resolution:

```sh
dbpm lock \
  gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 \
  --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 \
  --check
```

Commit release-oriented lockfiles so production deployments use exact artifact identities and checksums.

## Upgrade, Resume, and Reinstall

Upgrade an installed package:

```sh
dbpm upgrade \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.1.0
```

If a deployment failed or was interrupted, prefer `resume`:

```sh
dbpm resume \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
```

Use `reinstall` only when a clean slate is acceptable:

```sh
dbpm reinstall \
  gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0 \
  --allow-destructive
```

Core reinstall is a schema-level dbpm system teardown. Treat it as equivalent to wiping dbpm-managed state from the schema. It requires both destructive flags:

```sh
dbpm reinstall \
  gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0 \
  --allow-destructive \
  --confirm-delete-system CORE
```

Avoid destructive reinstall in established environments unless the environment policy and operator intent are absolutely clear.

## Publish a Package

dbpm can build and publish a ZIP artifact to GitHub Packages or a generic Maven repository. It generates:

- `{artifact_id}-{version}.zip`
- checksums
- a detached GPG signature
- `{artifact_id}-{version}.pom`
- `maven-metadata.xml`

The uploaded POM is generated from the dbpm manifest. A checked-in `pom.xml` is optional legacy compatibility for repositories that still have other Maven-based workflows.

Add publish metadata to `dbpm.yaml`:

```yaml
publish:
  group: com.512itconsulting.database
  artifact_id: core
```

Configure GPG:

```sh
gpg --list-secret-keys --keyid-format=long
export DBPM_SIGNING_KEY="your-key-id-or-fingerprint"
```

Dry run:

```sh
dbpm publish ~/repos/core \
  --target gh-maven:512itconsulting/core \
  --group com.512itconsulting.database \
  --artifact-id core \
  --signing-key "$DBPM_SIGNING_KEY" \
  --dry-run
```

Publish:

```sh
dbpm publish ~/repos/core \
  --target gh-maven:512itconsulting/core \
  --group com.512itconsulting.database \
  --artifact-id core \
  --signing-key "$DBPM_SIGNING_KEY"
```

After verification, dbpm writes `dbpm-publish-receipt.json` in the package root.
The receipt contains immutable artifact metadata but no credentials. To index it
in a dbpm registry:

```sh
export DBPM_REGISTRY_URL="https://dbpm.io"
export DBPM_REGISTRY_TOKEN="your-publisher-token"

dbpm registry index ~/repos/core --dry-run
dbpm registry index ~/repos/core
```

Use `--index-registry` on `dbpm publish` to perform both steps in one command.
If indexing fails, the verified publish receipt remains available for retry.

See [dbpm publish](commands/publish.md) for details.
See [dbpm registry index](commands/registry-index.md) for indexing details.

## Troubleshooting

If dbpm cannot connect to the database, confirm:

```sh
source ./dbpm-env.sh
"$DBPM_SQL_RUNNER" -L "$DBPM_CONNECT"
```

If artifact downloads fail from GitHub Packages, confirm `DBPM_GITHUB_TOKEN` has package read access and `DBPM_GITHUB_USER` is set.

If paths show a literal `~`, use `$HOME` in environment files:

```sh
export DBPM_CACHE_DIR="$HOME/.local/cache/dbpm"
export DBPM_LOG_DIR="$HOME/.local/state/dbpm_logs"
```

If GPG signing fails, test signing outside dbpm:

```sh
echo "test" > /tmp/dbpm-gpg-test.txt
gpg --armor --detach-sign --local-user "$DBPM_SIGNING_KEY" /tmp/dbpm-gpg-test.txt
gpg --verify /tmp/dbpm-gpg-test.txt.asc /tmp/dbpm-gpg-test.txt
```

## Next Steps

- Read the command reference in [commands](commands/).
- Review [source type syntax](commands/source-types.md).
- Read the project [philosophy](philosophy.md) and [vision](vision.md).
- Run `dbpm <command> --help` for command-specific flags.
