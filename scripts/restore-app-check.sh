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
name=sierx-restore-acceptance-$$
cleanup() { podman rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
podman run --detach --name "$name" --network host --read-only --security-opt no-new-privileges \
  --env-file "$SIERX_RESTORE_APP_ENV" --env DATABASE_URL \
  --env "SIERX_LISTEN_ADDR=127.0.0.1:$SIERX_RESTORE_APP_PORT" --env "SIERX_BASE_URL=$SIERX_RESTORE_BASE_URL" "$SIERX_RESTORE_IMAGE" >/dev/null
export SIERX_SMOKE_URL=$SIERX_RESTORE_BASE_URL
for _attempt in $(seq 1 20); do
  if curl --fail --silent "$SIERX_SMOKE_URL/api/v1/healthz" >/dev/null; then break; fi
  sleep 1
done
python3 scripts/release-smoke.py
