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

- 2026-09-17, three defects found on the first real dev host (arm64, DGX
  Spark), all in the harness rather than the product:
  1. **Every `.env` loader exited silently.** The pattern
     `[[ -z ${!key+x} ]] && export "$key=$val"` returns 1 under `set -e` the
     first time a variable is already set in the environment, killing the
     script with no output and exit 1. Invisible until a `.env` file existed
     AND the caller had exported one of its keys — which is the normal case on
     a real host. Fixed in all 11 scripts by using an `if`.
  2. **`gate-notopology` false positive.** It treated any `.env` value
     differing from the example's default for that key as a secret. Narrowing
     an enumerated list to one of its members therefore flagged every mention
     of that member across the tree. Now a value is exempt if it appears
     anywhere in `.env.example`, which is public by construction; a real host,
     path or secret still is not. A proof case covers it.
  3. **Three invariant checks passed for the wrong reason.**
     `invariants_test.sql` derived item keys from `right(id::text, 12)`, which
     is identical for the `05...005` and `06...005` fixture families, so the
     three ADR-012 composite-FK checks raised a unique violation on
     `item_workspace_id_key_key` instead of the FK error they exist to assert.
     Keys now use the whole id; the three checks raise 23503 against
     `item_status_same_project`, `item_type_same_project` and
     `item_config_version_exists` as intended. The PROGRESS entry for task 0.5
     records the earlier output, which was green for the wrong reason on those
     three lines.
- 2026-09-17: `go.sum` and `vendor/` were regenerated from the real module
  proxy on the dev host. The agent's mirror-built module zips hashed
  differently from the proxy's, so the committed `go.sum` was self-consistent
  but did not match upstream, and the vendored `golang.org/x/text` did not
  compile. An earlier note claiming `go.sum` carried "the real hashes" was
  wrong.

- 2026-09-16, performance (no behaviour change): the property suite dropped
  from 137s to 13s. `VerifyRollups` is unscoped by design — an operator asking
  "is anything wrong" means anything — so a test that created 14 items was
  re-verifying the whole 10k-item seed on every sequence. Added
  `VerifyRollupsForProject` and used it in the tests; the CLI still uses the
  unscoped query. The Go-side comparison also fetches a project's rollups in
  one round trip instead of one query per item. No property was weakened and
  no test-count lowered.
- 2026-09-16: added `make check`, a fast dev loop (vet, both SQL test files,
  store tests, sqlc diff, the three source gates; ~30s). It is NOT a gate and
  is not part of one — `gate-0` is unchanged, and `check` passing is not a
  claim that the phase gate passes. `make sierxctl` and `scripts/sierxctl.sh`
  build `bin/sierxctl` once and reuse it, so the make targets and scripts no
  longer `go run` the CLI on every call. Measured saving: ~85ms per
  invocation, not the seconds first estimated — kept because it is harmless
  and gives the CLI a stable path for the systemd units, not because it is
  fast.

- 2026-09-12, task 0.13: the license gate classifies the LICENSE text of every
  vendored module itself rather than running `go-licenses check`.
  `go-licenses` resolves licenses by downloading modules and carries a large
  dependency tree of its own — both of which this gate exists to constrain.
  The classifier matches distinctive strings from each license text, the same
  method go-licenses' classifier uses, minus the network, and it is proven
  against AGPL, MPL, SSPL, BSL, an unclassifiable license and a missing one.
- 2026-09-12, task order: 0.13's license gate was built before 0.10 because
  0.10's instruction is to clear the property-testing library through
  `make gate-license` before adopting it.

- 2026-09-12, tasks 0.3/0.7: goose and sqlc are pinned release binaries
  (version + per-arch sha256 in `scripts/tool.sh`, fetched into gitignored
  `bin/`) rather than `go tool` entries. Both pull large dependency trees —
  database drivers, a SQL parser — that would enter `go.mod` and
  `gate-license`'s scope without a line of them shipping in the binary. This
  supersedes the earlier note that said to switch to `go tool goose` at 0.8.
- 2026-09-12, environment: the agent sandbox cannot reach `proxy.golang.org`,
  `sum.golang.org`, `golang.org` or `gopkg.in`, but can reach `github.com`. Go
  modules were resolved with `GOPROXY=file:///<local>,direct GOSUMDB=off`,
  where the local filesystem proxy holds `golang.org/x/text`,
  `golang.org/x/sync`, `gopkg.in/yaml.v3` and `gopkg.in/check.v1` mirrored from
  their GitHub repositories. **Nothing in the repository depends on this** — no
  `replace` directives, no vendored fork, and `go.sum` carries the real
  hashes. On a normal network `go mod download` works unmodified. Re-run
  `go mod verify` on the dev host to confirm.

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

- 2026-09-12, task 0.9: the seed cannot backdate `change_event.at` — the
  column defaults to `now()` and `Mutate` does not accept a timestamp, so
  "status transitions spread over ~9 months" is only true of the items' dates
  and the transition order, not of the event timestamps. Cycle-time and
  burndown work (§13, phase 5) needs real historical `at` values. The choice —
  let a caller set `at` under a seed-only flag, or accept that history begins
  at first run — belongs in an ADR before phase 5, not in the seed.

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
- [x] 0.6 Sequence counter and partition maintenance — 2026-09-12 (Go half
      closed in the same session once module egress was worked around)
      ```
      $ make test-partitions
      NOTICE:  ok   ensure(1): first run created 0, second run created 0, change_event_2026_10 present
      NOTICE:  ok   ensure(6): created 4 more, then 0
      NOTICE:  ok   every workspace has a seq_counter row (1)
      NOTICE:  ok   event routed to the current-month partition
      NOTICE:  test-partitions: passed
      $ go build ./cmd/... && go run ./cmd/sierxctl partitions ensure --months-ahead 1
      partitions ensure: 0 created, months-ahead=1
      $ go run ./cmd/sierxctl partitions ensure --months-ahead 3
      created change_event_2026_12
      partitions ensure: 1 created, months-ahead=3
      $ go run ./cmd/sierxctl partitions ensure --months-ahead 3
      partitions ensure: 0 created, months-ahead=3
      ```
- [x] 0.7 sqlc wiring — 2026-09-12
      ```
      $ make sqlc-diff && go build ./...
      sqlc-diff: checked-in generated code matches fresh output
      ```
      sqlc v1.31.1, `sql_package: pgx/v5`, schema read from `migrations/` so
      there is no second schema definition. Queries limited to what 0.8–0.9
      need: workspace/seq allocation, item CRUD + one-statement subtree
      reparent, rollup insert/recompute/verify, events, config and links.
      `ltree` is overridden to `string` (no pgx type; the store passes text and
      lets Postgres cast). Also proven: renaming a query without regenerating
      turns `sqlc-diff` red.
      Note: `models.go` contains structs for the three `change_event`
      partitions declared in 0006. Partitions created later at runtime by
      `change_event_ensure_partitions` do not appear, because sqlc reads
      `migrations/`, so the generated output stays stable month to month.
- [x] 0.8 `store.Mutate`: the unit of work — 2026-09-12
      ```
      $ make test-store
      --- PASS: TestMutateAllocatesOneSeqPerEvent (0.02s)
      --- PASS: TestMutateRejectsChangeWithoutEvents (0.01s)
      --- PASS: TestMutateEmptyIsAnError (0.01s)
      --- PASS: TestMutateCallbackErrorRollsBack (0.01s)
      --- PASS: TestMutatePathAndKey (0.02s)
      --- PASS: TestMutateRollupsAreMaintained (0.02s)
      --- PASS: TestMutateReparentRewritesSubtreeAndRollups (0.03s)
      --- PASS: TestMutateRejectsSelfAncestryAndCrossProject (0.02s)
      --- PASS: TestMutateSoftAndHardDelete (0.02s)
      --- PASS: TestMutateVersionIncrements (0.02s)
      --- PASS: TestMutateConfigVersionOnlyOnCreateAndTransition (0.02s)
      --- PASS: TestMutateSeqGapFreeUnderConcurrency (0.11s)
      --- PASS: TestMutateRankOrderAndRebalance (0.04s)
      ok      github.com/siercks/sierx/internal/store 0.364s
      $ make gate-nodirect && make prove-nodirect
      gate-nodirect: OK (governed tables written only through internal/store)
      prove: INSERT INTO item from internal/api: gate went red — OK
      prove: lowercase multi-line UPDATE item: gate went red — OK
      prove: DELETE FROM comment: gate went red — OK
      prove: INSERT INTO sprint_item: gate went red — OK
      prove: TRUNCATE item_link: gate went red — OK
      prove: item_type/item_rollup writes and a plain SELECT stay green — OK
      prove: clean tree: gate GREEN — OK
      ```
      The §5.1 requirement is met: 8 concurrent writers, 48 events, a cursor
      polled throughout the run, every seq value observed exactly once and no
      gaps. `Mutation` has no way to register a row change without its events
      (ADR-001 as a type property), and no event-count parameter — the seq
      block is sized from the accumulated events (ADR-002).
      Three implementation notes worth keeping:
      - `item.fields` is `jsonb NOT NULL DEFAULT '{}'`; an explicit NULL in an
        INSERT bypasses the default, so inserts send `{}` and updates send NULL
        to mean "leave alone".
      - item reads and RETURNING clauses name their columns instead of `*`:
        `search_tsv` is a generated tsvector pgx cannot scan, and `path` is
        ltree and needs `::text` to land in the Go string the sqlc override
        declares. Adding a column to `item` means adding it to those lists.
      - `SET CONSTRAINTS` is transaction control, not a query sqlc can model,
        so the rebalance issues it through the connection directly.
- [x] 0.9 Seed generator — 2026-09-12
      ```
      $ make migrate-up && go run ./cmd/sierxctl seed      # ~40s for 10k on the agent host
      seed: workspace=01a0a07b-123d-7c4e-80e9-a01409674a39 items=10000 max_depth=6 links=500 events=16989
      seed: checksum=39f6fdbadfb442aa37e4ed96383accfa
      $ psql -Atc "select (select count(*) from item) items, (select max(nlevel(path)) from item) depth,
                          (select count(*) from item_rollup) rollups, (select count(*) from item_link) links,
                          (select count(*) from change_event) events"
      10000|6|10000|500|16989
      $ make rollup-verify
      rollup --verify: items=10000 rollups=10000 mismatches=0
      $ make seed-determinism
      run A: 5a31bd7418c25469b218817b349bcd4c
      run B: 5a31bd7418c25469b218817b349bcd4c
      run C (--seed 8): 907901972a7675dda5b465d05644f86b
      seed-determinism: OK (same seed identical, different seed differs)
      ```
      10000 items, max depth 6 (the target, not an accident — the planner fills
      the shallowest empty level first), 5 projects, rollups == items
      (ADR-013), 392 of the 500 links cross project boundaries (ADR-012: the
      hierarchy cannot, so links must), 35 `config_transition` rows = 3
      explicit arcs + the 4-row `{from: "*"}` fan-in per project (ADR-011),
      event kinds created 10000 / status_changed 6489 / linked 500.
      Determinism is checked in two scratch databases rather than two
      workspaces, so the second run cannot be influenced by the first, and a
      different `--seed` is asserted to differ — otherwise the checksum would
      not be measuring anything.
      **Deviation on backdated history:** items carry start and due dates
      spread across a nine-month window and their transitions are ordered, but
      `change_event.at` is `now()` — Mutate does not write `at`, so the events
      are stamped with the run time. Backdating them means letting a caller
      set `at`, which is a schema-level decision (and an audit-log
      consideration) rather than something the seed should fake. Cycle-time
      work in phase 5 will need it; raised as an open question below.
- [x] 0.10 Property tests — 2026-09-12
      ```
      $ make test-property
      + moving a node moves its whole subtree: OK, passed 10 tests.
      --- PASS: TestPropertySubtreeMovesWholesale (0.33s)
      + per-project ranks are a strict total order matching insertion order: OK, passed 10 tests.
      --- PASS: TestPropertyRankIsStrictTotalOrder (0.33s)
      + RankBetween lands strictly between its bounds: OK, passed 200 tests.
      + RankBetween rejects inverted bounds: OK, passed 200 tests.
      --- PASS: TestPropertyRankBetweenAlwaysStrictlyBetween (0.01s)
      --- PASS: TestRankRebalance5000 (14.20s)
      + rollups equal a fresh aggregate over descendants: OK, passed 12 tests.
      --- PASS: TestPropertyRollupsMatchAggregate (121.66s)
      + count(item_rollup) == count(item): OK, passed 12 tests.
      --- PASS: TestPropertyRollupCountEqualsItemCount (0.43s)
      + paths agree with parent_id and contain no cycles: OK, passed 12 tests.
      --- PASS: TestPropertyPathsStayConsistent (0.53s)
      ok      github.com/siercks/sierx/test/property  137.499s
      ```
      Library: `github.com/leanovate/gopter` v0.2.9 (MIT, no runtime deps),
      named in `go.mod` and cleared through `make gate-license` before
      adoption. **`pgregory.net/rapid` was the first choice and was rejected:
      it is MPL-2.0, which §15.1 blocks.** That is the instruction to run a
      candidate through the gate first earning its place.
      Rollups are checked twice per sequence — against the store's SQL
      recomputation and against an aggregate computed independently in Go — so
      the property is not one query agreeing with itself. The 5,000-item
      rebalance (ADR-003) commits in ~14s and preserves relative order, and a
      create after a rebalance still lands last.
      **Bug found and fixed:** `ListProjectRanks` filtered `deleted_at IS
      NULL`, but `item_project_rank_uniq` covers every row in the project. A
      sequence that soft-deleted an item and then created one allocated a rank
      that collided with the deleted row. The query now spans deleted rows —
      also correct for restoring a soft-deleted item, which must keep a unique
      rank. No randomized sequence in the earlier unit tests had produced that
      interleaving.
- [ ] 0.11 Backup and restore harness — **steps 1–4 and 6 green; steps 5 and 7
      left as ⚠ blocked, exactly as the task prescribes.** pgBackRest is not
      installed here and there is no repository target, so
      `driver-pgbackrest.sh`, `render-conf.sh` and the major-upgrade runbook are
      not written: step 5 requires verifying against an installed pgBackRest
      that the cipher cannot be changed on an existing stanza, and a driver
      whose acceptance has never run is what BUILD §0.4 exists to prevent.
      ```
      $ SIERX_BACKUP_DRIVERS=pgdump make backup-conformance
      === conformance: pgdump
      --- describe
      pgdump driver; pg_dump 18.6; target dir pgdump, keep 8
      --- contract
      contract: OK
      --- backup
      backup id: pgdump-20260914T155511Z
      --- verify
      pgdump: verified pgdump-20260914T155511Z.dump (167 archive entries)
      --- restore-to scratch
      pgdump: restored pgdump-20260914T155511Z.dump
      --- row counts
        20 tables, all counts equal
      --- content checksum
        4ad73262ab7958670147da18f7102f31
      --- event sequence high-water mark
        max(seq) = 16989
      --- rollup --verify on the restored copy (ADR-005 control 2)
      rollup --verify: items=21215 rollups=21215 mismatches=0
      === conformance: pgdump PASSED
      backup-conformance: OK for: pgdump

      $ make gate-nobackupleak && make prove-nobackupleak
      gate-nobackupleak: OK (no backup tool named outside the drivers)
      prove: pg_restore in the Makefile: gate went red — OK
      prove: pgbackrest in a make target: gate went red — OK
      prove: pg_dump named in Go source: gate went red — OK
      prove: wal-g in a non-driver script: gate went red — OK
      prove: clean tree: gate GREEN — OK

      $ bash scripts/backup/driver.sh pgdump retention      # 11 dumps planted
      pgdump: retention kept 8 of 11 dump(s), limit 8

      $ make restore-test
      restore-test: run 1 of the rotation -> driver "pgdump" (configured: pgdump)
      pgdump: restored pgdump-20260914T155511Z.dump
      restore-test: driver "pgdump" restored into the scratch database
      $ SIERX_BACKUP_DRIVERS=pgdump,other make restore-test   # rotation advances
      restore-test: run 2 of the rotation -> driver "other" (configured: pgdump, other)
      driver.sh: no driver 'other' (expected scripts/backup/driver-other.sh)
      $ go run ./cmd/sierxctl restore-test --force
      restore-test takes no arguments ("--force"); it has no escape hatches by design
      ```
      ADR-017 driver `describe` output, for recovering later which tool
      produced a green restore: `pgdump driver; pg_dump 18.6; target dir
      pgdump, keep 8`.
      Notes:
      - The rotation counter advances only on success, so a persistently broken
        secondary keeps failing the weekly test rather than being skipped past.
        That is the intent of ADR-010's rotation; a driver that cannot restore
        should be loud every week.
      - `gate-nobackupleak`'s allowlist gained two entries beyond the two
        ADR-017 names, each with its reason in the script: `.env.example`
        (the driver list and repository variables are how a driver is
        *selected* — naming them in configuration is the ADR's mechanism, and
        BUILD Appendix B fixes the names) and `scripts/schema.sh` (a
        `--schema-only` structural snapshot for drift detection: no data, no
        restore path, still needed if every driver were replaced).
      - Once modules were vendored, `vendor/` tripped gate-notopology (a
        dependency's `.gitignore` lists a dev-tool config file whose name ends
        in one of the internal-hostname suffixes) and gate-nobackupleak (pgx's
        Rakefile names a dump tool). All three
        content gates now exclude `vendor/`: third-party source is not this
        project's configuration and is not edited here.
- [ ] 0.12 CI skeleton, proven to fail
- [~] 0.13 License gate, SBOM, supply chain — **license gate green; SBOM
      outstanding.** Done out of order, before 0.10: BUILD requires a
      property-testing library be cleared through `make gate-license` before
      adoption, which needs the gate to exist.
      ```
      $ make gate-license
      ok       github.com/jackc/pgpassfile                             MIT
      ok       github.com/jackc/pgservicefile                          MIT
      ok       github.com/jackc/pgx/v5                                 MIT
      ok       github.com/jackc/puddle/v2                              MIT
      ok       github.com/leanovate/gopter                             MIT
      ok       golang.org/x/sync                                       BSD-3-Clause
      ok       golang.org/x/text                                       BSD-3-Clause
      licenses.sh: 7 Go module(s) checked
      licenses.sh: no node_modules — the frontend tree arrives at task 2.1; nothing to check on the npm side
      gate-license: OK (every dependency on the §15.1 allowlist)
      $ make prove-license
      prove: AGPL-3.0 module: gate went red — OK        <- the negative test the task names
      prove: MPL-2.0 module: gate went red — OK
      prove: SSPL-1.0 module: gate went red — OK
      prove: BSL-1.1 module: gate went red — OK
      prove: unclassifiable license: gate went red — OK
      prove: module with no license file: gate went red — OK
      prove: clean tree: gate GREEN — OK
      $ make vendor-verify
      vendor-verify: OK
      ```
      Still to do before this box is checked: the per-release SBOM, which
      belongs with `release.yml` in task 0.12 (BUILD task 0.12 step 2: "SBOM
      per release"), so it is written there and referenced here.
- [x] 0.14 Benchmark harness — 2026-09-12 (agent host, not reference hardware)
      ```
      $ make bench-smoke
      --- timings
      BenchmarkBoardView500                  5     1440152 ns/op
      BenchmarkItemDetail                    5      580556 ns/op
      BenchmarkDescendantRollupDepth6        5      121237 ns/op
      BenchmarkDeltaSync50                   5      347681 ns/op     7050 resp_bytes
      BenchmarkFullTextSearch                5      936019 ns/op
      BenchmarkRollupRecompute200            5    46960326 ns/op
      --- skipped scenarios (by name)
        sxq query over 10k items, indexed fields: skipped: needs the sxq parser (phase 3)
        steady-state RSS, sierx process: skipped: needs the sierx process (task 1.1)
        cold start to serving: skipped: needs the sierx process (task 1.1)
      bench-smoke: OK (no scenario errored; thresholds not asserted here — ADR-016)

      $ make gate-bench
      gate-bench: no baseline — §12's thresholds are measured on the Pi 5
        reference box, which does not exist until task 2.16 (ADR-016).
        Run 'make bench-baseline' there, commit test/bench/baseline.json, then
        this gate becomes meaningful. This exit is expected until then.
      make: *** [gate-bench] Error 1        <- the required behaviour
      ```
      Six of the nine §12 rows are measurable now and do run; the other three
      are skipped by name with the reason. `bench-baseline` and `gate-bench`
      were exercised once on this host to prove the round trip (all six inside
      budget on a 2.1GHz Xeon, which says nothing about the Pi) and the
      baseline was then **deleted**: it must be captured on reference hardware
      at task 2.16, and a dev-box baseline committed here would make the gate
      permanently meaningless.
      Thresholds live only in `test/bench/thresholds.go`, with scenario names
      copied verbatim from §12 — `ThresholdFor` panics on an unknown name,
      because a zero threshold would silently pass and turn a typo into a
      disabled gate.

### Phase 0 exit

- gate-0: `<paste the tail of make gate-0>`
- Human gates:
  - [x] ADR-002 signed off — 2026-09-12
  - [x] ADR-005 signed off — 2026-09-12
  - [x] ADR-012 signed off — 2026-09-12
  - [~] Task 0.11 — `backup-conformance` and `restore-test` green for the
        `pgdump` driver (output under 0.11). Not signed off: the `pgbackrest`
        driver (step 5) and the major-upgrade runbook (step 7) need an
        installed pgBackRest and ADR-010's repository target, which bind at
        task 2.16
- Pin drift (ADR-019): `<any pin more than one cycle behind, or "none">`
- Deviations: `<none | list>`
- Open questions raised: `<none | list with ADR numbers>`
- Requesting sign-off to enter phase 1.
