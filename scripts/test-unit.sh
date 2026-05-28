#!/usr/bin/env bash
set -euo pipefail

# Unit tests should not inherit live database configuration. Some CLI tests
# intentionally exercise behavior when no database connection is configured.
unset DBPM_CONNECT
unset DBPM_RUN_DB_TESTS

uv run --extra dev pytest "$@"
