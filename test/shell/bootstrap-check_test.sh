#!/usr/bin/env bash
# Prove the security floor rejects old cached runtimes without a real database.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/scripts" "$scratch/bin"
cp "$root/scripts/bootstrap-check.sh" "$scratch/scripts/"
cp "$root/.nvmrc" "$root/go.mod" "$scratch/"
cd "$scratch"
git init -q
cat > bin/go <<'SH'
#!/usr/bin/env bash
printf 'go version go%s linux/amd64\n' "$(awk '$1=="go"{print $2;exit}' go.mod)"
SH
cat > bin/node <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$MOCK_NODE_VERSION"
SH
cat > bin/podman <<'SH'
#!/usr/bin/env bash
echo 'podman version 5.6.0'
SH
cat > bin/psql <<'SH'
#!/usr/bin/env bash
echo 'psql (PostgreSQL) 18.6'
SH
chmod +x bin/*
export PATH="$scratch/bin:$PATH"
export SIERX_ENV=dev PGBACKREST_REPO_TYPE=posix PGBACKREST_REPO_PATH=fixture
unset DATABASE_URL
for version in v24.22.1 v24.22.2 v24.23.0 v24.100.0; do
  MOCK_NODE_VERSION=$version bash scripts/bootstrap-check.sh > result
  grep -q '^node .*OK' result
done
for version in v24.21.0 v24.22.0 v22.23.4 v26.12.1 v24.22.1-rc.1 invalid; do
  if MOCK_NODE_VERSION=$version bash scripts/bootstrap-check.sh > result; then
    echo "bootstrap-check proof FAILED: accepted $version" >&2
    exit 1
  fi
  grep -q '^node .*FAIL' result
done
printf '24\n' > .nvmrc
if MOCK_NODE_VERSION=v24.22.1 bash scripts/bootstrap-check.sh > result; then
  echo 'bootstrap-check proof FAILED: accepted an incomplete Node pin' >&2
  exit 1
fi
grep -q 'complete stable Node version' result
echo 'bootstrap-check proof: PASS (security floor, same major, stable versions)'
