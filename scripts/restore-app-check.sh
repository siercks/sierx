#!/usr/bin/env bash
# Optional conformance hook. Gateway for the isolated restore origin is preconfigured by the owner.
set -euo pipefail
: "${SIERX_RESTORE_IMAGE:?Set the accepted image digest}"
: "${SIERX_RESTORE_APP_ENV:?Set the protected application environment file}"
: "${SIERX_RESTORE_BASE_URL:?Set the HTTPS restore-test origin}"
: "${SIERX_RESTORE_APP_PORT:?Set a separate unprivileged loopback port}"
[[ $SIERX_RESTORE_IMAGE == *@sha256:* ]] || exit 1
[[ $SIERX_RESTORE_APP_PORT =~ ^[0-9]+$ && $SIERX_RESTORE_APP_PORT -ge 1024 && $SIERX_RESTORE_APP_PORT -le 65535 ]] || exit 1
[[ $SIERX_RESTORE_APP_PORT != "${SIERX_APP_PORT:-}" ]] || exit 1
: "${SIERX_LIFECYCLE_GUARD_DIR:?Set the current trusted checkpoint directory}"
role_dsn() {
 python3 - "$1" "$restore_target" "$2" <<'PYROLE'
import sys,urllib.parse
role=urllib.parse.urlsplit(sys.argv[1]);target=urllib.parse.urlsplit(sys.argv[2])
if role.scheme not in ('postgres','postgresql') or role.username != sys.argv[3] or not target.path.strip('/') or any(k in urllib.parse.parse_qs(role.query) for k in ('dbname','host','port','service')):
    raise SystemExit('restore-app-check: explicit restricted role URL and restore target required')
if role.hostname != target.hostname or role.port != target.port:
    raise SystemExit('restore-app-check: role URL must use the isolated restore cluster')
print(urllib.parse.urlunsplit(role._replace(path=target.path)))
PYROLE
}
# Reject symlinks, broad permissions and operator keys before reading config.
[[ -f $SIERX_RESTORE_APP_ENV && ! -L $SIERX_RESTORE_APP_ENV ]] || exit 1
[[ $(stat -c %a "$SIERX_RESTORE_APP_ENV") == 600 ]] || exit 1
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?(DATABASE_URL|SIERX_MAINTENANCE_DATABASE_URL|SIERX_LIFECYCLE_KEY_FILE|SIERX_LIFECYCLE_JOURNAL)=' "$SIERX_RESTORE_APP_ENV"; then
 echo 'restore-app-check: application environment contains operator inputs' >&2; exit 1
fi
restore_target=$DATABASE_URL
# Source only the reviewed protected file; never print its credentials.
set -a
# shellcheck source=/dev/null
. "$SIERX_RESTORE_APP_ENV"
set +a
runtime_restore_url=$(role_dsn "$SIERX_RUNTIME_DATABASE_URL" sierx_runtime)
auth_restore_url=$(role_dsn "$SIERX_AUTH_DATABASE_URL" sierx_auth)
export SIERX_RUNTIME_DATABASE_URL=$runtime_restore_url
export SIERX_AUTH_DATABASE_URL=$auth_restore_url
export SIERX_LIFECYCLE_CHECKPOINT=/var/lib/sierx/lifecycle/guard/checkpoint.json
export SIERX_LIFECYCLE_GUARD_KEY_FILE=/var/lib/sierx/lifecycle/guard/verification.key
name=sierx-restore-acceptance-$$
cleanup() { podman rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
podman run --detach --name "$name" --network host --read-only --security-opt no-new-privileges \
  --userns=keep-id:uid=65532,gid=65532 --volume "$SIERX_LIFECYCLE_GUARD_DIR:/var/lib/sierx/lifecycle/guard:ro,z" \
  --env-file "$SIERX_RESTORE_APP_ENV" --env SIERX_RUNTIME_DATABASE_URL --env SIERX_AUTH_DATABASE_URL \
  --env SIERX_LIFECYCLE_CHECKPOINT --env SIERX_LIFECYCLE_GUARD_KEY_FILE \
  --env "SIERX_LISTEN_ADDR=127.0.0.1:$SIERX_RESTORE_APP_PORT" --env "SIERX_BASE_URL=$SIERX_RESTORE_BASE_URL" "$SIERX_RESTORE_IMAGE" >/dev/null
export SIERX_SMOKE_URL=$SIERX_RESTORE_BASE_URL
for _attempt in $(seq 1 20); do
  if curl --fail --silent "$SIERX_SMOKE_URL/api/v1/healthz" >/dev/null; then break; fi
  sleep 1
done
python3 scripts/release-smoke.py
