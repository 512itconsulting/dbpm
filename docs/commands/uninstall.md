# `dbpm uninstall`

Uninstall a root application and its resolved dependency graph:

```text
dbpm uninstall <source> \
  [--dependency-source <source>]... \
  --runtime-prefix <path> \
  --allow-destructive
```

For installations made with Phase 1 lifecycle receipts, the source is optional:

```text
dbpm uninstall --application APP_NAME \
  --runtime-prefix <path> \
  --allow-destructive [--cascade unused]
```

This path verifies and uses the immutable installed snapshot. It does not read
hooks from the current checkout or live runtime payload, and passes only the
documented `DBPM_*` environment to receipt-backed runtime hooks. A checksum
mismatch stops before any hook runs. `--cascade unused` removes only packages
recorded as `AUTO_DEPENDENCY` that have no external dependents; manual packages
survive. `--cascade graph` remains unavailable until Core exposes the
`DBPM_ALLOW_GRAPH_RESET` capability planned for Phase 3.

Uninstall is destructive and requires `--allow-destructive`. In a
deployment-locked environment it is blocked by policy.

Before running database uninstall scripts, dbpm validates the active runtime
receipt, payloads, and command links, and runs package health scripts. After
database removal, it repeats the structural receipt, payload, and command
validation without rerunning package health scripts. It then runs optional package
runtime uninstall scripts in reverse dependency order and removes only
dbpm-managed runtime state: `bin`, `packages`, retained generation metadata,
staging content, and the active receipt. The final receipt is archived as
`.dbpm/uninstalled-receipt.json`.

Application/operator-owned `etc` and `var` directories and unrelated files
under the runtime prefix are preserved. These durable directories are shared
at the application level; package-specific directory layers are optional.
Package uninstall scripts must not remove shared directories or
operator-owned files.

Database uninstall entry points are taken from `scripts.uninstall`. Packages
should keep those scripts SQL*Plus/SQLcl-compatible and idempotent.
