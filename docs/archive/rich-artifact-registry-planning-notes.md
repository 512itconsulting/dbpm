# Rich Artifact Registry Planning Notes

These notes preserve earlier registry design ideas that are not part of the
current dbpm CLI behavior. The current implemented behavior is documented in
[Rich Artifact Registry](../rich-artifact-registry.md).

## Multi-Registry Trust Configuration

Earlier plans allowed registry trust configuration from the root package
manifest and environment-level overrides:

```yaml
registries:
  - name: public
    url: https://registry.example.com
    token_env: DBPM_REGISTRY_TOKEN_PUBLIC
  - name: internal
    url: https://registry.internal.example.com
    token_env: DBPM_REGISTRY_TOKEN_INTERNAL
```

```sh
export DBPM_REGISTRY_URLS="public=https://registry.example.com,internal=https://registry.internal.example.com"
export DBPM_REGISTRY_TOKEN_PUBLIC="token-for-public"
export DBPM_REGISTRY_TOKEN_INTERNAL="token-for-internal"
```

The planned rules were:

- Env registries with the same name override root manifest registry entries.
- `DBPM_REGISTRY_TOKEN_<NAME>` is used for bearer auth when present.
- `DBPM_REGISTRY_TOKEN` is a fallback token for registry entries without a
  specific token.
- Registry URLs must use `https://`, except `http://localhost` and
  `http://127.0.0.1` for local development.

Current dbpm does not implement this multi-registry configuration. It uses one
registry URL selected from `--registry-url`, `DBPM_REGISTRY_URL`, or the default
`https://registry.dbpm.io`.

## Authenticated Resolve Requests

Earlier plans included bearer authentication for private registry resolution:

```text
Authorization: Bearer <token>
```

Current dbpm registry resolution does not attach bearer tokens to `GET
/resolve` requests. Registry indexing remains authenticated through
`DBPM_REGISTRY_TOKEN` or the environment variable named by `--token-env`.

## Compatibility-Aware Resolution

The registry resolve endpoint may eventually accept optional compatibility
filters:

```text
GET /resolve?package=<name>&constraint=<constraint>&core_version=<version>&oracle_version=<release>
```

Future dbpm versions could pass known Core and Oracle compatibility values when
resolving registry sources. This would let the registry select only versions
compatible with the installed Core version and target Oracle release.

## Search And Info

Earlier plans included consumer discovery commands:

```sh
dbpm search interval
dbpm search interval --json
dbpm info utl_interval
dbpm info utl_interval --json
```

Those commands would call:

```text
GET /search?q=<query>
GET /packages/<name>
```

`dbpm info` could also call `GET /packages/<name>/versions/<version>` when the
user asks for a specific version.

## Historical Implementation Checklist

The original implementation checklist included:

- Add a registry client module using the standard library HTTP stack, matching
  the existing source and publisher style.
- Add manifest parsing for top-level root `registries`.
- Add environment parsing for `DBPM_REGISTRY_URLS`,
  `DBPM_REGISTRY_TOKEN_<NAME>`, and `DBPM_REGISTRY_TOKEN`.
- Add registry URL validation with HTTPS required except localhost.
- Add `registry:` source parsing and resolution.
- Extend dependency resolution so missing dependencies can be resolved into
  normal package sources.
- Preserve all existing source type behavior.

The implemented subset covers single-registry URL selection, `registry:` source
parsing, artifact checksum verification, same-registry dependency resolution,
lockfile bypass behavior, and registry indexing.
