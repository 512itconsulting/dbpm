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
- Support [semantic versioning](https://semver.org/)
- Enable repeatable deployments
- Use [Core](https://github.com/512itconsulting/core) as the in-database install registry and deployment substrate
- Support schema evolution
- Inject deployment provenance from package artifacts
- Lock deployments to immutable artifact identities
- Simplify CI/CD integration
- Reduce fragile hand-managed deployment scripts

Example
```powershell
uv run dbpm check-core --minimum-version 3.2.0
uv run dbpm plan gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --mode install --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
uv run dbpm lock gh-maven:rsantmyer/simple_scheduler:com.512itconsulting.database:simple_scheduler:1.1.0 --dependency-source gh-maven:512itconsulting/utl_interval:com.512itconsulting.database:utl_interval:1.0.0
uv run dbpm install --lockfile dbpm-lock.json --env development
```

## Current MVP
- Package manifests through `dbpm.yaml`, `dbpm.yml`, `dbpm.json`, or `package.dbpm.yaml`
- Local package directory sources
- Local ZIP package sources
- GitHub Maven ZIP package sources with `gh-maven:owner/repo:group:artifact:version[:extension]`
- Generic Maven ZIP package sources with `maven:repository-url::group:artifact:version[:extension]`
- HTTPS ZIP artifact sources for lockfile installs
- Maven snapshot ZIP resolution through `maven-metadata.xml`
- SHA-256 checksum capture for ZIP artifacts and deterministic TREE-SHA-256 capture for local directories
- Content-addressed artifact cache keyed by SHA-256 for lockfile-verified downloads
- Exact and caret-compatible dependency constraints
- Ordered multi-package install, conservative upgrade, and validate for dependency sources
- Dependency lockfile generation and verification through `dbpm lock`
- Lockfile-driven install without restating package sources
- Core-backed installed-state lookup
- Core-backed reverse-dependency lookup
- Core provenance staging through `pkg_application.stage_deployment_provenance_p`
- Environment-aware deployment plans
- Install, upgrade, reinstall, resume, and validate workflows

## Still Planned
- Package signing
- APEX integration
- Rich artifact registry

## Status
Early-stage experimental project. The current MVP has been live-tested against GitHub Packages artifacts for:

- `core`
- `utl_interval`
- `simple_scheduler`

`simple_scheduler` depends on `utl_interval`; dbpm can install both from GitHub Packages in dependency order and record Core provenance with artifact URLs and SHA-256 checksums.

## Environment

Database and GitHub Packages access is configured through local, uncommitted environment files such as `dbpm-env.ps1` or `dbpm-env.sh`. Start from the committed templates `dbpm-env.ps1.example` or `dbpm-env.sh.example`.

Common variables:

- `DBPM_SQL_RUNNER`: SQLcl or SQLPlus executable, such as `sql.exe`
- `DBPM_CONNECT`: Oracle connect string
- `DBPM_GITHUB_TOKEN`: GitHub token with package read access
- `DBPM_GITHUB_USER`: optional GitHub username for package authentication
- `DBPM_CACHE_DIR`: optional local artifact cache directory, default: `~/.dbpm/cache`
- `DBPM_LOG_DIR`: optional execution log directory, default: `.dbpm-logs` in the current working directory
- `DBPM_RUN_DB_TESTS`: optional `1` to enable live database pytest tests

## Commands

```text
dbpm check-core
dbpm plan
dbpm lock
dbpm bootstrap-core
dbpm install
dbpm upgrade
dbpm reinstall
dbpm resume
dbpm validate
```

Run `dbpm <command> --help` for command-specific options.

During development, examples use `uv run dbpm ...` so uv runs the project console script in the project environment. If the project has already been installed into a virtual environment, the generated console script can also be called directly: `.venv/bin/dbpm` on Linux/macOS or `.\.venv\Scripts\dbpm.exe` on Windows.

## Related Projects
- [core](https://github.com/512itconsulting/core)
