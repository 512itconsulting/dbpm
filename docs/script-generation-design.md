# Convention-Driven SQL Generation Design

## Purpose

Manually maintaining Oracle full-install and release-update scripts is
repetitive and error-prone. dbpm should generate most deployment SQL from Git
history and repository conventions while preserving plain SQL artifacts that
can be executed without dbpm.

This is a producer-side capability. Core remains the authoritative in-database
registry, while dbpm inspects source history, determines deployment intent, and
renders standalone SQL.

## Requirements

Expose:

```sh
dbpm generate-scripts . --from <git-ref> [--to <git-ref>]
```

- `--from` is required.
- `--to` defaults to `HEAD`.
- Both refs identify committed Git states.
- CLI values override `dbpm.yaml`; conventions provide remaining defaults.
- Repositories without `dbpm.yaml` are supported when `--version` is supplied.
- Core repositories are rejected because Core's initial install requires a
  bootstrap-aware lifecycle.

Generate three distinct outputs:

```text
Deployment_Manifests/deploy.sql
Deployment_Manifests/releases/<version>/update.sql
Deployment_Manifests/update.sql
```

The top-level update script points to the versioned release update. Output
paths are configurable through CLI options, and install/current-upgrade paths
may default from `dbpm.yaml`.

## Object And Table Conventions

Canonical object files represent the current full-install state. Full installs
must never include lifecycle scripts.

Table lifecycle intent is expressed through files added within the release
comparison window:

```text
Tables/ORDERS.alter.1.5.0.sql
Tables/ORDERS.recreate.1.5.0.sql
Tables/OLD_ORDERS.drop.1.5.0.sql
```

- `alter` evolves an existing table and suppresses canonical table DDL during
  the update.
- `recreate` runs immediately before the canonical table DDL.
- `drop` permanently removes an object and its Core ownership.
- Lifecycle versions must match the target release version.
- A new table uses only canonical DDL and must not have an `alter` or
  `recreate` script.
- Conflicting lifecycle strategies are rejected.
- Semantic versions are parsed by dbpm; correctness never depends on OS
  filename sorting.

## Generation Behavior

Full-install generation inventories canonical objects from the complete tree at
`--to`, registers owned objects, and deploys objects in dependency-friendly
groups.

Release-update generation uses the Git diff between `--from` and `--to`:

1. Begin deployment.
2. Register every new or modified owned object with
   `pkg_application.add_object_p` so `APP_OBJECTS` records the new version.
3. Run permanent drop scripts without re-registering removed objects.
4. Run table alter scripts.
5. Run each recreate script immediately followed by its canonical DDL.
6. Create newly added tables.
7. Deploy new and modified replaceable objects.
8. Compile, validate, and complete deployment.

A modified canonical table without `alter` or `recreate` is omitted from active
update execution, emitted as commented SQL with a warning, and reported by the
CLI. A deleted object without a matching `drop` script receives a warning and
a blocking commented placeholder.

## Configuration And Validation

Zero-configuration defaults:

| Value | Default |
|---|---|
| Application name | Normalized repository directory name |
| Install output | `Deployment_Manifests/deploy.sql` |
| Release upgrade output | `Deployment_Manifests/releases/<version>/update.sql` |
| Upgrade pointer output | `Deployment_Manifests/update.sql` |

The application name and version may default from `dbpm.yaml`. Upgrade
deployment type is inferred from the baseline manifest version or a semantic
version baseline ref, with an explicit CLI override available.

`--check` must fail when any generated output is missing or stale, allowing CI
to enforce committed generated scripts.

## Acceptance Criteria

- Explicit historical `--from` and `--to` refs generate deterministic output.
- Omitting `--to` uses `HEAD`.
- CLI options override manifest values.
- Generation works without `dbpm.yaml` when required CLI inputs are supplied.
- Full installs exclude all lifecycle scripts.
- Updates register all new and modified owned objects.
- Recreate scripts immediately precede canonical DDL.
- Permanent drops are not re-registered.
- Unexplained table changes produce warnings and commented SQL.
- Semantic versions such as `3.10.0` are handled correctly.
- `--check` identifies stale generated outputs.
- Generated SQL has no runtime dependency on dbpm.

## Deferred Work

- Core bootstrap-aware script generation.
- Automatic dependency analysis inside SQL files.
- Multiple ordered lifecycle scripts for one object and release.
- Working-tree or staged-change generation.
