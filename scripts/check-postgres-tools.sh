#!/usr/bin/env bash
# Fail before migrations if the caller's PATH selects an incompatible client.
set -euo pipefail
for tool in psql pg_dump pg_restore; do
  command -v "$tool" >/dev/null || { echo "postgres-tools: $tool is missing" >&2; exit 1; }
  version=$("$tool" --version)
  echo "postgres-tools: $version"
  if [[ ! $version =~ PostgreSQL\)\ 18\. ]]; then
    echo "postgres-tools: $tool must be PostgreSQL 18; check PATH" >&2
    exit 1
  fi
done
# The phase gate's scripts may obtain DATABASE_URL from .env; do not duplicate
# that loader or print connection settings here. Query when already exported.
if [[ -n ${DATABASE_URL:-} ]]; then
  server=$(psql "$DATABASE_URL" -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version_num')
  [[ $server =~ ^[0-9]+$ ]] || { echo 'postgres-tools: invalid server version' >&2; exit 1; }
  echo "postgres-tools: server_version_num=$server"
  [[ $server -ge 180000 && $server -lt 190000 ]] || {
    echo 'postgres-tools: server must be PostgreSQL 18' >&2; exit 1;
  }
fi
