# Vision

## Why dbpm Exists

Modern software engineering has mature ecosystems for packaging, dependency management, versioning, and deployment:

- Java has Maven and Gradle
- JavaScript has npm
- Rust has Cargo
- Python has pip
- Linux distributions have rpm and apt

Oracle database development largely does not.

Database deployments are still commonly managed through:
- manually ordered SQL scripts
- shared folders
- spreadsheets
- tribal knowledge
- ad hoc release coordination
- environment-specific patching

This creates operational risk, slows development velocity, and makes reuse difficult.

dbpm exists to bring modern package management concepts to Oracle database development while respecting the realities of enterprise database environments.

The ecosystem has two important audiences:
- package producers, who publish reusable database packages
- package consumers, who install and operate those packages

Consumers are expected to drastically outnumber producers. dbpm should therefore optimize the everyday install experience for database developers and DBAs who may not be comfortable with Java build tooling.

---

## Core Vision

dbpm aims to become a complete ecosystem for:

- reusable database packages
- dependency management
- schema evolution
- deployment orchestration
- version tracking
- repeatable installations
- deterministic deployments

The long-term goal is to make database development feel closer to modern software engineering disciplines without forcing developers to abandon Oracle-native workflows.

---

## Design Principles

dbpm is designed around several core ideas:

### Database-First

The database is not a secondary deployment artifact.

The database is a first-class software platform deserving:
- proper packaging
- versioning
- dependency management
- automation
- testing
- distribution

### Oracle-Native

dbpm should integrate naturally with:
- SQL*Plus
- SQLcl
- PL/SQL
- Oracle metadata
- Oracle deployment workflows

rather than forcing developers into unnatural abstractions.

Consumer workflows should not require Maven or a JDK merely to retrieve a package. Maven-compatible repositories may be supported as a storage and publishing convention, but dbpm should resolve and download artifacts through plain HTTP(S) where possible.

### Declarative Over Manual

Developers should declare:
- dependencies
- versions
- installation requirements
- deployment intent

rather than manually coordinating deployment order and scripts.

### Deterministic Deployments

Deployments should be:
- repeatable
- auditable
- environment-aware
- predictable

with minimal hidden state or operator-dependent behavior.

### Reuse Over Duplication

Reusable PL/SQL utilities should be easy to:
- package
- publish
- discover
- version
- consume

without copy/paste distribution models.

---

## Long-Term Goals

### Package Registry

A central or distributed registry of reusable Oracle database packages.

Registries may use Maven-compatible layouts, GitHub Packages, static HTTP(S) hosting, or other immutable artifact stores. dbpm should hide those repository details behind its own package resolution flow for consumers.

### Dependency Resolution

Automatic dependency resolution similar to:
- Maven
- npm
- Cargo

including semantic versioning support.

Core is treated as the substrate prerequisite for dbpm-managed deployments. dbpm should verify that Core exists and satisfies the required minimum version before package deployment begins, while ordinary package manifests should declare dependencies beyond Core.

### Schema Evolution

Structured, version-aware schema evolution with support for:
- incremental migrations
- installation history
- deployment plans
- environment state tracking

### CI/CD Integration

Integration with modern development workflows including:
- GitHub Actions
- Jenkins
- Azure DevOps
- GitLab CI

Producer workflows may use Maven, Gradle, GitHub Actions, or dbpm-native publishing commands to create and publish immutable artifacts. This producer-side flexibility should not leak into consumer installation requirements.

### Artifact-Based Deployments

Deployments should use immutable versioned artifacts rather than mutable collections of scripts.

Deployment provenance should come from artifact metadata whenever possible, including the artifact coordinates, source commit hash, dirty-state marker, and build time. Local source deployments may derive provenance from repository state, but committed deployment scripts should remain parameterized rather than embedding a specific commit hash.

### Ecosystem Standardization

Establish common conventions for:
- package structure
- metadata
- dependency declarations
- installation manifests
- deployment orchestration

---

## Non-Goals

dbpm is not intended to:
- replace Oracle itself
- abstract away SQL
- eliminate DBA oversight
- hide database behavior behind ORM layers
- become a low-code platform

The goal is to improve database engineering workflows, not replace database engineering.

---

## Current Status

dbpm is currently an early-stage experimental project exploring architecture, standards, and deployment models for Oracle database package management.

The ecosystem and specifications are expected to evolve significantly during initial development.
