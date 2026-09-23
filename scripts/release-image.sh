#!/usr/bin/env bash
# Online release build, run only after the exact revision passes gate-2.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
: "${SIERX_RELEASE_IMAGE:?Set the destination registry image and release tag}"
[[ -z $(git status --porcelain) ]] || { echo 'release-image: commit and test the candidate first' >&2; exit 1; }
revision=$(git rev-parse HEAD)
go_version=$(awk '$1=="go"{print $2;exit}' go.mod)
node_version=$(tr -d '[:space:]' < .nvmrc)
podman pull "docker.io/library/node:${node_version}-bookworm-slim"
podman pull "docker.io/library/golang:${go_version}-bookworm"
node_image=$(podman image inspect --format '{{index .RepoDigests 0}}' "docker.io/library/node:${node_version}-bookworm-slim")
go_image=$(podman image inspect --format '{{index .RepoDigests 0}}' "docker.io/library/golang:${go_version}-bookworm")
[[ $node_image == *@sha256:* && $go_image == *@sha256:* ]]
podman build --platform linux/amd64,linux/arm64 --manifest "$SIERX_RELEASE_IMAGE" \
  --build-arg "NODE_IMAGE=$node_image" --build-arg "GO_IMAGE=$go_image" \
  --label "org.opencontainers.image.revision=$revision" -f deploy/Containerfile .
mkdir -p dist
podman manifest push --all --digestfile dist/image.digest "$SIERX_RELEASE_IMAGE" "docker://$SIERX_RELEASE_IMAGE"
python3 - "$SIERX_RELEASE_IMAGE" "$revision" <<'PY'
import json,pathlib,re,sys
tag,revision=sys.argv[1:]
digest=pathlib.Path('dist/image.digest').read_text().strip()
assert re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
image=tag.rsplit(':',1)[0]+'@'+digest
pathlib.Path('dist/release.json').write_text(json.dumps({'revision':revision,'image':image},indent=2)+'\n')
PY
echo 'release-image: publish dist/release.json to the operator-selected deployment channel after review'
