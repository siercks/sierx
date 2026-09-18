#!/usr/bin/env bash
# gate-nobackupleak — the backup abstraction has no leaks (ADR-017).
#
# Fails on a literal `pgbackrest`, `pg_dump`, `pg_restore` or `wal-g` outside
# scripts/backup/driver-*.sh and deploy/pgbackrest/. Same shape as
# gate-nodirect, for the same reason: an abstraction with one leak is not an
# abstraction. In particular no `make` target may name a tool — a Makefile that
# says pg_dump has already decided which driver you use.
#
# `--prove` plants a leak in a scratch copy and asserts the gate goes red.
set -euo pipefail

TOOLS=(pgbackrest pg_dump pg_restore wal-g)
# Allowlist, with the reason each entry is here. ADR-017 names the first two;
# the rest are recorded deliberately rather than widened later to make a task
# pass.
ALLOW=(
  'scripts/backup/driver-[a-z]*\.sh'   # the drivers, which must name their tool
  'deploy/pgbackrest/'                 # the pgBackRest config template and runbook
  'scripts/gate-nobackupleak\.sh'      # this script carries the patterns
  'docs/'                              # SPEC, BUILD and the ADRs discuss the tools
  'PROGRESS\.md'                       # describe output is pasted here (ADR-017)
  '\.env\.example'                     # SIERX_BACKUP_DRIVERS and PGBACKREST_* are
                                       # how a driver is SELECTED; naming them in
                                       # configuration is ADR-017's mechanism, not a
                                       # leak. BUILD Appendix B fixes these names.
  'vendor/'                            # third-party source; pgx's own tooling mentions
                                       # pg_dump and we do not edit it
  'scripts/schema\.sh'                 # takes a --schema-only structural snapshot for
                                       # drift detection (task 0.4). No data, no
                                       # restore path, not a backup: it would still be
                                       # needed if every backup driver were replaced.
)

scan() {
  local root=$1 rc=0 files tool hits entry
  files=$(cd "$root" && git ls-files --cached --others --exclude-standard -z | tr '\0' '\n')
  for entry in "${ALLOW[@]}"; do
    files=$(printf '%s\n' "$files" | grep -Ev "^${entry}" || true)
  done
  [[ -z $files ]] && { echo "gate-nobackupleak: no files outside the allowlist to scan"; return 0; }

  for tool in "${TOOLS[@]}"; do
    hits=$(cd "$root" && printf '%s\n' "$files" | xargs -d '\n' grep -nIF -- "$tool" 2>/dev/null || true)
    if [[ -n $hits ]]; then
      echo "Backup tool '${tool}' named outside the drivers:"
      sed 's/^/  /' <<<"$hits"
      rc=1
    fi
  done
  return $rc
}

prove() {
  local src tmp fails=0
  src=$(git rev-parse --show-toplevel)
  tmp=$(mktemp -d); trap "rm -rf '$tmp'" EXIT
  (cd "$src" && git ls-files --cached --others --exclude-standard -z | xargs -0 cp --parents -t "$tmp")
  (cd "$tmp" && git init -q && git add -A)

  expect_red() {
    if (scan "$tmp" >/dev/null); then echo "prove: $1: gate stayed GREEN — FAIL"; fails=1
    else echo "prove: $1: gate went red — OK"; fi
  }

  printf '\nrestore-test-hack:\n\tpg_restore --dbname $$DSN latest.dump\n' >> "$tmp/Makefile"
  expect_red "pg_restore in the Makefile"
  (cd "$tmp" && git checkout -q -- Makefile)

  printf '\nbackup-now:\n\tpgbackrest --stanza=sierx backup\n' >> "$tmp/Makefile"
  expect_red "pgbackrest in a make target"
  (cd "$tmp" && git checkout -q -- Makefile)

  printf 'package api\n\n// TODO: shell out to pg_dump here\n' > "$tmp/internal/leak.go"
  expect_red "pg_dump named in Go source"
  rm -f "$tmp/internal/leak.go"

  printf '#!/bin/sh\nwal-g backup-push\n' > "$tmp/scripts/nightly.sh"
  expect_red "wal-g in a non-driver script"
  rm -f "$tmp/scripts/nightly.sh"

  if (scan "$tmp" >/dev/null); then echo "prove: clean tree: gate GREEN — OK"
  else echo "prove: clean tree: gate went red — FAIL"; fails=1; fi
  return $fails
}

case ${1:-} in
  --prove) prove ;;
  "")      if scan "$(git rev-parse --show-toplevel)"; then
             echo "gate-nobackupleak: OK (no backup tool named outside the drivers)"
           else exit 1; fi ;;
  *)       echo "usage: $0 [--prove]" >&2; exit 2 ;;
esac
