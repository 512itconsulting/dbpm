# Changelog

Notable changes to dbpm are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and dbpm follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

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
