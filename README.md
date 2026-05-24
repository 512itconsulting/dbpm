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

Maven-compatible repositories may be useful for publishing immutable package artifacts, but dbpm should not require ordinary package consumers to understand Maven or install a JDK. Consumer installs should use dbpm's own CLI and plain HTTP(S) artifact retrieval where possible.

## Goals
- Package reusable PL/SQL libraries
- Deploy end-user Oracle database applications through the same package workflow
- Resolve dependencies automatically
- Support semantic versioning
- Enable repeatable deployments
- Use Core as the in-database install registry and deployment substrate
- Support schema evolution
- Inject deployment provenance from package artifacts
- Lock deployments to immutable artifact identities
- Simplify CI/CD integration
- Reduce fragile hand-managed deployment scripts

Example
```text
dbpm bootstrap core@1.2.0
dbpm install utl_interval@2.1.4
```

## Planned Features
- Package manifests
- Dependency lockfiles
- Dependency resolution
- Local artifact cache
- HTTP(S) package retrieval
- Maven-compatible and GitHub Packages repository resolution
- Trusted artifact mirrors for production deployments
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
