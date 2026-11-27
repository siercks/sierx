#!/usr/bin/env bash
# Online OS/browser prerequisites, separated from the isolated acceptance run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
diagnostic=${SIERX_HOST_PREPARE_DIAGNOSTIC:-0}
stage=identify-fixture
scratch=
container=
runtime_image=
cleanup() {
  local status=$?
  if [[ $diagnostic == 1 && $status != 0 ]]; then
    python3 -B - "$stage" "$status" "${scratch:+$scratch/build.log}" <<'PY' || :
import json, sys
from pathlib import Path
sys.path.insert(0, 'scripts')
from offline_host_diagnostics import preparation_failure

stage, status, path = sys.argv[1:]
record = preparation_failure(stage, int(status), None)
if stage == 'build-os' and path and Path(path).is_file():
    with Path(path).open(encoding='utf-8', errors='replace') as stream:
        record = preparation_failure(stage, int(status), stream)
if record is not None:
    Path('dist').mkdir(exist_ok=True)
    Path('dist/host-preparation-failure.json').write_text(json.dumps(record) + '\n')
PY
  fi
  [[ -z $container ]] || podman rm "$container" >/dev/null
  if [[ -n $runtime_image ]] && podman image exists "$runtime_image"; then podman rmi "$runtime_image" >/dev/null; fi
  [[ -z $scratch ]] || rm -rf "$scratch"
}
trap cleanup EXIT
if [[ $diagnostic == 1 ]]; then rm -f -- dist/host-preparation-failure.json; fi
profile=${1:-ubuntu24}
case $profile in
  ubuntu24) base=docker.io/library/ubuntu:24.04 ;;
  rocky10) base=docker.io/rockylinux/rockylinux:10 ;;
  *) echo 'offline-host: expected ubuntu24 or rocky10' >&2; exit 1 ;;
esac
case $(uname -m) in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) exit 1 ;; esac
node_version=$(tr -d '[:space:]' < .nvmrc)
node=docker.io/library/node:$node_version-bookworm-slim
stage=pull-os
podman pull "$base"
stage=pull-node
podman pull "$node"
stage=inspect-images
base_id=$(podman image inspect --format '{{.Id}}' "$base")
node_id=$(podman image inspect --format '{{.Id}}' "$node")
stage=build-inputs
scratch=$(mktemp -d)
runtime_input=$base_id
if [[ $profile == rocky10 ]]; then
  stage=pull-runtime-compiler
  compiler=$(python3 -B scripts/offline_guest_podman.py --compiler-image)
  podman pull "$compiler"
  compiler_id=$(podman image inspect --format '{{.Id}}' "$compiler")
  stage=build-compatible-runtime
  mkdir "$scratch/runtime"
  cp deploy/ci/Containerfile.offline-podman "$scratch/runtime/Containerfile"
  cp scripts/offline_guest_podman.py "$scratch/runtime/"
  runtime_image=localhost/sierx-offline-podman:$(basename "$scratch")
  podman build --pull=never --build-arg HOST_IMAGE="$base_id" --build-arg GO_IMAGE="$compiler_id" \
    --tag "$runtime_image" "$scratch/runtime"
  runtime_input=$(podman image inspect --format '{{.Id}}' "$runtime_image")
fi
cp deploy/ci/Containerfile.offline-host "$scratch/Containerfile"
cp scripts/offline_guest_tracer.py scripts/offline_guest_podman.py test/diagnostics/tracer-termination/termination-fix.json "$scratch/"
cp web/package.json web/package-lock.json "$scratch/"
image=localhost/sierx-offline-host:$profile-$arch
stage=build-os
build_args=(--pull=never --target "$profile" --build-arg HOST_IMAGE="$base_id" --build-arg NODE_IMAGE="$node_id" \
  --build-arg PODMAN_IMAGE="$runtime_input" --tag "$image" "$scratch")
if [[ $diagnostic == 1 ]]; then
  podman build "${build_args[@]}" 2>&1 | tee "$scratch/build.log"
else
  podman build "${build_args[@]}"
fi
stage=create-export-container
mkdir -p dist
destination=$PWD/dist/host-fixture-$profile-$arch.tar
container=$(podman create --pull=never --network=none "$image")
stage=export-os
podman export --output "$destination.pending" "$container"
mv "$destination.pending" "$destination"
stage=hash-os
sha256sum "$destination" > "$destination.sha256"
stage=cleanup
podman rm "$container" >/dev/null
container=
if [[ ${SIERX_HOST_DISCARD_BUILD_IMAGE:-0} == 1 ]]; then podman rmi "$image" >/dev/null; fi
echo "offline-host: prepared $profile/$arch; isolate before installing the application"
