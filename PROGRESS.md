# sierx build progress

The agent's only progress claim. Append and check boxes; never rewrite history.
A checked box with no pasted acceptance output is treated as red (BUILD Â§0.4).

**Current phase:** 1
**Phase 2 deadline anchor:** 2026-09-12
**Phase 2 deadline:** none (owner direction, ADR-020; original 2026-10-10 date retired)

## Sign-offs (human writes these â€” see BUILD Â§4.0)

- [x] ADR-002 approved â€” 2026-09-12 â€” one sequence value per event row
- [x] ADR-005 approved â€” 2026-09-12 â€” rollups maintained in the store layer
- [x] ADR-012 approved â€” 2026-09-12 â€” cross-project moves rejected in v1
- [x] ADR-014 approved â€” 2026-09-12 â€” Markdown with raw HTML disabled at the parser
- [x] ADR-010 dev repository target defined â€” 2026-09-12 â€” `posix` to a local
      path, no decision required (BUILD ADR-010)
- [ ] ADR-010 **deployment** repository target â€” set at task 2.16 in the host
      env file. `sftp` recommended. `bootstrap-check` rejects the dev `posix`
      target whenever `SIERX_ENV` is not `dev`, so this cannot be skipped

## Cuts taken (BUILD Â§1.2)

- none

## Deviations from the guide

- 2026-09-18, takeover verification: the operator's verbose Spark run confirmed
  that all 13 store tests and six database-backed property tests skipped because
  DATABASE_URL was not exported. The standalone rank-string property test ran.
  The two preceding gate-0 GREEN runs therefore do not establish store/property
  acceptance, although their SQL and populated logical-restore checks did run.
  Scripts loaded .env in child processes; the Makefile's direct Go invocations
  could not inherit those settings. scripts/test-go.sh now loads .env using
  the existing parser, preserves environment overrides, rejects missing/empty
  DATABASE_URL, and runs verbose tests. check, test-store, test-property and
  gate-0 all use it. The regression proof runs in check and gate-0.
  Local validation (Windows Git Bash; fake Go, no database):
  ```
  $ bash test/shell/test-go_test.sh
  test-go proof: missing .env and environment rejected before Go runs
  test-go proof: empty .env value rejected before Go runs
  test-go proof: .env loaded literally; arguments preserved
  test-go proof: exported environment wins over .env
  test-go proof: explicitly empty environment override rejected before Go runs
  test-go proof: Go failure exit status preserved
  test-go proof: PASS
  ```
  Spark acceptance remains PENDING: make test-store && make test-property,
  followed by make gate-0 against the disposable development database.

- 2026-09-18, regression introduced by the `sierxctl` wrapper (the 2026-09-16
  speedup commit): `scripts/sierxctl.sh` did not load `.env`, unlike every
  other script in `scripts/`. `go run` had inherited nothing either, but the
  targets that used it were never run on a host where `DATABASE_URL` was set
  as a plain shell variable rather than an exported one â€” which is how one
  normally types it. `make seed` then failed with "DATABASE_URL is unset" on a
  host where `echo $DATABASE_URL` printed the URL. The loader is now present
  and identical to the others. Worth noting the speedup that caused this saved
  ~85ms per call; the fix is correct either way, but the trade was not a good
  one.

- 2026-09-18, task 0.11: `conformance.sh` swallowed the contract check's
  output, so a failing driver reported only "failed the contract check" while
  the check itself knew which verb failed and why. It now prints that output,
  and `driver.sh --contract` reports the verb's own message â€” for the
  pgbackrest driver on a host with no rendered config that reads
  `init FAILED on first run: pgbackrest: ... render it with
  scripts/backup/render-conf.sh`, which is actionable. The check was right; it
  just would not say so.

- 2026-09-17, defect six, found by reading a GREEN gate-0 rather than a
  failure: **gate-0 ran backup conformance and the benchmarks against an empty
  database.** `migrate.sh updown-up` leaves the schema at zero rows, and
  nothing seeded before those two steps, so the restore comparison compared
  nothing against nothing (equal counts of zero, equal empty checksums, zero
  rollups to disagree) and every benchmark scenario skipped for want of data.
  Both printed OK. The first real gate-0 GREEN was therefore a weaker claim
  than it looked, and the log shows it plainly: `max(seq) = 0`, an empty
  checksum line, `items=0 rollups=0`, and nine skipped scenarios.
  Fixed two ways: gate-0 seeds before conformance and bench, and
  `conformance.sh` now refuses a source database with no items instead of
  reporting a trivial pass. BUILD Â§0.4's "a green claim without evidence is
  treated as red" applies to the harness, not just to the checkboxes.
  Also: the pgdump driver's `describe` printed `pg_dump 18.6-1.pgdg24.04+2)`
  on a Debian-packaged client â€” `$NF` picked up the packaging string and its
  bracket. That line is restore attribution under ADR-017, so it now reads
  `pg_dump 18.6`.

- 2026-09-17, defect five, and the root cause of defect four's symptom: the
  Quadlet unit's `Environment=POSTGRES_INITDB_ARGS=--locale=C --encoding=UTF8`
  was **unquoted**. systemd's `Environment=` takes space-separated VAR=VALUE
  pairs, so it set `POSTGRES_INITDB_ARGS=--locale=C` and discarded
  `--encoding=UTF8`; initdb then defaulted to SQL_ASCII under the C locale.
  The task 0.2 acceptance could not have caught this â€” it was never run in the
  agent sandbox, which had no Podman, and the encoding check did not exist
  until defect four. Quoted now, and `db.sh up` asserts `UTF8 C` after the
  container reports ready, so a volume born from a wrong unit fails at startup
  instead of three tasks later. initdb args apply only to a fresh volume, so
  an existing cluster needs `make db-reset` in dev or a dump and reload
  elsewhere.

- 2026-09-17, defect four, same dev host: **every scratch database was created
  with inherited encoding and collation.** `CREATE DATABASE x` with no options
  copies template1, so on a cluster initdb'd without `--encoding=UTF8` the
  scratch copy comes out `SQL_ASCII` while the committed snapshot is `UTF8`.
  `schema-diff` then reports a one-line `client_encoding` difference that looks
  exactly like schema drift and is not. All four creators â€” `schema.sh`,
  `seed-determinism.sh`, `conformance.sh` and `sierxctl restore-test` â€” now
  pin `TEMPLATE template0 ENCODING 'UTF8' LOCALE 'C'`. The restore case
  mattered most: a restore into a differently-encoded database is not a test
  of the backup.
  `bootstrap-check` now also asserts the dev database's own encoding and
  collation are UTF8 and C (Â§4.4), skipping with an INFO line when the server
  is unreachable. It checked the tools and never the cluster, which is why a
  mis-initialised cluster surfaced three tasks later as a schema-diff failure.
  **If that check fails, the cluster is wrong, not the snapshot**: `make
  db-reset` recreates it through the Quadlet unit, which passes
  `--locale=C --encoding=UTF8` to initdb.

- 2026-09-17, three defects found on the first real dev host (arm64, DGX
  Spark), all in the harness rather than the product:
  1. **Every `.env` loader exited silently.** The pattern
     `[[ -z ${!key+x} ]] && export "$key=$val"` returns 1 under `set -e` the
     first time a variable is already set in the environment, killing the
     script with no output and exit 1. Invisible until a `.env` file existed
     AND the caller had exported one of its keys â€” which is the normal case on
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
  from 137s to 13s. `VerifyRollups` is unscoped by design â€” an operator asking
  "is anything wrong" means anything â€” so a test that created 14 items was
  re-verifying the whole 10k-item seed on every sequence. Added
  `VerifyRollupsForProject` and used it in the tests; the CLI still uses the
  unscoped query. The Go-side comparison also fetches a project's rollups in
  one round trip instead of one query per item. No property was weakened and
  no test-count lowered.
- 2026-09-16: added `make check`, a fast dev loop (vet, both SQL test files,
  store tests, sqlc diff, the three source gates; ~30s). It is NOT a gate and
  is not part of one â€” `gate-0` is unchanged, and `check` passing is not a
  claim that the phase gate passes. `make sierxctl` and `scripts/sierxctl.sh`
  build `bin/sierxctl` once and reuse it, so the make targets and scripts no
  longer `go run` the CLI on every call. Measured saving: ~85ms per
  invocation, not the seconds first estimated â€” kept because it is harmless
  and gives the CLI a stable path for the systemd units, not because it is
  fast.

- 2026-09-12, task 0.13: the license gate classifies the LICENSE text of every
  vendored module itself rather than running `go-licenses check`.
  `go-licenses` resolves licenses by downloading modules and carries a large
  dependency tree of its own â€” both of which this gate exists to constrain.
  The classifier matches distinctive strings from each license text, the same
  method go-licenses' classifier uses, minus the network, and it is proven
  against AGPL, MPL, SSPL, BSL, an unclassifiable license and a missing one.
- 2026-09-12, task order: 0.13's license gate was built before 0.10 because
  0.10's instruction is to clear the property-testing library through
  `make gate-license` before adopting it.

- 2026-09-12, tasks 0.3/0.7: goose and sqlc are pinned release binaries
  (version + per-arch sha256 in `scripts/tool.sh`, fetched into gitignored
  `bin/`) rather than `go tool` entries. Both pull large dependency trees â€”
  database drivers, a SQL parser â€” that would enter `go.mod` and
  `gate-license`'s scope without a line of them shipping in the binary. This
  supersedes the earlier note that said to switch to `go tool goose` at 0.8.
- 2026-09-12, environment: the agent sandbox cannot reach `proxy.golang.org`,
  `sum.golang.org`, `golang.org` or `gopkg.in`, but can reach `github.com`. Go
  modules were resolved with `GOPROXY=file:///<local>,direct GOSUMDB=off`,
  where the local filesystem proxy holds `golang.org/x/text`,
  `golang.org/x/sync`, `gopkg.in/yaml.v3` and `gopkg.in/check.v1` mirrored from
  their GitHub repositories. **Nothing in the repository depends on this** â€” no
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
  the task's Files list â€” the kickoff prompt's read order names it. HANDOVER Â§1
  said the five doc files were already committed; the repository held only
  `LICENSE`, so task 0.1 installed them as BUILD steps 3â€“5 and 7 describe.
- 2026-09-12, task 0.1: `prove-gates` (task 0.12) does not exist yet, so the
  gate's proof ships as `scripts/gate-notopology.sh --prove` (`make
  prove-notopology`). Task 0.12's `prove-gates.sh` should discover `gate-*`
  targets and call `scripts/<gate>.sh --prove`.

## Open questions raised

- 2026-09-12, task 0.9: the seed cannot backdate `change_event.at` â€” the
  column defaults to `now()` and `Mutate` does not accept a timestamp, so
  "status transitions spread over ~9 months" is only true of the items' dates
  and the transition order, not of the event timestamps. Cycle-time and
  burndown work (Â§13, phase 5) needs real historical `at` values. The choice â€”
  let a caller set `at` under a seed-only flag, or accept that history begins
  at first run â€” belongs in an ADR before phase 5, not in the seed.

- 2026-09-12, task 0.6: `deploy/quadlet/sierx-maintenance.service` (added â€” a
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

## Phase 0 â€” Schema, migrations, seed, CI skeleton

Gate: `make gate-0`. Tasks in order; one commit each (BUILD Â§3.3).

- [x] 0.1 Repository skeleton and toolchain pins â€” 2026-09-17, on the dev host
      (arm64, DGX Spark, Ubuntu 24.04)
      ```
      $ make bootstrap-check
      go         OK    go1.27.1 (go.mod pins 1.27.1)
      node       OK    v24.21.0 (.nvmrc pins 24)
      podman     OK    podman version 4.9.3
      psql       OK    psql 18.6
      database   OK    encoding UTF8, collation C
      signoff    INFO  ADR-010 **deployment** repository target â€” set at task 2.16 in the host
      backup     OK    repository type posix, path set, SIERX_ENV=dev
      $ make gate-notopology && make prove-notopology
      gate-notopology: OK (no topology in committable files)
      ... 9 proof cases, all OK (see the phase-0 exit block)
      ```
- [x] 0.2 Dev database â€” 2026-09-17, on the dev host
      ```
      $ make db-reset
      db-reset will DESTROY:
        container : sierx-postgres
        volume    : sierx-pgdata (the entire PGDATA â€” every database in this cluster)
        database  : sierx on localhost:5432
      dropped volume sierx-pgdata
      waiting for postgres ...
      db-up: sierx-postgres ready on 127.0.0.1:5432
      $ make bootstrap-check | grep database
      database   OK    encoding UTF8, collation C
      ```
      The cluster is UTF8 and C as Â§4.4 requires. Getting there took two fixes
      recorded under deviations: the Quadlet unit's unquoted
      `POSTGRES_INITDB_ARGS` (which silently produced SQL_ASCII) and the
      encoding assertion that now catches it at `db-up` and in
      `bootstrap-check`. The acceptance's `show lc_collate` does not exist on
      PostgreSQL 18; the `pg_database` query above is the equivalent.
- [x] 0.3 Migration tooling and extensions â€” 2026-09-12, against PostgreSQL
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
- [x] 0.4 Schema: all of SPEC Â§4 â€” 2026-09-12, against PostgreSQL 18.6 (native)
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
      red. 24 = 21 tables in Â§4 + 3 monthly `change_event` partitions
      (2026-09 â€¦ 2026-11). `seq_counter` (Â§4.7) is created here; task 0.6 adds
      the per-workspace row mechanism.
- [x] 0.5 Invariant enforcement in the database â€” 2026-09-12, PostgreSQL 18.6
      ```
      $ make test-sql
      NOTICE:  ok   raised  status.name update  [23001 ...]
      NOTICE:  ok   raised  status.key update  [23001 ...]
      NOTICE:  ok   raised  status.category update  [23001 ...]
      NOTICE:  ok   raised  item_type.name update  [23001 ...]
      NOTICE:  ok   raised  item_type.level update  [23001 ...]
      NOTICE:  ok   allowed item_type.is_idea update (not immutable by spec)
      NOTICE:  ok   raised  depth-9 insert  [23514 ... would be at depth 9, maximum is 8 (SPEC Â§5.3)]
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
      (Â§5.5) commits without `SET CONSTRAINTS ... DEFERRED`. The decision
      (DEFERRABLE) stands and the deferral step is harmless belt-and-braces;
      the ADR's "checked per row" rationale describes the non-deferrable case.
- [x] 0.6 Sequence counter and partition maintenance â€” 2026-09-12 (Go half
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
- [x] 0.7 sqlc wiring â€” 2026-09-12
      ```
      $ make sqlc-diff && go build ./...
      sqlc-diff: checked-in generated code matches fresh output
      ```
      sqlc v1.31.1, `sql_package: pgx/v5`, schema read from `migrations/` so
      there is no second schema definition. Queries limited to what 0.8â€“0.9
      need: workspace/seq allocation, item CRUD + one-statement subtree
      reparent, rollup insert/recompute/verify, events, config and links.
      `ltree` is overridden to `string` (no pgx type; the store passes text and
      lets Postgres cast). Also proven: renaming a query without regenerating
      turns `sqlc-diff` red.
      Note: `models.go` contains structs for the three `change_event`
      partitions declared in 0006. Partitions created later at runtime by
      `change_event_ensure_partitions` do not appear, because sqlc reads
      `migrations/`, so the generated output stays stable month to month.
- [x] 0.8 `store.Mutate`: the unit of work â€” 2026-09-12
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
      prove: INSERT INTO item from internal/api: gate went red â€” OK
      prove: lowercase multi-line UPDATE item: gate went red â€” OK
      prove: DELETE FROM comment: gate went red â€” OK
      prove: INSERT INTO sprint_item: gate went red â€” OK
      prove: TRUNCATE item_link: gate went red â€” OK
      prove: item_type/item_rollup writes and a plain SELECT stay green â€” OK
      prove: clean tree: gate GREEN â€” OK
      ```
      The Â§5.1 requirement is met: 8 concurrent writers, 48 events, a cursor
      polled throughout the run, every seq value observed exactly once and no
      gaps. `Mutation` has no way to register a row change without its events
      (ADR-001 as a type property), and no event-count parameter â€” the seq
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
- [x] 0.9 Seed generator â€” 2026-09-12
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
      10000 items, max depth 6 (the target, not an accident â€” the planner fills
      the shallowest empty level first), 5 projects, rollups == items
      (ADR-013), 392 of the 500 links cross project boundaries (ADR-012: the
      hierarchy cannot, so links must), 35 `config_transition` rows = 3
      explicit arcs + the 4-row `{from: "*"}` fan-in per project (ADR-011),
      event kinds created 10000 / status_changed 6489 / linked 500.
      Determinism is checked in two scratch databases rather than two
      workspaces, so the second run cannot be influenced by the first, and a
      different `--seed` is asserted to differ â€” otherwise the checksum would
      not be measuring anything.
      **Deviation on backdated history:** items carry start and due dates
      spread across a nine-month window and their transitions are ordered, but
      `change_event.at` is `now()` â€” Mutate does not write `at`, so the events
      are stamped with the run time. Backdating them means letting a caller
      set `at`, which is a schema-level decision (and an audit-log
      consideration) rather than something the seed should fake. Cycle-time
      work in phase 5 will need it; raised as an open question below.
- [x] 0.10 Property tests â€” 2026-09-12
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
      it is MPL-2.0, which Â§15.1 blocks.** That is the instruction to run a
      candidate through the gate first earning its place.
      Rollups are checked twice per sequence â€” against the store's SQL
      recomputation and against an aggregate computed independently in Go â€” so
      the property is not one query agreeing with itself. The 5,000-item
      rebalance (ADR-003) commits in ~14s and preserves relative order, and a
      create after a rebalance still lands last.
      **Bug found and fixed:** `ListProjectRanks` filtered `deleted_at IS
      NULL`, but `item_project_rank_uniq` covers every row in the project. A
      sequence that soft-deleted an item and then created one allocated a rank
      that collided with the deleted row. The query now spans deleted rows â€”
      also correct for restoring a soft-deleted item, which must keep a unique
      rank. No randomized sequence in the earlier unit tests had produced that
      interleaving.
- [~] 0.11 Backup and restore harness â€” **steps 1â€“4 and 6 green; steps 5 and 7
      left as âš  blocked, exactly as the task prescribes.** pgBackRest is not
      installed here and there is no repository target, so
      `driver-pgbackrest.sh`, `render-conf.sh` and the major-upgrade runbook are
      not written: step 5 requires verifying against an installed pgBackRest
      that the cipher cannot be changed on an existing stanza, and a driver
      whose acceptance has never run is what BUILD Â§0.4 exists to prevent.
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
      prove: pg_restore in the Makefile: gate went red â€” OK
      prove: pgbackrest in a make target: gate went red â€” OK
      prove: pg_dump named in Go source: gate went red â€” OK
      prove: wal-g in a non-driver script: gate went red â€” OK
      prove: clean tree: gate GREEN â€” OK

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
        *selected* â€” naming them in configuration is the ADR's mechanism, and
        BUILD Appendix B fixes the names) and `scripts/schema.sh` (a
        `--schema-only` structural snapshot for drift detection: no data, no
        restore path, still needed if every driver were replaced).
      - Once modules were vendored, `vendor/` tripped gate-notopology (a
        dependency's `.gitignore` lists a dev-tool config file whose name ends
        in one of the internal-hostname suffixes) and gate-nobackupleak (pgx's
        Rakefile names a dump tool). All three
        content gates now exclude `vendor/`: third-party source is not this
        project's configuration and is not edited here.
- [x] 0.12 CI skeleton, proven to fail (offline Spark acceptance recorded below) â€” 2026-09-18
      ```
      $ make prove-gates
      prove-gates: 5 proven, 2 exempt, 0 without a proof, 0 proof failures
      prove-gates: OK
      ```
      Every `gate-*` target has a proof or a recorded exemption. The two
      exemptions are `gate-0` (composite â€” proving it means proving each part
      again) and `gate-bench` (advisory under ADR-016 until reference hardware
      exists, with its one testable behaviour asserted directly).
      `docs/ci-portability.md` written: the claim that CI can move providers
      in a day, with worked GitLab and cron examples, the list of things that
      would break portability, and an honest statement of current state.
      `ci.yml` is one `make gate-0` step plus environment setup.
      **Two things named there rather than hidden:** `ci.yml`'s postgres
      service still needs `make db-pin` run on a machine with registry access
      (it now writes the digest into both the Quadlet unit and the workflow);
      and `release.yml` calls `make release-binaries`, `release-image` and
      `release-manifest`, which do not exist yet because there is no server
      binary until task 1.1 and no image until phase 2. Tagging a release
      today would fail at the first missing target. Not scaffolded â€” BUILD
      forbids writing files for later phases â€” so the workflow names its
      future steps and the targets arrive with the tasks that own them.
- [x] 0.13 License gate, SBOM, supply chain â€” 2026-09-18 (license gate
      2026-09-12, out of order before 0.10: BUILD requires a
      property-testing library be cleared through `make gate-license` before
      adoption, which needs the gate to exist)
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
      gate-license: OK (every dependency on the Â§15.1 allowlist)
      $ make prove-license
      prove: AGPL-3.0 module: gate went red â€” OK     <- the negative test the task names
      prove: MPL-2.0 module: gate went red â€” OK
      prove: SSPL-1.0 module: gate went red â€” OK
      prove: BSL-1.1 module: gate went red â€” OK
      prove: unclassifiable license: gate went red â€” OK
      prove: module with no license file: gate went red â€” OK
      prove: clean tree: gate GREEN â€” OK
      $ make sbom && make sbom-check
      sbom: wrote dist/sbom.cdx.json (7 Go component(s))
      sbom: no node_modules â€” the frontend tree arrives at task 2.1; this SBOM covers the Go build only
      sbom-check: dist/sbom.cdx.json lists the current component set
      $ make vendor-verify
      all modules verified
      vendor-verify: OK
      ```
      SBOM is CycloneDX 1.5, generated by `scripts/sbom.sh` from
      `vendor/modules.txt`, `go.sum` and the vendored LICENSE files â€” the same
      inputs `gate-license` reads, so the two cannot disagree about what is in
      the build. `release.yml` calls `make sbom` rather than
      `anchore/sbom-action`: BUILD Â§3.4 forbids logic that lives only in CI
      YAML, and an SBOM nobody can regenerate locally is an SBOM nobody
      checks. `go.sum`'s `h1:` value is recorded as a property named
      `go:mod:h1`, not as a CycloneDX hash â€” it is Go's module dirhash, not a
      file digest, and labelling it SHA-256 would be false.
      The npm side is absent until task 2.1; `sbom.sh` says so rather than
      implying coverage, and fails if `node_modules` appears without the
      generator being extended.
- [x] 0.14 Benchmark harness â€” 2026-09-12 (agent host, not reference hardware)
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
      bench-smoke: OK (no scenario errored; thresholds not asserted here â€” ADR-016)

      $ make gate-bench
      gate-bench: no baseline â€” Â§12's thresholds are measured on the Pi 5
        reference box, which does not exist until task 2.16 (ADR-016).
        Run 'make bench-baseline' there, commit test/bench/baseline.json, then
        this gate becomes meaningful. This exit is expected until then.
      make: *** [gate-bench] Error 1        <- the required behaviour
      ```
      Six of the nine Â§12 rows are measurable now and do run; the other three
      are skipped by name with the reason. `bench-baseline` and `gate-bench`
      were exercised once on this host to prove the round trip (all six inside
      budget on a 2.1GHz Xeon, which says nothing about the Pi) and the
      baseline was then **deleted**: it must be captured on reference hardware
      at task 2.16, and a dev-box baseline committed here would make the gate
      permanently meaningless.
      Thresholds live only in `test/bench/thresholds.go`, with scenario names
      copied verbatim from Â§12 â€” `ThresholdFor` panics on an unknown name,
      because a zero threshold would silently pass and turn a typo into a
      disabled gate.

### Phase 0 exit

- gate-0: **GREEN** on the dev host (arm64, DGX Spark), 2026-09-18
  ```
  $ make gate-0
  ... bootstrap-check: all OK, database UTF8/C
  ... migrate updown-up: 9 versions / clean at zero / 9 versions
  schema-diff: from-scratch migration matches docs/schema.sql
  NOTICE:  test-sql: 24 checks passed
  NOTICE:  test-partitions: passed
  sqlc-diff: checked-in generated code matches fresh output
  ok      github.com/siercks/sierx/internal/store
  ok      github.com/siercks/sierx/test/property
  licenses.sh: 7 Go module(s) checked
  gate-license: OK (every dependency on the Â§15.1 allowlist)
  all modules verified / vendor-verify: OK
  gate-nodirect: OK (governed tables written only through internal/store)
  gate-notopology: OK (no topology in committable files)
  gate-nobackupleak: OK (no backup tool named outside the drivers)
  seed-determinism: OK (same seed identical, different seed differs)
  seed: items=10000 max_depth=6 links=500 events=16989
  === conformance: pgdump
  source: 10000 item(s)
  pgdump driver; pg_dump 18.6; target dir pgdump, keep 8
  contract: OK
  backup id: pgdump-20260918T045740Z
  pgdump: verified pgdump-20260918T045740Z.dump (167 archive entries)
    20 tables, all counts equal
    content checksum e5a738e861bfb9d699b4318cfc8b7bd5
    max(seq) = 16989
  rollup --verify: items=10000 rollups=10000 mismatches=0
  === conformance: pgdump PASSED
  bench-smoke: OK (no scenario errored; thresholds not asserted here â€” ADR-016)
    BenchmarkBoardView500-20                 5     853661 ns/op
    BenchmarkItemDetail-20                   5     453083 ns/op
    BenchmarkDescendantRollupDepth6-20       5     154775 ns/op
    BenchmarkDeltaSync50-20                  5     327252 ns/op   5842 resp_bytes
    BenchmarkFullTextSearch-20               5     466373 ns/op
    BenchmarkRollupRecompute200-20           5  162650220 ns/op
  prove-gates: 5 proven, 2 exempt, 0 without a proof, 0 proof failures
  gate-0: GREEN
  ```
  Note on the benchmark figures: the DGX Spark is not the Â§12 reference
  hardware, so these are a smoke run and not a baseline. `gate-bench` still
  refuses to pass without one, which is correct (ADR-016).
- Human gates:
  - [x] ADR-002 signed off â€” 2026-09-12
  - [x] ADR-005 signed off â€” 2026-09-12
  - [x] ADR-012 signed off â€” 2026-09-12
  - [ ] Task 0.11 green â€” `make backup-conformance && make restore-test`.
        **Partially met.** The `pgdump` driver is conformance-green against a
        10k-item database, and `restore-test` rotates through it. The
        `pgbackrest` driver has never been run against an installed
        pgBackRest, so per ADR-017 it is not yet a driver: `pgbackrest` is
        absent from `SIERX_BACKUP_DRIVERS` and step 5's cipher-immutability
        check is unverified. Deferred to task 2.16, where ADR-010's repository
        target binds and a real data directory exists. **This gate is the
        human's call, not the agent's.**
- Pin drift (ADR-019): none. Go 1.27.1, Node 24, PostgreSQL 18.6, goose
  v3.28.0, sqlc v1.31.1, gopter v0.2.9.
- Deviations: see the list above â€” eleven, every one in the harness rather
  than the product. Seven were found only by running on real hardware.
- Open questions raised: `change_event.at` cannot be backdated by the seed
  (needs an ADR before phase 5); ADR-003's "checked per row" rationale is
  wrong for a DEFERRABLE constraint; the CI workflows' provenance.
- Outstanding before phase 1: task 0.11's pgBackRest conformance (or an
  explicit decision to defer it to 2.16), `docs/ci-portability.md` (0.12),
  and the per-release SBOM (0.13).
- **Requesting sign-off to enter phase 1.**


## Phase 0 closeout correction - 2026-09-18

The operator applied the final-deliverables and test-environment patches.
Their subsequent Spark gate output is preserved in
[the acceptance log](docs/acceptance/phase0-spark-2026-09-18.log).
This supersedes the PENDING Spark acceptance in the earlier test-runner entry:

```text
$ make gate-0
test-go proof: PASS
NOTICE:  test-sql: 24 checks passed
ok      github.com/siercks/sierx/internal/store 0.714s
ok      github.com/siercks/sierx/test/property 20.480s
source: 15443 item(s)
20 tables, all counts equal
rollup --verify: items=15443 rollups=15443 mismatches=0
backup-conformance: OK for: pgdump
gate-0: GREEN
```

All 13 store and all seven property-suite tests ran; no database-test skips.
Three future benchmark scenarios remain explicitly skipped. The sxq skip
label is corrected from Phase 3 to Phase 1 in this closeout.

### Closeout changes and acceptance boundary

- Task 0.12 is reopened: its former completion claim lacked ci-local.sh.
  The replacement now snapshots the current tree without host configuration,
  prepares tools/modules online, and runs gate-0 in an offline disposable
  container with its own database. Host databases and checkout are not mounted.
- SBOM checking compares all stable inventory/build fields, including licenses,
  hashes and provenance, and rejects malformed generated-format documents.
  It is wired into gate-0. The generator shares the license classifier and
  allowlist resolutions. General CycloneDX schema validation is not claimed.
- sqlc cached-version detection uses `sqlc version`, avoiding repeated fetches
  caused by `sqlc --version`. Container setup inputs require re-preparation
  when they change. The CI auth fixture now uses the specified `local` mode.
- The database digest was already pinned. Earlier placeholder claims and task
  counts are historical; the handover now describes the actual acceptance state.
- ADR-020 records the owner's no-deadline instruction and Spark-first staging.
  Physical backup deferral remains proposed, not human-signed approval.

Local closeout validation (Windows; no PostgreSQL/Podman execution):

```text
$ python -m unittest discover -s test/python -p 'test_*.py'
Ran 5 tests
OK
$ bash scripts/sbom.sh && bash scripts/sbom.sh --check dist/sbom.cdx.json
sbom: wrote dist/sbom.cdx.json (7 Go component(s))
sbom-check: current inventory, licenses, hashes and build metadata verified
```

Additional local checks:

```text
$ bash test/shell/ci-local_test.sh
ci-local proof: absent image fails with preparation instructions
ci-local proof: offline flags, no host mounts, host .env excluded
ci-local proof: container failure propagated
ci-local proof: cached sqlc accepted using version subcommand
ci-local proof: PASS (mock boundary, not container acceptance)
$ bash test/shell/test-go_test.sh
test-go proof: PASS
$ bash scripts/gate-notopology.sh && bash scripts/gate-nobackupleak.sh && bash scripts/gate-nodirect.sh
gate-notopology: OK (no topology in committable files)
gate-nobackupleak: OK (no backup tool named outside the drivers)
gate-nodirect: OK (governed tables written only through internal/store)
```

**PENDING on the Spark:** `make ci-local-prepare && make ci-local` and the
updated `make gate-0`. Do not mark task 0.12 or Phase 0 complete from local
mock/unit checks. No phase-advance sign-off is recorded by this patch.


## Offline CI follow-up - vendor snapshot exclusion, 2026-09-18

The Spark successfully built the prepared image and started the offline
container. Runner proofs, five Python tests, bootstrap, migration round trip,
24 SQL checks, partition checks and sqlc-diff passed. The gate then failed at
Go compilation with undefined language.NewCoverage and language.Coverage.

The repository ignore pattern `coverage*` also matches dependency source such
as vendor/golang.org/x/text/language/coverage.go. That file is absent from the
tracked review copy; a locally regenerated but ignored copy would compile on
the host yet be omitted from the committable-files CI snapshot. The rule now
applies only at the repository root (`/coverage*`). Run `go mod vendor` to
restore the pinned dependency source, and include the restored files when
committing. Do not weaken snapshot isolation by copying all ignored files.

The old vendor verifier regenerated vendor/ before comparing tracked diffs,
which could repair missing files and then overlook their untracked state.
The replacement generates a separate temporary tree and compares all paths
and file content against the current vendor/. Missing, extra and altered files
fail; verification does not silently repair the tree.

Local regression validation: six Python tests passed, including a snapshot
case with an untracked vendor coverage.go and an excluded root coverage report.
The shell proof rejected missing, modified and extra vendor source and accepted
an identical tree. All three source gates passed. These were fixture tests;
the actual Go/module verification and complete offline rerun remain pending
on the Spark. The existing prepared image can be reused because none of its
pinned preparation inputs changed.


## Phase 0 accepted; Phase 1 authorized - 2026-09-18

The owner reviewed the successful offline Spark run and instructed:
"Let's defer and push, and begin to look at Phase 1 and how we can build
something interactable."

- [x] Task 0.12 accepted: real prepared-container execution, offline, on Spark.
- [x] Closeout SBOM and vendor checks passed inside that same gate.
- [x] Phase 0 accepted with the explicit task 0.11 exception below.
- [x] Entry to Phase 1 authorized by the owner.
- [x] Physical-backup conformance/cipher validation deferred to task 2.16.
      This is an approved deferral, NOT a claim that those tests passed.
      Require encrypted off-machine backup and an isolated physical restore
      before relying on the deployed backlog. ADR-010 deployment inputs remain
      unset until deployment. Task 0.11 remains partially implemented.

The complete supplied output is in
[the offline acceptance log](docs/acceptance/phase0-offline-spark-2026-09-18.log).
It supersedes the earlier pending/failed container entries:

```text
$ go mod vendor && make vendor-verify && make ci-local
all modules verified
vendor-verify: OK (complete file tree matches pinned modules)
Ran 6 tests
OK
NOTICE:  test-sql: 24 checks passed
ok      github.com/siercks/sierx/internal/store 0.313s
ok      github.com/siercks/sierx/test/property 8.462s
sbom-check: current inventory, licenses, hashes and build metadata verified
source: 15438 item(s)
20 tables, all counts equal
rollup --verify: items=15438 rollups=15438 mismatches=0
backup-conformance: OK for: pgdump
prove-gates: 5 proven, 2 exempt, 0 without a proof, 0 proof failures
gate-0: GREEN
```

All 13 store tests and seven property-suite tests ran. The three named
future-feature benchmark skips remain expected. Timings are Spark smoke
measurements, not a small-host production baseline. The missing vendored
coverage.go is restored from the pinned upstream module and must be committed.

## Phase 1 - REST API, auth, event log

All 25 implementation tasks are complete. Planning is in docs/PHASE-1-PLAN.md;
per-task evidence and composite-gate results follow. Human Spark acceptance
remains pending.

- [x] 1.1 Server skeleton and executable boot checks.
- [x] 1.2 Error model.
- [x] 1.3 Local authentication.
- [x] 1.4 Proxy authentication.
- [x] 1.5 TOTP.
- [x] 1.6 Operator bootstrap.
- [x] 1.7 Projection registry.
- [x] 1.8 Cursor pagination.
- [x] 1.9 Projects.
- [x] 1.10 Resolved configuration.
- [x] 1.11 Item create/read/update/delete with optimistic concurrency.
- [x] 1.12 Transitions.
- [x] 1.13 Move and reparent.
- [x] 1.14 Links.
- [x] 1.15 Comments.
- [x] 1.16 Hierarchy reads.
- [x] 1.17 Item history.
- [x] 1.18 Saved views.
- [x] 1.19 Preferences.
- [x] 1.20 Delta sync.
- [x] 1.21 sxq subset.
- [x] 1.22 Caching and compression.
- [x] 1.23 Concurrent cursor/race tests.
- [x] 1.24 Endpoint golden files.
- [x] 1.25 Metrics.

### Task 1.1 acceptance - 2026-09-18

Owner authorized all Phase 1 implementation locally, on `build/phase-1-api`,
with a draft PR and hands-on Spark testing before merge. The `build/` prefix
supersedes BUILD's suggested branch name. Owner also authorized conventional,
documented and tested defaults for unspecified API behavior.

Added the server entry point, validated environment, pgx pool, chi routing,
JSON request logs, bounded health checks and graceful shutdown. Request logs
omit query strings and connection errors. Proxy CIDRs are required only in
proxy mode. `SIERX_LISTEN_ADDR` is optional and defaults to `:8080`; session
keys require at least 32 bytes. Health returns `alive` and `database`, with
200 for reachable and 503 for unavailable. A database outage does not block
startup. These operational defaults resolve details left open by task 1.1.

Required supporting files beyond the task list: boot tests, Makefile test-api
target with TEST_ARGS, README usage, environment reference, and vendored chi
v5.3.2 (MIT). No later endpoint handlers were added.

Actual acceptance ran with Go 1.27.1 in a disposable local Linux container,
network disabled and a fresh PostgreSQL 18 cluster. Selected output:

```text
$ make test-api TEST_ARGS='-run TestServerBoot'
--- PASS: TestServerBoot (1.02s)
    --- PASS: TestServerBoot/configuration (0.00s)
    --- PASS: TestServerBoot/reachable (0.00s)
    --- PASS: TestServerBoot/unavailable (1.01s)
    --- PASS: TestServerBoot/startup_shutdown (0.00s)
PASS
ok      github.com/siercks/sierx/internal/api 1.027s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
ok       github.com/go-chi/chi/v5                                MIT
licenses.sh: 8 Go module(s) checked
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

This is task acceptance, not the complete Phase 1 gate or human walkthrough.

### Task 1.2 acceptance - 2026-09-18

Added RFC 9457 constructors with locally authored error text, a `current`
extension for conflict responses, no-store headers, and JSON router/panic
errors. Supporting router/middleware edits and fixed problem JSON fixtures
are required to exercise the error model. Golden tests inspect problem.go
literals to reject dependency-produced error copy.

Actual output from the same isolated offline PostgreSQL test setup:

```text
$ make test-api
--- PASS: TestProblemGolden (0.00s)
--- PASS: TestRouterProblems (0.00s)
--- PASS: TestServerBoot (1.01s)
PASS
ok      github.com/siercks/sierx/internal/api 1.019s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.3 acceptance - 2026-09-18

Added local login/logout/current-user endpoints, Argon2id hashing, secure
12-hour sessions stored only as SHA-256 hashes, inactive-account enforcement,
origin checks and bounded login work/attempts. ADR-022 records defaults approved
under the owner's authorization. Server registration, tests and dependency
vendoring are required supporting wiring outside the task's auth directory.
golang.org/x/crypto v0.57.0 and x/sys v0.48.0 are BSD-3-Clause; their module
requirements advance x/sync to v0.23.0 and x/text to v0.42.0. The license gate
checked all ten modules. No schema change was needed.

Real isolated-container acceptance:

```text
$ make test-api
--- PASS: TestAuthLocal (0.75s)
--- PASS: TestAuthOriginAndLimits (0.13s)
--- PASS: TestPasswordHash (0.35s)
--- PASS: TestProblemGolden (0.00s)
--- PASS: TestRouterProblems (0.00s)
--- PASS: TestServerBoot (1.01s)
PASS
ok      github.com/siercks/sierx/internal/api 2.241s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
licenses.sh: 10 Go module(s) checked
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.4 acceptance - 2026-09-18

Proxy identity is accepted only from explicitly trusted immediate peers and for
active pre-provisioned users with NULL local passwords. ADR-022 documents the
header and account rules. Required supporting edits register the mode in auth
middleware and exercise spoofed headers, unknown users and local-mode isolation.

```text
$ make test-api
--- PASS: TestAuthLocal (0.71s)
--- PASS: TestAuthOriginAndLimits (0.12s)
--- PASS: TestPasswordHash (0.33s)
--- PASS: TestProblemGolden (0.00s)
--- PASS: TestRouterProblems (0.00s)
--- PASS: TestAuthProxy (0.12s)
--- PASS: TestServerBoot (1.01s)
PASS
ok      github.com/siercks/sierx/internal/api 2.294s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.5 acceptance - 2026-09-18

Added password-confirmed TOTP enrollment, verification and disable endpoints,
encrypted account-bound secret storage, single-use hashed recovery codes and
transactional step replay prevention. Enabling/disabling revokes all sessions.
ADR-022 records the API, cryptography and recovery defaults. No extra dependency
or schema column was required. Router, login integration and tests are required
supporting files. RFC 6238 Appendix B supplies the independent code vectors.

Actual local isolated-container output:

```text
$ make test-api
--- PASS: TestTOTP (1.14s)
PASS
ok      github.com/siercks/sierx/internal/api 3.621s
=== RUN   TestTOTPVectors
--- PASS: TestTOTPVectors (0.00s)
=== RUN   TestTOTPEncryption
--- PASS: TestTOTPEncryption (0.00s)
PASS
ok      github.com/siercks/sierx/internal/api/auth 0.003s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

The earlier auth, proxy, boot and problem tests also passed in this run.

### Task 1.6 acceptance - 2026-09-18

Added environment-driven operator bootstrap. The whole workspace/admin/project
creation commits atomically under an advisory lock. The existing workspace
trigger creates seq_counter; the seed configuration is reused without creating
benchmark items. Re-running with the same identity inputs reports existing IDs
and changes nothing. Different workspace inputs are refused. Required supporting
files are the reusable bootstrap implementation, shared config installer, CLI
registration, environment/README documentation and an executable integration test.

TestBootstrap builds and invokes the real CLI twice against its own newly
created and migrated database, compares stored rows, checks five config statuses,
then signs in over HTTP. It also rejects a second workspace. Test fixture cleanup
now removes the workspace counter before the workspace.

```text
$ make test-api
=== RUN   TestBootstrap
--- PASS: TestBootstrap (0.90s)
PASS
ok      github.com/siercks/sierx/internal/api 4.424s
ok      github.com/siercks/sierx/internal/api/auth 0.003s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

All previously added API/auth tests also passed. Phase 1 remains in progress.

### Task 1.7 acceptance - 2026-09-18

Added the field/SQL/type registry, nested and custom-field selection, nearest
name suggestions, generated client types, gate-gen and its deliberate drift
proof. Required, optional and rejected field policies are tested without adding
future handlers. Item detail permits optional fields; fixed-shape project/link
collections reject fields alongside ADR-007's named fixed-shape endpoints.
Only the explicitly required generated TypeScript contract starts the web tree.

```text
$ make gen-fields gate-gen prove-gen
gate-gen: OK
gate-gen: OK
gate-gen: generated fields differ; run make gen-fields
exit status 1
prove-gen: drift rejected
$ make test-api
--- PASS: TestProjectionGolden (0.00s)
--- PASS: TestProjectionPolicies (0.00s)
PASS
ok      github.com/siercks/sierx/internal/api/projection 0.004s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

The full API suite passed in the same isolated PostgreSQL container run.

### Task 1.8 acceptance - 2026-09-18

Added signed opaque cursors with stable tiebreak and upper boundary, request
scope binding, limits and offset rejection. ADR-023 documents traversal and
collection response defaults, including the limits of mutable sorting.
The database test inserts additional rows between page requests and observes
each original bounded row once. Cursor tests reject tampering and scope reuse.

```text
$ make test-api
=== RUN   TestCursor
--- PASS: TestCursor (0.00s)
=== RUN   TestCursorConcurrentInsert
--- PASS: TestCursorConcurrentInsert (0.01s)
PASS
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

All other API tests passed in that isolated-container run.

### Task 1.9 acceptance - 2026-09-18

Added administrator-only project creation with atomic config version 1,
workspace-scoped detail and bounded list reads, archive filtering and the
reserved-prefix authority. Fixed golden responses cover all three verbs.
Tests cover member rejection, every reserved prefix, malformed prefixes,
initial key counter and resolved seed status membership.

Required supporting changes: route registration, response helpers, golden
fixtures and per-test database creation. This also corrects the bootstrap test:
pgx ConnString retains its original input even after changing Config.Database,
so the former test used the container's disposable main database rather than
the newly named database. Both CLI runs still happened inside the disposable
container; this run now proves them against the intended separate empty database.

```text
$ make test-api
--- PASS: TestBootstrap (1.09s)
--- PASS: TestProjects (0.46s)
PASS
ok      github.com/siercks/sierx/internal/api 5.897s
ok      github.com/siercks/sierx/internal/api/auth 0.003s
ok      github.com/siercks/sierx/internal/api/projection 0.003s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.10 acceptance - 2026-09-18

Added one-query resolved configuration with ordered statuses/types, initial
status keys, enumerated transition arcs and required fields, field definitions
and a content ETag. Fixed golden JSON covers the seeded wildcard expansion.
Supporting route/test files verify weak conditional ETags, empty 304 bodies
and rejection of fields on this fixed representation.

```text
$ make test-api
=== RUN   TestResolvedConfig
--- PASS: TestResolvedConfig (0.47s)
PASS
ok      github.com/siercks/sierx/internal/api 6.788s
ok      github.com/siercks/sierx/internal/api/auth 0.004s
ok      github.com/siercks/sierx/internal/api/projection 0.004s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (every dependency on the Â§15.1 allowlist)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.11 acceptance - 2026-09-18

Added projected item reads, validated creation/edits, soft deletion and quoted
version preconditions. Store checks versions under the workspace sequence lock;
failed creates roll back keys and sequences. Conflicts include current and
submitted values. Local creates now record origin_seq; JSON preserves int64
sequence precision. Leaf rollup point totals correctly retain SQL NULL.

```text
$ make test-api
--- PASS: TestItemsCRUD (0.46s)
--- PASS: TestFailedCreateRollsBack (0.39s)
--- PASS: TestConcurrentItemEdit (0.45s)
--- PASS: TestItemSequencePrecision (0.40s)
ok github.com/siercks/sierx/internal/api 7.601s
$ make test-store
ok github.com/siercks/sierx/internal/store 0.437s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (10 modules allowed)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.12 acceptance - 2026-09-18

Implemented current-config transitions with atomic editable-field patches,
required-field errors, version checks and status_changed events. Golden errors
name to_status and missing assignee. Tests cover every seeded wildcard source,
terminal dropped, and config-version advancement only on transition.

```text
$ make test-api
PASS (including TestTransitions and TestWildcardTransitions)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.403s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (10 modules allowed)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.13 acceptance - 2026-09-18

Added hierarchy move with explained project/cycle/depth errors, single-statement
subtree rewrite, and rank placement computed under the workspace write lock.
The store repeats hierarchy validation after serialization. Omitted rank_after
preserves rank; explicit null prepends in the project ordering. Randomized HTTP
create/move/delete/transition sequences verify paths and materialized rollups.

```text
$ make test-api
--- PASS: TestMove (0.40s)
+ API mutations preserve paths and materialized rollups: OK, passed 8 tests.
--- PASS: TestAPIHierarchyProperty (3.25s)
ok github.com/siercks/sierx/internal/api 11.563s
$ make test-store
ok github.com/siercks/sierx/internal/store 0.381s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.14 acceptance - 2026-09-18

Added inbound/outbound paginated link reads, all five link kinds, cross-project
creation and deletion with source-item version preconditions. Store now preserves
supplied link IDs and advances the source item version/change sequence. Nested
endpoint summaries leave room for later reduced cross-workspace projections;
Phase 1 resolves targets within the authenticated workspace.

```text
$ make test-api
--- PASS: TestLinks (0.38s)
ok github.com/siercks/sierx/internal/api 12.423s
$ make test-store
ok github.com/siercks/sierx/internal/store 0.390s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.15 acceptance - 2026-09-18

Added raw Markdown comments, bounded listing, author edits and soft deletion.
Supporting PATCH/DELETE routes make edited_at and deleted_at actionable. Every
change uses store.Mutate with an owning-item version check and history event.
Deleted comment responses retain attribution/timestamps and hide the body.

```text
$ make test-api
--- PASS: TestComments (0.49s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.438s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.16 acceptance - 2026-09-18

Added projected, keyset-paginated children/descendant reads with bounded depth,
and direct materialized rollup reads. Goldens cover each shape and leaf zeros /
nullable totals; six-level traversal verifies depth filtering and pagination.
The test inspects the rollup SQL to reject recursion or aggregation on read.

```text
$ make test-api
--- PASS: TestHierarchyReads (0.46s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.436s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.17 acceptance - 2026-09-18

Added newest-first event history with signed sequence cursors, actor attribution,
and field before/after values. Golden history distinguishes moves, transitions
and ordinary edits. Backdated events preserve timestamps; events arriving after
the first page do not enter that bounded traversal.

```text
$ make test-api
--- PASS: TestItemHistory (0.38s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.425s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

Task ordering note: 1.18 explicitly requires the parser from 1.21. Implementing
1.21 next as that prerequisite, then returning to 1.18-1.20; no parser bypass or
placeholder view validation is introduced.

### Task 1.21 acceptance - 2026-09-18 (prerequisite for 1.18)

Added bounded lexer/parser, case-insensitive keywords and JQL aliases, typed
parameterized compilation, project-aware custom fields, date arithmetic,
full-text matching and field completion. All SPEC examples are golden cases;
future hierarchy/sprint functions explain their phase. Item lists now execute
sxq and page by the requested sort plus ID, with nulls last and now() frozen
in the authenticated cursor. Integration tests exposed an untyped unused
first-page parameter; explicitly typing it fixed all default and sorted reads.

```text
$ make test-sxq
ok github.com/siercks/sierx/internal/sxq 0.033s
$ make fuzz-sxq
fuzz: execs: 25599, new interesting: 83 (total: 89)
PASS
ok github.com/siercks/sierx/internal/sxq 6.022s
$ make test-api
PASS (including TestSXQItems and all existing API tests)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.443s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.18 acceptance - 2026-09-18

Added saved-view creation with full SXQ parse/type validation and the parser's
own suggestions. Listing enforces workspace and private/shared ownership before
pagination. Goldens cover create/list/invalid queries; a second member cannot
see a private view but can see a shared one.

```text
$ make test-api
PASS (including TestViews)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.383s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.19 acceptance - 2026-09-18

Added the ADR-015 preference patch, restricted to theme, reduced_motion and
display_name, without an item version requirement. Goldens cover valid updates,
illegal themes and forbidden email changes. Corrected golden normalization to
replace whole JSON string values, avoiding nondeterministic UUID/email overlap.

```text
$ make test-api
--- PASS: TestMePreferences (0.43s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.500s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.20 acceptance - 2026-09-18

Added workspace-scoped, ascending sequence delta reads with next_seq and no
ETag. Compact event summaries exclude unbounded before/after content, which
remains available in history. Tests traverse every sequence and verify a
50-change response is below 20 KB even after fifty large-body item edits.

```text
$ make test-api
--- PASS: TestChanges (0.76s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.565s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.22 acceptance - 2026-09-18

Added Brotli v1.2.4 (MIT, vendored) and gzip with quality-aware negotiation,
Vary and body-free 304 responses. Item/config read tags hash the representation;
parent rollup changes invalidate caches without fabricating edit-version bumps.
Tests cover decoded equivalence, q=0, projection variants and delta ETag absence.
There are no static assets in Phase 1; their routes arrive with the Phase 2 web
bundle and must use its content fingerprint. No placeholder asset route added.

```text
$ make test-api
--- PASS: TestCachingCompression (0.44s)
PASS (all API packages)
$ make test-store
ok github.com/siercks/sierx/internal/store 0.460s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
gate-license: OK (11 modules allowed)
gate-nodirect: OK (governed tables written only through internal/store)
gate-notopology: OK (no topology in committable files)
```

### Task 1.23 acceptance - 2026-09-18

Added six HTTP writers plus a live HTTP delta poller, interleaved with a
200-item store transition transaction. Native gcc/libc headers now support the
required race detector in the prepared offline image. Disposable CI copies no
longer create synthetic Git commits or override identity; source SBOM revision
is explicitly unknown when the copy has no Git history.

```text
$ make ci-local-prepare
all modules verified
ci-local: preparation complete; make ci-local now runs without network access
$ make test-concurrency  # invokes go test -race
observed all 544 committed events exactly once across 313 polls, including a 200-item transition
--- PASS: TestCommitOrderedCursor (1.56s)
ok github.com/siercks/sierx/test/concurrency 2.587s
$ bash test/shell/ci-local_test.sh
ci-local proof: PASS (mock boundary, not container acceptance)
$ go vet ./test/concurrency/...
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

### Task 1.24 acceptance - 2026-09-18

All 34 current routes have mapped response fixtures, including authentication,
TOTP, successful moves/transitions and the empty logout response envelope.
The route inventory also checks authentication boundaries; separate tests check
cross-workspace isolation and comment authorship. Regeneration is toolchain-
pinned and checked for drift. Added a real-binary curl walkthrough, operator
notes and the gate-1/CI wiring. Existing fixture semantics remained unchanged
when regenerated; only formatting and the newly covered responses were added.

```text
$ make golden-update
PASS (all API and SXQ packages)
$ make test-golden
--- PASS: TestWorkspaceIsolation (0.68s)
--- PASS: TestGoldenRouteCoverage (0.00s)
golden: all endpoint and query fixtures reproduce without drift
$ make smoke-api
smoke-api: real CLI bootstrap and curl workflow PASS
$ make test-store
ok github.com/siercks/sierx/internal/store 0.360s
$ go vet ./internal/api/... ./internal/config/... ./cmd/sierx
$ make gate-license gate-nodirect gate-notopology
All three gates OK.
```

The full composite offline gate is pending the final metrics task. The owner's
Spark walkthrough remains a separate, pending human acceptance item.

### Task 1.25 acceptance - 2026-09-18

Added authenticated administrator-only Prometheus text metrics on the SPEC path
`/api/v1/metrics`. The format test parses every emitted HELP/TYPE/sample family,
checks numeric validity, verifies request and duration counters advance, verifies
in-flight accounting, and rejects ordinary members. Route inventory now covers
35 routes. Metrics carry no identity labels and require no monitoring service.

```text
$ make golden-update
--- PASS: TestMetrics (0.34s)
--- PASS: TestGoldenRouteCoverage (0.00s)
PASS (API, authentication, projection and SXQ packages)
```

The full offline gate is running; the Spark human walkthrough remains pending.

### Full-gate integration correction - 2026-09-18

The first composite run found the Phase 0 property generator retained deleted
items in its live-item list. Phase 1 correctly rejects a deleted move parent.
Removed deleted targets from that list and added a deterministic store-level
regression proving rejection preserves items, events and gap-free sequences.
The existing property assertions remain intact. The repeated full-gate run
passed all property tests (20.717s), including TestDeletedParentMoveRollsBack.

### Phase 1 automated closeout - 2026-09-18

All tasks 1.1-1.25 are implemented. No Phase 1 scope cuts were taken.
The full `make ci-local` run completed with exit status 0 in the prepared
rootless Podman container, with network disabled and disposable PostgreSQL.

```text
$ make ci-local
schema-diff / sqlc-diff: checked-in definitions match generated output
SQL invariants: 24 checks passed; partition tests passed
go vet ./... and complete Go test suite: PASS
license / SBOM / vendor / write-boundary / topology gates: PASS
seed-determinism: OK
backup-conformance: OK for: pgdump
bench-smoke: OK (thresholds not asserted on this host)
Linux amd64 and arm64 builds: PASS
gate proofs: PASS
gate-0: GREEN
golden: all endpoint and query fixtures reproduce without drift
fuzz: 30848 executions; PASS
TestCommitOrderedCursor: 544 events exactly once across 302 polls
Race-enabled concurrency package: PASS (2.607s)
gate-gen: OK
smoke-api: real CLI bootstrap and curl workflow PASS
gate-1: GREEN (automated; human walkthrough remains required)
```

The tested source includes the deleted-parent regression fix. Subsequent changes
only preserve the owner's AGENTS.md and record these results. All branch commits
retain the existing human author/committer identity with no agent attribution.
The owner's manual Spark walkthrough must still be recorded before final Phase 1
acceptance and merge. Existing ADR-021 physical-backup deployment remains Phase
2.16; smoke benchmarks are not a Spark performance baseline.

### Owner-operated Spark walkthrough - 2026-09-18

The owner ran the manual curl walkthrough on Spark against a separate trial
database on PostgreSQL 18.6 and supplied the responses in the implementation
conversation. This records observed results, not an automated rerun. The exact
Spark checkout SHA and a native Spark gate-1 result remain to be confirmed.
The completed local offline gate is recorded above. No Phase 1 scope cuts.

Observed manual checks:

- Bootstrap created the workspace, administrator and project; health returned
  HTTP 200 with `{"alive":true,"database":"reachable"}`.
- Authenticated administrator read and story creation passed: TRY-1, version 1.
- Transition without assignee returned HTTP 422 with
  `Required fields are missing: assignee.` Supplying the administrator assignee
  succeeded with HTTP 200, status doing, version 2.
- Created epic TRY-2; moved TRY-1 beneath it with HTTP 200, version 3.
  Children returned `{"data":[{"key":"TRY-1","title":"My first Spark test"}],"next_cursor":null}`.
  Rollup returned descendant_count 1 and done_count 0.
- Created and read back a relates link from TRY-1 to TRY-2 (HTTP 201/200).
  Created and read back `First comment from the Spark walkthrough.` with the
  administrator as author (HTTP 201/200); story version advanced to 5.
- PATCH at version 5 succeeded with title `Spark walkthrough verified`,
  version 6. Repeating with version 5 returned HTTP 409 containing both current
  version 6 and submitted edits. History showed successful operations; changes
  returned sequences 1 through 8 with next_seq 8 and no rejected-edit event.
- Move to OTH-1 returned HTTP 422:
  `Cannot move an item from project TRY under a parent in project OTH. Choose a parent in TRY.`
  Readback: `{"key":"TRY-1","parent":{"key":"TRY-2"},"version":6}`.
- Created TRY-3, deleted it (HTTP 200, `{"deleted":true,"key":"TRY-3"}`),
  and read back a deletion timestamp and version 2. Next creation was TRY-4;
  the deleted key was not reused.
- TOTP confirmation initially returned 401, then succeeded using the owner's
  authenticator. Summary: enabled true, sign_in_required true, eight recovery
  codes. Fresh authenticator login and authenticated account read returned 200.
  The old-session rejection was reported as passing by the owner, but its raw
  response was not included. No claim is made about the cause of the first 401
  or Apple Passwords compatibility.
- First use of one recovery code returned HTTP 200, `{"authenticated":true}`;
  reuse returned HTTP 401, `Sign in to continue.` Secrets and codes are omitted.
- After stopping and restarting the application, health returned 200 and the
  existing session read returned
  `{"key":"TRY-1","parent":{"key":"TRY-2"},"title":"Spark walkthrough verified","version":6}`.
  A fresh password-plus-authenticator login returned HTTP 200,
  `{"authenticated":true}`.

Manual workflow and the additional checks above passed. Final closeout awaits
checkout identification and confirmation of the Spark automated-gate status;
this entry does not claim a Spark performance baseline or physical-backup test.
