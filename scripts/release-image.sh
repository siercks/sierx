#!/usr/bin/env bash
# Compatibility entry point for a native candidate, not an alternate image recipe.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [[ -n ${SIERX_RELEASE_IMAGE:-} ]]; then
  echo 'Use SIERX_RELEASE_REPOSITORY and TAG. This wrapper builds one native candidate; promotion requires both native acceptance results.' >&2
  exit 1
fi
bash scripts/release.sh binaries
bash scripts/release.sh image
echo 'Native candidate prepared. Use release-stage, release-test and release-manifest as documented in docs/RELEASE-ASSURANCE.md.'
