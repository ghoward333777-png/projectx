#!/usr/bin/env python3
"""Claude Code sessions only — not part of QueryBook. Writes the repository's .graphifyignore so Graphify (the code
knowledge graph in graphify-out/) indexes each file once: the synced copies of the QueryBook core in every application
and the shell, and bulk data, are left out. The list follows FILES in querybook-one/apps/tools/sync_core.py (read, not
changed). Run: python3 .claude/graphify/ignore.py  (the session-start rebuild runs it)."""
import importlib.util, os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("sync_core", os.path.join(REPO, "querybook-one", "apps", "tools", "sync_core.py"))
_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sync)
APPS, FILES, ROOT = _sync.APPS, _sync.FILES, _sync.ROOT


def write_graphifyignore():
    """Graphify (the code knowledge graph, graphify-out/) indexes each file once: the synced copies of the core in every
    application and the shell, and bulk data (book texts, vendored libraries, bundles), are left out — regenerated here
    so the list follows FILES."""
    repo = REPO
    path = os.path.join(repo, ".graphifyignore")
    head = ["# Graphify ignore list (gitignore syntax). The block between the markers is written by",
            "# .claude/graphify/ignore.py (from sync_core.py FILES); edit the lines above or below it by hand.", ""]
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read().split("\n")
    except OSError:
        old = head + ["# bulk data and generated output",
                      "querybook-one/downloads/", "querybook-one/dist/", "**/vendor/", "**/translate/packs/", "**/library/**/*.gz",
                      "**/avatars_starter/", "**/.lake/", "**/target/", "**/node_modules/", "graphify-out/cache/", "*.min.js", "*.wasm", "*.dll", ""]
    start, end = "# >>> synced copies (.claude/graphify/ignore.py)", "# <<< synced copies"
    block = [start]
    for app in APPS:
        for src, dst in FILES:
            block.append("querybook-one/apps/%s/%s" % (app, dst.replace(os.sep, "/")))
        if app == "video":
            block += ["querybook-one/apps/video/%s" % t for t in ("hybrid_video.py", "qbframes.py", "reuse_bench.py", "generate_exemplars.py")]
    block += ["querybook-one/apps/shell/%s" % f for f in ("bookq.py", "qbcompose.py", "qbbooks.py")]
    block.append(end)
    if start in old and end in old:
        lines = old[:old.index(start)] + block + old[old.index(end) + 1:]
    else:
        lines = old + [""] + block + [""]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


if __name__ == "__main__":
    write_graphifyignore()
    print("wrote .graphifyignore")
