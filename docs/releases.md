# Releasing dbpm

dbpm follows semantic versioning. User-visible changes are accumulated under
`Unreleased` in the root [changelog](../CHANGELOG.md) as they are merged.

## Release checklist

1. Review the changes since the previous release and choose the next semantic
   version.
2. Move the applicable `Unreleased` entries into a section named
   `[X.Y.Z] - YYYY-MM-DD`. Leave an empty `Unreleased` section for subsequent
   work.
3. Update all authoritative version declarations:

   - `pyproject.toml`
   - the `dbpm` package entry in `uv.lock`
   - `src/dbpm/__init__.py`

4. Update the changelog comparison links at the bottom of `CHANGELOG.md`.
5. Run the unit test suite and verify both public version interfaces:

   ```sh
   scripts/test-unit.sh
   uv build --no-sources
   uvx twine check --strict dist/*
   dbpm --version
   python -c 'import dbpm; print(dbpm.__version__)'
   ```

6. Commit the release changes and create an annotated `vX.Y.Z` tag.
7. Push the commit and tag.
8. Create the GitHub release from the matching changelog section. Publishing
   the release runs `.github/workflows/release.yml`, which verifies that the
   tag and package versions agree, rebuilds and tests the distributions,
   publishes them to PyPI, and attaches the same files to the GitHub release.

## One-time PyPI configuration

The `dbpm` project must trust the GitHub Actions release workflow before its
first publication:

1. Create or sign in to the owning PyPI account and enable two-factor
   authentication.
2. Configure a pending trusted publisher for project name `dbpm` with:

   - PyPI project: `dbpm`
   - GitHub owner: `512itconsulting`
   - GitHub repository: `dbpm`
   - Workflow: `release.yml`
   - Environment: `pypi`

3. In the GitHub repository, create an environment named `pypi`. Protect it
   with required reviewers if releases should require manual approval.

The workflow uses GitHub's OpenID Connect identity and does not require a
stored PyPI API token.

Do not change version-like values used solely as test fixtures or documentation
examples unless the release specifically changes the scenario they demonstrate.

## Changelog guidance

Document behavior that matters to package authors, operators, or contributors.
Use the `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, and `Security`
headings as applicable, and omit empty headings from a released section.

Entries should describe the observable result rather than repeat commit
messages. Breaking changes and required operator actions must be explicit.
