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
- The latest inspected owner record accepts walkthrough sessions A/B. It does not
  establish seven consecutive primary-backlog days, independent recovery custody,
  real-phone Phase 3 acceptance, or overall Phase 2 exit. Those gaps remain open in
  [PHASE-2-ACCEPTANCE.md](PHASE-2-ACCEPTANCE.md).

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
