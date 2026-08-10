# Composable Application Runtime Specification

## Status

Partially implemented; execution design in progress.

The composable application runtime replaces the short-lived package-owned
runtime implementation. The selected root application owns one application
runtime. Runtime-bearing dependencies install into isolated package
directories beneath it and declare exports that dbpm activates at the
application level.

The manifest parser and planner compose isolated payload paths and resolved
command names. Install execution stages package payloads, runs package-local
scripts, validates exports, promotes payloads, activates command links, and
writes the application receipt. Validate reconciles that receipt with the
planned graph, payload identities, managed command links, and package-declared
health scripts. Resume can deterministically retry a matching failed or
interrupted staging generation. Upgrade retains prior versioned payloads while
activating the new graph; reinstall reconstructs same-version payloads while
retaining recoverable backups. The active and immediately prior generation
are retained; receipt-reachability garbage collection removes older,
unreferenced payloads and recovery data. Uninstall runs cleanup in reverse
dependency order while preserving operator-owned state. The removed
`runtime.name`,
`runtime.home_env`, `runtime.into`, and `runtime.layout` fields are rejected.

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

Each runtime-bearing package installs executable code and immutable assets only
within its assigned package directory. It must not write directly into another
package directory or create application-level command links.

A package may initialize its distinctly named durable files beneath the
application-level `etc` and `var` directories. It must not overwrite
operator-owned files, claim an entire shared directory, or remove durable
content during upgrade or uninstall.

dbpm, rather than package install order, owns application-level composition.

### Exports are declarative

A package declares the commands or other resources it makes available to a
consuming application. dbpm validates and activates those exports. Package
install scripts prepare package-local content but do not create
application-level links.

### Mutable state is separate from immutable payloads

Versioned package directories contain replaceable package payloads. Persistent
configuration, secrets, logs, queues, and other operator or application data
do not belong in those directories. Durable files live directly beneath the
application-level `etc` and `var` directories. A package-name directory is not
required; packages use distinctive filenames or narrower subdirectories only
where needed to avoid collisions.

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
  etc/
    job-control.toml
    job-control.toml.template
    emmt-el.env
    sql/
  var/
    log/
    spool/
  packages/
    warehouse_app/
      2.0.0/
        bin/
        lib/
    job_control/
      1.1.0/
        bin/
        lib/
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
  areas shared by the composed application. Package installers may atomically
  create distinctly named initial configuration and refresh distinctly named
  templates, but must never overwrite operator-owned configuration.

Flat durable directories are the default. Package-specific subdirectories are
an organizational or collision-avoidance choice, not a lifecycle boundary.
For example, `etc/job-control.toml`, `var/log/`, and `var/spool/` are valid
application-level paths. Packages contributing collections with potentially
generic names may use a narrower directory such as `etc/sql/emmt_el/`.
Uninstall scripts must remove only explicitly package-maintained files and
must not remove shared `etc` or `var` directories.

Package and version path segments must be derived from validated manifest
values and must not permit path traversal. dbpm prefers relative symlinks for
application-level commands so a runtime can be relocated as a unit. When the
platform or local policy denies symlink creation, dbpm falls back to hard
links for executable files and validates them with file identity checks.

The prefix must exist and be writable by the invoking user. Creating OS users,
root-owned directories, systemd units, or other privileged host resources
remains an operator prerequisite. dbpm must not require privilege elevation.
dbpm validates the prefix before executing any database script in a runtime-
bearing single- or multi-package plan, and repeats the check when runtime
staging begins to detect intervening filesystem changes.

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
  payload and whenever the package declares command exports. It may be omitted
  by an activation-only root application that has no package-local payload.
- `runtime.scripts.upgrade`: optional migration entry point. If absent,
  upgrade uses the idempotent `install` entry point against a newly staged
  package directory.
- `runtime.scripts.validate`: optional read-only validation entry point.
- `runtime.scripts.uninstall`: optional cleanup entry point scoped to the
  package payload. It must not remove shared application state.
- `runtime.exports.commands`: mapping from a requested application-level
  command name to a relative executable path within the installed package
  payload.

`runtime.name`, `runtime.home_env`, `runtime.into`, and `runtime.layout` do not
belong in the manifest contract. Package identity already comes from
`package.name`;
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
  activation:
    commands:
      aliases:
        job_control.job-control: warehouse-jobs
      disabled:
        - warehouse_loads.load-now
```

The canonical identity of an export is `<package-name>.<export-name>`, such as
`job_control.job-control`. Canonical identities are stable references within
plans, lockfiles, receipts, and application configuration.

Application-level command configuration is declared under
`runtime.activation.commands`:

- `aliases` maps canonical command identities to activated names
- `disabled` lists canonical identities that should not be activated

These settings take effect only when the declaring package is selected as the
root application. This allows any reusable package to remain independently
deployable as a root without letting a dependency configure its consumer's
application namespace.

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
- with the invoking dbpm process environment inherited
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

`DBPM_RUNTIME_PACKAGE_PREFIX` is the only target for executable code and
immutable package assets. The application prefix is also the root for durable
application/operator state. A package script may initialize its distinctly
named files beneath `etc` or `var` without replacing existing operator-owned
content. It must not mutate application-level command links, another package
payload, `.dbpm` metadata, or durable files owned by another contributor.

The inherited process environment includes operator-provided variables such
as `DBPM_DB_USER`, `DBPM_DB_PASSWORD`, and `DBPM_DB_DSN` when they are set for
the dbpm process. Runtime packages may use these values to create
an initial application configuration for an Oracle client library that cannot
consume a SQLcl saved connection. Environment inheritance applies to install,
upgrade, reinstall, resume, validate, and uninstall scripts.

dbpm does not add inherited environment values to the runtime graph, staging
status, application receipt, or its own log messages. A package script remains
responsible for protecting inherited secrets: it must not print them, place
them in a replaceable package payload, or write them with permissions that
allow unintended access. Environment inheritance is limited to the script
process; services or commands launched after deployment must obtain their
runtime environment or durable configuration independently.

Scripts must be idempotent within their assigned staged directory. A non-zero
exit fails the package runtime step. dbpm captures stdout and stderr in the
normal execution logs.

Secrets are never injected as artifact content or rendered by dbpm. Service
start, stop, supervision, OS account management, and privileged host
configuration remain outside dbpm.

## Activated Runtime Command Contract

`DBPM_RUNTIME_PREFIX` is required in the conditioned environment whenever an
activated runtime command executes. DBPM supplies it to lifecycle scripts.
Operators and service managers supply the same absolute application runtime
prefix to interactive commands, services, and scheduled processes. A runtime
process must propagate it unchanged to child runtime processes.

Scheduled runtime tasks execute with this working directory:

```text
$DBPM_RUNTIME_PREFIX/bin
```

The working-directory convention permits `./command` invocation, but runtime
packages should prefer the explicit application-level path:

```sh
"${DBPM_RUNTIME_PREFIX}/bin/command"
```

Runtime dependencies are consumed only through their activated application-
level exports. A package must not resolve a command symlink to its physical
target and navigate from its versioned package payload into a dependency
payload. The payload layout and selected dependency versions are dbpm
implementation details.

Package-specific home variables such as `JOB_CONTROL_HOME` are not part of the
composable runtime contract. Durable configuration is read beneath
`$DBPM_RUNTIME_PREFIX/etc`, logs and spool data are written beneath
`$DBPM_RUNTIME_PREFIX/var`, and executable dependencies are invoked beneath
`$DBPM_RUNTIME_PREFIX/bin`.

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
activation spans multiple filesystem operations, dbpm records a durable
activation journal before payload promotion and advances it after payload,
command-directory, and receipt boundaries. A later activation automatically
rolls back an incomplete journal under the runtime lock; a journal whose
receipt was published is finalized without undoing the active generation.

Service quiescence remains an operator responsibility. Plan output must show
all runtime payload and activated-command changes so the operator can decide
whether a running process needs to be stopped.

Install execution promotes a validated staged generation into
`<prefix>/packages`, replaces the dbpm-managed command directory, and writes
the active receipt. Failed staging remains beneath `<prefix>/.dbpm/staging/`
for diagnostics. Activation refuses to overwrite an unmanaged `bin`
directory.

## Runtime Receipt

The receipt is authoritative for host-side application runtime state:

```text
<prefix>/.dbpm/receipt.json
```

The application runtime uses receipt schema
`dbpm.application-runtime.v1`. Its shape is:

```json
{
  "schema": "dbpm.application-runtime.v1",
  "application": {
    "name": "warehouse_app",
    "version": "2.0.0"
  },
  "generation": 3,
  "resolution": {
    "lock_schema": "dbpm.lock.v0",
    "lock_checksum": "sha256:<hex>"
  },
  "packages": {
    "warehouse_app": {
      "version": "2.0.0",
      "path": "packages/warehouse_app/2.0.0",
      "commit": "<40-char hash>",
      "artifact": {
        "uri": "https://...",
        "checksum": "<hex>",
        "checksum_alg": "SHA-256"
      }
    },
    "job_control": {
      "version": "1.1.0",
      "path": "packages/job_control/1.1.0",
      "commit": "<40-char hash>",
      "artifact": {
        "uri": "https://...",
        "checksum": "<hex>",
        "checksum_alg": "SHA-256"
      }
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

- root artifact identity through the root entry in `packages`
- every runtime-bearing package's artifact provenance and installed path
- the canonical identity and activated name of each command export
- the activation generation
- enough prior-generation state for deterministic resume or rollback
- platform information needed to interpret links

`resolution.lock_schema` and `resolution.lock_checksum` must either both be
present or both be null for an unlocked local workflow. The checksum is the
SHA-256 identity of the exact lockfile bytes used for deployment.

Each command target is application-prefix-relative and must resolve beneath
the payload path recorded for its package. Each package artifact must provide
both `checksum` and `checksum_alg`, or neither for a development source whose
identity has not yet been captured.

The receipt is dbpm-owned. Runtime programs may read it but must not modify it.
The receipt describes host state and does not replace Core's database
deployment records. Optional database-side runtime reporting remains
observability, not authority.

## Deployment Modes

- **install**: stage the complete runtime graph and activate it only after all
  required payloads and exports validate.
- **upgrade**: implemented; resolves and stages the new graph, reuses unchanged
  payloads only when receipt identity matches, retains prior versions, and
  switches command activation and receipt generation.
- **reinstall**: implemented; reconstructs same-version package payloads with
  explicit destructive intent and retains the replaced payloads as recovery
  backups, without touching application-owned `etc` or `var` content.
- **resume**: implemented for incomplete staging; selects only a generation
  whose recorded graph exactly matches the requested graph, reuses a ready
  stage or reconstructs a failed/interrupted payload set in the same staging
  directory, and never treats partial content as active.
- **validate**: implemented; verifies receipt identity, package payload and
  artifact identity, the exact managed command-link set, executable targets,
  and package-declared read-only health checks without mutating activation.
- **uninstall**: implemented; validates the active graph, runs optional package
  cleanup scripts in reverse dependency order, removes dbpm-managed links,
  payloads, retained generations, and the active receipt, archives the final
  receipt, and preserves application/operator-owned `etc` and `var` content.
  Full runtime validation, including package health scripts, runs before any
  database uninstall scripts. After database removal, dbpm repeats structural
  receipt, payload, and command validation without rerunning health scripts,
  then performs runtime cleanup.

Removing or changing a dependency is an application upgrade driven by the new
resolved graph. A package payload becomes eligible for garbage collection only
when no active or retained generation references it. The current policy
retains one prior generation and runs collection after successful activation.

## Upgrade And Rollback

Versioned package paths allow a new graph to be prepared without overwriting
the active graph. This is the preferred upgrade mechanism even when policy
normally retains only one active version.

Rollback reactivates a retained, verified graph as a new generation rather
than running downgrade scripts or decrementing generation history. The
`dbpm rollback` command reads installed Core state for every retained package
and refuses activation unless database versions exactly match the target
runtime graph. The active generation is retained before the command links and
receipt switch.

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

A package-owned runtime makes a reusable dependency appear to own the
deployment boundary. This can work for a standalone program but does not
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

## Implementation Status

The composable application runtime lifecycle described here is implemented.
Runtime version path segments accept letters, digits, dots, underscores,
pluses, and hyphens and reject separators or traversal. Plans expose the
operation plus affected payload and command paths before execution.

Database components execute before runtime staging because host programs
normally depend on the deployed schema contract. If database execution fails,
runtime mutation does not begin. If runtime staging or activation fails after
database success, the database remains advanced and `resume` is the recovery
path; dbpm does not attempt an unsafe automatic database downgrade.
