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

STANZA=${PGBACKREST_STANZA:-sierx}
CONF=${PGBACKREST_CONF:-/etc/pgbackrest/pgbackrest.conf}
REPO=${PGBACKREST_REPO:-1}

die() { echo "pgbackrest: $*" >&2; exit 1; }

pgbr() { pgbackrest --config="$CONF" --stanza="$STANZA" --repo="$REPO" "$@"; }

preflight() {
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
  pgbr backup
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
  die "not yet implemented: this driver has never been run against an installed pgBackRest (ADR-017 — see PROGRESS.md task 0.11)"
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
      init|backup|verify|restore-to|retention|describe) exit 0 ;;
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
