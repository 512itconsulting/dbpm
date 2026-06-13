# Registry

dbpm can resolve packages through a dbpm registry so consumers can install by
package name and version constraint instead of Maven repository coordinates.

The registry is a metadata and resolution service. It maps dbpm package names
and version constraints to immutable ZIP artifact URLs, SHA-256 checksums, and
optional signature metadata. dbpm still downloads the artifact, verifies it,
loads its manifest, builds the deployment plan, writes lockfiles, and executes
deployment scripts.

Older multi-registry and discovery-command planning notes are archived in
[Rich Artifact Registry Planning Notes](archive/rich-artifact-registry-planning-notes.md).

## Goals

- Let consumers install packages by dbpm package name instead of Maven
  repository coordinates.
- Resolve missing manifest dependencies automatically when the root package was
  resolved from a registry.
- Preserve deterministic deployments through lockfiles that pin resolved
  artifact URLs and checksums.
- Keep Core as an implicit substrate prerequisite, not a normal registry
  dependency.
- Keep existing `gh-maven:`, `maven:`, local directory, local ZIP, direct URL,
  and lockfile workflows working unchanged.

## Source Syntax

Use a `registry:` source:

```text
registry:<package>@<constraint>
```

Examples:

```text
registry:utl_interval@1.0.0
registry:utl_interval@^1.0.0
registry:simple_scheduler@1.1.0
```

The constraint syntax matches manifest dependency constraints:

- exact: `1.2.3`
- tilde: `~1.2.3`
- caret: `^1.2.3`

After registry resolution, dbpm treats the returned ZIP artifact like any other
remote package source.

## Registry Configuration

dbpm currently uses one registry base URL per command invocation. The URL is
selected in this order:

1. `--registry-url`
2. `DBPM_REGISTRY_URL`
3. `https://registry.dbpm.io`

Example:

```sh
dbpm install registry:simple_scheduler@^1.1.0 \
  --registry-url https://registry.dbpm.io
```

The current resolver does not read top-level `registries:` manifest settings
and does not use `DBPM_REGISTRY_URLS` or per-registry resolve tokens.

## Resolve API

For registry sources, dbpm calls:

```text
GET /resolve?package=<name>&constraint=<constraint>
```

The response must include:

```json
{
  "package": "utl_interval",
  "version": "1.2.3",
  "artifact_url": "https://...",
  "artifact_checksum": "sha256:abc123...",
  "artifact_signature_url": "https://...asc",
  "publisher_key_fingerprint": "..."
}
```

Required fields:

- `package`
- `version`
- `artifact_url`
- `artifact_checksum`

Optional fields:

- `artifact_signature_url`
- `publisher_key_fingerprint`
- `core_minimum_version`
- `oracle_minimum_version`
- `warning`
- `warnings`

The checksum must be SHA-256. dbpm accepts either plain hex or a
`sha256:`-prefixed value and normalizes it before artifact verification.

If `artifact_signature_url` is present, dbpm downloads the detached signature
and verifies it through the same signature path used by lockfile-driven remote
artifacts.

## Resolution Behavior

`dbpm plan`, `dbpm lock`, and non-lockfile execution commands can use registry
resolution when given a `registry:` source.

Resolution order:

1. Load the root package source.
2. Load explicit `--dependency-source` values.
3. Read installed package state when the command has a database connection.
4. For each dependency:
   - explicit `--dependency-source` wins when it satisfies the constraint;
   - already-installed complete dependencies remain satisfied;
   - if the current source came from a registry, missing dependencies are
     resolved from the same registry URL.
5. dbpm downloads each registry-returned artifact URL and verifies SHA-256.
6. dbpm adds the resolved artifact as a normal package source and continues
   dependency ordering.

If no explicit, installed, sibling-workspace, or same-registry source can
satisfy a dependency, dbpm fails before running SQL scripts.

Core is never auto-resolved as an ordinary registry dependency. Core remains the
in-database substrate that must be bootstrapped and checked separately.

## Command Coverage

Implemented registry source coverage includes:

- `dbpm plan`
- `dbpm lock`
- `dbpm install`
- `dbpm upgrade`
- `dbpm reinstall`
- `dbpm resume`
- `dbpm validate`
- `dbpm bootstrap-core`

Locked installs bypass the registry entirely:

```sh
dbpm install --lockfile dbpm-lock.json
```

Lockfile installation uses the exact artifact URL, checksum, signature URL, and
publisher key fingerprint recorded in the lockfile.

## Registry Indexing

dbpm can index already-published immutable artifacts in a registry. The registry
stores metadata only; dbpm does not upload ZIP bytes to the registry.

`dbpm publish` writes a durable, secret-free `dbpm-publish-receipt.json` after
upload and post-publish verification. Producers can index that receipt later or
request indexing immediately:

```sh
dbpm registry index <package-root> \
  --registry-url https://registry.dbpm.io \
  --token-env DBPM_REGISTRY_TOKEN

dbpm publish <package-root> \
  --target gh-maven:owner/repo \
  --index-registry
```

Registry indexing submits metadata dbpm already knows after publish:

- publisher name
- package name and version
- artifact URL
- SHA-256 checksum
- detached signature URL
- publisher key fingerprint
- Core and Oracle compatibility fields
- manifest dependencies beyond Core

`artifact_signature_url` and `publisher_key_fingerprint` must be supplied
together. `dbpm publish` derives the full primary fingerprint from its
configured GPG signing key and records it in the publish receipt. `dbpm registry
index` accepts `--publisher-key-fingerprint` for existing artifacts.

## Verification And Lockfiles

Registry-resolved artifacts must include SHA-256 checksums. dbpm verifies the
downloaded ZIP before planning execution.

Lockfiles record registry results as exact artifact identity:

- resolved artifact URL
- SHA-256 checksum
- checksum algorithm
- optional signature URL
- optional publisher key fingerprint
- resolved package version
- dependency metadata

Subsequent lockfile installs do not contact the registry.
