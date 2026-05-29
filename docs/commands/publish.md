# dbpm publish

Build a ZIP artifact from a local package directory and publish it to a Maven-compatible repository (GitHub Packages or generic Maven). Signs the artifact with GPG and runs a post-publish verification step to confirm the artifact is accessible.

## Syntax

```
dbpm publish source --target TARGET
             [--group GROUP] [--artifact-id ID]
             [--signing-key KEY]
             [--dry-run]
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `source` | required | Local package directory or ZIP to publish. |
| `--target` | required | Repository to publish to. See [target formats](#target-formats). |
| `--group` | `publish.group` in manifest | Maven group ID. Overrides the `publish:` section of `dbpm.yaml`. |
| `--artifact-id` | `publish.artifact_id` or package name | Maven artifact ID. Overrides the `publish:` section of `dbpm.yaml`. |
| `--signing-key` | `DBPM_SIGNING_KEY` | GPG key ID, fingerprint, or email used to sign the artifact. Required. |
| `--dry-run` | false | Print what would be published without uploading. |

## Target formats

| Format | Example |
|---|---|
| GitHub Packages | `gh-maven:owner/repo` |
| Generic Maven | `maven:https://repo.example.com/maven2` |

## Manifest configuration

Add a `publish:` section to `dbpm.yaml` to avoid repeating coordinates on every publish:

```yaml
publish:
  group: com.512itconsulting.database
  artifact_id: utl_interval   # optional; defaults to package.name
```

`group` is required if the `publish:` section is present and `--group` is not provided on the command line.

## Environment variables

| Variable | Description |
|---|---|
| `DBPM_SIGNING_KEY` | Default GPG key ID for `--signing-key`. |
| `DBPM_GITHUB_TOKEN` / `GITHUB_TOKEN` | Token for GitHub Packages targets. |
| `DBPM_MAVEN_TOKEN` | Token for generic Maven repository targets. |
| `DBPM_MAVEN_USER` | Username for generic Maven repository targets. |

## What gets uploaded

For each publish operation, dbpm uploads:

| File | Description |
|---|---|
| `{artifact_id}-{version}.zip` | The built artifact ZIP. |
| `{artifact_id}-{version}.zip.sha256` | SHA-256 checksum. |
| `{artifact_id}-{version}.zip.sha1` | SHA-1 checksum. |
| `{artifact_id}-{version}.zip.asc` | GPG detached ASCII-armor signature. |
| `{artifact_id}-{version}.pom` | Maven POM with dependency metadata. |
| `{artifact_id}-{version}.pom.sha256` | POM SHA-256 checksum. |
| `{artifact_id}-{version}.pom.sha1` | POM SHA-1 checksum. |
| `maven-metadata.xml` | Updated artifact-level metadata (version list). |
| `maven-metadata.xml.sha256` | Metadata SHA-256 checksum. |
| `maven-metadata.xml.sha1` | Metadata SHA-1 checksum. |

## Post-publish verification

After uploading, dbpm automatically verifies that:

1. The new version appears in `maven-metadata.xml`.
2. The artifact can be downloaded and its SHA-256 matches what was uploaded.

## Output

On success, dbpm prints:

```
PUBLISHED=https://maven.pkg.github.com/owner/repo/com/example/utl_interval/1.0.0/utl_interval-1.0.0.zip
```

## Examples

```bash
# Dry run — show what would be published
dbpm publish ~/repos/utl_interval \
  --target gh-maven:512itconsulting/utl_interval \
  --signing-key signing@example.com \
  --dry-run

# Publish to GitHub Packages
dbpm publish ~/repos/utl_interval \
  --target gh-maven:512itconsulting/utl_interval \
  --signing-key $DBPM_SIGNING_KEY

# Publish to a generic Maven repository
dbpm publish ~/repos/utl_interval \
  --target maven:https://repo.example.com/maven2 \
  --group com.example.database \
  --signing-key $DBPM_SIGNING_KEY
```
