# sierx — every gate and every CI step lives here (BUILD §3.4).
# CI YAML may only call these targets; a human can run each one locally and offline.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help bootstrap-check gate-notopology prove-notopology

help: ## List targets
	@awk 'BEGIN{FS=":.*## "} /^[A-Za-z0-9_-]+:.*## /{printf "  %-20s %s\n",$$1,$$2}' $(MAKEFILE_LIST)

bootstrap-check: ## Toolchain versions match the pins; required inputs present (task 0.1)
	@bash scripts/bootstrap-check.sh

gate-notopology: ## No real hostnames, addresses, or .env values in committable files (BUILD §3.7)
	@bash scripts/gate-notopology.sh

prove-notopology: ## Plant each topology violation in a scratch copy and assert the gate goes red
	@bash scripts/gate-notopology.sh --prove
