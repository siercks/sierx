#!/usr/bin/env bash
# Native release builds only; the manifest combines independently built images.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
revision=$(git rev-parse HEAD)
case $(uname -m) in x86_64) native=amd64 ;; aarch64|arm64) native=arm64 ;; *) native=unsupported ;; esac
arch=${ARCH:-$native}
image=${SIERX_RELEASE_REPOSITORY:-ghcr.io/siercks/sierx}
tag=${TAG:-$revision}
[[ $arch == amd64 || $arch == arm64 ]] || { echo 'Unsupported architecture' >&2; exit 1; }
[[ $tag =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || { echo 'Invalid release tag' >&2; exit 1; }
case ${1:-} in
  binaries|image|stage|manifest)
    [[ -z $(git status --porcelain) ]] || { echo 'Release construction/promotion requires a clean committed checkout' >&2; exit 1; }
    ;;
esac
case ${1:-} in
  binaries)
    [[ $native == "$arch" ]] || { echo 'Use the matching native runner' >&2; exit 1; }
    npm --prefix web ci
    npm --prefix web run build
    mkdir -p dist
    CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -mod=vendor -trimpath -o "dist/sierx-$arch" ./cmd/sierx
    CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -mod=vendor -trimpath -o "dist/sierxctl-$arch" ./cmd/sierxctl
    tar -C web/dist -czf "dist/assets-$arch.tar.gz" assets
    cp /etc/ssl/certs/ca-certificates.crt "dist/ca-certificates-$arch.crt"
    sha256sum "dist/ca-certificates-$arch.crt" > "dist/ca-certificates-$arch.sha256"
    ;;
  image)
    [[ -f dist/sierx-$arch && -f dist/assets-$arch.tar.gz ]] || { echo 'Native release artifacts are missing' >&2; exit 1; }
    mkdir -p "dist/runtime-$arch"
    tar -xzf "dist/assets-$arch.tar.gz" -C "dist/runtime-$arch"
    podman build --ignorefile deploy/Containerfile.release.dockerignore --platform "linux/$arch" --build-arg "TARGETARCH=$arch" --label "org.opencontainers.image.revision=$revision" -f deploy/Containerfile.release -t "$image:$tag-$arch" .
    podman save --format oci-archive --output "dist/candidate-$arch.tar" "$image:$tag-$arch"
    ;;
  login)
    : "${REGISTRY_USER:?Set REGISTRY_USER}" "${REGISTRY_TOKEN:?Set REGISTRY_TOKEN}"
    printf '%s' "$REGISTRY_TOKEN" | podman login "${image%%/*}" --username "$REGISTRY_USER" --password-stdin
    ;;
  stage)
    # Publishing a candidate is not release promotion. Tests pull this digest.
    podman load --input "dist/candidate-$arch.tar"
    podman push --digestfile "dist/digest-$arch.txt" "$image:$tag-$arch"
    printf '%s@%s\n' "$image" "$(cat "dist/digest-$arch.txt")" > "dist/image-$arch.txt"
    ;;
  test)
    source scripts/tool.sh
    export GOOSE
    GOOSE=$(tool_path goose)
    export ARCH=$arch SIERX_TEST_REVISION=$revision
    SIERX_TEST_IMAGE=$(cat "dist/image-$arch.txt")
    export SIERX_TEST_IMAGE
    python3 scripts/test-release-image.py
    ;;
  manifest)
    # No network mutation until exact-digest test evidence has passed validation.
    rm -f dist/release.json
    python3 scripts/release-evidence.py "$image" "$revision"
    podman manifest create "$image:$tag" "$(cat dist/image-amd64.txt)" "$(cat dist/image-arm64.txt)"
    podman manifest inspect "$image:$tag" > dist/manifest.json
    python3 scripts/release-evidence.py "$image" "$revision" dist/manifest.json
    podman manifest push --all --digestfile dist/index.digest "$image:$tag" "docker://$image:$tag"
    # Verify the remotely published index still names the tested children.
    podman manifest inspect "$image@$(cat dist/index.digest)" > dist/manifest.json
    python3 scripts/release-evidence.py "$image" "$revision" dist/manifest.json
    python3 - "$image" "$revision" <<'PY'
import json,pathlib,re,sys
digest=pathlib.Path('dist/index.digest').read_text().strip()
assert re.fullmatch(r'sha256:[a-f0-9]{64}',digest)
pathlib.Path('dist/release.json').write_text(json.dumps({'image':sys.argv[1]+'@'+digest,'revision':sys.argv[2]},indent=2)+'\n')
PY
    ;;
  *) echo 'Usage: release.sh binaries|image|login|stage|test|manifest' >&2; exit 1 ;;
esac
