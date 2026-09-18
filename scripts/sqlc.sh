#!/usr/bin/env bash
# sqlc.sh — generate the store's typed queries, or assert the checked-in
# generated code matches fresh output (BUILD task 0.7).
#   gen  : regenerate internal/store/gen in place
#   diff : generate into a scratch tree and diff — fails on any difference
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/tool.sh
source scripts/tool.sh
SQLC=$(tool_path sqlc)

case ${1:-} in
  gen)
    "$SQLC" generate
    echo "sqlc-gen: regenerated internal/store/gen"
    ;;
  diff)
    # Scratch config and output both live inside the repo: sqlc resolves the
    # config's schema/, queries/ and out/ paths relative to the config file's
    # directory, so an absolute /tmp target is silently not written. sed keeps
    # sqlc.yaml the single source of truth — a second config would drift.
    cfg=.sqlc-diff.yaml out=.sqlc-diff-out
    trap 'rm -rf "$cfg" "$out"' EXIT
    rm -rf "$out"
    sed "s|out: internal/store/gen|out: $out/gen|" sqlc.yaml > "$cfg"
    "$SQLC" generate -f "$cfg"
    if diff -ru internal/store/gen "$out/gen"; then
      echo "sqlc-diff: checked-in generated code matches fresh output"
    else
      echo "sqlc-diff: generated code is stale — run make sqlc-gen and commit" >&2
      exit 1
    fi
    ;;
  *) echo "usage: $0 gen|diff" >&2; exit 2 ;;
esac
