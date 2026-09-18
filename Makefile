# sierx — every gate and every CI step lives here (BUILD §3.4).
# CI YAML may only call these targets; a human can run each one locally and offline.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help bootstrap-check gate-notopology prove-notopology \
        db-up db-down db-psql db-reset db-pin \
        migrate-up migrate-down migrate-status migrate-updown-up \
        schema-snapshot schema-diff test-sql test-partitions \
        sqlc-gen sqlc-diff gate-nodirect prove-nodirect test-store \
        seed seed-determinism rollup-verify \
        gate-license prove-license vendor-verify test-property \
        backup-conformance restore-test gate-nobackupleak prove-nobackupleak

# `make db-psql -- -c "select 1"`: make consumes `--` and leaves the words in
# MAKECMDGOALS; swallow them as no-op goals and hand them to db.sh, which
# rejoins everything after -c into one command.
ifeq (db-psql,$(firstword $(MAKECMDGOALS)))
  PSQL_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  export PSQL_ARGS
  .DEFAULT: ; @:
endif

help: ## List targets
	@awk 'BEGIN{FS=":.*## "} /^[A-Za-z0-9_-]+:.*## /{printf "  %-20s %s\n",$$1,$$2}' $(MAKEFILE_LIST)

bootstrap-check: ## Toolchain versions match the pins; required inputs present (task 0.1)
	@bash scripts/bootstrap-check.sh

gate-notopology: ## No real hostnames, addresses, or .env values in committable files (BUILD §3.7)
	@bash scripts/gate-notopology.sh

prove-notopology: ## Plant each topology violation in a scratch copy and assert the gate goes red
	@bash scripts/gate-notopology.sh --prove

db-up: ## Start PostgreSQL 18 (rootless Podman Quadlet, C locale, digest-pinned) (task 0.2)
	@bash scripts/db.sh up

db-down: ## Stop the database; data stays in the named volume
	@bash scripts/db.sh down

db-psql: ## psql into the dev database: make db-psql -- -c "select 1"
	@bash scripts/db.sh psql

db-reset: ## DESTROY the dev database and recreate it (refuses unless SIERX_ENV=dev)
	@bash scripts/db.sh reset

db-pin: ## Resolve the postgres:18 digest and write it into the Quadlet unit (needs registry access)
	@bash scripts/db.sh pin

migrate-up: ## Apply pending migrations (goose, plain SQL) (task 0.3)
	@bash scripts/migrate.sh up

migrate-down: ## Roll back the most recent migration
	@bash scripts/migrate.sh down

migrate-status: ## Show migration status
	@bash scripts/migrate.sh status

migrate-updown-up: ## up -> down to zero -> up, asserting clean at each step
	@bash scripts/migrate.sh updown-up

schema-snapshot: ## Dump the live schema to docs/schema.sql (deliberate, human-run) (task 0.4)
	@bash scripts/schema.sh snapshot

schema-diff: ## Migrate a scratch DB from zero and diff it against docs/schema.sql
	@bash scripts/schema.sh diff

test-sql: ## Database-level invariants raise on every forbidden operation (task 0.5)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/psql.sh -f test/sql/invariants_test.sql

test-partitions: ## Partition maintenance is idempotent and next month exists (task 0.6)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/psql.sh -f test/sql/partitions_test.sql

sqlc-gen: ## Regenerate internal/store/gen from the migrations and queries (task 0.7)
	@bash scripts/sqlc.sh gen

sqlc-diff: ## Fail if the checked-in generated code differs from fresh output
	@bash scripts/sqlc.sh diff

gate-nodirect: ## Governed tables written only through internal/store (task 0.8)
	@bash scripts/gate-nodirect.sh

prove-nodirect: ## Plant direct writes in a scratch copy and assert the gate goes red
	@bash scripts/gate-nodirect.sh --prove

test-store: ## store.Mutate unit-of-work tests against the dev database (task 0.8)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@go test ./internal/store/... -count=1

seed: ## Build a 10k-item, 6-deep, 5-project workspace (deterministic) (task 0.9)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@go run ./cmd/sierxctl seed $(SEED_ARGS)

seed-determinism: ## Seed twice with the same --seed into fresh databases and compare checksums
	@bash scripts/seed-determinism.sh

rollup-verify: ## ADR-005 control 2: recompute every rollup and report disagreements
	@go run ./cmd/sierxctl rollup --verify

gate-license: ## Every dependency on the §15.1 license allowlist (task 0.13)
	@bash scripts/licenses.sh check

prove-license: ## Plant AGPL/MPL/SSPL/BSL/unknown dependencies and assert the gate goes red
	@bash scripts/licenses.sh --prove

vendor-verify: ## go mod verify plus a check that vendor/ matches go.mod
	@go mod verify
	@go mod vendor
	@git diff --exit-code --stat vendor/ go.mod go.sum \
	  || { echo "vendor/ is out of date — commit the result of go mod vendor" >&2; exit 1; }
	@echo "vendor-verify: OK"

test-property: ## Randomized invariant tests: rollups, paths, ranks (task 0.10)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@go test ./test/property/... -count=1 -timeout 20m

backup-conformance: ## Run every configured backup driver through the shared assertion set (task 0.11)
	@bash scripts/backup/conformance.sh

restore-test: ## Restore the latest backup into a scratch database, rotating drivers (§14.2)
	@go run ./cmd/sierxctl restore-test

gate-nobackupleak: ## No backup tool named outside the drivers (ADR-017)
	@bash scripts/gate-nobackupleak.sh

prove-nobackupleak: ## Plant tool names outside the drivers and assert the gate goes red
	@bash scripts/gate-nobackupleak.sh --prove
