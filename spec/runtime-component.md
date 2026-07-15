# Runtime Component Specification

## Status

Draft. Not implemented. This document defines the design direction for
non-database package payloads before any manifest or CLI changes land.

## Purpose

Some dbpm packages ship more than database objects. A package such as
`job_control` deploys a database application through the normal dbpm flow, but
it also has an OS-side runtime: a Python scheduler program, helper scripts, a
runtime home directory, and configuration templates.

Today dbpm installs only the database component and leaves the rest to
hand-managed documentation. This spec defines how a package declares a
**runtime component**, how dbpm installs and upgrades it, and how installed
state is tracked on the host.

The goals are the same ones dbpm already applies to database deployments:

- explicit, manifest-declared entry points instead of tribal knowledge
- immutable versioned artifacts with checksum verification
- version coupling between the runtime and the database contract it depends on
- repeatable installs driven by the same plan/lock/install workflow

## Non-Goals

dbpm is not a configuration manager or an OS package manager. The runtime
component model deliberately excludes:

- **Privileged host setup.** Creating OS users, writing systemd units,
  creating root-owned directories, and opening firewall rules remain
  documented operator prerequisites. dbpm must never require root.
- **Secrets and rendered configuration.** dbpm may place configuration
  *templates*; it must never render or store credentials. Connection files
  such as `etc/dbconnect` remain operator-managed, consistent with the
  connection-agnostic script rule in `package-layout.md`.
- **Language-ecosystem package management.** dbpm does not resolve PyPI or
  npm dependency graphs. A runtime that embeds a Python program should ship
  it as a built wheel inside the package artifact; installing that wheel into
  a virtual environment is the job of the runtime install script (or a future
  typed component kind), not of dbpm's resolver.
- **Service lifecycle management.** Starting, stopping, and supervising
  daemons belongs to systemd or the operator. dbpm may run a validate script
  that performs a read-only health check; it does not manage processes.

## Terminology

- **Runtime component**: the non-database payload of a dbpm package, declared
  in the manifest under `runtime`.
- **Runtime prefix**: the host directory a runtime component installs into,
  such as `/opt/job_control`. Analogous to an installation prefix, and often
  exposed to programs as a home environment variable such as
  `JOB_CONTROL_HOME`.
- **Receipt**: the installed-state record dbpm writes inside the runtime
  prefix. The host-side analog of Core's application registry.
- **Contribution**: files one package installs into a runtime prefix owned by
  a different package, such as an application's EXE task scripts landing in
  `job_control`'s `bin/` directory.

## Manifest Extension

A package that owns a runtime declares it alongside (or instead of) its
database component:

```yaml
package:
  name: job_control
  version: "1.1.0"

database:
  platform: oracle

core:
  minimum_version: "3.0.0"

scripts:
  install: deployment_manifests/deploy.jc.full.sql
  upgrade: deployment_manifests/deploy.jc.full.sql

runtime:
  name: job_control
  scripts:
    install: os/dbpm/install.sh
    upgrade: os/dbpm/upgrade.sh
    validate: os/dbpm/health.sh
    uninstall: os/dbpm/uninstall.sh
```

A package that contributes files into another package's runtime declares a
contribution instead:

```yaml
package:
  name: warehouse_loads
  version: "2.4.0"

dependencies:
  - name: job_control
    version: "^1.1.0"

runtime:
  into: job_control
  scripts:
    install: os/dbpm/install.sh
    uninstall: os/dbpm/uninstall.sh
```

### Fields

- `runtime.name`: declares this package as the owner of a runtime prefix.
  Defaults the home environment variable to the upper-cased name plus
  `_HOME`, for example `JOB_CONTROL_HOME`.
- `runtime.home_env`: optional override for the home environment variable
  name.
- `runtime.into`: declares a contribution into the named runtime. Mutually
  exclusive with `runtime.name`. The named runtime's owning package must
  also appear in `dependencies` with a version constraint; that constraint is
  how the contribution states which runtime contract it supports.
- `runtime.scripts`: executable entry points relative to the package root.
  `install` is required; the rest are optional. Scripts follow the same
  philosophy as SQL entry points: dbpm does not infer behavior from directory
  names, it executes what the manifest declares.

Database-only packages omit `runtime` entirely and behave exactly as before.
Runtime-only packages (no database objects) may omit `database` and
`scripts`; dbpm should skip Core registration for them, though Core remains a
substrate prerequisite when the package declares `core.minimum_version`.

### Future: Typed Component Kinds

The MVP supports only script entry points (`kind: scripts`, the implicit
default). Later versions may add declarative kinds so common shapes need no
hand-written install script, for example:

```yaml
runtime:
  name: job_control
  kind: python-venv
  wheel: os/dist/job_control_runner-*.whl
  entrypoint: job-control-runner
```

Typed kinds are sugar over the same contract: they must produce the same
receipt entries and honor the same prefix and mode rules as script-based
components.

## Execution Contract

dbpm owns resolution, artifact verification, dependency planning, Core
checks, deployment-lock policy evaluation, and provenance — exactly as it
does for database deployments. Only after those steps does it invoke the
runtime script, symmetric to how it invokes the SQL runner.

Runtime scripts are executed:

- with the extracted package artifact root as the working directory
- as the invoking OS user, never with elevated privileges
- with dbpm-injected environment variables:

| Variable | Meaning |
|---|---|
| `DBPM_RUNTIME_PREFIX` | absolute path of the target runtime prefix |
| `DBPM_RUNTIME_MODE` | `install`, `upgrade`, `reinstall`, `resume`, `validate`, or `uninstall` |
| `DBPM_PACKAGE_NAME` | manifest package name |
| `DBPM_PACKAGE_VERSION` | package version being deployed |
| `DBPM_INSTALLED_VERSION` | previously installed version from the receipt, empty on first install |
| `DBPM_COMMIT_HASH` | resolved 40-character commit hash from artifact provenance |
| `DBPM_ARTIFACT_URL` | resolved artifact URL or coordinate |
| `DBPM_ARTIFACT_SHA256` | verified artifact checksum |

Environment variables are used instead of positional arguments because
runtime scripts are ordinary executables, not SQL*Plus scripts; the
positional-argument convention in `manifest.md` remains specific to SQL entry
points.

Scripts must be idempotent. `resume` re-runs the runtime script from the
beginning, matching the database upgrade contract in `deployment-modes.md`.

A non-zero exit status fails the deployment step. dbpm should capture stdout
and stderr into the execution log directory alongside SQL runner output.

## Runtime Prefix Resolution

dbpm resolves the target prefix in this order:

1. an explicit `--runtime-prefix` command-line flag
2. the runtime's home environment variable (`JOB_CONTROL_HOME` by default
   for a runtime named `job_control`)

If neither is set, deployment of the runtime component fails with a clear
message. dbpm must not guess a default such as `/opt/<name>` because prefix
choice is an operator decision.

The prefix must exist and be writable by the invoking user before dbpm runs.
Creating it — including any privileged `useradd`/`mkdir`/`chown` steps — is a
documented prerequisite, as in job_control's OS deployment guide. dbpm may
create subdirectories inside the prefix but must not attempt to create or
chown the prefix itself.

For a contribution (`runtime.into`), dbpm resolves the prefix the same way
using the *owning* runtime's home variable, then requires that the receipt
shows the owning package installed at a version satisfying the contributor's
declared dependency constraint. A contribution into a prefix with no receipt,
or with an incompatible owner version, must fail loudly rather than install
into an unmanaged directory.

## Installed-State Receipt

Core is the source of truth for what is deployed in a schema. It cannot play
that role for host state: runtime installs are per-host and per-prefix, and a
single database may be served by several runtime homes (or none). The
host-side source of truth is a receipt file inside the prefix:

```text
<prefix>/.dbpm/receipt.json
```

Schema version `dbpm.receipt.v0`. The receipt records one entry per package
that has installed into the prefix — the owner and any contributors:

```json
{
  "schema": "dbpm.receipt.v0",
  "runtime": "job_control",
  "packages": {
    "job_control": {
      "role": "owner",
      "version": "1.1.0",
      "commit": "<40-char hash>",
      "artifact_url": "https://...",
      "artifact_sha256": "<hex>",
      "installed_at": "2026-07-13T18:04:00Z",
      "mode": "install"
    },
    "warehouse_loads": {
      "role": "contributor",
      "version": "2.4.0",
      "commit": "<40-char hash>",
      "artifact_url": "https://...",
      "artifact_sha256": "<hex>",
      "installed_at": "2026-07-13T18:09:00Z",
      "mode": "install"
    }
  }
}
```

Receipt entries mirror the lockfile artifact-identity fields in
`lockfile.md` so a locked deployment can be verified against host state the
same way `--check-db` verifies Core state today.

Rules:

- dbpm writes the receipt only after the runtime script exits successfully.
- A failed runtime step should mark the entry with a failed status rather
  than leaving the prior entry intact, so `resume` has accurate state.
- dbpm must take a simple exclusive lock (for example
  `<prefix>/.dbpm/lock`) while mutating the receipt to guard against
  concurrent deployments into the same prefix.
- Uninstalling a contributor removes only that contributor's entry;
  uninstalling the owner while contributor entries remain must fail unless
  the operator forces it.
- The receipt is dbpm-owned metadata. Runtime programs may read it but must
  not write it.

### Optional Database Reporting

Packages may additionally report their deployed runtime version into
database tables for observability, as job_control's scheduler already
registers itself in `jc_scheduler`. That reporting is a package concern, not
a dbpm requirement, and it never substitutes for the receipt. A future Core
version may add a host-deployment provenance API; if it does, dbpm may
mirror receipt entries into it, with the receipt remaining authoritative for
the host.

## Deployment Modes And Ordering

Runtime components participate in the modes defined in
`deployment-modes.md`:

- **install / upgrade**: within a single package, the database component
  deploys first, then the runtime component. The runtime typically depends
  on the schema contract, never the reverse. If the database step succeeds
  and the runtime step fails, the package deployment as a whole is failed;
  `resume` re-runs from the failed component using receipt and Core state.
- **reinstall**: destructive intent extends to the runtime. The runtime
  script receives `DBPM_RUNTIME_MODE=reinstall` and may clear
  package-managed files under the prefix. dbpm must never delete operator
  data directories (`var/`, `etc/`) itself; only the package's script knows
  what is safe to remove. Deployment-lock policy applies before the database
  step as usual.
- **resume**: re-runs the runtime script; idempotency is required.
- **validate**: runs the runtime `validate` script (a read-only health
  check) after the database validate script, when both exist.
- **uninstall**: runs the runtime `uninstall` script and removes the receipt
  entry. Contributor ordering: contributors should be uninstalled before the
  owner.

Across packages, the existing dependency-ordered multi-package plan applies
unchanged; a contribution's dependency on the runtime owner guarantees the
owner deploys first.

Stopping and restarting services around an upgrade is the operator's job.
dbpm should state in the plan output that a runtime component will be
modified so the operator can quiesce the service first; a future version may
add optional pre/post hooks, but process management stays out of scope.

## Version Coupling

The runtime component is part of the package: same artifact, same version,
same commit provenance. There is no separate runtime version in the
manifest. When a runtime embeds a separately versioned program — such as a
wheel with its own `pyproject.toml` version — that inner version is an
implementation detail; the package version is authoritative for dbpm
resolution, locking, and receipts.

This is the point of the model: the compatibility contract between a
runtime and its database package (`x$get_next` signatures, run-status
semantics) is expressed by shipping them in one versioned artifact, and the
contract between a contributor and the runtime it targets is expressed as an
ordinary dependency constraint. Both reuse dbpm's existing semver machinery.

## Artifact And Lockfile Interaction

The runtime payload lives inside the normal package ZIP artifact, so the
existing SHA-256 checksum, GPG signature verification, content-addressed
cache, and lockfile identity in `lockfile.md` cover it with no new artifact
types. Built runtime programs (wheels) should be placed into the artifact at
build time, for example under `os/dist/`, so consumer installs need no
language-ecosystem registry access and remain reproducible offline from the
locked artifact.

`.dbpmignore` continues to exclude producer-side files from the artifact;
runtime source trees that build into a bundled wheel are natural candidates
for exclusion when only the built wheel should ship.

A future version may allow a runtime component to reference an external
locked artifact (for example a wheel fetched from a registry) instead of a
bundled file. If added, that reference must carry the same immutable
identity guarantees: exact URL, checksum, and failure — never substitution —
when the locked artifact is unavailable.

## Alternatives Considered

### Git Submodules

Splitting the database package and the runtime into separate repositories
joined by git submodules was considered and rejected.

Submodules answer a source-organization question, not a deployment
question: dbpm consumes artifacts, not checkouts, so a submodule split would
still require either this component model or a two-package model on top of
it. Where the two overlap, submodules conflict with stated dbpm principles:

- A submodule pins a commit in source, which is exactly the
  mutable-checkout coupling that `manifest.md` excludes from packages and
  that lockfiles exist to replace. The coupling point becomes a commit
  pointer on a mutable branch instead of a released, checksummed,
  semver-addressed artifact.
- The strongest property of the single-artifact model is lost: one version
  naming one tested database-plus-runtime contract. A split reintroduces a
  runner-to-schema compatibility matrix.
- Operationally, submodules add contributor friction (recursive clones,
  detached-HEAD state, accidental pointer bumps) and break GitHub source
  tarballs, which complicates release automation.

Provenance alone would survive a submodule split, because a parent commit
deterministically pins its submodule commits. That is not sufficient reason
to adopt them.

### Split Repositories With Artifact Coupling

If repository separation is needed — separate ownership, independent CI, a
heavy language-ecosystem test matrix — the supported path is to couple
through published artifacts rather than source:

1. The runtime repository publishes a versioned, checksummed wheel (or
   equivalent built program) to an artifact repository.
2. The database package's build fetches that exact wheel by version and
   checksum and bundles it into the package artifact under `os/dist/`.

Consumers still see one immutable artifact and one package version; only the
producer-side build crosses repositories, and it crosses at a released
artifact identity. This requires no change to this spec.

### Separate Runtime Package

Promoting the runtime to its own runtime-only dbpm package, with the
database contract expressed as an ordinary dependency constraint, remains
open for the case where one runtime genuinely serves multiple database
packages or needs an independent release cadence. The receipt and execution
contract defined here apply unchanged to that shape, so it can be adopted
later without rework. Until that need is real, the single-package component
model is preferred for its one-version-one-contract property.

### Monorepo Workspace (Status Quo)

Keeping database and runtime trees side by side in one repository under a
workspace manifest — the current `job_control` layout — remains the default
recommendation. Separation of ownership is handled with directory ownership
and CI path filters, and it is the cheapest layout to operate until it
visibly hurts.

## Relationship To Existing Specs

- `manifest.md`: `runtime` is a new top-level manifest mapping; all existing
  fields are unchanged.
- `package-layout.md`: the workspace example already places an `os/` tree
  next to `database/` package roots; this spec gives that tree a declared
  deployment path. Runtime entry points follow the same
  manifest-declared-not-inferred rule as SQL scripts.
- `deployment-modes.md`: modes gain a runtime step; operator intent
  semantics are unchanged.
- `lockfile.md`: no schema change required for the MVP because runtime
  payloads ship inside existing package artifacts.
- `provenance.md`: runtime scripts receive the same resolved provenance the
  SQL entry points receive, via environment variables instead of positional
  arguments.

## MVP Scope

1. Parse and validate the `runtime` manifest mapping (`name` form only).
2. Prefix resolution via home environment variable and `--runtime-prefix`.
3. Script execution with the injected environment contract and log capture.
4. Receipt read/write with locking, and receipt-aware `install`, `upgrade`,
   `resume`, `validate`, and `reinstall`.
5. Plan output that shows the runtime step explicitly.

Deferred beyond MVP:

- `runtime.into` contributions
- `uninstall` orchestration
- typed component kinds such as `python-venv`
- external locked runtime artifacts
- Core-side host-deployment reporting
