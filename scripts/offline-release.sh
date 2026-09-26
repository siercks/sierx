#!/usr/bin/env bash
# Reproducible connected assembly and isolated acceptance, shared with CI.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
case $(uname -m) in
  x86_64) native=amd64 ;;
  aarch64|arm64) native=arm64 ;;
  *) echo 'offline-release: unsupported native architecture' >&2; exit 1 ;;
esac
arch=${ARCH:-$native}
[[ $arch == "$native" ]] || { echo 'offline-release: use the matching native runner' >&2; exit 1; }
bundle="$PWD/dist/sierx-offline-$arch"
caddy=${SIERX_CADDY_IMAGE:-docker.io/library/caddy@sha256:0c994536bddb66445885237f1a5dcc1916bccea922661c76b4e9fc24061f9b52}
case ${1:-} in
  build)
    python3 -B scripts/offline.py prepare --release dist/release.json \
      --caddy-image "$caddy" --sbom "dist/sbom-$arch.cdx.json" --output "$bundle"
    ;;
  test)
    expected=$(sha256sum "$bundle/bundle.lock.json" | cut -d ' ' -f1)
    sudo env SIERX_OFFLINE_BUNDLE="$bundle" SIERX_OFFLINE_SHA256="$expected" \
      SIERX_OFFLINE_REPORT="$PWD/dist/offline-acceptance-$arch.json" \
      unshare --net -- python3 -B scripts/test-offline-bundle.py
    ;;
  archive)
    python3 -B - "$bundle" "dist/offline-acceptance-$arch.json" <<'PY'
import hashlib, json, pathlib, sys
sys.path.insert(0, 'scripts')
from offline import verify_evidence
root, evidence = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
lock = root / 'bundle.lock.json'
data, report = json.loads(lock.read_text()), json.loads(evidence.read_text())
expected = hashlib.sha256(lock.read_bytes()).hexdigest()
verify_evidence(data, expected, report)
PY
    expected=$(sha256sum "$bundle/bundle.lock.json" | cut -d ' ' -f1)
    python3 -B scripts/offline.py verify --bundle "$bundle" --expected-sha256 "$expected"
    tar -C dist -czf "dist/sierx-offline-$arch.tar.gz" "sierx-offline-$arch"
    printf '%s\n' "$expected" > "dist/sierx-offline-$arch.lock.sha256"
    sha256sum "dist/sierx-offline-$arch.tar.gz" > "dist/sierx-offline-$arch.tar.gz.sha256"
    ;;
  *) echo 'Usage: offline-release.sh build|test|archive' >&2; exit 1 ;;
esac
