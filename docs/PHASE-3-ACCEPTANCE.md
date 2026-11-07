# Phase 3 entry and acceptance record

November 6, 2026. Implementation base: `4b73427ab63ea1076556fd0b20f9bd2433acd65b`
(main, merged PR #24). Work is isolated on `codex/phase-3-foundation`.

The owner explicitly requested Phase 3 development and publication of the resulting
image. That authorizes starting this increment; it does not fill in missing manual
Phase 2 evidence or accept a failed release profile. Scope and order are in
[PHASE-3-PLAN.md](PHASE-3-PLAN.md); fixed contracts are in ADR-031.

## Reconciled entry evidence

- [Release run 42163914084](https://github.com/siercks/sierx/actions/runs/42163914084)
  is at this exact base. Source Gate 2 passed on native amd64 and arm64; security,
  both native builds, both exact-image tests and both offline bundle tests passed.
- Ubuntu amd64 and Rocky amd64 host checks passed. Ubuntu arm64 host acceptance
  failed; the aggregate failed and promotion was skipped. Both architectures remain
  in the support/release matrix. No AMD64-only scope change is inferred.
- The separate main push CI was cancelled, so it is not additional green evidence.
- The owner reported completion of the seven-day Phase 2 backlog collection at
  the start of the Phase 2 next-steps chat and later accepted walkthrough sessions
  A/B. Preserve that owner report. The repository still lacks the filled daily
  ledger and overall Phase 2 exit/independent recovery approval; no Phase 3 phone
  acceptance is inferred. See [PHASE-2-ACCEPTANCE.md](PHASE-2-ACCEPTANCE.md).

## Increment boundaries

P3-01 records the scope/base/contracts. P3-02 adds build/route/dependency checks,
negative proofs and a fail-closed Phase 3 acceptance gate. P3-03 introduces only
versioned board schema/constraints/policies and database proofs. Board population,
workflow carry-forward, APIs and screens belong to subsequent tasks. No empty
Board/Account screen or nonworking menu action is presented as a feature.

The additive schema is not populated until P3-04 implements seeding and snapshot
carry-forward together. Existing workflows/items/preferences remain authoritative.
Fresh-install, migration round-trip, populated restore/rehearsal, schema snapshot,
generated store code and full Gate 2 must pass before releasing the schema increment.

## Candidate completion evidence

To be appended after checks: candidate commit, migration, exact commands/results,
bundle sizes, release workflow/digest and deployment verification. Gate 3 remains
incomplete until actual features and the required acceptance evidence exist.

No Board benchmark, iPhone/Safari walkthrough, owner review or Phase 3 completion
is claimed by this first increment.


## First increment: verified code and staged image

Candidate code commit: `6d84b86dc2178d6520b5f0f2058c5b219a8e5f02`.
P3-01: `7f57cbd`; P3-02: `d6e29e9`; P3-03: `6d84b86`.
The follow-up evidence commit changes documentation only.

Migration: `0017_board_config.sql`. No new runtime/build dependency.
Supported release matrix is still native amd64 + arm64; only the amd64 candidate
has been built/tested in this increment. Ubuntu/Rocky amd64 and Ubuntu arm64
host acceptance remain mandatory for release promotion.

Validation on native amd64 Linux, cached pinned offline environment (Go 1.27.3,
Node 24.22.1, PostgreSQL 18.6):

```
make phase3-foundation
  lazy entry/shared-chunk and route negative controls: PASS
make test-board-schema
  scoped snapshots/mappings/defaults/limits and tenant/admin policies: PASS
make migrate-updown-up schema-diff sqlc-diff gate-db-privileges
  clean at zero; 17 migrations applied; schema/code current; privileges: PASS
make gate-2
  151 Python tests; 45 frontend unit tests: PASS
  prove-gates: 17 proven, 8 exempt, 0 without a proof, 0 proof failures
  real HTTPS workflow: 63 Chromium + 63 Firefox cases: PASS
  10,000-item scale/keyboard/focus: Chromium + Firefox: PASS
  gate-2: GREEN (automated; deployment, restore and human acceptance remain separate)
python3 scripts/phase3.py acceptance
  expected rejection: Phase 3 acceptance is incomplete; no evidence report
```

The 16-to-17 populated rehearsal and populated four-table restore comparison
passed as recorded in PROGRESS.md. Full Gate 2 also exercised the existing seeded
backup/restore, API goldens, race, lifecycle, license, topology and offline asset
checks. This is isolated-container development evidence, not a new OS-host matrix
acceptance or a claim of offline production installation.

Actual build budgets (decimal bytes Brotli): initial JS **105674**, initial CSS
**19482**, largest lazy JS **36179**; limits remain 250000/20000/60000.
No Board endpoint benchmark, reference-hardware result or real iPhone/Safari
walkthrough exists yet. P3-33 must supply those independently.

Native packaged image from the exact clean code commit:

- Local candidate manifest digest:
  `sha256:4461c840b2661edd7bc8d8f3f2c97290ca6a5f31ffd810ba6d8a9e23686f3a46`.
- Image configuration ID:
  `af41e084e4bb3669ae6ffff6b27afbe87400b93db2fac7bd5a520a915bcdf2e6`.
- OCI archive SHA256:
  `a82accb934023eea89a8f34b34889a36b494dadf211d3d01ed31c833ef2f339e`.
- Existing `scripts/test-release-image.py` passed native amd64 image policy,
  shipped bootstrap/partition commands, authenticated writes/deep links,
  graceful stop and restart persistence against that exact digest.
- PostgreSQL 18 clients were invoked from the cached tool image with loopback
  host networking and fixture SQL-file mounts. Two initial temporary-wrapper
  attempts failed before migrations because stdin/file forwarding was incomplete;
  after correcting the runner, the unchanged packaged candidate passed. No
  acceptance receipt was issued by failed attempts.

The tested archive and receipt were transferred privately to the deployment host.
Archive checksum, image ID, Linux/amd64 platform, nonroot runtime user and source
label were verified after import. The existing live container ID/image remained
unchanged and running. No production migration or activation was performed.

Production promotion remains blocked by the pre-existing required ARM64 host
failure described above. The host uses a pinned reviewed manifest rather than
following candidate tags: image transfer alone cannot update the site. No release
check, architecture requirement, automatic updater, backup policy or branch
protection was bypassed or changed. The owner was asked whether to preserve both
architectures and investigate or explicitly approve an AMD64-only release scope;
no compatibility change is inferred without a response.

Hosted code-candidate evidence:
[CI](https://github.com/siercks/sierx/actions/runs/42327857483) and
[offline delivery](https://github.com/siercks/sierx/actions/runs/42327857484)
were still running at this record; [security](https://github.com/siercks/sierx/actions/runs/42327857516)
passed. These links concern the exact code candidate; later documentation commits
must not be reported as having separately passed those runs.

Next implementation task: P3-04 (seed/persist/carry board snapshots through workflow
edits); then P3-05 through P3-12 before visible Board interaction acceptance.
P3-13 onward supplies real personal preferences/identity/security/avatar surfaces.
Phase 3 completion, production use and owner review remain open.
