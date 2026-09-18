#!/usr/bin/env bash
# tool.sh — fetch a pinned release binary into bin/ (gitignored) and print its
# path. Sourced by the scripts that need one; never run directly.
#
# Why release binaries rather than `go tool`: goose and sqlc each pull a large
# dependency tree (database drivers, a SQL parser) that would land in go.mod and
# in `gate-license`'s scope without a single line of them shipping in the
# binary. The pins here are version + sha256 per architecture, checked on every
# fetch, which is the property `go tool` would otherwise provide.
#
# Adding a tool: add a tool_<name> function setting VERSION, URL, and SHA.
set -euo pipefail

TOOL_BIN=bin

tool_goose() {
  VERSION=v3.28.0
  case $1 in
    x86_64) SHA=ab073515b78ef345f64f018c0d79aa7db50106806efc686dda7181253765ae13 ;;
    arm64)  SHA=3968855c11b4093af271c5226909789ea294468f6e50203d738b7504995b6247 ;;
  esac
  URL=https://github.com/pressly/goose/releases/download/$VERSION/goose_linux_$1
  ARCHIVE=none
}

tool_sqlc() {
  VERSION=v1.31.1
  local a=$1
  [[ $a == x86_64 ]] && a=amd64
  case $a in
    amd64) SHA=497ae4fcdfa64c5b0c311ffe4c2bd991e43991e82e5367792ed78bc2dca27354 ;;
    arm64) SHA=b7cae247740d0c51a1e657479e5b2d21e6fef428f596682a01bc55bf4ab8a23d ;;
  esac
  URL=https://github.com/sqlc-dev/sqlc/releases/download/$VERSION/sqlc_${VERSION#v}_linux_$a.tar.gz
  ARCHIVE=tar.gz
}

# tool_path NAME -> path to the verified binary, fetching it if needed
tool_path() {
  local name=$1 arch
  arch=$(uname -m)
  case $arch in x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=arm64 ;;
    *) echo "tool.sh: no pin for arch $arch" >&2; return 1 ;;
  esac
  local VERSION SHA URL ARCHIVE
  "tool_$name" "$arch"
  [[ -n ${SHA:-} ]] || { echo "tool.sh: no $name pin for $arch" >&2; return 1; }

  local dest=$TOOL_BIN/$name
  local version_arg=--version
  [[ $name != sqlc ]] || version_arg=version
  if [[ -x $dest ]] && "$dest" "$version_arg" 2>/dev/null | grep -q "${VERSION#v}"; then
    echo "$dest"; return 0
  fi
  mkdir -p "$TOOL_BIN"
  local tmp; tmp=$(mktemp -d)
  echo "fetching $name $VERSION ($arch) ..." >&2
  curl -fsSL -o "$tmp/dl" "$URL"
  echo "$SHA  $tmp/dl" | sha256sum -c --quiet - \
    || { echo "tool.sh: $name checksum mismatch — refusing to run it" >&2; rm -rf "$tmp"; return 1; }
  if [[ $ARCHIVE == tar.gz ]]; then
    tar xzf "$tmp/dl" -C "$tmp" && mv "$tmp/$name" "$dest"
  else
    mv "$tmp/dl" "$dest"
  fi
  chmod +x "$dest"; rm -rf "$tmp"
  echo "$dest"
}
