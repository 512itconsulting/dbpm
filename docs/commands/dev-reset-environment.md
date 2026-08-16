# dbpm dev reset-environment

Remove every dbpm-managed application except CORE from an explicitly eligible
schema.

```sh
dbpm dev reset-environment --keep CORE --confirm APP_SCHEMA \
  --connect user/pass@db
```

The command requires a healthy CORE installation and the independent
`DBPM_ALLOW_ENVIRONMENT_RESET` capability. `DBPM_ALLOW_GRAPH_RESET` does not
imply this permission. Applications are removed consumer-first and CORE is
excluded structurally. After removal, dbpm queries Core again and fails if any
non-CORE registration remains.

Use repeatable `--runtime-prefix PREFIX` arguments for colocated application
runtimes that belong to the target. Each verified installed receipt supplies
its uninstall graph and hooks. Runtime cleanup preserves application-level
`etc` and `var` by default. The confirmation summary lists all supplied
prefixes. Interactive confirmation is required unless `--yes` is supplied.
`--confirm` additionally asserts the connected schema or Core environment
label; it does not bypass the interactive prompt by itself.
