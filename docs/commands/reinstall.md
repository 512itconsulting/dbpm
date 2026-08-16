# dbpm reinstall

Destructively reinstall a package by deleting its existing Core application registration and running a fresh install. Intended for active development databases. Blocked when Core `DEPLOY_LOCKED=Y`.

For Core itself, reinstall is a full system teardown: dbpm calls `pkg_application.delete_system_p` with Core's required confirmation text, runs Core's `Deployment_Manifests/uninstall.core.sql`, then runs the Core install script.

## Syntax

```
dbpm reinstall source [--approve] [--dry-run]
                     [--package NAME] [--registry-url URL]
                     [--allow-destructive] [--cascade graph]
                     [--dependency-source SOURCE]... [--yes]
                     [--confirm-delete-system CORE]
                     [--connect STRING | --connect-name NAME] [--runner EXEC]
```

## EBNF diagram

```mermaid
flowchart LR
    command["command"] --> dbpm["dbpm"]
    dbpm --> reinstall["reinstall"]
    reinstall --> source["source"]
    source --> options["{ option }"]
    options --> end_node(("end"))

    options -. expands to .-> option["option"]
    option --> approve["--approve"]
    option --> dry_run["--dry-run"]
    option --> package["--package NAME"]
    option --> registry_url["--registry-url URL"]
    option --> allow_destructive["--allow-destructive"]
    option --> confirm_system["--confirm-delete-system CORE"]
    option --> connect["--connect STRING or --connect-name NAME"]
    option --> runner["--runner EXEC"]

    allow_destructive -. required for execution .-> destructive_note["permits delete pre-action"]
    confirm_system -. required when source is Core .-> core_note["confirms Core system teardown"]
    package -. only when source is a workspace root .-> package_note["selects workspace package"]
    registry_url -. only for registry sources .-> registry_note["sets registry base URL"]
    dry_run -. changes execution .-> dry_run_note["prints plan without executing"]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `source` | required | Package source. See [source types](source-types.md). |
| `--approve` | false | Approve policy-gated actions. |
| `--dry-run` | false | Print the deployment plan as JSON without executing. |
| `--package` | none | Package name or application name to select when `source` is a workspace root. |
| `--registry-url` | `DBPM_REGISTRY_URL` or `https://registry.dbpm.io` | Registry base URL for `registry:` sources. |
| `--allow-destructive` | false | Required to allow the destructive pre-action (application deletion). Without this flag, dbpm fails before touching the database. |
| `--dependency-source` | none | Package source for a dependency in a graph reinstall. Repeatable. |
| `--cascade graph` | none | Reinstall the complete resolved graph. Requires `DBPM_ALLOW_GRAPH_RESET`. |
| `--yes` | false | Skip interactive confirmation for graph reinstall. Does not bypass Core policy. |
| `--confirm-delete-system` | none | Required for Core reinstall. Must be exactly `CORE`. |
| `--connect` | `DBPM_CONNECT` or structured database variables | Raw SQL*Plus/SQLcl connect string. `DBPM_DB_USER`, `DBPM_DB_PASSWORD`, and `DBPM_DB_DSN` are composed when the raw value is unset. Mutually exclusive with `--connect-name`. |
| `--connect-name` | `DBPM_CONNECT_NAME` | SQLcl saved connection name. Requires SQLcl via `--runner` or `DBPM_SQL_RUNNER`. |
| `--runner` | `DBPM_SQL_RUNNER` or `sqlplus` | SQL runner executable. |

## Preflight checks

dbpm fails before running any script if:

- `--allow-destructive` is not provided.
- Core `DEPLOY_LOCKED=Y`.
- A local directory replacement lacks `DBPM_ALLOW_MUTABLE_SOURCE`.
- Same-version replacement lacks `DBPM_ALLOW_SAME_VERSION_REPLACE`.
- `--cascade graph` lacks `DBPM_ALLOW_GRAPH_RESET`.
- The package is Core and `--confirm-delete-system CORE` is not provided.
- The package has installed dependents. The names of the blocking dependents are reported. Dependents must be reinstalled or removed first.

Unlike `upgrade`, reinstall does not block based on deployment status — it can recover a package in any state.

## Examples

Reinstall a local package in development:
```sh
dbpm reinstall ~/repos/utl_interval --allow-destructive --connect user/pass@db
```

Preview the destructive plan:
```sh
dbpm reinstall ~/repos/utl_interval --allow-destructive --dry-run
```

Reinstall Core in a disposable schema:
```sh
dbpm reinstall gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.5.0 \
  --allow-destructive \
  --confirm-delete-system CORE \
  --connect user/pass@db
```

## Notes

- `reinstall` calls `pkg_application.delete_application_p` before running the install script. This removes the Core application registration and any dependent records.
- Core reinstall is special because Core blocks `delete_application_p` for itself. It calls `pkg_application.delete_system_p` with confirmation text and requires Core `DEPLOY_LOCKED=N`, then runs `Deployment_Manifests/uninstall.core.sql` before reinstalling Core. Treat this as equivalent to wiping dbpm-managed state from the schema.
- Installed applications outside the selected graph that depend on a selected package block reinstall.
- Graph reinstall removes consumers before dependencies, then installs dependencies before consumers. Runtime replacement is validated and activated for the complete graph; application-level `etc` and `var` are preserved.
- Use `dbpm resume` when a previous deployment failed but data should be preserved. Use `dbpm reinstall` only when a clean slate is acceptable.
