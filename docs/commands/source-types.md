# Package Source Types

All commands that accept a `source` argument support the following source forms.

## Workspace root

```
/path/to/repo --package package_name
```

A directory containing `dbpm-workspace.yaml` may be used as a source when paired with `--package`. The workspace manifest selects a package root, and dbpm then treats that package root like an ordinary local directory source.

Example workspace manifest:
```yaml
workspace:
  packages:
    - database/utl_interval
    - database/simple_scheduler
```

Example command:
```sh
dbpm plan /path/to/repo --package simple_scheduler
```

When a selected workspace package has dependencies, sibling workspace packages may satisfy them automatically. Explicit `--dependency-source` values take precedence.

## Local directory

```
/path/to/package
C:\path\to\package
```

A directory containing a `dbpm.yaml`, `dbpm.yml`, `dbpm.json`, or `package.dbpm.yaml` manifest at its root. dbpm computes a deterministic `TREE-SHA-256` checksum over the source tree, excluding VCS, cache, build output, virtual environment, and log directories.

Local directory sources may also include a package-root `.dbpmignore`. Ignore patterns apply to local directory checksums and to `dbpm publish` ZIP contents. File patterns such as `pom.xml`, directory patterns such as `assembly/`, and root-relative path patterns such as `docs/maven/**` are supported. Negation patterns are not supported yet.

## Local ZIP

```
/path/to/package-1.0.0.zip
C:\path\to\package-1.0.0.zip
```

A ZIP archive containing a manifest at its root or inside a single top-level directory. dbpm computes a `SHA-256` checksum of the ZIP file.

## GitHub Maven coordinate

```
gh-maven:owner/repo:group:artifact:version
gh-maven:owner/repo:group:artifact:version:extension
```

Resolves to `https://maven.pkg.github.com/<owner>/<repo>/` using the standard Maven repository layout. The default extension is `zip`.

Authentication uses `DBPM_GITHUB_TOKEN` (or `GITHUB_TOKEN`). The username comes from `DBPM_GITHUB_USER`, `GITHUB_ACTOR`, or `x-access-token`.

Examples:
```
gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0
```

SNAPSHOT versions are supported. dbpm reads `maven-metadata.xml` to resolve the timestamped filename before downloading.

## Generic Maven coordinate

```
maven:repository-url::group:artifact:version
maven:repository-url::group:artifact:version:extension
```

Resolves the coordinate against any Maven-compatible repository base URL. The `::` separator distinguishes the URL from the coordinate.

Example:
```
maven:https://repo.example.com/releases::com.example:my_package:2.0.0
```

## dbpm registry source

```
registry:package@constraint
```

Resolves a package and semantic version constraint through the dbpm registry, then downloads the immutable ZIP artifact URL returned by the registry. The registry base URL is selected from `--registry-url`, then `DBPM_REGISTRY_URL`, then `https://dbpm.io`.

Registry sources verify the returned SHA-256 checksum immediately. When the registry returns an `artifact_signature_url`, dbpm downloads the detached signature and verifies it with local GPG. Locked installs record the resolved artifact URL, checksum, signature URL, and publisher key fingerprint, then bypass the registry and download directly from the locked artifact URL.

Examples:
```
registry:utl_interval@^1.0.0
registry:simple_scheduler@1.1.0
```

## Direct HTTPS URL

```
https://example.com/path/to/package-1.0.0.zip
```

The URL must reference a `.zip` file directly. Supported in lockfile-driven installs; also accepted as a direct source. dbpm downloads and caches the artifact on first use.

## Version constraint syntax

Used in `dependencies` declarations in manifests and in `scripts.upgrade_from`:

| Form | Example | Meaning |
|------|---------|---------|
| Exact | `1.2.3` | Must match exactly |
| Tilde | `~1.2.3` | Patch-compatible: ≥1.2.3 and <1.3.0 |
| Caret | `^1.2.3` | Minor-compatible: ≥1.2.3 and <2.0.0 |

Constraints follow [Semantic Versioning 2.0.0](https://semver.org/).
