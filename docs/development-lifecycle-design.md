# Development Lifecycle and Runtime Reconciliation

## Status

Design proposal. This document evaluates ways to make dbpm easier to use during
active, pre-release development without weakening the guarantees expected in
shared, released, or production deployments.

This proposal was adversarially reviewed; the findings adopted from that review
are folded into the sections below, and the findings not yet decided are
recorded in [Open design questions](#open-design-questions) rather than as a
separate document.

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

## Scope and dependencies

This design does not attempt to solve every safety question a full lifecycle
overhaul eventually touches. Three boundaries are intentional:

- **Capability privilege is inherited, not redefined.** Who is authorized to
  set `DBPM_LIFECYCLE=DEVELOPER`/`DISPOSABLE` (or the equivalent capability
  flags) on a Core target is governed by Core's existing administrative
  authorization model. This design does not introduce a new privilege system;
  it only requires that whatever mechanism already controls Core configuration
  mutation covers this capability, and that changes to it are audited with
  actor, time, previous value, and new value.
- **Cross-package data ownership is a pre-existing gap, not a new one.**
  Packages can own rows in tables belonging to other packages (application
  configuration living in a shared UFL/MFT-style table is one example).
  Removing an application's registered schema objects does not by itself
  remove that cross-package configuration or its processing lineage today,
  independent of this proposal. The lifecycle hook contract described later
  assumes package-owned objects; closing the cross-package ownership gap is
  tracked separately and is not a precondition for this design.
- **One colocated runtime prefix per deployment.** This design assumes a
  single local runtime instance per database deployment, matching current
  dbpm behavior. Multiple runtime hosts, disconnected nodes, or a deployment
  continued from a different workstation are out of scope; supporting that
  topology is a separate design effort.

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
- runtime uninstall hooks from the checksum-verified installed lifecycle
  receipt, never read directly from the live runtime payload;
- database object ownership from Core;
- exact artifact retrieval information from recorded provenance.

Hook content must be verified immediately before execution, and the receipt
must not be able to redirect execution outside the verified artifact. If no
verified snapshot is available, dbpm must either perform a narrowly defined
structural cleanup without hooks, or stop with a supported recovery path.
Running an unverified installed hook, even in development, is a distinct
emergency operation with its own audit record — it is not part of ordinary
source-free uninstall.

This is a change to how dbpm resolves hook paths today, not a restatement of
existing behavior: runtime payload resolution currently derives the package
root and every script reference — including uninstall — from the live source
checkout, for every mode. An edited or deleted checkout already changes what
an uninstall would execute. The fix is scoped: runtime payload resolution
needs a second, receipt-backed path, so that for uninstall and other
maintenance-mode operations, package root and script reference resolve
against the installed lifecycle receipt's recorded snapshot location instead
of the current source. Checksum verification belongs immediately before the
hook process is launched, not earlier in planning, so a snapshot that changed
between plan and execution is still caught.

Runtime scripts currently inherit the full ambient process environment in
addition to the `DBPM_*` variables dbpm sets. That is an acceptable
convention when a script is resolved from a source the operator controls, but
the receipt-backed hook path should not inherit it — pass an explicit
allowlist of `DBPM_*` variables only. Introducing a trusted, source-free
execution path is the right moment to stop trusting the ambient environment
along with it.

Phase 1 should require hooks to be idempotent — safe to invoke again after a
crash or retry — without yet adding enforced timeouts or automatic retry.
Those require executor changes beyond hook sourcing and can follow once the
receipt-backed path is in place; they should not block it.

The current source can remain optional. When supplied, it can provide additional
validation or operator-selected lifecycle hooks, but source drift should not make
the installed application impossible to remove in an eligible environment.

Cascade semantics must be explicit, and every removal plan must state why each
package is included. dbpm should record the installation reason for every
package:

```text
MANUAL
AUTO_DEPENDENCY
APPLICATION_ROOT
```

With that record available:

- no cascade: remove only the requested application and fail if dependents block
  it;
- `--cascade unused`: remove dependencies with no remaining external dependents,
  restricted to packages installed as `AUTO_DEPENDENCY` — a `MANUAL` dependency
  survives even if currently unreferenced;
- `--cascade graph`: remove the complete reachable dependency graph regardless
  of installation reason; this is a distinct, more destructive choice from
  `--cascade unused`;
- a reverse-dependent cascade (removing packages that depend on the target) is a
  separate, explicitly named option, never an implicit side effect of `graph`
  or `unused`;
- a graph reset prints the complete ordered package list, with each entry's
  inclusion reason, before confirmation;
- CORE is excluded structurally from cascade resolution, not by a late runtime
  check.

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

Selecting the command name is not a substitute for confirming the connected
target. Before mutating anything, `dev reset` and `dev reset-environment` must
display a confirmation summary — database service, schema, Core environment
label, root application, ordered package removal list with cascade reasons,
and affected runtime prefixes — and require interactive confirmation by
default. Noninteractive execution requires an explicit `--yes`; it does not
bypass the two-key protection above. This keeps the command name's destructive
intent paired with an explicit look at what it is about to touch, rather than
replacing that look.

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

## Authority and trust hierarchy

The sections above establish several independent sources of truth: Core policy,
Core's registry, recorded provenance, installed receipts, the live runtime, and
the operator's current source tree. This proposal only works if dbpm has one
explicit answer for which source wins when they disagree — without it,
"installed-state-driven" and "policy-gated" are aspirations, not rules an
implementation can follow.

### Precedence, highest to lowest

1. **Protected Core policy.** Whether a target is locked, and whether it permits
   mutable source, same-version replacement, destructive graph operations, or
   environment reset, is decided by Core and by nothing else. Nothing lower in
   this list can override `DEPLOY_LOCKED=Y` or an absent disposable capability —
   not an operator flag, not a CLI environment profile, and not a match between
   a local source checksum and what Core expects.
2. **Verified immutable artifact and operation receipt.** Once a snapshot has
   been taken and checksummed under the rules in Installed lifecycle receipts,
   that artifact — and the operation record describing what was done with it —
   is the authoritative description of what dbpm actually deployed. It outranks
   the live filesystem and the current source because both of those can change
   after the fact without dbpm's involvement.
3. **Core's installed application and dependency state.** The registry of what
   is installed, what depends on what, and why (`MANUAL` / `AUTO_DEPENDENCY` /
   `APPLICATION_ROOT`) is authoritative for planning removal, cascade, and
   ownership questions, even when a receipt is missing or a runtime host is
   unreachable.
4. **Verified runtime receipt.** The filesystem-side record of what is active at
   a given prefix (version, path, commit, artifact URI, checksum) is
   authoritative for runtime-specific operations — activation, staging,
   generation promotion — but only once verified against its recorded checksum.
   An unverified receipt is observed state, not ground truth.
5. **Current local source — only when explicitly selected for replacement.** A
   mutable checkout is never consulted to validate an existing installation; it
   is only ever an input to a new replacement or install operation the operator
   has explicitly requested, and only when Core policy for the target permits
   mutable source.
6. **Live runtime filesystem, as observed state only.** What is actually present
   on disk is useful for collision detection, drift reporting, and
   classification (missing / identical / replaceable / conflicting), but it is
   never trusted as executable input. Runtime uninstall hooks in particular must
   never be read from the live payload — the live filesystem can tell dbpm
   *that* something changed, never *what to run* because of it.

A CLI environment profile or connection selector sits outside this ranked list
entirely: it may choose *which* target dbpm talks to, but it never supplies a
fact used to decide *what that target is allowed to do*. If a local profile
claims a capability that Core's policy does not confirm for the connected
target, dbpm must reject the operation rather than reconcile the two — a
mismatch here is treated as a misconfigured or spoofed profile, not as
ambiguity to resolve in the operator's favor.

### Applying the hierarchy to conflicts

- **Receipt says X, live filesystem says Y (drift or tampering).** The verified
  receipt wins for anything executable (hooks, entry points). The filesystem
  difference is reported as drift; it does not by itself authorize an operation
  the receipt doesn't describe.
- **Source tree matches what's installed, but Core policy is locked.** Locked
  wins. A dirty-but-matching checksum is not evidence of authorization.
- **No receipt is recoverable, but Core still lists the application as
  installed.** Core's registry (level 3) is sufficient to plan a structural
  removal without hooks; a missing receipt blocks hook execution, not removal
  entirely, per the fallback described in Option 2.
- **A runtime host is offline and its receipt can't be confirmed.** Database
  removal proceeds from Core's registry (level 3) with a tombstone recorded for
  the unreachable runtime instance; the offline host is reconciled later against
  levels 2 and 4 once it's reachable again, rather than blocking database
  cleanup indefinitely.

This hierarchy is binding on every command in this proposal, not background
philosophy: any operation that would need a lower authority to override a
higher one — trusting a live payload's hook over a verified receipt, or letting
a CLI profile mark a target disposable — is out of scope for this design and
must be rejected in implementation.

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

### Snapshot content and integrity

A local checkout is not a safe artifact source by default. It may contain
credentials, `.env` files, logs, test archives, generated data, ignored files,
or other operator-local content that must never be captured, checksummed, or
retained.

- Snapshot only a manifest-defined package allowlist or reproducible build
  output — never an unfiltered working-tree copy.
- Use identical inclusion rules for checksum calculation and for artifact
  creation. Hashing one file set and packaging a different one reopens the gap
  this receipt exists to close.
- Never include `.git`, environment profiles, local secrets, runtime `var`, or
  other unrelated working-tree files by default.
- Create the snapshot only after execution is approved, not during a dry-run.
- Store snapshots with restrictive filesystem permissions.
- Never store a rendered script that embeds credentials or environment secrets;
  render those at execution time from a separately governed source.
- Document cache location, retention, garbage collection, and size limits for
  the snapshot store, and retain an artifact for as long as any installed
  lifecycle receipt references it.

The recorded checksum must identify the exact artifact that database deployment
and runtime staging consume. If a later step reads different bytes than were
hashed, the checksum verifies nothing.

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

Step 3 is deliberately scoped to collision validation, not script execution.
Classifying every destination as missing, identical, replaceable, or
conflicting only needs the destination paths already present in the graph, so
that check can move ahead of the database phase with no new risk. Actually
running each payload's install script is a separate action and stays in its
current position, after the database phase, until either existing runtime
scripts are audited for database independence or a package explicitly opts in
(for example, a manifest `stage_before_database: true` flag). Runtime scripts
have always run after database completion up to now and have never been
required to work without it, so moving script execution earlier is a real
behavior change, not a formalization of current practice.

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

## Destructive dry-run fidelity

The safety of any destructive command depends on a preview that matches what
execution will actually do. A dry-run that only models expected behavior,
without inspecting the connected target, is not a safety mechanism for a
destructive operation.

For any destructive command (uninstall, reinstall with replacement, dev reset,
environment reset), a connected dry-run must execute the same read-only steps as
execution:

- Core policy lookup;
- installed application and dependency lookup;
- reverse-dependency lookup;
- lifecycle receipt and artifact verification;
- runtime prefix and generation inspection;
- graph construction and ordering;
- hook availability checks;
- collision classification;
- confirmation summary generation.

Execution should either consume the reviewed plan directly or verify that a
freshly generated plan has the same plan digest as the one the operator
confirmed. A dry-run that does not inspect the connected target must be clearly
labeled as a disconnected model and must not be presented as an execution
preview.

## Upgrade semantics

`upgrade` should remain strict and release-oriented:

- the target version must be higher;
- the migration path must be declared;
- published artifact identity must be immutable;
- dependency compatibility must be enforced;
- incomplete operations should use `resume`.

Same-version content replacement is not an upgrade. It belongs to `reinstall`,
`dev reset`, or a similarly explicit replacement operation, and it must not be
allowed to invalidate dependents silently:

- record a deployment revision or artifact checksum separately from semantic
  version, so two installs of "the same version" remain distinguishable;
- invalidate lockfile comparisons made against the previous checksum;
- identify reverse dependents that were built or validated against the prior
  artifact;
- redeploy or validate affected consumers as part of the same operation, or
  explicitly report which consumers were excluded from the replacement graph;
- forbid isolated replacement of a single package when target policy requires
  graph consistency.

For clean-install-only packages under active development, moving from one local
version to another can also use graph-aware reinstall. Whether a synthetic
upgrade script can be skipped must depend on authoritative target lifecycle
capability, explicit operator selection of the replacement operation, and
source identity/checksum classification — not on whether the package "has never
been released." A local dbpm invocation cannot prove global release history, so
release status must not be used as an automatic safety decision.

## Environment reset

The recurring operation "remove all dbpm applications except CORE" deserves a
first-class command for disposable schemas:

```text
dbpm dev reset-environment --keep CORE --confirm EMMT_ADMIN
```

This command should:

1. require a Core disposable-environment capability;
2. require confirmation of the target schema or environment identity;
3. stop if CORE is not healthy, and direct the operator to the registry salvage
   workflow below rather than attempting a normal reset against an inconsistent
   registry;
4. calculate consumer-before-dependency removal order from Core;
5. remove each application's runtime and database ownership records;
6. preserve operator-owned `etc` and `var` by default, subject to the
   classification below;
7. verify that only CORE remains registered;
8. report remnants by evidence tier, not as one undifferentiated list;
9. never include CORE in the deletion plan.

### Preserved-state classification

"Preserve `etc` and `var`" is not a single behavior. A fresh database install
may immediately consume stale configuration, work queues, inbox files, locks, or
cached payloads left behind by the prior install, so the reset result must
enumerate preserved paths and warn when they could affect the new deployment.
Runtime state should be classified before any purge decision is made:

- operator configuration and secrets;
- durable business or input data;
- application work state;
- reproducible caches;
- logs and diagnostics.

Purge behavior should be granular against this classification. Selecting
`--purge-var` must not delete configuration or secrets, and disposable work
state should not be preserved automatically just because it shares a directory
with durable business data. An optional `--purge-var` remains a separate, more
strongly confirmed action, scoped to the categories the operator selects.

### Remnant reporting

Core can report registered objects, but an unregistered object cannot reliably
be attributed to an application by name convention alone — automatically
dropping a suspected remnant risks deleting an unrelated schema object. The
audit must separate:

- registered objects that should have been removed;
- invalid objects remaining in the schema;
- objects explicitly listed in a verified package ownership manifest;
- suspected objects identified only by naming convention;
- application configuration rows with declared ownership;
- runtime instances not acknowledging removal.

Only authoritative ownership evidence — Core registration or a verified
ownership manifest — should permit automatic deletion. Convention-based matches
must be reported for operator review, never dropped automatically.

### Registry salvage when Core itself is unhealthy

An inconsistent Core registry may be the *reason* an operator needs a reset, so
requiring healthy Core for the normal workflow can block the recovery case that
needs it most. That case requires a separate `doctor`/salvage workflow, not a
relaxed reset:

- it must never masquerade as a normal uninstall or environment reset;
- it performs a read-only inventory first;
- it distinguishes registry corruption from an incomplete application
  deployment;
- it requires stronger confirmation and authoritative artifact receipts than
  normal reset;
- it produces a manual remediation plan when ownership cannot be proven, rather
  than guessing;
- it never infers ownership solely from object naming.

## Recommended implementation order

### Phase 1: Reliable installed-state lifecycle

1. Snapshot mutable local packages before execution.
2. Make uninstall source-optional and driven by Core plus installed receipts.
3. Add explicit cascade semantics.
4. Make runtime collision validation non-mutating and graph-wide.

`--cascade unused` (restricted to `AUTO_DEPENDENCY` packages) is a bounded
refinement of existing uninstall behavior and can ship in this phase.
`--cascade graph` is the actual destructive-capability delta and must wait for
the Core developer/disposable capabilities added in Phase 3, even though both
are introduced under item 3 above.

Phase 1 is done when:

- A tampered or replaced installed hook (checksum mismatch against the
  installed lifecycle receipt) is never executed.
- Uninstall completes correctly with the local source checkout deleted or
  unavailable, using only Core and the installed lifecycle receipt.
- A dependency installed with reason `MANUAL` is never removed by
  `--cascade unused`, regardless of what else is being removed in the same
  operation.
- `--cascade graph` is unavailable until the Phase 3 developer/disposable
  capability is granted; attempting it without that capability fails closed
  and names the required capability.
- Runtime collision validation runs against the full dependency graph without
  staging or mutating any payload, and reports every conflicting destination
  in one pass rather than failing on the first.

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

## Open design questions

The adversarial review raised several questions this proposal has not yet
resolved. They are recorded here as open questions rather than folded into the
recommendations above, because no specific answer has been chosen — only the
question and its stakes. Each should be resolved before the phase that depends
on it begins; none of them are implementation decisions yet.

### Operation saga mechanics — before Phase 2

Database and runtime operation state defines the phase states an operation
moves through, but not how `resume` recovers reliably. Open: whether an
operation needs a lease or fencing token to prevent concurrent continuation, a
monotonically increasing attempt number, and durable per-step receipts that let
`resume` roll forward from recorded evidence rather than inferring completion
from Core application status alone.

### Lifecycle hook contract detail — before Phase 1 hook execution

Option 2 now specifies where hooks come from (a receipt-backed resolution path
in the planner, checksum-verified immediately before launch, replacing the
live-source lookup `_application_runtime_package()` currently uses for every
mode including uninstall), what environment they receive (an explicit `DBPM_*`
allowlist instead of inherited `os.environ`), and that Phase 1 requires
idempotency without yet enforcing timeout or retry — that's deferred by design,
not open. Still open: ordering relative to dependents during cascade, whether
database access is guaranteed at each hook phase beyond uninstall (which is
Core/receipt-driven and does not require it), and what happens after a partial
DML/DDL failure — Oracle DDL auto-commit means this can't assume rollback.

### Threat model — before implementation begins

No section enumerates what this design defends against: wrong-target
operations, an unauthorized policy change, a tampered payload or receipt,
source mutating between plan and execution, a compromised or unavailable
registry, concurrent operators, a crashed operator process, an offline runtime
host, accidental deletion of a manually installed dependency, and accidental
deletion of operator-owned data. Authority and trust hierarchy answers *which
source wins*; a threat model would state *what each rule defends against*, and
should stay consistent with it. Recommended format when this is written: one
table, threat → defending section(s) → residual risk, assembled from sections
already in this document rather than introduced as new mechanism.

### Acceptance criteria — before each phase is considered done

Phase 1's criteria are now recorded with Phase 1 itself, under "Phase 1 is done
when." Phases 2-4 still need theirs written the same way, as each phase is
scoped rather than all upfront.

### Runtime staging purity contract — before Phase 1 collision validation

"Database and runtime operation state" now splits this: collision validation
is pure path inspection and safe to run before database changes; actually
executing each payload's install script stays in its current post-database
position. What remains open is empirical, not architectural — whether any real
runtime script depends on database state during staging, which requires
auditing real packages (none exist in this repo to audit) or relying on the
proposed `stage_before_database: true` manifest opt-in until one is audited.

### `dev reset` vs. graph-aware `reinstall` — before Phase 3

Open: whether `dev reset` is a genuinely separate command or policy-gated
syntax sugar over `reinstall` that compiles to the same normalized plan
(recording which surface initiated it). Two independent implementations of
destructive graph replacement should not ship; which one is canonical needs a
decision before Phase 3.

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
