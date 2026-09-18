#!/usr/bin/env bash
# prove-gates.sh — every gate is proven to fail when violated (BUILD task 0.12).
# An unproven gate is not a gate.
#
# Scope rule (task 0.12 step 4): gates are DISCOVERED FROM THE MAKEFILE, not
# from a list here, and a `gate-*` target with no corresponding proof fails this
# script. That makes "add a gate, add its proof" a build failure rather than a
# convention, and it is why phase 2's gates need no anticipating: they will be
# discovered when they exist.
#
# The proof convention: for `gate-x`, either
#   - `scripts/gate-x.sh --prove` exists (the content gates), or
#   - a `prove-x` Makefile target exists, or
#   - `gate-x` appears in EXEMPT below, with its reason.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Exemptions, each with the reason it cannot be proven by planting a violation.
# This list is the only place a gate escapes a proof, and every entry is a
# claim someone can argue with.
declare -A EXEMPT=(
  [gate-0]="composite: runs the other gates, so its failure modes are theirs. Proving it would mean proving each again."
  [gate-1]="composite: runs gate-0 plus endpoint goldens, fuzzing, race checks, generation and curl smoke; their assertions define its failures."
  [gate-bench]="advisory by ADR-016 until reference hardware exists at task 2.16. Its one testable behaviour — exiting nonzero with no baseline — is asserted below rather than by planting a violation."
)

# discover_gates -> every gate-* target declared in the Makefile
discover_gates() {
  grep -oE '^gate-[a-z0-9-]+:' Makefile | tr -d ':' | sort -u
}

has_prove_target() {
  grep -qE "^prove-${1#gate-}:" Makefile
}

has_prove_script() {
  [[ -f "scripts/$1.sh" ]] && grep -q -- '--prove' "scripts/$1.sh"
}

missing=0
proven=0
exempted=0
failed=0

echo "=== discovering gates from the Makefile"
gates=$(discover_gates)
[[ -n $gates ]] || { echo "prove-gates: no gate-* targets found in the Makefile" >&2; exit 1; }
printf '  %s\n' $gates

for gate in $gates; do
  echo
  echo "=== $gate"
  if [[ -n ${EXEMPT[$gate]:-} ]]; then
    echo "  exempt: ${EXEMPT[$gate]}"
    exempted=$((exempted + 1))
    continue
  fi

  if has_prove_script "$gate"; then
    echo "  proof: scripts/$gate.sh --prove"
    if bash "scripts/$gate.sh" --prove; then
      proven=$((proven + 1))
    else
      echo "  PROOF FAILED for $gate"
      failed=$((failed + 1))
    fi
  elif has_prove_target "$gate"; then
    echo "  proof: make prove-${gate#gate-}"
    if make -s "prove-${gate#gate-}"; then
      proven=$((proven + 1))
    else
      echo "  PROOF FAILED for $gate"
      failed=$((failed + 1))
    fi
  else
    echo "  NO PROOF: add scripts/$gate.sh --prove, or a prove-${gate#gate-} target,"
    echo "            or an entry in prove-gates.sh's EXEMPT list with a reason."
    missing=$((missing + 1))
  fi
done

# gate-bench's one testable behaviour, per its exemption above.
echo
echo "=== gate-bench: asserting it refuses to pass without a baseline"
if [[ -f test/bench/baseline.json ]]; then
  echo "  a baseline exists, so this assertion does not apply on this host"
else
  if make -s gate-bench >/dev/null 2>&1; then
    echo "  gate-bench exited 0 with no baseline — it should refuse (ADR-016)"
    failed=$((failed + 1))
  else
    echo "  gate-bench exits nonzero with no baseline — OK"
    proven=$((proven + 1))
  fi
fi

echo
echo "prove-gates: $proven proven, $exempted exempt, $missing without a proof, $failed proof failures"
if [[ $missing -gt 0 || $failed -gt 0 ]]; then
  exit 1
fi
echo "prove-gates: OK"
