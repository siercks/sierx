#!/usr/bin/env bash
# Runs only inside the disposable local CI container, with no network.
set -euo pipefail
cd /workspace
tar -xf -
sha256sum --check --quiet /opt/prepared-inputs.sha256 || {
  echo 'ci-local: prepared inputs changed; run make ci-local-prepare again' >&2
  exit 1
}
git init -q
git add -A
mkdir -p bin
cp /opt/sierx-tools/* bin/
export GOPROXY=off GOSUMDB=off

# The entire cluster lives in the container layer, never the image's PGDATA
# volume or a host directory. The loopback socket is private to this container.
install -d -o postgres -g postgres /tmp/sierx-ci-pg
gosu postgres initdb -D /tmp/sierx-ci-pg --encoding=UTF8 --locale=C --auth=trust >/dev/null
gosu postgres pg_ctl -D /tmp/sierx-ci-pg -l /tmp/sierx-ci-pg/server.log \
  -o '-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp' -w start
trap 'gosu postgres pg_ctl -D /tmp/sierx-ci-pg -m immediate -w stop >/dev/null' EXIT
createuser -h 127.0.0.1 -U postgres --superuser sierx
createdb -h 127.0.0.1 -U postgres -O sierx -T template0 --encoding=UTF8 --locale=C sierx

# Only public fixture values, consistent with the hosted CI job.
export DATABASE_URL=postgres://sierx:sierx@localhost:5432/sierx
export SIERX_ENV=dev SIERX_AUTH_MODE=local SIERX_BASE_URL=http://localhost:8080
export SIERX_SESSION_KEY=ci-only-not-a-secret-000000000000000000000000
export SIERX_TRUSTED_PROXIES= SIERX_BACKUP_DRIVERS=pgdump
export PGBACKREST_REPO_TYPE=posix PGBACKREST_REPO_PATH=.backups/physical
export SIERX_DUMP_PATH=.backups/logical
make gate-0
