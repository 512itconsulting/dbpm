# Package Retrieval Specification

## Purpose

This document defines the intended direction for retrieving dbpm package artifacts.

## User Classes

dbpm should distinguish between two broad classes of users:

- package producers, who build and publish reusable database packages
- package consumers, who install packages into Oracle environments

Consumers are expected to be the larger audience. The consumer workflow should therefore minimize external tooling assumptions.

## Consumer Requirements

Consumers should install packages through dbpm, not through Maven directly.

dbpm should retrieve package archives over HTTP(S) where possible, using a built-in downloader or a ubiquitous platform tool such as `curl`.

Consumer machines should not require Maven or a JDK solely to resolve and download dbpm packages.

## Repository Compatibility

Maven-compatible repositories remain useful as an artifact publishing and hosting format because they provide:

- immutable versioned coordinates
- checksum and metadata conventions
- compatibility with Nexus, Artifactory, GitHub Packages, and similar systems
- familiar CI/CD publishing paths for producers

dbpm may support Maven-style coordinates and repository layouts by resolving them to HTTP(S) artifact URLs internally.

## Producer Flexibility

Package producers may use Maven, Gradle, GitHub Actions, dbpm-native publishing, or another build workflow to publish immutable package archives.

Producer tooling should create artifacts with stable dbpm manifests and generated provenance metadata. It should not force Maven concepts into the package manifest beyond optional repository coordinates and artifact metadata.

## MVP Status

Remote retrieval is outside the current MVP implementation. The MVP supports local package directories and local built ZIP files.

When remote retrieval is added, the first consumer-facing implementation should prioritize direct HTTP(S) archive download over shelling out to Maven.
