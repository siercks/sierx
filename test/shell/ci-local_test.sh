#!/usr/bin/env bash
# Command-boundary proof only: this does not certify a real container run.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d); trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/scripts" "$scratch/bin"
cp "$root/scripts/ci-local.sh" "$root/scripts/ci-snapshot.py" "$root/scripts/tool.sh" "$scratch/scripts/"
cd "$scratch"
git init -q
printf '.env\nbin/\n' > .gitignore
printf 'DATABASE_URL=host-value-must-not-be-used\n' > .env
cat > bin/uname <<'SH'
#!/usr/bin/env bash
case $1 in -s) echo Linux ;; -m) echo aarch64 ;; *) exit 1 ;; esac
SH
cat > bin/podman <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ $* == 'image exists localhost/sierx-ci:phase0' ]]; then
  exit "${MOCK_MISSING:-0}"
fi
[[ $* == 'run --rm --pull=never --network=none --interactive --entrypoint /bin/bash localhost/sierx-ci:phase0 /usr/local/bin/sierx-ci-run.sh' ]] || exit 90
tar -tf - > bin/archive-list
if grep -qx '.env' bin/archive-list; then exit 91; fi
grep -qx scripts/ci-local.sh bin/archive-list
exit "${MOCK_RUN_EXIT:-0}"
SH
cat > bin/sqlc <<'SH'
#!/usr/bin/env bash
[[ $1 == version ]] || exit 1
echo "$MOCK_SQLC_VERSION"
SH
chmod +x bin/uname bin/podman bin/sqlc
export PATH="$scratch/bin:$PATH"

export MOCK_MISSING=1
if output=$(bash scripts/ci-local.sh run 2>&1); then
  echo 'ci-local proof FAILED: missing image accepted' >&2; exit 1
fi
[[ $output == *'run make ci-local-prepare'* ]]
echo 'ci-local proof: absent image fails with preparation instructions'
export MOCK_MISSING=0
bash scripts/ci-local.sh run
echo 'ci-local proof: offline flags, no host mounts, host .env excluded'
export MOCK_RUN_EXIT=37
status=0
bash scripts/ci-local.sh run || status=$?
[[ $status == 37 ]]
echo 'ci-local proof: container failure propagated'

source scripts/tool.sh
tool_sqlc arm64
export MOCK_SQLC_VERSION=$VERSION
[[ $(tool_path sqlc) == bin/sqlc ]]
echo 'ci-local proof: cached sqlc accepted using version subcommand'
echo 'ci-local proof: PASS (mock boundary, not container acceptance)'
