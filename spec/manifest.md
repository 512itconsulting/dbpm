# Package Manifest Specification

## Purpose

The package manifest declares the identity, version, dependencies, and deployment entry points for a dbpm package.

Core is not declared as a normal package dependency for every application. It is the dbpm substrate and is checked separately through the package's Core requirement.

End-user applications should use the same manifest model as reusable packages. The manifest should describe the application package and its dependencies beyond Core; it should not embed dependent repository contents or mutable source checkout assumptions.

## Candidate File Names

Possible manifest names:

- `dbpm.yaml`
- `dbpm.json`
- `package.dbpm.yaml`

Initial recommendation: `dbpm.yaml`.

## Example

```yaml
package:
  name: job_control
  version: "1.0.0"
  description: Scheduling Package
  vendor: rsantmyer
  license: Apache-2.0

database:
  platform: oracle
  minimum_version: "19c"

core:
  minimum_version: "3.0.0"

dependencies:
  - name: utl_interval
    version: "^1.2.0"

scripts:
  install: Deployment_Manifests/deploy.sql
  upgrade: Deployment_Manifests/upgrade.sql
  validate: Deployment_Manifests/validate.sql
  uninstall: Deployment_Manifests/uninstall.sql
```

## Fields

- `package.name`: The Core application name, expressed in manifest-friendly lowercase or snake case. dbpm should normalize to Core's uppercase application name when calling `pkg_application`.
- `package.version`: The package artifact version. This should align with the deployment semantic version unless a later spec defines a deliberate distinction.
- `database.platform`: Initially `oracle`.
- `database.minimum_version`: Minimum supported Oracle version.
- `core.minimum_version`: Minimum Core version required before dbpm executes the package deployment.
- `dependencies`: Package dependencies beyond Core.
- `scripts`: SQL*Plus/SQLcl-compatible entry points. Scripts should accept dbpm-injected provenance parameters instead of hard-coding commit hashes.
- `runtime`: Optional non-database runtime component with its own executable entry points, deployed into an operator-provided prefix. See `runtime-component.md`.

Version values follow [Semantic Versioning 2.0.0](https://semver.org/) and should be quoted in YAML so they are always parsed as strings.

Dependency constraints in the manifest describe acceptable package versions. Exact released deployments should be recorded in a lockfile rather than by rewriting the manifest to include transient repository details.

## SQLcl Project Compatibility

Packages produced from SQLcl `project` workflows should still expose dbpm metadata. SQLcl project files, release folders, generated Liquibase changelogs, and `dist/install.sql` may be part of the package implementation, but they do not replace the dbpm manifest.

A SQLcl project-based package may point a manifest script entry at the SQLcl-generated installer, for example:

```yaml
scripts:
  install: dist/install.sql
```

Future manifest versions may add explicit runner metadata when dbpm needs to distinguish plain SQL*Plus scripts from SQLcl-only commands or a direct `project deploy` adapter. Until then, manifest entry points should remain SQL*Plus/SQLcl-compatible files wherever possible.

Dependencies declared by a SQLcl project-based package should remain dependencies beyond Core. Core itself should continue to be represented by `core.minimum_version` and verified before deployment.

## Provenance

The manifest should not contain the source commit hash for a built artifact. dbpm should resolve provenance from artifact metadata, such as `META-INF/<artifact>-build.properties`, and pass it into the deployment script at execution time.

## Deployment Scripts

The default convention is that deployment scripts accept the resolved 40-character commit hash as their first SQL*Plus/SQLcl argument. Future manifest versions may make script arguments explicit, but scripts should remain parameterized from the beginning.
