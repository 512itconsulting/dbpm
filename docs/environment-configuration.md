# Environment Configuration

dbpm has two independent scopes:

- The dbpm executable is normally installed once as an isolated, user-level
  CLI tool.
- Deployment configuration belongs to one application and one target
  environment at a time.

Installing dbpm does not select an Oracle database, install Core, or create a
system-wide deployment environment.

## Profile Layout

Keep live target profiles outside application repositories. Use
`XDG_CONFIG_HOME`, which normally resolves to `~/.config`:

```text
~/.config/dbpm/
└── my_application/
    └── environments/
        ├── development.sh
        ├── test.sh
        └── production.sh
```

Profiles in this directory are operator-specific and may contain credentials.
Restrict their permissions:

```sh
chmod 600 "${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments/"*.sh
```

Do not place live profiles inside a package source directory. Ignoring a file
with Git does not necessarily exclude it from local artifact hashing or package
publication. An application repository may contain sanitized `*.example.sh`
templates that document the required settings, but never populated profiles.

CI/CD systems should provide the same variables through protected environments
and secret stores rather than creating a local profile.

## Select One Connection Form

Start every profile by clearing all connection forms:

```sh
unset DBPM_CONNECT
unset DBPM_CONNECT_NAME
unset DBPM_DB_USER
unset DBPM_DB_PASSWORD
unset DBPM_DB_DSN
```

Then select exactly one form.

Structured credentials are preferred when package runtime scripts also need
the individual values:

```sh
export DBPM_DB_USER="application_user"
export DBPM_DB_PASSWORD="application_password"
export DBPM_DB_DSN="tns_alias_or_host/service"
```

A raw Oracle connect string is supported:

```sh
export DBPM_CONNECT="user/password@service"
```

SQLcl users may select a saved connection without putting a password in the
profile:

```sh
export DBPM_SQL_RUNNER="sql"
export DBPM_CONNECT_NAME="Development Database (APP_USER)"
```

Do not put a SQLcl saved connection name in `DBPM_CONNECT`.

## Scope Each Invocation

Load a profile in a subshell so its values do not remain in the operator's
shell:

```sh
(
  source "${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments/development.sh"
  dbpm plan registry:example@^1.0.0 --mode install
)
```

Use a separate subshell for another target:

```sh
(
  source "${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments/production.sh"
  dbpm validate registry:example@1.0.0
)
```

Do not export database targets, passwords, or runtime prefixes from a global
shell startup file. Persistent target selection makes accidental cross-
environment execution more likely.

## Local and Shared State

Application- and environment-specific values include:

- Oracle connection selection
- `DBPM_RUNTIME_PREFIX`
- artifact repository credentials
- registry publishing credentials
- signing identity
- deployment policy inputs used before Core is available

The default artifact cache at `~/.dbpm/cache` is user-scoped and may safely be
shared across application targets because cached artifacts are content
addressed. Logs default to `.dbpm-logs` in the current working directory and
should remain associated with the invocation that produced them.

## Pin the CLI for Controlled Deployments

An interactive installation may track the current dbpm release:

```sh
pipx install dbpm
# or
uv tool install dbpm
```

Production automation should pin the CLI version independently of the Oracle
package version:

```sh
uvx --from dbpm==X.Y.Z dbpm validate registry:example@1.0.0
```

Alternatively, install a pinned user-level tool:

```sh
pipx install dbpm==X.Y.Z
# or
uv tool install dbpm==X.Y.Z
```

This keeps the dbpm CLI version, application package version, and target
environment configuration as three explicit and independently controlled
inputs.

## Credentials

Prefer SQLcl saved connections or a deployment platform's secret store for
production. If a local profile contains credentials, restrict its permissions:

```sh
chmod 600 "${XDG_CONFIG_HOME:-$HOME/.config}/dbpm/my_application/environments/production.sh"
```

Do not commit local profiles, print passwords in logs, or combine unrelated
publishing and deployment credentials unless the invocation requires both.
