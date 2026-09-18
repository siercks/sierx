#!/usr/bin/env bash
# conformance.sh — the shared assertion set every driver must pass (ADR-017).
# A driver that has not passed this is not a driver.
#
#   init -> backup -> verify -> restore-to a scratch database
#        -> per-table row counts -> content checksum
#        -> sierxctl rollup --verify on the restored copy
#
# The rollup check is ADR-005's control 2 applied to a restored copy: a restore
# that brings back rows but loses the derived rollups would otherwise look
# perfectly healthy, because nothing recomputes them on read (A.5).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

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
    [[ -z ${!key+x} ]] && export "$key=$val"
  done < "$file"
}
load_dotenv .env

die() { echo "conformance: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset"

SCRATCH=${SIERX_RESTORE_SCRATCH_DB:-sierx_restore_check}

url_for_db() {
  local base=${DATABASE_URL%%\?*} query=
  [[ $DATABASE_URL == *\?* ]] && query="?${DATABASE_URL#*\?}"
  printf '%s/%s%s' "${base%/*}" "$1" "$query"
}
admin_url=$(url_for_db postgres)

# The tables whose row counts must survive a restore. Every table in SPEC §4
# that holds data; partitions are covered through their parent.
TABLES=(workspace user_account membership session project project_config status
        item_type config_status config_type config_transition field_def item
        item_rollup item_link change_event sprint sprint_item comment saved_view)

row_counts() {   # row_counts DSN -> "table<TAB>count" per line
  local dsn=$1 t
  for t in "${TABLES[@]}"; do
    printf '%s\t%s\n' "$t" "$(psql "$dsn" -X -q -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM $t")"
  done
}

# content_checksum hashes the data that must survive a restore byte for byte.
# Ordered explicitly: a checksum over an unordered result is a checksum over
# whatever order the planner chose today.
content_checksum() {
  local dsn=$1
  psql "$dsn" -X -q -At -v ON_ERROR_STOP=1 <<'SQL'
SELECT md5(string_agg(sig, '|' ORDER BY sig)) FROM (
  SELECT i.key || ':' || i.title || ':' || i.path::text || ':' ||
         coalesce(i.points::text,'-') || ':' || i.status_id::text || ':' ||
         i.version::text || ':' || i.change_seq::text || ':' ||
         coalesce(r.descendant_count::text,'-') || ':' ||
         coalesce(r.done_count::text,'-') AS sig
    FROM item i LEFT JOIN item_rollup r ON r.item_id = i.id
) x;
SQL
}

event_max() {
  psql "$1" -X -q -At -v ON_ERROR_STOP=1 -c "SELECT coalesce(max(seq),0) FROM change_event"
}

run_one() {
  local d=$1 scratch_dsn id
  scratch_dsn=$(url_for_db "$SCRATCH")
  echo "=== conformance: $d"
  echo "--- describe"
  bash scripts/backup/driver.sh "$d" describe

  echo "--- contract"
  bash scripts/backup/driver.sh --contract "$d" >/dev/null || die "$d failed the contract check"
  echo "contract: OK"

  echo "--- backup"
  id=$(bash scripts/backup/driver.sh "$d" backup) || die "$d backup failed"
  [[ -n ${id//[[:space:]]/} ]] || die "$d backup printed no id (ADR-017)"
  echo "backup id: $id"

  echo "--- verify"
  bash scripts/backup/driver.sh "$d" verify || die "$d verify failed"

  echo "--- restore-to scratch"
  psql "$admin_url" -X -q -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS $SCRATCH" -c "CREATE DATABASE $SCRATCH" >/dev/null
  bash scripts/backup/driver.sh "$d" restore-to "$scratch_dsn" || die "$d restore-to failed"

  echo "--- row counts"
  local src dst diff_found=0
  src=$(row_counts "$DATABASE_URL")
  dst=$(row_counts "$scratch_dsn")
  while IFS=$'\t' read -r t n; do
    local m
    m=$(grep -P "^$t\t" <<<"$dst" | cut -f2)
    if [[ $n != "$m" ]]; then
      echo "  MISMATCH $t: source $n, restored ${m:-missing}"
      diff_found=1
    fi
  done <<<"$src"
  [[ $diff_found -eq 0 ]] || die "$d restored row counts differ from source"
  echo "  $(wc -l <<<"$src") tables, all counts equal"

  echo "--- content checksum"
  local csrc cdst
  csrc=$(content_checksum "$DATABASE_URL")
  cdst=$(content_checksum "$scratch_dsn")
  [[ $csrc == "$cdst" ]] || die "$d content checksum differs: source $csrc, restored $cdst"
  echo "  $csrc"

  echo "--- event sequence high-water mark"
  local esrc edst
  esrc=$(event_max "$DATABASE_URL"); edst=$(event_max "$scratch_dsn")
  [[ $esrc == "$edst" ]] || die "$d restored max(change_event.seq) is $edst, source is $esrc"
  echo "  max(seq) = $esrc"

  echo "--- rollup --verify on the restored copy (ADR-005 control 2)"
  DATABASE_URL=$scratch_dsn bash scripts/sierxctl.sh rollup --verify \
    || die "$d restored copy has wrong rollups"

  psql "$admin_url" -X -q -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  echo "=== conformance: $d PASSED"
}

drivers=$(bash scripts/backup/driver.sh --list)
[[ -n $drivers ]] || die "no drivers configured"
for d in $drivers; do
  run_one "$d"
done
echo "backup-conformance: OK for: $drivers"
