# AGENTS.md

## Purpose

dbpm is an Oracle database package manager and deployment orchestrator. It resolves package artifacts, plans dependency order, injects deployment provenance, executes package manifests, and relies on Core as the in-database deployment substrate.

## Rules

- Treat Core as an implicit substrate prerequisite, not as a normal application dependency to register for every package.
- Verify Core is installed and meets the required minimum version before running dbpm-managed package deployments.
- Keep application dependencies focused on dependencies beyond Core.
- Do not hard-code git commit hashes in committed deployment wrappers or manifests.
- Prefer provenance injection from immutable artifact metadata, falling back to repository state only for local development workflows.
- Keep destructive behavior explicit. A full reinstall that calls Core's `pkg_application.delete_application_p` must be a distinct deployment mode, not the default install path.
- Avoid destructive reinstall in established environments unless the user clearly requests it and the environment policy allows it.
- Prefer additive, forward-only schema evolution for production-oriented deployments.
- Preserve Oracle-native workflows: SQL*Plus/SQLcl-compatible manifests, plain SQL/PLSQL assets, and transparent execution logs.

## Architecture

dbpm should own artifact resolution, dependency solving, deployment planning, provenance injection, environment policy checks, and execution orchestration.

Core should own installed application state, deployment history, dependency and privilege records, object registration, metadata ownership, and cleanup behavior inside the target Oracle schema.

Package manifests should declare identity, version, supported database requirements, dependencies beyond Core, and deployment entry points. They should remain stable and parameterized so dbpm can inject environment-specific values at execution time.
