#!/usr/bin/env bash
# Exercise the runner without requiring Go or PostgreSQL.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/scripts" "$scratch/bin"
cp "$root/scripts/test-go.sh" "$scratch/scripts/"
cd "$scratch"
git init -q

cat > bin/go <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ ${DATABASE_URL:-} == "$EXPECTED_DATABASE_URL" ]] || exit 91
[[ $# == 5 && $1 == test && $2 == -v && $3 == ./internal/store/... && $4 == -count=1 && $5 == '-run=TestOne|TestTwo' ]] || exit 92
echo 'fake go invoked'
exit "${FAKE_GO_EXIT:-0}"
SH
chmod +x bin/go
export PATH="$scratch/bin:$PATH"
unset DATABASE_URL

run() { bash scripts/test-go.sh ./internal/store/... -count=1 '-run=TestOne|TestTwo'; }
reject() {
  local label=$1 output
  if output=$(run 2>&1); then
    echo "test-go proof FAILED: $label was accepted" >&2; exit 1
  fi
  [[ $output == *'DATABASE_URL is missing or empty'* && $output != *'fake go invoked'* ]]
  echo "test-go proof: $label rejected before Go runs"
}

reject 'missing .env and environment'
printf '# comment\nDATABASE_URL=\n' > .env
reject 'empty .env value'

# No trailing newline, CRLF comment, whitespace and literal shell syntax.
printf '# comment\r\n  DATABASE_URL = fixture-from-file\nUNRELATED=$(touch SHOULD_NOT_EXIST)' > .env
export EXPECTED_DATABASE_URL=fixture-from-file
run >/dev/null
[[ ! -e SHOULD_NOT_EXIST ]]
echo 'test-go proof: .env loaded literally; arguments preserved'

export DATABASE_URL=fixture-from-environment EXPECTED_DATABASE_URL=fixture-from-environment
run >/dev/null
echo 'test-go proof: exported environment wins over .env'

export DATABASE_URL=
reject 'explicitly empty environment override'

export DATABASE_URL=fixture-from-environment FAKE_GO_EXIT=23
status=0
run >/dev/null || status=$?
[[ $status == 23 ]]
echo 'test-go proof: Go failure exit status preserved'
echo 'test-go proof: PASS'
