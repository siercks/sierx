# sierx — Technical Specification

**Version:** 0.1 (draft)
**Date:** 2026-09-11
**Status:** Pre-implementation. Sections marked ⚠ contain decisions that are expensive to reverse.
**License:** Apache-2.0

---

## 0. How to use this document

This spec is written to be handed to a coding agent (Claude Code) one phase at a time. Rules for that process:

1. **Work one phase at a time.** Do not generate stubs for future phases. The characteristic failure mode of agent-assisted development on a spec this size is a plausible-looking scaffold across all seven phases with nothing usable in any of them.
2. **No phase N+1 code merges until phase N has been in daily use for a week.** Dogfooding is the only reliable signal about which later phases are actually wanted.
3. **§5 (Invariants) is normative and overrides convenience.** Several rules there are counter-intuitive and the obvious implementation is wrong. If an implementation conflicts with §5, §5 wins.
4. **When this spec is ambiguous, ask rather than infer.** Record the resolution back into this document.
5. **Phase 2 has a calendar deadline: four weeks from start.** If it slips, cut scope, not the date.

---

## 1. Thesis and anti-goals

### 1.1 What sierx is

A self-hosted work tracker for a small team, covering the idea→delivery→outcome path in one object graph, with its entire configuration expressible as reviewable text.

### 1.2 The seven things it does differently

| # | Idea | Mechanism |
|---|---|---|
| 1 | **Config as reviewable text** | Project configuration is a YAML file with `plan`/`apply` and an optional git reconcile loop. Config is versioned; items reference a config version, so a status rename never corrupts historical reporting. |
| 2 | **Discovery and delivery are one graph** | An `idea` is an item type. `promote` mutates its type in place, preserving id and full history. No second product, no second ID space. |
| 3 | **Arbitrary-depth hierarchy in core** | `ltree` materialized path. No paywalled tier for anything above epic. |
| 4 | **Forecasts from actuals, not estimates** | Every status transition is timestamped in the event log, so cycle-time distributions are free. Monte Carlo forecast replaces story points. Points ship off by default. |
| 5 | **Dependencies are plan constraints** | Typed link graph plus rollup dates gives a computable cross-team critical path, not a label you have to go looking for. |
| 6 | **One query language everywhere** | The same `sxq` string drives search, board filters, saved views, and the API. Every query is URL-addressable, so a link is a shareable view. |
| 7 | **Portable by construction** | Permissive licensing throughout, full config and data export, no proprietary runtime, works air-gapped. |

### 1.3 Anti-goals ⚠

This list is a contract, not a disclaimer. Jira's incomprehensibility is accumulated yes-saying, one reasonable request at a time. Adding to this list is easy; removing from it requires a written reason in this document.

sierx will not have:

- A plugin or app marketplace
- Custom dashboard gadgets or a dashboard builder
- Field-level security
- More than two permission levels (`member`, `admin`) before 25 users
- A rich-text editor (comments and bodies are Markdown, rendered client-side)
- Email notifications in v1
- Time tracking / worklogs
- A Jira importer
- Per-user custom color pickers (see §10.2)
- Real-time collaborative editing
- WebSockets or a message broker
- Any second datastore (no Redis, no Elasticsearch, no Meilisearch)

---

## 2. Phases

| Phase | Deliverable | Done means |
|---|---|---|
| **0** | Schema, migrations, seed generator, CI skeleton | All of §4 applied; `up → down → up` clean; seed generator produces a 10k-item workspace; rollup property tests green; all CI gates wired and failing loudly when violated |
| **1** | REST API, auth, event log | curl can CRUD items, links, statuses; every write produces correct `change_event` rows; `If-Match` returns 409 correctly; `?since_seq` cursor verified gap-free under concurrent writes |
| **2** | List view, item detail, theming baseline | **Usable as a real backlog. Start tracking sierx's own work in sierx here.** All five themes pass the contrast gate; keyboard-only walkthrough passes |
| **3** | Kanban board | Column↔status mapping, WIP limits, optimistic updates, drag **and** keyboard/menu-based move (§10.4) |
| **4** | Sprints and Scrum board | Sprint scope with `removed_at` tracking, burndown computed from the event log, scope-change visible |
| **5** | Hierarchy and timeline | Arbitrary depth, rollups, dependency overlay, critical path |
| **6** | Discovery | Idea board, scoring, `promote` operation, outcome fields, Monte Carlo forecast (needs ~3 months of real data before it says anything true — build last, not early) |
| **7** | Config-as-code tooling | YAML schema, `sierx plan` / `sierx apply`, git reconcile loop |

### 2.1 Phasing correction worth noting ⚠

Config-as-code is split deliberately:

- **Phase 0:** `item.config_version` and the versioned config tables (§4.3). Irreversible — retrofitting this after history exists means no historical chart can be trusted.
- **Phase 7:** the YAML schema, `plan`/`apply`, and reconcile loop. Designing a configuration surface before needing to configure anything is the Jira mistake in reverse.
- **Between:** config rows are inserted by seed SQL.

---

## 3. Architecture

### 3.1 Stack

| Layer | Choice | Notes |
|---|---|---|
| Database | PostgreSQL 18 | `uuidv7()`, generated columns, improved I/O. Extensions: `ltree`, `citext`, `pg_trgm`, `pg_stat_statements` |
| Backend | Go | Single static binary. `net/http` + `chi` or stdlib routing. No web framework. |
| SQL layer | **sqlc** | Hand-written SQL → generated type-safe Go. No ORM. |
| Migrations | goose (or Atlas) | Plain SQL up/down files. No model-diffing. |
| Frontend | Vite + React 19 + shadcn/ui (Base UI primitives) + Tailwind | SPA, served by the Go binary |
| Client data | TanStack Query + TanStack Virtual + dnd-kit | |
| Proxy | Caddy | Brotli precompressed static assets, HTTP/3 |
| Edge | Cloudflare Tunnel | Optional; app must run without it |
| Runtime | Podman + Quadlet | `linux/arm64` and `linux/amd64` |

### 3.2 Process topology

One Go process. One Postgres. One Caddy. Nothing else. Every additional process is RAM you don't have on a Pi and an outage source you don't need.

```
┌──────────────┐   ┌───────────────────────────────┐   ┌──────────────┐
│   Caddy      │──▶│  sierx (Go, single binary)    │──▶│ PostgreSQL 18│
│ static+proxy │   │  · REST API                   │   │  (NVMe)      │
└──────────────┘   │  · embedded SPA assets        │   └──────────────┘
                   │  · sxq parser                 │
                   │  · config reconcile (ph. 7)   │
                   └───────────────────────────────┘
```

### 3.3 Repository layout

```
/cmd/sierx           — server entrypoint
/cmd/sierxctl        — CLI: plan, apply, export, seed, restore-test
/internal/store      — sqlc-generated code + hand-written SQL
/internal/api        — HTTP handlers, DTOs, projection
/internal/sxq        — query language: lexer, parser, SQL compiler
/internal/config     — YAML schema, plan/apply/reconcile
/internal/forecast   — Monte Carlo
/migrations          — goose SQL files
/web                 — Vite + React
/web/src/themes      — theme token definitions (§10)
/test/property       — rollup and path invariant tests
/test/golden         — API golden files
/test/bench          — performance gates
```

### 3.4 Hardware targets

| Target | Spec | Role |
|---|---|---|
| Primary | VPS, 2 vCPU / 4GB, snapshots enabled | Production |
| Secondary | Pi 5 (8GB or 16GB) + NVMe via M.2 HAT+ | Dev / staging / air-gapped |

Pi notes: NVMe is mandatory, not optional — microSD manages roughly 1,500–4,000 IOPS against ~200,000 for a budget NVMe, and WAL writes will chew through an SD card. Pi 5 PCIe is a single lane, officially Gen 2 (~450–500 MB/s); Gen 3 (~800 MB/s) works unofficially on most drives. Never build the frontend on the Pi — cross-compile and ship artifacts.

---

## 4. Data model

All DDL targets PostgreSQL 18. `uuidv7()` is built in; do not add `pgcrypto` for ID generation.

```sql
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 4.1 Tenancy and identity

```sql
CREATE TABLE workspace (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  slug       text NOT NULL UNIQUE,
  name       text NOT NULL,
  origin_id  uuid NOT NULL,                      -- §5.7
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE user_account (
  id            uuid PRIMARY KEY DEFAULT uuidv7(),
  email         citext NOT NULL UNIQUE,
  display_name  text NOT NULL,
  password_hash text,                            -- NULL under proxy auth (§11.2)
  totp_secret   bytea,
  theme         text NOT NULL DEFAULT 'system',  -- §10.2
  reduced_motion boolean,                        -- NULL = follow OS preference
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE membership (
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  user_id      uuid NOT NULL REFERENCES user_account(id),
  role         text NOT NULL CHECK (role IN ('member','admin')),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE session (
  id_hash      bytea PRIMARY KEY,                -- SHA-256 of the cookie token
  user_id      uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  last_seen_at timestamptz
);
```

### 4.2 Projects

```sql
CREATE TABLE project (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  key_prefix   text NOT NULL CHECK (key_prefix ~ '^[A-Z][A-Z0-9]{1,9}$'),
  name         text NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('delivery','discovery','portfolio')),
  next_key_num int  NOT NULL DEFAULT 1,          -- monotonic, never reset (§A.1)
  archived_at  timestamptz,
  UNIQUE (workspace_id, key_prefix)
);
```

### 4.3 Configuration ⚠

The design goal: renaming or removing a status must never alter the meaning of historical data.

Mechanism: **`status` and `item_type` rows are immutable.** A rename inserts a new row; the new config version points at it; existing items keep pointing at the old row. `project_config` is the version header, and the `config_*` tables declare which entities are live in which version.

```sql
CREATE TABLE project_config (
  project_id  uuid NOT NULL REFERENCES project(id),
  version     int  NOT NULL,
  source_yaml text,                              -- verbatim, for round-trip export
  applied_at  timestamptz NOT NULL DEFAULT now(),
  applied_by  uuid REFERENCES user_account(id),
  PRIMARY KEY (project_id, version)
);

-- IMMUTABLE after insert. Never UPDATE key, name, or category. (§5.6)
CREATE TABLE status (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,
  name       text NOT NULL,
  category   text NOT NULL CHECK (category IN ('open','active','done','cancelled'))
);

-- IMMUTABLE after insert.
CREATE TABLE item_type (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,
  name       text NOT NULL,
  level      int  NOT NULL,                      -- 0 = most granular
  is_idea    boolean NOT NULL DEFAULT false
);

CREATE TABLE config_status (
  project_id    uuid NOT NULL,
  version       int  NOT NULL,
  status_id     uuid NOT NULL REFERENCES status(id),
  display_order int  NOT NULL,
  PRIMARY KEY (project_id, version, status_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE config_type (
  project_id        uuid NOT NULL,
  version           int  NOT NULL,
  item_type_id      uuid NOT NULL REFERENCES item_type(id),
  initial_status_id uuid NOT NULL REFERENCES status(id),
  PRIMARY KEY (project_id, version, item_type_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE config_transition (
  project_id     uuid NOT NULL,
  version        int  NOT NULL,
  from_status_id uuid NOT NULL REFERENCES status(id),
  to_status_id   uuid NOT NULL REFERENCES status(id),
  requires       jsonb NOT NULL DEFAULT '[]',    -- e.g. ["assignee","points"]
  PRIMARY KEY (project_id, version, from_status_id, to_status_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE field_def (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,                      -- the jsonb key in item.fields
  name       text NOT NULL,
  data_type  text NOT NULL CHECK (data_type IN
               ('text','number','date','select','multiselect','user','url','bool')),
  options    jsonb NOT NULL DEFAULT '[]',
  UNIQUE (project_id, key)
);
```

### 4.4 Items

```sql
CREATE TABLE item (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id   uuid NOT NULL REFERENCES workspace(id),
  project_id     uuid NOT NULL REFERENCES project(id),
  key            text NOT NULL,                  -- 'SRX-142'; immutable for life (§A.1)
  item_type_id   uuid NOT NULL REFERENCES item_type(id),
  status_id      uuid NOT NULL REFERENCES status(id),
  config_version int  NOT NULL,
  parent_id      uuid REFERENCES item(id),
  path           ltree NOT NULL,                 -- ancestry incl. self (§5.3)
  title          text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
  body           text,                           -- Markdown
  assignee_id    uuid REFERENCES user_account(id),
  points         numeric(6,2),
  start_date     date,                            -- date, NOT timestamptz (§A.3)
  due_date       date,
  rank           text NOT NULL,                  -- LexoRank (§5.5)
  fields         jsonb NOT NULL DEFAULT '{}',
  version        int  NOT NULL DEFAULT 1,        -- optimistic concurrency (§5.4)
  change_seq     bigint NOT NULL,                -- §5.1
  origin_id      uuid NOT NULL,                  -- §5.7
  origin_seq     bigint,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  search_tsv     tsvector GENERATED ALWAYS AS (
                   to_tsvector('english', title || ' ' || coalesce(body, ''))
                 ) STORED,
  UNIQUE (workspace_id, key)
);

CREATE INDEX item_path_gist  ON item USING gist (path);
CREATE INDEX item_ws_seq     ON item (workspace_id, change_seq);
CREATE INDEX item_proj_stat  ON item (project_id, status_id) WHERE deleted_at IS NULL;
CREATE INDEX item_parent     ON item (parent_id);
CREATE INDEX item_assignee   ON item (assignee_id) WHERE deleted_at IS NULL;
CREATE INDEX item_fields_gin ON item USING gin (fields jsonb_path_ops);
CREATE INDEX item_search     ON item USING gin (search_tsv);
```

**Gotcha:** PostgreSQL 18 makes *virtual* the default for generated columns, and virtual generated columns cannot be indexed. `search_tsv` must be declared `STORED` as above.

**ltree labels.** Path labels are the items' own UUIDs. Since PostgreSQL 16, ltree labels permit hyphens, with a 1000-character label limit and up to 65535 labels per path, so raw UUIDs are valid labels and no secondary key space is needed. Labels are locale-dependent; in C locale the permitted set is `A-Za-z0-9_-`.

### 4.5 Rollups

```sql
CREATE TABLE item_rollup (
  item_id          uuid PRIMARY KEY REFERENCES item(id) ON DELETE CASCADE,
  descendant_count int NOT NULL DEFAULT 0,
  done_count       int NOT NULL DEFAULT 0,
  points_total     numeric(10,2),
  points_done      numeric(10,2),
  earliest_start   date,
  latest_due       date,
  computed_at      timestamptz NOT NULL DEFAULT now()
);
```

Rollups are **written, never computed on read.** This is the single most important performance decision in the system; a recursive aggregate per page load is the first thing that will fall over on ARM.

### 4.6 Links

```sql
CREATE TABLE item_link (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  from_item_id uuid NOT NULL REFERENCES item(id),
  to_item_id   uuid NOT NULL REFERENCES item(id),
  kind         text NOT NULL CHECK (kind IN
                 ('blocks','duplicates','relates','implements','discovered_from')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  created_by   uuid REFERENCES user_account(id),
  CHECK (from_item_id <> to_item_id),
  UNIQUE (from_item_id, to_item_id, kind)
);

CREATE INDEX item_link_to ON item_link (to_item_id, kind);
```

Links may cross projects and workspaces by construction. Cross-workspace visibility is a projection, not full access (§11.4).

### 4.7 Event log

```sql
CREATE TABLE change_event (
  workspace_id uuid   NOT NULL,
  seq          bigint NOT NULL,                  -- §5.1: allocated from seq_counter
  at           timestamptz NOT NULL DEFAULT now(),
  item_id      uuid,
  actor_id     uuid,
  kind         text NOT NULL,                    -- created | field_changed |
                                                 -- status_changed | moved | linked |
                                                 -- unlinked | promoted | deleted
  field        text,
  old_value    jsonb,
  new_value    jsonb,
  PRIMARY KEY (workspace_id, seq, at)
) PARTITION BY RANGE (at);

CREATE INDEX change_event_ws_seq ON change_event (workspace_id, seq);
CREATE INDEX change_event_item   ON change_event (item_id, at DESC);

CREATE TABLE seq_counter (
  workspace_id uuid PRIMARY KEY REFERENCES workspace(id),
  value        bigint NOT NULL DEFAULT 0
);
```

Monthly range partitions, created by a scheduled job one month ahead. **No retention or pruning policy** — pruning destroys the audit trail, the activity feed, the forecast inputs, and the history views. Partition, don't prune.

### 4.8 Sprints, comments, views

```sql
CREATE TABLE sprint (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  name       text NOT NULL,
  goal       text,
  starts_on  date NOT NULL,
  ends_on    date NOT NULL,
  state      text NOT NULL CHECK (state IN ('planned','active','closed')),
  CHECK (ends_on > starts_on)
);

CREATE TABLE sprint_item (
  sprint_id  uuid NOT NULL REFERENCES sprint(id),
  item_id    uuid NOT NULL REFERENCES item(id),
  added_at   timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz,
  PRIMARY KEY (sprint_id, item_id)
);

CREATE TABLE comment (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  item_id    uuid NOT NULL REFERENCES item(id),
  author_id  uuid NOT NULL REFERENCES user_account(id),
  body       text NOT NULL,                      -- Markdown
  created_at timestamptz NOT NULL DEFAULT now(),
  edited_at  timestamptz,
  deleted_at timestamptz
);

CREATE TABLE saved_view (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  owner_id     uuid REFERENCES user_account(id),
  name         text NOT NULL,
  query        text NOT NULL,                    -- an sxq string (§7)
  layout       text NOT NULL CHECK (layout IN ('list','board','timeline','grid')),
  shared       boolean NOT NULL DEFAULT false
);
```

`sprint_item.removed_at` is what makes an honest burndown possible: it distinguishes committed scope from mid-sprint additions and removals. Do not replace it with a hard delete.

---

## 5. Invariants — normative

### 5.1 ⚠ `change_seq` allocation: never use a sequence

**A `bigserial` is not safe as a sync cursor.** Sequence values are handed out before commit, and transactions commit out of order:

```
T1 takes seq=99   ───────────────────────────────┐ commits t+3
T2 takes seq=100  ──┐ commits t+1                │
T3 takes seq=101  ──┼─┐ commits t+2              │
                    ▼ ▼                          ▼
client polls since_seq=98 at t+2  → receives 100, 101. Cursor := 101.
client polls since_seq=101 at t+4 → seq 99 is never returned. Lost permanently.
```

An edit disappears from every client until something else touches that item. Because polling is the only refresh path, this is invisible until someone reports stale data nobody can reproduce.

**Required implementation:** allocate from a row-locked counter inside the same transaction as the write.

```sql
-- first statement of every mutating transaction
UPDATE seq_counter
   SET value = value + 1
 WHERE workspace_id = $1
RETURNING value;
```

This serializes writes on one row per workspace — irrelevant at ten users — and guarantees the sequence is gap-free and commit-ordered. Every mutation writes the allocated value to both `item.change_seq` and `change_event.seq`.

Test requirement: a concurrency test that runs N parallel writers, polls with a cursor throughout, and asserts every committed change was observed exactly once.

### 5.2 Rollup maintenance

State is truth; rollups are derived. Maintain them as follows:

1. A row-level `AFTER INSERT/UPDATE/DELETE` trigger on `item` inserts the changed item's ancestor ids into a transaction-local dirty set.
2. A `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` recomputes each dirty ancestor once at commit.

The naive version — recompute ancestors on every row change — is O(depth × changes) and will recompute the same ancestor dozens of times in one bulk operation.

Rollup writes target `item_rollup` only, never `item`, so no trigger recursion is possible.

Ancestors of an item are found by prefix on `path`; descendants by `path <@ $ancestor_path`.

### 5.3 Path maintenance

- `path` always includes the item's own id as the final label.
- On reparent, rewrite `path` for the item and all descendants in one statement.
- Reject any reparent that would make an item its own ancestor (`new_parent.path <@ item.path`).
- Maximum depth: 8. Enforce in the API, not only the database.

### 5.4 Optimistic concurrency

Every item carries `version`, incremented on each successful mutation.

- Mutations require `If-Match: "<version>"`.
- Mismatch returns `409 Conflict` with the current server representation in the body so the client can present a real diff.
- Missing `If-Match` on a mutation returns `428 Precondition Required`.

Without this, two people dragging the same card produces silent last-write-wins.

### 5.5 Ranking

Manual ordering uses LexoRank-style strings: insert between two neighbours by generating a string that sorts between them. Rebalance a project's ranks when any generated key exceeds 40 characters. Never use integer positions — every reorder would rewrite the whole column.

### 5.6 Config immutability

`status` and `item_type` rows are append-only. `UPDATE` on `key`, `name`, `category`, or `level` is forbidden; enforce with a `BEFORE UPDATE` trigger that raises an exception. Renames insert a new row and a new config version.

### 5.7 Federation columns

`workspace.origin_id`, `item.origin_id`, and `item.origin_seq` are populated from phase 0 even though nothing reads them. They are the difference between a future sync daemon and a rewrite. `origin_id` is the id of the instance that authored the row; `origin_seq` is that instance's `change_seq` at authorship.

### 5.8 Deletion

Soft delete via `deleted_at`. Keys and `next_key_num` are never reused or reset. Hard deletion exists only in an admin CLI path and always writes a terminal `change_event` first.

---

## 6. API

### 6.1 Conventions

| Concern | Rule |
|---|---|
| Format | JSON. `snake_case` keys. |
| Errors | RFC 9457 problem+json |
| Pagination | Cursor only. `?cursor=<opaque>&limit=<n>`, `limit` max 200, default 50. No offset pagination anywhere. |
| Field projection | `?fields=key,title,status,assignee,points,due_date`. **Required on all collection endpoints.** A board returning full item records is 250KB+ of JSON per view; board cards need six fields, not forty. |
| Delta sync | `?since_seq=<n>` returns changes after that cursor, plus the new cursor. See §5.1. |
| Caching | `ETag` + `If-None-Match` on stable resources (item detail, config, static assets). **No `ETag` on `?since_seq=` endpoints** — the cursor is the cache key; layering both muddles invalidation. |
| Concurrency | `If-Match` on all mutations (§5.4) |
| Compression | Brotli where offered, gzip fallback |

### 6.2 Endpoints (phase 1)

```
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
GET    /api/v1/me

GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{key}
GET    /api/v1/projects/{key}/config            # resolved current config version

GET    /api/v1/items?q=<sxq>&fields=&cursor=&limit=
POST   /api/v1/items
GET    /api/v1/items/{key}
PATCH  /api/v1/items/{key}                      # If-Match required
DELETE /api/v1/items/{key}                      # soft delete
POST   /api/v1/items/{key}/transition           # {to_status, fields?}
POST   /api/v1/items/{key}/move                 # {parent, rank_after?}
POST   /api/v1/items/{key}/promote               # {to_type} — phase 6

GET    /api/v1/items/{key}/children
GET    /api/v1/items/{key}/descendants?depth=
GET    /api/v1/items/{key}/rollup
GET    /api/v1/items/{key}/history               # from change_event
GET    /api/v1/items/{key}/links
POST   /api/v1/items/{key}/links
DELETE /api/v1/links/{id}

GET    /api/v1/comments?item={key}
POST   /api/v1/comments

GET    /api/v1/changes?since_seq=<n>&limit=      # delta sync
GET    /api/v1/views
POST   /api/v1/views
GET    /api/v1/healthz
GET    /api/v1/metrics                           # Prometheus text format
```

### 6.3 Live updates

Poll `/api/v1/changes` with the cursor. Interval: 10s when the tab is focused, paused when hidden, exponential backoff on failure.

Deliberately **not** SSE or WebSockets in v1. Counter-intuitive but correct for a low-bandwidth target: a persistent connection on a flaky link produces reconnect storms and duplicate-delivery handling. If live updates are added later, use SSE driven by Postgres `LISTEN/NOTIFY`, behind a feature flag.

---

## 7. `sxq` — the query language

One string drives search, board filters, saved views, and the API. Every query is URL-addressable; a link is a shareable view. There is no separate filter-builder UI to maintain.

### 7.1 Grammar

```
query      := expr
expr       := term (("and" | "or") term)*  | "not" term | "(" expr ")"
term       := field op value | "text" ":" string
field      := ident ("." ident)?            -- e.g. status, assignee, fields.impact
op         := "=" | "!=" | ">" | ">=" | "<" | "<=" | "in" | "not in"
            | "is" | "is not" | "~"          -- "~" = full-text match
value      := literal | list | function
function   := "me()" | "now()" | "startOfSprint()" | "endOfSprint()"
order      := "order by" field ("asc" | "desc")?
```

### 7.2 Examples

```
project = SRX and status.category != done and assignee = me() order by rank
type = epic and descendants(status.category = open) > 0
due_date < now() + 7d and status.category in (open, active)
text ~ "certificate rotation" and project in (SRX, PLAT)
parent = SRX-42 order by rank asc
fields.impact >= 4 and type = idea order by fields.impact desc
```

### 7.3 Implementation rules

- Compile to parameterized SQL. **Never** string-concatenate user input into SQL.
- Fields resolve against `field_def` per project; unknown fields are a parse error with a suggestion, not a silent empty result.
- The parser exposes a completion API (`/api/v1/sxq/complete?partial=`) so the same grammar drives autocomplete.
- Queries are pure and read-only. No mutations in sxq, ever.

---

## 8. Config-as-code (phase 7)

### 8.1 File format

```yaml
# projects/platform/sierx.yaml
project:
  key: PLAT
  name: Platform
  kind: delivery

types:
  - {key: initiative, name: Initiative, level: 3}
  - {key: epic,       name: Epic,       level: 2}
  - {key: story,      name: Story,      level: 1}
  - {key: bug,        name: Bug,        level: 1}

statuses:
  - {key: todo,     name: To Do,       category: open}
  - {key: doing,    name: In Progress, category: active}
  - {key: review,   name: In Review,   category: active}
  - {key: done,     name: Done,        category: done}
  - {key: dropped,  name: Dropped,     category: cancelled}

initial_status:
  story: todo
  bug: todo
  epic: todo
  initiative: todo

transitions:
  - {from: todo,   to: doing,   requires: [assignee]}
  - {from: doing,  to: review}
  - {from: review, to: done,    requires: [assignee]}
  - {from: "*",    to: dropped}

fields:
  - {key: impact,    name: Impact,    type: number}
  - {key: component, name: Component, type: select, options: [api, web, infra]}

board:
  columns:
    - {name: Backlog,  statuses: [todo],           wip_limit: null}
    - {name: Building, statuses: [doing],          wip_limit: 5}
    - {name: Review,   statuses: [review],         wip_limit: 3}
    - {name: Done,     statuses: [done, dropped]}

rollup:
  points: sum
  dates:  envelope
```

### 8.2 Operations

```bash
sierxctl plan   -f sierx.yaml     # Terraform-style diff, exit 2 if changes pending
sierxctl apply  -f sierx.yaml     # bumps project_config.version
sierxctl export --project PLAT    # regenerate YAML from live config
sierxctl reconcile --git-ref main --interval 2m
```

`plan` output must name consequences, not just field diffs:

```
~ status "In Review" renamed to "Review"
    14 items will report under the new name; history preserved (config v7 → v8)
- transition doing → done removed
    WARNING: 2 items are in "In Progress" with no path to a done status
+ field "component" added (select: api, web, infra)

Plan: 1 to add, 1 to change, 1 to destroy.
Destructive changes require --force.
```

### 8.3 Reconcile loop

Pull-based, matching the existing deployment pattern: poll a git ref, `plan`, apply only non-destructive changes automatically, and record every application in `project_config`. Destructive drift raises an alert and does nothing. No inbound webhooks, no self-hosted runner.

---

## 9. Frontend

### 9.1 Build and budget

| Gate | Threshold | Enforcement |
|---|---|---|
| First-route JS | ≤ 250KB brotli | CI fails the build |
| First-route CSS | ≤ 20KB brotli | CI fails the build |
| Any single lazy chunk | ≤ 60KB brotli | CI fails the build |
| Route count with eager imports | 1 | lint rule |

Expected composition, first route (estimates — verify with `vite-bundle-visualizer` in week one): react + react-dom ~45KB, router ~15KB, TanStack Query ~13KB, Tailwind ~12KB, ~14 shadcn components ~35KB, app code ~50KB ≈ **170KB**. Board route adds dnd-kit ≈ 30KB.

**One optional experiment, phase 2:** alias `react` → `preact/compat`, which removes roughly 40KB. Base UI and Radix internals occasionally break under Preact, so this is a two-hour timeboxed experiment with a measured result and an easy revert — not a commitment.

### 9.2 Load-path rules

1. **Content-hashed immutable assets.** `Cache-Control: public, max-age=31536000, immutable`. Repeat visits ship zero JS. This matters more than every bundle optimization combined.
2. **Bootstrap state injected into `index.html`.** The Go server embeds the first screen's data as a JSON script tag, killing the JS→API waterfall. Six serialized round trips at 650ms RTT is 3.9s before first useful pixel regardless of bundle size.
3. **Brotli precompressed at build time**, served by Caddy. Not on-the-fly.
4. **Optimistic mutations everywhere.** On a 650ms link this is the single largest perceived-speed improvement.
5. **Virtualized lists** (TanStack Virtual) for any list over 50 rows. Render 30 rows, not 5,000.
6. **Route-level code splitting.** Board code does not ship on the roadmap route.
7. **No browser storage for application state.** React state only.

### 9.3 Visual direction

The product is a dense, keyboard-first work tracker for engineers on variable connections. The design job is legibility under density, not delight.

Specific things to avoid, because they are defaults rather than choices:

- **The identical-card kit.** A Kanban tool is mostly cards; if every card, panel, and dialog shares one border-radius and one soft grey shadow, hierarchy disappears exactly where it matters most. Let card elevation encode state (selected, dragging, blocked), not decoration.
- **ALL-CAPS labels.** Sentence case throughout, including column headers and field labels.
- **Accenting one word in a heading**, tracked-out eyebrow labels above every heading, and meta strings joined with middle dots.
- **Ambient motion.** Motion answers an action — a card landing, a panel opening, a conflict appearing. Nothing fades in on scroll.

Spend the visual boldness in one place: the board. Everything around it stays quiet.

### 9.4 Copy rules

- Active voice. A button says what happens: "Move to review", not "Submit".
- An action keeps its name through the whole flow: the button that says "Promote" produces a toast that says "Promoted".
- Errors state what happened and what to do, in the interface's voice. They do not apologize and they are never vague. `409` surfaces as "Someone else changed this item. Review the differences and retry." with the diff, not "Conflict error".
- Empty states are invitations: "No items match this query. Clear the filter or create one."
- Name things as users understand them. "Linked items", not "edge set".

---

## 10. Theming and accessibility

### 10.1 Standard

**Target: WCAG 2.2 Level AA**, which is the current W3C Recommendation (published October 2023). The high-contrast themes target Level AAA contrast (7:1).

Relevance note: ADA Title III does not clearly reach a private internal tool, but Section 508 does reference WCAG for federal contexts, and Level AA is the conformance level cited by Section 508, EN 301 549, and the EAA. If sierx is ever used on a contract, AA is the floor that matters. Building to it now is far cheaper than retrofitting.

### 10.2 Theme set ⚠

Five options, four palettes. **Curated themes only — no per-user color pickers.** Arbitrary user-chosen colors make contrast guarantees unenforceable, which is the opposite of the goal; every palette here is contrast-tested in CI.

| `user_account.theme` | Behavior |
|---|---|
| `system` (default) | Follows `prefers-color-scheme`; honors `prefers-contrast: more` by upgrading to the matching HC palette |
| `light` | Light palette, AA |
| `dark` | Dark palette, AA |
| `light-hc` | High-contrast light, AAA contrast, heavier borders |
| `dark-hc` | High-contrast dark, AAA contrast, heavier borders |

Implementation: CSS custom properties on `:root[data-theme="…"]`, matching shadcn's token convention so components need no theme-awareness. Selected theme is persisted server-side on `user_account` and injected into the initial HTML to prevent a flash of the wrong theme. Zero runtime CSS-in-JS.

Token surface (kept small on purpose):

```
--background      --foreground
--card            --card-foreground
--muted           --muted-foreground
--border          --input          --ring
--primary         --primary-foreground
--destructive     --destructive-foreground
--status-open     --status-active   --status-done    --status-cancelled
```

### 10.3 Contrast requirements, enforced

| Pair | Minimum |
|---|---|
| `--foreground` on `--background` | 4.5:1 (AA), 7:1 in HC themes |
| `--muted-foreground` on `--background` | 4.5:1 — muted text is the most common real-world failure |
| `--border` on `--background` | 3:1 (non-text contrast) |
| `--ring` (focus) on adjacent colors | 3:1 |
| Status colors on their card background | 3:1 |

**CI gate:** a unit test enumerating every declared token pair and computing contrast ratios, failing the build on violation. This runs on the token definitions, so it catches a bad color the moment it is written rather than in a manual audit later.

### 10.4 Hard interaction requirements

These are the ones a work tracker gets wrong.

1. **⚠ 2.5.7 Dragging Movements (AA) — every drag needs a non-drag alternative.** A Kanban board whose only way to move a card is dragging fails AA. Required: each card exposes a keyboard path and a menu path to change status and rank. dnd-kit's `KeyboardSensor` covers the keyboard half; the card context menu ("Move to → Review", "Move up / down") covers the pointer half. **This is a phase 3 requirement, not polish.**
2. **1.4.1 Use of Color (A) — never encode meaning in color alone.** Status, priority, and blocked state each need a glyph or text label in addition to color. This is the most common accessibility failure in project tools, and it also happens to be what makes boards readable in bright sunlight and on cheap screens.
3. **2.5.8 Target Size Minimum (AA) — interactive targets ≥ 24×24 CSS px**, padding counts toward the total. Applies to card menu buttons, inline status chips, and avatar buttons. Dense views may use the spacing exception instead.
4. **2.4.11 Focus Not Obscured (AA)** — focused elements must not be hidden behind sticky headers or the board's column headers. Test with the board scrolled.
5. **Focus is always visible.** `outline: none` without a replacement is banned by lint rule. Focus ring ≥ 3:1 against adjacent colors.
6. **`prefers-reduced-motion`** disables card-drag animations, panel transitions, and any non-essential motion. Drag still works; it just doesn't animate.
7. **Text resize to 200%** without loss of content (1.4.4) and user text-spacing overrides tolerated (1.4.12). The board must remain usable; columns may scroll.
8. **Semantic structure.** The board is a labelled list-of-lists, not a grid of divs. Column headers announce name and item count. Every icon-only control has an accessible name.
9. **3.3.8 Accessible Authentication (AA)** — no puzzle-based auth. Password managers must be able to fill the login form (no split inputs, no paste blocking).

### 10.5 Accessibility gates in CI

| Gate | Tool |
|---|---|
| Automated audit on list, board, item detail, login | axe-core, zero violations |
| Contrast of all token pairs | custom unit test (§10.3) |
| Keyboard-only walkthrough: create → transition → reparent → reorder → comment | Playwright, no mouse events |
| Screen-reader labels present on all interactive elements | axe rule subset |

---

## 11. Auth and permissions

### 11.1 Scope

One workspace, under 10 users. `workspace_id` is present on every table (free now, unmigratable later) but there is no workspace-switching UI.

### 11.2 Two auth modes

| Mode | Mechanism |
|---|---|
| `local` (default) | Email + password (Argon2id), cookie session, optional TOTP. Cookies: `HttpOnly`, `Secure`, `SameSite=Lax`. Session table per §4.1, tokens stored hashed. |
| `proxy` | Trust an identity header asserted by an authenticating reverse proxy. Requires an explicit allowlist of trusted proxy source IPs; requests from anywhere else are rejected. |

`proxy` mode is about half a day of work and it means SSO can be added later — Cloudflare Access in front of the existing tunnel, or any OIDC proxy — with no further auth code, while the app remains fully functional air-gapped with `local`.

### 11.3 Permissions

Two roles. `member` can read and write all items in the workspace. `admin` adds user management, config apply, project archive, and hard delete. There is no third level, no project-level scoping, and no field-level security until there is a real person to exclude — that decision saves roughly three weeks and is the single largest source of Jira's complexity.

### 11.4 Cross-workspace projections (not v1)

Reserved design: when items are visible across workspaces, a link grants **projection** access, not full access — key, title, status category, and target date only. A team sees that it is blocked by `PLAT-88 — In Progress — due Nov 14` and nothing else. Do not implement in v1; do not implement a design that makes this impossible.

---

## 12. Performance gates

Assertions, not prose. Prose budgets decay; failing tests don't. All measured on the Pi 5 reference box with a 10k-item seeded workspace.

| Scenario | Gate |
|---|---|
| Board view, 500 items, projected fields | p95 < 150ms server time |
| Item detail with rollup and history | p95 < 100ms |
| `sxq` query over 10k items, indexed fields | p95 < 200ms |
| Descendant rollup read, depth 6 | p95 < 50ms |
| Delta sync, 50 changes | p95 < 80ms, response < 20KB |
| Full-text search over 10k items | p95 < 300ms |
| Rollup recompute after a 200-item bulk transition | < 2s total |
| Steady-state RSS, sierx process | < 80MB |
| Cold start to serving | < 1s |

---

## 13. Testing

For an agent-driven build this section matters more than the architecture section. Agents produce plausible code; the spec's real job is making wrongness detectable.

| Kind | What | Why |
|---|---|---|
| **Property** | `parent.rollup == aggregate over ltree descendants`, asserted after randomized sequences of create / move / delete / reparent / transition | Trigger bugs hide here, and they hide quietly |
| **Property** | `path` consistency: every item's path ends with its id, prefixes match ancestors, no cycles | Reparenting is the easiest thing to get subtly wrong |
| **Concurrency** | N parallel writers + a polling cursor; assert every committed change observed exactly once | §5.1 is invisible without this |
| **Golden file** | Request → committed expected JSON for every endpoint | Makes refactors safe and diffs reviewable |
| **Migration** | `up → down → up` on a seeded database | Down migrations rot silently |
| **Seed generator** | Build a 10k-item, 6-deep, 5-project workspace with realistic history | Write in phase 0. Otherwise ARM performance is discovered at month four. |
| **Restore** | Scheduled: restore the latest backup to a scratch database, assert row counts and a checksum | An untested backup is not a backup |
| **Benchmark** | §12 gates | |
| **Accessibility** | §10.5 gates | |
| **Bundle size** | §9.1 gates | |
| **License** | §15 allowlist | |

---

## 14. Operations

### 14.1 Deployment

Podman + Quadlet units for `sierx` and `postgres`. Caddy on the host or as a third unit. Pull-based deploy: CI builds and pushes multi-arch images and the frontend bundle; the host polls a deploy branch or registry tag on an interval. No self-hosted runner and no inbound webhook.

### 14.2 Backups ⚠

Of everything in this plan, a bad restore is the most likely thing to actually cause loss.

- WAL archiving to an off-box target, continuously.
- `pg_dump` weekly as a second mechanism with a different failure mode.
- **A scheduled restore test** that restores to a scratch database and asserts row counts and a content checksum. If the restore test has never run green, there is no backup.
- Retention: 30 days of WAL, 8 weekly dumps.

### 14.3 Observability — deliberately minimal

Do not install Prometheus and Grafana on a Pi. That restraint is a requirement, not an oversight, and it should not be "improved" later.

- Structured JSON logs to journald, one line per request with method, route, status, duration, actor, and workspace.
- `pg_stat_statements` enabled; `log_min_duration_statement = 200ms`.
- `/api/v1/healthz` (liveness plus database reachability) and `/api/v1/metrics` in Prometheus text format, scraped only when investigating.

### 14.4 Configuration

Environment variables only, no config file. Required: `DATABASE_URL`, `SIERX_AUTH_MODE`, `SIERX_TRUSTED_PROXIES`, `SIERX_BASE_URL`, `SIERX_SESSION_KEY`. Fail fast and loudly on a missing or malformed value at startup.

---

## 15. Licensing and supply chain

**sierx is Apache-2.0.** Chosen over MIT for the express patent grant and the contribution clause; if sierx ever takes outside contributions or gets adopted by an organization, Apache-2.0 is strictly better and MIT's only advantage is brevity.

### 15.1 Dependency allowlist

Permitted: MIT, Apache-2.0, BSD-2, BSD-3, ISC, Unlicense, CC0, PostgreSQL, Zlib.

Blocked: **GPL, LGPL, AGPL, MPL, SSPL, BSL.** Note that SSPL and BSL are not copyleft and therefore slip past a "no GPL family" rule, but both restrict exactly the commercial optionality this posture exists to preserve.

### 15.2 Enforcement

`go-licenses check` plus an npm-side license checker against the allowlist, failing the build. Roughly an hour of work, and it catches the transitive dependency no one would audit by hand. Verified permissive at time of writing: PostgreSQL (PostgreSQL license), `ltree` (ships with PostgreSQL), shadcn/ui (MIT). Everything else is the gate's job, not a human's.

### 15.3 Clean-room discipline ⚠

Plane is AGPL-3.0 and OpenProject is GPLv3. Reading their documentation and data models is fine — schema design is not copyrightable and their docs are a genuinely useful reference for workflow-engine and board-virtualization edge cases. **Do not read their source and then write adjacent code.** This is the real cost of the licensing posture and the one that depends on discipline rather than tooling.

### 15.4 Supply chain

Vendored Go modules, `go mod verify` in CI, SBOM generated per release, pinned base images by digest, and a reproducible build target so the binary can be verified independently.

---

## 16. Open decisions

| # | Question | Blocks |
|---|---|---|
| 1 | Production host: VPS or Pi? Recommendation is VPS for production with the Pi as staging — snapshot-restore is worth the monthly cost for a tool holding the team's work. | Phase 0 ops setup |
| 2 | Is disconnected/field use a real requirement or hypothetical? If real, it is a phase 8 offline client with a local store, not a v1 constraint. | Nothing in v1; changes phase 8 |
| 3 | `sxq` name and syntax details — is JQL-familiar syntax worth keeping for muscle memory, or is a cleaner break better? | Phase 1 parser |
| 4 | Attachments — out of v1 entirely, or link-only (paste a URL)? | Phase 2 |
| 5 | Does `points` ship at all, given §1.2 item 4? Recommendation: the column exists, the UI is off by default. | Phase 4 |
| 6 | Time-travel scope. Recommendation: three specific queries (item state on date X, epic target-date history, roadmap snapshot diff) rather than general `AS OF`, which needs a temporal variant of every read path and costs roughly a month. | Phase 5 |

---

## Appendix A — Decisions that are expensive to reverse

**A.1 Item keys.** `SRX-142` format. Keys are **never reused** after deletion and `next_key_num` is never reset. Keys **never change when an item moves between projects** — Jira rewrites them, which breaks every external link ever created. Project membership is a separate mutable field; the key is permanent.

**A.2 IDs.** `uuidv7()` internally: time-ordered so index locality is good, globally unique so clients can generate offline and federation needs no coordination, and non-sequential so row counts don't leak. Human-facing keys are separate (A.1).

**A.3 Dates vs timestamps.** Events, audit, and session data are `timestamptz`. Due dates, start dates, and sprint boundaries are `date`. A sprint boundary stored as a timestamp is a permanent source of off-by-one bugs across timezones, and it is unpleasant to migrate once real sprints exist.

**A.4 Event log semantics.** State tables are the source of truth. `change_event` is a derived append-only log written in the same transaction by trigger. **This is not event sourcing** — no projections, no replay, no versioned event schemas. Given an ambiguous spec an agent will build event sourcing, and the config system and event schema will then be coupled permanently.

**A.5 Rollups are written, never computed on read.** §5.2.

**A.6 Config entities are immutable.** §5.6.

**A.7 The anti-goals list is a contract.** §1.3.

---

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **item** | Any trackable thing: idea, initiative, epic, story, bug, spike. One table, type is data. |
| **promote** | Changing an item's type in place, preserving id and history. Used for idea → initiative. |
| **rollup** | Materialized aggregate over an item's ltree descendants. |
| **change_seq** | Per-workspace monotonic, gap-free, commit-ordered counter. The sync cursor. §5.1. |
| **config version** | Immutable snapshot of a project's types, statuses, transitions, and fields. Items reference the version in force at their last transition. |
| **sxq** | sierx query language. §7. |
| **projection** | Reduced view of an item exposed across a workspace boundary. §11.4. |
| **origin** | The instance that authored a row. Reserved for federation. §5.7. |
