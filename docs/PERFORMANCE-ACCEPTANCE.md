# Phase 2 performance evidence

`make bench-http` records authenticated, read-only HTTP latency and response
bytes for a selected project containing exactly 10,000 active items. It requires
one existing item key in that project, warms each scenario, and records 500
measured samples by default. The report includes p50, p95, maximum, sample
count, response bytes, operating system, architecture, CPU model and memory
size. Percentiles use the nearest-rank method.

The request scenarios are a 100-item project page, item detail plus 50 history
rows, an indexed SXQ project query, one item rollup, a 50-change page, and a
full-text SXQ query. Every request is a GET. Login creates the measurement
session and the script attempts logout in a `finally` block. It does not log
credentials, response content, hostnames, item keys, project prefixes or
request paths. Its report compares client-side round-trip times with SPEC
budgets and includes TLS/network time. For server-path measurements, point it
at a direct HTTPS origin on the host being measured and label the fixture
without including private topology.

Run it against a disposable, quiescent benchmark project where possible. Never
seed or reset the daily-use backlog to create the fixture. The script refuses
to report latency unless the selected project has exactly 10,000 active items.
Keep credentials in the protected environment, not in shell history or the
report. Save and review the report privately:

```bash
umask 077
export SIERX_BENCH_URL='https://direct-test-origin'
export SIERX_BENCH_TARGET_LABEL='Rocky 10 / confirmed testbed hardware'
export SIERX_BENCH_ITEM='SRX-10000'
export SIERX_BENCH_EMAIL='operator@example.invalid'
read -rsp 'Sierx password: ' SIERX_BENCH_PASSWORD; export SIERX_BENCH_PASSWORD; echo
python3 -B scripts/bench-http.py > "$HOME/bench-http.json"
unset SIERX_BENCH_PASSWORD
```

`SIERX_BENCH_CODE` may provide a fresh second-factor code when required. The
default report uses 20 warmups and 500 measured samples per scenario; measured
sample count cannot be lowered below 500. Public/tunnel measurements are useful
for user-perceived latency but include network and gateway overhead and should
be reported separately from direct-host results.

This report does not measure steady-state process RSS or cold-start time. Those
remain separate acceptance measurements and are not inferred from Go
`ns/op` averages. Manual operator evidence records the hardware model and
results in `docs/PHASE-2-ACCEPTANCE.md` without hostnames, credentials or
database contents.
