# Environment Policy Specification

## Purpose

Environment policy controls which deployment behaviors are allowed in a target environment.

dbpm should evaluate policy before executing a deployment plan, especially when the plan includes destructive actions, dirty local source deployments, or production-oriented upgrades.

## Environment Identity

dbpm needs a reliable way to identify the target environment. Candidate sources include:

- an explicit CLI option
- a dbpm environment configuration file
- a Core dictionary value such as `CORE / DEPLOY_ENVIRONMENT`
- CI/CD variables supplied by the deployment runner

The selected source should be visible in the deployment plan.

## Environment Classes

Initial environment classes:

- `development`
- `test`
- `staging`
- `production`

Local names such as `DEV`, `QA`, or `PROD` may map to these classes.

## Default Rules

Suggested defaults:

| Mode | development | test | staging | production |
|---|---:|---:|---:|---:|
| `bootstrap-core` | allow | allow | require approval | require approval |
| `install` | allow | allow | allow | allow |
| `upgrade` | allow | allow | allow | allow |
| `repair` | allow | allow | require approval | require approval |
| `reinstall` | allow | require approval | block | block |

Dirty local source deployments should be allowed in development, require approval in test, and be blocked in staging and production.

## Overrides

Policy overrides should be explicit and recorded in the deployment log. Destructive overrides should require both:

- an explicit deployment mode such as `reinstall`
- an explicit override or approval flag

## Plan Output

The deployment plan should show:

- resolved environment name
- environment class
- policy source
- requested deployment modes
- blocked actions
- required approvals
- dirty-artifact or dirty-source warnings
