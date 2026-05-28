#!/usr/bin/env bash
set -euo pipefail

# Unit tests should not inherit live database configuration. Some CLI tests
# intentionally exercise behavior when no database connection is configured.
unset DBPM_CONNECT
unset DBPM_RUN_DB_TESTS

export UV_CACHE_DIR="${UV_CACHE_DIR:-"$PWD/.uv-cache"}"

uv run --extra dev pytest "$@"
