#!/usr/bin/env bash
# gate-notopology — no real hostnames, addresses, or .env values in any
# committable file. BUILD §3.7, task 0.1 step 8.
#
# Scans every tracked file plus every untracked file git would accept
# (`git ls-files --cached --others --exclude-standard`), so a violation is
# caught before `git add`, not after. Three checks:
#
#   1. RFC 1918 address literals: 10/8, 172.16/12, 192.168/16
#   2. Hostnames under .internal, .local, .lan, .home
#   3. Any value the operator has set in the untracked .env that differs from
#      the committed .env.example default for the same key. The example's own
#      values are public by construction; what must never leak is what the
#      human filled in on top of them. The whole value is matched, verbatim;
#      values shorter than 4 characters are skipped as noise.
#
# `--prove` runs the gate against a scratch copy with each violation planted
# in turn and asserts the gate goes red, then asserts a clean copy passes.
# Task 0.12's prove-gates.sh discovers gate-* targets from the Makefile and
# invokes `scripts/<gate>.sh --prove`; this is the convention it will read.
#
# Excluded from the scan: this script (it carries the patterns).
set -euo pipefail

SELF=scripts/gate-notopology.sh

rfc1918='(^|[^0-9.])(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3})([^0-9.]|$)'
hostsfx='(^|[^A-Za-z0-9._-])[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.(internal|local|lan|home)([^A-Za-z0-9_-]|$)'

# read_env FILE -> prints KEY<TAB>VALUE per assignment, comments stripped
read_env() {
  local line key val
  [[ -f $1 ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%"${line##*[![:space:]]}"}
    [[ -z $line || $line != *=* ]] && continue
    key=${line%%=*}; val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}
    val=${val#"${val%%[![:space:]]*}"}
    [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    printf '%s\t%s\n' "$key" "$val"
  done < "$1"
}

# scan ROOT -> exit 0 clean, 1 on any hit. Prints hits as file:line:match.
scan() {
  local root=$1 rc=0 files
  files=$(cd "$root" && git ls-files --cached --others --exclude-standard -z \
            | tr '\0' '\n' | grep -vx "$SELF" | grep -v '^\.env$' || true)
  [[ -z $files ]] && { echo "gate-notopology: no files to scan"; return 0; }

  local hits
  hits=$(cd "$root" && printf '%s\n' "$files" | xargs -d '\n' grep -nIE "$rfc1918" -- 2>/dev/null || true)
  if [[ -n $hits ]]; then
    echo "RFC 1918 address literal in a committable file:"; sed 's/^/  /' <<<"$hits"; rc=1
  fi

  hits=$(cd "$root" && printf '%s\n' "$files" | xargs -d '\n' grep -nIE "$hostsfx" -- 2>/dev/null || true)
  if [[ -n $hits ]]; then
    echo "Internal hostname suffix (.internal/.local/.lan/.home) in a committable file:"
    sed 's/^/  /' <<<"$hits"; rc=1
  fi

  if [[ -f $root/.env ]]; then
    declare -A example=()
    local key val
    while IFS=$'\t' read -r key val; do example[$key]=$val; done < <(read_env "$root/.env.example")
    while IFS=$'\t' read -r key val; do
      [[ -z $val || ${#val} -lt 4 ]] && continue
      [[ ${example[$key]+x} && ${example[$key]} == "$val" ]] && continue
      hits=$(cd "$root" && printf '%s\n' "$files" | xargs -d '\n' grep -nIF -- "$val" 2>/dev/null || true)
      if [[ -n $hits ]]; then
        # Print the key, never the value — this output gets pasted into PROGRESS.md.
        echo "Value of ${key} from .env appears in a committable file:"
        cut -d: -f1,2 <<<"$hits" | sed 's/^/  /'; rc=1
      fi
    done < <(read_env "$root/.env")
  fi
  return $rc
}

prove() {
  local src tmp
  src=$(git rev-parse --show-toplevel)
  tmp=$(mktemp -d); trap "rm -rf '$tmp'" EXIT
  (cd "$src" && git ls-files --cached --others --exclude-standard -z \
     | xargs -0 cp --parents -t "$tmp")
  (cd "$tmp" && git init -q && git add -A)
  local fails=0 target=README.md

  expect_red() {   # expect_red LABEL
    if (scan "$tmp" >/dev/null); then echo "prove: $1: gate stayed GREEN — FAIL"; fails=1
    else echo "prove: $1: gate went red — OK"; fi
  }
  restore() { (cd "$tmp" && git checkout -q -- "$target" && rm -f .env); }

  printf '\nhost 192.168.44.9 is the staging box\n' >> "$tmp/$target"; expect_red "rfc1918 192.168/16"; restore
  printf '\nssh backup@10.0.7.3\n' >> "$tmp/$target";                 expect_red "rfc1918 10/8"; restore
  printf '\nendpoint 172.20.1.5\n' >> "$tmp/$target";                 expect_red "rfc1918 172.16/12"; restore
  printf '\nrepo on nas01.lan\n' >> "$tmp/$target";                   expect_red ".lan hostname"; restore
  printf '\npg1-host=db.internal\n' >> "$tmp/$target";                expect_red ".internal hostname"; restore
  printf 'PGBACKREST_REPO_PATH=bkp-zq81x:/srv/pgbackrest/sierx\n' > "$tmp/.env"
  printf '\nrepo is at bkp-zq81x:/srv/pgbackrest/sierx\n' >> "$tmp/$target"; expect_red ".env value leak"; restore
  # a .env that only restates the example must not fail the gate
  cp "$tmp/.env.example" "$tmp/.env"
  if (scan "$tmp" >/dev/null); then echo "prove: .env == example: gate GREEN — OK"
  else echo "prove: .env == example: gate went red — FAIL"; fails=1; fi
  restore
  if (scan "$tmp" >/dev/null); then echo "prove: clean tree: gate GREEN — OK"
  else echo "prove: clean tree: gate went red — FAIL"; fails=1; fi
  return $fails
}

case ${1:-} in
  --prove) prove ;;
  "")      root=$(git rev-parse --show-toplevel)
           if scan "$root"; then echo "gate-notopology: OK (no topology in committable files)"; else exit 1; fi ;;
  *)       echo "usage: $0 [--prove]" >&2; exit 2 ;;
esac
