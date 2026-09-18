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

# Environment wins; .env fills the gaps. Every other script in scripts/ does
# this, and this one did not: the CLI then saw no DATABASE_URL whenever the
# caller had set it as a shell variable rather than an exported one, which is
# the normal way to type it. `make seed` failed with "DATABASE_URL is unset"
# on a host where DATABASE_URL was plainly set. Introduced when this wrapper
# replaced `go run` in the make targets.
load_dotenv() {
  local file=$1 line key val
  [[ -f $file ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}
    line=${line#"${line%%[![:space:]]*}"}; line=${line%"${line##*[![:space:]]}"}
    [[ -z $line || $line != *=* ]] && continue
    key=${line%%=*}; val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}; val=${val#"${val%%[![:space:]]*}"}
    [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z ${!key+x} ]]; then export "$key=$val"; fi
  done < "$file"
}
load_dotenv .env

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
