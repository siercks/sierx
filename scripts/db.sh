#!/usr/bin/env bash
# db.sh — dev/staging PostgreSQL lifecycle over a rootless Podman Quadlet unit.
# BUILD task 0.2. Subcommands: up | down | psql [args] | reset | pin
#
# Everything is derived from DATABASE_URL (SPEC §14.4: env only). The tracked
# unit is deploy/quadlet/sierx-postgres.container; `up` installs it under
# ~/.config/containers/systemd/ with the host port substituted from the URL and
# renders the credentials into a 0600 env file beside it.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

UNIT_SRC=deploy/quadlet/sierx-postgres.container
UNIT_NAME=sierx-postgres
QUADLET_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd
VOLUME=sierx-pgdata
PLACEHOLDER='sha256:PIN-ME-WITH-make-db-pin'

# ---- .env loader: environment wins, .env fills the gaps ------------------
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

die() { echo "db.sh: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL is unset (see .env.example)"

# postgres://user:pass@host:port/db  — the only shape the dev URL takes
parse_url() {
  local rest=${DATABASE_URL#postgres://}; rest=${rest#postgresql://}
  local userinfo=${rest%%@*}; rest=${rest#*@}
  PGUSER_=${userinfo%%:*}; PGPASS_=${userinfo#*:}
  [[ $userinfo == *:* ]] || PGPASS_=
  local hostport=${rest%%/*}; rest=${rest#*/}
  PGHOST_=${hostport%%:*}
  PGPORT_=${hostport#*:}; [[ $hostport == *:* ]] || PGPORT_=5432
  PGDB_=${rest%%\?*}
  [[ -n $PGUSER_ && -n $PGDB_ ]] || die "could not parse DATABASE_URL"
  [[ $PGPORT_ =~ ^[0-9]+$ && $PGPORT_ -ge 1024 && $PGPORT_ -le 65535 ]] || \
    die "DATABASE_URL port must be an unprivileged TCP port from 1024 through 65535"
}
parse_url

need_podman() { command -v podman >/dev/null || die "podman not found (BUILD §1: rootless Podman)"; }

cmd_pin() {
  need_podman
  echo "Resolving digest for docker.io/library/postgres:18 ..."
  podman pull -q docker.io/library/postgres:18 >/dev/null
  local digest
  digest=$(podman image inspect --format '{{.Digest}}' docker.io/library/postgres:18)
  [[ $digest == sha256:* ]] || die "could not resolve digest"
  sed -i -E "s|^Image=docker.io/library/postgres:18@sha256:.*|Image=docker.io/library/postgres:18@${digest}|" "$UNIT_SRC"
  echo "Pinned: $(grep '^Image=' "$UNIT_SRC")"

  # The CI service container must be the SAME image, pinned the same way
  # (§15.4). Updating it here rather than by hand: two places holding one
  # digest is two places to forget, and the symptom is a CI run that cannot
  # pull its database.
  local ci=.github/workflows/ci.yml
  if [[ -f $ci ]]; then
    sed -i -E "s|(image: postgres:18@)sha256:[A-Za-z0-9._-]+|\1${digest}|" "$ci"
    echo "Pinned: $(grep -m1 'image: postgres:18@' "$ci" | sed 's/^ *//')"
  fi
}

cmd_up() {
  need_podman
  grep -q "$PLACEHOLDER" "$UNIT_SRC" && die "image digest not pinned yet — run: make db-pin"
  mkdir -p "$QUADLET_DIR"
  sed -E "s|^PublishPort=127\.0\.0\.1:[0-9]+:5432|PublishPort=127.0.0.1:${PGPORT_}:5432|" \
    "$UNIT_SRC" > "$QUADLET_DIR/$UNIT_NAME.container"
  umask 077
  printf 'POSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=%s\n' "$PGUSER_" "$PGPASS_" "$PGDB_" \
    > "$QUADLET_DIR/$UNIT_NAME.env"
  systemctl --user daemon-reload
  systemctl --user start "$UNIT_NAME.service"
  echo "waiting for postgres ..."
  local i
  for i in $(seq 1 30); do
    if podman exec "$UNIT_NAME" pg_isready -q -U "$PGUSER_" -d "$PGDB_" 2>/dev/null; then
      assert_encoding
      echo "db-up: $UNIT_NAME ready on 127.0.0.1:${PGPORT_}"; return 0
    fi
    sleep 1
  done
  systemctl --user status "$UNIT_NAME.service" --no-pager || true
  die "postgres did not become ready"
}

# The cluster's encoding and collation are pinned (§4.4) and are set only when
# initdb runs, so a volume created by an earlier, differently-configured unit
# keeps whatever it was born with. Checked here rather than left to surface
# later as something that looks like schema drift.
assert_encoding() {
  local got
  got=$(podman exec "$UNIT_NAME" psql -U "$PGUSER_" -d "$PGDB_" -X -q -At \
        -c "SELECT pg_encoding_to_char(encoding) || ' ' || datcollate FROM pg_database WHERE datname = current_database()" 2>/dev/null) || return 0
  if [[ $got != "UTF8 C" ]]; then
    die "the cluster is '$got' but must be 'UTF8 C' (§4.4). initdb args apply only to a fresh volume, so: make db-reset"
  fi
}

cmd_down() {
  need_podman
  systemctl --user stop "$UNIT_NAME.service" 2>/dev/null || true
  echo "db-down: $UNIT_NAME stopped (data kept in volume $VOLUME)"
}

# `make db-psql -- -c "select 1"` arrives via $PSQL_ARGS as the single string
# "-c select 1" (make re-splits words, so it is exported rather than passed as
# arguments). A leading -c means everything after it is one SQL command.
# Called directly, arguments are passed through to psql untouched.
cmd_psql() {
  need_podman
  local -a args=("$@")
  if [[ $# -eq 0 && -n ${PSQL_ARGS:-} ]]; then
    if [[ $PSQL_ARGS == -c\ * ]]; then args=(-c "${PSQL_ARGS#-c }"); else read -r -a args <<<"$PSQL_ARGS"; fi
  fi
  local tty=()
  [[ -t 0 ]] && tty=(-it)
  exec podman exec "${tty[@]}" "$UNIT_NAME" psql -U "$PGUSER_" -d "$PGDB_" "${args[@]}"
}

# ⚠ Destroys the database. Dev only, and says what it will drop before it does.
cmd_reset() {
  [[ ${SIERX_ENV:-} == dev ]] || die "db-reset refused: SIERX_ENV is '${SIERX_ENV:-unset}', not dev"
  need_podman
  grep -q "$PLACEHOLDER" "$UNIT_SRC" && die "image digest not pinned yet — run: make db-pin (nothing dropped)"
  echo "db-reset will DESTROY:"
  echo "  container : $UNIT_NAME"
  echo "  volume    : $VOLUME (the entire PGDATA — every database in this cluster)"
  echo "  database  : $PGDB_ on ${PGHOST_}:${PGPORT_}"
  systemctl --user stop "$UNIT_NAME.service" 2>/dev/null || true
  podman volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  echo "dropped volume $VOLUME"
  cmd_up
}

case ${1:-} in
  up)    cmd_up ;;
  down)  cmd_down ;;
  psql)  shift; cmd_psql "$@" ;;
  reset) cmd_reset ;;
  pin)   cmd_pin ;;
  *)     echo "usage: $0 up|down|psql [args]|reset|pin" >&2; exit 2 ;;
esac
