# Convention-Driven SQL Generation

`dbpm generate-scripts` generates standalone Oracle install and upgrade SQL
from committed Git state. The generated SQL can be executed without dbpm.

See [dbpm generate-scripts](commands/generate-scripts.md) for the command
reference.

See [Convention-Driven SQL Generation Design](script-generation-design.md) for
the feature requirements, behavioral contract, and deferred scope.

Core repositories are intentionally unsupported because Core's initial install
uses a bootstrap lifecycle that differs from ordinary Core-dependent
applications.

## Usage

```sh
dbpm generate-scripts . --version 0.1.0
dbpm generate-scripts . --from v1.4.0 --to HEAD --check
```

Omitting `--from` generates only the initial full-install script. Supplying
`--from` generates the full install, the versioned release update, and the
current update pointer. `--to` defaults to `HEAD`. Supplied refs must resolve
to commits. CLI options override `dbpm.yaml`; without a manifest, provide
`--version`. Other zero-configuration defaults are:

```text
application name:          normalized repository directory name
install output:            Deployment_Manifests/deploy.sql
release upgrade output:    Deployment_Manifests/releases/<version>/update.sql
upgrade pointer output:    Deployment_Manifests/update.sql
```

The upgrade deployment type is inferred from the version stored in the
baseline manifest or a semantic-version `--from` ref such as `v1.4.0`. Use
`--deployment-type major|minor|patch` when neither source is available.

The optional manifest setting below changes the versioned release output:

```yaml
generation:
  release_upgrade_output: Deployment_Manifests/releases/{version}/update.sql
```

## Table Conventions

```text
Tables/ORDERS.sql
Tables/ORDERS.alter.1.5.0.sql
Tables/ORDERS.recreate.1.5.0.sql
Tables/OLD_ORDERS.drop.1.5.0.sql
```

- Canonical DDL represents the current full-install shape.
- `alter` evolves an existing table without running canonical DDL.
- `recreate` runs immediately before the updated canonical DDL.
- `drop` permanently removes an object and should normally call
  `pkg_application.drop_and_forget_object_p`.

Full installs contain only canonical object and metadata files. Upgrade scripts
register every new or modified object with `pkg_application.add_object_p`
before applying object changes. A modified canonical table without a matching
`alter` or `recreate` script is emitted as commented SQL with a warning.

Use `--check` in CI to fail when committed generated scripts are stale.

## Type Conventions

`Types/*.sql` files are treated as generic standalone type DDL. Use
`Types/*.tps` for type specifications and `Types/*.tpb` for type bodies when
ordering matters. dbpm emits type specifications before generic type SQL, and
generic type SQL before type bodies. It does not inspect `.sql` contents to
infer type spec or body intent.
