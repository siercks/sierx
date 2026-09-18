#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
[[ -n ${DATABASE_URL:-} ]] || { echo 'smoke-api: DATABASE_URL required' >&2; exit 1; }
name="sierx_smoke_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
createdb --maintenance-db="$DATABASE_URL" "$name"
trap 'dropdb --maintenance-db="$DATABASE_URL" --if-exists "$name"' EXIT
scratch_url=$(python3 - "$DATABASE_URL" "$name" <<'PY'
import sys, urllib.parse
url = urllib.parse.urlsplit(sys.argv[1])
print(urllib.parse.urlunsplit(url._replace(path="/" + sys.argv[2])))
PY
)
source scripts/tool.sh
"$(tool_path goose)" -dir migrations postgres "$scratch_url" up
go build -o bin/sierx ./cmd/sierx
go build -o bin/sierxctl ./cmd/sierxctl
DATABASE_URL="$scratch_url" python3 test/smoke/api.py
