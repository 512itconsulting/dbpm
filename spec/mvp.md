# MVP Specification

## Purpose
Define the smallest useful dbpm implementation.

## MVP Commands
- bootstrap-core
- plan
- install
- reinstall

## Supported Sources
- local package directory
- local built ZIP

## Deferred
- upgrade
- remote HTTP(S) artifact retrieval
- Maven-compatible/GitHub Packages repository resolution
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
- enforce environment policy
- execute SQLPlus/SQLcl manifest scripts
- pass commit hash into deployment scripts
- read installed state from Core

## Fixtures
- core
- utl_interval
- one small dependency-order test package later

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

The MVP should keep consumer prerequisites minimal. Remote package retrieval is deferred, but when it is introduced, dbpm should retrieve artifacts over HTTP(S) itself rather than requiring Maven or a JDK on consumer machines.

Maven-compatible repository layouts can remain a publishing and hosting option. dbpm should treat them as addressable artifact repositories, not as a requirement that consumers invoke Maven directly.

## Open Decisions
- SQLPlus vs SQLcl default
- exact plan JSON shape
