#!/usr/bin/env bash
# Compare the actual vendor tree, including untracked/ignored/missing files.
# Generating into vendor/ first would repair defects before inspecting them;
# git diff would then miss newly generated files not present in its index.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
go mod verify
scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
go mod vendor -o "$scratch/vendor"
if ! diff -qr vendor "$scratch/vendor"; then
  echo 'vendor-verify: vendor/ differs from pinned modules; run go mod vendor, review and include the restored files in the commit' >&2
  exit 1
fi
echo 'vendor-verify: OK (complete file tree matches pinned modules)'
