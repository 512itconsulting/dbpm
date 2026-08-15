# Development Lifecycle and Runtime Reconciliation

## Status

Design proposal. This document evaluates ways to make dbpm easier to use during
active, pre-release development without weakening the guarantees expected in
shared, released, or production deployments.

## Problem statement

dbpm's current lifecycle rules are intentionally conservative:

- uninstall and reinstall are explicitly destructive;
- upgrades require a higher semantic version and a declared upgrade path;
- runtime payloads must match the artifact identities in the deployment plan;
- installed dependents prevent isolated destructive replacement;
- locked environments reject dirty artifacts and destructive operations.

Those are appropriate release-oriented defaults. They become cumbersome when a
developer repeatedly changes and deploys a local application graph, especially
when several packages provide runtime payloads. A local checkout may have the
same semantic version but a different content checksum from the last deployment.
That is normal during development, but dbpm currently treats it much like
released-artifact drift.

The observed friction is primarily a lifecycle design gap, not a reason to
remove the existing safeguards. dbpm needs a first-class disposable-development
workflow with explicit policy boundaries.

## Current behavior contributing to the problem

### Uninstall is source-oriented

Uninstall planning resolves the current root source and dependency sources, then
reverses that newly resolved graph. The installed Core dependency graph and
active runtime receipt are validation targets rather than the primary authority.

Consequences include:

- an edited local checkout may no longer reproduce the installed runtime graph;
- the exact dirty source that produced an installed artifact may be impossible
  to reconstruct from its recorded Git commit;
- dependency sources must be supplied again just to remove already-installed
  packages;
- source drift can prevent database cleanup even when the operator explicitly
  requested an uninstall.

### Runtime identity is coupled to the current plan

Runtime uninstall validates the active receipt against the runtime graph
generated from the current sources. Version, path, commit, artifact URI,
checksum, and checksum algorithm must match.

This protects immutable deployments, but it means the current source tree can
block removal of an older installed tree. In development, the installed receipt
should be sufficient to remove the installed runtime.

### Database completion precedes runtime activation

For a multi-package deployment, dbpm executes the database packages and then
stages and activates the application runtime. A runtime activation failure can
therefore occur after Core records the application deployment as complete.

The normal `resume` command accepts database status `R` or `F`, not `C`. This can
leave an operation that is complete from Core's perspective but incomplete from
the application-runtime perspective, without a supported runtime-only recovery
path.

### Same-version content changes have no first-class operation

`upgrade` correctly rejects a target version equal to the installed version.
`install` correctly rejects an already-installed application. `reinstall` is the
remaining semantic fit, but it does not currently coordinate a multi-package
dependency graph.

As a result, a normal local development iteration may require manual uninstall
ordering, runtime cleanup, database reinstall, and runtime recovery even though
the desired operation is simply: make this disposable environment match the
current local graph.

### Deployment policy is mostly binary

Core currently provides a locked or unlocked deployment policy. That protects
production, but an unlocked shared integration environment and an intentionally
disposable developer schema have materially different risk tolerances.

The package version must not be used as the safety boundary. A `0.x` package can
be deployed to production, while a local `2.x` checkout can be disposable. The
target environment policy and artifact provenance are better signals.

## Design goals

1. Preserve the existing strict defaults for published artifacts and protected
   environments.
2. Make removal depend primarily on installed state, not on reconstructing the
   original source tree.
3. Give local development an explicit same-version replacement operation.
4. Coordinate database and runtime state as one resumable lifecycle operation.
5. Support application-graph reinstall and removal without accidentally deleting
   shared dependencies.
6. Preserve operator-owned `etc` and `var` content by default.
7. Keep Core protected from application-level reset operations.
8. Make destructive intent clear without requiring a collection of overlapping
   force flags.

## Options considered

### Option 1: Add force and ignore flags

Possible flags include:

```text
--ignore-runtime-identity
--force-same-version
--force-uninstall
```

This is the smallest implementation, but it is not recommended as the primary
design. Independent escape hatches are difficult to reason about in combination
and are easy to carry into environments where they should not be used.

Narrow emergency recovery flags may still be useful, provided they are gated by
authoritative environment policy and produce a prominent audit record.

### Option 2: Make uninstall installed-state-driven

This change is recommended regardless of the other choices.

A package manager should be able to remove an installed package even when the
source checkout has changed, moved, or disappeared. A source-free interface
could look like:

```text
dbpm uninstall --application APP_X
dbpm uninstall --application APP_X --cascade unused
```

The uninstall plan should derive:

- installed applications and dependencies from Core;
- runtime packages and artifact identities from the active runtime receipt;
- runtime uninstall hooks from installed payloads or an installed lifecycle
  receipt;
- database object ownership from Core;
- exact artifact retrieval information from recorded provenance.

The current source can remain optional. When supplied, it can provide additional
validation or operator-selected lifecycle hooks, but source drift should not make
the installed application impossible to remove in an eligible environment.

Cascade semantics must be explicit:

- no cascade: remove only the requested application and fail if dependents block
  it;
- `--cascade unused`: also remove dependencies with no remaining external
  dependents;
- `--cascade graph`: remove the complete reachable application graph;
- CORE is never part of an application cascade.

`--cascade graph` should be restricted to developer or disposable targets.

### Option 3: Add a policy-gated development reset workflow

This is the recommended user-facing direction.

Example commands:

```text
dbpm dev reset .
dbpm dev reset . --cascade graph
dbpm dev reset-environment --keep CORE
```

The command name itself expresses destructive intent. Requiring an additional
collection of force flags adds ceremony without necessarily adding meaningful
safety.

The workflow must use two independent keys:

1. Core marks the target as eligible for development or disposable operations.
2. The operator explicitly selects the development reset command.

One possible Core policy model is:

```text
DEPLOY_LOCKED=N
DBPM_LIFECYCLE=DEVELOPER
```

or:

```text
DEPLOY_LOCKED=N
DBPM_LIFECYCLE=DISPOSABLE
```

An alternative is capability-based metadata, such as:

```text
DBPM_ALLOW_MUTABLE_SOURCE=Y
DBPM_ALLOW_GRAPH_RESET=Y
DBPM_ALLOW_RUNTIME_REPLACE=Y
```

Capabilities are more precise, while lifecycle profiles are easier to operate.
A profile can be implemented as a documented set of capabilities.

Suggested policy behavior:

| Target class | Mutable source | Same-version replacement | Graph reset |
| --- | ---: | ---: | ---: |
| Locked/production | No | No | No |
| Shared unlocked | Configurable | No by default | No |
| Developer | Yes | Yes | Explicit |
| Disposable CI | Yes | Yes | Yes |

An environment name such as `DEV` is not sufficient by itself. Development
environments may contain valuable shared data. The destructive capability must
be deliberately configured in Core.

### Option 4: Make reinstall graph-aware

The existing `reinstall` operation is already close to the correct semantic
operation for clean-install-only packages. It should support:

- repeatable `--dependency-source` arguments;
- consumer-before-dependency deletion;
- dependency-before-consumer installation;
- runtime replacement for the entire resolved graph;
- same-version checksum replacement when target policy permits it;
- preservation of application-level `etc` and `var` directories;
- a final registry, object, compilation, and runtime audit.

An eligible development command could then be:

```text
dbpm reinstall . --cascade graph
```

For a local mutable source, a changed checksum at the same semantic version is
expected in developer mode. For a published immutable artifact, the same version
with a different checksum remains a hard supply-chain error, even in most
unlocked environments.

## Recommended policy model

Safety decisions should consider both target capabilities and source identity.

### Target authority

Core is authoritative for whether a target permits:

- dirty or mutable local sources;
- same-version replacement;
- destructive graph operations;
- runtime identity replacement;
- complete environment reset.

CLI environment variables may select connections and defaults, but they must not
be able to claim that a protected database is disposable.

### Source authority

dbpm should distinguish:

- a mutable local directory;
- a local immutable ZIP with a recorded checksum;
- a signed or checksummed registry artifact;
- the exact snapshot captured for an earlier installation.

Published artifact coordinates and checksums should remain immutable. Semantic
version `0.x` is not itself evidence that an artifact is disposable.

### Operator intent

The operator must explicitly choose the destructive or replacement operation.
In a developer profile, `dbpm dev reset` can serve as that declaration without a
second `--allow-destructive` flag. In automation, the environment capability and
the selected command provide the same two-key protection.

## Installed lifecycle receipts

Source-free removal and reliable recovery require dbpm to preserve enough of the
resolved installation to operate later.

At plan time, dbpm should snapshot every resolved local package into an immutable
artifact. Database deployment and runtime staging must use that snapshot rather
than the live working directory.

The installed lifecycle receipt should include:

- application name and semantic version;
- exact content checksum and checksum algorithm;
- source and published artifact coordinates;
- resolved dependency graph;
- database install, validate, and uninstall entry points;
- runtime payload paths, commands, and lifecycle hooks;
- deployment operation identifier;
- target runtime prefix, when applicable.

The artifact should be recoverable from one or more of:

- a local content-addressed installation cache;
- an application runtime cache;
- an immutable registry coordinate verified against the recorded checksum.

Core should retain the authoritative database identity and dependency records.
The filesystem receipt should retain the runtime-specific material. Neither
should require a dirty Git commit to reproduce uncommitted deployed content.

## Database and runtime operation state

Database deployment and runtime activation should be modeled as phases of one
operation:

1. resolve and snapshot artifacts;
2. evaluate policy and dependency graph;
3. stage the entire runtime;
4. validate all destination collisions without mutation;
5. begin the database operation;
6. execute database lifecycle scripts;
7. activate the runtime generation;
8. run database and runtime validation;
9. mark the composite operation complete.

The operation state must distinguish at least:

```text
RESOLVED
RUNTIME_STAGED
DATABASE_COMPLETE
RUNTIME_ACTIVE
VALIDATED
FAILED
```

If database deployment succeeds and runtime activation fails, `resume` must be
able to continue from `DATABASE_COMPLETE` without attempting another database
install or upgrade.

A separate recovery surface would also be useful:

```text
dbpm runtime reconcile .
dbpm runtime reconcile . --replace
```

Runtime replacement must be restricted to an eligible target. Structural repair
that restores a recorded installed identity can be allowed more broadly.

## Runtime activation improvements

Runtime activation should use a two-pass algorithm:

1. Classify every destination as missing, identical, replaceable, or conflicting.
2. Fail before mutation if any conflict is not permitted.
3. Promote, retain, or replace payloads only after the complete graph passes.

The current per-payload loop can remove an identical staged payload and then
encounter a conflict later in the graph. The retained staging generation is then
marked ready but is no longer complete enough for a straightforward retry.

Activation journals should be self-healing. A retry should recognize and safely
remove or reuse transient staged command directories rather than requiring
manual cleanup.

## Upgrade semantics

`upgrade` should remain strict and release-oriented:

- the target version must be higher;
- the migration path must be declared;
- published artifact identity must be immutable;
- dependency compatibility must be enforced;
- incomplete operations should use `resume`.

Same-version content replacement is not an upgrade. It belongs to `reinstall`,
`dev reset`, or a similarly explicit replacement operation.

For clean-install-only packages under active development, moving from one local
version to another can also use graph-aware reinstall. dbpm should not require a
synthetic upgrade script when the package has never been released and the target
is explicitly disposable.

## Environment reset

The recurring operation "remove all dbpm applications except CORE" deserves a
first-class command for disposable schemas:

```text
dbpm dev reset-environment --keep CORE --confirm EMMT_ADMIN
```

This command should:

1. require a Core disposable-environment capability;
2. require confirmation of the target schema or environment identity;
3. stop if CORE is not healthy;
4. calculate consumer-before-dependency removal order from Core;
5. remove each application's runtime and database ownership records;
6. preserve operator-owned `etc` and `var` by default;
7. verify that only CORE remains registered;
8. report registered-object remnants, known unmanaged remnants, and invalid
   objects;
9. never include CORE in the deletion plan.

An optional `--purge-var` should be a separate, more strongly confirmed action.

## Recommended implementation order

### Phase 1: Reliable installed-state lifecycle

1. Snapshot mutable local packages before execution.
2. Make uninstall source-optional and driven by Core plus installed receipts.
3. Add explicit cascade semantics.
4. Make runtime collision validation non-mutating and graph-wide.

### Phase 2: Recovery

1. Introduce composite database/runtime operation state.
2. Permit runtime-only resume after database completion.
3. Add supported runtime reconciliation and repair commands.

### Phase 3: Development workflows

1. Add Core developer/disposable lifecycle capabilities.
2. Add graph-aware reinstall with dependency sources.
3. Add `dbpm dev reset` for same-version local replacement.
4. Add `dbpm dev reset-environment --keep CORE` for disposable schemas.

### Phase 4: Auditing and ergonomics

1. Add a built-in post-removal and post-install audit.
2. Record every policy exception and destructive graph operation in deployment
   history.
3. Improve recovery guidance so errors name the supported next command rather
   than requiring manual receipt or runtime manipulation.

## Recommendation

Do not weaken `upgrade` or production artifact identity rules. Instead:

1. make uninstall authoritative from installed state;
2. make reinstall operate on a complete dependency and runtime graph;
3. add resumable composite database/runtime operations;
4. add an explicitly policy-gated development reset workflow;
5. add a disposable-environment reset that always preserves CORE.

This provides a compliant way to say "make this disposable target match my
current local graph" while keeping published and protected deployments strict,
deterministic, and auditable.
