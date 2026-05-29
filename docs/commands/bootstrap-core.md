# dbpm bootstrap-core

Install or initialize Core, the dbpm in-database deployment substrate, into an empty or prepared schema. This command is required before any ordinary package deployments can run.

## Syntax

```
dbpm bootstrap-core source [--env ENV] [--approve] [--dry-run] [--connect STRING] [--runner EXEC]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `source` | required | Package source for the Core artifact. See [source types](source-types.md). |
| `--env` | `development` | Target environment name. Controls environment policy evaluation. |
| `--approve` | false | Approve policy-gated actions that would otherwise be blocked. |
| `--dry-run` | false | Print the deployment plan as JSON without executing. |
| `--connect` | `DBPM_CONNECT` | SQLPlus/SQLcl connect string. |
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
