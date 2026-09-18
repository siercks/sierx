#!/usr/bin/env bash
# schema.sh — schema snapshot and drift check (BUILD task 0.4).
#   snapshot : dump the live schema to docs/schema.sql (run deliberately)
#   diff     : migrate a scratch database from zero, dump it, diff against the
#              committed snapshot — catches a retroactively edited migration
#              and a hand-patched live database alike
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SNAPSHOT=docs/schema.sql
SCRATCH_DB=sierx_schemadiff

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
die() { echo "schema.sh: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset (see .env.example)"

# Deterministic schema-only dump: no owners, no privileges, goose's bookkeeping
# table excluded, and the lines pg_dump varies between runs removed —
# the \restrict/\unrestrict guard tokens are random, and the "Dumped from/by"
# version comments change on every minor upgrade.
dump() {
  pg_dump "$1" --schema-only --no-owner --no-privileges \
    --exclude-table=goose_db_version \
    | grep -Ev '^\\(un)?restrict |^-- Dumped (from|by) '
}

url_for_db() {   # url_for_db NAME -> DATABASE_URL with its database replaced
  local base=${DATABASE_URL%%\?*} query=
  [[ $DATABASE_URL == *\?* ]] && query="?${DATABASE_URL#*\?}"
  printf '%s/%s%s' "${base%/*}" "$1" "$query"
}
admin_url() { url_for_db postgres; }

# A scratch database must be created with the SAME encoding and locale as the
# real one (§4.4: the C collation is pinned because ltree's label set is
# locale-dependent). CREATE DATABASE with no options inherits template1, so on
# a cluster initdb'd without --encoding=UTF8 the scratch copy comes out
# SQL_ASCII and pg_dump emits a different client_encoding line — which looks
# exactly like schema drift and is not.
create_db_sql() {
  printf "CREATE DATABASE %s TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C'" "$1"
}

case ${1:-} in
  snapshot)
    dump "$DATABASE_URL" > "$SNAPSHOT"
    echo "schema-snapshot: wrote $SNAPSHOT ($(grep -c '^CREATE TABLE' "$SNAPSHOT") CREATE TABLE statements)"
    ;;
  diff)
    [[ -f $SNAPSHOT ]] || die "no $SNAPSHOT — run make schema-snapshot first"
    scratch=$(url_for_db "$SCRATCH_DB")
    psql "$(admin_url)" -X -q -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS $SCRATCH_DB" \
                                                  -c "$(create_db_sql "$SCRATCH_DB")"
    trap 'psql "$(admin_url)" -X -q -c "DROP DATABASE IF EXISTS $SCRATCH_DB" >/dev/null 2>&1 || true' EXIT
    DATABASE_URL=$scratch bash scripts/migrate.sh up >/dev/null 2>&1 || die "from-scratch migration failed"
    if diff -u "$SNAPSHOT" <(dump "$scratch"); then
      echo "schema-diff: from-scratch migration matches $SNAPSHOT"
    else
      die "from-scratch migration differs from $SNAPSHOT (above). Either a migration was edited after the snapshot or the snapshot is stale."
    fi
    ;;
  *) echo "usage: $0 snapshot|diff" >&2; exit 2 ;;
esac
