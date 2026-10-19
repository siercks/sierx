#!/usr/bin/env bash
# Shared connected preparation and isolated acceptance; no registry write needed.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
case $(uname -m) in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) exit 1 ;; esac
profile=${PROFILE:-ubuntu24}
bundle=$PWD/dist/sierx-offline-$arch
case ${1:-} in
  local)
    python3 -B scripts/offline-local-candidate.py --archive "dist/candidate-$arch.tar" \
      --repository "${SIERX_RELEASE_REPOSITORY:-ghcr.io/siercks/sierx}" --output dist/release.json
    python3 -B scripts/offline.py prepare --release dist/release.json \
      --local-app "dist/candidate-$arch.tar" --sbom "dist/sbom-$arch.cdx.json" \
      --caddy-image docker.io/library/caddy@sha256:0c994536bddb66445885237f1a5dcc1916bccea922661c76b4e9fc24061f9b52 \
      --output "$bundle"
    tar -C dist -czf "dist/sierx-offline-$arch.tar.gz" "sierx-offline-$arch"
    sha256sum "dist/sierx-offline-$arch.tar.gz" > "dist/sierx-offline-$arch.tar.gz.sha256"
    sha256sum "$bundle/bundle.lock.json" | cut -d ' ' -f1 > "dist/sierx-offline-$arch.lock.sha256"
    ;;
  previous)
    readarray -t approval < <(python3 -B - <<'PY'
import json,re
p=json.load(open('deploy/ci/previous-offline-release.json'))
assert re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',p['repository'])
assert type(p['run_id']) is int and p['run_id']>0
print(p['repository']);print(p['run_id'])
PY
)
    [[ ${#approval[@]} == 2 ]]
    mkdir -p dist/previous
    gh run download "${approval[1]}" --repo "${approval[0]}" --name "offline-delivery-$arch" --dir dist/previous
    python3 -B scripts/offline-previous.py --directory dist/previous
    ;;
  prepare)
    bash scripts/offline-host-prepare.sh "$profile"
    ;;
  test)
    rootfs=$PWD/dist/host-fixture-$profile-$arch.tar
    rootfs_hash=$(cut -d ' ' -f1 "$rootfs.sha256")
    bundle_hash=$(sha256sum "$bundle/bundle.lock.json" | cut -d ' ' -f1)
    archive_hash=$(cut -d ' ' -f1 "dist/sierx-offline-$arch.tar.gz.sha256")
    previous_hash=$(python3 -B -c 'import json,sys; print(json.load(open("deploy/ci/previous-offline-release.json"))["architectures"][sys.argv[1]]["bundle_sha256"])' "$arch")
    python3 -B scripts/offline-host-evidence.py receipt --profile "$profile"
    sudo env PATH="$PATH" python3 -B scripts/offline-host.py \
      --bundle "$bundle" --expected-sha256 "$bundle_hash" \
      --archive "$PWD/dist/sierx-offline-$arch.tar.gz" --archive-sha256 "$archive_hash" \
      --rootfs "$rootfs" --rootfs-sha256 "$rootfs_hash" \
      --previous-bundle "$PWD/dist/previous/sierx-offline-$arch" --previous-sha256 "$previous_hash" \
      --previous-evidence "$PWD/dist/previous/offline-acceptance-$arch.json" \
      --report "$PWD/dist/host-acceptance-$profile-$arch.json"
    ;;
  *) echo 'Usage: offline-host-release.sh local|previous|prepare|test' >&2; exit 1 ;;
esac
