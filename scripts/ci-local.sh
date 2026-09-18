#!/usr/bin/env bash
# prepare: online image/tool/module preparation. run: offline, disposable gate.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
die() { echo "ci-local: $*" >&2; exit 1; }
[[ $(uname -s) == Linux ]] || die 'requires a Linux Podman host'
command -v podman >/dev/null || die 'podman is required'
command -v python3 >/dev/null || die 'python3 is required'
image=localhost/sierx-ci:phase0

# Only committable working-tree files; no .git, ignored files, or host .env.
# Include uncommitted changes so this command can validate a patch before commit.
snapshot() {
  python3 scripts/ci-snapshot.py "$1"
}

case ${1:-run} in
  prepare)
    scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
    snapshot "$scratch/source.tar"
    mkdir "$scratch/context"
    tar -xf "$scratch/source.tar" -C "$scratch/context"
    go_version=$(awk '$1=="go" {print $2; exit}' go.mod)
    node_version=$(tr -d '[:space:]' < .nvmrc)
    pg_image=$(sed -n 's/^Image=//p' deploy/quadlet/sierx-postgres.container)
    [[ $pg_image =~ @sha256:[a-f0-9]{64}$ ]] || die 'database image must have a real digest pin'
    # Resolve toolchain tags once for preparation, then build by immutable ID.
    # Runtime never resolves or pulls a tag. Native architecture only.
    podman pull "docker.io/library/golang:${go_version}-bookworm"
    podman pull "docker.io/library/node:${node_version}-bookworm-slim"
    podman pull "$pg_image"
    go_image=$(podman image inspect --format '{{.Id}}' "docker.io/library/golang:${go_version}-bookworm")
    node_image=$(podman image inspect --format '{{.Id}}' "docker.io/library/node:${node_version}-bookworm-slim")
    pg_id=$(podman image inspect --format '{{.Id}}' "$pg_image")
    podman build --pull=never --tag "$image" \
      --build-arg "GO_IMAGE=$go_image" --build-arg "NODE_IMAGE=$node_image" \
      --build-arg "PG_IMAGE=$pg_id" \
      --file "$scratch/context/deploy/ci/Containerfile" "$scratch/context"
    echo 'ci-local: preparation complete; make ci-local now runs without network access'
    ;;
  run)
    podman image exists "$image" || die 'prepared image missing; run make ci-local-prepare while online'
    scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
    snapshot "$scratch/source.tar"
    # No host mounts, database URL, credentials, socket, ports, or network.
    # Gate mutations affect only the copy and database inside this container.
    podman run --rm --pull=never --network=none --interactive \
      --entrypoint /bin/bash "$image" /usr/local/bin/sierx-ci-run.sh < "$scratch/source.tar"
    ;;
  *) die 'usage: scripts/ci-local.sh [prepare|run]' ;;
esac
