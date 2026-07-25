# Changelog

Notable changes to dbpm are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and dbpm follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

- Replaced the design-only `runtime.into` proposal with a composable
  application runtime specification based on a root-application prefix,
  isolated versioned dependency payloads, declarative command exports, and
  graph-level activation receipts.
- Replaced the short-lived package-owned runtime manifest and execution path;
  `runtime.name`, `runtime.home_env`, `runtime.into`, and `runtime.layout` are
  rejected rather than maintained as compatibility contracts.
- Added validation for the composable `runtime` manifest and an
  application-runtime receipt model.
- Added read-only application runtime graph planning, including isolated
  payload paths, root-controlled aliases and suppression, and export collision
  checks. Deployment execution remains intentionally blocked until activation
  is implemented.
- Added locked application runtime staging, package-local script execution
  with the injected application environment contract, per-package log capture,
  and staged command validation that rejects missing, non-executable, or
  payload-escaping targets. Activation remains intentionally disconnected from
  normal deployment execution.

### Deprecated

### Removed

### Fixed

### Security

## [1.3.0] - 2026-07-23

### Added

- Added manifest-declared runtime components for non-database payloads.
- Added runtime prefix resolution, installed-state receipts, explicit runtime
  plan output, and runtime install, upgrade, resume, reinstall, and validation
  execution.
- Added a design specification for a future first-class `dbpm test` command.

### Fixed

- Limited package tree exclusions for `build`, `dist`, and `target` to
  package-root directories so identically named nested content is retained.

## [1.2.2] - 2026-07-05

### Changed

- Validated manifest script paths before execution.
- Escaped generated SQL metadata safely.
- Sent a fallback successful exit directive to SQL runners.

### Security

- Rejected unsafe ZIP member paths during package extraction.

## [1.2.0] - 2026-07-04

### Added

- Added Core 3.5 deployment metadata prompt support.
- Added deployment-environment selection to Core bootstrap.

### Changed

- Refactored deployment policy handling and its documentation.

## [1.1.2] - 2026-07-03

### Added

- Added actionable suggested commands to deployment errors.
- Added issue templates and project contribution and security guidance.

### Changed

- Distinguished raw Oracle connect strings from SQLcl saved connections.
- Standardized shell examples and clarified that `uv` is a contributor
  convenience rather than a consumer requirement.

## [1.1.0] - 2026-06-24

### Added

- Added SQLcl saved-connection support.

## [1.0.1] - 2026-06-19

### Fixed

- Set the intended Oracle schema explicitly in generated deployment scripts.

[Unreleased]: https://github.com/512itconsulting/dbpm/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/512itconsulting/dbpm/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/512itconsulting/dbpm/compare/v1.2.0...v1.2.2
[1.2.0]: https://github.com/512itconsulting/dbpm/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/512itconsulting/dbpm/compare/v1.1.0...v1.1.2
[1.1.0]: https://github.com/512itconsulting/dbpm/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/512itconsulting/dbpm/releases/tag/v1.0.1
