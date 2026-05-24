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
- remote Maven/GitHub Packages resolution
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

## Open Decisions
- Python vs other runtime
- SQLPlus vs SQLcl default
- exact plan JSON shape