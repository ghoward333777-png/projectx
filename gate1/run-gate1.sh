#!/usr/bin/env bash
# Gate 1 — one command. Runs the engine/covenant/phase/agent harness (N runs,
# flake-free + deterministic) then the UI-render check (zero JS errors).
# Exit 0 iff both are GREEN. The UI check reports SKIP (not fail) if this
# environment has no Node Playwright browser.
set -uo pipefail
cd "$(dirname "$0")"
RUNS="${1:-3}"

echo "############################################################"
echo "# QueryBook Gate 1 — full suite (engine x${RUNS} + UI render)"
echo "############################################################"

python3 qb_gate1_harness.py -n "$RUNS"
ENGINE=$?

echo
python3 qb_gate1_ui.py
UI=$?

echo
echo "############################################################"
if [ "$ENGINE" -eq 0 ] && { [ "$UI" -eq 0 ] || [ "$UI" -eq 2 ]; }; then
  [ "$UI" -eq 2 ] && echo "# GATE 1: ENGINE GREEN ✓   UI SKIPPED (no browser here)"
  [ "$UI" -eq 0 ] && echo "# GATE 1: GREEN ✓  (engine + UI)"
  echo "############################################################"
  exit 0
fi
echo "# GATE 1: RED ✗   (engine rc=$ENGINE, ui rc=$UI)"
echo "############################################################"
exit 1
