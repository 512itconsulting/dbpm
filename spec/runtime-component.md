# Composable Application Runtime Specification

## Status

Design revision; not implemented.

dbpm 1.3 implements a transitional package-owned runtime model: a package
declares `runtime.name`, dbpm installs its script-managed payload directly into
an operator-provided prefix, and installed state is recorded in
`<prefix>/.dbpm/receipt.json`.

This specification supersedes the unimplemented `runtime.into` contribution
design. The revised model makes the selected root application the owner of one
application runtime. Runtime-bearing dependencies install into isolated
package directories beneath that application runtime and declare exports that
dbpm activates at the application level.

Until this design is implemented:

- `runtime.name` remains the only supported runtime manifest form.
- the existing receipt schema and direct-to-prefix installation behavior
  remain unchanged
- manifests must not use the proposed `runtime.exports` or application runtime
  composition fields described below
- `runtime.into` should not be implemented or adopted

## Purpose

dbpm is a package manager for composable Oracle applications. Reusable
packages are normally dependencies of an end-user application rather than
standalone deployments. Some packages also contain host-side programs,
scripts, templates, or other non-database assets.

The runtime model must compose those assets with the same dependency graph
that dbpm resolves for the database deployment. Given an application package
that depends on packages such as `job_control`, dbpm should materialize one
application runtime containing isolated payloads for the root application and
each runtime-bearing dependency.

This model provides:

- one operator-selected runtime root per deployed application
- isolated, versioned package payloads
- application-level commands assembled from declarative package exports
- deterministic conflict detection and application-controlled aliases
- graph-level installed-state and artifact provenance
- staging and atomic activation instead of in-place replacement
- a foundation for validation, rollback, uninstall, and garbage collection

## Design Principles

### The root application owns the runtime

The package selected by the operator is the root application and defines the
deployment boundary. Its full resolved dependency graph is installed into one
application runtime prefix.

A reusable dependency does not own the application prefix and does not choose
where its consumers deploy it. The same package may be installed independently
under several application prefixes at different versions.

### Packages own isolated payloads

Each runtime-bearing package installs only within its assigned package
directory. It must not write directly into another package directory or into
application-level `bin`, `etc`, or `var` directories.

dbpm, rather than package install order, owns application-level composition.

### Exports are declarative

A package declares the commands or other resources it makes available to a
consuming application. dbpm validates and activates those exports. Package
install scripts prepare package-local content but do not create
application-level links.

### Mutable state is separate from immutable payloads

Versioned package directories contain replaceable package payloads. Persistent
configuration, secrets, logs, queues, and other operator or application data
do not belong in those directories.

### Workspace and runtime are different concepts

A `dbpm-workspace.yaml` file describes source-repository package discovery. It
does not define a deployed runtime boundary. The root package selected for an
install, together with its resolved dependency graph, defines that boundary.

## Terminology

- **Root application**: the package explicitly selected for installation. It
  is the root of the resolved dependency graph and the identity of the
  application runtime.
- **Application runtime**: the host-side materialization of a root application
  and its runtime-bearing dependency graph.
- **Application runtime prefix**: the operator-selected root directory for an
  application runtime, such as `/opt/warehouse_app`.
- **Package payload**: one package version's isolated runtime installation
  beneath the application runtime prefix.
- **Export**: a package-local resource that dbpm exposes at the application
  level. Commands are the first export type.
- **Activation**: the atomic publication of a validated runtime graph and its
  application-level export links.
- **Runtime receipt**: dbpm-owned installed state describing the activated
  application graph, payload locations, artifact identities, and exports.

## Filesystem Layout

The logical layout is:

```text
<prefix>/
  bin/
    warehouse-run -> ../packages/warehouse_app/2.0.0/bin/warehouse-run
    job-control   -> ../packages/job_control/1.1.0/bin/job-control
  packages/
    warehouse_app/
      2.0.0/
        bin/
        lib/
    job_control/
      1.1.0/
        bin/
        lib/
  etc/
  var/
  .dbpm/
    receipt.json
    lock
    staging/
```

The names in this example are illustrative, but the ownership boundaries are
normative:

- `<prefix>/packages/<package>/<version>/` is package-owned during its runtime
  script and dbpm-owned for lifecycle management.
- `<prefix>/bin/` is dbpm-owned and contains only activated command links.
- `<prefix>/.dbpm/` is dbpm-owned metadata and staging space.
- `<prefix>/etc/` and `<prefix>/var/` are application/operator-owned mutable
  areas. Packages may document expected content but must not overwrite it
  implicitly.

Package and version path segments must be derived from validated manifest
values and must not permit path traversal. dbpm should use relative symlinks
for application-level links so an application runtime can be relocated as a
unit when the underlying platform supports it.

The prefix must exist and be writable by the invoking user. Creating OS users,
root-owned directories, systemd units, or other privileged host resources
remains an operator prerequisite. dbpm must not require privilege elevation.

## Root Application And Dependency Graph

The normal package manifest remains the source of application identity and
dependencies:

```yaml
package:
  name: warehouse_app
  version: "2.0.0"

dependencies:
  - name: job_control
    version: "^1.1.0"
  - name: warehouse_loads
    version: "^2.4.0"
```

The package explicitly selected by `dbpm install` is the root application.
Dependencies are never inferred from runtime exports or filesystem content.
dbpm resolves the ordinary package dependency graph, lockfile, artifact
identity, environment policy, and Core requirements before composing runtime
payloads.

Installing a dependency as a root package is valid when an operator
deliberately selects it, but that produces a distinct application runtime. It
does not make that package the implicit owner of every runtime in which it
appears.

## Proposed Package Manifest

A package with host-side content declares package-local runtime scripts and
exports:

```yaml
runtime:
  scripts:
    install: os/dbpm/install.sh
    upgrade: os/dbpm/upgrade.sh
    validate: os/dbpm/validate.sh
    uninstall: os/dbpm/uninstall.sh
  exports:
    commands:
      job-control: bin/job-control
```

The root application may declare its own payload and exports in exactly the
same form:

```yaml
runtime:
  scripts:
    install: os/dbpm/install.sh
    validate: os/dbpm/validate.sh
  exports:
    commands:
      warehouse-run: bin/warehouse-run
```

Proposed field semantics:

- `runtime.scripts`: executable entry points relative to the package artifact
  root. `install` is required when a package needs to construct or copy a
  payload. A future manifest revision may permit export-only packages whose
  payload is copied declaratively.
- `runtime.scripts.upgrade`: optional migration entry point. If absent,
  upgrade uses the idempotent `install` entry point against a newly staged
  package directory.
- `runtime.scripts.validate`: optional read-only validation entry point.
- `runtime.scripts.uninstall`: optional cleanup entry point scoped to the
  package payload. It must not remove shared application state.
- `runtime.exports.commands`: mapping from a requested application-level
  command name to a relative executable path within the installed package
  payload.

`runtime.name`, `runtime.home_env`, and `runtime.into` do not belong in the
new manifest contract. Package identity already comes from `package.name`;
the application prefix belongs to the root deployment; and every dependency
contributes through isolation plus exports rather than by writing into another
package's directory.

Future export types may include libraries, templates, plugin descriptors, or
other explicitly composable resources. Each type requires defined activation,
collision, and ownership semantics before it is added. Arbitrary overlay of
package directory trees is not an export type.

## Application-Level Runtime Configuration

The default activated name of a command is the key declared by the exporting
package. The root application may resolve conflicts or present application-
specific names through explicit configuration:

```yaml
runtime:
  commands:
    aliases:
      job_control.job-control: warehouse-jobs
```

The canonical identity of an export is `<package-name>.<export-name>`, such as
`job_control.job-control`. Canonical identities are stable references within
plans, lockfiles, receipts, and application configuration.

The exact location of application-level configuration remains an
implementation design decision. It may be part of the root package manifest
or a separate deployment manifest if operator choices must remain outside the
published package artifact. Before implementation, the schema must define:

- aliases from canonical command identities to activated names
- explicit selection when more than one package requests the same name
- optional suppression of an otherwise exported command
- whether environment-specific overrides may change command presentation
  without changing dependency resolution

Aliases affect presentation only. They must not change package resolution or
artifact identity.

## Export Validation And Collision Policy

For every command export, dbpm must verify before activation that:

- the target path is relative and remains inside the exporting package payload
- the target exists after the package install script succeeds
- the target is a regular executable file, or a symlink whose fully resolved
  target remains within the same package payload
- the activated command name is valid for the target platform

Two exports requesting the same application-level name are a hard planning
error unless the root application explicitly selects, aliases, or suppresses
one of them. Installation order must never decide the winner, and dbpm must
never silently replace an unrelated command.

An activated name must also not overwrite a non-dbpm-managed file already
present in `<prefix>/bin`. dbpm may replace a link only when the current
receipt proves that dbpm owns that link for the same application runtime.

## Prefix Resolution

The application runtime prefix is resolved once for the entire root
application graph:

1. an explicit `--runtime-prefix` command-line option
2. an application-level environment variable, if the future manifest schema
   provides one

dbpm must not resolve a separate prefix for each dependency. It must not use a
dependency-specific variable such as `JOB_CONTROL_HOME` to choose the
application deployment boundary.

If the graph contains runtime components and no prefix is available, execution
fails with a clear message. dbpm must not guess `/opt/<name>`.

One prefix represents one root application installation. If its receipt names
a different root application, installation must fail unless the operator uses
a separately designed replacement or adoption workflow. Merely sharing a
dependency does not permit two applications to share a prefix.

## Runtime Script Contract

Runtime scripts execute:

- with the extracted immutable package artifact as the working directory
- as the invoking OS user
- against a staged, package-specific payload directory
- only after artifact verification, dependency solving, Core checks, and
  environment policy evaluation

The proposed environment is:

| Variable | Meaning |
|---|---|
| `DBPM_RUNTIME_PREFIX` | absolute application runtime prefix |
| `DBPM_RUNTIME_PACKAGE_PREFIX` | absolute staged payload directory for this package version |
| `DBPM_RUNTIME_MODE` | `install`, `upgrade`, `reinstall`, `resume`, `validate`, or `uninstall` |
| `DBPM_ROOT_PACKAGE_NAME` | root application package name |
| `DBPM_ROOT_PACKAGE_VERSION` | root application version being deployed |
| `DBPM_PACKAGE_NAME` | current package name |
| `DBPM_PACKAGE_VERSION` | current package version |
| `DBPM_INSTALLED_VERSION` | previously activated version of this package, empty when absent |
| `DBPM_COMMIT_HASH` | resolved artifact commit provenance |
| `DBPM_ARTIFACT_URL` | resolved artifact URL or coordinate |
| `DBPM_ARTIFACT_SHA256` | verified artifact checksum, or the defined local-tree identity |

`DBPM_RUNTIME_PACKAGE_PREFIX` is the only installation target for the package
script. The application prefix is supplied for read-only context and for
locating documented application-owned state. A script must not mutate
application-level links, another package payload, `.dbpm` metadata, or shared
mutable state.

Scripts must be idempotent within their assigned staged directory. A non-zero
exit fails the package runtime step. dbpm captures stdout and stderr in the
normal execution logs.

Secrets are never injected as artifact content or rendered by dbpm. Service
start, stop, supervision, OS account management, and privileged host
configuration remain outside dbpm.

## Planning, Staging, And Activation

Runtime composition is a graph-level operation:

1. Resolve the root application and complete dependency graph.
2. Verify lockfile identities, checksums, signatures, Core requirements, and
   deployment policy.
3. Determine which packages have runtime payloads and collect all exports.
4. Resolve aliases and reject export conflicts before running scripts.
5. Acquire `<prefix>/.dbpm/lock`.
6. Stage each changed package payload without modifying the activated graph.
7. Run package validation against the staged graph.
8. Build the next receipt and application-level links in staging.
9. Atomically activate the new links and receipt.
10. Retain or garbage-collect superseded payloads according to explicit
    policy.

Dependency order applies while constructing payloads. The owner/contributor
ordering from the former `runtime.into` design is unnecessary because no
package writes into another package's payload.

Activation must be transactional from the application's perspective. Before
activation, the old graph remains usable. If staging or validation fails, dbpm
records diagnostic state without publishing partial command links. If
activation itself cannot be fully atomic on a supported platform, the
implementation specification must define recovery markers and deterministic
resume behavior.

Service quiescence remains an operator responsibility. Plan output must show
all runtime payload and activated-command changes so the operator can decide
whether a running process needs to be stopped.

## Runtime Receipt

The receipt is authoritative for host-side application runtime state:

```text
<prefix>/.dbpm/receipt.json
```

A new schema version is required because the existing
`dbpm.receipt.v0` owner/contributor model has different semantics. An
illustrative shape is:

```json
{
  "schema": "dbpm.application-runtime.v1",
  "application": {
    "name": "warehouse_app",
    "version": "2.0.0"
  },
  "packages": {
    "warehouse_app": {
      "version": "2.0.0",
      "path": "packages/warehouse_app/2.0.0",
      "commit": "<40-char hash>",
      "artifact_url": "https://...",
      "artifact_sha256": "<hex>",
      "status": "complete"
    },
    "job_control": {
      "version": "1.1.0",
      "path": "packages/job_control/1.1.0",
      "commit": "<40-char hash>",
      "artifact_url": "https://...",
      "artifact_sha256": "<hex>",
      "status": "complete"
    }
  },
  "commands": {
    "warehouse-run": {
      "package": "warehouse_app",
      "export": "warehouse-run",
      "target": "packages/warehouse_app/2.0.0/bin/warehouse-run"
    },
    "job-control": {
      "package": "job_control",
      "export": "job-control",
      "target": "packages/job_control/1.1.0/bin/job-control"
    }
  },
  "activated_at": "2026-07-25T18:04:00Z"
}
```

The final schema should also record:

- root artifact identity and the lockfile identity used for resolution
- every runtime-bearing package's artifact provenance and installed path
- the canonical identity and activated name of each export
- deployment mode and activation generation
- enough prior-generation state for deterministic resume or rollback
- platform information needed to interpret links

The receipt is dbpm-owned. Runtime programs may read it but must not modify it.
The receipt describes host state and does not replace Core's database
deployment records. Optional database-side runtime reporting remains
observability, not authority.

## Deployment Modes

- **install**: stage the complete runtime graph and activate it only after all
  required payloads and exports validate.
- **upgrade**: resolve the new graph, stage changed package versions beside the
  active versions, validate, and atomically switch activation.
- **reinstall**: reconstruct package payloads with explicit destructive intent,
  but never implicitly delete application-owned `etc` or `var` content.
- **resume**: continue or repeat staging based on receipt and recovery state;
  it must not treat a partially staged graph as active.
- **validate**: verify receipt identity, package payloads, export targets, and
  package-declared read-only health checks without mutating activation.
- **uninstall**: remove the root application's activated links and receipt,
  then remove package payloads according to policy. It operates on the
  application runtime as a whole, not by uninstalling a dependency from an
  otherwise unresolved graph.

Removing or changing a dependency is an application upgrade driven by the new
resolved graph. A package payload becomes eligible for garbage collection only
when no activated or retained generation references it.

## Upgrade And Rollback

Versioned package paths allow a new graph to be prepared without overwriting
the active graph. This is the preferred upgrade mechanism even when policy
normally retains only one active version.

Rollback should mean reactivating a previously retained, fully verified graph,
not running downgrade scripts in place. A future implementation design must
specify:

- how many inactive generations or payload versions are retained
- whether rollback is a distinct command or an install of an older lockfile
- how database compatibility is checked before host runtime rollback
- when package uninstall scripts run relative to garbage collection

dbpm must not promise host-only rollback when the database schema has already
advanced incompatibly.

## Artifact And Lockfile Interaction

Runtime payloads remain inside normal immutable dbpm package artifacts. The
existing artifact URL, checksum, signature, cache, and lockfile mechanisms
therefore cover both database and host-side content.

The dependency lockfile defines the desired package graph. The runtime receipt
records how that graph was materialized and activated on a host. Validation
should reconcile the receipt with the lockfile in the same spirit that
database validation reconciles Core state.

Built programs such as wheels should normally be bundled into the package
artifact so installation remains reproducible and offline-capable. dbpm does
not resolve PyPI, npm, or other language dependency graphs during deployment.
A future typed runtime kind may install a bundled artifact while preserving
the same package isolation, receipt, and activation contracts.

## Security And Integrity

Before activation, dbpm must defend the application boundary:

- reject absolute export targets and path traversal
- reject package scripts that produce exports escaping their payload through
  symlinks
- do not follow untrusted links when replacing or removing managed paths
- never overwrite unowned application-level files
- hold an exclusive application runtime lock during mutation
- write receipts and link sets using safe staging and replacement operations
- preserve verified artifact provenance for every activated payload

Package scripts execute as trusted code from a verified package artifact, but
dbpm should still constrain their documented write contract to the assigned
payload directory.

## Alternatives Rejected

### Dependencies own runtime prefixes

The transitional `runtime.name` model makes a reusable dependency appear to
own the deployment boundary. This works for a standalone program but does not
represent the normal dbpm case in which an application composes several
packages.

### Packages contribute into another package

The former `runtime.into` design lets one package write files into a runtime
owned by another dependency. That couples reusable packages to a particular
host layout, makes file ownership and collisions ambiguous, and makes upgrade
and uninstall depend on script ordering. Isolated payloads plus declarative
exports provide the desired composition without shared-directory mutation.

### One prefix per dependency

Resolving a separate operator prefix for every dependency shifts dependency
composition back to deployment documentation and environment variables.
The application graph should be deployable through one application-level
prefix choice.

### Flattened payload overlay

Copying every dependency into one shared directory makes provenance,
collisions, rollback, and safe removal difficult. Only explicitly declared
exports should be flattened into an application-level namespace.

### Workspace-owned runtime

A source workspace can contain several independently deployable applications
or reusable packages. Making it the runtime owner would confuse repository
organization with deployment identity.

## Compatibility And Migration

The implemented `runtime.name` behavior cannot be silently reinterpreted
because existing scripts may write throughout `DBPM_RUNTIME_PREFIX` and
existing receipts use owner semantics.

Implementation requires an explicit compatibility plan:

1. Introduce the new manifest and receipt schema behind a version or
   capability boundary.
2. Continue reading legacy manifests and receipts with their original
   semantics for a documented transition period.
3. Provide a dry-run migration report that identifies legacy files, proposed
   package payload locations, exports, and unmanaged conflicts.
4. Require explicit operator action to adopt an existing prefix; never infer
   ownership from directory names.
5. Do not create `runtime.into` as an intermediate migration mechanism.

Whether the new manifest retains the top-level name `runtime` or uses an
explicit manifest schema version must be settled before implementation.

## Relationship To Existing Specifications

- `manifest.md`: the selected root package and its normal dependencies define
  the application graph; this specification extends package manifests with
  package-local runtime payloads and exports.
- `package-layout.md`: a workspace remains source discovery only and does not
  own a deployed runtime.
- `deployment-modes.md`: modes apply to graph staging and activation in
  addition to database execution.
- `lockfile.md`: the lockfile is desired graph identity; the runtime receipt
  is host materialization state.
- `provenance.md`: runtime scripts receive the same resolved artifact
  provenance as database scripts.

## Implementation Decisions Still Required

The design intentionally precedes implementation. The following must be
specified and tested before code changes:

1. Final manifest schema for exports and application-level aliases.
2. Manifest-version negotiation and legacy `runtime.name` migration.
3. Exact payload path encoding, including build metadata and non-semver local
   versions.
4. Receipt schema, activation generations, and crash-recovery protocol.
5. Cross-platform link strategy, including systems without symlink support.
6. Collision handling for aliases and pre-existing unmanaged files.
7. Upgrade script semantics when old and new payload directories are isolated.
8. Retention, garbage-collection, uninstall, and rollback policy.
9. Interaction between runtime activation and database deployment failure.
10. Dry-run and plan output for payload, export, link, and removal changes.

## Proposed Delivery Sequence

1. Finalize manifest and receipt schemas with examples and validation rules.
2. Add read-only planning for application runtime graphs and export conflicts.
3. Implement isolated staging and package-local script execution.
4. Implement command export validation and atomic activation.
5. Add graph-aware validation and deterministic resume.
6. Add upgrade retention and garbage collection.
7. Add explicit legacy-prefix migration tooling.
8. Design uninstall and rollback only after activation recovery is proven.
