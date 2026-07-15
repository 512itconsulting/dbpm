# First-Class Test Command Design

## Purpose

`dbpm validate` runs a package-defined validation or smoke-test script after a
package is installed. That is useful for confirming package health in a target
environment, but it is not the same lifecycle as running a development or CI
test suite.

dbpm should add a first-class `test` command for package tests that may compile
test-only objects, create fixtures, require test frameworks such as utPLSQL, and
perform setup or cleanup that would be inappropriate for production validation.

## Proposed User Experience

Expose:

```sh
dbpm test source [--approve] [--dry-run]
                [--package NAME] [--registry-url URL]
                [--dependency-source SOURCE]...
                [--connect STRING] [--runner EXEC]
```

The command should execute a package test script declared in the manifest:

```yaml
scripts:
  install: deployment_manifests/deploy.sql
  validate: deployment_manifests/validate.sql
  test: tests/run_all.sql
```

`scripts.test` should be SQL*Plus/SQLcl-compatible, matching the existing
manifest script model. For Oracle packages, a typical test script may compile
utPLSQL packages, create fixtures, run `ut.run`, and clean up fixtures.

## Validate Versus Test

Keep `validate` and `test` distinct:

| Command | Question | Expected scope |
|---|---|---|
| `dbpm validate` | Is the installed package healthy in this environment? | Post-install checks, smoke tests, object validity, grants, registry state. |
| `dbpm test` | Does the package behavior pass its development suite? | Fixtures, test-only packages, utPLSQL suites, destructive setup/teardown, longer CI checks. |

Validation should remain safe enough to run after install in shared or
production-like environments. Tests may be invasive and should be treated as a
development or CI workflow by default.

## Execution Model

Initial behavior can reuse the existing planning and execution machinery:

1. Resolve the package source and manifest.
2. Verify the package is installed and complete, unless a future option permits
   install-and-test in one command.
3. Resolve dependencies enough to verify that declared dependency sources and
   installed dependency versions satisfy the selected package.
4. Default to testing only the selected package. Do not run dependency test
   scripts in the first implementation.
5. Execute `scripts.test` with the configured SQL runner.
6. Return the SQL runner exit code.

The first implementation does not need framework-specific parsing. A passing
test command is any script that exits successfully, and a failing suite should
cause a nonzero exit through the script itself.

## Implementation Notes

The first implementation should be a new execution mode rather than a separate
test-only code path:

- Extend `ScriptSet` and manifest parsing with `scripts.test`, using the same
  normalized path handling as other manifest scripts.
- Add `test` to the planner script lookup. `test` should use no automatic
  script arguments, should not stage deployment provenance, and should not
  record deployment provenance.
- Add `test` to the CLI execution-command dispatch and to `dbpm plan --mode`.
  It should use the same common, execution, dependency-source, and database
  arguments as `validate`.
- Read installed state for `test` and enforce the same installed-state
  preflight as `validate`: the package must exist in Core with deployment
  status `C`.
- Resolve dependency sources for graph/version correctness, but keep the
  executable plan scoped to the selected package until a future
  `--include-dependencies` option exists.
- Keep existing `validate` behavior unchanged, including its current
  dependency validation behavior when dependency sources are provided.

Tests under the scaffolded `tests/` directory are already compatible with the
package artifact model as long as `.dbpmignore` does not exclude them. Add a
packaging regression test so published ZIP artifacts include `tests/run_all.sql`
by default.

## Future Enhancements

- Add `--include-dependencies` to run dependency tests before consumer tests.
- Add `--install` or `--reinstall` for disposable CI databases.
- Add manifest metadata for test requirements, such as `utPLSQL`, minimum
  framework versions, or test-only dependencies.
- Capture structured test reports when frameworks can emit JUnit XML or JSON.
- Add policy controls so test scripts are disallowed in protected environments
  unless explicitly approved.
- Add workspace support for running tests across multiple packages in dependency
  order.

## Acceptance Criteria

- `dbpm test` fails clearly when `scripts.test` is missing.
- `dbpm test --dry-run` prints the resolved test plan without executing SQL.
- `dbpm plan --mode test` prints the same test plan shape that `dbpm test
  --dry-run` executes.
- Test scripts can live under `tests/` and are packaged with local and published
  artifacts.
- Test execution uses the same `--connect`, `--runner`, `--package`,
  and source resolution behavior as `validate`.
- Dependency sources supplied to `dbpm test` are checked for dependency
  resolution and version compatibility, but their test scripts are not executed
  by default.
- A SQL runner failure or utPLSQL failure propagates as a nonzero dbpm exit.
- `validate` behavior remains unchanged.
