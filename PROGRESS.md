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

- none

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
- [ ] 0.3 Migration tooling and extensions
- [ ] 0.4 Schema: all of SPEC §4
- [ ] 0.5 Invariant enforcement in the database
- [ ] 0.6 Sequence counter and partition maintenance
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
