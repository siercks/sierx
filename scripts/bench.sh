#!/usr/bin/env bash
# bench.sh — the two benchmark targets ADR-016 defines, plus baseline capture.
#
#   smoke     Run every scenario once. Assert none ERRORS, print timings, list
#             skipped scenarios BY NAME, exit 0 regardless of timing. This is
#             what CI runs inside gate-0: a shared runner has neither the Pi's
#             performance profile nor stable timing, so a threshold gate there
#             is either permanently red or meaningless noise.
#   baseline  Capture reference-hardware numbers into test/bench/baseline.json.
#   gate      Assert the §12 thresholds against that baseline. Exits nonzero
#             with "no baseline" until task 2.16, which is the documented
#             behaviour, not a failure to fix.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BASELINE=test/bench/baseline.json
BENCHTIME=${BENCHTIME:-5x}

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

run_benchmarks() {   # prints raw `go test -bench` output, tees to a file
  local out=$1
  go test ./test/bench/... -run '^$' -bench . -benchtime "$BENCHTIME" -v 2>&1 | tee "$out"
}

smoke() {
  local out; out=$(mktemp); trap "rm -f '$out'" RETURN
  local rc=0
  run_benchmarks "$out" >/dev/null || rc=1

  echo "--- timings"
  grep -E '^Benchmark[A-Za-z0-9_]+(-[0-9]+)?[[:space:]]+[0-9]' "$out" || echo "(none ran)"

  echo "--- skipped scenarios (by name)"
  # Task 0.14: skipped scenarios are named, never silently dropped. A skip
  # line's message carries the §12 scenario name and the reason.
  if grep -qE '^ *--- SKIP' "$out"; then
    grep -B1 -E '^ *--- SKIP' "$out" | grep -E '^ *(bench_test|bulk_test)\.go:[0-9]+:' \
      | sed -E 's/^ *[a-z_]+\.go:[0-9]+: /  /' || true
    grep -E '^ *--- SKIP' "$out" | sed -E 's/^ *--- SKIP: /  (test) /'
  else
    echo "  none"
  fi

  # A benchmark that errors is a real failure: it means a query stopped working
  # or a benchmark stopped compiling, which is exactly what CI can detect.
  if [[ $rc -ne 0 ]] || grep -qE '^(--- FAIL|FAIL|panic:)' "$out"; then
    echo "bench-smoke: FAILED — a benchmark errored (not a threshold miss)" >&2
    grep -E '^(--- FAIL|FAIL|panic:|.*\.go:[0-9]+:)' "$out" | head -20 >&2
    return 1
  fi
  echo "bench-smoke: OK (no scenario errored; thresholds not asserted here — ADR-016)"
  return 0
}

# parse_ns NAME FILE -> ns/op for a benchmark, or empty. Never fails: a skipped
# benchmark has no ns/op line, and under `set -e` a failing command
# substitution would abort the caller's loop.
parse_ns() {
  grep -E "^$1(-[0-9]+)?[[:space:]]" "$2" 2>/dev/null \
    | awk '{for (i=1;i<=NF;i++) if ($i=="ns/op") print $(i-1)}' | head -1 || true
}

baseline() {
  local out; out=$(mktemp); trap "rm -f '$out'" RETURN
  run_benchmarks "$out" >/dev/null || { echo "bench-baseline: benchmarks failed; refusing to record a baseline" >&2; return 1; }

  local host kernel
  host=$(uname -m); kernel=$(uname -r)
  {
    echo "{"
    echo "  \"recorded\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
    echo "  \"arch\": \"$host\","
    echo "  \"kernel\": \"$kernel\","
    echo "  \"benchtime\": \"$BENCHTIME\","
    echo "  \"results\": {"
    local first=1 name ns
    while read -r name; do
      ns=$(parse_ns "$name" "$out")
      [[ -z $ns ]] && continue
      [[ $first -eq 1 ]] || echo ","
      first=0
      printf '    "%s": %s' "$name" "$ns"
    done < <(grep -oE '^Benchmark[A-Za-z0-9_]+' "$out" | sort -u)
    echo
    echo "  }"
    echo "}"
  } > "$BASELINE"
  echo "bench-baseline: wrote $BASELINE on $host"
  cat "$BASELINE"
}

gate() {
  if [[ ! -f $BASELINE ]]; then
    echo "gate-bench: no baseline — §12's thresholds are measured on the Pi 5" >&2
    echo "  reference box, which does not exist until task 2.16 (ADR-016)." >&2
    echo "  Run 'make bench-baseline' there, commit $BASELINE, then this gate" >&2
    echo "  becomes meaningful. This exit is expected until then." >&2
    return 1
  fi
  local out; out=$(mktemp); trap "rm -f '$out'" RETURN
  run_benchmarks "$out" >/dev/null || { echo "gate-bench: a benchmark errored" >&2; return 1; }

  local rc=0 name ns budget_ms ns_ms
  # Scenario-to-benchmark mapping. A §12 row with no benchmark is a gate that
  # cannot fail, so the mapping is explicit and the unmapped rows are listed.
  while IFS='|' read -r name budget_ms; do
    [[ -z $name ]] && continue
    ns=$(parse_ns "$name" "$out")
    if [[ -z $ns ]]; then
      echo "  $name: did not run"; rc=1; continue
    fi
    ns_ms=$(awk -v n="$ns" 'BEGIN{printf "%.1f", n/1000000}')
    if awk -v n="$ns" -v b="$budget_ms" 'BEGIN{exit !(n/1000000 > b)}'; then
      echo "  FAIL $name: ${ns_ms}ms exceeds ${budget_ms}ms (§12)"; rc=1
    else
      echo "  ok   $name: ${ns_ms}ms within ${budget_ms}ms"
    fi
  done <<'MAP'
BenchmarkBoardView500|150
BenchmarkItemDetail|100
BenchmarkDescendantRollupDepth6|50
BenchmarkDeltaSync50|80
BenchmarkFullTextSearch|300
BenchmarkRollupRecompute200|2000
MAP

  echo "gate-bench: §12 rows not yet asserted — sxq query (phase 3), steady-state RSS and cold start (task 1.1)"
  if [[ $rc -eq 0 ]]; then echo "gate-bench: OK"; fi
  return $rc
}

case ${1:-smoke} in
  smoke)    smoke ;;
  baseline) baseline ;;
  gate)     gate ;;
  *)        echo "usage: $0 smoke|baseline|gate" >&2; exit 2 ;;
esac
