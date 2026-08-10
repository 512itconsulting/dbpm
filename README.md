# dbpm

See [Convention-Driven SQL Generation](docs/script-generation.md) for
generating standalone install and versioned upgrade scripts from Git changes.

**dbpm** is a package manager for Oracle database applications and reusable PL/SQL components.

The goal is to bring modern dependency management, versioning, packaging, and deployment workflows to Oracle database development.

Visit the [dbpm website](https://dbpm.io/) for product documentation and the
[package registry](https://registry.dbpm.io/) for published package metadata.

## Installation

dbpm requires Python 3.11 or newer. Published releases are available on
PyPI. Install the CLI into an isolated, user-level environment with `pipx` or
`uv`:

```sh
# pipx
pipx install dbpm

# uv
uv tool install dbpm
```

Installing dbpm makes the executable available to the current OS user. It does
not select an Oracle database or create a system-wide dbpm deployment
environment. Package manifests, lockfiles, connection settings, and runtime
prefixes remain specific to an application and target environment. Avoid
installing dbpm into the system Python with `sudo pip`.

If isolated tool installation is unavailable, a user-site installation is
also supported:

```sh
python3 -m pip install --user dbpm
```

For a quick sanity check after installation:

```sh
dbpm --version
```

If you want to install directly from the GitHub repository instead of PyPI,
use:

```sh
python3 -m pip install --user git+https://github.com/512itconsulting/dbpm.git@v1.4.3
```

Database deployment commands require access to an Oracle database and an
Oracle-compatible command-line runner. Set `DBPM_SQL_RUNNER` to
[SQLcl](https://www.oracle.com/database/sqldeveloper/technologies/sqlcl/) (the
`sql` executable) or SQL*Plus. Core is dbpm's in-database deployment substrate;
run `dbpm check-core` before managed deployments, or use `dbpm bootstrap-core`
for an empty schema. See [Getting Started](docs/getting-started.md) for database
connection setup.

## Vision

dbpm aims to make Oracle database development feel more like modern software engineering ecosystems such as:

- Maven
- npm
- Cargo
- pip

while remaining Oracle-native and deployment-friendly.

Maven-compatible repositories may be useful for publishing immutable package artifacts, but dbpm should not require ordinary package consumers to understand Maven or install a JDK. Consumer installs should use dbpm's own CLI and plain HTTP(S) artifact retrieval where possible.

## Goals
- Package reusable PL/SQL libraries
- Deploy end-user Oracle database applications through the same package workflow
- Resolve dependencies automatically
- Support [semantic versioning](https://semver.org/)
- Enable repeatable deployments
- Use [Core](https://github.com/512itconsulting/core) as the in-database install registry and deployment substrate
- Support schema evolution
- Inject deployment provenance from package artifacts
- Lock deployments to immutable artifact identities
- Simplify CI/CD integration
- Reduce fragile hand-managed deployment scripts

Example
```sh
dbpm check-core --minimum-version 3.2.0
dbpm plan gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --mode install --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
dbpm install --lockfile dbpm-lock.json
```

For a guided setup, see [Getting Started](docs/getting-started.md).
See the [changelog](CHANGELOG.md) for release contents and
[release checklist](docs/releases.md) for the versioning process.

## Features
- Package manifests through `dbpm.yaml`, `dbpm.yml`, `dbpm.json`, or `package.dbpm.yaml`
- Per-package minimum dbpm CLI version requirements
- Workspace manifests through `dbpm-workspace.yaml` for repositories with multiple package roots
- Local package directory sources
- Local ZIP package sources
- GitHub Maven ZIP package sources with `gh-maven:owner/repo:group:artifact:version[:extension]`
- Generic Maven ZIP package sources with `maven:repository-url::group:artifact:version[:extension]`
- dbpm registry sources with `registry:package@constraint`
- HTTPS ZIP artifact sources for lockfile installs
- Maven snapshot ZIP resolution through `maven-metadata.xml`
- SHA-256 checksum capture for ZIP artifacts and deterministic TREE-SHA-256 capture for local directories
- Content-addressed artifact cache keyed by SHA-256 for lockfile-verified downloads
- Exact and caret-compatible dependency constraints
- Ordered multi-package install, conservative upgrade, and validate for dependency sources
- Dependency lockfile generation and verification through `dbpm lock`
- Lockfile-driven install without restating package sources
- Core-backed installed-state lookup
- Core-backed reverse-dependency lookup
- Core provenance staging through `pkg_application.stage_deployment_provenance_p`
- Core `DEPLOY_LOCKED`-aware deployment policy
- Install, upgrade, reinstall, resume, and validate workflows
- Application-owned runtime composition for manifest-declared runtimes
  (`runtime:` in `dbpm.yaml`), including isolated dependency payloads,
  package-local scripts, command exports, staged activation, validation,
  resume, upgrade, reinstall, uninstall, and rollback. See
  [spec/runtime-component.md](spec/runtime-component.md) for the behavioral
  contract.
- ZIP artifact publishing to GitHub Packages and generic Maven repositories
- GPG artifact signing and lockfile-driven signature verification
- dbpm registry source resolution and artifact metadata indexing

## Known Limitations
- Multi-package dependency execution does not support `reinstall`.
- Lockfile database provenance reconciliation requires Core 3.3.0 or newer.
- Non-lockfile installs use the coordinate-based cache without checksum verification; the lockfile path has full SHA-256 verification.

## Roadmap
- APEX integration
- Registry search/info commands and compatibility-aware registry resolution

## Status
Live-tested against GitHub Packages artifacts for:

- `core`
- `utl_interval`
- `simple_scheduler`

`simple_scheduler` depends on `utl_interval`; dbpm can install both from GitHub Packages in dependency order and record Core provenance with artifact URLs and SHA-256 checksums.

## Target Environment Configuration

Keep live dbpm profiles outside the application repository under the user's
configuration directory. This prevents credentials from entering source
artifacts. Start from the committed `dbpm-env.sh.example` template and name the
copy for one application and target environment:

```sh
profile_dir="${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments"
mkdir -p "$profile_dir"
cp dbpm-env.sh.example "$profile_dir/development.sh"
chmod 600 "$profile_dir/development.sh"
```

Only sanitized `*.example.sh` templates belong in an application repository.
Run dbpm in a subshell so target-specific variables do not remain active
afterward:

```sh
(
  source "${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments/development.sh"
  dbpm check-core --minimum-version 3.0.0
)
```

See [Environment Configuration](docs/environment-configuration.md) for profile
layout, CI guidance, safe target switching, and CLI version pinning.

Common variables:

- `DBPM_SQL_RUNNER`: SQLcl or SQL*Plus executable, such as `sql`
- `DBPM_CONNECT`: raw Oracle connect string, such as `user/password@service`
- `DBPM_DB_USER`, `DBPM_DB_PASSWORD`, and `DBPM_DB_DSN`: structured database credentials used together when `DBPM_CONNECT` is unset; package runtime scripts inherit them
- `DBPM_CONNECT_NAME`: SQLcl saved connection name local to the invoking OS user. Mutually exclusive with the raw and structured connection forms; requires SQLcl as the runner.
- `DBPM_GITHUB_TOKEN`: GitHub token with package read access
- `DBPM_GITHUB_USER`: optional GitHub username for package authentication
- `DBPM_SIGNING_KEY`: optional default GPG key ID, fingerprint, or email for `dbpm publish`
- `DBPM_MAVEN_TOKEN`: token for generic Maven publishing targets
- `DBPM_MAVEN_USER`: optional username for generic Maven publishing targets
- `DBPM_REGISTRY_URL`: optional default registry URL, default: `https://registry.dbpm.io`
- `DBPM_REGISTRY_TOKEN`: bearer token for registry indexing
- `DBPM_REGISTRY_PUBLISHER`: optional registry publisher override
- `DBPM_REGISTRY_DESCRIPTION`: optional registry description override
- `DBPM_CACHE_DIR`: optional local artifact cache directory, default: `~/.dbpm/cache`
- `DBPM_LOG_DIR`: optional execution log directory, default: `.dbpm-logs` in the current working directory
- `DBPM_RUN_DB_TESTS`: optional `1` to enable live database pytest tests

For SQLcl saved connections, do not put the saved connection name in
`DBPM_CONNECT`. Unset `DBPM_CONNECT` and set `DBPM_CONNECT_NAME` instead:

```sh
unset DBPM_CONNECT
export DBPM_CONNECT_NAME="Development Database (APP_USER)"
export DBPM_SQL_RUNNER=sql
```

Alternatively, use structured database credentials. dbpm composes the Oracle
connect string, while runtime scripts inherit the individual values:

```sh
unset DBPM_CONNECT DBPM_CONNECT_NAME
export DBPM_DB_USER="application_user"
export DBPM_DB_PASSWORD="application_password"
export DBPM_DB_DSN="tns_alias_or_host/service"
```

## Commands

| Command | Description |
|---|---|
| [`dbpm init`](docs/commands/init.md) | Scaffold a new package or workspace directory |
| [`dbpm check-core`](docs/commands/check-core.md) | Verify Core is installed and meets a minimum version |
| [`dbpm plan`](docs/commands/plan.md) | Generate and print a deployment plan without executing |
| [`dbpm lock`](docs/commands/lock.md) | Write or verify a dependency lockfile |
| [`dbpm bootstrap-core`](docs/commands/bootstrap-core.md) | Install Core into an empty schema |
| [`dbpm install`](docs/commands/install.md) | Install a package not yet registered in Core |
| [`dbpm upgrade`](docs/commands/upgrade.md) | Upgrade an installed package to a higher version |
| [`dbpm reinstall`](docs/commands/reinstall.md) | Destructively reinstall a package |
| [`dbpm resume`](docs/commands/resume.md) | Resume a running or failed deployment |
| [`dbpm validate`](docs/commands/validate.md) | Run a package's validation script |
| [`dbpm uninstall`](docs/commands/uninstall.md) | Remove an application and its managed runtime |
| [`dbpm rollback`](docs/commands/rollback.md) | Reactivate a database-compatible retained runtime generation |
| [`dbpm generate-scripts`](docs/commands/generate-scripts.md) | Generate standalone Oracle install and upgrade scripts from Git changes |
| [`dbpm publish`](docs/commands/publish.md) | Build and publish a package to a Maven repository with GPG signing |
| [`dbpm registry index`](docs/commands/registry-index.md) | Index a published immutable artifact in a dbpm registry |
| [`dbpm workspace list`](docs/commands/workspace.md) | List packages declared by a workspace manifest |

Run `dbpm <command> --help` for a quick flag reference. See [docs/commands/source-types.md](docs/commands/source-types.md) for the full source and version constraint syntax.

## Related Projects
- [core](https://github.com/512itconsulting/core)
