#!/usr/bin/env bash
# sierxctl.sh — run the operator CLI from a built binary instead of `go run`.
#
# `go run` relinks on every invocation, which costs a few seconds each time;
# gate-0 invokes the CLI six times. This builds bin/sierxctl once and reuses it
# until a source file is newer than the binary, so the common case is exec with
# no compile at all.
#
# bin/ is gitignored. Callers pass arguments through unchanged.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BIN=bin/sierxctl

needs_build() {
  [[ -x $BIN ]] || return 0
  # Rebuild if any Go source, go.mod or go.sum is newer than the binary.
  local newer
  newer=$(find cmd internal go.mod go.sum -newer "$BIN" \
            \( -name '*.go' -o -name 'go.mod' -o -name 'go.sum' \) -print -quit 2>/dev/null || true)
  [[ -n $newer ]]
}

if needs_build; then
  mkdir -p bin
  go build -o "$BIN" ./cmd/sierxctl
fi

exec "./$BIN" "$@"
