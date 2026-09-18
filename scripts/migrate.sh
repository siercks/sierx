#!/usr/bin/env bash
# migrate.sh — goose over /migrations, plain SQL up/down, no model diffing
# (SPEC §3.1, BUILD task 0.3). Subcommands: up | down | status | updown-up
#
# goose is a pinned release binary in bin/ (gitignored), fetched and sha256-
# verified by scripts/tool.sh. Override with GOOSE=/path/to/goose. See tool.sh
# for why these two tools are pinned binaries rather than `go tool` entries.
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
die() { echo "migrate.sh: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset (see .env.example)"

# shellcheck source=scripts/tool.sh
source scripts/tool.sh
GOOSE=${GOOSE:-$(tool_path goose)}

goose() { "$GOOSE" -dir migrations -table goose_db_version postgres "$DATABASE_URL" "$@"; }
sql()   { psql "$DATABASE_URL" -X -q -At -v ON_ERROR_STOP=1 -c "$1"; }

# "clean" after down-to 0: nothing in public but goose's own bookkeeping table,
# and none of our extensions.
assert_zero() {
  local tables exts
  tables=$(sql "select count(*) from pg_tables where schemaname='public' and tablename<>'goose_db_version'")
  exts=$(sql "select count(*) from pg_extension where extname in ('ltree','citext','pg_trgm')")
  [[ $tables == 0 && $exts == 0 ]] || die "not clean at zero: $tables tables, $exts extensions remain"
  echo "clean at zero: 0 tables, 0 extensions"
}
assert_applied() {
  local pending
  pending=$(goose status 2>&1 | grep -c 'Pending' || true)
  [[ $pending == 0 ]] || { goose status; die "$pending migration(s) pending after up"; }
  echo "all migrations applied: $(sql "select count(*) from goose_db_version where is_applied and version_id>0") versions"
}

case ${1:-} in
  up)        goose up ;;
  down)      goose down ;;
  status)    goose status ;;
  updown-up) echo "== up";      goose up;        assert_applied
             echo "== down-to 0"; goose down-to 0; assert_zero
             echo "== up again"; goose up;        assert_applied ;;
  *)         echo "usage: $0 up|down|status|updown-up" >&2; exit 2 ;;
esac
