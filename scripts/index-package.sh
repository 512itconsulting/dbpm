#!/usr/bin/env sh
set -eu

# Friendly wrapper for the common "index the artifact I just published" workflow.
# dbpm remains responsible for parsing YAML, creating JSON, validating metadata,
# and sending the authenticated request. This script never reads or prints the
# registry token itself.

PACKAGE_ROOT="."
if [ "$#" -gt 0 ] && [ "${1#-}" = "$1" ]; then
  PACKAGE_ROOT="$1"
  shift
fi

if ! command -v dbpm >/dev/null 2>&1; then
  echo "index-package.sh: dbpm is not installed or not on PATH" >&2
  exit 2
fi

if [ ! -f "${PACKAGE_ROOT}/dbpm-publish-receipt.json" ]; then
  echo "index-package.sh: publish receipt not found: ${PACKAGE_ROOT}/dbpm-publish-receipt.json" >&2
  echo "Run dbpm publish first, or use dbpm registry index directly with artifact overrides." >&2
  exit 2
fi

if [ -z "${DBPM_REGISTRY_TOKEN:-}" ]; then
  echo "index-package.sh: DBPM_REGISTRY_TOKEN is not set" >&2
  exit 2
fi

# The public registry is the default. Override this in the environment for a
# private or local registry.
export DBPM_REGISTRY_URL="${DBPM_REGISTRY_URL:-https://dbpm.io}"

exec dbpm registry index "$PACKAGE_ROOT" "$@"
