# dbpm dev reset

Replace a local package using the canonical reinstall implementation. The
normalized plan and plan digest are identical to the equivalent `dbpm
reinstall`; the audit surface records `dev reset` as the initiating command.

```sh
dbpm dev reset . --connect user/pass@db
dbpm dev reset . --dependency-source ../base --cascade graph \
  --runtime-prefix /opt/my-app --connect user/pass@db
```

The target must be unlocked and grant `DBPM_ALLOW_MUTABLE_SOURCE` and
`DBPM_ALLOW_SAME_VERSION_REPLACE`. A graph reset additionally requires
`DBPM_ALLOW_GRAPH_RESET`. Before mutation, dbpm shows the database service,
schema, Core environment, root application, removal order, and runtime prefix.
Confirmation is interactive unless `--yes` is supplied.

Graph reset removes consumers before dependencies and then installs
dependencies before consumers. Runtime activation replaces the resolved graph
as one unit while preserving application-level `etc` and `var` directories.
