# `dbpm runtime reconcile`

Restore a missing or incomplete application runtime from the checksum-verified
installed lifecycle receipt:

```text
dbpm runtime reconcile [source | --application APP] \
  --runtime-prefix PATH \
  --connect STRING
```

Reconciliation reads Core's current operation and database state, acquires its
fenced lease, verifies the installed artifact snapshots, and classifies the
complete runtime graph before mutation. Missing and identical destinations are
safe to restore without a development capability. The current source checkout
is not authoritative and is not used for hooks or payload identity.

If the prefix is still unreachable, the operation remains
`RUNTIME_UNREACHABLE`. Conflicting destinations fail without mutation.

Reconciliation is subject to the same `DEPLOY_LOCKED=Y`/`--approve` policy as
`resume` — restoring a missing or identical runtime does not require a
development/disposable capability, but it is not a way to bypass a locked
target's approval requirement.

`--replace` is reserved for Phase 3 and currently fails closed with the required
`DBPM_ALLOW_RUNTIME_REPLACE` Core capability. It must never be treated as an
alias for ordinary structural repair.

Use `--dry-run` to inspect the receipt-backed recovery plan without mutation.
