#!/usr/bin/env bash
# Claude Code sessions only — not part of QueryBook and never shipped in QueryBook.zip.
# Makes the code knowledge graph (graphify-out/graph.json) ready at the start of a session:
# installs graphify if missing, refreshes .graphifyignore, and builds the graph (local AST only, ~20 s, no API cost).
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
export PATH="$HOME/.local/bin:$PATH"
if ! command -v graphify >/dev/null 2>&1; then
  command -v uv >/dev/null 2>&1 && uv tool install -q graphifyy==0.9.105 >/dev/null 2>&1
fi
command -v graphify >/dev/null 2>&1 || { echo "graphify not installed (uv tool install graphifyy==0.9.105) — search the code directly this session."; exit 0; }
python3 .claude/graphify/ignore.py >/dev/null 2>&1
if [ ! -f graphify-out/graph.json ]; then
  graphify extract . --code-only >/dev/null 2>&1 && graphify cluster-only . >/dev/null 2>&1
fi
if [ -f graphify-out/graph.json ]; then
  echo "Code graph ready: graphify query \"<question>\" | graphify explain \"<name>\" | graphify path \"<A>\" \"<B>\" (see CLAUDE.md, graphify section)."
fi
exit 0
