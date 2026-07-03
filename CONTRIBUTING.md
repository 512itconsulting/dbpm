# Contributing to dbpm

Thanks for helping improve dbpm. The project is an Oracle database package
manager and deployment orchestrator, so changes should favor reproducible
deployment behavior, clear logs, and conservative database safety.

## Development Setup

Use Python 3.11 or newer. From a local checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Contributors who use `uv` can run:

```sh
uv sync
```

Run the unit test suite without live database settings:

```sh
scripts/test-unit.sh
```

Live Oracle tests are opt-in and require local database configuration. Do not
commit local environment files, connection strings, credentials, tokens, or
database logs that contain sensitive values.

## Project Rules

- Treat Core as an implicit substrate prerequisite, not as a normal dependency
  that every package registers.
- Verify Core before dbpm-managed deployments that require it.
- Keep package dependencies focused on dependencies beyond Core.
- Prefer provenance from immutable artifact metadata. Repository state is a
  local development fallback, not a release contract.
- Do not hard-code git commit hashes in committed deployment wrappers or
  manifests.
- Keep destructive behavior explicit. A full reinstall that calls Core cleanup
  APIs must remain a distinct deployment mode.
- Prefer additive, forward-only schema evolution for production-oriented
  workflows.
- Preserve Oracle-native workflows: SQL*Plus/SQLcl-compatible manifests, plain
  SQL/PLSQL assets, and transparent execution logs.

## Pull Requests

Before opening a pull request:

- Add or update tests for behavioral changes.
- Update docs, examples, or command references when user-facing behavior
  changes.
- Include the commands you ran and any tests you could not run.
- Keep changes scoped to the issue or feature being addressed.
- Avoid rewriting unrelated formatting or generated files.

## Compatibility Notes

dbpm uses semantic versioning. Be careful with changes that affect:

- Manifest fields or package layout.
- Lockfile schema or checksum/signature behavior.
- CLI flags, source syntax, and exit behavior.
- Core integration, deployment provenance, and installed-state lookup.
- SQL generated for package execution or script generation.

Breaking changes should be called out clearly in the pull request.

