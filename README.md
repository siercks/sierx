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

sierx is licensed under the Apache License 2.0 — see `LICENSE` and `NOTICE`.
Dependencies are held to a permissive allowlist enforced in the build.

## Getting started

```bash
git clone https://github.com/siercks/sierx && cd sierx
cp .env.example .env            # then generate the two secrets it names
make bootstrap-check            # go, node, podman, psql, required inputs
make help                       # every target, one line each
```
