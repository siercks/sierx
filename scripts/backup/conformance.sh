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
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

# Environment wins; .env fills the gaps. The assignment is an `if` and not
# `[[ ... ]] && export` on purpose: under `set -e` the && form returns 1 the
# first time a variable is ALREADY set, which killed the script silently with
# no output and exit 1 — invisible whenever .env happened to define something
# the caller had already exported.
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

die() { echo "conformance: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset"

SCRATCH=${SIERX_RESTORE_SCRATCH_DB:-sierx_restore_check_$(date +%s)_$$}
[[ $SCRATCH =~ ^sierx_restore_check_[a-z0-9_]+$ && ${#SCRATCH} -le 63 ]] || die 'scratch database must use the sierx_restore_check_ prefix and safe lowercase characters'
[[ ${DATABASE_URL%%\?*} != */"$SCRATCH" ]] || die 'scratch database cannot be the source'

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
  local t
  for t in "${TABLES[@]}" seq_counter; do
    psql "$dsn" -X -q -At -v ON_ERROR_STOP=1 -c "SELECT '$t:' || coalesce(md5(string_agg(md5(row_to_json(r)::text), '' ORDER BY md5(row_to_json(r)::text))), 'empty') FROM $t r"
  done | sha256sum | cut -d' ' -f1
}

event_max() {
  psql "$1" -X -q -At -v ON_ERROR_STOP=1 -c "SELECT coalesce(max(seq),0) FROM change_event"
}

# A restore comparison over an empty database passes trivially: equal row
# counts of zero, equal empty checksums, zero rollups to disagree. Refuse
# rather than report OK — BUILD §0.4's "a green claim without evidence is
# treated as red" applies to the harness too.
assert_source_not_empty() {
  local n
  n=$(psql "$DATABASE_URL" -X -q -At -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM item") \
    || die "cannot read the source database"
  [[ ${n:-0} -gt 0 ]] \
    || die "the source database has no items — run 'make seed' first; restoring nothing proves nothing"
  echo "source: $n item(s)"
}

run_one() {
  local d=$1 scratch_dsn id
  scratch_dsn=$(url_for_db "$SCRATCH")
  echo "=== conformance: $d"
  assert_source_not_empty
  echo "--- describe"
  bash scripts/backup/driver.sh "$d" describe

  echo "--- contract"
  # Show the output on failure. Swallowing it left the operator with "failed
  # the contract check" and nothing to act on, when the check knows exactly
  # which verb failed and why.
  if ! contract_out=$(bash scripts/backup/driver.sh --contract "$d" 2>&1); then
    printf '%s\n' "$contract_out"
    die "$d failed the contract check (above)"
  fi
  echo "contract: OK"

  echo "--- backup"
  id=$(bash scripts/backup/driver.sh "$d" backup) || die "$d backup failed"
  [[ -n ${id//[[:space:]]/} ]] || die "$d backup printed no id (ADR-017)"
  echo "backup id: $id"

  echo "--- verify"
  bash scripts/backup/driver.sh "$d" verify || die "$d verify failed"

  echo "--- restore-to scratch"
  psql "$admin_url" -X -q -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE $SCRATCH TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C'" >/dev/null
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
  local counters_source counters_restored
  counters_source=$(psql "$DATABASE_URL" -X -q -At -v ON_ERROR_STOP=1 -c 'SELECT workspace_id,value FROM seq_counter ORDER BY workspace_id')
  counters_restored=$(psql "$scratch_dsn" -X -q -At -v ON_ERROR_STOP=1 -c 'SELECT workspace_id,value FROM seq_counter ORDER BY workspace_id')
  [[ $counters_source == "$counters_restored" ]] || die 'restored sequence counters differ'
  echo '  per-workspace sequence counters match'


  echo "--- rollup --verify on the restored copy (ADR-005 control 2)"
  DATABASE_URL=$scratch_dsn bash scripts/sierxctl.sh rollup --verify \
    || die "$d restored copy has wrong rollups"

  if [[ -n ${SIERX_RESTORE_APP_CHECK:-} ]]; then
    [[ -f $SIERX_RESTORE_APP_CHECK ]] || die 'restore application check script is missing'
    DATABASE_URL=$scratch_dsn bash "$SIERX_RESTORE_APP_CHECK" || die 'application access to restored data failed'
    echo '  restored application check passed'
  else
    echo '  restored application access: NOT CHECKED (required separately before cutover)'
  fi

  psql "$admin_url" -X -q -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  echo "=== conformance: $d PASSED"
}

drivers=$(bash scripts/backup/driver.sh --list)
[[ -n $drivers ]] || die "no drivers configured"
for d in $drivers; do
  run_one "$d"
done
echo "backup-conformance: OK for: $drivers"
