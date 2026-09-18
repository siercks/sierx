# Phase 1 testing

Phase 1 is the HTTP API and supporting CLI. The browser application begins in
Phase 2. Keep `build/phase-1-api` as the testing branch and merge after the
automated gate and the hands-on walkthrough both pass.

## Automated acceptance

On a Linux host (including WSL), with rootless Podman, make and Python available:

```sh
make ci-local-prepare  # online tool/image preparation
make ci-local          # complete gate-1, offline in a disposable container
```

The second command does not use the host database or host environment file.
The prepared image includes the native compiler needed for `-race`. Changes to
toolchain/dependency/runner inputs require preparation again. No synthetic Git
commit or Git identity override is needed by this workflow.

For an existing disposable development database, export `DATABASE_URL` and run
individual checks with the pinned Go toolchain:

```sh
make test-api test-sxq fuzz-sxq test-concurrency test-golden gate-gen smoke-api
```

`golden-update` deliberately rewrites fixtures. `test-golden` regenerates under
the pinned toolchain and rejects any difference. The route inventory rejects
missing fixtures. Authentication secrets and generated IDs/timestamps are
normalized; raw user content is not normalized away.

## Hands-on workspace

Use a separate empty PostgreSQL 18 database. Export its `DATABASE_URL`, then:

```sh
make migrate-up
go build -o bin/sierx ./cmd/sierx
go build -o bin/sierxctl ./cmd/sierxctl

export SIERX_AUTH_MODE=local
export SIERX_BASE_URL=http://localhost:8080
export SIERX_LISTEN_ADDR=127.0.0.1:8080
export SIERX_SESSION_KEY="$(openssl rand -hex 32)"
export SIERX_BOOTSTRAP_WORKSPACE_SLUG=trial
export SIERX_BOOTSTRAP_WORKSPACE_NAME=Trial
export SIERX_BOOTSTRAP_ADMIN_EMAIL=admin@example.test
export SIERX_BOOTSTRAP_ADMIN_NAME=Administrator
export SIERX_BOOTSTRAP_PROJECT_PREFIX=TRY
export SIERX_BOOTSTRAP_PROJECT_NAME=Trial
read -rsp 'Initial administrator password: ' SIERX_BOOTSTRAP_ADMIN_PASSWORD
export SIERX_BOOTSTRAP_ADMIN_PASSWORD
printf '\n'
bin/sierxctl bootstrap
unset SIERX_BOOTSTRAP_ADMIN_PASSWORD
bin/sierx
```

The binaries read exported environment variables; they do not source `.env`.
Preserve the session key in your untracked host configuration: it encrypts TOTP
state. Bootstrap is idempotent for matching workspace/admin/project identities
and does not reset credentials. Localhost is suitable for a same-host curl
walkthrough; use HTTPS at your reverse proxy for remote browser access because
session cookies are always Secure. Proxy mode and its allowlist/header contract
are documented in ADR-022.

Use the real curl workflow in `test/smoke/api.py` as the request sequence. It
covers login, preferences, config, creation, transition, reparenting, links,
comments, projected queries, saved views, history, changes and deletion.
`make smoke-api` executes that sequence in its own temporary database.

For manual requests, retain the login cookie with curl's cookie jar. Include
`Content-Type: application/json` on JSON writes. Copy the returned item's JSON
`version` into a quoted `If-Match` header for later mutations. The weak GET ETag
is a cache validator, not the edit version. Request `fields` on item collections,
children and descendants, for example `fields=key,title,status,version`.

Try competing edits using the same version: one must succeed and the other
must return 409 with the current item and submitted values. Check that an invalid
transition names its missing requirement, and a cross-project move names both
projects. Cross-project links are allowed. Confirm deleted keys are not reused.
Enroll TOTP, verify one code, retain the returned recovery codes, and confirm a
used recovery code cannot sign in again. Finish with a restart and verify the
same data and authentication configuration still work.

Record the human walkthrough result in `PROGRESS.md`. Passing automated checks
does not substitute for that acceptance. Physical backup deployment remains the
existing ADR-021/Phase 2.16 item; this phase does not certify it.

For an on-demand metrics scrape, use the administrator cookie with
`GET /api/v1/metrics`. The response is Prometheus text, not JSON. No monitoring
service is required; ordinary members receive 403.
