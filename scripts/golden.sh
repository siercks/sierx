#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
expected="go$(awk '$1=="go"{print $2;exit}' go.mod)"
[[ $(go env GOVERSION) == "$expected" ]] || { echo "golden: use pinned $expected" >&2; exit 1; }
case ${1:-check} in
  update) SIERX_GOLDEN_UPDATE=1 bash scripts/test-go.sh ./internal/api/... ./internal/sxq -count=1 ;;
  check)
    scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
    cp -a test/golden "$scratch/golden"
    SIERX_GOLDEN_UPDATE=1 bash scripts/test-go.sh ./internal/api/... ./internal/sxq -count=1
    diff -ru "$scratch/golden" test/golden
    echo 'golden: all endpoint and query fixtures reproduce without drift'
    ;;
  *) echo 'usage: golden.sh check|update' >&2; exit 1 ;;
esac
