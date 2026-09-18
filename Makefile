# sierx — every gate and every CI step lives here (BUILD §3.4).
# CI YAML may only call these targets; a human can run each one locally and offline.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: test-api
test-api: ## API tests; filter with TEST_ARGS='-run TestServerBoot'
	@bash scripts/test-go.sh ./internal/api/... ./internal/config/... $(TEST_ARGS) -count=1

.PHONY: gen-fields gate-gen prove-gen
gen-fields: ## Generate client fields from the API registry
	@go run ./internal/api/projection/cmd/genfields
gate-gen: ## Assert generated API fields have not drifted
	@bash scripts/gate-gen.sh
prove-gen: ## Prove generated field drift is rejected
	@bash scripts/gate-gen.sh --prove

.PHONY: help bootstrap-check gate-notopology prove-notopology \
        db-up db-down db-psql db-reset db-pin \
        migrate-up migrate-down migrate-status migrate-updown-up \
        schema-snapshot schema-diff test-sql test-partitions \
        sqlc-gen sqlc-diff gate-nodirect prove-nodirect test-store \
        seed seed-determinism rollup-verify \
        gate-license prove-license vendor-verify test-property \
        backup-conformance restore-test gate-nobackupleak prove-nobackupleak \
        bench-smoke bench-baseline gate-bench \
        gate-0 prove-gates ci-local

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

# The dev loop. NOT a gate and deliberately not part of one: it runs the checks
# that catch a mistake in seconds and skips the ones measured in minutes
# (property tests, seed determinism, backup conformance, benchmarks). Run
# `make gate-0` before asking for sign-off — `check` passing is not a claim
# that the phase gate passes.
check: ## Fast dev loop: vet, SQL invariants, store tests, generated-code and source gates
	@bash test/shell/test-go_test.sh
	@bash test/shell/ci-local_test.sh
	@python3 -m unittest discover -s test/python -p "test_*.py"
	@go vet ./...
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/psql.sh -f test/sql/invariants_test.sql
	@bash scripts/psql.sh -f test/sql/partitions_test.sql
	@bash scripts/sqlc.sh diff
	@bash scripts/test-go.sh ./internal/... -count=1
	@bash scripts/gate-nodirect.sh
	@bash scripts/gate-notopology.sh
	@bash scripts/gate-nobackupleak.sh
	@echo "check: OK (fast loop; run make gate-0 for the phase gate)"

sierxctl: ## Build bin/sierxctl (the make targets and scripts use it instead of go run)
	@bash scripts/sierxctl.sh --help >/dev/null 2>&1 || true
	@ls -l bin/sierxctl

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

.PHONY: test-sxq fuzz-sxq
.PHONY: test-concurrency
test-concurrency: ## Concurrent API writers plus delta poller, including a 200-item transaction
	@bash scripts/test-go.sh ./test/concurrency/... -race -count=1 -timeout=5m

test-sxq: ## Query grammar and normalized SQL golden corpus
	@go test ./internal/sxq -count=1

fuzz-sxq: ## Bounded fuzz run for parser safety and literal parameter binding
	@go test ./internal/sxq -run '^$$' -fuzz '^FuzzCompile$$' -fuzztime=5s -parallel=2

test-store: ## store.Mutate unit-of-work tests against the dev database (task 0.8)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/test-go.sh ./internal/store/... -count=1

seed: ## Build a 10k-item, 6-deep, 5-project workspace (deterministic) (task 0.9)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/sierxctl.sh seed $(SEED_ARGS)

seed-determinism: ## Seed twice with the same --seed into fresh databases and compare checksums
	@bash scripts/seed-determinism.sh

rollup-verify: ## ADR-005 control 2: recompute every rollup and report disagreements
	@bash scripts/sierxctl.sh rollup --verify

gate-license: ## Every dependency on the §15.1 license allowlist (task 0.13)
	@bash scripts/licenses.sh check

prove-license: ## Plant AGPL/MPL/SSPL/BSL/unknown dependencies and assert the gate goes red
	@bash scripts/licenses.sh --prove

vendor-verify: ## go mod verify plus a check that vendor/ matches go.mod
	@bash test/shell/vendor-verify_test.sh
	@bash scripts/vendor-verify.sh

test-property: ## Randomized invariant tests: rollups, paths, ranks (task 0.10)
	@bash scripts/migrate.sh up >/dev/null 2>&1
	@bash scripts/test-go.sh ./test/property/... -count=1 -timeout 20m

backup-conformance: ## Run every configured backup driver through the shared assertion set (task 0.11)
	@bash scripts/backup/conformance.sh

restore-test: ## Restore the latest backup into a scratch database, rotating drivers (§14.2)
	@bash scripts/sierxctl.sh restore-test

gate-nobackupleak: ## No backup tool named outside the drivers (ADR-017)
	@bash scripts/gate-nobackupleak.sh

prove-nobackupleak: ## Plant tool names outside the drivers and assert the gate goes red
	@bash scripts/gate-nobackupleak.sh --prove

bench-smoke: ## Run every §12 scenario once, assert none errors, name the skips (ADR-016)
	@bash scripts/bench.sh smoke

bench-baseline: ## Capture reference-hardware numbers into test/bench/baseline.json
	@bash scripts/bench.sh baseline

gate-bench: ## Assert the §12 thresholds against the baseline (reference hardware only)
	@bash scripts/bench.sh gate

# gate-0 is the phase gate. CI runs exactly this target and nothing else
# (§3.4), so anything that must hold before phase 1 belongs here, in this
# order: cheap checks first, so a broken toolchain fails in seconds rather
# than after the benchmarks.
gate-0: ## The phase-0 gate: every check that must pass before phase 1
	@bash test/shell/test-go_test.sh
	@bash test/shell/ci-local_test.sh
	@python3 -m unittest discover -s test/python -p "test_*.py"
	@bash scripts/bootstrap-check.sh
	@bash scripts/migrate.sh updown-up
	@bash scripts/schema.sh diff
	@bash scripts/psql.sh -f test/sql/invariants_test.sql
	@bash scripts/psql.sh -f test/sql/partitions_test.sql
	@bash scripts/sqlc.sh diff
	@go vet ./...
	@bash scripts/test-go.sh ./... -count=1 -timeout 20m
	@bash scripts/licenses.sh check
	@$(MAKE) --no-print-directory sbom sbom-check
	@$(MAKE) --no-print-directory vendor-verify
	@bash scripts/gate-nodirect.sh
	@bash scripts/gate-notopology.sh
	@bash scripts/gate-nobackupleak.sh
	@$(MAKE) --no-print-directory seed-determinism
# Seed BEFORE conformance and bench. migrate.sh updown-up leaves the schema at
# zero rows, so without this the restore comparison compares nothing against
# nothing and every benchmark scenario skips for want of data — both reported
# OK. A gate that passes on an empty database is not asserting what it claims.
	@$(MAKE) --no-print-directory seed
	@bash scripts/backup/conformance.sh
	@bash scripts/bench.sh smoke
	@GOOS=linux GOARCH=amd64 go build -trimpath -o /dev/null ./cmd/...
	@GOOS=linux GOARCH=arm64 go build -trimpath -o /dev/null ./cmd/...
	@bash scripts/prove-gates.sh
	@echo "gate-0: GREEN"

prove-gates: ## Every gate-* target in the Makefile has a proof, and it passes (task 0.12)
	@bash scripts/prove-gates.sh

ci-local: ## Run gate-0 the way CI does, in a container, offline
	@bash scripts/ci-local.sh run

sbom: ## Generate the release SBOM (CycloneDX 1.5) from vendor/ and go.sum (task 0.13)
	@bash scripts/sbom.sh "$(or $(SBOM_OUT),dist/sbom.cdx.json)"

sbom-check: ## Validate the generated SBOM format and all stable inventory/build fields
	@bash scripts/sbom.sh --check "$(or $(SBOM_OUT),dist/sbom.cdx.json)"

.PHONY: ci-local-prepare sbom sbom-check check
ci-local-prepare: ## Prepare the local CI container and caches while online
	@bash scripts/ci-local.sh prepare
