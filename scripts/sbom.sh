#!/usr/bin/env bash
# sbom.sh — generate a CycloneDX 1.5 SBOM for the release (BUILD task 0.13).
#   sbom.sh [output-path]     write the SBOM (default: dist/sbom.cdx.json)
#   sbom.sh --check <path>    fail if <path> is missing, malformed, or lists a
#                             component set that differs from a fresh run
#
# Why not `anchore/sbom-action` or another CI action: BUILD §3.4 — nothing may
# live only in CI YAML. An SBOM produced by an action cannot be generated,
# inspected or diffed on a laptop, which makes it an artifact nobody checks.
# This reads the same inputs the license gate reads — vendor/modules.txt for
# the module set, go.sum for the module hashes, the vendored LICENSE files for
# the licence — so the SBOM and gate-license can never disagree about what is
# in the build.
#
# The npm side arrives with the frontend tree at task 2.1; this reports its
# absence rather than implying the SBOM is complete.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

OUT=${1:-dist/sbom.cdx.json}
[[ ${1:-} == --check ]] && OUT=${2:-}

die() { echo "sbom: $*" >&2; exit 1; }

[[ -f vendor/modules.txt ]] || die "no vendor/ directory — run: go mod vendor"

# Use the exact same classifier, allowlist and dual-license resolutions.
source scripts/licenses.sh --library
load_allowlist

generate() {
  local target=$1
  (cd web && node scripts/licenses.mjs)
  mkdir -p "$(dirname "$target")"

  local version
  version=$(git describe --tags --always --dirty 2>/dev/null || echo unknown)
  local commit
  commit=$(git rev-parse --verify HEAD 2>/dev/null || echo unknown)

  # Collect module name, version, licence and go.sum hash into a TSV that
  # python turns into JSON. Keeping the parsing in shell and the serialising in
  # python avoids hand-rolling JSON escaping.
  local tsv
  tsv=$(mktemp); trap "rm -f '$tsv'" RETURN

  local mod ver lic lf h1
  while read -r mod; do
    [[ -z $mod ]] && continue
    ver=$(awk -v m="$mod" '$1=="#" && $2==m {print $3; exit}' vendor/modules.txt)
    [[ -z $ver ]] && ver=unknown
    lf=$(find_license_file "vendor/$mod" || true)
    if [[ -n $lf ]]; then lic=$(classify "$lf"); else lic=UNKNOWN; fi
    lic=${RESOLVED[$mod]:-$lic}
    in_list "$lic" "${ALLOWED[@]}" || die "module license is missing or not allowed: $mod"
    # go.sum records a base64 dirhash, NOT a hex digest of a file, so it is
    # reported as a property rather than as a CycloneDX hash — claiming
    # alg SHA-256 for it would be wrong.
    h1=$(awk -v m="$mod" -v v="$ver" '$1==m && $2==v {print $3; exit}' go.sum 2>/dev/null || true)
    [[ -n $h1 ]] || die "module hash missing from go.sum: $mod"
    printf '%s\t%s\t%s\t%s\n' "$mod" "$ver" "$lic" "${h1:-}" >> "$tsv"
  done < <(awk '/^# /{print $2}' vendor/modules.txt | sort -u)

  local goversion
  goversion=$(awk '$1=="go"{print $2; exit}' go.mod)

  SBOM_VERSION=$version SBOM_COMMIT=$commit SBOM_GO=$goversion \
  python3 - "$tsv" "$target" <<'PY'
import json, os, sys, uuid, datetime

tsv, target = sys.argv[1], sys.argv[2]
components = []
with open(tsv) as f:
    for line in f:
        name, version, lic, h1 = (line.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
        if not name:
            continue
        comp = {
            "type": "library",
            "bom-ref": f"pkg:golang/{name}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:golang/{name}@{version}",
            "scope": "required",
        }
        if lic and lic != "UNKNOWN":
            comp["licenses"] = [{"license": {"id": lic}}]
        if h1:
            # Honest naming: this is Go's module dirhash, not a file digest.
            comp["properties"] = [{"name": "go:mod:h1", "value": h1}]
        components.append(comp)

from urllib.parse import quote
with open("web/package-lock.json") as f:
    lock = json.load(f)
with open("web/licenses.json") as f:
    license_evidence = json.load(f)
resolutions = {}
with open('.licenses-allowlist') as f:
    for line in f:
        if line.startswith('resolve npm:'):
            _,name,license,*_ = line.split()
            resolutions[name[4:]] = license
for path, package in lock["packages"].items():
    if not path:
        continue
    name = path.rsplit("node_modules/", 1)[-1]
    purl = f"pkg:npm/{quote(name, safe='/')}@{package['version']}"
    components.append({"type": "library", "bom-ref": purl + "#" + path,
        "name": name, "version": package["version"], "purl": purl,
        "scope": "optional" if package.get("dev") or package.get("optional") else "required",
        "licenses": [{"expression": resolutions.get(f"{name}@{package['version']}", package.get("license") or license_evidence[f"{name}@{package['version']}"]["license"])}],
        "properties": [{"name": "npm:integrity", "value": package["integrity"]},
                       {"name": "npm:resolved", "value": package["resolved"]}]})

bom = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "serialNumber": "urn:uuid:" + str(uuid.uuid4()),
    "version": 1,
    "metadata": {
        "timestamp": datetime.datetime.now(datetime.timezone.utc)
                      .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tools": [{"vendor": "sierx", "name": "scripts/sbom.sh", "version": "1"}],
        "component": {
            "type": "application",
            "bom-ref": "pkg:golang/github.com/siercks/sierx",
            "name": "sierx",
            "version": os.environ.get("SBOM_VERSION", "unknown"),
            "licenses": [{"license": {"id": "Apache-2.0"}}],
            "properties": [
                {"name": "vcs:commit", "value": os.environ.get("SBOM_COMMIT", "unknown")},
                {"name": "go:toolchain", "value": os.environ.get("SBOM_GO", "unknown")},
            ],
        },
    },
    "components": sorted(components, key=lambda c: c["name"]),
}
with open(target, "w") as f:
    json.dump(bom, f, indent=2, sort_keys=False)
    f.write("\n")
print(f"sbom: wrote {target} ({len(components)} Go and npm component(s))")
PY


}

case ${1:-} in
  --check)
    [[ -n ${2:-} ]] || die "usage: $0 --check <path>"
    [[ -f $2 ]] || die "$2 does not exist"
    tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
    generate "$tmp/fresh.json" >/dev/null
    python3 scripts/sbom_check.py "$2" "$tmp/fresh.json"
    ;;
  *) generate "$OUT" ;;
esac
