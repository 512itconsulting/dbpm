# dbpm
**dbpm** is a package manager for Oracle database applications and reusable PL/SQL components.

The goal is to bring modern dependency management, versioning, packaging, and deployment workflows to Oracle database development.

## Vision

dbpm aims to make Oracle database development feel more like modern software engineering ecosystems such as:

- Maven
- npm
- Cargo
- pip

while remaining Oracle-native and deployment-friendly.

## Goals
- Package reusable PL/SQL libraries
- Resolve dependencies automatically
- Support semantic versioning
- Enable repeatable deployments
- Use Core as the in-database install registry and deployment substrate
- Support schema evolution
- Inject deployment provenance from package artifacts
- Simplify CI/CD integration
- Reduce fragile hand-managed deployment scripts

Example
```text
dbpm bootstrap core@1.2.0
dbpm install utl_interval@2.1.4
```

## Planned Features
- Package manifests
- Dependency resolution
- Maven/GitHub Packages integration
- Core-backed install registry
- Deployment orchestration
- Roll-forward migrations
- Environment-aware deployment plans
- Package signing
- APEX integration
- CLI tooling

## Status
Early-stage experimental project.

## Related Projects
- [core](https://github.com/rsantmyer/core)
