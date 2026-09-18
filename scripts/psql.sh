#!/usr/bin/env bash
# psql.sh — run psql against DATABASE_URL (from the environment or .env) with
# ON_ERROR_STOP. Used by make targets that execute SQL files without the
# container round-trip db.sh psql performs.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
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
    [[ -z ${!key+x} ]] && export "$key=$val"
  done < "$file"
}
load_dotenv .env
[[ -n ${DATABASE_URL:-} ]] || { echo "psql.sh: DATABASE_URL is unset" >&2; exit 1; }
exec psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 "$@"
