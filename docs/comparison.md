# Comparison

## Introduction

dbpm is inspired by modern software package ecosystems and database deployment tools, but it occupies a different space than most existing solutions.

This document explains how dbpm compares to related tools and approaches.

---

# dbpm vs Liquibase

## Liquibase Focus

Liquibase primarily focuses on:
- schema migrations
- database change tracking
- deployment automation

using changelog files and ordered migrations.

## dbpm Focus

dbpm focuses more broadly on:
- package distribution
- dependency management
- reusable database components
- versioned artifacts
- deployment orchestration
- schema evolution

Schema migration is only one part of the ecosystem.

## Key Difference

Liquibase manages database changes.

dbpm aims to manage database packages and ecosystems.

---

# dbpm vs Flyway

## Flyway Focus

Flyway emphasizes:
- lightweight migration execution
- ordered SQL versioning
- simple deployment workflows

## dbpm Focus

dbpm aims to provide:
- dependency resolution
- reusable package publishing
- artifact metadata
- installation manifests
- ecosystem-level package management

## Key Difference

Flyway is primarily migration-oriented.

dbpm is package-oriented.

---

# dbpm vs Maven

## Maven Focus

Maven provides:
- dependency management
- artifact repositories
- build lifecycle management
- semantic versioning

for Java ecosystems.

## dbpm Similarities

dbpm borrows several concepts from Maven:
- repositories
- immutable artifacts
- versioned dependencies
- transitive dependency resolution

dbpm may also support Maven-compatible repository layouts as an artifact hosting and publishing convention.

## dbpm Differences

Unlike Maven:
- deployments target database schemas
- artifacts contain SQL and PL/SQL assets
- runtime state exists inside the database
- installation order may depend on schema conditions
- deployments may involve data migration
- ordinary consumers should not need Maven or a JDK installed just to retrieve packages

For dbpm, Maven is a useful model and possible repository format, not the required consumer-facing client. dbpm should be able to resolve coordinates to HTTP(S) artifact URLs and retrieve package archives directly where possible.

---

# dbpm vs npm

## npm Focus

npm provides:
- package distribution
- dependency resolution
- rapid ecosystem reuse

for JavaScript.

## dbpm Similarities

dbpm similarly aims to enable:
- reusable libraries
- easy package installation
- ecosystem sharing
- versioned distribution

## dbpm Differences

Database deployments involve:
- persistent state
- data durability
- migration complexity
- operational governance

which creates challenges beyond typical application package management.

---

# dbpm vs Cargo

## Cargo Focus

Cargo combines:
- package management
- dependency resolution
- build orchestration

for Rust.

## dbpm Inspiration

Cargo demonstrates how strongly integrated tooling can improve developer productivity and ecosystem consistency.

dbpm aims for similar cohesiveness in Oracle database development.

---

# dbpm vs Traditional SQL Script Deployments

## Traditional Model

Many database deployments rely on:
- manually ordered scripts
- release folders
- deployment spreadsheets
- environment-specific patching
- operator knowledge

## dbpm Model

dbpm aims to replace this with:
- package manifests
- dependency declarations
- version-aware deployments
- installation tracking
- deterministic orchestration

---

# dbpm vs Oracle SQLcl

## SQLcl Focus

SQLcl is a powerful Oracle command-line client and scripting environment.

SQLcl also includes the `project` command for Oracle database CI/CD workflows. A SQLcl project can:

- initialize a database project repository
- export database objects into source control
- compare branches and stage changes
- generate Liquibase changelogs or changesets
- promote staged work into versioned releases
- generate deployable artifacts
- deploy those artifacts to a target database
- verify snapshots, staged changes, and project state

The `project` workflow is especially useful when a team wants Oracle-supported object export, Git-based change capture, and Liquibase-backed deployment artifacts.

## dbpm Relationship

dbpm is complementary to SQLcl rather than competitive with it. SQLcl `project` overlaps with dbpm around database change packaging and deployment execution, but it does not replace dbpm's package-management responsibilities.

SQLcl `project` is primarily project and changelog oriented.

dbpm is package and dependency oriented.

dbpm should own:

- artifact resolution
- dependency solving across packages
- deployment planning
- Core prerequisite checks
- provenance injection
- deployment lock policy evaluation
- install, upgrade, reinstall, and repair mode selection
- execution orchestration across one or more packages

SQLcl `project` may be useful to dbpm as:

- a producer-side workflow for creating deployable database artifacts
- an artifact format dbpm can retrieve, verify, and deploy
- an execution backend for packages that are authored as SQLcl projects
- a source of generated Liquibase changelogs for schema evolution

In that model, dbpm would still treat Core as an implicit substrate prerequisite, not as a normal package dependency. A SQLcl project artifact consumed by dbpm should still declare package identity, version, Core requirements, dependencies beyond Core, and deployment entry points in dbpm metadata.

dbpm may eventually:

- integrate with SQLcl
- execute deployments through SQLcl
- leverage SQLcl scripting capabilities
- consume SQLcl project artifacts as package artifacts
- wrap `project deploy` behind dbpm planning, policy, and provenance checks

## Key Difference

SQLcl `project` helps a project produce and deploy database changes.

dbpm coordinates packages, dependencies, policy, provenance, and Core-backed installed state across database applications and reusable components.

---

# dbpm vs utPLSQL

## utPLSQL Focus

utPLSQL provides:
- unit testing
- test execution
- testing frameworks

for PL/SQL development.

## dbpm Relationship

dbpm and utPLSQL are complementary.

dbpm may eventually support:
- package-level test execution
- deployment validation
- test-aware installation workflows

using tools such as utPLSQL.

---

# Summary

dbpm attempts to combine ideas from:
- package managers
- artifact repositories
- migration frameworks
- deployment orchestration systems

while remaining grounded in Oracle database realities.

The goal is not merely to automate deployments, but to create a modern ecosystem for Oracle database engineering.
