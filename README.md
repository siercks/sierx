# sierx

sierx is a self-hosted work tracker for a small team: projects, items in an
arbitrary hierarchy, Kanban and Scrum boards, sprints, and a query language
(`sxq`) that makes any view a URL. It is a single Go binary in front of one
PostgreSQL database, with a lean React frontend that stays usable on a slow
link and a Raspberry Pi. There is no message broker, no background service,
and no cloud dependency — a VPS with 2 vCPU and 4 GB is the production target.

The project is being built from a written specification, one phase at a time,
by a coding agent under human review. `docs/SPEC.md` is the normative design,
`docs/BUILD.md` is the task-by-task build guide, `docs/DECISIONS.md` records
every resolution of an ambiguity, and `PROGRESS.md` is the only claim about
where the build is. Every gate is a `make` target you can run locally; CI does
nothing that `make` does not.

sierx is licensed under the Apache License 2.0 - see `LICENSE` and `NOTICE`.
Dependencies are held to a permissive allowlist enforced in the build.

## Phase 2 browser candidate

Start with [the Phase 2 walkthrough](docs/PHASE-2-WALKTHROUGH.md). It separates
safe disposable testing from deployment, recovery and real-backlog cutover.
Build the frontend with `npm --prefix web ci` and `make web-build` before building
the embedded Go server. The exact phase-exit status remains in PROGRESS and the
[acceptance record](docs/PHASE-2-ACCEPTANCE.md).

## API development

Run `make test-api TEST_ARGS='-run TestServerBoot'` to select an API test.
`TEST_ARGS` contains trusted Go test flags, not an extra make option. The runner
loads the disposable database URL from the environment or the untracked `.env`
and fails when it is missing. `go run ./cmd/sierx` reads environment variables
directly; export them before starting it. `SIERX_LISTEN_ADDR` defaults to `:8080`.
`GET /api/v1/healthz` returns `alive: true` and `database: reachable` (200) or
`database: unavailable` (503). A database outage does not prevent process startup.

After migrations, export the `SIERX_BOOTSTRAP_*` settings shown in `.env.example`
and run `go run ./cmd/sierxctl bootstrap`. This creates one workspace, an admin
and an empty project with the standard configuration. Run it again with the
same identity settings to inspect the existing IDs without changing data. In
proxy mode the administrator has no local password. Bootstrap never runs the
benchmark seed or creates a second workspace.

## Getting started

```bash
git clone https://github.com/siercks/sierx && cd sierx
cp .env.example .env            # then generate the two secrets it names
make bootstrap-check            # go, node, podman, psql, required inputs
make help                       # every target, one line each
```

The example publishes the rootless PostgreSQL container only on
`127.0.0.1:55432`; PostgreSQL continues to use port 5432 inside the container.
Set a different explicit port in the private `DATABASE_URL` if 55432 is already
occupied.
