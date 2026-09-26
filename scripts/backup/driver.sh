#!/usr/bin/env bash
# driver.sh — dispatch to the backup drivers named in SIERX_BACKUP_DRIVERS, and
# assert the six-verb contract from ADR-017.
#
#   driver.sh <driver> <verb> [args...]   run one verb on one driver
#   driver.sh --contract <driver>         assert the driver implements the contract
#   driver.sh --list                      the configured drivers, in order
#
# The contract check is the reason this file exists rather than callers
# invoking driver-*.sh directly: a driver missing a verb, or one whose verb
# exits 0 without doing anything, fails here rather than at 3am. `backup`
# printing nothing and `describe` printing nothing are both "exited 0 without
# doing anything" — both are caught.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

VERBS=(init backup verify restore-to retention describe)

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

die() { echo "driver.sh: $*" >&2; exit 1; }

drivers() {
  local list=${SIERX_BACKUP_DRIVERS:-}
  [[ -n $list ]] || die "SIERX_BACKUP_DRIVERS is unset (see .env.example)"
  echo "${list//,/ }"
}

driver_script() {
  local d=$1 path=scripts/backup/driver-$1.sh
  [[ -f $path ]] || die "no driver '$d' (expected $path)"
  echo "$path"
}

run_verb() {
  local d=$1 verb=$2; shift 2
  local script; script=$(driver_script "$d")
  # Each verb is a function inside the driver script, so the contract check can
  # see which ones exist rather than discovering a missing verb by running it.
  bash "$script" "$verb" "$@"
}

# contract DRIVER — asserts the shape of the driver, not the correctness of a
# backup. Correctness is conformance.sh's job.
contract() {
  local d=$1 script rc=0 verb
  script=$(driver_script "$d")
  echo "contract: $d ($script)"

  for verb in "${VERBS[@]}"; do
    if bash "$script" --has-verb "$verb"; then
      printf '  %-12s present\n' "$verb"
    else
      printf '  %-12s MISSING\n' "$verb"
      rc=1
    fi
  done

  # describe must say something: it is what PROGRESS.md and /healthz read.
  local out
  if ! out=$(run_verb "$d" describe 2>&1); then
    echo "  describe     FAILED: $out"; rc=1
  elif [[ -z ${out//[[:space:]]/} ]]; then
    echo "  describe     exited 0 but printed nothing (ADR-017: one line, name/version/targets)"; rc=1
  elif [[ $(wc -l <<<"$out") -ne 1 ]]; then
    echo "  describe     printed $(wc -l <<<"$out") lines, contract says one"; rc=1
  else
    echo "  describe     -> $out"
  fi

  # init must be idempotent: running it twice must still exit 0. The verb's own
  # message is the useful part — a driver that cannot init usually says exactly
  # what is missing — so it is reported rather than discarded.
  if ! init_out=$(run_verb "$d" init 2>&1); then
    echo "  init         FAILED on first run: ${init_out%%$'\n'*}"; rc=1
  elif ! run_verb "$d" init >/dev/null 2>&1; then
    echo "  init         not idempotent — second run failed (ADR-017)"; rc=1
  else
    echo "  init         idempotent"
  fi

  # restore-to must refuse to run without a dsn rather than silently succeeding.
  if run_verb "$d" restore-to >/dev/null 2>&1; then
    echo "  restore-to   exited 0 with no dsn argument (ADR-017: restores into <dsn>)"; rc=1
  else
    echo "  restore-to   requires a dsn"
  fi

  if [[ $rc -eq 0 ]]; then echo "contract: $d OK"; else echo "contract: $d FAILED"; fi
  return $rc
}

case ${1:-} in
  --list)     drivers ;;
  --contract) shift; [[ $# -eq 1 ]] || die "usage: driver.sh --contract <driver>"; contract "$1" ;;
  --contract-all)
              rc=0
              for d in $(drivers); do contract "$d" || rc=1; done
              exit $rc ;;
  "")         die "usage: driver.sh <driver> <verb> [args] | --contract <driver> | --list" ;;
  *)          d=$1; shift
              [[ $# -ge 1 ]] || die "usage: driver.sh $d <verb> [args]"
              verb=$1; shift
              printf '%s\n' "${VERBS[@]}" | grep -qx "$verb" || die "unknown verb '$verb'"
              run_verb "$d" "$verb" "$@" ;;
esac
