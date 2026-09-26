# Contributing to Sierx

Start with `docs/SPEC.md`, current amendments in `docs/DECISIONS.md`, and
`PROGRESS.md`. Phase 2 code is merged; host, recovery and human acceptance remain
separate. Use a focused `uplift/` branch for this Phase 2 work.

## Reproduce the checks

Use a disposable Linux environment with rootless Podman, make and Python. The
prepared CI path acquires pinned toolchains online, then runs offline with its
own database. It requires no private infrastructure or production credentials:

```sh
make ci-local-prepare
make ci-local
```

Refresh preparation when its recorded inputs change. For direct source tests,
follow `docs/BUILD.md` for the disposable database and tools. Go/Node versions are
in `go.mod` and `.nvmrc`; unit checks need Quadlet and systemd-analyze. Never run
source gates against your persistent backlog: migration/seed gates destroy data.

```sh
make check             # Focused backend/source loop; not phase acceptance.
make web-test          # Frontend unit tests after npm preparation.
python3 -m unittest discover -s test/python -p 'test_*.py'
make gate-units prove-units
make gate-markdown prove-markdown
```

`make gate-2` runs the full source gate. Online security checks remain separate:
`make check-vulnerabilities`, `make check-web-supply-chain`, and
`make check-workflows` (requires ShellCheck). Native artifact tests and their
prerequisites are documented in `docs/RELEASE-ASSURANCE.md`.

## Review expectations

Describe the problem, resulting behavior and checks actually run. Include a
reproduction for fixes, screenshots for UI work, and explicit untested host or
architecture limitations. Use synthetic data. Do not upload raw credential-bearing
logs or traces. See `SECURITY.md` for security reports.

Contracts, budgets, license policy and material gate exemptions need a documented
decision. Routine fixture updates need a reviewed rationale; do not regenerate
expectations just to hide a failure. Required tests must execute: missing
prerequisites and unexpected skips are failures. New gates need negative controls
that fail for the intended reason.

Keep connected deployment working while adding optional offline support. Preserve
the browser/data contract and review the actual dependency graph before adding
packages. The default-deny license policy, including the MPL restriction, applies
to frontend components too (ADR-024/025).

Useful starter contributions include a reproducible UX defect, a missing failure
test, clearer operational guidance, or one shared component used by a real screen.
Follow `AGENTS.md`: preserve the human Git identity and omit AI attribution.
