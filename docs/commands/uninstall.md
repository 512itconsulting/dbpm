# `dbpm uninstall`

Uninstall a root application and its resolved dependency graph:

```text
dbpm uninstall <source> \
  [--dependency-source <source>]... \
  --runtime-prefix <path> \
  --allow-destructive
```

Uninstall is destructive and requires `--allow-destructive`. In a
deployment-locked environment it is blocked by policy.

For the application runtime, dbpm first validates the active receipt,
payloads, and command links. It then runs optional package runtime uninstall
scripts in reverse dependency order and removes only dbpm-managed runtime
state: `bin`, `packages`, retained generation metadata, staging content, and
the active receipt. The final receipt is archived as
`.dbpm/uninstalled-receipt.json`.

Application/operator-owned `etc` and `var` directories and unrelated files
under the runtime prefix are preserved. These durable directories are shared
at the application level; package-specific directory layers are optional.
Package uninstall scripts must not remove shared directories or
operator-owned files.

Database uninstall entry points are taken from `scripts.uninstall`. Packages
should keep those scripts SQL*Plus/SQLcl-compatible and idempotent.
