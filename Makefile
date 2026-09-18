# sierx — every gate and every CI step lives here (BUILD §3.4).
# CI YAML may only call these targets; a human can run each one locally and offline.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help bootstrap-check gate-notopology prove-notopology \
        db-up db-down db-psql db-reset db-pin \
        migrate-up migrate-down migrate-status migrate-updown-up \
        schema-snapshot schema-diff test-sql test-partitions

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
