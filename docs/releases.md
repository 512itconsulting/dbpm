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
   dbpm --version
   python -c 'import dbpm; print(dbpm.__version__)'
   ```

6. Commit the release changes and create an annotated `vX.Y.Z` tag.
7. Push the commit and tag.
8. Create the GitHub release from the matching changelog section.

Do not change version-like values used solely as test fixtures or documentation
examples unless the release specifically changes the scenario they demonstrate.

## Changelog guidance

Document behavior that matters to package authors, operators, or contributors.
Use the `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, and `Security`
headings as applicable, and omit empty headings from a released section.

Entries should describe the observable result rather than repeat commit
messages. Breaking changes and required operator actions must be explicit.
