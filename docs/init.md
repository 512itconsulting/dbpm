# Initializing a Package or Workspace

`dbpm init` scaffolds a new package or workspace directory with the standard
folder layout, a template manifest, and git-friendly placeholder files.

See [dbpm init](commands/init.md) for the command reference.

## Package names

Package names must start with a lowercase letter and contain only lowercase
letters, digits, underscores (`_`), or hyphens (`-`). These names map to the
Oracle application registry name by converting to uppercase and replacing
hyphens with underscores.

Valid examples: `core`, `my_package`, `utl-bs-numeric`

## Generated manifest

The generated `dbpm.yaml` includes all active fields needed for a minimal
deployment plus commented-out stanzas for optional fields — vendor, license,
Core version requirement, dependencies, extra script entry points, and
publishing config — so the file is self-documenting without cluttering a
working manifest.

## Non-empty directories

`dbpm init` refuses to run in a non-empty directory unless `--force` is given.
With `--force`, only missing files and directories are created; nothing already
present is modified or overwritten.
