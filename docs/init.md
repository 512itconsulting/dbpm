# Initializing a Package or Workspace

`dbpm init` scaffolds a new package or workspace directory with the standard
folder layout, a template manifest, and git-friendly placeholder files.

## Package

```sh
dbpm init package [directory] [--name NAME] [--version VERSION] [--description TEXT] [--force]
```

Creates the canonical package structure under `directory` (default: current
directory):

```text
dbpm.yaml
README.md
LICENSE
.gitignore
deployment_manifests/
  .gitignore          ← ignores SQL*Plus/SQLcl spool files (*.log, *.lst)
docs/
examples/
functions/
helper_scripts/
metadata/
packages/
procedures/
tables/
tests/
types/
```

All leaf directories contain a `.gitkeep` so the empty tree is tracked by git.
`deployment_manifests/` uses `.gitignore` instead to silently exclude log files
produced by SQL runners.

The generated `dbpm.yaml` references `deployment_manifests/deploy.sql` and
`deployment_manifests/update.sql` as install and upgrade entry points. Edit
those paths once you name the actual scripts.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `directory` | `.` | Target directory to initialize |
| `--name` | directory basename | Package name; must be lowercase letters, digits, `_`, or `-` |
| `--version` | `0.1.0` | Initial semantic version |
| `--description` | *(empty)* | Short package description |
| `--force` | off | Allow init in a non-empty directory; existing files are never overwritten |

### Example

```sh
mkdir my_package && dbpm init package my_package --name my_package --description "My Oracle package"
```

## Workspace

```sh
dbpm init workspace [directory] [--package NAME ...] [--force]
```

Creates a workspace structure suitable for a repository containing multiple
related packages and non-database code:

```text
dbpm-workspace.yaml
README.md
LICENSE
.gitignore
database/
  my_package/         ← one per --package argument
    dbpm.yaml
    deployment_manifests/
    docs/
    functions/
    helper_scripts/
    metadata/
    packages/
    procedures/
    tables/
    tests/
    types/
helper_scripts/
os/
```

Each package directory under `database/` is fully scaffolded with the same
layout as `dbpm init package` and is listed in `dbpm-workspace.yaml`.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `directory` | `.` | Target directory to initialize |
| `--package` | `my_package` | Package name to scaffold under `database/`; repeatable |
| `--force` | off | Allow init in a non-empty directory; existing files are never overwritten |

### Example

```sh
mkdir my_workspace
dbpm init workspace my_workspace --package billing --package orders
```

This creates `database/billing/` and `database/orders/`, each with a full
package scaffold, and a `dbpm-workspace.yaml` that declares both.

## Package Name Rules

Package names must start with a lowercase letter and contain only lowercase
letters, digits, underscores (`_`), or hyphens (`-`). These names map directly
to Oracle application registry names via `_application_name()`, which converts
them to uppercase with hyphens replaced by underscores.

Examples of valid names: `core`, `my_package`, `utl-bs-numeric`

## Non-Empty Directories

`dbpm init` refuses to run in a non-empty directory unless `--force` is given.
With `--force`, only missing files and directories are created — nothing
already present is modified or overwritten. This makes `--force` safe to run
on a partially initialized directory.
