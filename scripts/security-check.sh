#!/usr/bin/env bash
# Online security checks are intentionally separate from the offline phase gate.
# Versioned Go installs leave the application's module/vendor inventory unchanged.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export GOBIN="$PWD/bin/security-tools"
mkdir -p "$GOBIN"
case ${1:-} in
  workflows)
    command -v shellcheck >/dev/null || { echo 'Install ShellCheck before running check-workflows.' >&2; exit 1; }
    go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
    "$GOBIN/actionlint" -color=false
    ;;
  vulnerabilities)
    go install golang.org/x/vuln/cmd/govulncheck@v1.8.0
    "$GOBIN/govulncheck" ./...
    ;;
  *) echo 'usage: security-check.sh workflows|vulnerabilities' >&2; exit 2 ;;
esac
