# sierx — Build Guide

**Companion to:** `docs/SPEC.md` (sierx Technical Specification v0.1)
**Version:** 1.6
**Date:** 2026-09-12
**Supersedes:** v1.2, v1.1 (2026-09-12), v1.0 (2026-09-11)
**Sign-off state:** ADR-002, ADR-005, ADR-012, ADR-014 approved 2026-09-12.
ADR-010 still blocked on one input — see §4.0.
**Audience:** a coding agent executing the build, and the human reviewing it.

**Takeover amendment (2026-09-18):** ADR-020 supersedes the calendar deadline and
Pi-only staging requirement below. Initial staging is the Spark; smaller-host
performance acceptance remains a separate, explicitly selected hardware check.
The original deadline and deadline-triggered cuts are historical. Task 0.12
requires `make ci-local-prepare` while online followed by `make ci-local`
offline, with the real container result recorded. Read the current handover
and latest progress correction before interpreting older completion claims.

---

## Changelog

Read this once, then never again. It exists so the human can review what changed
without diffing 2,000 lines.

### v1.5 → v1.6

**Correction.** v1.3 through v1.5 treated §14.2's off-box backup requirement as
binding at task 0.1. It binds at deployment. Task 0.11's restore test runs
against the *dev* database — a throwaway workspace that `make db-reset` destroys
on purpose — so what is under test there is the harness, not the durability of
anything. A local repository satisfies it completely.

ADR-010 now separates the two targets: dev gets `posix` to a local path, set at
task 0.1; staging and prod get `sftp` or `s3`, set at task 2.16 where the deploy
actually happens. `bootstrap-check` still fails when the type is unset, and now
also fails on `posix` when `SIERX_ENV` is not `dev` — which is the guard that
keeps the dev convenience from quietly becoming the production arrangement.

Net effect: phase 0 needs no infrastructure decision at all. `.env.example` has a
copy-pasteable dev block, and the only human action is generating two secrets
locally.

### v1.4 → v1.5

Repository confirmed: `github.com/siercks/sierx`, **public**, `main`, one commit
containing only an Apache-2.0 `LICENSE`. Three consequences.

1. §1.1's arm64 runner question is settled — free, unlimited, 4 vCPU. No longer
   an open item.
2. **§3.7 is new: public-repository discipline.** `PROGRESS.md` will accumulate
   pasted command output from every task, and `.env.example` documents every
   variable, in a world-readable repo. Real hostnames, bucket names, and internal
   addresses must never be committed — not only secrets. `gate-notopology`
   enforces it from the first commit, because that is when `PROGRESS.md` starts
   collecting output.
3. Task 0.1 now clones rather than `git init`s, preserves the existing `LICENSE`,
   and adds `NOTICE`.

ADR-019 adds an update path for §15.4's digest pins, which nothing previously
updated. A pinned base image with no update mechanism is an unpatched base image
with extra steps.

**ADR-010 is no longer waiting on anything from anyone but the operator's own
shell** — see §4.0. The recommended type is `sftp`; the host goes in the
untracked `.env` and is never committed or shared.

### v1.3 → v1.4

ADR-018 specifies the SPA route design. Neither document covered it — SPEC §7
says only that sxq queries are URL-addressable — so the agent would have invented
it at task 2.7. Adds `gate-routes`, a reserved-key-prefix check to task 1.9, and
the route table to task 2.1.

### v1.2 → v1.3

The backup design is future-proofed: ADR-010's tool choice is now one
implementation behind a driver interface (ADR-017), with two drivers shipping
from the first commit because §14.2 already requires both mechanisms. Task 0.11
is rewritten accordingly.

**The useful side effect: task 0.11 is no longer fully blocked.** The interface,
the `pgdump` driver, and the conformance suite need no repository target and can
be green before one arrives. Only the `pgbackrest` driver's stanza and its
conformance run wait. `bootstrap-check` still fails without a target, and
deliberately so — see §4.0.

Four pgBackRest mechanics are now pinned rather than left to be discovered:
repository encryption at `stanza-create` (not reversible in place), always
passing `--repo` explicitly, multi-repository support from the outset, and
`stanza-upgrade` on a PostgreSQL major bump.

### v1.1 → v1.2

The four ⚠ ADRs were approved on 2026-09-12. Recorded in three places, because
the agent checks all three: §4.0's table, the `PROGRESS.md` template in §3.1
(pre-checked boxes — this is the one §0.3 actually reads), and the per-task
sign-off notes at tasks 0.8, 1.13, and 2.9. Task 0.1 step 4 now seeds
`docs/DECISIONS.md` with every ADR at status `accepted` except ADR-010.

**ADR-010 remains blocked.** `bootstrap-check` fails at task 0.1 until
`PGBACKREST_REPO_TYPE` and `PGBACKREST_REPO_PATH` are filled in. Nothing else
stands between this document and the first commit.

### v1.0 → v1.1

**Blocking fixes**

| # | Was | Now |
|---|---|---|
| 1 | §0.1 read order started at `PROGRESS.md`, which task 0.1 creates | §0.1 has a cold-start rule |
| 2 | ADR-002 / ADR-005 sign-offs were unchecked at task 0.1, so the build hard-stopped at task 0.8 | §4.0 records the sign-off state the human must set **before** the first session; the agent still stops if it is unset |
| 3 | Gate 0 could not close without the pgBackRest repo target, discovered at task 0.11 | Task 0.1 step 7 now fails `bootstrap-check` on an unfilled `PGBACKREST_REPO_*`, so the blocker surfaces in the first five minutes |

**Corrected gates** (each would have made `gate-0` unpassable or meaningless)

| # | Gate | Fix |
|---|---|---|
| 4 | `gate-nodirect` | Explicit path allowlist and word-boundary matching. Task 0.5's invariant tests *must* attempt forbidden writes, and `UPDATE item` matched `item_type`/`item_link`/`item_rollup` as a substring |
| 5 | `UNIQUE (project_id, rank)` | Now `DEFERRABLE INITIALLY IMMEDIATE`, deferred inside rebalance. A non-deferrable unique index is checked per row, so a mass renumber fails even when the end state is unique. ADR-003 amended |
| 6 | `gate-bench` | Split into `bench-smoke` (CI, non-blocking) and `gate-bench` (reference hardware, human-run). ADR-016 |
| 7 | `schema-diff` | Was tautological if the agent regenerated the snapshot. Now compares a from-scratch migration against a separately committed snapshot |
| 8 | `prove-gates` | Scope defined: covers gates that exist; adding a gate requires adding its proof in the same task |

**New decisions** (§4) — resolve genuine gaps found by reading SPEC.md against this guide

| ADR | Subject | Sign-off |
|---|---|---|
| ADR-011 | Wildcard transitions (`from: "*"` in §8.1 cannot be stored in §4.3's schema) | none |
| ADR-012 | Cross-project moves are rejected in v1; project-scoped config integrity enforced by composite FK | ⚠ required |
| ADR-013 | Every item gets an `item_rollup` row, including leaves | none |
| ADR-014 | Markdown rendering and the XSS boundary — neither document addressed it | ⚠ required |
| ADR-015 | `PATCH /me` — §10.2 persists theme server-side but §6.2 has no write path | none |
| ADR-016 | Benchmark gate split | none |

**New tasks.** Phase 1 went from 19 to 25 tasks. Eight endpoints in SPEC §6.2 —
`/projects` (×3), `/projects/{key}/config`, `/items/{key}/children`,
`/descendants`, `/rollup`, `/history`, `/views` (×2) — had no owning task in
v1.0, while gate 1 required a curl walkthrough of "the §6.2 surface end to end."
Phase 2 went from 16 to 18: a Markdown rendering task (ADR-014) and a
create-flow / empty-states task. Tasks are renumbered in both phases; nothing
has executed yet, so renumbering is free.

**Verified while revising** (the version claims in §1 held up; these are additions)

- Go 1.27 backs `encoding/json` with the v2 engine. Behaviour is preserved but
  escaping bytes and error text changed. This build's API contract *is*
  byte-exact golden JSON, so §1 now pins the toolchain for golden generation and
  task 1.2 forbids pinning stdlib error strings. **high (verified)**
- Go 1.27 ships a stdlib `uuid` with `NewV7`. If confirmed, it removes a
  dependency from the license gate — noted in task 0.8. **moderate** (single
  secondary source; the agent verifies before relying on it)

---

## 0. Agent protocol — read this first, every session

### 0.1 Read order at session start

0. **Cold start.** If `PROGRESS.md` does not exist, this is session one: skip to
   §5 task 0.1, which creates it. Do not ask.
1. `PROGRESS.md` — find the current phase and the next unchecked task. This is
   the only source of truth for where the build is.
2. This file, sections 0–4 — protocol, environment, and the decision record.
3. This file, the section for the current phase only. **Do not read ahead into
   later phases.**
4. `docs/DECISIONS.md` — any ADRs added since this guide was written.

`docs/SPEC.md` is the normative design document. Read the sections a task cites.
Do not edit it (§3.5).

### 0.2 The loop

```
1. Read PROGRESS.md → next unchecked task in the current phase.
2. Implement exactly that task. Nothing outside its "Files" list without saying why.
3. Run the task's Acceptance command.
4. If red: fix and re-run. Do not proceed with a red acceptance.
5. If green: check the box in PROGRESS.md, paste the acceptance output under it.
6. Commit. One commit per task, message format in §3.3.
7. Repeat. When all tasks in the phase are checked, run `make gate-N`.
8. Gate green → write the phase-exit block in PROGRESS.md → stop and request sign-off.
```

### 0.3 Hard stops — the agent stops and asks

| Situation | Why |
|---|---|
| An ADR in §4 marked ⚠ **REQUIRES SIGN-OFF** has no recorded approval in `PROGRESS.md` | It deviates from a normative spec section |
| A task marked ⚠ **BLOCKED** has unresolved inputs | Guessing produces work that must be redone |
| This guide and `docs/SPEC.md` disagree and no ADR covers it | SPEC §0 rule 4: ask, don't infer |
| A phase gate is green and the phase-exit block is written | The human decides when to advance |
| A human gate (dogfooding, design review) is the next item | Not machine-checkable |
| An acceptance command needs a credential, bucket, host, or domain that is not in `.env.example` | See §3.6 |
| Implementing the task as written would violate a §5 invariant | §5 overrides convenience |

### 0.4 Prohibitions

- **No forward scaffolding.** No stubs, no "we'll need this in phase 4" files, no
  commented-out future code. SPEC §0 rule 1.
- **No inventing semantics.** If an operator, field, status, or response shape is
  not specified, stop and ask. A plausible guess is worse than a question because
  it survives review.
- **No marking a task done without pasted acceptance output.** A green claim
  without evidence is treated as red.
- **No editing `docs/SPEC.md`.** Resolutions go in `docs/DECISIONS.md`. §3.5.
- **No adding dependencies** not named in this guide without running
  `make gate-license` and recording the addition in `PROGRESS.md`.
- **No new datastore, broker, or background service.** SPEC §1.3 anti-goals are a
  contract.
- **No deleting code without showing the diff first.** No commented-out blocks as
  a substitute for deletion.

### 0.5 Precedence

```
docs/SPEC.md §5 (Invariants)
  > docs/SPEC.md Appendix A
    > docs/SPEC.md (rest)
      > this guide's §4 ADRs
        > this guide's task text
          > convenience
```

Where an ADR in §4 knowingly departs from a higher tier, it says so and carries
⚠ **REQUIRES SIGN-OFF**.

---

## 1. Locked environment decisions

| Concern | Decision | Notes |
|---|---|---|
| Agent role | Writes code; does not operate production | Human deploys and dogfoods |
| Dev host | RHEL-family Linux, Podman (rootless) | No Docker, no docker-compose |
| Database | PostgreSQL 18, self-hosted container, dev and prod | Full control of extensions and `pg_stat_statements` |
| Go | **1.27.x** — pin `go 1.27.1` in `go.mod` | Go 1.27.0 released 2026-08-19; 1.27.1 on 2026-09-01. Supported lines are 1.27 and 1.26. **high (verified)** |
| Node | **24.x (Active LTS)** — pin in `.nvmrc` and `package.json` `engines` | Node 22 entered Maintenance 2025-10-21; Node 24 Active LTS since 2025-10-28, Maintenance 2026-10-20, EOL 2028-04-30. Node 26 becomes LTS in October 2026 — schedule a bump task then, don't chase it now. **high (verified)** |
| JSON | Golden files are generated and verified under the pinned toolchain only | Go 1.27 backs `encoding/json` with the v2 engine: behaviour preserved, but escaping bytes and error text differ from 1.26. `GOEXPERIMENT=nojsonv2` is a comparison escape hatch, not a shipping configuration. **high (verified)** |
| Frontend | Vite + React 19 + Tailwind + shadcn/ui on Base UI | SPEC §3.1. shadcn/ui defaults new projects to Base UI as of July 2026; Radix remains supported. Base UI uses `render` rather than `asChild` and pulls `@floating-ui/react` — both matter to §9.1's budget. **high (verified)** |
| Markdown | `markdown-it`, `html: false`, lazy-loaded | ADR-014 |
| Git | Branch `phase/N-slug`, squash-merge to `main` at gate, tag `phase-N-complete` | §3.3 |
| CI | GitHub Actions, **zero logic in YAML** — every job calls a `make` target | §3.4 |
| Repository | `github.com/siercks/sierx` — **public**, Apache-2.0, module path `github.com/siercks/sierx` | Confirmed 2026-09-12: `main`, one commit, `LICENSE` only. Public means free 4 vCPU arm64 runners (§1.1) and world-readable `PROGRESS.md` (§3.7) |
| Registry | `ghcr.io/siercks/sierx`, multi-arch | Native runners, no QEMU |
| Prod | VPS 2 vCPU / 4 GB, snapshots on | SPEC §3.4 |
| Staging | Pi 5 + NVMe | Never build the frontend on the Pi |
| Backups | pgBackRest to an S3-compatible repo | MIT licensed **high (verified)**. See ADR-010 |
| Phase 2 clock | Four weeks from the first phase-0 commit | SPEC §0 rule 5. Record the date in `PROGRESS.md` at task 0.1. See §1.2 |

### 1.1 Why the CI shape matters

Two facts drive it. First, GitHub's standard hosted runners are free and
unlimited on public repositories, and the arm64 Linux label is
`ubuntu-24.04-arm` at 4 vCPU / 16 GB — so `linux/arm64` images build
**natively**, not under QEMU emulation, which otherwise makes container builds
for the Pi painfully slow. Arm64 standard runners also became available in
private repositories in January 2026 at 2 vCPU, counting against the plan's
included minutes. The repository is public, so the 4 vCPU tier applies; making it
private later costs build speed, not the design. **high (verified)**

Second, SPEC §14.1 deploy is pull-based: the host polls, CI never holds deploy
credentials. CI's entire job is *build, test, publish, tag*. That is what makes
the CI system swappable — see `docs/ci-portability.md`, task 0.12.

### 1.2 ⚠ The four-week clock, honestly

SPEC §0 rule 5 sets a calendar deadline for phase 2 and says to cut scope rather
than the date. v1.0 of this guide named two cut candidates worth about two hours
between them, which is not a cut list. Phase 1 is now 25 tasks and phase 2 is 18.

**Ranked cut list, decided now rather than under pressure.** Cut from the top.
Every cut is recorded in `PROGRESS.md` with the date and the reason; a cut task
is deferred, never silently dropped.

| Order | Cut | Cost of cutting |
|---|---|---|
| 1 | Task 2.17 Preact experiment | None. It is an experiment |
| 2 | Task 1.5 TOTP | Single-factor local auth on a private host. Reinstate before any non-local exposure |
| 3 | Task 1.4 Proxy auth mode | Forecloses SSO until it lands. Half a day whenever it returns (SPEC §11.2) |
| 4 | Task 1.18 Saved views | The sxq string in the URL is already a shareable view (SPEC §7). Saved views are convenience |
| 5 | Task 1.25 Metrics endpoint | `/healthz` still reports database state. Observability is already minimal by design (§14.3) |
| 6 | The two high-contrast palettes (`light-hc`, `dark-hc`) | Drops AAA coverage; AA palettes remain gated. **Do not cut the contrast gate itself** |
| 7 | Task 1.17 History endpoint | Item detail loses its history panel. The event rows are still written, so nothing is lost permanently |

**Never cut:** the contrast gate, `gate-axe`, `gate-keyboard`, `gate-nodirect`,
the property tests, task 0.11's restore test, or task 2.18's cutover. Those are
the gates that make agent-written code reviewable; cutting them converts a
schedule problem into a correctness problem.

---

## 2. Repository layout

SPEC §3.3, plus the paths this guide adds:

```
/cmd/sierx                — server entrypoint
/cmd/sierxctl             — CLI: bootstrap, plan, apply, export, seed, restore-test, rollup
/internal/store           — sqlc-generated code + hand-written SQL + Mutate() unit of work
/internal/api             — HTTP handlers, DTOs, projection registry
/internal/sxq             — query language: lexer, parser, SQL compiler
/internal/config          — YAML schema, plan/apply/reconcile        (phase 7)
/internal/forecast        — Monte Carlo                              (phase 6)
/migrations               — goose SQL files
/web                      — Vite + React
/web/src/themes           — theme token definitions
/test/property            — rollup and path invariant tests
/test/golden              — API golden files, sxq golden corpus
/test/bench               — performance gates
/test/concurrency         — §5.1 cursor test

--- added by this guide ---
/docs/SPEC.md             — the specification, verbatim, read-only
/docs/BUILD.md            — this file
/docs/DECISIONS.md        — ADR log; where spec ambiguities get resolved
/docs/ci-portability.md   — Forgejo / GitLab / local equivalents of the CI jobs
/docs/schema.sql          — committed schema snapshot (task 0.4)
/PROGRESS.md              — phase and task state; the agent's only progress claim
/Makefile                 — every gate and every CI step
/scripts/                 — everything the Makefile shells out to
/deploy/quadlet/          — Podman Quadlet units (sierx, postgres, caddy)
/deploy/caddy/            — Caddyfile
/deploy/pgbackrest/       — stanza config example
/.env.example             — every env var, documented, no secrets
```

---

## 3. Progress protocol

### 3.1 `PROGRESS.md` format

Created in task 0.1. The agent appends and checks boxes; it never rewrites
history.

````markdown
# sierx build progress

**Current phase:** 0
**Phase 2 deadline anchor:** <date of first phase-0 commit>
**Phase 2 deadline:** <anchor + 28 days>

## Sign-offs (human writes these — see §4.0)
- [x] ADR-002 approved — 2026-09-12
- [x] ADR-005 approved — 2026-09-12
- [x] ADR-012 approved — 2026-09-12
- [x] ADR-014 approved — 2026-09-12
- [ ] ADR-010 repository target supplied

## Cuts taken (§1.2)
- <none | task, date, reason>

## Phase 0 — Schema, migrations, seed, CI skeleton

- [x] 0.1 Repository skeleton and toolchain pins
      ```
      $ make bootstrap-check
      go1.27.1 OK / node v24.x OK / podman OK / psql 18 OK
      ```
- [ ] 0.2 Dev database
...

### Phase 0 exit
- gate-0: <paste `make gate-0` tail>
- Deviations from the guide: <none | list>
- Open questions raised: <none | list, with ADR numbers>
- Requesting sign-off to enter phase 1.
````

### 3.2 Gates

Every phase has exactly one command. It exits 0 or nonzero; there is no partial
credit and no prose substitute.

```bash
make gate-0    # …through gate-7
make gate      # the current phase's gate, read from PROGRESS.md
```

Two classes, because SPEC §0 rule 2 is not machine-checkable:

| Class | Closed by | Examples |
|---|---|---|
| **Automated** | The agent, by running the gate | Migrations, property tests, contrast, bundle size, axe |
| **Human** | The human, by writing in `PROGRESS.md` | A week of daily use after phase 2; design review of the board; `gate-bench` on reference hardware; ⚠ ADR sign-offs |

A phase is closed when its automated gate is green **and** its human gates are
signed. The agent stops at that boundary.

### 3.3 Commits, branches, tags

```bash
git switch -c phase/0-foundation           # one branch per phase
git commit -m "phase0(0.4): item, rollup, link, event tables"
# at gate:
#   squash-merge to main, then:
git tag phase-0-complete && git push --tags
```

Commit subject: `phase<N>(<task>): <imperative summary>`. One task per commit. A
commit that touches files outside the task's **Files** list must say why in the
body.

### 3.4 Make targets are the interface

Nothing may live only in CI YAML. If CI does it, `make` does it, and a human can
run it locally and offline. `.github/workflows/*.yml` is limited to: checkout,
toolchain setup, `make <target>`, artifact upload.

### 3.5 Spec and ADR discipline

`docs/SPEC.md` is committed verbatim in task 0.1 and is **read-only to the
agent**. SPEC §0 rule 4 says to record resolutions back into the document; this
guide redirects that to `docs/DECISIONS.md` so that the normative document is
never rewritten by the thing being measured against it, and so every resolution
keeps its reasoning and date.

ADR format:

```markdown
## ADR-0NN — <title>
**Date:** <date>  **Status:** proposed | accepted | superseded by ADR-0MM
**Spec refs:** §5.1, A.4
**Deviation:** none | ⚠ departs from normative §5.2 — requires sign-off
**Context:** <what was ambiguous or conflicting>
**Decision:** <what we do>
**Consequence:** <what this costs, what it forecloses>
**Enforcement:** <the test or gate that keeps it true>
```

ADR-001 through ADR-016 (§4) are seeded into `docs/DECISIONS.md` at task 0.1.

### 3.6 Missing inputs

Any value the agent cannot invent — a bucket name, a hostname, a domain, a
credential — goes in `.env.example` with a `# REQUIRED: supplied by human`
comment, and the dependent task is marked ⚠ **BLOCKED** in `PROGRESS.md`. The
agent does not stub a fake value and it does not skip the task silently.

Never commit a real secret. `SIERX_SESSION_KEY` and the pgBackRest repo
credentials live in a `0600` env file on the host, outside git.

### 3.7 Public-repository discipline

The repository is public. Two committed files collect operational detail as a
side effect of how this build works: `PROGRESS.md` accumulates pasted acceptance
output from every task, and `.env.example` documents every variable. Both are
world-readable.

So the rule is broader than "no secrets," which §3.6 already covers. **No real
hostnames, bucket names, internal addresses, SSH targets, or private IPs in any
tracked file** — including `PROGRESS.md`, `docs/`, `deploy/`, and
`.env.example`. Topology is reconnaissance even when it is not a credential.

| File | Carries | Does not carry |
|---|---|---|
| `.env.example` | Variable names, types, allowed values, `# REQUIRED: supplied by human` | Any real value |
| `.env` (untracked, in `.gitignore`) | Real values for dev | — |
| Host env file (`0600`, outside git) | Real values for staging and prod, all secrets | — |
| `PROGRESS.md` | Acceptance output, scrubbed | Hostnames, paths outside the repo, IPs |

Scrubbing pasted output is a step in the loop (§0.2 step 5), not an afterthought:
replace a hostname with `<staging-host>` and keep everything else verbatim. An
output that cannot be scrubbed without becoming meaningless is a sign the
acceptance command should not have printed it.

**Enforcement.** `make gate-notopology` greps tracked files for RFC 1918 address
literals, `.internal` / `.local` / `.lan` / `.home` hostnames, and any value
present in `.env` — so a real value copied into a tracked file fails the build
even if nobody recognizes it as sensitive. Wired in task 0.1, because the first
commit is when `PROGRESS.md` starts collecting output.

This is a constraint worth having rather than a tax. A public build log of a
spec-driven project is the artifact; it just has to be one that does not also
publish the infrastructure.

---

## 4. Decision record — resolutions of spec ambiguities

These are seeded into `docs/DECISIONS.md` at task 0.1.

### 4.0 Sign-off state

Four ADRs carry ⚠ **REQUIRES SIGN-OFF** and one is ⚠ **BLOCKED** on an input.
Per §0.3 the agent stops when it reaches an unsigned one, so the state is decided
before the build starts rather than discovered at task 0.8.

| ADR | Subject | Reached at | State |
|---|---|---|---|
| ADR-002 | One sequence value per event row | Task 0.8 | ✅ **approved 2026-09-12** |
| ADR-005 | Rollups maintained in the store layer, not by triggers | Task 0.8 | ✅ **approved 2026-09-12** |
| ADR-012 | Cross-project moves rejected in v1 | Task 0.4 | ✅ **approved 2026-09-12** |
| ADR-014 | Markdown rendering and the XSS boundary | Task 2.9 | ✅ **approved 2026-09-12** |
| ADR-010 | Backup repository target | Tasks 0.1 and 2.16 | ✅ dev target defined (`posix`, no decision). Real off-box target is task 2.16's, enforced there |
| ADR-017 | Backup driver interface | Task 0.11 | ✅ accepted (no sign-off needed) |
| ADR-018 | SPA route design | Task 2.1 | ✅ accepted (no sign-off needed) |
| ADR-019 | Digest pin update path | Task 0.1 | ✅ accepted (no sign-off needed) |

The four approvals are pre-written into the `## Sign-offs` block of the
`PROGRESS.md` template (§3.1), which is what §0.3 reads. The agent does not stop
at tasks 0.4, 0.8, 1.13, or 2.9 on their account.

ADR-010 is different: it needs a value, not a decision.
`scripts/bootstrap-check.sh` **fails** while `PGBACKREST_REPO_TYPE` or
`PGBACKREST_REPO_PATH` is unfilled, so the build cannot start without it.

**That hard fail survived the v1.3 future-proofing on purpose.** ADR-017 makes
the target cheap to *change* and lets most of task 0.11 proceed without one, but
it cannot make a missing target harmless: §14.2 requires continuous off-box WAL
archiving, and the `pgdump` driver alone loses up to a week. A dump-only
configuration is not a temporary state that anyone revisits. One value, filled in
once, is what stops "we'll sort backups later" from becoming the permanent
arrangement.

**v1.6 corrects where that requirement binds.** It binds at task 2.16, not task
0.1: phase 0's restore test runs against a dev database that `make db-reset`
destroys by design, so a local `posix` repository tests the harness completely.
What survived is the part that does the work — `bootstrap-check` rejects `posix`
whenever `SIERX_ENV` is not `dev`, so the dev fixture cannot be deployed, and
task 2.16 cannot pass without a real off-box target. The requirement is now
enforced by a check rather than by a hard fail five weeks upstream of the
decision.

**If an approval is later withdrawn,** uncheck the box in `PROGRESS.md` and say
so; the ADR's own "if sign-off is withheld" paragraph is the fallback, and for
ADR-005 that means implementing SPEC §5.2 as written.

### ADR-001 — The application writes `change_event`, not a trigger

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

### ADR-002 — ⚠ One sequence value per `change_event` row, allocated in exact-size blocks

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

### ADR-003 — `rank` is scoped per project, uniquely and deferrably

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

### ADR-004 — `sxq` keeps the clean grammar; hierarchy predicates land in phase 5

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

### ADR-005 — ⚠ Rollups are maintained in the store layer, not by triggers

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

### ADR-006 — `item.config_version` advances on create, transition, and promote only

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

### ADR-007 — One projection registry, generating the client's types

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

### ADR-008 — Attachments are link-only

**Spec refs:** §16 #4, §4.3. **Deviation:** none.

The `url` `field_def` data type already exists. A project that wants attachments
declares a `url` field. No blob storage, no upload endpoint, no virus-scanning
question, no backup-size surprise, zero new schema. If real file attachments are
ever wanted, they are a phase-8 conversation with an object-store dependency, not
a v1 feature.

### ADR-009 — Theme bands: 60 / 30 / 10 over token families, with status color confined

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

### ADR-010 — ⚠ Backups: pgBackRest to at least one encrypted off-box repository

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

### ADR-017 — The backup harness talks to a driver interface, with two drivers from day one

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

### ADR-011 — Wildcard transitions are enumerated, not stored as a wildcard

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

### ADR-012 — ⚠ Cross-project moves are rejected in v1; config integrity is enforced by the schema

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

### ADR-013 — Every item has an `item_rollup` row, including leaves

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

### ADR-014 — ⚠ Markdown is rendered with raw HTML disabled at the parser

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

### ADR-015 — `PATCH /me` for the preferences §10.2 already persists

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

### ADR-016 — The benchmark gate runs advisory in CI and blocking on reference hardware

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

### ADR-019 — Digest pins need an update path, or they are just old images

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

### ADR-018 — Path is which code ships; query is what it shows

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

## 5. Phase 0 — Schema, migrations, seed generator, CI skeleton

**Spec "done means":** all of §4 applied; `up → down → up` clean; the seed
generator produces a 10k-item workspace; rollup property tests green; all CI
gates wired and failing loudly when violated.

**Branch:** `phase/0-foundation`
**Tasks:** 0.1 – 0.14, in order.

Note on scope: the mutation layer (task 0.8) is in phase 0 rather than phase 1
because §13's rollup property test asserts invariants "after randomized sequences
of create / move / delete / reparent / transition," which cannot be written
without it. The HTTP layer is not.

### Task 0.1 — Repository skeleton and toolchain pins

**Goal.** A repository that a second person can clone and verify their toolchain
against in one command.

**Files.** `go.mod`, `.nvmrc`, `package.json`, `Makefile`, `.gitignore`,
`.editorconfig`, `NOTICE`, `README.md`, `PROGRESS.md`, `docs/SPEC.md`,
`docs/BUILD.md`, `docs/DECISIONS.md`, `.env.example`,
`.github/dependabot.yml`, `scripts/bootstrap-check.sh`,
`scripts/gate-notopology.sh`

**Steps.**
0. **Clone, do not `git init`.** `github.com/siercks/sierx` already exists on
   `main` with one commit containing an Apache-2.0 `LICENSE`. Do not overwrite or
   re-create `LICENSE`. Add `NOTICE` with the copyright line — per-file license
   headers are **not** used; LICENSE plus NOTICE is sufficient for a
   single-author Apache-2.0 project and headers across several hundred files are
   noise the license gate does not need.
1. `go mod init github.com/siercks/sierx`; set `go 1.27.1`. The module path
   matches the repository's `go-import` metadata, so it must be exactly this.
2. `.nvmrc` → `24`; `package.json` `engines.node` → `>=24 <25`.
3. Copy the specification to `docs/SPEC.md` verbatim and this guide to
   `docs/BUILD.md`.
4. Seed `docs/DECISIONS.md` with ADR-001 … ADR-016 from §4, verbatim, all at
   status `accepted` except ADR-010 (`blocked`). ADR-002, ADR-005, ADR-012 and
   ADR-014 were approved 2026-09-12 (§4.0); each records that date.
5. Create `PROGRESS.md` from the §3.1 template, including the `## Sign-offs` and
   `## Cuts taken` blocks. **Record the current date as the phase-2 deadline
   anchor** and compute the deadline (anchor + 28 days).
6. `scripts/bootstrap-check.sh`: assert `go version` matches `go.mod`, `node -v`
   matches `.nvmrc`, `podman` present, `psql` client ≥ 18 or
   absent-but-containerized. Print one line per check. Then print any unchecked
   box from `PROGRESS.md`'s `## Sign-offs` block as an informational line. Exit
   nonzero on any toolchain failure, **or** on an unset `PGBACKREST_REPO_TYPE` /
   `PGBACKREST_REPO_PATH`, **or** on `PGBACKREST_REPO_TYPE=posix` when
   `SIERX_ENV` is anything other than `dev` (ADR-010). The last check is the one
   that matters: a local repository is a valid dev fixture and a production
   data-loss event, and the guide will not rely on anyone remembering which they
   configured.
7. `.env.example`: every variable in Appendix B, each with a comment, and
   `# REQUIRED: supplied by human` on the ones the agent cannot invent. **Types
   and allowed values only — never a real value** (§3.7). `.gitignore` must
   cover `.env`.
8. `scripts/gate-notopology.sh` (§3.7) plus its `prove-gates` proof: grep tracked
   files for RFC 1918 literals, `.internal`/`.local`/`.lan`/`.home` hostnames,
   and any value present in `.env`. This is the first commit precisely because
   `PROGRESS.md` starts collecting pasted output now.
9. `.github/dependabot.yml` (ADR-019): `gomod`, `npm`, `github-actions`,
   `docker`, weekly, one grouped pull request per ecosystem. Toolchain and
   PostgreSQL major pins are excluded from automation.
10. `README.md`: what sierx is, the license, and `make help`. Three paragraphs,
    not a feature list. It is the public face of a public repository — write it
    for someone who found the repo, not for the agent.

**Acceptance.**
```bash
make bootstrap-check && make gate-notopology && \
  test -f LICENSE && test -f NOTICE && test -f docs/SPEC.md && \
  git log --oneline | head -3
```

**Do not.** Do not create `/internal`, `/web`, or `/cmd` trees yet — empty
directories are forward scaffolding. Do not replace `LICENSE`. Do not put a real
hostname, bucket, or address in any tracked file (§3.7).

### Task 0.2 — Dev database

**Goal.** `make db-up` gives a Postgres 18 with the three extensions,
reproducibly, rootless.

**Files.** `deploy/quadlet/sierx-postgres.container`, `scripts/db.sh`, `Makefile`

**Steps.**
1. Quadlet unit for `postgres:18` pinned **by digest**, not tag (§15.4). Named
   volume for `PGDATA`. `pg_stat_statements` in `shared_preload_libraries`;
   `log_min_duration_statement=200ms` (§14.3).
2. Initialize the cluster with `--locale=C --encoding=UTF8`. §4.4 notes ltree's
   permitted label set is locale-dependent and that `A-Za-z0-9_-` holds in C
   locale; UUID labels depend on that, so it is pinned rather than inherited from
   the container's default.
3. `make db-up`, `db-down`, `db-psql`, `db-reset` (⚠ `db-reset` destroys data: it
   must refuse unless `SIERX_ENV=dev` and print what it will drop before doing
   it).
4. Same unit file serves dev and staging; differences come from env only.

**Acceptance.**
```bash
make db-up && make db-psql -- -c "select version()" && \
make db-psql -- -c "show lc_collate" && \
make db-psql -- -c "select extname from pg_extension order by 1"
# expects postgres 18.x, C collation, and after task 0.3: citext, ltree, pg_trgm, plpgsql
```

### Task 0.3 — Migration tooling and extensions

**Files.** `migrations/0001_extensions.sql`, `Makefile`, `scripts/migrate.sh`

**Steps.** Wire goose against `/migrations` with plain SQL up/down, no model
diffing (§3.1). `0001` creates `ltree`, `citext`, `pg_trgm`; its down drops them.
Add `make migrate-up`, `migrate-down`, `migrate-status`, and `migrate-updown-up`
(up → down to zero → up again, asserting clean at each step).

**Acceptance.** `make migrate-updown-up`

### Task 0.4 — Schema: all of SPEC §4

**Files.** `migrations/0002_identity.sql`, `0003_project.sql`, `0004_config.sql`,
`0005_item.sql`, `0006_rollup_links_events.sql`,
`0007_sprints_comments_views.sql`, `docs/schema.sql`

**Steps.** Transcribe §4.1 – §4.8 exactly. Every table, every check constraint,
every index. Specific points that are easy to get wrong:

- `item.search_tsv` **must** be `STORED`. Postgres 18 makes generated columns
  virtual by default and virtual columns cannot be indexed (§4.4).
  **high (verified)**
- Do not add `pgcrypto`. `uuidv7()` is built in (§4).
- `item.path` labels are the items' own UUIDs. Hyphens in ltree labels are legal
  since PG 16 with a 1000-character label limit, so no secondary key space
  (§4.4). **high (verified)**
- `change_event` is `PARTITION BY RANGE (at)` with PK `(workspace_id, seq, at)`.
  Create the current month and the next two in this migration.
- `start_date`, `due_date`, `sprint.starts_on`, `sprint.ends_on` are `date`, not
  `timestamptz` (A.3).
- Populate `workspace.origin_id`, `item.origin_id`, `item.origin_seq` from the
  start even though nothing reads them (§5.7).

**Additions beyond §4, each from an ADR — no others.**

| Addition | ADR |
|---|---|
| `UNIQUE (project_id, rank) DEFERRABLE INITIALLY IMMEDIATE` on `item`, as a named constraint | ADR-003 |
| `UNIQUE (project_id, id)` on `status` and on `item_type` | ADR-012 |
| `FOREIGN KEY (project_id, status_id)` → `status(project_id, id)` on `item` | ADR-012 |
| `FOREIGN KEY (project_id, item_type_id)` → `item_type(project_id, id)` on `item` | ADR-012 |
| `FOREIGN KEY (project_id, config_version)` → `project_config(project_id, version)` on `item` | ADR-012 |
| Index on `session (expires_at)` for expiry sweeps | none — mechanical |

**Acceptance.**
```bash
make migrate-updown-up && make schema-snapshot && make schema-diff
```

`schema-snapshot` dumps the live schema to `docs/schema.sql` and is run
deliberately by a human or by this task. `schema-diff` migrates a **scratch
database from zero**, dumps it, and diffs against the committed
`docs/schema.sql` — so it catches a retroactively edited migration and a
hand-patched live database, which a self-regenerating snapshot cannot.

**Do not.** No tables not in §4. No "we'll need an attachments table" (ADR-008).
No additions beyond the table above.

### Task 0.5 — Invariant enforcement in the database

**Files.** `migrations/0008_invariants.sql`, `test/sql/invariants_test.sql`

**Steps.**
1. `BEFORE UPDATE` triggers on `status` and `item_type` raising an exception on
   any change to `key`, `name`, `category`, `level` (§5.6, A.6).
2. A trigger rejecting a reparent where `new_parent.path <@ item.path`
   (self-ancestry, §5.3).
3. Depth ceiling of 8 enforced in the database *as well as* the API (§5.3 says
   enforce in the API, not only the database — so both).
4. `item.path` must end with the item's own id — trigger-enforced.
5. `item.path`'s penultimate label must equal `item.parent_id`, and a NULL
   `parent_id` must mean a single-label path. §5.3 constrains the path's
   *contents* but nothing ties it to `parent_id`, so the two can drift into
   disagreement with every read silently picking whichever one it happened to
   use.

**Acceptance.** `make test-sql` — each forbidden operation is attempted and
asserted to raise. The file must cover, at minimum: a `status.name` update, a
self-ancestry reparent, a depth-9 insert, a path not ending in its own id, a
`parent_id`/`path` disagreement, and one violation of each ADR-012 composite FK
(an item pointing at another project's status, another project's type, and a
nonexistent config version).

**Note.** This file writes directly to `item` on purpose, which is exactly what
`gate-nodirect` forbids. `test/sql/` is on that gate's allowlist (task 0.8) for
this reason and no other.

### Task 0.6 — Sequence counter and partition maintenance

**Files.** `migrations/0009_seq.sql`, `cmd/sierxctl/partitions.go`,
`deploy/quadlet/sierx-maintenance.timer`

**Steps.**
1. `seq_counter` with a row per workspace, created alongside the workspace.
2. `sierxctl partitions ensure --months-ahead 1`: idempotent, creates missing
   monthly partitions for `change_event`. Runs from a systemd timer, not pg_cron
   — pg_cron would be a second moving part inside the database, and §1.3/§3.2
   forbid extra processes.
3. **No pruning, ever** (§4.7). The command has no `--drop` flag to misuse.

**Acceptance.**
```bash
make test-partitions   # runs ensure twice, asserts idempotence and that next month exists
```

### Task 0.7 — sqlc wiring

**Files.** `sqlc.yaml`, `internal/store/query/*.sql`, `internal/store/gen/*`
(generated)

**Steps.** sqlc against the migrated schema, `pgx/v5`, generated code checked in.
`make sqlc-gen` and `make sqlc-diff` (fails if the checked-in generated code
differs from fresh output). Start with only the queries tasks 0.8–0.9 need; do
not pre-generate the phase-1 API's queries.

**Acceptance.** `make sqlc-diff && go build ./...`

### Task 0.8 — `store.Mutate`: the unit of work

**Goal.** The single write path. This task implements ADR-001, ADR-002, ADR-005,
ADR-006, and ADR-013 together, because they are one mechanism.

**ADR-002 and ADR-005 were approved 2026-09-12** (§4.0). Proceed. If either box
in `PROGRESS.md` is unchecked, the approval was withdrawn — stop and ask.

**Files.** `internal/store/mutate.go`, `internal/store/events.go`,
`internal/store/rollup.go`, `internal/store/rank.go`,
`internal/store/mutate_test.go`, `scripts/gate-nodirect.sh`

**Steps.**
1. A `Mutation` accumulator: callers register row changes and the `change_event`
   rows that describe them. There is no API for a row change without at least one
   event — make it a compile error, not a convention.
2. `Mutate(ctx, workspaceID, func(*Mutation) error)` opens a transaction and on
   flush, in order:
   a. bump `seq_counter` by `len(events)`, one statement, `RETURNING value`
      (ADR-002);
   b. assign `seq` to each event and set each touched `item.change_seq` to its
      highest assigned value;
   c. apply row changes, including `path` rewrites for reparents (one statement
      for the item and all descendants, §5.3);
   d. set `config_version` on create / transition / promote only (ADR-006);
   e. insert an `item_rollup` row for every created item (ADR-013);
   f. compute the dirty ancestor set from touched paths and recompute those
      `item_rollup` rows once each (ADR-005);
   g. insert events;
   h. bump `item.version` for optimistic concurrency (§5.4).
3. LexoRank generator and rebalance (§5.5, ADR-003): generate between neighbours;
   rebalance a project's ranks when any generated key exceeds 40 characters;
   `SET CONSTRAINTS item_project_rank_uniq DEFERRED` inside the rebalance
   transaction only. Never integer positions.
4. Hard delete exists only here, only reachable from a CLI path, and always
   writes a terminal event first (§5.8).
5. `scripts/gate-nodirect.sh`: fail on a write to a governed table outside
   `/internal/store`. Two details that make the difference between a working gate
   and a red build:
   - **Word boundaries.** Match `\bitem\b`, not `item` — otherwise `item_type`,
     `item_link`, and `item_rollup` all trip it. Governed tables: `item`,
     `item_link`, `sprint_item`, `comment`.
   - **Path allowlist**, as a literal list in the script with a comment naming
     why each entry is there: `migrations/` (DDL and the invariant triggers),
     `test/sql/` (task 0.5 attempts forbidden writes by design),
     `internal/store/`, `docs/`, and this script itself.
6. For UUID generation in Go, prefer the standard library if Go 1.27's `uuid`
   package is present (**moderate** — verify with
   `go doc uuid 2>/dev/null`); otherwise `github.com/google/uuid` through
   `gate-license`. Database-side ids come from `uuidv7()` either way.

**Acceptance.**
```bash
go test ./internal/store/... -run 'TestMutate' -count=1 && make gate-nodirect
```

**Do not.** Do not expose a `WithoutEvents` escape hatch. Do not let `Mutate`
take an event count parameter (ADR-002). Do not widen `gate-nodirect`'s allowlist
to make a later task pass — if a task needs to write `item` from elsewhere, that
task is wrong.

### Task 0.9 — Seed generator

**Goal.** A 10k-item, 6-deep, 5-project workspace with realistic history — in
phase 0, because otherwise ARM performance is discovered in month four (§13).

**Files.** `cmd/sierxctl/seed.go`, `internal/store/seed/*`,
`internal/store/seed/config.sql`

**Steps.**
1. Config rows inserted as seed SQL (§2.1) — no YAML tooling until phase 7. The
   config mirrors §8.1's example so phase 7 has a known-good round-trip target,
   with `{from: "*", to: dropped}` written out as one row per live status
   (ADR-011).
2. Items across 5 projects, depth up to 6, realistic status distributions,
   assignees, points, dates, links including cross-project ones. Hierarchy stays
   **within** a project (ADR-012); cross-project relationships are links.
3. **Backdated history**: status transitions spread over ~9 months so cycle-time
   distributions and burndowns have something true to say later. Events must go
   through `Mutate` so sequences and rollups are correct by construction.
4. Deterministic: `--seed <int>` reproduces the same workspace exactly.

**Acceptance.**
```bash
make db-reset && make seed && make db-psql -- -c \
  "select (select count(*) from item) items, \
          (select max(nlevel(path)) from item) depth, \
          (select count(*) from item_rollup) rollups"
# ≥10000 items, max depth 6, rollups == items (ADR-013);
# run twice with the same --seed and diff a checksum
```

### Task 0.10 — Property tests

**Files.** `test/property/rollup_test.go`, `test/property/path_test.go`,
`test/property/rank_test.go`

**Steps.** Randomized sequences of create / move / delete / reparent / transition
against a seeded database, asserting after each sequence:
- `parent.item_rollup == aggregate over ltree descendants` for every non-leaf,
  and all-zero for every leaf (§13, A.5, ADR-013);
- `count(item_rollup) == count(item)` (ADR-013);
- every `path` ends with its own id, every prefix matches an ancestor, the
  penultimate label equals `parent_id`, no cycles (§13, task 0.5);
- per-project `rank` is a strict total order, and a 5,000-item rebalance commits
  (ADR-003).

Use one property-testing library and name it in `go.mod`; run it through
`make gate-license` before adopting.

**Acceptance.** `make test-property`

### Task 0.11 — Backup and restore harness (⚠ partially blocked)

**Implements ADR-017; ADR-010 supplies the pgBackRest driver's configuration.**

**Blocked on:** `PGBACKREST_REPO_*` — but only steps 5 and 7. Steps 1–4 and 6
need no repository target and must be green before the target arrives. Task 0.1's
`bootstrap-check` already fails while the target is empty, so reaching this task
without it should be impossible; if it happens anyway, do steps 1–4 and 6, paste
their output, and leave the task unchecked with the reason in `PROGRESS.md`.

**Files.** `scripts/backup/driver.sh` (dispatch + contract assertions),
`scripts/backup/driver-pgdump.sh`, `scripts/backup/driver-pgbackrest.sh`,
`scripts/backup/render-conf.sh`, `scripts/backup/conformance.sh`,
`scripts/gate-nobackupleak.sh`, `deploy/pgbackrest/pgbackrest.conf.tmpl`,
`deploy/pgbackrest/README.md`, `cmd/sierxctl/restoretest.go`,
`deploy/quadlet/sierx-restoretest.timer`, `Makefile`

**Steps.**
1. `scripts/backup/driver.sh`: dispatch on `SIERX_BACKUP_DRIVERS`, and assert the
   six-verb contract from ADR-017 — a driver missing a verb, or one whose verb
   exits 0 without doing anything, fails here rather than at 3am.
2. `driver-pgdump.sh`: `pg_dump -Fc` to the dump target, `restore-to` via
   `pg_restore` into a scratch database, retention 8 weekly dumps (§14.2).
   Requires no repository target — this is the driver that proves the interface
   before the bucket exists.
3. `scripts/backup/conformance.sh`: the shared assertion set from ADR-017, run
   per driver. Row counts per table, a content checksum, and
   `sierxctl rollup --verify` on the restored copy (ADR-005 control 2).
4. `scripts/gate-nobackupleak.sh`: the leak gate from ADR-017's enforcement, plus
   its `prove-gates` proof (task 0.12's scope rule).
5. ⚠ `driver-pgbackrest.sh` + `render-conf.sh`: generate `pgbackrest.conf` from
   env into the template — never hand-edited (§14.4). Every invocation passes
   `--repo` explicitly. Encryption per ADR-010: `repoN-cipher-type=aes-256-cbc`
   with the passphrase read from the host env file, and **verify against the
   installed pgBackRest that the cipher cannot be changed on an existing stanza
   before committing the config** — if it can, say so in `PROGRESS.md` and
   ADR-010's table is wrong. Continuous WAL archiving; retention 30 days.
6. `make restore-test` + the Quadlet timer: calls `driver.sh restore-to` only,
   and **rotates** across configured repositories and drivers so a secondary that
   has never been restored from cannot stay untested (ADR-010). Paste each
   driver's `describe` output into `PROGRESS.md`.
7. ⚠ `deploy/pgbackrest/README.md`: the PostgreSQL major-upgrade runbook —
   update `pg1-path`, run `stanza-upgrade` **before starting the new cluster**,
   then run `make restore-test` immediately (ADR-010). Also: how to add `repo2`,
   and how to swap in a WAL-G driver (write the driver, run
   `make backup-conformance`, change `SIERX_BACKUP_DRIVERS`).

**Acceptance.**
```bash
# no repository target needed:
SIERX_BACKUP_DRIVERS=pgdump make backup-conformance && make gate-nobackupleak
# with the target supplied:
make backup-conformance && make restore-test
```

**Do not.** Do not let `restore-test` or any Makefile target name a tool — that
is what `gate-nobackupleak` is for. Do not add a `--force`, `--skip-verify`, or
`--dry-run` to `restore-test`: a restore test with an escape hatch becomes a
restore test that never fully runs.

### Task 0.12 — CI skeleton, proven to fail

**Goal.** Every gate wired, and **demonstrated to fail when violated** — an
unproven gate is not a gate.

**Files.** `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
`docs/ci-portability.md`, `Makefile`, `scripts/prove-gates.sh`

**Steps.**
1. `ci.yml`: checkout → setup-go (`go-version-file: go.mod`) → setup-node
   (`node-version-file: .nvmrc`) → `make gate-0`. Nothing else. No inline shell
   beyond a single `make` invocation per job (§3.4).
2. `release.yml`: two native build jobs, `ubuntu-latest` and `ubuntu-24.04-arm`,
   then a manifest merge to `ghcr.io/siercks/sierx`. No QEMU (§1.1). SBOM per
   release, base images pinned by digest, `-trimpath` and `CGO_ENABLED=0` for a
   reproducible target (§15.4).
3. `make ci-local`: the full gate set in a container, runnable offline.
4. `scripts/prove-gates.sh`: for each gate, introduce a deliberate violation in a
   scratch copy, assert the gate goes red, revert.
   **Scope rule:** it proves the gates that exist *now*, discovered from the
   Makefile rather than from a hardcoded list, and it fails if a `gate-*` target
   exists with no corresponding proof. That makes "add a gate, add its proof" a
   build failure rather than a convention, and it is why phase 2's gates do not
   need to be anticipated here.
5. `docs/ci-portability.md`: the Forgejo Actions and GitLab CI equivalents, each
   a thin wrapper over the same make targets.

**Acceptance.**
```bash
make ci-local && bash scripts/prove-gates.sh
```

### Task 0.13 — License gate, SBOM, supply chain

**Files.** `scripts/licenses.sh`, `.licenses-allowlist`, `Makefile`

**Steps.** `go-licenses check` plus an npm-side checker against the §15.1
allowlist (MIT, Apache-2.0, BSD-2, BSD-3, ISC, Unlicense, CC0, PostgreSQL, Zlib).
Blocked: GPL, LGPL, AGPL, MPL, SSPL, BSL — note that SSPL and BSL are not
copyleft and slip past a "no GPL family" rule, so they must be named explicitly.
Dual-licensed packages are resolved to their permitted arm **only if** the
allowlist file records which arm was taken and why. Vendor Go modules;
`go mod verify` in CI.

**Acceptance.** `make gate-license`, plus one negative test: add a known AGPL
module in a scratch branch and assert the gate goes red.

### Task 0.14 — Benchmark harness

**Files.** `test/bench/*_test.go`, `test/bench/thresholds.go`, `Makefile`

**Steps.** The §12 table as executable assertions with thresholds in one
constants file. Two targets per ADR-016: `bench-smoke` (runs everything, asserts
no errors, prints timings, never fails on a threshold — this is what CI runs) and
`gate-bench` (asserts the §12 thresholds against a committed baseline, run on
reference hardware). `make bench-baseline` captures the baseline. Scenarios whose
endpoints do not exist yet are skipped **explicitly by name**, never silently.

**Acceptance.** `make bench-smoke` runs, lists skipped scenarios by name, and
exits 0. `make gate-bench` exits nonzero with "no baseline" until task 2.16.

### Gate 0

```bash
make gate-0
```

Runs: `bootstrap-check`, `migrate-updown-up`, `schema-diff`, `test-sql`,
`test-partitions`, `sqlc-diff`, `go vet`, `go test ./...`, `test-property`,
`seed` + determinism check, `gate-nodirect`, `gate-notopology`,
`gate-nobackupleak`,
`backup-conformance` (every configured driver), `gate-license`, `bench-smoke`,
build for `linux/amd64` and `linux/arm64`, `prove-gates`.

**Human gates for phase 0:**
- [x] ADR-002 signed off — 2026-09-12
- [x] ADR-005 signed off — 2026-09-12
- [x] ADR-012 signed off — 2026-09-12
- [ ] ADR-010 repository target supplied and task 0.11 green — **outstanding**

`gate-bench` is not a phase-0 human gate: there is no reference-hardware
deployment until task 2.16 (ADR-016).

---

## 6. Phase 1 — REST API, auth, event log

**Spec "done means":** curl can CRUD items, links, statuses; every write
produces correct `change_event` rows; `If-Match` returns 409 correctly;
`?since_seq` cursor verified gap-free under concurrent writes.

**Entry condition:** gate 0 green, all phase-0 human gates signed.
**Branch:** `phase/1-api`
**Tasks:** 1.1 – 1.25, in order.

Every endpoint in SPEC §6.2 except `POST /items/{key}/promote` (phase 6) has an
owning task in this phase. Gate 1 requires a curl walkthrough of that surface, so
an endpoint without a task is a gate that cannot pass.

### Task 1.1 — Server skeleton

**Files.** `cmd/sierx/main.go`, `internal/api/server.go`,
`internal/api/middleware.go`, `internal/config/env.go`

**Steps.** `net/http` + `chi`, no framework (§3.1). Environment variables only,
no config file; **fail fast and loudly** at startup on any missing or malformed
value (§14.4): `DATABASE_URL`, `SIERX_AUTH_MODE`, `SIERX_TRUSTED_PROXIES`,
`SIERX_BASE_URL`, `SIERX_SESSION_KEY`. Structured JSON logs to journald, one line
per request with method, route, status, duration, actor, workspace (§14.3).
`GET /api/v1/healthz` = liveness plus database reachability. Graceful shutdown.
Cold start to serving under 1s (§12).

**Acceptance.** `make test-api -run TestServerBoot` — asserts a missing env var
aborts startup with a message naming the variable, and that healthz reports
database state honestly when the database is down.

### Task 1.2 — Error model

**Files.** `internal/api/problem.go`

**Steps.** RFC 9457 problem+json for every error path (§6.1). One constructor per
error class. Error copy follows §9.4: state what happened and what to do, in the
interface's voice, never apologize, never vague. `409` in particular carries the
current server representation in the body (§5.4).

**Golden files pin fields, not stdlib strings.** Go 1.27 backs `encoding/json`
with the v2 engine and its error text differs from 1.26 (§1). A golden file that
embeds a marshalling error message is a golden file that breaks on a toolchain
bump for no reason. Every `detail` string in a problem body is written by this
package, never passed through from the standard library or from pgx.

**Acceptance.** Golden files for every error class, including the `409` body
shape, and one test asserting no golden file contains a string produced outside
`internal/api`.

### Task 1.3 — Local auth

**Files.** `internal/api/auth/*`, `migrations/0010_*` if needed

**Steps.** Argon2id password hashing, cookie session with the token stored as a
SHA-256 hash in `session` (§4.1), `HttpOnly`, `Secure`, `SameSite=Lax`.
`POST /auth/login`, `POST /auth/logout`, `GET /me`. §10.4.9: no puzzle auth, no
split inputs, no paste blocking — password managers must be able to fill the
form.

**Acceptance.** `make test-api -run TestAuthLocal` — login, session reuse,
expiry, logout invalidation, and a test asserting the stored token is not the
cookie value.

### Task 1.4 — Proxy auth mode

**Cut candidate #3** (§1.2).

**Files.** `internal/api/auth/proxy.go`

**Steps.** Trust an identity header only when the request's source IP is in
`SIERX_TRUSTED_PROXIES`; reject everything else (§11.2). `password_hash` stays
NULL for proxy-mode users. The app must remain fully functional air-gapped in
`local` mode.

**Acceptance.** Tests asserting a spoofed identity header from an untrusted
source is rejected, and that mode selection is explicit rather than inferred.

### Task 1.5 — TOTP (optional second factor)

**Cut candidate #2** (§1.2).

**Files.** `internal/api/auth/totp.go`

**Steps.** `totp_secret` on `user_account` (§4.1). Enrollment, verification, and
recovery.

**Acceptance.** `make test-api -run TestTOTP`

### Task 1.6 — `sierxctl bootstrap`

**Goal.** The spec never says how workspace #1, admin #1, and config v1 come into
existence. This is it.

**Files.** `cmd/sierxctl/bootstrap.go`

**Steps.** Idempotent, env-driven: creates the workspace (with `origin_id`), the
`seq_counter` row, the first admin membership, and project config version 1 from
the seed config. Re-running is a no-op that reports what already exists. Refuses
to create a second workspace (§11.1: one workspace, no switching UI).

**Acceptance.** Run twice against an empty database; second run exits 0 and
changes nothing. Then `POST /auth/login` succeeds as the bootstrapped admin.

### Task 1.7 — Projection registry

**Files.** `internal/api/projection/registry.go`, `web/src/api/fields.ts`
(generated)

**Steps.** ADR-007 in full, including the table of which endpoints require
`?fields=` and which reject it. Unknown field → `400` naming the field and the
nearest valid alternative. `make gen-fields` and `make gate-gen`.

**Acceptance.** `make gate-gen` and golden files pinning every entry's JSON
shape, plus one test per endpoint class asserting `?fields=` is required,
optional, or rejected as ADR-007 specifies.

### Task 1.8 — Cursor pagination

**Files.** `internal/api/cursor.go`

**Steps.** Opaque cursor, `limit` default 50 max 200, **no offset pagination
anywhere** (§6.1). The cursor encodes the sort key and a stable tiebreak so a
page boundary cannot duplicate or skip under concurrent writes.

**Acceptance.** A test that inserts rows mid-pagination and asserts no duplicate
and no skipped row.

### Task 1.9 — Projects

**Goal.** Items cannot be created without a project, and nothing before this task
can read one over HTTP.

**Files.** `internal/api/projects.go`

**Steps.** `GET /projects`, `POST /projects`, `GET /projects/{key}` where `{key}`
is `key_prefix` (§4.2). `POST` is admin-only (§11.3) and must: validate
`key_prefix` against §4.2's pattern, set `kind` from
`delivery|discovery|portfolio`, initialize `next_key_num` at 1, and create
project config version 1 — a project with no config version cannot hold an item
(ADR-012's composite FK makes that literal). Archived projects (`archived_at`)
are excluded from `GET /projects` unless `?archived=true`.

**Reserved prefixes (ADR-018).** §4.2's pattern admits `API`, `LOGIN`, `BOARD`,
`VIEWS`, `SETTINGS`, `ROADMAP`, `PROJECTS`, `ASSETS` — each of which collides with
a root SPA segment. `POST /projects` rejects them with `400` naming the reserved
set.

The list is **declared here, in `internal/api/reserved.go`**, not generated from
the frontend: there is no `/web` tree in phase 1 and creating one would be
forward scaffolding (§0.4). Phase 2 checks the other direction — task 2.1's
`gate-routes` fails on a root route whose uppercase form is absent from this
list — so the two cannot drift without a red build, and the dependency runs
backwards in time rather than forwards.

**Acceptance.** Golden files for each verb; a test asserting a non-admin `POST`
gets `403`; a test asserting a bad `key_prefix` gets `400` naming the pattern;
a table-driven test asserting every entry in `reserved.go` is rejected.

### Task 1.10 — Resolved config endpoint

**Goal.** One request returns everything a client needs to render a transition
menu, a type picker, and a field form. Without it the frontend makes five.

**Files.** `internal/api/config.go`

**Steps.** `GET /projects/{key}/config` returns the **current** config version
resolved: version number, statuses in `config_status.display_order` with key,
name and category, types with their initial status, transitions as
`from_key → [to_key]` with `requires`, and `field_def` entries with data type and
options. Keys throughout, never uuids (ADR-007's convention). `ETag` on this
response (§6.1) — it changes only when a config version is applied.

**Acceptance.** Golden file over the seeded config, including the expanded
wildcard transitions from ADR-011. A test asserting `304` on a matching
`If-None-Match`.

### Task 1.11 — Items CRUD with optimistic concurrency

**Files.** `internal/api/items.go`

**Steps.** `GET/POST /items`, `GET/PATCH/DELETE /items/{key}`. `If-Match`
required on all mutations; mismatch → `409` with the current representation;
**missing** `If-Match` → `428` (§5.4). The one exemption is `PATCH /me`
(ADR-015). Soft delete via `deleted_at`; keys and `next_key_num` never reused or
reset (§5.8, A.1). `POST` allocates the key from the project's `next_key_num` in
the same `Mutate` as the insert, so a rolled-back create does not burn a key.

**Acceptance.** Golden files for each verb, plus tests for `409` and `428`
specifically, and one asserting a failed create leaves `next_key_num` unchanged.

### Task 1.12 — Transitions

**Files.** `internal/api/transition.go`

**Steps.** `POST /items/{key}/transition` validating against `config_transition`
for the item's project at the **current** config version, honouring `requires`
(e.g. `["assignee"]`). Advances `config_version` (ADR-006). Emits a
`status_changed` event.

**Acceptance.** Golden files including a rejected transition and a `requires`
violation, each with a problem+json body that names the missing field. One test
asserting a wildcard-derived transition (`* → dropped`, ADR-011) is accepted from
every status in the seeded config.

### Task 1.13 — Move and reparent

**Files.** `internal/api/move.go`

**ADR-012 was approved 2026-09-12** (§4.0). Proceed.

**Steps.** `POST /items/{key}/move` with `{parent, rank_after?}`. Path rewrite
for the item and all descendants in one statement; reject self-ancestry; depth
ceiling 8 enforced here as well as in the database (§5.3). Rank per ADR-003.
**Reject a parent in a different project with `422`** and a body naming both
projects (ADR-012) — the composite FK would reject it anyway, but as a
constraint-violation `500` rather than an explained `422`.

**Acceptance.** Tests for a legal move, a self-ancestry attempt, a depth-9
attempt, a cross-project attempt (`422`, golden body), and a rank insertion
between neighbours; property test from task 0.10 re-run through the API.

### Task 1.14 — Links

**Files.** `internal/api/links.go`

**Steps.** `GET/POST /items/{key}/links`, `DELETE /links/{id}`. The five kinds
from §4.6. Links may cross projects and workspaces by construction — this is the
mechanism cross-project dependency lives on, given ADR-012. **Do not implement
cross-workspace projection (§11.4)** — but do not implement anything that
forecloses it either: the response builder must be able to emit a reduced shape
later.

**Acceptance.** Golden files, plus a test asserting a cross-project link succeeds
and a self-link is rejected.

### Task 1.15 — Comments

**Files.** `internal/api/comments.go`

**Steps.** `GET /comments?item={key}`, `POST /comments`. Markdown stored raw,
rendered client-side (§1.3 — no rich-text editor; rendering is ADR-014, phase 2).
Soft delete and `edited_at`.

**Acceptance.** Golden files.

### Task 1.16 — Hierarchy reads

**Files.** `internal/api/hierarchy.go`

**Steps.** `GET /items/{key}/children`, `GET /items/{key}/descendants?depth=`,
`GET /items/{key}/rollup`. Descendants resolve by `path <@ $ancestor_path`
(§5.2), bounded by `depth` (default: unbounded, max 8 per §5.3). `?fields=`
required on the first two, rejected on `/rollup` (ADR-007). `/rollup` reads
`item_rollup` and **never** aggregates on read (A.5) — and because every item has
a row (ADR-013), a leaf returns zeros rather than `404`.

**Acceptance.** Golden files for each; a test asserting `/rollup` executes no
recursive query (assert against `pg_stat_statements`, or assert the generated
SQL has no `WITH RECURSIVE`); a depth-bounded descendants call over the seeded
6-deep tree.

### Task 1.17 — Item history

**Cut candidate #7** (§1.2).

**Files.** `internal/api/history.go`

**Steps.** `GET /items/{key}/history` from `change_event`, newest first, cursor
paginated on `seq` (§6.1 — no offset). Uses the `change_event_item` index. Emits
`kind`, `at`, `actor`, `field`, `old_value`, `new_value`. `?fields=` is rejected
here (ADR-007).

**Acceptance.** Golden file over a seeded item with backdated transitions,
asserting the ordering and that a transition, a field change, and a move are each
distinguishable.

### Task 1.18 — Saved views

**Cut candidate #4** (§1.2).

**Files.** `internal/api/views.go`

**Steps.** `GET /views`, `POST /views` per §4.8. `query` is validated by parsing
it through `sxq` (task 1.21) before insert — a saved view that does not parse is
a stored error. `shared=false` views are visible only to `owner_id`.

**Acceptance.** Golden files; a test asserting an unparseable query is rejected
with the parser's own suggestion in the problem body.

### Task 1.19 — `PATCH /me`

**Files.** `internal/api/me.go`

⚠ **Implements ADR-015.**

**Steps.** `PATCH /api/v1/me` accepting `theme`, `reduced_motion`,
`display_name`. Reject `email`, `password`, `totp_secret`, `is_active` with `400`.
No `If-Match` (ADR-015's recorded exemption).

**Acceptance.** Golden files for a valid patch, an illegal theme value, and an
attempt to patch `email`. A test asserting `PATCH /me` succeeds without
`If-Match` while `PATCH /items/{key}` without it returns `428`.

### Task 1.20 — Delta sync

**Files.** `internal/api/changes.go`

**Steps.** `GET /changes?since_seq=&limit=` returning changes after the cursor
plus the new cursor (§6.1). **No `ETag` on this endpoint** — the cursor is the
cache key and layering both muddles invalidation (§6.1). `?fields=` is rejected
(ADR-007). Response for 50 changes must stay under 20KB (§12).

**Acceptance.** Golden files plus the size assertion.

### Task 1.21 — `sxq` phase-1 subset

**Files.** `internal/sxq/{lexer,parser,compile,aliases}.go`,
`internal/api/sxq.go`, `test/golden/sxq/*`

**Steps.** ADR-004's phase-1 row, no more. Compile to **parameterized** SQL;
never string-concatenate user input (§7.3). Unknown fields resolve against
`field_def` per project and produce a parse error with a suggestion, never a
silent empty result. `GET /sxq/complete?partial=` driven by the same grammar.
Queries are pure and read-only, always.

**Acceptance.**
```bash
make test-sxq          # the golden corpus, including §7.2 examples
make fuzz-sxq          # short fuzz run asserting no unparameterized literal is ever emitted
```

### Task 1.22 — Caching and compression

**Steps.** `ETag` + `If-None-Match` on item detail, project config, and static
assets; not on `?since_seq=`. Brotli where offered, gzip fallback (§6.1).

**Acceptance.** Tests asserting a `304` on a matching `If-None-Match`, and
asserting the `since_seq` endpoint emits no `ETag`.

### Task 1.23 — Concurrency test for §5.1

**Files.** `test/concurrency/cursor_test.go`

**Steps.** N parallel writers plus a poller following the cursor throughout;
assert every committed change is observed exactly once and no sequence value is
skipped (§5.1, §13, ADR-002). Include a bulk transition of 200 items in the mix,
since that is the case where per-row sequencing matters.

**Acceptance.** `make test-concurrency` — and it must be run with `-race`.

### Task 1.24 — Golden files for every endpoint

**Steps.** Request → committed expected JSON for every endpoint in §6.2 that this
phase implements — which, after tasks 1.9–1.19, is all of them except
`/promote` (§13). `make golden-update` regenerates; CI asserts no diff. Generated
under the pinned toolchain only (§1).

**Acceptance.** `make test-golden`, plus a coverage assertion: the test
enumerates the router's registered routes and fails if any lacks a golden file.

### Task 1.25 — Metrics

**Cut candidate #5** (§1.2).

**Steps.** `GET /metrics` in Prometheus text format, scraped only when
investigating. **Do not install Prometheus or Grafana** — that restraint is a
requirement, not an oversight (§14.3).

**Acceptance.** A test asserting the endpoint parses as valid Prometheus text
format.

### Gate 1

```bash
make gate-1
```

Runs gate-0 plus: `test-api`, `test-golden`, `test-sxq`, `fuzz-sxq` (short),
`test-concurrency -race`, `gate-gen`, and a curl-driven smoke script exercising
the §6.2 surface end to end against a seeded database.

**Human gates for phase 1:**
- [ ] A manual curl walkthrough of create → transition → reparent → link →
      comment, output pasted into `PROGRESS.md`
- [ ] Any cuts taken from §1.2 recorded with date and reason

---

## 7. Phase 2 — List view, item detail, theming baseline

**Spec "done means":** usable as a real backlog; **start tracking sierx's own
work in sierx here**; all five theme settings pass the contrast gate;
keyboard-only walkthrough passes.

**Entry condition:** gate 1 green.
**Branch:** `phase/2-frontend`
**Tasks:** 2.1 – 2.18, in order.
**⚠ Calendar deadline:** four weeks from the anchor recorded in `PROGRESS.md` at
task 0.1. If it slips, **cut scope, not the date** (§0 rule 5) — from the ranked
list in §1.2, top first, each cut recorded.

### Task 2.1 — Frontend skeleton and budget gates

**Files.** `web/*`, `.github/workflows/ci.yml`, `Makefile`

**Steps.** Vite + React 19 + Tailwind + shadcn/ui on Base UI primitives. Wire the
§9.1 budgets as build failures **before writing features**: first-route JS ≤ 250KB
brotli, first-route CSS ≤ 20KB brotli, any lazy chunk ≤ 60KB brotli, exactly one
route with eager imports (lint rule). Brotli precompression at build time, not on
the fly. Run `vite-bundle-visualizer` once in week one and record actual
composition against §9.1's estimate in `PROGRESS.md`.

**Budget note, recorded now rather than discovered at 250KB.** §9.1's estimate is
~170KB and omits three things this phase actually ships: TanStack Virtual (task
2.7), `@floating-ui/react` which Base UI depends on (§1), and the theme CSS. The
Markdown renderer is deliberately out of the first route (ADR-014). If the
week-one measurement lands above ~215KB, raise it in `PROGRESS.md` then — not at
task 2.10.

**Route table (ADR-018).** Declare `web/src/routes/table.ts` in this task, before
any route exists to be split, because it is the router's source and — via
`make gen-routes` — the Go bootstrap-injection table task 2.4 dispatches on.
`gate-routes` asserts three things: the generated Go table matches fresh output,
every route in it has an injection handler, and **every root segment's uppercase
form appears in `internal/api/reserved.go`** (task 1.9). That last check is why
the reserved list can be owned by Go in phase 1 and still be correct — a root
route added later without reserving its prefix fails the build here.

Wire `make gate-routes` now, alongside `gate-bundle`, for the same reason the
budget gates come first: a gate added after the code it constrains gets
negotiated with.

**Acceptance.** `make gate-bundle && make gate-routes` — both green on the
skeleton, and each proven to fail: a large import for the first; for the second,
a hand-edited generated table, and separately a new root route with no reserved
prefix.

### Task 2.2 — Theme tokens and the contrast gate

**Files.** `web/src/themes/*.css`, `web/src/themes/tokens.test.ts`,
`.stylelintrc`

**Steps.** Five settings over four palettes: `system`, `light`, `dark`,
`light-hc`, `dark-hc` (§10.2). CSS custom properties on
`:root[data-theme="…"]`, matching shadcn's token convention so components need no
theme awareness. Zero runtime CSS-in-JS. Bands and constraints per ADR-009.

The contrast gate enumerates **every declared token pair** and computes ratios,
failing the build on violation (§10.3): foreground/background 4.5:1 (7:1 in HC),
muted-foreground/background 4.5:1, border/background 3:1, ring 3:1 against
adjacent, status colors 3:1 on their card background. Add the ADR-009 chroma
ceiling on the 60% band and the stylelint rule restricting where `--status-*` may
appear.

**Acceptance.** `make gate-contrast` and `make gate-stylelint`, both proven to
fail with a deliberately bad token.

### Task 2.3 — Theme delivery

**Steps.** Theme read from `user_account.theme` and **injected into the initial
HTML** so there is no flash of the wrong theme (§10.2); written via
`PATCH /me` (task 1.19, ADR-015). `system` follows `prefers-color-scheme` and
upgrades to the matching HC palette under `prefers-contrast: more`.
`reduced_motion` NULL means follow the OS.

**Acceptance.** A Playwright test asserting no theme flash on load for each of
the five settings, and one asserting the switcher persists across a reload.

### Task 2.4 — Bootstrap state injection

**Steps.** The Go server embeds the first screen's data as a JSON script tag in
`index.html`, killing the JS→API waterfall (§9.2.2). Six serialized round trips
at 650ms RTT is 3.9s before first useful pixel regardless of bundle size — this
matters more than bundle tuning.

The server decides what to embed by matching the request path against the
generated route table from task 2.1, and the query string against §7's `q`
(ADR-018) — which is why `q` cannot live in a fragment. A route in the table with
no injection handler is a `gate-routes` failure, not a slow page.

**Acceptance.** A test asserting the first route renders content with network
requests blocked after document load, for `/`, `/?q=<sxq>`, and `/SRX-42`.

### Task 2.5 — API client and optimistic mutations

**Steps.** TanStack Query with a shared optimistic-mutation helper; on a 650ms
link this is the single largest perceived-speed improvement (§9.2.4).
Content-hashed immutable assets with
`Cache-Control: public, max-age=31536000, immutable` (§9.2.1). **No browser
storage for application state** — React state only (§9.2.7), and note that
`localStorage` and `sessionStorage` must not be used at all. The client sends
`If-Match` on every mutation except `PATCH /me` (ADR-015).

**Acceptance.** Tests asserting an optimistic update rolls back correctly on a
`409`.

### Task 2.6 — Login route

**Steps.** §10.4.9 compliant: single password input, paste allowed, autocomplete
attributes set so password managers fill it.

**Acceptance.** axe with zero violations; a Playwright test asserting paste works
and autocomplete attributes are present.

### Task 2.7 — List view

**Steps.** Virtualized with TanStack Virtual for anything over 50 rows — render
30 rows, not 5,000 (§9.2.5). Dense, legible, sentence case throughout. Field
projection requested explicitly, never the full record. Because an item's key
prefix is not necessarily its project (A.1), the row shows project separately
where they differ (ADR-007's `project` projection).

**Acceptance.** A test with a 10k-item seeded workspace asserting the DOM node
count stays bounded while scrolling.

### Task 2.8 — Query input

**Steps.** A single `sxq` input backed by `/sxq/complete`. Every query is
URL-addressable so a link is a shareable view (§7). There is no filter-builder UI
to maintain. The query lives in `?q=`, percent-encoded, **never in a fragment**
(ADR-018) — a long query is what saved views (task 1.18) are for, not a shorter
URL scheme.

**Acceptance.** A test asserting a query in the URL restores the same view, that
a parse error shows the suggestion from the server rather than an empty list, and
that `/?q=<sxq>` server-renders its bootstrap payload (ADR-018's fragment
constraint, asserted rather than assumed).

### Task 2.9 — Markdown rendering

**ADR-014 was approved 2026-09-12** (§4.0). **Precedes task 2.10**, which
renders item bodies.

**Files.** `web/src/markdown/render.ts`, `web/src/markdown/render.test.ts`,
`test/golden/markdown/*`

**Steps.** ADR-014 in full: `markdown-it` with
`{ html: false, linkify: true, typographer: false, breaks: false }`,
`validateLink` narrowed to `https?:` and `mailto:`, links rendered with
`rel="noopener noreferrer"` and `target="_blank"` for external ones. **Dynamically
imported** — a static import in a first-route module is a `gate-bundle` failure,
which is the intended enforcement.

**Acceptance.** `make gate-markdown` — the hostile corpus from ADR-014
(`<script>`, `<img onerror>`, `<iframe>`, `javascript:` and `data:text/html`
links, raw `<style>`, an HTML comment) asserting no element outside the allowed
set and no `on*` attribute survives; plus `make gate-bundle` proving markdown-it
is absent from the first-route chunk.

### Task 2.10 — Item detail

**Steps.** Fields, Markdown body rendered client-side via task 2.9, history from
`change_event` (task 1.17), linked items, comments. "Linked items", not "edge
set" (§9.4). Rollup shown where meaningful — and because a leaf's rollup is zeros
rather than absent (ADR-013), the component decides *whether to show* it from
`descendant_count`, not from the field's presence.

Routed at `/SRX-42` — no project segment, no path suffixes (ADR-018). A
soft-deleted item **renders with a banner rather than 404ing**: keys are never
reused (§5.8, A.1), so the URL stays meaningful permanently and a dead link is
the worse outcome. Mutation controls are hidden, not merely disabled, and the
banner says when it was deleted.

**Acceptance.** axe zero violations; golden snapshot of the rendered structure; a
test asserting `/srx-42` redirects `308` to `/SRX-42` and that a soft-deleted
item returns 200 with the banner and no mutation controls.

### Task 2.11 — Create flow and empty states

**Goal.** The dogfooding gate needs a way to add work without curl.

**Steps.** A create form reachable by keyboard from the list view: project, type,
title, and the type's initial status resolved from `/projects/{key}/config` (task
1.10) rather than hardcoded. Empty states per §9.4 — invitations, not dead ends:
"No items match this query. Clear the filter or create one." Copy rules
throughout: active voice, a button says what happens, an action keeps its name
through the flow.

**Acceptance.** axe zero violations on the form and on each empty state; a
Playwright test creating an item with no mouse events; a copy review item in the
phase-2 human gates.

### Task 2.12 — Conflict UI

**Steps.** A `409` surfaces as "Someone else changed this item. Review the
differences and retry." **with the actual diff**, not "Conflict error" (§9.4).

**Acceptance.** A Playwright test driving two sessions into a real conflict and
asserting the diff renders.

### Task 2.13 — Keyboard and focus model

**Steps.** Focus always visible; `outline: none` without a replacement banned by
lint rule; focus ring ≥ 3:1 against adjacent colors (§10.4.5). Focused elements
never obscured by sticky headers (§10.4.4). Interactive targets ≥ 24×24 CSS px
including padding, with the spacing exception available in dense views (§10.4.3).
Text to 200% without loss of content, and user text-spacing overrides tolerated
(§10.4.7). `prefers-reduced-motion` disables panel transitions and non-essential
motion (§10.4.6). Motion answers an action; nothing fades in on scroll (§9.3).

**Acceptance.** `make gate-lint-focus` plus the axe gate.

### Task 2.14 — Accessibility gates

**Steps.** axe-core, **zero violations**, on login, list, item detail, and the
create form (§10.5). Screen-reader label subset asserted on all interactive
elements. Every icon-only control has an accessible name (§10.4.8).

**Acceptance.** `make gate-axe`

### Task 2.15 — Keyboard-only walkthrough

**Steps.** Playwright, **no mouse events**: create → transition → reparent →
reorder → comment (§10.5).

**Acceptance.** `make gate-keyboard`

### Task 2.16 — Serve and deploy

**Steps.** Embed the SPA in the Go binary (§3.2). Caddy serving
brotli-precompressed static assets with HTTP/3; Quadlet units for `sierx`,
`postgres`, and Caddy. Pull-based deploy: the host polls a deploy branch or
registry tag on an interval — **no self-hosted runner, no inbound webhook**
(§14.1). Cross-compile for the Pi; never build the frontend on it (§3.4).

**This task unblocks `gate-bench`** (ADR-016): once staging exists, run
`make bench-baseline` on the Pi against the 10k seed and commit the baseline.
That is the first time §12's thresholds are meaningful.

**This is also where §14.2's off-box backup requirement binds** (ADR-010). The
host env file sets `SIERX_ENV=staging` and a real repository — `sftp` to a host
already in service, or `s3` — and `bootstrap-check` rejects the dev-shaped
`posix` target at that point automatically. Then `driver.sh init` against the new
repository and one `make restore-test` before the host holds anything worth
keeping. Set `SIERX_BASE_URL` here too; it has no committable value (§3.7).

**Acceptance.** `make deploy-staging` (documented, human-run) followed by
`curl https://<staging>/api/v1/healthz`, then `make backup-conformance` and
`make restore-test` against the real repository, then `make bench-baseline` and
`make gate-bench` on the Pi with the 10k seed.

### Task 2.17 — Preact experiment (cut candidate #1)

**Steps.** Alias `react` → `preact/compat`, measure, decide. **Two-hour
timebox**, a measured result in `PROGRESS.md`, and an easy revert. Base UI
occasionally breaks under Preact — and Base UI is now the default shadcn
primitive layer (§1), so this is an experiment, not a commitment (§9.1).

**Acceptance.** Either a recorded bundle delta with all gates still green, or a
revert commit and a one-line note. Both outcomes are success.

### Task 2.18 — Cutover

**Steps.** Bootstrap a real workspace on staging, create the `SRX` project, and
**start tracking sierx's own work in sierx.** Migrate the remaining phase-3…7
items out of `PROGRESS.md` and into sierx itself.

This may follow the deadline by a few days. It cannot be dropped: it is phase 2's
actual point, and it is what makes SPEC §0 rule 2's dogfooding gate possible.

**Acceptance.** `SRX-1` exists and describes phase 3.

### Gate 2

```bash
make gate-2
```

Runs gate-1 plus: `gate-bundle`, `gate-routes`, `gate-contrast`,
`gate-stylelint`, `gate-markdown`, `gate-axe`, `gate-keyboard`,
`gate-lint-focus`, and the theme-flash, redirect-canonicalization, and
virtualization tests.

**Human gates for phase 2:**
- [ ] `gate-bench` green on the Pi 5 with the 10k seed, baseline committed
      (ADR-016)
- [ ] **Seven consecutive days of real daily use** as the primary backlog (§0
      rule 2). No phase-3 code merges before this is signed
- [ ] Design review against §9.3: card elevation encodes state rather than
      decoration; no ALL-CAPS labels; no tracked-out eyebrow labels; no
      middle-dot meta strings; no ambient motion
- [ ] Copy review against §9.4: buttons name their action, actions keep their
      name, errors say what to do, empty states invite
- [ ] The 60/30/10 proportion review (ADR-009) — the one gate that is judgement,
      not a test

---

## 8. Phases 3–7 — gate definitions only

These phases are **deliberately not expanded into tasks.** SPEC §0 rules 1 and 2
forbid scaffolding ahead, and phase 2's exit condition is a week of real use —
which is the only reliable signal about which of these phases is actually wanted
and in what shape. Detailed task lists written now would be rewritten anyway, and
their existence would tempt forward scaffolding.

**Expansion protocol.** When the prior phase's gate is green and its human gates
are signed, the human asks for the next phase to be expanded. Expansion uses the
task template in Appendix C and resolves that phase's open questions first,
recording each as an ADR. Expansion is also where the endpoint-coverage check
from task 1.24 is repeated: every route the phase adds gets an owning task before
any code is written.

### Phase 3 — Kanban board

| | |
|---|---|
| **Deliverable** | Column↔status mapping, WIP limits, optimistic updates, drag **and** keyboard/menu-based move |
| **Entry** | Gate 2 green; seven days of dogfooding signed |
| **Gate** | `make gate-3` = gate-2 plus: board route bundle within budget (dnd-kit adds ~30KB, so the board is a lazy chunk); board view p95 < 150ms server time at 500 items with projected fields; **§10.4.1 non-drag alternative** proven by a Playwright test that moves a card between columns using only the keyboard, and a second test using only the context menu; `1.4.1` assertion that status, priority, and blocked state each carry a glyph or text label, not color alone; focus-not-obscured test **with the board scrolled** |
| **Open questions to resolve at entry** | Do board columns come from config (§8.1 `board.columns`) before phase 7 exists? Recommended: a seed-SQL-backed `board_column` table now, YAML in phase 7. Does a WIP limit block a move or warn? |
| **Do not** | Do not add WebSockets for live board updates. Polling at 10s focused, paused when hidden, exponential backoff (§6.3) |

### Phase 4 — Sprints and Scrum board

| | |
|---|---|
| **Deliverable** | Sprint scope with `removed_at` tracking, burndown computed from the event log, scope change visible |
| **Entry** | Gate 3 green; a week of board use |
| **Gate** | `make gate-4` = gate-3 plus: a burndown property test asserting the chart derives entirely from `change_event` and `sprint_item.added_at`/`removed_at`, with committed scope, mid-sprint additions, and removals distinguishable; `startOfSprint()`/`endOfSprint()` added to the sxq golden corpus |
| **Open questions** | §16 #5: does `points` ship? Spec recommendation stands — the column exists, the UI is off by default. Decide the toggle's scope (per project or per workspace) |
| **Do not** | Do not hard-delete from `sprint_item`. `removed_at` is what makes an honest burndown possible (§4.8) |

### Phase 5 — Hierarchy and timeline

| | |
|---|---|
| **Deliverable** | Arbitrary depth, rollups surfaced, dependency overlay, critical path |
| **Entry** | Gate 4 green |
| **Gate** | `make gate-5` = gate-4 plus: descendant rollup read at depth 6 p95 < 50ms; a critical-path property test over a randomized typed link graph; `descendants(expr)` and `ancestors(expr)` added to the sxq corpus (ADR-004); cross-project ordered views proven **not** to order by `item.rank` (ADR-003) |
| **Open questions** | §16 #6 time-travel scope. Spec recommendation stands: three specific queries — item state on date X, epic target-date history, roadmap snapshot diff — rather than a general `AS OF`, which needs a temporal variant of every read path and costs roughly a month. **Also:** whether the portfolio roadmap needs cross-project hierarchy, which would supersede ADR-012 — decide before building the roadmap view, not during |
| **Do not** | Do not compute rollups on read (A.5) |

### Phase 6 — Discovery

| | |
|---|---|
| **Deliverable** | Idea board, scoring, `promote` operation, outcome fields, Monte Carlo forecast |
| **Entry** | Gate 5 green, **and at least three months of real transition history in the production database** |
| **Gate** | `make gate-6` = gate-5 plus: a `promote` test asserting the item id, key, and full history survive a type change in place (§1.2, Appendix B); a forecast test asserting the Monte Carlo output is derived only from observed cycle-time distributions and refuses to produce a forecast below a minimum sample size |
| **Open questions** | What does the forecast do when there is not enough history? Recommended: say so, explicitly, rather than emit a wide-interval guess. Also: `promote` across projects is blocked by ADR-012 — confirm that idea→initiative always stays in one project |
| **Do not** | Do not build this early. It needs ~3 months of real data before it says anything true (§2) |

### Phase 7 — Config-as-code tooling

| | |
|---|---|
| **Deliverable** | YAML schema, `sierxctl plan` / `apply`, git reconcile loop |
| **Entry** | Gate 6 green — or earlier if configuration friction becomes the actual bottleneck, which is a legitimate reordering to propose |
| **Gate** | `make gate-7` = gate-6 plus: a round-trip test (`export` → `apply` → `export` is a fixed point); a `plan` output test asserting consequences are named, not just field diffs — "14 items will report under the new name; history preserved (config v7 → v8)", and the warning when a removed transition leaves items with no path to a done status (the reachability check from ADR-011, reused); a wildcard-expansion test asserting a newly added status does **not** silently acquire `* → dropped` and that `plan` says so (ADR-011); `plan` exits 2 when changes are pending; destructive changes require `--force`; a reconcile test asserting non-destructive changes apply automatically and destructive drift alerts and does nothing |
| **Open questions** | Where does the alert go, given no email in v1 (§1.3)? Recommended: a log line at error level plus a field on `/healthz` |
| **Do not** | No inbound webhooks, no self-hosted runner (§8.3) |

---

## 9. Appendix A — Make target reference

Created incrementally; every target must exist by the phase that needs it. Every
`gate-*` target must have a `prove-gates` proof in the same task that adds it
(task 0.12).

| Target | Purpose | First needed |
|---|---|---|
| `help` | List targets | 0.1 |
| `bootstrap-check` | Toolchain versions match pins; required inputs present | 0.1 |
| `gate-notopology` | No real hostnames, addresses, or `.env` values in tracked files | 0.1 |
| `db-up` / `db-down` / `db-psql` / `db-reset` | Dev database lifecycle | 0.2 |
| `migrate-up` / `migrate-down` / `migrate-status` | Migrations | 0.3 |
| `migrate-updown-up` | up → down → up clean | 0.3 |
| `schema-snapshot` | Dump live schema to `docs/schema.sql` | 0.4 |
| `schema-diff` | From-scratch migration vs committed snapshot | 0.4 |
| `test-sql` | Database-level invariants raise | 0.5 |
| `test-partitions` | Partition maintenance idempotent | 0.6 |
| `sqlc-gen` / `sqlc-diff` | Generated store code current | 0.7 |
| `gate-nodirect` | No writes to governed tables outside the store | 0.8 |
| `seed` | 10k-item workspace | 0.9 |
| `test-property` | Rollup, path, rank invariants | 0.10 |
| `backup-conformance` | Every driver through ADR-017's assertion set | 0.11 |
| `gate-nobackupleak` | No tool name outside its driver | 0.11 |
| `restore-test` | Restore via the driver interface, rotating targets | 0.11 |
| `ci-local` | Full gate set, offline, in a container | 0.12 |
| `gate-license` | §15.1 allowlist | 0.13 |
| `bench-smoke` | Benchmarks run, advisory timings (CI) | 0.14 |
| `bench-baseline` | Capture §12 baseline on reference hardware | 0.14 |
| `gate-bench` | §12 thresholds vs baseline (human gate) | 0.14 |
| `test-api` / `test-golden` | API behaviour | 1.1 |
| `gen-fields` / `gate-gen` | Projection registry ↔ client types | 1.7 |
| `test-sxq` / `fuzz-sxq` | Query language | 1.21 |
| `test-concurrency` | §5.1 cursor, with `-race` | 1.23 |
| `golden-update` | Regenerate golden files | 1.24 |
| `gate-bundle` | §9.1 budgets | 2.1 |
| `gen-routes` / `gate-routes` | Route table ↔ Go bootstrap table ↔ reserved prefixes | 2.1 |
| `gate-contrast` / `gate-stylelint` | §10.3 and ADR-009 | 2.2 |
| `gate-markdown` | ADR-014 hostile corpus | 2.9 |
| `gate-axe` / `gate-keyboard` / `gate-lint-focus` | §10.5 | 2.14 |
| `deploy-staging` | Documented, human-run | 2.16 |
| `gate-0` … `gate-7` | Phase gates | per phase |
| `gate` | The current phase's gate, read from `PROGRESS.md` | 0.12 |

---

## 10. Appendix B — Environment variables

All configuration is environment variables; there is no config file (§14.4).
Startup fails loudly on a missing or malformed value.

`.env.example` carries names, types, and allowed values — **never a real value**.
Real values live in the untracked `.env` (dev) and the host's `0600` env file
(staging, prod). The repository is public; see §3.7.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | |
| `SIERX_AUTH_MODE` | yes | `local` \| `proxy`; explicit, never inferred |
| `SIERX_TRUSTED_PROXIES` | yes in `proxy` mode | CIDR allowlist; requests from elsewhere rejected |
| `SIERX_BASE_URL` | yes | |
| `SIERX_SESSION_KEY` | yes | Host env file, `0600`, never in git |
| `SIERX_ENV` | yes | `dev` \| `staging` \| `prod`; `db-reset` refuses unless `dev` |
| `SIERX_BACKUP_DRIVERS` | yes | Ordered list, e.g. `pgbackrest,pgdump` (ADR-017). Makefile targets never name a tool |
| `PGBACKREST_REPO_TYPE` | yes — checked at 0.1 | ⚠ **supplied by human**; `s3` \| `sftp` \| `posix`. `bootstrap-check` fails while empty |
| `PGBACKREST_REPO_PATH` | yes — checked at 0.1 | ⚠ **supplied by human**; bucket, `host:/path`, or mount path |
| `PGBACKREST_REPO_S3_*` | if `s3` | ⚠ **supplied by human**; endpoint, bucket, region. Keys in the host env file only |
| `PGBACKREST_CIPHER_PASS` | yes | Host env file, `0600`, never in git. `openssl rand -base64 48`. Fixed at `stanza-create` (ADR-010) |
| `PGBACKREST_REPO2_*` | no | Second repository when one is added. The harness supports up to four from day one (ADR-010) |
| `SIERX_DUMP_PATH` | yes | Target for the `pgdump` driver's weekly dumps |

---

## 11. Appendix C — Task template for expanding phases 3–7

````markdown
### Task N.M — <short imperative title>

**Goal.** <one sentence: what is true after this task that was not before>

**Files.** <explicit list; anything outside it needs a reason in the commit body>

**Steps.**
1. <ordered, specific, citing SPEC sections where they constrain the work>

**Acceptance.**
```bash
<a single command that exits 0 or nonzero>
```

**Do not.** <the specific wrong turn available here — omit if there isn't one>
````

Rules for a well-formed task:

1. **The acceptance is a command.** Not "verify that…", not "check the UI". If it
   cannot be a command, it is a human gate and belongs in the phase's human gate
   list instead.
2. **One task, one commit, one concern.** If the Files list spans the database,
   the API, and the frontend, it is three tasks.
3. **Cite the spec where it constrains.** An agent that can see *why* a
   constraint exists violates it less often.
4. **Name the available wrong turn.** Most of the "Do not" lines in phases 0–2
   exist because the obvious implementation is the wrong one — §5 says so in five
   places.
5. **Gates before features.** Budget, contrast, and license gates are wired
   before the code they constrain, never after.
6. **Every route gets an owner.** Before writing code for a phase, list the
   endpoints it adds and check each against a task. v1.0 of this guide left eight
   §6.2 endpoints unowned while gating on a walkthrough of all of them; that is
   the failure this rule exists to prevent.
7. **A new gate ships with its proof.** `prove-gates` fails on a `gate-*` target
   that has no deliberate-violation proof, so the proof is part of the task that
   introduces the gate.
