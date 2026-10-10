#!/usr/bin/env bash
# Provision the dedicated non-privileged application login roles from private DSNs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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

die() { echo "db-roles: $*" >&2; exit 1; }
[[ -n ${DATABASE_URL:-} ]] || die "DATABASE_URL (privileged operator DSN) is required"
[[ -n ${SIERX_RUNTIME_DATABASE_URL:-} ]] || die "SIERX_RUNTIME_DATABASE_URL is required"
[[ -n ${SIERX_AUTH_DATABASE_URL:-} ]] || die "SIERX_AUTH_DATABASE_URL is required"
[[ -n ${SIERX_MAINTENANCE_DATABASE_URL:-} ]] || die "SIERX_MAINTENANCE_DATABASE_URL is required"
command -v psql >/dev/null || die "psql not found"

sql_file=$(python3 - <<'PY'
import os
import pathlib
import tempfile
import urllib.parse

admin = urllib.parse.urlsplit(os.environ["DATABASE_URL"])
runtime = urllib.parse.urlsplit(os.environ["SIERX_RUNTIME_DATABASE_URL"])
auth = urllib.parse.urlsplit(os.environ["SIERX_AUTH_DATABASE_URL"])
maintenance = urllib.parse.urlsplit(os.environ["SIERX_MAINTENANCE_DATABASE_URL"])

def credentials(url, expected):
    if url.scheme not in ("postgres", "postgresql") or not url.hostname or not url.path.strip("/"):
        raise SystemExit("database URL must include a PostgreSQL scheme, host, and database")
    if urllib.parse.unquote(url.username or "") != expected:
        raise SystemExit(f"runtime role URL must use the dedicated {expected} login")
    password = urllib.parse.unquote(url.password or "")
    if not password or any(ord(character) < 32 for character in password):
        raise SystemExit(f"database URL for {expected} must include a password")
    return password

if admin.scheme not in ("postgres", "postgresql") or not admin.hostname or not admin.path.strip("/"):
    raise SystemExit("DATABASE_URL must include a PostgreSQL scheme, host, and database")
if urllib.parse.unquote(admin.username or "") in {"sierx_runtime", "sierx_auth", "sierx_maintenance"}:
    raise SystemExit("DATABASE_URL must use a separate privileged operator login")
for candidate in (runtime, auth, maintenance):
    if (candidate.scheme not in ("postgres", "postgresql") or candidate.hostname != admin.hostname
            or (candidate.port or 5432) != (admin.port or 5432)
            or candidate.path != admin.path):
        raise SystemExit("operator, runtime, authentication, and maintenance URLs must target the same database")
if len({urllib.parse.unquote(url.username or "") for url in (runtime, auth, maintenance)}) != 3:
    raise SystemExit("runtime, authentication, and maintenance URLs must use distinct roles")

runtime_password = credentials(runtime, "sierx_runtime")
auth_password = credentials(auth, "sierx_auth")
maintenance_password = credentials(maintenance, "sierx_maintenance")
def literal(value):
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
def identifier(value):
    return '"' + value.replace('"', '""') + '"'
database_name = urllib.parse.unquote(admin.path.strip("/"))

sql = f"""DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) THEN
    RAISE EXCEPTION 'role provisioning requires a superuser operator connection';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_shdepend d JOIN pg_roles r ON r.oid = d.refobjid
    WHERE d.refclassid = 'pg_authid'::regclass
      AND d.deptype = 'o'
      AND d.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND r.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
      AND NOT (
        r.rolname = 'sierx_maintenance'
        AND d.classid = 'pg_proc'::regclass
        AND EXISTS (
          SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE p.oid=d.objid AND n.nspname='public' AND p.prokind='f'
            AND ((p.proname='sierx_set_account_active'
                  AND pg_get_function_identity_arguments(p.oid)='p_user_id uuid, p_active boolean, p_case_ref uuid')
              OR (p.proname='sierx_create_session'
                  AND pg_get_function_identity_arguments(p.oid)='p_hash bytea, p_user_id uuid')
              OR (p.proname='sierx_create_data_export'
                  AND pg_get_function_identity_arguments(p.oid)='p_user_id uuid, p_case_ref uuid')
              OR (p.proname='sierx_read_data_export'
                  AND pg_get_function_identity_arguments(p.oid)='p_export_id uuid, p_case_ref uuid'))
        )
      )
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
    WHERE r.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
  ) OR EXISTS (
    SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid
    WHERE r.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
  ) OR EXISTS (
    SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba
    WHERE r.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
  ) OR EXISTS (
    SELECT 1 FROM pg_default_acl d JOIN pg_roles r ON r.oid = d.defaclrole
    WHERE r.rolname IN ('sierx_runtime','sierx_auth','sierx_maintenance')
  ) THEN
    RAISE EXCEPTION 'application role owns unapproved objects/databases/default ACLs or has role memberships; inventory and resolve before changing it';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_runtime') THEN
    EXECUTE 'CREATE ROLE sierx_runtime';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_auth') THEN
    EXECUTE 'CREATE ROLE sierx_auth';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='sierx_maintenance') THEN
    EXECUTE 'CREATE ROLE sierx_maintenance';
  END IF;
  EXECUTE format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', 'sierx_runtime', {literal(runtime_password)});
  EXECUTE format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', 'sierx_auth', {literal(auth_password)});
  EXECUTE format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', 'sierx_maintenance', {literal(maintenance_password)});
END
$roles$;
GRANT CONNECT ON DATABASE {identifier(database_name)} TO sierx_runtime, sierx_auth, sierx_maintenance;
"""
fd, path = tempfile.mkstemp(prefix="sierx-db-roles-", suffix=".sql")
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    stream.write(sql)
print(path)
PY
) || die "invalid or unsafe role configuration"
trap 'rm -f "$sql_file"' EXIT
psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -f "$sql_file" >/dev/null || die "role provisioning failed; no application role changes were accepted"
echo "db-roles: runtime, authentication, and maintenance roles provisioned with restricted role attributes"
