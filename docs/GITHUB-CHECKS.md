# GitHub checks before merging Phase 1

The `ci` workflow runs the offline-compatible phase gate. The `security`
workflow adds two read-only jobs on PRs, pushes to main/build branches, manual
dispatch, and Mondays at 08:23 UTC. Scheduled runs begin after the workflow
reaches the default branch.

- `workflow-lint`: actionlint v1.7.12 plus ShellCheck validates all workflow files.
- `go-vulnerabilities`: govulncheck v1.8.0 fails for known vulnerabilities reachable
  from the Go source. Findings outside reachable code may be reported without
  failure; this is not a claim that every dependency is vulnerability-free.
- `frontend-vulnerabilities`: installs the exact npm lockfile without lifecycle
  scripts, verifies registry integrity hashes, registry signatures/provenance,
  and the license policy (including negative drift tests), then fails on known
  moderate-or-higher npm advisories.

Run locally with the pinned Go toolchain, make, Bash and ShellCheck installed:

```sh
make check-workflows
make check-vulnerabilities
make check-web-supply-chain
```

These targets fetch pinned tool versions through Go's module checksum mechanism;
the tools are kept in ignored `bin/security-tools`, outside application go.mod
and vendor. Vulnerability scanning reads the current online Go vulnerability
database. It is deliberately separate from `make ci-local`. The existing
Dependabot GitHub Actions configuration maintains the full commit-SHA pins.

The initial scan on 2026-09-18 found zero reachable or imported-package
vulnerabilities. It reported module-only GO-2026-5932 for the unused
golang.org/x/crypto/openpgp package (no fixed version). Sierx does not import
that package. No suppression was added; subsequent scans use fresh advisory
data and will fail if a vulnerability becomes reachable.

The phase gate now reports and requires PostgreSQL 18 psql, dump and restore
clients before migrations. When DATABASE_URL is exported, it also checks the
server major version without printing credentials. Existing bootstrap checks
still handle database configuration loaded from .env.

## Required GitHub settings

These settings are not enabled by committing workflow files. Apply them in the
repository UI after the new jobs have run at least once on the PR.

1. Settings > Rules > Rulesets: create an **Active** branch ruleset named
   `Protect main`, targeting `main`. Require a pull request before merging.
   Keep required approvals at **0** for the current solo-maintainer workflow.
2. Require status checks: select `gate`, `workflow-lint`, and
   `go-vulnerabilities`, with **GitHub Actions** as their expected source.
   Require the branch to be up to date before merging. Block force pushes and
   branch deletion. No routine bypass actors are needed.
3. Settings > security settings: verify **Secret Protection / secret scanning**
   and **push protection** are enabled. Review any existing secret alerts.
   Supported-pattern detection is not a guarantee that arbitrary passwords or
   application session keys will be detected.
4. Return to the PR and confirm all three jobs pass and GitHub identifies them
   as required. Preserve any stronger existing protections instead of replacing
   them with weaker rules.

Public API inspection initially returned no repository rulesets. Legacy branch
protection and secret settings could not be read without authentication. Their
state must be confirmed in the authenticated UI; this file does not claim they
have been enabled. CodeQL and dependency-review remain possible later additions.

References:
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/enable-push-protection
- https://go.dev/doc/security/vuln/
- https://github.com/rhysd/actionlint


## Phase 2 additions

Keep the separate workflow-lint and go-vulnerabilities checks. Add
frontend-vulnerabilities to required checks after its first hosted run. Its
license portion is default-deny: an unknown license, a copyleft license, a
package using another package's narrow exception, or a stale exact-version
exception fails. The advisory portion uses the current npm registry database,
so it remains an online scheduled/PR check. The main
gate now invokes gate-2; frontend preparation downloads the exact lockfile and
Playwright browsers before offline execution. Build the web assets before running
Go source scans because the application embeds those assets. Release publication
is separate from the operator-controlled deployment manifest channel.
