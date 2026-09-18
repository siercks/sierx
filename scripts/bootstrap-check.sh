#!/usr/bin/env bash
# bootstrap-check — toolchain versions match the pins; required inputs present.
#
# BUILD §5 task 0.1 step 6, ADR-010. One line per check. Exit nonzero on any
# toolchain failure, on an unset PGBACKREST_REPO_TYPE / PGBACKREST_REPO_PATH,
# or on PGBACKREST_REPO_TYPE=posix when SIERX_ENV is anything other than dev.
#
# Reads the environment. If an untracked .env exists it is loaded for any
# variable the environment does not already set — the example file is never
# consulted (ADR-010: "bootstrap-check reads the environment, not the example
# file"). Values printed here may end up pasted into PROGRESS.md, so this
# script prints versions and verdicts only, never a configured value.
set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || dirname "$0")/."

fail=0
ok()   { printf '%-10s OK    %s\n' "$1" "$2"; }
bad()  { printf '%-10s FAIL  %s\n' "$1" "$2"; fail=1; }
info() { printf '%-10s INFO  %s\n' "$1" "$2"; }

# ---- .env loader: environment wins, .env fills the gaps ------------------
load_dotenv() {
  local file=$1 line key val
  [[ -f $file ]] || return 0
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}                      # strip comments
    line=${line#"${line%%[![:space:]]*}"} # ltrim
    line=${line%"${line##*[![:space:]]}"} # rtrim
    [[ -z $line || $line != *=* ]] && continue
    key=${line%%=*}; val=${line#*=}
    key=${key%"${key##*[![:space:]]}"}
    val=${val#"${val%%[![:space:]]*}"}
    [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -z ${!key+x} ]]; then export "$key=$val"; fi
  done < "$file"
}
load_dotenv .env

# ---- go ------------------------------------------------------------------
go_pin=$(awk '$1=="go"{print $2; exit}' go.mod)
if command -v go >/dev/null 2>&1; then
  go_have=$(go version | awk '{print $3}' | sed 's/^go//')
  if [[ ${go_have%.*} == "${go_pin%.*}" ]]; then
    # Same release line. The patch level may run ahead of the pin (security
    # releases); it may not fall behind it.
    have_patch=${go_have##*.}; pin_patch=${go_pin##*.}
    if [[ ${have_patch:-0} -ge ${pin_patch:-0} ]]; then
      ok go "go${go_have} (go.mod pins ${go_pin})"
    else
      bad go "go${go_have} is older than the go.mod pin ${go_pin}"
    fi
  else
    bad go "go${go_have} is not on the ${go_pin%.*} line pinned in go.mod"
  fi
else
  bad go "go not found; go.mod pins ${go_pin}"
fi

# ---- node ----------------------------------------------------------------
node_pin=$(tr -d '[:space:]' < .nvmrc)
if command -v node >/dev/null 2>&1; then
  node_have=$(node -v)                       # vNN.x.y
  node_major=${node_have#v}; node_major=${node_major%%.*}
  if [[ $node_major == "$node_pin" ]]; then
    ok node "${node_have} (.nvmrc pins ${node_pin})"
  else
    bad node "${node_have} is not the major pinned in .nvmrc (${node_pin})"
  fi
else
  bad node "node not found; .nvmrc pins ${node_pin}"
fi

# ---- podman --------------------------------------------------------------
if command -v podman >/dev/null 2>&1; then
  ok podman "$(podman --version 2>/dev/null | head -1)"
  have_podman=1
else
  bad podman "podman not found (BUILD §1: rootless Podman, no Docker)"
  have_podman=0
fi

# ---- psql: >= 18, or absent but containerized ---------------------------
if command -v psql >/dev/null 2>&1; then
  psql_ver=$(psql --version | awk '{print $3}')
  if [[ ${psql_ver%%.*} -ge 18 ]]; then
    ok psql "psql ${psql_ver}"
  else
    bad psql "psql ${psql_ver} is older than 18 (BUILD §1: PostgreSQL 18)"
  fi
elif [[ $have_podman -eq 1 ]]; then
  ok psql "absent; using the containerized client (make db-psql, task 0.2)"
else
  bad psql "psql not found and no podman to containerize it"
fi

# ---- sign-offs: informational, never a failure --------------------------
if [[ -f PROGRESS.md ]]; then
  while IFS= read -r line; do
    info signoff "${line#- \[ \] }"
  done < <(awk '/^## Sign-offs/{f=1;next} /^## /{f=0} f && /^- \[ \]/' PROGRESS.md)
fi

# ---- backup repository target (ADR-010) ---------------------------------
env_name=${SIERX_ENV:-}
if [[ -z ${PGBACKREST_REPO_TYPE:-} ]]; then
  bad backup "PGBACKREST_REPO_TYPE is unset (ADR-010; see .env.example)"
elif [[ -z ${PGBACKREST_REPO_PATH:-} ]]; then
  bad backup "PGBACKREST_REPO_PATH is unset (ADR-010; see .env.example)"
elif [[ $PGBACKREST_REPO_TYPE == posix && $env_name != dev ]]; then
  bad backup "PGBACKREST_REPO_TYPE=posix is a dev fixture; SIERX_ENV is '${env_name:-unset}' (ADR-010)"
elif [[ $PGBACKREST_REPO_TYPE != posix && $PGBACKREST_REPO_TYPE != sftp && $PGBACKREST_REPO_TYPE != s3 ]]; then
  bad backup "PGBACKREST_REPO_TYPE must be posix | sftp | s3"
else
  ok backup "repository type ${PGBACKREST_REPO_TYPE}, path set, SIERX_ENV=${env_name:-unset}"
fi

exit $fail
