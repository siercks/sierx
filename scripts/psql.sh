#!/usr/bin/env bash
# psql.sh — run psql against DATABASE_URL (from the environment or .env) with
# ON_ERROR_STOP. Used by make targets that execute SQL files without the
# container round-trip db.sh psql performs.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# Environment wins; .env fills the gaps. The assignment is an `if` and not
# `[[ ... ]] && export` on purpose: under `set -e` the && form returns 1 the
# first time a variable is ALREADY set, which killed the script silently with
# no output and exit 1 — invisible whenever .env happened to define something
# the caller had already exported.
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
[[ -n ${DATABASE_URL:-} ]] || { echo "psql.sh: DATABASE_URL is unset" >&2; exit 1; }
exec psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 "$@"
