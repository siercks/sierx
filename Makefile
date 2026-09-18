# sierx — every gate and every CI step lives here (BUILD §3.4).
# CI YAML may only call these targets; a human can run each one locally and offline.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help bootstrap-check gate-notopology prove-notopology \
        db-up db-down db-psql db-reset db-pin

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
