#!/usr/bin/env bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cat > "$scratch/client" <<'SH'
#!/usr/bin/env bash
name=${0##*/}
if [[ ${1:-} == --version ]]; then
  version=18.6
  [[ $name == "${OLD_CLIENT:-}" ]] && version=16.15
  echo "$name (PostgreSQL) $version"
else
  echo "${SERVER_VERSION:-180006}"
fi
SH
chmod +x "$scratch/client"
for tool in psql pg_dump pg_restore; do cp "$scratch/client" "$scratch/$tool"; done
export PATH="$scratch:$PATH" DATABASE_URL=postgres://fixture:fixture@localhost/fixture
bash "$root/scripts/check-postgres-tools.sh"
for tool in psql pg_dump pg_restore; do
  if OLD_CLIENT=$tool bash "$root/scripts/check-postgres-tools.sh" > "$scratch/result" 2>&1; then
    echo "postgres-tools proof FAILED: old $tool accepted" >&2; exit 1
  fi
  grep -q "$tool must be PostgreSQL 18" "$scratch/result"
done
for version in 170006 190000 invalid; do
  if SERVER_VERSION=$version bash "$root/scripts/check-postgres-tools.sh" > "$scratch/result" 2>&1; then
    echo "postgres-tools proof FAILED: server $version accepted" >&2; exit 1
  fi
done
echo 'postgres-tools proof: PASS (each old client and incompatible server rejected)'
