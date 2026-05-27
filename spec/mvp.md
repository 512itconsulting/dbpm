# MVP Specification

## Purpose
Define the smallest useful dbpm implementation.

## MVP Commands
- check-core
- bootstrap-core
- plan
- lock
- install
- upgrade
- reinstall
- resume
- validate

## Supported Sources
- local package directory
- local built ZIP
- GitHub Maven ZIP artifact coordinate: `gh-maven:owner/repo:group:artifact:version[:extension]`
- HTTPS ZIP artifact URL loaded from a lockfile
- Maven snapshot ZIP artifacts resolved through `maven-metadata.xml`
- SHA-256 checksum capture for local built ZIP artifacts
- SHA-256 checksum capture for downloaded GitHub Maven ZIP artifacts
- deterministic TREE-SHA-256 checksum capture for local package directory sources
- local cache for downloaded and extracted ZIP artifacts
- lockfile generation for resolved install plans
- lockfile verification against current resolution
- lockfile/database reconciliation for installed versions and complete Core status
- lockfile/database reconciliation for Core deployment provenance rows
- lockfile-driven install without restating package sources

## Deferred
- generic Maven repository resolution beyond GitHub Packages
- trusted artifact mirrors
- package publishing
- signing
- APEX integration
- rollback
- rich artifact registry

## Required Behaviors
- parse dbpm.yaml
- verify Core for non-Core packages
- read provenance from artifact metadata or local git
- generate a deployment plan
- generate an ordered multi-package plan from local dependency sources
- enforce environment policy
- execute SQLPlus/SQLcl manifest scripts
- execute ordered local dependency-source install and validate plans
- execute ordered GitHub Maven dependency-source install plans
- write a lockfile for resolved package artifacts
- fail clearly when the current source resolution differs from the lockfile
- verify locked package versions are installed with complete Core status
- verify Core deployment provenance rows match locked artifact identity
- install from locked artifact sources recorded in `dbpm-lock.json`
- pass commit hash into deployment scripts
- stage artifact provenance in Core before running package deployment scripts
- stage Core upgrade provenance when installed Core is 3.2.0 or newer
- include artifact checksum in staged Core provenance when deploying ZIP artifacts or local package directories
- read installed state from Core
- resolve exact semantic version dependencies
- resolve caret-compatible semantic version dependencies, such as `^1.0.0`
- block normal install when the package is already installed
- upgrade complete installed applications to a higher semantic version
- fail clearly when local dependency planning cannot resolve a required package
- block destructive reinstall when installed applications depend on the target
- resume running or failed deployments without deleting application state
- run package validation scripts after successful deployment
- run package validation scripts in dependency order when dependency sources are provided

## Fixtures
- core
- utl_interval
- simple_scheduler, which depends on utl_interval
- live GitHub Maven artifacts for core, utl_interval, and simple_scheduler
- local unit-test packages for dependency ordering

## Runtime Decision

The MVP implementation will use Python.

Rationale:
- strong standard library support for ZIP files, JSON, subprocess execution, filesystem paths, and testing
- straightforward CLI implementation
- broad contributor familiarity
- practical CI/CD and packaging path

Initial third-party dependency:
- PyYAML for `dbpm.yaml` parsing

## Consumer Tooling Direction

The MVP keeps consumer prerequisites minimal. GitHub Maven ZIP package retrieval is implemented through direct HTTP(S) download, without requiring Maven or a JDK on consumer machines.

Maven-compatible repository layouts can remain a publishing and hosting option. dbpm should treat them as addressable artifact repositories, not as a requirement that consumers invoke Maven directly.

## Open Decisions
- SQLPlus vs SQLcl default
- exact plan JSON shape
- generic Maven repository configuration beyond GitHub Packages
