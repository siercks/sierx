#!/usr/bin/env bash
# render-conf.sh — render deploy/pgbackrest/pgbackrest.conf.tmpl from the
# environment (BUILD task 0.11 step 5, §14.4).
#
#   render-conf.sh <output-path>     write the rendered config (mode 0600)
#   render-conf.sh --check <path>    fail if <path> differs from a fresh render
#
# The config is never hand-edited. --check exists so a drifted file is a build
# failure rather than a discovery during an incident.
#
# Every placeholder must be set: an unset one would render an empty value that
# pgBackRest accepts and then behaves surprisingly around.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

TMPL=deploy/pgbackrest/pgbackrest.conf.tmpl
VARS=(PGBACKREST_REPO_TYPE PGBACKREST_REPO_PATH PGBACKREST_CIPHER_PASS
      PGBACKREST_SPOOL_PATH PGBACKREST_PROCESS_MAX PGBACKREST_STANZA
      PGBACKREST_PG1_PATH PGBACKREST_PG1_PORT PGBACKREST_PG1_USER)

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
die() { echo "render-conf: $*" >&2; exit 1; }

# Defaults for the two tuning values only; everything else must be supplied.
: "${PGBACKREST_STANZA:=sierx}"
: "${PGBACKREST_PROCESS_MAX:=2}"
: "${PGBACKREST_PG1_PORT:=5432}"

render() {
  local out tmp v
  out=$1
  for v in "${VARS[@]}"; do
    [[ -n ${!v:-} ]] || die "$v is unset — every placeholder must be supplied (§14.4)"
  done
  tmp=$(mktemp); chmod 600 "$tmp"
  cp "$TMPL" "$tmp"
  for v in "${VARS[@]}"; do
    # Values may contain / and &, so substitute with a literal replacement
    # rather than a sed expression built from them.
    python3 - "$tmp" "@$v@" "${!v}" <<'PY'
import sys
path, placeholder, value = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f:
    text = f.read()
with open(path, "w") as f:
    f.write(text.replace(placeholder, value))
PY
  done
  # Optional repository transport inputs remain private and are rendered only
  # for the selected transport. Never interpolate shell or permit INI injection.
  python3 - "$tmp" <<'PYCONF'
import os, sys
kind=os.environ.get('PGBACKREST_REPO_TYPE')
fields={
 'sftp': [('sftp-host','SFTP_HOST'),('sftp-host-user','SFTP_USER'),('sftp-private-key-file','SFTP_PRIVATE_KEY'),('sftp-known-host','SFTP_KNOWN_HOSTS')],
 's3': [('s3-bucket','S3_BUCKET'),('s3-endpoint','S3_ENDPOINT'),('s3-region','S3_REGION'),('s3-key','S3_KEY'),('s3-key-secret','S3_SECRET')],
 'posix': []
}
if kind not in fields: raise SystemExit('Unsupported repository type')
extra=[]
for option,suffix in fields[kind]:
    key='PGBACKREST_'+suffix; value=os.environ.get(key,'')
    if not value or any(c in value for c in '\r\n\0'): raise SystemExit(key+' must be a single nonempty value')
    extra.append('repo1-'+option+'='+value)
if kind=='sftp': extra.append('repo1-sftp-host-key-check-type=strict')
path=sys.argv[1]
with open(path) as f: text=f.read()
text=text.replace('[global]','[global]\n'+'\n'.join(extra))
with open(path,'w') as f: f.write(text)
PYCONF
  if grep -q '@[A-Z_]*@' "$tmp"; then
    die "unsubstituted placeholder remains: $(grep -o '@[A-Z_]*@' "$tmp" | sort -u | tr '\n' ' ')"
  fi
  mv "$tmp" "$out"
  chmod 600 "$out"
  echo "render-conf: wrote $out (0600)"
}

case ${1:-} in
  --check)
    [[ $# -eq 2 ]] || die "usage: $0 --check <path>"
    [[ -f $2 ]] || die "$2 does not exist"
    tmp=$(mktemp); trap "rm -f '$tmp'" EXIT
    render "$tmp" >/dev/null
    if diff -q "$2" "$tmp" >/dev/null; then
      echo "render-conf: $2 matches a fresh render"
    else
      die "$2 has drifted from the template and environment — re-render it, do not hand-edit"
    fi ;;
  "")  die "usage: $0 <output-path> | --check <path>" ;;
  *)   render "$1" ;;
esac
