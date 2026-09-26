#!/usr/bin/env bash
# driver-pgbackrest.sh — physical backup driver (ADR-017, §14.2).
#
# ⚠ NOT YET CONFORMANCE-TESTED. Per ADR-017, "a driver that has not passed
# [backup-conformance] is not a driver" — this file is written so that adding
# pgBackRest is `init` plus one conformance run, but it has never been executed
# against an installed pgBackRest. Do not add it to SIERX_BACKUP_DRIVERS until
# `make backup-conformance` has passed with it and the output is pasted into
# PROGRESS.md. See PROGRESS.md task 0.11 for what is outstanding.
#
# Verbs: init | backup | verify | restore-to <dsn> | retention | describe
# Every invocation passes --repo explicitly (BUILD task 0.11 step 5): letting
# pgBackRest choose among configured repositories makes "which repo did that
# restore come from" unanswerable.
#
# Configuration comes from the rendered config, which comes from the
# environment (§14.4). This script never writes pgbackrest.conf itself —
# render-conf.sh does.
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

STANZA=${PGBACKREST_STANZA:-sierx}
CONF=${PGBACKREST_CONF:-/etc/pgbackrest/pgbackrest.conf}
REPO=${PGBACKREST_REPO:-1}

die() { echo "pgbackrest: $*" >&2; exit 1; }

pgbr() { pgbackrest --config="$CONF" --stanza="$STANZA" --repo="$REPO" "$@"; }

preflight() {
  [[ $REPO == 1 ]] || die 'the rendered configuration supports repository 1 only'
  command -v pgbackrest >/dev/null || die "pgbackrest is not installed"
  [[ -f $CONF ]] || die "$CONF does not exist — render it with scripts/backup/render-conf.sh"
  bash scripts/backup/render-conf.sh --check "$CONF" \
    || die "the config has drifted from the template and environment"
}

verb_init() {
  preflight
  # stanza-create is idempotent; --no-online lets it run before the cluster is
  # accepting connections, which is the order a fresh host boots in.
  pgbr stanza-create || pgbr stanza-upgrade
  pgbr check
}

verb_backup() {
  preflight
  local kind=${SIERX_BACKUP_KIND:-full}
  [[ $kind == full || $kind == diff || $kind == incr ]] || die "invalid backup kind"
  pgbr --type="$kind" backup
  # An opaque id the caller passes back and does not parse (ADR-017).
  pgbr info --output=json \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["backup"][-1]["label"])'
}

verb_verify() {
  preflight
  # verify checks repository integrity without restoring anything.
  pgbr verify
}

verb_restore_to() {
  local dsn=${1:-}
  [[ -n $dsn ]] || die "restore-to needs a target dsn"
  preflight
  # A physical restore replaces a whole cluster's data directory, so it cannot
  # restore "into" a scratch database inside the live cluster the way a logical
  # dump can. It restores into a scratch DATA DIRECTORY, starts a temporary
  # cluster on a spare port, and hands back a dsn pointing at it.
  #
  # PGBACKREST_RESTORE_PATH and PGBACKREST_RESTORE_PORT must be set for this;
  # they are deployment inputs (task 2.16), not dev defaults.
  [[ -n ${PGBACKREST_RESTORE_PATH:-} ]] || die "PGBACKREST_RESTORE_PATH is unset (deployment input, task 2.16)"
  [[ -n ${PGBACKREST_RESTORE_PORT:-} ]] || die "PGBACKREST_RESTORE_PORT is unset (deployment input, task 2.16)"
  [[ $PGBACKREST_RESTORE_PORT =~ ^[0-9]+$ && $PGBACKREST_RESTORE_PORT -ge 1024 && $PGBACKREST_RESTORE_PORT -le 65535 ]] || die "restore port must be an unprivileged TCP port"
  [[ $PGBACKREST_RESTORE_PORT != "${PGBACKREST_PG1_PORT:-5432}" ]] || die "restore port must differ from the source"
  local root scratch restored
  root=$(realpath -m "$PGBACKREST_RESTORE_PATH")
  [[ $root != *[[:space:]\'\"]* ]] || die 'restore root must not contain spaces or quotes'
  [[ $root != / && $root != "$(realpath -m "$PGBACKREST_PG1_PATH")" ]] || die "restore root must be separate from the source cluster"
  case "$root/" in "$(realpath -m "$PGBACKREST_PG1_PATH")/"*) die "restore root cannot be within source PGDATA" ;; esac
  mkdir -p "$root"; chmod 700 "$root"
  scratch=$(mktemp -d "$root/restore.XXXXXXXX")
  # A fresh directory prevents --delta from ever replacing an existing cluster.
  # All files stay private. Keep the failed restore for diagnosis, never delete
  # a caller-supplied path. The owning operator can prune completed evidence.
  chmod 700 "$scratch"
  pgbr --pg1-path="$scratch" --type=immediate --target-action=promote restore
  local started=0
  cleanup_restore() { if [[ $started == 1 ]]; then pg_ctl -D "$scratch" -m fast -w stop >/dev/null; fi; }
  trap cleanup_restore EXIT
  pg_ctl -D "$scratch" -l "$scratch/acceptance-server.log" \
    -o "-c listen_addresses=127.0.0.1 -c port=$PGBACKREST_RESTORE_PORT -c unix_socket_directories=$scratch -c archive_mode=off -c archive_command='' -c primary_conninfo=''" -w start >/dev/null
  started=1
  restored=$(python3 - "$DATABASE_URL" "$PGBACKREST_RESTORE_PORT" "$dsn" <<'PY'
import sys, urllib.parse
source, port, target = sys.argv[1:]
s=urllib.parse.urlsplit(source); t=urllib.parse.urlsplit(target)
if source == target or s.path == t.path:
    raise SystemExit('restore target must differ from source database')
auth=s.netloc.rsplit('@',1)[0]+'@' if '@' in s.netloc else ''
print(urllib.parse.urlunsplit(s._replace(netloc=auth+'127.0.0.1:'+port)))
PY
  )
  # The driver contract takes a target database, not a replacement server DSN.
  # Transport only from the recovered physical cluster into that isolated DB;
  # this never reads the live source. Shared conformance compares this result.
  pg_dump "$restored" --format=custom --file="$scratch/recovered.dump"
  pg_restore --dbname="$dsn" --exit-on-error --no-owner --no-privileges "$scratch/recovered.dump"
  cleanup_restore; started=0; trap - EXIT
  echo 'physical restore completed; recovered data transported to isolated target'
}

verb_cipher_check() {
  preflight
  local info
  info=$(pgbr info --output=json)
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d and all(s.get("cipher")=="aes-256-cbc" and s.get("status",{}).get("code")==0 for s in d), "repository encryption is not verified"' <<<"$info"
  # Probe incompatible settings without modifying the protected config, stanza
  # or repository. A readable repository under either setting fails acceptance.
  if pgbr --repo1-cipher-type=none info --output=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d and all(s.get("status",{}).get("code")==0 for s in d) else 1)'; then
    die 'repository accepted cipher=none; inspect cipher immutability before cutover'
  fi
  if pgbr --repo1-cipher-pass=deliberately-invalid-acceptance-key info --output=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d and all(s.get("status",{}).get("code")==0 for s in d) else 1)'; then
    die 'repository accepted an incorrect cipher key'
  fi
  echo 'physical backup cipher configuration verified; incompatible settings rejected'
}

verb_retention() {
  preflight
  # Retention is expressed in the config (§14.2: 30 days); expire applies it.
  pgbr expire
}

verb_describe() {
  local v repo_type
  v=$(pgbackrest version 2>/dev/null | awk '{print $NF}') || v=unknown
  repo_type=${PGBACKREST_REPO_TYPE:-unset}
  # Names no host, path or bucket (§3.7).
  echo "pgbackrest driver; pgBackRest $v; stanza $STANZA, repo $REPO, repo type $repo_type"
}

case ${1:-} in
  --has-verb)
    case ${2:-} in
      init|backup|verify|restore-to|retention|describe|cipher-check) exit 0 ;;
      *) exit 1 ;;
    esac ;;
  init)       verb_init ;;
  backup)     verb_backup ;;
  verify)     verb_verify ;;
  restore-to) shift; verb_restore_to "$@" ;;
  retention)  verb_retention ;;
  describe)   verb_describe ;;
  cipher-check) verb_cipher_check ;;
  *)          die "usage: $0 init|backup|verify|restore-to <dsn>|retention|describe" ;;
esac
