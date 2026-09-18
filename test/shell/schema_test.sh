#!/usr/bin/env bash
# Failed or partial dumps must not masquerade as drift or replace a snapshot.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/scripts" "$scratch/docs" "$scratch/bin"
cp "$root/scripts/schema.sh" "$scratch/scripts/"
cd "$scratch"
git init -q
printf 'CREATE TABLE example ();\n' > docs/schema.sql
cp docs/schema.sql expected.sql
printf '#!/usr/bin/env bash\nexit 0\n' > scripts/migrate.sh
printf '#!/usr/bin/env bash\nexit 0\n' > bin/psql
cat > bin/pg_dump <<'SH'
#!/usr/bin/env bash
case ${MOCK_DUMP_MODE:-ok} in
  failed) echo 'pg_dump: server version mismatch' >&2; exit 1 ;;
  partial) echo 'incomplete dump'; exit 1 ;;
  drift) echo 'CREATE TABLE changed ();' ;;
  *) printf '%s\n' '-- Dumped by pg_dump version 18.6' 'CREATE TABLE example ();' ;;
esac
SH
chmod +x bin/*
export PATH="$scratch/bin:$PATH"
export DATABASE_URL=postgres://fixture:fixture@localhost/fixture
for mode in failed partial; do
  export MOCK_DUMP_MODE=$mode
  for operation in diff snapshot; do
    if bash scripts/schema.sh "$operation" > result.log 2>&1; then
      echo "schema proof FAILED: $mode dump accepted for $operation" >&2; exit 1
    fi
    grep -q 'schema.sh: pg_dump failed' result.log
    if grep -q 'migration differs' result.log; then
      echo 'schema proof FAILED: dump failure reported as drift' >&2; exit 1
    fi
    cmp expected.sql docs/schema.sql
  done
done
export MOCK_DUMP_MODE=drift
if bash scripts/schema.sh diff > result.log 2>&1; then
  echo 'schema proof FAILED: actual drift accepted' >&2; exit 1
fi
grep -q 'migration differs' result.log
export MOCK_DUMP_MODE=ok
bash scripts/schema.sh diff
bash scripts/schema.sh snapshot
cmp expected.sql docs/schema.sql
echo 'schema proof: PASS (failed/partial dumps rejected, snapshot preserved, real drift detected)'
