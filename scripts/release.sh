#!/usr/bin/env bash
# Native release builds only; the manifest combines independently built images.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
revision=$(git rev-parse HEAD)
arch=${ARCH:-$(go env GOARCH)}
image=${SIERX_RELEASE_REPOSITORY:-ghcr.io/siercks/sierx}
tag=${TAG:-$revision}
[[ $arch == amd64 || $arch == arm64 ]] || { echo 'Unsupported architecture' >&2; exit 1; }
[[ $tag =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo 'Invalid release tag' >&2; exit 1; }
case ${1:-} in
  binaries)
    [[ $(go env GOARCH) == "$arch" ]] || { echo 'Use the matching native runner' >&2; exit 1; }
    npm --prefix web ci
    npm --prefix web run build
    mkdir -p dist
    CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -mod=vendor -trimpath -o "dist/sierx-$arch" ./cmd/sierx
    CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -mod=vendor -trimpath -o "dist/sierxctl-$arch" ./cmd/sierxctl
    tar -C web/dist -czf "dist/assets-$arch.tar.gz" assets
    cp /etc/ssl/certs/ca-certificates.crt "dist/ca-certificates-$arch.crt"
    ;;
  image)
    [[ -f dist/sierx-$arch && -f dist/assets-$arch.tar.gz ]] || { echo 'Native release artifacts are missing' >&2; exit 1; }
    mkdir -p "dist/runtime-$arch"
    tar -xzf "dist/assets-$arch.tar.gz" -C "dist/runtime-$arch"
    docker build --platform "linux/$arch" --build-arg "TARGETARCH=$arch" --label "org.opencontainers.image.revision=$revision" -f deploy/Containerfile.release -t "$image:$tag-$arch" .
    docker push "$image:$tag-$arch"
    docker image inspect --format '{{index .RepoDigests 0}}' "$image:$tag-$arch" > "dist/image-$arch.txt"
    ;;
  manifest)
    for architecture in amd64 arm64; do
      [[ $(cat "dist/image-$architecture.txt") == "$image@sha256:"* ]] || { echo 'Missing pinned architecture image' >&2; exit 1; }
    done
    docker buildx imagetools create --tag "$image:$tag" "$(cat dist/image-amd64.txt)" "$(cat dist/image-arm64.txt)"
    docker buildx imagetools inspect "$image:$tag" --format '{{json .Manifest}}' > dist/manifest.json
    python3 - "$image" "$revision" <<'PY'
import json,pathlib,re,sys
manifest=json.loads(pathlib.Path('dist/manifest.json').read_text())
digest=manifest['digest']
assert re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
pathlib.Path('dist/release.json').write_text(json.dumps({'image':sys.argv[1]+'@'+digest,'revision':sys.argv[2]},indent=2)+'\n')
PY
    ;;
  *) echo 'Usage: release.sh binaries|image|manifest' >&2; exit 1 ;;
esac
