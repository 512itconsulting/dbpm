# `dbpm rollback`

Reactivate a retained application runtime generation:

```text
dbpm rollback \
  --runtime-prefix <path> \
  [--target-generation <number>] \
  (--connect <connect-string> | --connect-name <sqlcl-name>)
```

Without `--target-generation`, dbpm selects the newest retained generation.
Rollback verifies that every package version currently registered in Core
exactly matches the retained runtime graph. It fails before activation when
the database and runtime target are incompatible.

Rollback does not run downgrade scripts. It validates retained payloads and
executables, publishes the target command links, archives the formerly active
receipt, and records the rollback as a new monotonically increasing
generation.
