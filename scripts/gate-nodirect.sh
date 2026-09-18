#!/usr/bin/env bash
# gate-nodirect — the governed tables are written through store.Mutate and
# nowhere else (BUILD task 0.8 step 5, ADR-001).
#
# Governed tables: item, item_link, sprint_item, comment. Matched on WORD
# BOUNDARIES: a bare `item` pattern would trip on item_type, item_link and
# item_rollup and the gate would be permanently red, so every table is matched
# as \bNAME\b.
#
# Allowlist, with the reason each entry is here. Nothing is added to this list
# to make a later task pass: if a task needs to write a governed table from
# outside internal/store, that task is wrong (BUILD task 0.8 "Do not").
#
#   migrations/         DDL, and the invariant triggers of task 0.5
#   test/sql/           task 0.5 attempts forbidden writes on purpose
#   internal/store/     the single write path itself, including its generated code
#   docs/               SPEC and BUILD quote the DDL
#   scripts/gate-nodirect.sh  this script carries the patterns
#
# `--prove` plants a violation in a scratch copy and asserts the gate goes red;
# prove-gates.sh (task 0.12) discovers gate-* targets and calls this.
set -euo pipefail

TABLES=(item item_link sprint_item comment)
ALLOW=(
  migrations/
  test/sql/
  internal/store/
  docs/
  scripts/gate-nodirect.sh
)

# A write is one of these SQL verbs aimed at a governed table. Case-insensitive,
# and tolerant of the whitespace and newlines a formatted query uses.
verbs='INSERT[[:space:]]+INTO|UPDATE|DELETE[[:space:]]+FROM|TRUNCATE'

scan() {
  local root=$1 rc=0 files hits table
  files=$(cd "$root" && git ls-files --cached --others --exclude-standard -z | tr '\0' '\n')
  for entry in "${ALLOW[@]}"; do
    files=$(printf '%s\n' "$files" | grep -v "^${entry}" || true)
  done
  # Only source files can contain a query; keeping the list narrow stops a
  # README sentence from failing the build.
  files=$(printf '%s\n' "$files" | grep -E '\.(go|sql|sh|ts|tsx|js|jsx|py)$' || true)
  [[ -z $files ]] && { echo "gate-nodirect: no files outside the allowlist to scan"; return 0; }

  for table in "${TABLES[@]}"; do
    hits=$(cd "$root" && printf '%s\n' "$files" | xargs -d '\n' grep -nIEi \
      "(${verbs})[[:space:]]+(ONLY[[:space:]]+)?\"?\b${table}\b\"?" -- 2>/dev/null || true)
    if [[ -n $hits ]]; then
      echo "Write to governed table '${table}' outside internal/store:"
      sed 's/^/  /' <<<"$hits"
      rc=1
    fi
  done
  return $rc
}

prove() {
  local src tmp fails=0 target=internal/api_probe.go
  src=$(git rev-parse --show-toplevel)
  tmp=$(mktemp -d); trap "rm -rf '$tmp'" EXIT
  (cd "$src" && git ls-files --cached --others --exclude-standard -z | xargs -0 cp --parents -t "$tmp")
  # scan() enumerates files with git, so the scratch copy needs to be a repo.
  (cd "$tmp" && git init -q && git add -A)
  mkdir -p "$tmp/internal"

  expect_red() {
    if (scan "$tmp" >/dev/null); then echo "prove: $1: gate stayed GREEN — FAIL"; fails=1
    else echo "prove: $1: gate went red — OK"; fi
    rm -f "$tmp/$target"
  }

  printf 'package api\n\nconst q = `INSERT INTO item (title) VALUES ($1)`\n' > "$tmp/$target"
  expect_red "INSERT INTO item from internal/api"
  printf 'package api\n\nconst q = `update  item\n  set title = $1`\n' > "$tmp/$target"
  expect_red "lowercase multi-line UPDATE item"
  printf 'package api\n\nconst q = `DELETE FROM comment WHERE id = $1`\n' > "$tmp/$target"
  expect_red "DELETE FROM comment"
  printf 'package api\n\nconst q = `INSERT INTO sprint_item (sprint_id) VALUES ($1)`\n' > "$tmp/$target"
  expect_red "INSERT INTO sprint_item"
  printf 'package api\n\nconst q = `TRUNCATE item_link`\n' > "$tmp/$target"
  expect_red "TRUNCATE item_link"

  # Must NOT trip: the non-governed tables whose names contain a governed one.
  printf 'package api\n\nconst (\n a = `INSERT INTO item_type (key) VALUES ($1)`\n b = `UPDATE item_rollup SET done_count = 0`\n c = `SELECT * FROM item WHERE id = $1`\n)\n' > "$tmp/$target"
  if (scan "$tmp" >/dev/null); then
    echo "prove: item_type/item_rollup writes and a plain SELECT stay green — OK"
  else
    echo "prove: item_type/item_rollup writes and a plain SELECT: gate went red — FAIL"; fails=1
  fi
  rm -f "$tmp/$target"

  if (scan "$tmp" >/dev/null); then echo "prove: clean tree: gate GREEN — OK"
  else echo "prove: clean tree: gate went red — FAIL"; fails=1; fi
  return $fails
}

case ${1:-} in
  --prove) prove ;;
  "")      if scan "$(git rev-parse --show-toplevel)"; then
             echo "gate-nodirect: OK (governed tables written only through internal/store)"
           else exit 1; fi ;;
  *)       echo "usage: $0 [--prove]" >&2; exit 2 ;;
esac
