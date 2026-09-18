#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/scripts" "$scratch/bin" "$scratch/vendor/library"
cp "$root/scripts/vendor-verify.sh" "$scratch/scripts/"
cd "$scratch"
git init -q
cat > bin/go <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ $* != 'mod verify' ]] || exit 0
[[ $# == 4 && $1 == mod && $2 == vendor && $3 == -o ]] || exit 90
mkdir -p "$4/library"
printf 'expected source\n' > "$4/library/coverage.go"
SH
chmod +x bin/go
export PATH="$scratch/bin:$PATH"
reject() {
  if bash scripts/vendor-verify.sh >/dev/null 2>&1; then
    echo "vendor proof FAILED: $1 accepted" >&2; exit 1
  fi
  echo "vendor proof: $1 rejected"
}
reject 'missing source'
[[ ! -f vendor/library/coverage.go ]] # verification must not repair in place
printf 'modified source\n' > vendor/library/coverage.go
reject 'modified source'
printf 'expected source\n' > vendor/library/coverage.go
printf 'unexpected source\n' > vendor/library/extra.go
reject 'extra source'
rm vendor/library/extra.go
bash scripts/vendor-verify.sh
echo 'vendor proof: PASS'
