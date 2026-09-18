# Phase 1: a usable API, then a browser backlog

Phase 0 is accepted with the backup exception in ADR-021. The owner wants
sierx on the Spark for interactive testing and tracking its own development.
There is no calendar deadline. This plan groups the existing BUILD tasks into
observable milestones; it does not change task order or claim implementation.

## What you can interact with, and when

| Milestone | Existing tasks | Observable result |
|---|---|---|
| Running service | 1.1-1.2 | Start the server, query health, get useful failures and structured logs |
| Authenticated workspace | 1.3-1.6 | Bootstrap an administrator, sign in, inspect the current user and sign out |
| Editable backlog through HTTP | 1.7-1.11 | List projects/configuration, create and read items, edit with version checks |
| Complete item workflow | 1.12-1.20 | Transition, reorder/reparent, link, comment, inspect history and observe incremental changes |
| Queryable, verified API | 1.21-1.25 | Filter with sxq, use caching, verify concurrent sync, cover every endpoint with expected responses |
| Browser backlog | Phase 2 | Login page, keyboard-accessible list, item detail, create/edit/transition interactions |

Phase 1 is interactive through HTTP requests (curl or an API client). It does
not yet provide a browser workspace. Keep the first browser milestone focused
on list and detail; Kanban remains Phase 3. Avoid a disposable demo UI that
would need replacing when the real theme, bundle and accessibility gates land.

## First implementation task: 1.1

Build the server entry point, environment validation, database pool, routing,
request logging and graceful shutdown. Expose GET /api/v1/healthz and make its
response distinguish a reachable database from one that is unavailable. Validate
required settings without printing secret values. Trusted proxy configuration
is required only in proxy-auth mode.

Acceptance must be executable: missing/malformed configuration fails clearly;
health reflects database availability; startup/shutdown work under the pinned
Go toolchain. Use the existing Make-based test runner so database-backed tests
cannot silently skip. BUILD's illustrative `make test-api -run TestServerBoot`
needs a real supported argument mechanism (for example TEST_ARGS passed to the
runner), not an unsupported make option. Implement and document that mechanism
with the task. Check chi and any other new dependencies against the license gate
before adoption; do not add a new framework or datastore.

Only task 1.1 files and their required tests/build wiring land in that task's
commit. No placeholder handlers for later milestones. Retain one task per
commit and paste real acceptance output into PROGRESS.

## Demonstration that makes Phase 1 tangible

As each endpoint lands, extend an executable smoke walkthrough against a
throwaway workspace. The complete demonstration is:

1. Bootstrap, authenticate and inspect the current user.
2. Create an item, read it back, and update it using its current version.
3. Submit a stale version and verify that the response preserves both edits
   for conflict review rather than silently overwriting work.
4. Transition, reparent/reorder, add a linked item and comment.
5. Read history and poll incremental changes, including concurrent updates.
6. Filter the items with an sxq query.

Use fixed, reviewable expected JSON responses as specified by BUILD. The manual
curl walkthrough remains a human Phase 1 gate; automation supplies reproducible
evidence, not a substitute for actually trying the workflow.

## Spark execution and persistence

Continue to use the isolated ci-local database for full gates. Never point
migration-down acceptance at persistent application data. Any early server
interaction uses disposable fixtures until deployment and backup prerequisites
are satisfied. The first persistent backlog is a distinct deployment/database,
not the 10k benchmark seed. Application containers must remain portable across
Linux amd64/arm64; nothing in the server should depend on Spark-specific hardware.

The new Phase 1 tests must be included in the offline workflow. In particular,
the required race tests need a functioning native C compiler in the prepared
CI image: its present Phase 0 package list does not install one. Add and test
that prerequisite with the concurrency tooling rather than weakening the race
requirement. Re-prepare the CI image when its pinned inputs change.

## Phase boundary

Phase 1 exits only with gate-1, concurrency/race verification, endpoint golden
coverage and the manual workflow accepted. Phase 2 then adds the real browser
experience under bundle, theme, keyboard and accessibility gates. Before the
Spark backlog becomes relied-upon data, fulfill ADR-021's encrypted off-machine
backup and isolated physical-restore requirement. Small-host performance remains
a separate measurement; fast Spark timings cannot sign it off.
