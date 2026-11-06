#!/usr/bin/env bash
# Online OS/browser prerequisites, separated from the isolated acceptance run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
profile=${1:-ubuntu24}
case $profile in
  ubuntu24) base=docker.io/library/ubuntu:24.04 ;;
  rocky10) base=docker.io/rockylinux/rockylinux:10 ;;
  *) echo 'offline-host: expected ubuntu24 or rocky10' >&2; exit 1 ;;
esac
case $(uname -m) in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) exit 1 ;; esac
node_version=$(tr -d '[:space:]' < .nvmrc)
node=docker.io/library/node:$node_version-bookworm-slim
podman pull "$base"
podman pull "$node"
base_id=$(podman image inspect --format '{{.Id}}' "$base")
node_id=$(podman image inspect --format '{{.Id}}' "$node")
scratch=$(mktemp -d)
container=
cleanup() { [[ -z $container ]] || podman rm "$container" >/dev/null; rm -rf "$scratch"; }
trap cleanup EXIT
cp deploy/ci/Containerfile.offline-host "$scratch/Containerfile"
cp web/package.json web/package-lock.json "$scratch/"
image=localhost/sierx-offline-host:$profile-$arch
podman build --pull=never --build-arg HOST_IMAGE="$base_id" --build-arg NODE_IMAGE="$node_id" --tag "$image" "$scratch"
mkdir -p dist
destination=$PWD/dist/host-fixture-$profile-$arch.tar
container=$(podman create --pull=never --network=none "$image")
podman export --output "$destination.pending" "$container"
mv "$destination.pending" "$destination"
sha256sum "$destination" > "$destination.sha256"
podman rm "$container" >/dev/null
container=
if [[ ${SIERX_HOST_DISCARD_BUILD_IMAGE:-0} == 1 ]]; then podman rmi "$image" >/dev/null; fi
echo "offline-host: prepared $profile/$arch; isolate before installing the application"
