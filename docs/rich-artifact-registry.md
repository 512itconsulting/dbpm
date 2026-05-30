# Rich Artifact Registry

This plan describes dbpm's consumer-side integration with a rich artifact registry.

dbpm remains the CLI that resolves packages, creates plans, writes lockfiles, verifies artifacts, and executes deployments. The registry is a trusted resolution and discovery service. It maps dbpm package names and version constraints to immutable artifact URLs, checksums, and optional signature metadata.

The companion service/API plan lives in the dbpm-registry repository. dbpm-registry owns registry storage, indexing, yanking/deprecation policy, search, package metadata APIs, and registry publishing workflows.

## Goals

- Let consumers install packages by dbpm package name instead of Maven repository coordinates.
- Resolve missing manifest dependencies automatically from trusted registries.
- Preserve deterministic deployments through lockfiles that pin resolved artifact URLs and checksums.
- Keep Core as an implicit substrate prerequisite, not a normal registry dependency.
- Keep existing `gh-maven:`, `maven:`, local directory, local ZIP, direct URL, and lockfile workflows working unchanged.

## Source Syntax

dbpm adds a registry source form:

```text
registry:<package>@<constraint>
```

Examples:

```text
registry:utl_interval@1.0.0
registry:utl_interval@^1.0.0
registry:simple_scheduler@1.1.0
```

The constraint syntax is the same syntax already used in manifests:

- exact: `1.2.3`
- tilde: `~1.2.3`
- caret: `^1.2.3`

Registry source resolution produces a normal package artifact source internally. After resolution, dbpm downloads the returned ZIP artifact and proceeds through the existing manifest parsing and planning flow.

## Registry Configuration

Registry trust configuration is read from two places:

1. The root package manifest passed on the command line.
2. Environment-level overrides for local and CI configuration.

Only the root invoked manifest can contribute registry configuration. Dependency manifests inside resolved artifacts must not add or override trusted registries. This keeps registry trust as project/operator policy rather than publisher-controlled package metadata.

Example root `dbpm.yaml` configuration:

```yaml
registries:
  - name: public
    url: https://registry.example.com
    token_env: DBPM_REGISTRY_TOKEN_PUBLIC
  - name: internal
    url: https://registry.internal.example.com
    token_env: DBPM_REGISTRY_TOKEN_INTERNAL
```

Environment overrides:

```sh
export DBPM_REGISTRY_URLS="public=https://registry.example.com,internal=https://registry.internal.example.com"
export DBPM_REGISTRY_TOKEN_PUBLIC="token-for-public"
export DBPM_REGISTRY_TOKEN_INTERNAL="token-for-internal"
```

Rules:

- Env registries with the same name override root manifest registry entries.
- `DBPM_REGISTRY_TOKEN_<NAME>` is used for bearer auth when present.
- `DBPM_REGISTRY_TOKEN` is a fallback token for registry entries without a specific token.
- Registry URLs must use `https://`, except `http://localhost` and `http://127.0.0.1` for local development.

## API Contract Used By dbpm

dbpm calls the registry's resolve endpoint during plan, lock, and non-lockfile install resolution:

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
  "artifact_signature_url": "https://...asc"
}
```

Required fields:

- `package`
- `version`
- `artifact_url`
- `artifact_checksum`

Optional fields:

- `artifact_signature_url`
- `core_minimum_version`
- `oracle_minimum_version`

The checksum must be SHA-256. dbpm accepts either plain hex or a `sha256:`-prefixed value and normalizes it before artifact verification.

For private registries, dbpm sends:

```text
Authorization: Bearer <token>
```

## Resolution Behavior

`dbpm plan`, `dbpm lock`, and non-lockfile `dbpm install` use registry resolution.

Resolution order:

1. Load the root package source.
2. Load explicit `--dependency-source` values.
3. Read installed Core state when the command has a database connection.
4. For each dependency:
   - explicit `--dependency-source` wins when it satisfies the constraint;
   - already-installed complete dependencies remain satisfied;
   - missing dependencies are resolved from configured registries.
5. The registry chooses the highest stable compatible version server-side.
6. dbpm downloads the artifact URL returned by the registry and verifies SHA-256.
7. dbpm adds the resolved artifact as a normal `PackageSource` and continues dependency ordering.

If no configured registry can resolve a missing dependency, dbpm fails before running any SQL scripts.

dbpm trusts the registry's yanked/deprecated policy in v1. Range resolution, exact-yanked behavior, and deprecation selection are registry-owned decisions.

## Command Coverage

V1 registry integration covers:

- `dbpm plan`
- `dbpm lock`
- non-lockfile `dbpm install`
- `dbpm search`
- `dbpm info`

Deferred:

- `dbpm upgrade` registry resolution
- `dbpm validate` registry resolution
- registry publishing or index mutation from dbpm

Locked installs bypass the registry entirely:

```sh
dbpm install --lockfile dbpm-lock.json
```

Lockfile installation uses the exact artifact URL, checksum, and signature URL recorded in the lockfile.

## Search And Info

Add consumer discovery commands:

```sh
dbpm search interval
dbpm search interval --json
dbpm info utl_interval
dbpm info utl_interval --json
```

These commands call:

```text
GET /search?q=<query>
GET /packages/<name>
```

The default output is human-readable text. `--json` prints raw registry JSON.

## Verification And Lockfiles

Registry-resolved artifacts must include SHA-256 checksums. dbpm verifies the downloaded ZIP before planning execution.

If `artifact_signature_url` is present, dbpm passes it through the existing signature verification path. Signature metadata remains optional in v1 so the registry can launch with checksum verification first.

Lockfiles record registry results as exact artifact identity:

- resolved artifact URL;
- SHA-256 checksum;
- checksum algorithm;
- optional signature URL;
- resolved package version;
- dependency metadata.

Subsequent lockfile installs do not contact the registry.

## Implementation Notes

- Add a registry client module using the standard library HTTP stack, matching the existing source and publisher style.
- Add manifest parsing for top-level root `registries`.
- Add environment parsing for `DBPM_REGISTRY_URLS`, `DBPM_REGISTRY_TOKEN_<NAME>`, and `DBPM_REGISTRY_TOKEN`.
- Add registry URL validation with HTTPS required except localhost.
- Add `registry:` source parsing and resolution.
- Extend dependency resolution so missing dependencies can be resolved into normal `PackageSource` values.
- Preserve all existing source type behavior.

## Tests

Cover:

- registry config parsing from root manifest;
- dependency manifests ignored for registry config;
- env override precedence;
- token header behavior;
- HTTPS and localhost validation;
- `registry:name@constraint` parsing;
- missing checksum errors;
- failed registry responses;
- explicit dependency source overriding registry resolution;
- already-installed dependency satisfaction;
- lockfile install bypassing registry;
- `search` and `info` text output plus `--json`.
