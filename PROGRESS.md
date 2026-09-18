# sierx build progress

The agent's only progress claim. Append and check boxes; never rewrite history.
A checked box with no pasted acceptance output is treated as red (BUILD §0.4).

**Current phase:** 0
**Phase 2 deadline anchor:** 2026-09-12
**Phase 2 deadline:** 2026-10-10

## Sign-offs (human writes these — see BUILD §4.0)

- [x] ADR-002 approved — 2026-09-12 — one sequence value per event row
- [x] ADR-005 approved — 2026-09-12 — rollups maintained in the store layer
- [x] ADR-012 approved — 2026-09-12 — cross-project moves rejected in v1
- [x] ADR-014 approved — 2026-09-12 — Markdown with raw HTML disabled at the parser
- [x] ADR-010 dev repository target defined — 2026-09-12 — `posix` to a local
      path, no decision required (BUILD ADR-010)
- [ ] ADR-010 **deployment** repository target — set at task 2.16 in the host
      env file. `sftp` recommended. `bootstrap-check` rejects the dev `posix`
      target whenever `SIERX_ENV` is not `dev`, so this cannot be skipped

## Cuts taken (BUILD §1.2)

- none

## Deviations from the guide

- 2026-09-12, task 0.3: goose runs as a pinned release binary (v3.28.0,
  sha256-verified into gitignored `bin/`) rather than `go tool goose`, because
  the agent's sandbox cannot reach the Go module proxy. Switch to `go tool
  goose` at task 0.8 when go.mod gets its dependencies, so the pin is in
  go.mod and visible to `gate-license`.

- 2026-09-12, task 0.2: acceptance uses `show lc_collate`, which PostgreSQL 18
  rejects (GUC removed in PG 16). Verified with `select datcollate from
  pg_database where datname = current_database()` instead.
- 2026-09-12, task 0.2: the `postgres:18` digest is a `# supplied by human`
  input in the agent's environment (no registry egress). `make db-pin` resolves
  it on any machine with registry access; `db-up`/`db-reset` refuse to run on
  the placeholder.

- 2026-09-12, task 0.1: `docs/HANDOVER.md` is committed although it is not in
  the task's Files list — the kickoff prompt's read order names it. HANDOVER §1
  said the five doc files were already committed; the repository held only
  `LICENSE`, so task 0.1 installed them as BUILD steps 3–5 and 7 describe.
- 2026-09-12, task 0.1: `prove-gates` (task 0.12) does not exist yet, so the
  gate's proof ships as `scripts/gate-notopology.sh --prove` (`make
  prove-notopology`). Task 0.12's `prove-gates.sh` should discover `gate-*`
  targets and call `scripts/<gate>.sh --prove`.

## Open questions raised

- 2026-09-12, task 0.6: `deploy/quadlet/sierx-maintenance.service` (added — a
  timer needs a service; not in the Files list) runs `podman exec sierx
  sierxctl partitions ensure --months-ahead 1`. The application container's
  name is not specified until task 2.16; `sierx` is a placeholder to confirm
  or change there.
- 2026-09-12, task 0.6: the partition logic is a SQL function
  (`change_event_ensure_partitions`) with `sierxctl` as a one-line caller, so
  the idempotence test runs from psql. The guide names only the CLI; if the
  logic is wanted in Go instead, it is a mechanical move.

- 2026-09-12, task 0.5 (ADR-003, no new ADR needed): observed on PG 18.6 that
  `item_project_rank_uniq`, being DEFERRABLE, is enforced at end of statement
  rather than per row while immediate. The rebalance path's `SET CONSTRAINTS
  DEFERRED` is therefore optional, not required. Recorded so the ADR's
  rationale can be corrected when it is next amended.

---

## Phase 0 — Schema, migrations, seed, CI skeleton

Gate: `make gate-0`. Tasks in order; one commit each (BUILD §3.3).

- [ ] 0.1 Repository skeleton and toolchain pins — **implemented; acceptance
      pending on the dev host.** The agent's sandbox had no Go, no Podman, and
      Node 22, so `make bootstrap-check` cannot go green there. Run the
      acceptance on the RHEL/Podman dev host, paste its output here, check
      the box, and amend this commit (one task, one commit — BUILD §3.3).
      ```
      $ make gate-notopology
      gate-notopology: OK (no topology in committable files)
      $ make prove-notopology
      prove: rfc1918 192.168/16: gate went red — OK
      prove: rfc1918 10/8: gate went red — OK
      prove: rfc1918 172.16/12: gate went red — OK
      prove: .lan hostname: gate went red — OK
      prove: .internal hostname: gate went red — OK
      prove: .env value leak: gate went red — OK
      prove: .env == example: gate GREEN — OK
      prove: clean tree: gate GREEN — OK
      $ make bootstrap-check          # sandbox, dev .env present — expected red
      go         FAIL  go not found; go.mod pins 1.27.1
      node       FAIL  v22.22.2 is not the major pinned in .nvmrc (24)
      podman     FAIL  podman not found (BUILD §1: rootless Podman, no Docker)
      psql       FAIL  psql not found and no podman to containerize it
      signoff    INFO  ADR-010 **deployment** repository target — set at task 2.16 in the host
      backup     OK    repository type posix, path set, SIERX_ENV=dev
      $ SIERX_ENV=staging make bootstrap-check | grep backup   # ADR-010 guard
      backup     FAIL  PGBACKREST_REPO_TYPE=posix is a dev fixture; SIERX_ENV is 'staging' (ADR-010)
      $ test -f LICENSE && test -f NOTICE && test -f docs/SPEC.md && echo files-ok
      files-ok
      ```
- [ ] 0.2 Dev database — **implemented; ⚠ partially BLOCKED: acceptance needs
      the dev host.** (1) No Podman in the agent sandbox, so `make db-up` was not
      run. (2) The `postgres:18` image digest cannot be resolved without registry
      access; the unit carries a placeholder that `db.sh` refuses to start, and
      `make db-pin` resolves and writes it — run that first on the dev host.
      What was verified: `bash -n` on `scripts/db.sh`; `db-reset` refuses when
      `SIERX_ENV=staging` and refuses before dropping anything while unpinned;
      the `make db-psql -- -c "..."` argument path via a stub podman; and a
      native PostgreSQL 18.6 started with the unit's exact initdb args and
      `-c` flags:
      ```
      $ SIERX_ENV=staging make db-reset
      db.sh: db-reset refused: SIERX_ENV is 'staging', not dev
      $ psql "$DATABASE_URL" -Atc "select version()" -c "select datcollate from pg_database where datname=current_database()" \
          -c "show shared_preload_libraries" -c "show log_min_duration_statement" -c "select extname from pg_extension order by 1"
      PostgreSQL 18.6 on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit
      C
      pg_stat_statements
      200ms
      plpgsql
      ```
      Deviation: the acceptance's `show lc_collate` errors on PostgreSQL 18
      (`unrecognized configuration parameter`; the GUC was removed in PG 16).
      `select datcollate from pg_database where datname = current_database()`
      is the equivalent check.
- [x] 0.3 Migration tooling and extensions — 2026-09-12, against PostgreSQL
      18.6 (native, sandbox; see 0.2 note)
      ```
      $ make migrate-updown-up
      fetching goose v3.28.0 (linux_x86_64) ...
      == up
      OK   0001_extensions.sql (29.16ms)
      goose: successfully migrated database to version: 1
      all migrations applied: 1 versions
      == down-to 0
      OK   0001_extensions.sql (10.66ms)
      goose: no migrations to run. current version: 0
      clean at zero: 0 tables, 0 extensions
      == up again
      OK   0001_extensions.sql (22.79ms)
      goose: successfully migrated database to version: 1
      all migrations applied: 1 versions
      ```
- [x] 0.4 Schema: all of SPEC §4 — 2026-09-12, against PostgreSQL 18.6 (native)
      ```
      $ make migrate-updown-up && make schema-snapshot && make schema-diff
      == up
      goose: successfully migrated database to version: 7
      all migrations applied: 7 versions
      == down-to 0
      goose: no migrations to run. current version: 0
      clean at zero: 0 tables, 0 extensions
      == up again
      goose: successfully migrated database to version: 7
      all migrations applied: 7 versions
      schema-snapshot: wrote docs/schema.sql (24 CREATE TABLE statements)
      schema-diff: from-scratch migration matches docs/schema.sql
      ```
      Also proven: editing a migration after the snapshot turns `schema-diff`
      red. 24 = 21 tables in §4 + 3 monthly `change_event` partitions
      (2026-09 … 2026-11). `seq_counter` (§4.7) is created here; task 0.6 adds
      the per-workspace row mechanism.
- [x] 0.5 Invariant enforcement in the database — 2026-09-12, PostgreSQL 18.6
      ```
      $ make test-sql
      NOTICE:  ok   raised  status.name update  [23001 ...]
      NOTICE:  ok   raised  status.key update  [23001 ...]
      NOTICE:  ok   raised  status.category update  [23001 ...]
      NOTICE:  ok   raised  item_type.name update  [23001 ...]
      NOTICE:  ok   raised  item_type.level update  [23001 ...]
      NOTICE:  ok   allowed item_type.is_idea update (not immutable by spec)
      NOTICE:  ok   raised  depth-9 insert  [23514 ... would be at depth 9, maximum is 8 (SPEC §5.3)]
      NOTICE:  ok   allowed depth-8 exists (positive control)
      NOTICE:  ok   raised  path not ending in own id  [23514 ...]
      NOTICE:  ok   raised  parent_id set, path penultimate label is someone else  [23514 ...]
      NOTICE:  ok   raised  parent_id NULL, path has two labels  [23514 ...]
      NOTICE:  ok   raised  parent_id set, single-label path  [23514 ...]
      NOTICE:  ok   raised  update parent_id without rewriting path  [23514 ...]
      NOTICE:  ok   raised  self-ancestry reparent (root under its grandchild)  [23514 ...]
      NOTICE:  ok   raised  reparent under itself  [23514 ...]
      NOTICE:  ok   allowed legal subtree reparent in one statement
      NOTICE:  ok   allowed subtree paths consistent after reparent
      NOTICE:  ok   raised  item pointing at another project's status  [23503 ... "item_status_same_project"]
      NOTICE:  ok   raised  item pointing at another project's type  [23503 ... "item_type_same_project"]
      NOTICE:  ok   raised  item pointing at a nonexistent config version  [23503 ... "item_config_version_exists"]
      NOTICE:  ok   raised  duplicate rank within a project (immediate)  [23505 ... "item_project_rank_uniq"]
      NOTICE:  ok   allowed single-statement rank swap with the constraint immediate
      NOTICE:  ok   raised  rank collision surviving a statement raises immediately  [23505 ...]
      NOTICE:  ok   allowed same collision tolerated mid-transaction when deferred
      NOTICE:  test-sql: 24 checks passed
      ```
      Also proven: dropping `status_immutable_trg` by hand turns `test-sql`
      red. `docs/schema.sql` re-snapshotted for 0008; `schema-diff` green.
      **Finding for ADR-003:** a DEFERRABLE unique constraint is checked at end
      of statement even while immediate, so the single-statement rebalance
      (§5.5) commits without `SET CONSTRAINTS ... DEFERRED`. The decision
      (DEFERRABLE) stands and the deferral step is harmless belt-and-braces;
      the ADR's "checked per row" rationale describes the non-deferrable case.
- [ ] 0.6 Sequence counter and partition maintenance — **SQL half green; Go
      half unverified.** `0009_seq.sql` (seq_counter row created by trigger
      alongside each workspace, backfilled; `change_event_ensure_partitions(n)`
      idempotent creator, no drop), the timer + oneshot service units, and
      `cmd/sierxctl/partitions.go` (a thin `pgx` caller of that function) are
      written. `pgx` cannot be added to go.mod from the agent sandbox (module
      proxy blocked), so `sierxctl` has not been compiled. On the dev host:
      `go get github.com/jackc/pgx/v5@latest && go mod tidy && go mod vendor
      && go build ./cmd/sierxctl && make gate-license` (§0.4: record the
      addition here), then re-run the acceptance and check this box.
      ```
      $ make test-partitions
      NOTICE:  ok   ensure(1): first run created 0, second run created 0, change_event_2026_10 present
      NOTICE:  ok   ensure(6): created 4 more, then 0
      NOTICE:  ok   every workspace has a seq_counter row (1)
      NOTICE:  ok   event routed to the current-month partition
      NOTICE:  test-partitions: passed
      $ make migrate-updown-up && make schema-snapshot && make schema-diff && make test-sql
      ... 9 versions / clean at zero / 9 versions
      schema-snapshot: wrote docs/schema.sql (24 CREATE TABLE statements)
      schema-diff: from-scratch migration matches docs/schema.sql
      NOTICE:  test-sql: 24 checks passed
      ```
- [ ] 0.7 sqlc wiring
- [ ] 0.8 `store.Mutate`: the unit of work
- [ ] 0.9 Seed generator
- [ ] 0.10 Property tests
- [ ] 0.11 Backup and restore harness (all steps runnable; dev target is local)
- [ ] 0.12 CI skeleton, proven to fail
- [ ] 0.13 License gate, SBOM, supply chain
- [ ] 0.14 Benchmark harness

### Phase 0 exit

- gate-0: `<paste the tail of make gate-0>`
- Human gates:
  - [x] ADR-002 signed off — 2026-09-12
  - [x] ADR-005 signed off — 2026-09-12
  - [x] ADR-012 signed off — 2026-09-12
  - [ ] Task 0.11 green — `make backup-conformance && make restore-test`
        against the dev repository (the off-box target binds at task 2.16)
- Pin drift (ADR-019): `<any pin more than one cycle behind, or "none">`
- Deviations: `<none | list>`
- Open questions raised: `<none | list with ADR numbers>`
- Requesting sign-off to enter phase 1.
