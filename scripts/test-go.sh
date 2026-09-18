#!/usr/bin/env bash
# Database-backed Go tests must inherit the same settings as the SQL scripts.
# Child scripts cannot export their .env settings back into make's environment.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Match the existing scripts: environment wins, .env fills gaps, never source
# the file as executable shell code. An explicitly empty value stays empty.
load_dotenv() {
  local file=$1 line key val
  [[ -f $file ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}
    line=${line#"${line%%[![:space:]]*}"}; line=${line%"${line##*[![:space:]]}"}
    [[ -z $line || $line != *=* ]] && continue
    key=${line%%=*}; val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}; val=${val#"${val%%[![:space:]]*}"}
    [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z ${!key+x} ]]; then export "$key=$val"; fi
  done < "$file"
}
load_dotenv .env

if [[ -z ${DATABASE_URL:-} ]]; then
  echo "test-go: DATABASE_URL is missing or empty; set it in .env or export it for the disposable test database. Refusing to report skipped database tests as a pass." >&2
  exit 1
fi

# Verbose output makes individual skipped tests visible in acceptance logs.
exec go test -v "$@"
