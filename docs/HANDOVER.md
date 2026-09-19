# sierx — handover to the coding agent

**Date:** 2026-09-12, revised 2026-09-18 (see §0)
**Repository:** `github.com/siercks/sierx` (public, Apache-2.0, module path
`github.com/siercks/sierx`)

This file exists so a session starts with zero ambiguity about what is already
true. Read it once; `PROGRESS.md` is the running state thereafter.

---

## 0. Current state (Phase 2 code candidate, 2026-09-18)

Phase 1 is merged as PR #5 at 561df396f73058a77d9a34370d9e407528490dbc.
The owner authorized implementation through the end of Phase 2 code. The
frontend and deployment/recovery tooling are implemented; see PROGRESS and
docs/PHASE-2-ACCEPTANCE.md for measured results and pending acceptance. Work is on
build/phase-2-frontend in an isolated checkout. Brave/Chromium is the primary
walkthrough browser; Firefox is available. The owner executes Spark commands.

ADR-020 removes deadlines and the immediate Pi requirement. Spark measurements
are not small-host certification. ADR-021 requires verified encrypted off-machine
physical backup and an isolated restore before the deployed backlog is relied on.
Seven days of actual primary-backlog use and human design/copy/keyboard reviews
remain acceptance requirements, not outcomes implied by implementation.

Never run the destructive phase gate against persistent backlog data. Use the
isolated offline CI container. The historical acceptance evidence is preserved
in PROGRESS and docs/acceptance.

Sections 1-3 below are historical pre-build context, not current status.

---

## 1. What is already committed

Five files are in place before the agent's first commit. They are the documents
the build reads, not the build itself.

| File | Status | Effect on the guide |
|---|---|---|
| `LICENSE` | Apache-2.0, from the repository's initial commit | Task 0.1 step 0: **do not replace it** |
| `docs/SPEC.md` | Normative, verbatim, **read-only** | Task 0.1 step 3 is satisfied. Never edit it (BUILD §3.5) |
| `docs/BUILD.md` | v1.5 — the build guide | Task 0.1 step 3 is satisfied |
| `docs/DECISIONS.md` | ADR-001 … ADR-019 seeded, statuses recorded | Task 0.1 step 4 becomes **verification**: confirm 19 ADRs are present with the statuses in BUILD §4.0, then move on |
| `PROGRESS.md` | Phase-0 checklist, sign-offs recorded | Task 0.1 step 5 becomes **verification** plus one edit: fill the deadline anchor |
| `.env.example` | Every variable, types and placeholders only | Task 0.1 step 7 becomes **verification**: confirm it matches BUILD Appendix B |

Task 0.1's acceptance command is unchanged. Steps 0–1, 2, 6, 8, 9, 10 are still
real work: `go.mod`, `.nvmrc`, `package.json`, `Makefile`, `.gitignore`,
`.editorconfig`, `NOTICE`, `README.md`, `.github/dependabot.yml`,
`scripts/bootstrap-check.sh`, `scripts/gate-notopology.sh`.

**Nothing executable is pre-written.** No `Makefile`, no scripts, no migrations.
Pre-writing them would hand over code whose acceptance has never been run, which
is the exact failure mode BUILD §0.4 exists to prevent.

## 2. What is outstanding

**Two secrets, generated locally. No infrastructure decisions.**

```bash
cp .env.example .env
openssl rand -base64 32   # -> SIERX_SESSION_KEY
openssl rand -base64 48   # -> PGBACKREST_CIPHER_PASS
```

Every other value in `.env.example` is a working dev default. Neither of these
two ever enters git or a prompt (BUILD §3.7); `gate-notopology` fails the build
if a real value reaches a tracked file.

**The backup repository is not a phase-0 decision.** Dev uses `posix` to a local
path, which exercises the harness completely — task 0.11's restore test runs
against a database `make db-reset` destroys on purpose, so what is under test is
the harness, not durability. The real off-box target (`sftp` to a host already in
service, recommended, or `s3`) is set at **task 2.16** in the host's `0600` env
file, where the deploy happens.

`bootstrap-check` rejects `PGBACKREST_REPO_TYPE=posix` whenever `SIERX_ENV` is
not `dev`, so the dev fixture cannot reach staging or production by accident, and
task 2.16 cannot pass without a real repository (ADR-010).

## 3. Sign-off state

| ADR | Subject | State |
|---|---|---|
| ADR-002 | One sequence value per event row | ✅ approved 2026-09-12 |
| ADR-005 | Rollups in the store layer, not triggers | ✅ approved 2026-09-12 |
| ADR-012 | Cross-project moves rejected in v1 | ✅ approved 2026-09-12 |
| ADR-014 | Markdown with raw HTML disabled at the parser | ✅ approved 2026-09-12 |

Recorded in `PROGRESS.md`, which is what BUILD §0.3 reads. The agent does not
stop at tasks 0.4, 0.8, 1.13, or 2.9 on their account.

## 4. Read order for every session

1. `PROGRESS.md` — current phase, next unchecked task. The only source of truth
   for where the build is.
2. `docs/BUILD.md` §0–§4 — protocol, environment, decision record.
3. `docs/BUILD.md` for the **current phase**. Phase 1 is §6. Read later-phase
   requirements when planning an explicitly requested interface, without scaffolding it.
4. `docs/DECISIONS.md` — ADRs added since the guide was written.
5. `docs/SPEC.md` — the sections the current task cites. Read those; do not read
   the whole specification into context on every task.

## 5. Stop conditions (BUILD §0.3)

Stop and ask, rather than choosing:

- A ⚠ ADR has no recorded approval in `PROGRESS.md`
- A task's inputs are unresolved
- `docs/BUILD.md` and `docs/SPEC.md` disagree and no ADR covers it
- A phase gate is green and the exit block is written — the human decides when to
  advance
- A human gate is next
- An acceptance command needs a credential, host, or domain not in `.env.example`
- Implementing a task as written would violate a SPEC §5 invariant

## 6. Historical Phase 0 kickoff prompt (superseded)

Paste this as the first message of the build session.

````text
You are executing the sierx build. The repository is github.com/siercks/sierx.

Read, in this order:
  1. PROGRESS.md
  2. docs/HANDOVER.md
  3. docs/BUILD.md sections 0 through 4
  4. docs/BUILD.md section 5 (phase 0). Do NOT read sections 6, 7, or 8.
  5. docs/DECISIONS.md

Then read the SPEC sections that task 0.1 cites, and begin at the first
unchecked task in PROGRESS.md.

Rules that override your defaults:
  - One task, one commit. Message format: phase0(0.N): <imperative summary>.
  - Do not mark a task done without pasting its acceptance command's output
    into PROGRESS.md. A green claim without evidence is treated as red.
  - Do not implement anything outside the current task's Files list without
    saying why in the commit body.
  - No forward scaffolding. No stubs or files for later phases.
  - If a semantic is not specified, stop and ask. Do not choose plausibly.
  - docs/SPEC.md is read-only. Resolutions go in docs/DECISIONS.md as new ADRs.
  - Ask before any destructive command. Show a diff before deleting code.
  - Never put a real hostname, bucket, address, or secret in a tracked file.
  - Before asserting a software version, release date, or availability, verify
    it. Do not assert from training data on those topics.

Start by confirming what you have read and what task 0.1 requires, then
implement it.
````

## 7. Calendar

ADR-020 supersedes the original 28-day deadline and deadline-triggered cuts.
The owner requests steady progress without a calendar deadline. Human phase
reviews, real-use feedback and acceptance evidence remain required.
