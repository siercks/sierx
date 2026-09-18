#!/usr/bin/env bash
# migrate.sh — goose over /migrations, plain SQL up/down, no model diffing
# (SPEC §3.1, BUILD task 0.3). Subcommands: up | down | status | updown-up
#
# goose is a pinned release binary in bin/ (gitignored), fetched on first use
# and verified against its published sha256. Override with GOOSE=/path/to/goose.
# When go.mod acquires its dependencies (task 0.8), switch this to
# `go tool goose` so the pin lives in go.mod and the license gate sees it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

GOOSE_VERSION=v3.28.0
declare -A GOOSE_SHA=(
  [linux_x86_64]=ab073515b78ef345f64f018c0d79aa7db50106806efc686dda7181253765ae13
  [linux_arm64]=3968855c11b4093af271c5226909789ea294468f6e50203d738b7504995b6247
)

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

ensure_goose() {
  if [[ -n ${GOOSE:-} ]]; then return 0; fi
  GOOSE=bin/goose
  if [[ -x $GOOSE ]] && [[ $("$GOOSE" --version 2>/dev/null) == *"$GOOSE_VERSION"* ]]; then return 0; fi
  local arch; arch=$(uname -m)
  case $arch in x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=arm64 ;; *) die "no goose pin for arch $arch" ;; esac
  local key=linux_$arch url=https://github.com/pressly/goose/releases/download/$GOOSE_VERSION/goose_linux_$arch
  mkdir -p bin
  echo "fetching goose $GOOSE_VERSION ($key) ..."
  curl -fsSL -o "$GOOSE.tmp" "$url"
  echo "${GOOSE_SHA[$key]}  $GOOSE.tmp" | sha256sum -c --quiet - || die "goose checksum mismatch — refusing to run it"
  chmod +x "$GOOSE.tmp" && mv "$GOOSE.tmp" "$GOOSE"
}
ensure_goose

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
