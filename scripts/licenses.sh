#!/usr/bin/env bash
# licenses.sh — every dependency's license is on the §15.1 allowlist.
# BUILD task 0.13. Subcommands: check (default) | list | --prove
#
# Go side: classifies the LICENSE file of every module in vendor/. Vendoring is
# required by the task, and it makes this gate offline and auditable — the text
# being judged is in the tree, not fetched at gate time.
#
# Why not `go-licenses check`: it resolves licenses by downloading modules and
# carries a large dependency tree of its own, both of which this gate exists to
# constrain. The classifier below matches distinctive strings from each license
# text, which is the same method go-licenses' classifier uses, minus the
# network. Recorded as a deviation in PROGRESS.md.
#
# npm side: reads the `license` field of every installed package under
# node_modules. With no frontend yet there is nothing to read, which the gate
# reports rather than passing silently.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ALLOWLIST=.licenses-allowlist

# classify FILE -> prints an SPDX id, or UNKNOWN
classify() {
  local f=$1 t
  t=$(tr -d '\r' < "$f" | tr '\n' ' ' | tr -s ' ')
  case $t in
    *"GNU AFFERO GENERAL PUBLIC LICENSE"*)            echo AGPL-3.0 ;;
    *"GNU LESSER GENERAL PUBLIC LICENSE"*"Version 2.1"*) echo LGPL-2.1 ;;
    *"GNU LESSER GENERAL PUBLIC LICENSE"*)            echo LGPL-3.0 ;;
    *"GNU GENERAL PUBLIC LICENSE"*"Version 2"*)       echo GPL-2.0 ;;
    *"GNU GENERAL PUBLIC LICENSE"*)                   echo GPL-3.0 ;;
    *"Mozilla Public License"*)                       echo MPL-2.0 ;;
    *"Server Side Public License"*)                   echo SSPL-1.0 ;;
    *"Business Source License"*)                      echo BSL-1.1 ;;
    *"Elastic License 2.0"*)                          echo Elastic-2.0 ;;
    *"Commons Clause"*)                               echo Commons-Clause ;;
    *"Apache License"*"Version 2.0"*)                 echo Apache-2.0 ;;
    *"Permission to use, copy, modify, and"*"distribute this software"*) echo ISC ;;
    *"Permission is hereby granted, free of charge"*) echo MIT ;;
    *"PostgreSQL License"*)                           echo PostgreSQL ;;
    *"This is free and unencumbered software released into the public domain"*) echo Unlicense ;;
    *"CC0 1.0 Universal"*)                            echo CC0-1.0 ;;
    *"altered source versions must be plainly marked"*) echo Zlib ;;
    # BSD: the 3-clause text adds the no-endorsement clause; check it first.
    *"Neither the name of"*"may be used to endorse"*) echo BSD-3-Clause ;;
    *"Redistributions in binary form must reproduce"*) echo BSD-2-Clause ;;
    *)                                                echo UNKNOWN ;;
  esac
}

load_allowlist() {
  ALLOWED=(); BLOCKED=(); declare -gA RESOLVED=(); declare -gA RESOLVE_REASON=()
  local verb a b rest
  while read -r verb a b rest; do
    [[ -z ${verb:-} || $verb == \#* ]] && continue
    case $verb in
      allow) ALLOWED+=("$a") ;;
      block) BLOCKED+=("$a") ;;
      resolve)
        [[ $rest == --* ]] || { echo "licenses.sh: resolve $a has no '-- reason'" >&2; exit 2; }
        RESOLVED[$a]=$b; RESOLVE_REASON[$a]=${rest#-- } ;;
      *) echo "licenses.sh: unknown directive '$verb' in $ALLOWLIST" >&2; exit 2 ;;
    esac
  done < "$ALLOWLIST"
}

in_list() { local n=$1; shift; local x; for x in "$@"; do [[ $x == "$n" ]] && return 0; done; return 1; }

# find_license_file DIR -> path, or empty
find_license_file() {
  local d=$1 name
  for name in LICENSE LICENSE.txt LICENSE.md LICENCE COPYING LICENSE-MIT LICENSE.BSD NOTICE; do
    [[ -f "$d/$name" ]] && { echo "$d/$name"; return; }
  done
  # Some modules keep it one level down (a vendored monorepo subpackage).
  find "$d" -maxdepth 2 -iname 'license*' -o -maxdepth 2 -iname 'copying*' 2>/dev/null | head -1
}

# go_modules ROOT -> "module<TAB>dir" for every vendored module
go_modules() {
  local root=$1
  [[ -f $root/vendor/modules.txt ]] || return 0
  awk '/^# /{print $2}' "$root/vendor/modules.txt" | sort -u | while read -r mod; do
    [[ -d "$root/vendor/$mod" ]] && printf '%s\t%s\n' "$mod" "$root/vendor/$mod"
  done
}

check() {
  local root=$1 rc=0 mod dir file spdx n=0
  load_allowlist

  if [[ ! -f $root/vendor/modules.txt ]]; then
    echo "licenses.sh: no vendor/ directory — run: go mod vendor" >&2
    return 1
  fi

  while IFS=$'\t' read -r mod dir; do
    [[ -z $mod ]] && continue
    n=$((n + 1))
    file=$(find_license_file "$dir")
    if [[ -z $file ]]; then
      echo "MISSING  $mod — no license file in the vendored tree"
      rc=1
      continue
    fi
    spdx=$(classify "$file")
    if [[ -n ${RESOLVED[$mod]:-} ]]; then
      printf 'RESOLVED %-55s %s -- %s\n' "$mod" "${RESOLVED[$mod]}" "${RESOLVE_REASON[$mod]}"
      spdx=${RESOLVED[$mod]}
    fi
    if in_list "$spdx" "${BLOCKED[@]}"; then
      echo "BLOCKED  $mod — $spdx (SPEC §15.1)"
      rc=1
    elif in_list "$spdx" "${ALLOWED[@]}"; then
      printf 'ok       %-55s %s\n' "$mod" "$spdx"
    else
      echo "UNKNOWN  $mod — could not classify $file; add a resolve line or replace the dependency"
      rc=1
    fi
  done < <(go_modules "$root")

  echo "licenses.sh: $n Go module(s) checked"

  if [[ -f $root/web/package.json ]]; then
    (cd "$root/web" && node scripts/licenses.mjs) || rc=1
  elif [[ -f web/package.json ]]; then
    # Scratch Go-license proofs still validate the actual frontend inventory.
    (cd web && node scripts/licenses.mjs) || rc=1
  else
    echo "Missing frontend manifest/inventory" >&2; rc=1
  fi

  if [[ $rc -eq 0 ]]; then
    echo "gate-license: OK (every dependency on the §15.1 allowlist)"
  fi
  return $rc
}

prove() {
  local src tmp fails=0
  src=$(git rev-parse --show-toplevel)
  tmp=$(mktemp -d); trap "rm -rf '$tmp'" EXIT
  mkdir -p "$tmp/vendor"
  cp "$src/$ALLOWLIST" "$tmp/"
  cp "$src/vendor/modules.txt" "$tmp/vendor/" 2>/dev/null || {
    echo "prove: no vendor/ to copy — run go mod vendor first" >&2; return 1
  }
  cp -r "$src/vendor/." "$tmp/vendor/"
  # git rev-parse inside check() is not used, but keep the scratch tree honest.
  (cd "$tmp" && git init -q && git add -A 2>/dev/null || true)

  plant() {   # plant MODULE SPDX_TEXT_FILE_CONTENT
    local mod=$1 text=$2
    mkdir -p "$tmp/vendor/$mod"
    printf '%s\n' "$text" > "$tmp/vendor/$mod/LICENSE"
    printf 'package x\n' > "$tmp/vendor/$mod/x.go"
    printf '# %s\n## explicit; go 1.27\n%s\n' "$mod" "$mod" >> "$tmp/vendor/modules.txt"
  }
  unplant() {
    local mod=$1
    rm -rf "$tmp/vendor/$mod"
    grep -v "^${mod}$" "$tmp/vendor/modules.txt" | grep -v "^# ${mod}$" > "$tmp/modules.tmp"
    mv "$tmp/modules.tmp" "$tmp/vendor/modules.txt"
  }
  expect_red() {
    if (check "$tmp" >/dev/null 2>&1); then echo "prove: $1: gate stayed GREEN — FAIL"; fails=1
    else echo "prove: $1: gate went red — OK"; fi
  }

  # The negative test BUILD task 0.13 asks for by name.
  plant example.com/agpllib "GNU AFFERO GENERAL PUBLIC LICENSE Version 3, 19 November 2007"
  expect_red "AGPL-3.0 module"; unplant example.com/agpllib

  # MPL is not GPL-family but is blocked: this is the check that kept
  # pgregory.net/rapid out of task 0.10.
  plant example.com/mpllib "Mozilla Public License Version 2.0 1. Definitions"
  expect_red "MPL-2.0 module"; unplant example.com/mpllib

  # Source-available licences that a "no GPL family" rule would miss.
  plant example.com/ssplthing "Server Side Public License VERSION 1, OCTOBER 16, 2018"
  expect_red "SSPL-1.0 module"; unplant example.com/ssplthing
  plant example.com/bsllib "Business Source License 1.1 Parameters"
  expect_red "BSL-1.1 module"; unplant example.com/bsllib

  plant example.com/mystery "Copyright somebody. You may do as you please, probably."
  expect_red "unclassifiable license"; unplant example.com/mystery

  mkdir -p "$tmp/vendor/example.com/nolicense"
  printf 'package x\n' > "$tmp/vendor/example.com/nolicense/x.go"
  printf '# example.com/nolicense\n## explicit; go 1.27\nexample.com/nolicense\n' >> "$tmp/vendor/modules.txt"
  expect_red "module with no license file"
  unplant example.com/nolicense

  if (check "$tmp" >/dev/null 2>&1); then echo "prove: clean tree: gate GREEN — OK"
  else echo "prove: clean tree: gate went red — FAIL"; fails=1; fi
  return $fails
}

case ${1:-check} in
  --library) : ;; # Shared classifier and allowlist for the SBOM generator.
  check)   check "$(git rev-parse --show-toplevel)" ;;
  list)    load_allowlist
           while IFS=$'\t' read -r mod dir; do
             [[ -z $mod ]] && continue
             f=$(find_license_file "$dir")
             printf '%-55s %s\n' "$mod" "$([[ -n $f ]] && classify "$f" || echo MISSING)"
           done < <(go_modules "$(git rev-parse --show-toplevel)") ;;
  --prove) prove ;;
  *)       echo "usage: $0 [check|list|--prove]" >&2; exit 2 ;;
esac
