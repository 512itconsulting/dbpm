# Deployment Lock Policy Specification

## Purpose

Deployment lock policy controls which deployment behaviors are allowed in a target database.

dbpm should evaluate policy before executing a deployment plan, especially when the plan includes destructive actions or dirty local source deployments.

## Policy Source

For connected workflows, dbpm reads Core 3.5.0 deployment metadata from `APP_DICTIONARY`:

- `CORE / DEPLOY_LOCKED`: authoritative policy value, `Y` or `N`
- `CORE / DEPLOY_ENVIRONMENT`: optional human-readable environment label

`DEPLOY_ENVIRONMENT` answers "Where am I?" and must not drive policy. `DEPLOY_LOCKED` answers "Should dangerous deployment behavior be blocked?"

For disconnected `plan` and `lock` workflows, dbpm may use `--policy locked|unlocked`. The disconnected default is `unlocked`.

## Default Rules

| Mode | `DEPLOY_LOCKED=N` | `DEPLOY_LOCKED=Y` |
|---|---:|---:|
| `bootstrap-core` | Core install owns metadata setup | Core install owns metadata setup |
| `install` | allow | allow |
| `upgrade` | allow | allow |
| `resume` | allow | require approval |
| `validate` | allow | allow |
| `reinstall` | allow with `--allow-destructive` | block |

Dirty local source deployments should warn when unlocked and be blocked when locked.

## Bootstrap

Before Core exists, dbpm cannot read `DEPLOY_LOCKED`. Core's bootstrap/install script requires the operator to supply `DEPLOY_LOCKED`, validates `Y/N`, and stores the normalized value.

## Plan Output

The deployment plan should show:

- `deployment_locked`
- policy source, such as `core-dictionary`, `cli-policy`, or `default`
- `deploy_environment` when read from Core
- blocked actions
- required approvals
- dirty-artifact or dirty-source warnings
