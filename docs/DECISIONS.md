# sierx — Decision record

Resolutions of ambiguities, conflicts, and gaps in `docs/SPEC.md`, plus decisions
the specification leaves open. Seeded from `docs/BUILD.md` §4 at handover.

`docs/SPEC.md` is normative and **read-only** (BUILD §3.5). Every resolution is
recorded here instead of by editing it, so the normative document is never
rewritten by the thing being measured against it.

**Precedence** (BUILD §0.5):

```
SPEC §5 (Invariants) > SPEC Appendix A > SPEC (rest) > these ADRs > task text > convenience
```

New ADRs are appended by the agent when it hits an ambiguity, using the format in
BUILD §3.5. An ADR that departs from a normative spec section carries
⚠ **REQUIRES SIGN-OFF** and the agent stops until the approval is recorded in
`PROGRESS.md` (BUILD §0.3).

**Sign-off state at handover:** ADR-002, ADR-005, ADR-012, ADR-014 approved
2026-09-12. All others accepted without sign-off required.

---

## Index

| ADR | Subject | Status |
|---|---|---|
| [ADR-001](#adr-001) | The application writes `change_event`, not a trigger | accepted |
| [ADR-002](#adr-002) | ⚠ ⚠ One sequence value per `change_event` row, allocated in exact-size blocks | accepted — approved 2026-09-12 |
| [ADR-003](#adr-003) | `rank` is scoped per project, uniquely and deferrably | accepted (amended v1.1) |
| [ADR-004](#adr-004) | `sxq` keeps the clean grammar; hierarchy predicates land in phase 5 | accepted |
| [ADR-005](#adr-005) | ⚠ ⚠ Rollups are maintained in the store layer, not by triggers | accepted — approved 2026-09-12 |
| [ADR-006](#adr-006) | `item.config_version` advances on create, transition, and promote only | accepted |
| [ADR-007](#adr-007) | One projection registry, generating the client's types | accepted |
| [ADR-008](#adr-008) | Attachments are link-only | accepted |
| [ADR-009](#adr-009) | Theme bands: 60 / 30 / 10 over token families, with status color confined | accepted |
| [ADR-010](#adr-010) | ⚠ Backups: pgBackRest to at least one encrypted off-box repository | accepted (amended v1.3, v1.6) |
| [ADR-011](#adr-011) | Wildcard transitions are enumerated, not stored as a wildcard | accepted |
| [ADR-012](#adr-012) | ⚠ ⚠ Cross-project moves are rejected in v1; config integrity is enforced by the schema | accepted — approved 2026-09-12 |
| [ADR-013](#adr-013) | Every item has an `item_rollup` row, including leaves | accepted |
| [ADR-014](#adr-014) | ⚠ ⚠ Markdown is rendered with raw HTML disabled at the parser | accepted — approved 2026-09-12 |
| [ADR-015](#adr-015) | `PATCH /me` for the preferences §10.2 already persists | accepted |
| [ADR-016](#adr-016) | The benchmark gate runs advisory in CI and blocking on reference hardware | accepted |
| [ADR-017](#adr-017) | The backup harness talks to a driver interface, with two drivers from day one | accepted |
| [ADR-018](#adr-018) | Path is which code ships; query is what it shows | accepted |
| [ADR-019](#adr-019) | Digest pins need an update path, or they are just old images | accepted |

Ordered numerically here for lookup. `docs/BUILD.md` §4 presents the same ADRs
grouped by subject — ADR-017 sits beside ADR-010 because it amends it — so the
two documents differ in order and not in content.

---

## ADR-001 — The application writes `change_event`, not a trigger

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §5.1, A.4. **Deviation:** none — resolves a conflict using the
spec's own precedence rule.

SPEC §5.1 says every mutation writes the allocated sequence value to both
`item.change_seq` and `change_event.seq`, which places the write in the
application. A.4 says `change_event` is "written in the same transaction by
trigger." These cannot both be implemented. §0 rule 3 makes §5 normative, so
**the application writes the event rows.**

This is also the better engineering answer: the event `kind` vocabulary
(`moved`, `promoted`, `field_changed`, `linked`) encodes *semantic intent*, and a
row-level trigger sees only before/after images. A trigger would have to
reconstruct "this was a move, not a field change" from a `parent_id` delta, and
would need `actor_id` and the allocated sequence smuggled in through session
GUCs. A.4's real intent — same transaction, append-only, not event sourcing — is
fully preserved.

**Enforcement.** All writes to `item`, `item_link`, `sprint_item`, and `comment`
go through one function, `store.Mutate` (task 0.8), whose signature makes an
event-less mutation impossible to express. Plus `gate-nodirect` (task 0.8) and
golden tests asserting the exact event rows each endpoint produces.

---

## ADR-002 — ⚠ One sequence value per `change_event` row, allocated in exact-size blocks

**Status:** accepted — approved 2026-09-12  **Recorded:** 2026-09-12

**Spec refs:** §5.1. **Deviation:** ⚠ refines §5.1's statement ordering —
**REQUIRES SIGN-OFF**.

§5.1 prescribes the counter bump as "the first statement of every mutating
transaction" and does not say whether a transaction consumes one value or one per
change. A 200-item bulk transition (a scenario §12 gates) makes the difference
load-bearing.

**One value per `change_event` row.** If a whole transaction shared one value,
`GET /changes?since_seq=` could not paginate inside it: with 200 changes at
`seq=1234` and `limit=50`, any cursor either repeats or skips. Per-row sequencing
keeps `seq` a total order over changes, which is what a cursor needs.

Allocation: the unit of work is accumulated in memory first, then flushed. The
flush's first statement is a single row-locked bump by the exact event count:

```sql
UPDATE seq_counter SET value = value + $2 WHERE workspace_id = $1 RETURNING value;
```

Events get `value - count + 1 … value`. `item.change_seq` is set to the highest
value assigned to that item. Gap-free holds because the bump is in the same
transaction and rolls back with it. Commit-ordered holds because the row lock is
held from bump to commit, so no transaction can commit between another's
allocation and its commit. Contention is one row per workspace, which §5.1
already accepts as irrelevant at ten users, and the lock window is *shorter*
than bumping first — the accumulate phase happens outside the lock.

Allocating exactly — rather than a fixed block — is what keeps the sequence
gap-free. An over-allocating caller would burn values and break the invariant, so
`Mutate` derives the count from the event slice and never takes it as a
parameter.

**Enforcement.** `/test/concurrency`: N parallel writers, a poller following the
cursor throughout, asserting every committed change is observed exactly once and
no value is skipped (§13).

---

## ADR-003 — `rank` is scoped per project, uniquely and deferrably

**Status:** accepted (amended v1.1)  **Recorded:** 2026-09-12

**Spec refs:** §4.4, §5.5. **Deviation:** none. **Amended in v1.1** — the
uniqueness constraint is now deferrable.

One `rank` column has to serve backlog order, board-column order, sprint order,
and sibling order. It can, because all four are *filtered slices of one total
order* — that is the property that makes LexoRank work. The open question was the
scope of that order, and §5.5 answers it implicitly by saying to "rebalance a
project's ranks": **per project.** A workspace-global order cannot be rebalanced
one project at a time without disturbing interleaving with other projects' items.

Insert rule: a drop between two cards sets a rank strictly between the ranks of
its **immediately adjacent items in the current filtered view**. The honest
consequence, which belongs in the UI copy: an item's position relative to items
*not* in the current view is arbitrary. That is how every tool with a single rank
behaves, and nobody notices because the other items are filtered out.

Cross-project ordered views (the portfolio roadmap, phase 5) must order by an
explicit key — rollup dates, or a separate portfolio rank added then. They may
not order by `item.rank`.

**Schema addition:**

```sql
ALTER TABLE item ADD CONSTRAINT item_project_rank_uniq
  UNIQUE (project_id, rank) DEFERRABLE INITIALLY IMMEDIATE;
```

It must be a **constraint, not a bare unique index**, and it must be
`DEFERRABLE`. A non-deferrable unique index is checked per row as rows are
updated, so the single-statement rebalance in §5.5 transiently collides and fails
even though the end state is unique. The rebalance path therefore runs
`SET CONSTRAINTS item_project_rank_uniq DEFERRED;` inside its transaction; every
other write leaves it immediate, so an ordinary generator collision still
surfaces immediately as a retryable `409` rather than at commit.

**Soft-deleted items keep their rank.** A partial constraint
(`WHERE deleted_at IS NULL`) is not available — PostgreSQL cannot back a
deferrable constraint with a partial index — so uniqueness covers deleted rows
too. This is the right trade: rank strings are cheap and keys are never reused
(§5.8, A.1), so there is no reason to recycle a rank either.

**Enforcement.** Property test: after a randomized sequence of reorders within
filtered views, the per-project rank order is a strict total order, no rank
exceeds 40 characters without triggering rebalance, and rebalance preserves
relative order. Plus one test that rebalances a project of 5,000 items in a
single statement and asserts it commits.

---

## ADR-004 — `sxq` keeps the clean grammar; hierarchy predicates land in phase 5

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §7, §16 #3. **Deviation:** none.

§16 asks whether to keep JQL-familiar syntax. The §7.2 examples already answer it
— lowercase `and`, `me()`, dotted `status.category` — so the grammar stays as
specified, with two additions:

1. **Keywords are case-insensitive.** `AND`, `and`, `Order By` all parse.
2. **A thin JQL alias table**, canonicalized at parse time, so muscle memory does
   not produce errors: `currentUser()` → `me()`, `EMPTY`/`NULL` → `is null`,
   `startOfSprint()`/`endOfSprint()` already match. Aliases are a fixed table in
   `/internal/sxq/aliases.go`, not a parallel grammar. Roughly an hour of work
   and no long-term debt.

The grammar in §7.1 does not admit two of its own examples in §7.2 —
`now() + 7d` (no duration arithmetic) and `descendants(status.category = open) > 0`
(no argument-taking functions) — and `order` is defined but never referenced from
`query`. Resolution by phasing:

| Feature | Phase | Notes |
|---|---|---|
| `expr`, `and`/`or`/`not`, parens, precedence `not` > `and` > `or` | 1 | Explicit precedence; parens always allowed |
| `field op value`, lists, `is`/`is not`, `~` full-text | 1 | |
| `order by field [asc\|desc]` wired into `query` | 1 | Default `asc`; stable tiebreak on `id` |
| Duration literals `Nd`, `Nw`, `Nh`, `Nm` and `now() ± duration` | 1 | Resolves to `date`/`timestamptz` per the field's type (A.3) |
| `me()` | 1 | |
| `descendants(expr)`, `ancestors(expr)` with a count comparison | **5** | Needs ltree traversal and rollups; belongs with hierarchy |
| `startOfSprint()`, `endOfSprint()` | **4** | Needs sprints |

Anything not in the phase-1 row is a parse error with a "not available until
phase N" message, not a silent empty result (§7.3).

**Enforcement.** `/test/golden/sxq/`: a corpus of
`query → normalized SQL + ordered params`. Every example in §7.2 is in the
corpus, the phase-5 and phase-4 ones asserting the explicit parse error until
their phase. Plus a fuzz target asserting the compiler never emits a
non-parameterized literal.

---

## ADR-005 — ⚠ Rollups are maintained in the store layer, not by triggers

**Status:** accepted — approved 2026-09-12  **Recorded:** 2026-09-12

**Spec refs:** §5.2, A.5. **Deviation:** ⚠ departs from normative §5.2 —
**REQUIRES SIGN-OFF**.

§5.2 prescribes a row-level trigger appending ancestor ids to a
"transaction-local dirty set" plus a `DEFERRABLE INITIALLY DEFERRED` constraint
trigger that recomputes each dirty ancestor once at commit. Its *goals* are
explicit: recompute once per ancestor per transaction, and avoid the
O(depth × changes) naive version.

The prescribed mechanism is implementable but fragile in exactly the way this
build cannot afford. Postgres has no transaction-local set primitive: the dirty
set must be a temp table (`ON COMMIT DELETE ROWS`, created lazily per session) or
an array in a session GUC. Constraint triggers fire **per row even when
deferred**, so "once at commit" needs a processed-marker in that same structure
to suppress repeats. That is a nontrivial amount of PL/pgSQL whose failure mode
is a silently stale aggregate, and it is the hardest kind of code for an agent to
get right and for a human to review.

**Decision:** `store.Mutate` computes the dirty ancestor set in Go from the paths
it already touched, and recomputes those rollups once per unit of work, in the
same transaction. Same invariant, same transaction, one recompute per ancestor,
no PL/pgSQL. A.5 ("written, never computed on read") is unaffected.

**What this gives up, honestly:** triggers would hold the invariant even for
writes that bypass the application — `sierxctl`, a migration, a manual `psql`
fix. Store-layer maintenance does not. Three compensating controls:

1. `gate-nodirect` (task 0.8): no `INSERT`/`UPDATE` on `item` outside
   `/internal/store`.
2. `sierxctl rollup --verify [--repair]`, which recomputes from `ltree` and diffs
   against `item_rollup`; run in the nightly restore test.
3. The §13 property test, which asserts `parent.rollup == aggregate over
   descendants` after randomized create/move/delete/reparent/transition
   sequences — this catches drift regardless of who caused it.

**Approved 2026-09-12.** The §5.2 trigger design stays in `docs/DECISIONS.md` as
the recorded alternative: if this ADR is ever superseded, implement §5.2 as
written. The property test and `sierxctl rollup --verify` stay either way, which
is what makes the two implementations interchangeable.

---

## ADR-006 — `item.config_version` advances on create, transition, and promote only

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §4.3, §4.4, Appendix B glossary. **Deviation:** none.

The glossary says items "reference the version in force at their last
transition." So: **create**, **transition**, and **promote** (a type change, and
type is config) set `config_version` to the project's current version. Title,
body, assignee, points, dates, custom fields, moves, links, and comments do
**not** touch it.

Consequence: an item edited but not transitioned for six months still reports
under the config version of its last status change, which is precisely the point
— a status rename cannot retroactively alter what a historical chart means.

**Enforcement.** Golden tests: `PATCH /items/{key}` with a title change asserts
`config_version` unchanged; `POST /items/{key}/transition` asserts it advanced to
the project's current version.

---

## ADR-007 — One projection registry, generating the client's types

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §6.1. **Deviation:** none.

`?fields=` is required on every collection endpoint, and the spec's example
(`key,title,status,assignee,points,due_date`) leaves the shape of a composite
like `status` undefined. Without one authority the backend and frontend drift on
day one.

A single declarative registry in `/internal/api/projection/registry.go` maps API
field names to SQL columns and JSON shapes:

| Requested | Emits |
|---|---|
| `status` | `{"key","name","category"}` — never the uuid; clients address config by key |
| `status.category` | scalar |
| `assignee` | `{"id","display_name"}` — the uuid is needed to address a user |
| `type` | `{"key","name","level"}` |
| `parent` | `{"key"}` |
| `project` | `{"key_prefix","name"}` — needed because an item's key prefix is not its project (A.1) |
| `fields.<key>` | scalar or array, per `field_def.data_type` |
| `rollup` | `{"descendant_count","done_count","points_total","points_done","earliest_start","latest_due"}` |

Rules: unknown field name → `400` problem+json naming the field and the closest
valid alternative, never a silent drop. Dotted paths select a leaf. Requesting a
composite and one of its leaves is not an error; the leaf is redundant.

**Which endpoints require `?fields=`.** §6.1 says "all collection endpoints,"
which is ambiguous for three of them. Resolved: **required** on `/items`,
`/items/{key}/children`, `/items/{key}/descendants`. **Not applicable** to
`/changes` (its rows are events, not items, and its shape is fixed by §5.1),
`/comments` (four fields total), `/views`, or `/items/{key}/history`. Requesting
`?fields=` on a not-applicable endpoint is a `400`, not a silent ignore.

**Enforcement.** The registry generates `web/src/api/fields.ts` (types plus the
legal field-name union) via `make gen-fields`; `make gate-gen` fails if the
checked-in file differs from freshly generated output — the same pattern as
`sqlc diff`. A golden test pins the JSON shape of every registry entry.

---

## ADR-008 — Attachments are link-only

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §16 #4, §4.3. **Deviation:** none.

The `url` `field_def` data type already exists. A project that wants attachments
declares a `url` field. No blob storage, no upload endpoint, no virus-scanning
question, no backup-size surprise, zero new schema. If real file attachments are
ever wanted, they are a phase-8 conversation with an object-store dependency, not
a v1 feature.

---

## ADR-009 — Theme bands: 60 / 30 / 10 over token families, with status color confined

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §9.3, §10.2, §10.3, §10.4.2. **Deviation:** none.

The 60/30/10 proportion rule is adopted, mapped to *surface area across token
families* rather than to hues:

| Band | Tokens | Constraint |
|---|---|---|
| 60% | `--background`, `--card`, `--muted` | Near-neutral: chroma ≤ 0.02 OKLCH. A saturated dominant is wrong for hours of dense reading and makes the contrast math harder across four palettes |
| 30% | `--border`, `--input`, `--muted-foreground`, secondary surfaces | One low-chroma hue family; carries structure |
| 10% | `--primary`, `--ring`, `--destructive`, `--status-open\|active\|done\|cancelled` | The accent budget, shared |

**The amendment that makes it work.** Seven tokens compete for that 10%, and four
of them are status colors that appear on every card of the board — the one view
that is mostly cards. Literal 60/30/10 breaks there. So: **status color may only
be applied as a ≤3px left edge or a 12–16px glyph — never a card fill, never a
chip background.** That holds the area budget, and it is what §10.4.2 (never
color alone) and §9.3 (elevation encodes state, not decoration) already push
toward.

**Enforcement.** The proportion itself is a design-review item and this guide
says so rather than pretending it is gated. What *is* gated:

- stylelint rule: `--status-*` may appear only in `border-left-color`,
  `border-inline-start-color`, `fill`, `stroke`. Any other property fails the
  build.
- The token unit test (§10.3) gains a chroma ceiling assertion on the 60% band
  alongside the contrast ratios it already computes.

---

## ADR-010 — ⚠ Backups: pgBackRest to at least one encrypted off-box repository

**Status:** accepted (amended v1.3, v1.6)  **Recorded:** 2026-09-12

**Spec refs:** §14.2, §1.2 #7. **Deviation:** none. **Status: BLOCKED** on one
input. **Amended in v1.3** — pgBackRest is now one implementation of ADR-017's
interface, and the repository configuration below is pinned rather than left to
be discovered.

§14.2 requires continuous off-box WAL archiving, weekly `pg_dump` as a second
mechanism, and a scheduled restore test — and names a bad restore as the most
likely cause of real loss. pgBackRest does all three with verification built in,
is MIT licensed (**high (verified)**, so it clears the §15.1 allowlist), and has
arm64 builds for the Pi. Barman is excluded by the allowlist: it is GPL-3.

One caveat worth recording rather than discovering later: a 2026 survey of
Postgres backup tools claims pgBackRest no longer accepts outside contributions
and recommends WAL-G or pgmoneta for new deployments. Against that, the project
is still cutting releases (v2.59.x) with 2026 copyright and current sponsors.
Treat it as a watch item, not a blocker; **WAL-G (Apache-2.0) is the pre-approved
swap** if maintenance status changes, and the restore-test harness is written
against a `make` target, not against pgBackRest's CLI, so the swap is local.

**Repository configuration, pinned now because three of these are not cheaply
reversible.** All verified against pgBackRest's documentation at the current
release line (2.59.x).

| Requirement | Why | Reversible later? |
|---|---|---|
| Encryption at `stanza-create`: `repoN-cipher-type=aes-256-cbc`, passphrase from `openssl rand -base64 48` | A repository is a full copy of the team's work sitting on someone else's storage. Turning encryption on is a per-repository property fixed when the stanza is created | **No** — it means a new repository or stanza. **moderate**; task 0.11 verifies against the installed version before committing the config |
| Always pass `--repo=N` explicitly, even with one repository | `--repo` is optional when only `repo1` exists but **required** when the single configured repository is `repo2` — pgBackRest's own docs say this exists to prevent command breakage when a repository is added later. Passing it from day one makes adding `repo2` a config change with no command edits. **high (verified)** | Yes, but every call site changes |
| Configuration generated from environment, never hand-edited | §14.4 is environment-only. `scripts/backup/render-conf.sh` writes `pgbackrest.conf` from env, so changing target is an env change plus a re-render | Yes |
| Harness handles up to four repositories from its first commit; ship with one | Up to four are supported, any type per repository; `archive-push` writes to all, `archive-get` searches all in priority order, retention is per-repository. The common shape later is a fast local/SSH `repo1` for restore speed plus cloud `repo2` for survival. **high (verified)** | Yes |
| The scheduled restore test rotates which repository it restores from | A secondary repository nobody has ever restored from is not a backup, it is a second place the same bad assumption lives | Yes |
| `stanza-upgrade` in the PostgreSQL major-upgrade runbook | After a major upgrade, `pg1-path` must point at the new cluster and `stanza-upgrade` must run **before starting it**; skip it and archiving breaks quietly. PG 18 → 19 is a real event for a tool holding the team's work. **high (verified)** | n/a — it is a procedure, and it is only future-proof if it is written down |

**Two targets, set at two different times.** Earlier versions of this guide
collapsed them, which is what made phase 0 look like it needed an infrastructure
decision.

| | Dev | Staging and prod |
|---|---|---|
| Set at | Task 0.1, in the untracked `.env` | Task 2.16, in the host's `0600` env file |
| Type | `posix` to a local path | `sftp` (recommended) or `s3` |
| Protects | Nothing. `make db-reset` destroys this database by design | The team's actual work |
| Exists to | Exercise the harness so task 0.11's restore test is real | Satisfy §14.2's off-box requirement |

**Dev — no decision required:**

```
SIERX_BACKUP_DRIVERS=pgbackrest,pgdump
PGBACKREST_REPO_TYPE=posix
PGBACKREST_REPO_PATH=/var/lib/sierx/backup-repo
SIERX_DUMP_PATH=/var/lib/sierx/dumps
PGBACKREST_CIPHER_PASS=<openssl rand -base64 48>
```

**Deployment — recommended `sftp` to a host already in service**, with an
S3-compatible `repo2` added if off-site redundancy is wanted. No account to
create, no egress cost, no new vendor, and its failure mode is one the operator
already understands. ADR-017 makes the choice cheap to reverse, so the cheap
option is the right one to start with; the decision belongs at task 2.16, with
the deploy, not five weeks earlier.

**The guard that keeps dev from becoming production.** `bootstrap-check` fails
when `PGBACKREST_REPO_TYPE` is unset, **and fails on `posix` whenever
`SIERX_ENV` is not `dev`**. A local repository is a test fixture in dev and a
data-loss event in production; the only thing distinguishing those two readings
is an environment variable, so the check reads it rather than trusting anyone to
remember. Task 2.16's acceptance therefore cannot pass with a dev-shaped
repository — which is the enforcement §14.2 always needed and did not have.

Types and paths that contain no host are safe to commit in `.env.example`. A real
hostname, bucket, cipher passphrase, or S3 key is not (§3.7): those live in the
untracked `.env` and the host's `0600` env file — never in git, never in
`.env.example`, never in a prompt. `bootstrap-check` reads the environment, not
the example file.

---

## ADR-011 — Wildcard transitions are enumerated, not stored as a wildcard

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §4.3, §8.1, §8.2. **Deviation:** none — resolves a conflict
between a normative schema and a phase-7 file format.

§8.1's YAML contains `{from: "*", to: dropped}`. §4.3's `config_transition` has
`from_status_id uuid NOT NULL` and it is part of the primary key, so a wildcard
has nowhere to live. Making the column nullable is not available either:
PostgreSQL primary-key columns are implicitly `NOT NULL`, so the nullable version
requires replacing the PK with a `UNIQUE NULLS NOT DISTINCT` index and then
special-casing NULL in every transition lookup.

**Decision: expand wildcards at write time.** A `from: "*"` entry becomes one
`config_transition` row per live status in that config version. The schema is
untouched, transition validation stays a single indexed lookup, and the seed
config in phase 0 writes the expanded rows directly.

**Consequence, which belongs in phase 7's `plan` output:** a status added in a
later config version does **not** automatically acquire the wildcard
transition — the expansion happened against the statuses live at apply time. That
is a real behavioural difference from a stored wildcard and `plan` must name it,
in the §8.2 style: `+ status "blocked" added — no transition to "dropped"; add
{from: "*"} to regenerate`.

**Enforcement.** A test over the seeded config asserting that every status whose
category is `open` or `active` has at least one transition to a status whose
category is `done` or `cancelled`. This is the same reachability check §8.2's
warning needs, so it is written once and reused in phase 7.

---

## ADR-012 — ⚠ Cross-project moves are rejected in v1; config integrity is enforced by the schema

**Status:** accepted — approved 2026-09-12  **Recorded:** 2026-09-12

**Spec refs:** §4.3, §4.4, §5.3, A.1. **Deviation:** ⚠ narrows a capability A.1
implies — **REQUIRES SIGN-OFF**.

A.1 says keys "never change when an item moves between projects," which implies
items can change project. Nothing in §5 says what happens to the item's config
when they do — and `item.status_id`, `item.item_type_id`, and
`item.config_version` are all project-scoped. An item moved to another project
while keeping `status_id` would point at a status belonging to a project it is no
longer in, which silently destroys §4.3's entire guarantee: the historical chart
would resolve the item's status through the wrong project's config.

`POST /items/{key}/move` takes `{parent, rank_after?}`. A parent in another
project is the path by which this happens.

**Decision:** in v1, `move` rejects a parent in a different project with `422`
and a problem+json body naming both projects. `project_id` is immutable after
create. The guarantee A.1 actually cares about — that a key is permanent and
never rewritten — is untouched; the capability is deferred and the deferral is
explicit rather than discovered.

**Enforced in the schema, not only the handler.** Composite foreign keys make the
corrupt state unrepresentable:

```sql
ALTER TABLE status    ADD CONSTRAINT status_project_id_uniq    UNIQUE (project_id, id);
ALTER TABLE item_type ADD CONSTRAINT item_type_project_id_uniq UNIQUE (project_id, id);

ALTER TABLE item
  ADD CONSTRAINT item_status_in_project
    FOREIGN KEY (project_id, status_id)      REFERENCES status(project_id, id),
  ADD CONSTRAINT item_type_in_project
    FOREIGN KEY (project_id, item_type_id)   REFERENCES item_type(project_id, id),
  ADD CONSTRAINT item_config_version_exists
    FOREIGN KEY (project_id, config_version) REFERENCES project_config(project_id, version);
```

The third one is worth noticing on its own: §4.4 declares
`config_version int NOT NULL` with no referential integrity at all, so before
this constraint an item could reference a config version that does not exist.

**Consequence.** Cross-project *links* still work in every direction (§4.6) —
that is the mechanism §11.4 and phase 5's dependency overlay actually use.
Cross-project *hierarchy* does not. If phase 5's portfolio roadmap wants a parent
spanning projects, ADR-012 is superseded then and the work is: a status/type
remapping decision, a `project_changed` event kind carrying both config versions,
and rank regeneration in the destination project. The `move` handler is the only
call site that changes.

**Enforcement.** Task 0.5 asserts each constraint raises on a crafted violation.
Task 1.13 asserts the `422` with a golden body.

---

## ADR-013 — Every item has an `item_rollup` row, including leaves

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §4.5, §13, A.5. **Deviation:** none.

§4.5's primary key is `item_id`, §13's property test says
"`parent.rollup == aggregate over descendants` for every non-leaf," and ADR-007's
projection emits `rollup` for any item. Whether a leaf has a row is undefined,
and the answer changes the read path.

**Decision: one row per item, inserted in the same `Mutate` that creates the
item, zeros for a leaf.** The hot read path becomes a plain join instead of a
`LEFT JOIN` plus six `coalesce`s; `?fields=rollup` has one unconditional shape;
`sierxctl rollup --verify` becomes a row-for-row diff with no "missing row"
case to reason about. The cost is one narrow row per item — 10k rows in the seed
workspace, which is nothing.

Soft-deleted items keep their rollup row. Hard delete is already handled by
§4.5's `ON DELETE CASCADE`.

**Enforcement.** Property test asserts
`count(item_rollup) == count(item)` after every randomized sequence, and that a
leaf's row is all zeros/nulls rather than absent.

---

## ADR-014 — ⚠ Markdown is rendered with raw HTML disabled at the parser

**Status:** accepted — approved 2026-09-12  **Recorded:** 2026-09-12

**Spec refs:** §1.3, §4.4, §4.8, §9.1, §9.2. **Deviation:** ⚠ adds a dependency
and a security boundary neither document specifies — **REQUIRES SIGN-OFF**.

§1.3 bans a rich-text editor; item bodies and comments are Markdown "rendered
client-side." Neither document names a renderer, and neither mentions
sanitization. Rendering untrusted Markdown in the browser is stored XSS by
default, because most renderers pass raw HTML through — and `body` is
user-supplied text with no validation beyond `NOT NULL` on comments.

**Decision:** `markdown-it` configured
`{ html: false, linkify: true, typographer: false, breaks: false }`.

With `html: false` the parser escapes raw HTML rather than emitting it, so there
is no HTML for a sanitizer to clean and **no sanitizer is added.** The remaining
vector is the link protocol, and markdown-it's default `validateLink` already
rejects `javascript:`, `vbscript:`, `file:`, and all but a small set of image
`data:` URIs. **high (verified)** We narrow it further to `https?:` and `mailto:`
only, since nothing in sierx needs an image data URI in a comment. Links render
with `rel="noopener noreferrer"`.

This is deliberately *not* DOMPurify plus `html: true`. That combination is a
larger dependency, a bigger attack surface, and a licensing question (DOMPurify
is dual Apache-2.0 / MPL-2.0, and MPL is on §15.1's blocked list — dual
licensing means the Apache-2.0 arm is available, but it is a conversation the
license gate will start and nobody needs to have).

**Bundle.** markdown-it is not free — roughly 35–40KB minified before brotli, on
a first-route budget of 250KB whose own estimate in §9.1 is already 170KB and
does not include it. It is therefore **dynamically imported by the item-detail
route only**, where it counts against the 60KB lazy-chunk budget instead. The
list view renders titles, not bodies, so the first route never loads it.

**Licence:** markdown-it is MIT. **moderate (training data)** — `gate-license`
is the authority and runs before the dependency is committed.

**Enforcement.** A golden test over a hostile corpus — `<script>`,
`<img src=x onerror=…>`, `<iframe>`, `javascript:` and `data:text/html` links,
an HTML comment, a raw `<style>` block — asserting the rendered output contains
no element outside the allowed set and no `on*` attribute. Plus `gate-bundle`,
which fails if markdown-it appears in the first-route chunk.

---

## ADR-015 — `PATCH /me` for the preferences §10.2 already persists

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §4.1, §6.2, §10.2. **Deviation:** none — supplies a write path the
endpoint list omits.

§10.2 persists the selected theme server-side on `user_account.theme` and
injects it into the initial HTML. §4.1 also carries `reduced_motion`. §6.2 lists
`GET /api/v1/me` and no way to write either one, so phase 2's theme switcher has
nothing to call.

**Decision:** `PATCH /api/v1/me`, accepting `theme`
(`system|light|dark|light-hc|dark-hc`), `reduced_motion` (`true|false|null`), and
`display_name`. No new table, no new endpoint family. Email, password, TOTP, and
`is_active` are **not** writable here — they are auth operations and belong with
task 1.3 and 1.5.

**`/me` is the one mutation exempt from `If-Match`.** §5.4 requires it on all
mutations, but its stated rationale is two people editing one item; nobody
co-edits their own preferences, and a `428` on a theme toggle is a worse
interface than the conflict it prevents. The exemption is recorded here so it
reads as a decision rather than an oversight, and task 1.11's blanket rule points
at it.

**Enforcement.** Golden files for a valid patch, an invalid theme value (`400`
naming the legal set), and an attempt to patch `email` (`400`). A test asserting
`PATCH /me` without `If-Match` succeeds while `PATCH /items/{key}` without it
returns `428`.

---

## ADR-016 — The benchmark gate runs advisory in CI and blocking on reference hardware

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §12, §13. **Deviation:** none.

§12's thresholds are "all measured on the Pi 5 reference box with a 10k-item
seeded workspace." v1.0 of this guide put `gate-bench` inside `gate-0`, and
`gate-0` runs in CI on shared GitHub runners — which have neither the Pi's
performance profile nor stable timing. A threshold gate there is either
permanently red or meaningless noise, and there is no Pi deployment until task
2.16 anyway.

**Decision:** two targets.

| Target | Where | Behaviour |
|---|---|---|
| `bench-smoke` | CI, inside `gate-0`…`gate-7` | Runs every benchmark once against the seeded database, asserts none *errors*, prints timings, **never fails on a threshold**. Catches a benchmark that stopped compiling or a query that started erroring |
| `gate-bench` | Reference hardware, human-run | The §12 thresholds as assertions against a checked-in baseline. A **human gate** in every phase's list (§3.2) |

The baseline is captured by `make bench-baseline` on the reference box and
committed. Until task 2.16 stands up staging, there is no baseline and
`gate-bench` reports "no baseline — run bench-baseline on the reference box"
and exits nonzero, which is correct: it is an unmet human gate, not a passing
one.

**Enforcement.** `bench-smoke` lists skipped scenarios by name (§12 rows whose
endpoints do not exist yet), never silently. `prove-gates` covers `gate-bench` by
regressing the baseline file, not by slowing down real code.

---

## ADR-017 — The backup harness talks to a driver interface, with two drivers from day one

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §14.2, §1.2 #7, §13. **Deviation:** none — future-proofs a
decision ADR-010 already flagged as a watch item.

ADR-010 records that pgBackRest's maintenance status is worth watching and names
WAL-G as a pre-approved swap, and v1.1 of this guide said the harness is "written
against a `make` target, not against pgBackRest's CLI, so the swap is local."
That is an aspiration, not a mechanism. A swap nobody has executed is a swap
nobody has.

**Decision:** `scripts/backup/driver-<name>.sh`, each implementing exactly six
verbs with identical contracts and exit semantics:

| Verb | Contract |
|---|---|
| `init` | Idempotent. Prepare whatever the driver needs (stanza, target directory). Exit 0 if already prepared |
| `backup` | Take one backup. Print an opaque backup id on stdout |
| `verify` | Check repository integrity without restoring. Exit nonzero on any corruption |
| `restore-to <dsn>` | Restore the most recent backup into an empty scratch database at `<dsn>`. The only verb the restore test calls |
| `retention` | Apply this driver's retention policy (§14.2: 30 days WAL, 8 weekly dumps) |
| `describe` | One line: driver name, tool version, configured targets. For `PROGRESS.md` and `/healthz` |

`SIERX_BACKUP_DRIVERS` is an ordered list; `make` targets never name a tool.

**Two drivers exist from the first commit, at no extra scope,** because §14.2
already requires both mechanisms:

- `pgbackrest` — physical, continuous WAL archiving, point-in-time recovery
- `pgdump` — weekly logical dump in custom format

They are not two copies of one idea. Their failure modes differ, which is what
§14.2 asks for, and their **portability** differs, which matters more: a
`pg_dump -Fc` file is restorable by any future PostgreSQL with no pgBackRest
installed and no matching major version, while a physical repository is tied to
both. That makes the dump driver the escape hatch for §1.2 #7 ("portable by
construction") rather than merely a second copy — and it means the interface has
two real implementations on day one instead of one implementation and a promise.

**The scheduling consequence, which is the point.** The interface, the `pgdump`
driver, and the conformance suite require no repository target. They are
buildable and green while ADR-010's input is outstanding, so task 0.11 is
partially blocked rather than wholly blocked, and adding pgBackRest later is
`init` plus one conformance run.

**Consequence and cost.** Roughly 150 lines of shell plus one test harness. What
it buys is that the tool choice stops being expensive to reverse, which is the
only reason ADR-010's watch item is a watch item rather than a risk. What it does
not buy: an interface over tools you have never both run is theatre, which is why
the conformance suite is the enforcement and not documentation.

**Enforcement.**
- `make backup-conformance` runs **every** driver in `SIERX_BACKUP_DRIVERS`
  through one shared assertion set: `init` → `backup` → `verify` →
  `restore-to` a scratch database → per-table row counts → content checksum →
  `sierxctl rollup --verify` on the restored copy. A driver that has not passed
  it is not a driver.
- `scripts/gate-nobackupleak.sh`: fails on a literal `pgbackrest`, `pg_dump`, or
  `wal-g` outside `scripts/backup/driver-*.sh` and `deploy/pgbackrest/`. Same
  shape as `gate-nodirect` (ADR-001), for the same reason — an abstraction with
  one leak is not an abstraction.
- `describe` output is pasted into `PROGRESS.md` at task 0.11, so which tool and
  version produced a given green restore test is recoverable a year later.

---

## ADR-018 — Path is which code ships; query is what it shows

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §7, §9.1, §9.2.2, §6.2, A.1, §5.8. **Deviation:** none — specifies
something neither document covers.

SPEC §7 says every sxq query is URL-addressable so that a link is a shareable
view, and says nothing else about URLs. The browser-visible route scheme is
therefore undefined, which under §0.4 means the agent must stop and ask — at task
2.7, after the list view is half built.

**The organizing rule comes out of §9.1, not taste.** That section requires
route-level code splitting with exactly one eagerly-imported route, and says
board code must not ship on the roadmap route. So the **path** is the code-split
boundary — which bundle loads — and the **query string** is the data selector.
Anything that is view state over the same document goes in the query, because §7
already put filters there and two mechanisms for "which view of this thing" is
the thing to avoid.

```
/                       list view — the one eager route
/?q=<sxq>               filtered list; the shareable view of §7
/SRX-42                 item detail
/board?q=<sxq>          phase 3, lazy chunk (dnd-kit ≈30KB)
/roadmap?q=<sxq>        phase 5, lazy chunk
/views/<id>             saved view → resolves to a view type plus q (task 1.18)
/projects/SRX           project overview
/projects/SRX/config    project config (read-only until phase 7)
/login   /settings      auth, preferences
/api/v1/*               reserved; never an SPA route
```

**No project segment in an item's URL, ever.** A.1 says an item's key never
changes when it moves between projects, so an item's key prefix need not match
its current project. `/PLAT/SRX-42` is a URL that can become wrong; `/SRX-42`
cannot. Item keys match `^[A-Z][A-Z0-9]{1,9}-[0-9]+$` (§4.2, §4.4), which does
not collide with any lowercase root segment.

**No path suffixes under an item key.** Item detail (task 2.10) is one page —
fields, body, history, linked items, comments — not tabs. If a panel ever needs
deep-linking, it is `?panel=history`, not `/SRX-42/history`, so view state has
exactly one home.

**Decisions the scheme forces, recorded so they are not made twice:**

| | Decision | Why |
|---|---|---|
| Query string, not fragment | `?q=`, never `#q=` | Not stylistic. Task 2.4 injects first-screen state into `index.html`, so the **server must see the query**. A fragment never reaches it, and a list view addressed by fragment silently loses bootstrap injection and gets the §9.2.2 waterfall instead |
| Case | Accept `/srx-42`, `308` to canonical `/SRX-42` | Keys are uppercase; people type lowercase |
| Trailing slash | `308` to the no-slash form | One canonical URL per document |
| Soft-deleted items | Render with a banner; **do not 404** | Keys are never reused (§5.8, A.1), so `/SRX-42` stays meaningful permanently. A 404 on a link someone shared six months ago is the worse failure |
| Reserved key prefixes | `POST /projects` refuses prefixes colliding with a root segment | `^[A-Z][A-Z0-9]{1,9}$` admits `API`, `LOGIN`, `BOARD`, `VIEWS`. Cheap now, a migration later |

**Consequence, and the cost worth naming.** Because task 2.4 has the Go server
deciding what to embed from the URL, the route table exists on both sides. That
is real coupling: a route added to the client router and not to the Go table
still renders, just slowly and silently, which is the worst failure shape
available. So the table is declared **once**, in
`web/src/routes/table.ts`, and generated into Go by `make gen-routes` — the same
generate-and-diff pattern as ADR-007's projection registry and sqlc.

The reserved-prefix list is the exception, and deliberately so. It is needed by
`POST /projects` in **phase 1**, where no `/web` tree exists yet and creating one
would be forward scaffolding (§0.4). So Go owns it (`internal/api/reserved.go`,
task 1.9) and phase 2's `gate-routes` asserts the inclusion the other way: every
root segment in the route table must appear in the Go list. Neither side can
drift without a red build, and no phase depends on a later one.

**Enforcement.** `make gate-routes` fails if the generated Go route table differs
from freshly generated output, and a test asserts every route in the table
resolves to a bootstrap-injection handler. Plus a redirect test over the case and
trailing-slash rules, and one asserting a soft-deleted item renders rather than
404s.

---

## ADR-019 — Digest pins need an update path, or they are just old images

**Status:** accepted  **Recorded:** 2026-09-12

**Spec refs:** §15.4, §15.3, §1.3. **Deviation:** none — supplies the half of
§15.4 that was missing.

§15.4 requires base images pinned by digest, vendored Go modules, `go mod verify`,
and an SBOM per release. Pinning is the right call — a tag is mutable and a
digest is not — but nothing in either document ever *moves* a pin. A digest pin
with no update mechanism is an unpatched base image with extra steps, and it
fails silently: the build stays green while the image ages.

**Decision:** `.github/dependabot.yml` covering `gomod`, `npm`,
`github-actions`, and `docker`, weekly, grouped into one pull request per
ecosystem. It is configuration only — no service, no runner, nothing to operate
— so §1.3's anti-goals are untouched, and it is free on a public repository.

Every proposed bump arrives as a pull request that must pass the current phase's
gate. That is the point: `gate-license` (task 0.13) re-runs on the new dependency
tree, `gate-bundle` re-runs on the new frontend tree, and the golden files
re-verify under the pinned toolchain. A bump that breaks a gate is visible as a
red pull request rather than as a surprise at the next release.

**Excluded from automation:** the Go and Node toolchain pins (§1) and the
PostgreSQL major version. Those are deliberate, dated decisions with migration
consequences — Node 26's LTS transition in October 2026 is already a scheduled
task, and a PostgreSQL major bump requires `stanza-upgrade` and a restore test
(ADR-010). Dependabot may open the pull request; a human closes or merges it.

**Enforcement.** `gate-license` and the phase gate on every Dependabot pull
request — which is automatic, since they run on all pull requests. Plus a note in
`PROGRESS.md` at each phase exit recording whether any pin is more than one cycle
behind, so drift is visible at a gate rather than at an incident.


## ADR-020 - Owner-directed schedule and initial deployment environment

**Status:** accepted by explicit owner direction in the takeover conversation,
2026-09-18. **Deviation:** supersedes SPEC section 0 rule 5 and the corresponding
BUILD calendar requirement. SPEC itself remains unchanged as the design record.

There is no Phase 2 calendar deadline. The original October 10 date is historical;
the ranked cut list is available for deliberate scope decisions, not automatic
cuts on a clock. Small tasks, phase gates and the seven-day real-use gate remain.

The Spark is the initial test and deployment host for using sierx to track its
own development. The Pi is not required at present. Keep disposable acceptance
databases separate from the persistent backlog. Preserve Linux amd64/arm64,
environment-based configuration and deployment portability. Spark measurements
may describe the Spark, but cannot satisfy a performance claim about smaller
hardware. Choose representative hardware before asserting the small-host budget;
that choice must not be silently replaced with the faster Spark baseline.

This decision does not approve a backup exception, certify the untested local
CI container, authorize production operation or sign off Phase 1 entry.


## ADR-021 - Accepted Phase 0 backup exception and Phase 1 entry

**Status:** approved by the owner, 2026-09-18, in the takeover conversation.
**Scope:** amends Phase 0 entry/exit requirements in BUILD for task 0.11;
retains the deployment durability requirements of ADR-010 and SPEC 14.2.

The offline Phase 0 gate passed on the Spark with pgdump conformance, including
15,438 restored items and zero rollup mismatches. The owner approved deferring
pgBackRest conformance and cipher-immutability validation to task 2.16 and
entering Phase 1. Task 0.11 remains partially implemented; approval does not
turn an untested driver into a supported driver.

Before the deployed backlog becomes relied-upon data, configure encrypted
off-machine backup and prove an isolated physical restore and cipher checks.
Keep the physical driver out of the configured driver list until conformance
passes. Do not relax backup or restore requirements to achieve deployment.

The owner's instruction also authorizes publishing the reviewed Phase 0
closeout. Phase 1 implementation follows BUILD task order and acceptance;
this decision is not acceptance of any Phase 1 code.

## ADR-022 - Phase 1 authentication defaults

**Status:** owner authorized documented, tested defaults on 2026-09-18.
**Scope:** details left unspecified by SPEC 11.2; no architecture change.

Local passwords use Argon2id with 64 MiB, three iterations, one lane, a random
16-byte salt and 32-byte output. New passwords require 12–1024 bytes. Login
performs at most one password calculation concurrently, and allows ten attempts
per source address per minute, with bounded in-memory accounting. Proxy headers
never influence the source address used for these limits.

Session tokens contain 32 random bytes encoded as base64url; only the SHA-256
hash is stored. Sessions expire after 12 hours without sliding extension and
logout removes the stored session. The cookie is `__Host-sierx_session`, path
`/`, Secure, HttpOnly, SameSite=Lax, with no Domain. HTTPS is required for normal
browser use. CLI smoke tests explicitly handle the cookie over loopback.

JSON mutations reject unknown fields and bodies over 1 MiB. Browser Origin
headers must match SIERX_BASE_URL; requests without Origin are permitted for
non-browser API clients. Password/session/database errors never enter response
detail text. Account inactivity is checked on every authenticated request.

Proxy authentication uses a single `X-Sierx-Email` header supplied by the
authenticating proxy. The proxy must remove any client-supplied value before
setting it. Only the immediate TCP peer is checked against trusted CIDRs;
Forwarded, X-Forwarded-For and X-Real-IP cannot establish trust. The email must
identify an active, pre-provisioned member with a NULL password hash. No user
is created implicitly. Proxy mode does not accept local login or logout;
sign-out is handled by the authenticating proxy. Local mode ignores identity
headers. The operational health endpoint remains unauthenticated.

TOTP uses RFC 6238 SHA-1, six digits, 30-second periods and at most one period
of clock skew. Enrollment requires the current password, expires after ten
minutes and becomes active only after code verification. The existing
totp_secret bytea stores an AES-GCM encrypted state envelope bound to the user
ID, using a domain-separated SHA-256 derivation of SIERX_SESSION_KEY. Keep this
key with protected backups; changing it requires re-enrollment. Eight random
128-bit recovery codes are shown once, stored hashed and consumed once.
TOTP step replay and recovery reuse are prevented under a database row lock;
code consumption and login session creation commit together. Enabling or
disabling TOTP revokes existing sessions. Disable requires the password and a
fresh TOTP or recovery code. Proxy mode delegates second factors to the proxy.

Local endpoints are POST `/auth/totp/enroll` (password), `/auth/totp/verify`
(code), and `/auth/totp/disable` (password and code), under `/api/v1`.
Login accepts an optional `code` carrying either factor. Enrollment and
verification require an authenticated session. These routes mutate account
security, not versioned items, and do not require an item If-Match header.

## ADR-023 - Phase 1 API representation and pagination defaults

**Status:** owner authorized documented, tested defaults on 2026-09-18.

Collection responses contain `data` and nullable `next_cursor`. Cursors are
versioned JSON authenticated with HMAC-SHA-256 and base64url encoded, bound to
the requesting user/workspace, path and filters. They carry the last sort value,
stable identifier and an upper boundary chosen on the first page. Invalid,
tampered or differently scoped cursors return 400. Limits default to 50; values
outside 1–200 and all offset parameters are rejected. Inserts beyond the initial
upper boundary appear after refreshing the collection. This is keyset traversal,
not a persisted database snapshot; mutable sort/filter changes are reconciled
through the change feed. Stable ID ordering is the default when no order is given.

Item detail allows optional fields; items/children/descendants require them.
Fixed-shape project, link, comment, history, view, config and rollup responses
reject fields. Dotted selection preserves the containing JSON object; a whole
composite makes any requested leaf redundant. Unconfigured custom fields fail.

If-Match applies to mutations of an existing item, including its transitions,
hierarchy, links and comments. Creation has no prior item version to match;
POST items/projects/views and authentication/account actions do not require
an item If-Match. Item PATCH accepts editable scalar fields and a custom-field
overlay; identity, type, status and hierarchy use their own actions. A conflict
contains `current` and, for submitted item edits, `submitted`. Values are not
silently overwritten. Points are nonnegative, at most 9999.99, with two decimal
places; dates use YYYY-MM-DD and assignees must be active workspace members.
An item delete affects that item, preserves its key and remains readable by key.
New local items set origin_seq to their allocated creation sequence.
