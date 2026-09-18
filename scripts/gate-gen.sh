#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [[ ${1:-} == --prove ]]; then
  scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
  go run ./internal/api/projection/cmd/genfields "$scratch/fields.ts"
  go run ./internal/api/projection/cmd/genfields -check "$scratch/fields.ts"
  printf '\n// deliberate drift\n' >> "$scratch/fields.ts"
  if go run ./internal/api/projection/cmd/genfields -check "$scratch/fields.ts"; then
    echo 'gate-gen: failed to reject generated drift' >&2; exit 1
  fi
  echo 'prove-gen: drift rejected'
else
  go run ./internal/api/projection/cmd/genfields -check
fi
