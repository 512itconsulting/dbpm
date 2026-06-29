# dbpm bootstrap-core

Install or initialize Core, the dbpm in-database deployment substrate, into an empty or prepared schema. This command is required before any ordinary package deployments can run.

## Syntax

```
dbpm bootstrap-core source [--env ENV] [--approve] [--package NAME]
                           [--registry-url URL] [--dry-run]
                           [--connect STRING | --connect-name NAME] [--runner EXEC]
```

## EBNF diagram

```mermaid
flowchart LR
    command["command"] --> dbpm["dbpm"]
    dbpm --> bootstrap["bootstrap-core"]
    bootstrap --> source["source"]
    source --> options["{ option }"]
    options --> end_node(("end"))

    options -. expands to .-> option["option"]
    option --> env["--env ENV"]
    option --> approve["--approve"]
    option --> package["--package NAME"]
    option --> registry_url["--registry-url URL"]
    option --> dry_run["--dry-run"]
    option --> connect["--connect STRING or --connect-name NAME"]
    option --> runner["--runner EXEC"]

    package -. only when source is a workspace root .-> package_note["selects workspace package"]
    registry_url -. only for registry sources .-> registry_note["sets registry base URL"]
    dry_run -. changes execution .-> dry_run_note["prints plan without executing"]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `source` | required | Package source for the Core artifact. See [source types](source-types.md). |
| `--env` | `development` | Target environment name. Controls environment policy evaluation. |
| `--approve` | false | Approve policy-gated actions that would otherwise be blocked. |
| `--package` | none | Package name or application name to select when `source` is a workspace root. |
| `--registry-url` | `DBPM_REGISTRY_URL` or `https://registry.dbpm.io` | Registry base URL for `registry:` sources. |
| `--dry-run` | false | Print the deployment plan as JSON without executing. |
| `--connect` | `DBPM_CONNECT` | Raw SQL*Plus/SQLcl connect string. Mutually exclusive with `--connect-name`. |
| `--connect-name` | `DBPM_CONNECT_NAME` | SQLcl saved connection name. Requires SQLcl via `--runner` or `DBPM_SQL_RUNNER`. |
| `--runner` | `DBPM_SQL_RUNNER` or `sqlplus` | SQL runner executable. |

## Examples

Bootstrap Core from GitHub Packages:
```sh
dbpm bootstrap-core \
  gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0 \
  --connect user/pass@db
```

Preview the plan without executing:
```sh
dbpm bootstrap-core \
  gh-maven:512itconsulting/core:com.512itconsulting.database:core:3.4.0 \
  --dry-run
```

## Notes

- Core uses its own bootstrap manifest because `pkg_application` does not exist until Core's own objects are created. The bootstrap path is distinct from the ordinary install path.
- Run `dbpm check-core` after bootstrap to verify the installation.
- Core upgrades after initial bootstrap use `dbpm upgrade`, not `dbpm bootstrap-core`.
