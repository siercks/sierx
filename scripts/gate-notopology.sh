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
#   3. Any value the operator has set in the untracked .env that does not
#      already appear somewhere in the committed .env.example. The example file
#      is public by construction, so every token in it — including the members
#      of an enumerated choice such as the driver list — is
#      already world-readable and cannot leak. What must never appear is what
#      the human filled in on top of it: a real host, path, bucket or secret.
#      The whole value is matched, verbatim; values shorter than 4 characters
#      are skipped as noise.
#
#      Comparing against the example's value for the SAME KEY is not enough:
#      narrowing a two-item enumerated list to one of its members differs from
#      the default while being no more secret than it, and the gate then
#      reported every mention of that member in the tree as a leak. That is a
#      real failure from a real dev host, not a hypothetical.
#
# `--prove` runs the gate against a scratch copy with each violation planted
# in turn and asserts the gate goes red, then asserts a clean copy passes.
# Task 0.12's prove-gates.sh discovers gate-* targets from the Makefile and
# invokes `scripts/<gate>.sh --prove`; this is the convention it will read.
#
# Excluded from the scan: this script (it carries the patterns).
set -euo pipefail
for required_tool in git grep tr sed awk xargs; do
  command -v "$required_tool" >/dev/null || { echo "gate prerequisite missing: $required_tool" >&2; exit 2; }
done

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
  # vendor/ is third-party source, not this project's configuration: a
  # dependency's own .gitignore mentioning mise.local.toml is not a topology
  # leak, and we do not edit those files. The gate exists to stop OUR files
  # naming real hosts.
  files=$(cd "$root" && git ls-files --cached --others --exclude-standard -z \
            | tr '\0' '\n' | grep -vx "$SELF" | grep -v '^\.env$' \
            | grep -v '^vendor/' || true)
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
    local example_text key val
    example_text=$(cat "$root/.env.example" 2>/dev/null || true)
    while IFS=$'\t' read -r key val; do
      [[ -z $val || ${#val} -lt 4 ]] && continue
      # Already published in .env.example, anywhere in the file.
      [[ $example_text == *"$val"* ]] && continue
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
  # A fixture value, not a real one. Deliberately does not name a backup tool:
  # gate-nobackupleak scans this file too.
  printf 'SIERX_DUMP_DIR=bkp-zq81x:/srv/backups/sierx\n' > "$tmp/.env"
  printf '\nrepo is at bkp-zq81x:/srv/backups/sierx\n' >> "$tmp/$target"; expect_red ".env value leak"; restore
  # Narrowing an enumerated value is not a secret: selecting one member of the
  # driver list differs from the example's default, but every token is already
  # published there. This is the false positive that failed a real dev host.
  # The value is read from the example rather than written out, so this file
  # stays clean under gate-nobackupleak.
  awk -F= '/^SIERX_BACKUP_DRIVERS=/{split($2,a,","); print "SIERX_BACKUP_DRIVERS=" a[2]; exit}' \
    "$tmp/.env.example" > "$tmp/.env"
  if (scan "$tmp" >/dev/null); then echo "prove: narrowed enumerated value: gate GREEN — OK"
  else echo "prove: narrowed enumerated value: gate went red — FAIL"; fails=1; fi
  restore

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
