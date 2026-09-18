#!/usr/bin/env bash
# driver-pgdump.sh — logical backup driver (ADR-017, §14.2).
#
# The portable half of the pair: a `pg_dump -Fc` file is restorable by any
# later PostgreSQL with no pgBackRest installed and no matching major version,
# which is what makes it the escape hatch for §1.2 #7 rather than a second copy
# of the same idea. It needs no repository target, so it is green while
# ADR-010's deployment input is still outstanding.
#
# Verbs: init | backup | verify | restore-to <dsn> | retention | describe
# Configuration, from the environment (§14.4):
#   DATABASE_URL           the cluster to back up
#   SIERX_DUMP_DIR         where dumps land (default: ./.backups/pgdump)
#   SIERX_DUMP_KEEP        weekly dumps to keep (default 8, per §14.2)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

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

DUMP_DIR=${SIERX_DUMP_DIR:-.backups/pgdump}
KEEP=${SIERX_DUMP_KEEP:-8}

die() { echo "pgdump: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset"

verb_init() {
  mkdir -p "$DUMP_DIR"
  # Idempotent by construction: mkdir -p on an existing directory is a no-op,
  # and nothing else is needed for a logical dump target.
  [[ -d $DUMP_DIR ]] || die "could not create $DUMP_DIR"
}

verb_backup() {
  verb_init
  local stamp id path
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  id="pgdump-$stamp"
  path="$DUMP_DIR/$id.dump"
  # -Fc: custom format, the only one pg_restore can reorder and parallelise.
  # No --clean, no --create: restore-to takes an empty database, so a dump that
  # could drop objects in an existing one is a hazard with no upside.
  pg_dump "$DATABASE_URL" -Fc --no-owner --no-privileges -f "$path.partial"
  mv "$path.partial" "$path"
  # The id is opaque to callers (ADR-017) — they pass it back, they don't parse it.
  echo "$id"
}

latest_dump() {
  ls -1 "$DUMP_DIR"/*.dump 2>/dev/null | sort | tail -1
}

verb_verify() {
  local f
  f=$(latest_dump) || true
  [[ -n ${f:-} ]] || die "no dump to verify in $DUMP_DIR"
  # pg_restore --list reads the whole archive's table of contents; a truncated
  # or corrupt custom-format file fails here without touching a database.
  local entries
  entries=$(pg_restore --list "$f" | grep -c '^[0-9]') || die "archive $f is unreadable"
  [[ $entries -gt 0 ]] || die "archive $f contains no objects"
  echo "pgdump: verified $(basename "$f") ($entries archive entries)"
}

verb_restore_to() {
  local dsn=${1:-}
  [[ -n $dsn ]] || die "restore-to needs a target dsn"
  local f
  f=$(latest_dump) || true
  [[ -n ${f:-} ]] || die "no dump to restore from $DUMP_DIR"
  # --exit-on-error: a restore that reports success having skipped failures is
  # exactly the failure mode the restore test exists to catch.
  pg_restore --dbname "$dsn" --no-owner --no-privileges --exit-on-error "$f"
  echo "pgdump: restored $(basename "$f")"
}

verb_retention() {
  verb_init
  local -a files
  mapfile -t files < <(ls -1 "$DUMP_DIR"/*.dump 2>/dev/null | sort)
  local n=${#files[@]} removed=0
  if (( n > KEEP )); then
    local i
    for (( i = 0; i < n - KEEP; i++ )); do
      rm -f "${files[i]}"
      removed=$((removed + 1))
    done
  fi
  echo "pgdump: retention kept $(( n - removed )) of $n dump(s), limit $KEEP"
}

verb_describe() {
  local v
  v=$(pg_dump --version 2>/dev/null | awk '{print $3}') || v=unknown
  # No hostname or path that could name real topology (§3.7, gate-notopology).
  echo "pgdump driver; pg_dump $v; target dir $(basename "$DUMP_DIR"), keep $KEEP"
}

case ${1:-} in
  --has-verb)
    case ${2:-} in
      init|backup|verify|retention|describe) exit 0 ;;
      restore-to) exit 0 ;;
      *) exit 1 ;;
    esac ;;
  init)       verb_init ;;
  backup)     verb_backup ;;
  verify)     verb_verify ;;
  restore-to) shift; verb_restore_to "$@" ;;
  retention)  verb_retention ;;
  describe)   verb_describe ;;
  *)          die "usage: $0 init|backup|verify|restore-to <dsn>|retention|describe" ;;
esac
