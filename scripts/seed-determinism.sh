#!/usr/bin/env bash
# seed-determinism.sh — the same --seed produces the same workspace (task 0.9).
#
# Seeds twice into two scratch databases and compares the content checksum from
# SeedChecksum. Two databases rather than two workspaces in one, so the second
# run cannot be influenced by the first (key counters, rank space, slug).
#
# The checksum deliberately excludes ids and timestamps: uuidv7 embeds the
# clock, so those differ between runs by design. What must match is the
# content — titles, statuses, types, points, dates, bodies, fields, depths.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SEED=${SEED:-7}
ITEMS=${ITEMS:-1200}
PROJECTS=${PROJECTS:-5}
DEPTH=${DEPTH:-6}

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
die() { echo "seed-determinism: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset"

url_for_db() {
  local base=${DATABASE_URL%%\?*} query=
  [[ $DATABASE_URL == *\?* ]] && query="?${DATABASE_URL#*\?}"
  printf '%s/%s%s' "${base%/*}" "$1" "$query"
}
admin_url=$(url_for_db postgres)

run_one() {   # run_one DBNAME -> prints the checksum
  local db=$1 url
  url=$(url_for_db "$db")
  psql "$admin_url" -X -q -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS $db" \
    -c "CREATE DATABASE $db TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C'" >/dev/null
  DATABASE_URL=$url bash scripts/migrate.sh up >/dev/null 2>&1 \
    || die "migrating $db failed"
  DATABASE_URL=$url bash scripts/sierxctl.sh seed \
    --seed "$SEED" --items "$ITEMS" --projects "$PROJECTS" --max-depth "$DEPTH" \
    | sed -n 's/^seed: checksum=//p'
}

cleanup() {
  psql "$admin_url" -X -q -c "DROP DATABASE IF EXISTS sierx_seed_a" >/dev/null 2>&1 || true
  psql "$admin_url" -X -q -c "DROP DATABASE IF EXISTS sierx_seed_b" >/dev/null 2>&1 || true
}
trap cleanup EXIT

a=$(run_one sierx_seed_a)
b=$(run_one sierx_seed_b)
[[ -n $a && -n $b ]] || die "a seed run produced no checksum"

echo "run A: $a"
echo "run B: $b"
if [[ $a != "$b" ]]; then
  die "same --seed produced different content — the generator is not deterministic"
fi

# A different seed must produce a different workspace, or the checksum is not
# actually measuring anything.
SEED=$((SEED + 1))
c=$(run_one sierx_seed_a)
echo "run C (--seed $SEED): $c"
[[ $c != "$a" ]] || die "a different --seed produced identical content — the seed is being ignored"

echo "seed-determinism: OK (same seed identical, different seed differs)"
