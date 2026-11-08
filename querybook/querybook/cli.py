"""QueryBook command line. Same commands on Windows (py -m querybook …) and
macOS (python3 -m querybook …)."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from querybook import __version__
from querybook.apps import ALL_APPS, build_apps
from querybook.apps.base import QueryContext
from querybook.config import DEFAULT_PORTS, paths
from querybook.core.fql import run_fql
from querybook.core.store import FQLStore
from querybook.ingest import FolderSource, Harvester, IngestPipeline
from querybook.ingest.sources import parse_file

SAMPLES = Path(__file__).resolve().parent / "samples"


class Runtime:
    def __init__(self, home: str | None):
        self.paths = paths(home)
        self.store = FQLStore(self.paths.db)
        self.all_apps = build_apps()  # enrichment for every domain, always
        self.pipeline = IngestPipeline(self.store, self.all_apps)

    def harvester(self) -> Harvester:
        sources = [(FolderSource(self.paths.inbox), 1.0)]
        st = self.paths.settings
        for folder in st.watch_folders:  # existing stores, read-only
            sources.append((FolderSource(folder, name=f"watch:{folder}"), st.watch_interval))
        return Harvester(self.pipeline, sources)

    def seed(self) -> dict[str, int]:
        counts = {"added": 0, "duplicate": 0, "rejected": 0}
        for f in sorted(SAMPLES.glob("*.json")):
            for item in parse_file(f, source=f"sample:{f.name}", domain=f.stem if f.stem in ALL_APPS else None):
                counts[self.pipeline.ingest(item).status] += 1
        return counts


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _serve(rt: Runtime, args, apps: dict, mode: str, port: int) -> int:
    from querybook.server import QueryBookServer

    if not args.no_seed and not any(rt.store.count(a.collection) for a in rt.all_apps.values()):
        print("First run: loading the sample library…", rt.seed())
    harvester = None if args.no_harvest else rt.harvester().start()
    server = QueryBookServer(rt.store, apps, rt.pipeline, renders_dir=rt.paths.renders, harvester=harvester,
                             host=args.host, port=port, mode=mode)
    print(f"QueryBook {__version__} — {', '.join(a.title for a in apps.values())}")
    print(f"  open      {server.url}")
    print(f"  database  {rt.paths.db}")
    if harvester:
        print(f"  inbox     {rt.paths.inbox}  (drop .txt/.md/.json/.csv files; subfolders pick the domain)")
        for folder in rt.paths.settings.watch_folders:
            print(f"  watching  {folder}" + ("" if folder.is_dir() else "   (not found — check querybook.ini)"))
    print("  Ctrl+C to stop")
    if args.open:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if harvester:
            harvester.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="querybook", description="QueryBook — four domain apps on one FQL database.")
    p.add_argument("--home", help="data folder (default: per-OS app data folder, or $QUERYBOOK_HOME)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def server_flags(sp, port):
        sp.add_argument("--host", default="127.0.0.1")
        sp.add_argument("--port", type=int, default=port)
        sp.add_argument("--no-harvest", action="store_true", help="do not run the harvester in this process")
        sp.add_argument("--no-seed", action="store_true", help="do not load samples into an empty database")
        sp.add_argument("--open", action="store_true", help="open the browser")

    sp = sub.add_parser("serve", help="run the hub with every app (or --apps a,b)")
    server_flags(sp, DEFAULT_PORTS["hub"])
    sp.add_argument("--apps", default=",".join(ALL_APPS))
    sp = sub.add_parser("app", help="run ONE app standalone on its own port (shares the database)")
    sp.add_argument("domain", choices=list(ALL_APPS))
    server_flags(sp, 0)
    sp = sub.add_parser("harvest", help="run only the harvester (continuous unless --once)")
    sp.add_argument("--once", action="store_true")
    sp = sub.add_parser("ingest", help="ingest files or folders now")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--domain", choices=list(ALL_APPS))
    sub.add_parser("seed", help="load the bundled sample library")
    sp = sub.add_parser("fql", help="run an FQL query")
    sp.add_argument("query")
    sp.add_argument("--write", action="store_true", help="allow create/update/delete")
    sp = sub.add_parser("ask", help="ask one app a question and print its domain-shaped answer")
    sp.add_argument("domain", choices=list(ALL_APPS))
    sp.add_argument("question")
    sub.add_parser("info", help="show data paths and collection counts")
    args = p.parse_args(argv)
    rt = Runtime(args.home)

    if args.cmd == "serve":
        keys = [k.strip() for k in args.apps.split(",") if k.strip()]
        return _serve(rt, args, build_apps(keys), "hub", args.port)
    if args.cmd == "app":
        return _serve(rt, args, build_apps([args.domain]), args.domain, args.port or DEFAULT_PORTS[args.domain])
    if args.cmd == "harvest":
        h = rt.harvester()
        if args.once:
            _print(h.run_once())
            return 0
        print(f"Harvesting {rt.paths.inbox} and Source feeds into {rt.paths.db}. Ctrl+C to stop.")
        h.start()
        try:
            while True:
                h._stop.wait(5)
        except KeyboardInterrupt:
            h.stop()
        return 0
    if args.cmd == "ingest":
        results = []
        for raw in args.paths:
            root = Path(raw)
            files = sorted(f for f in root.rglob("*") if f.is_file()) if root.is_dir() else [root]
            for f in files:
                try:
                    items = parse_file(f, source=f"cli:{f.name}", domain=args.domain)
                except (ValueError, OSError) as exc:
                    results.append({"file": str(f), "status": "rejected", "reason": str(exc)})
                    continue
                results += [{"file": str(f), **rt.pipeline.ingest(it).to_json()} for it in items]
        _print(results)
        return 0
    if args.cmd == "seed":
        _print(rt.seed())
        return 0
    if args.cmd == "fql":
        res = run_fql(rt.store, args.query, readonly=not args.write)
        _print(res)
        return 0 if res["ok"] else 1
    if args.cmd == "ask":
        app = rt.all_apps[args.domain]
        _print(app.answer(args.question, QueryContext(rt.store, rt.paths.renders)))
        return 0
    if args.cmd == "info":
        _print({"version": __version__, "home": str(rt.paths.home), "database": str(rt.paths.db),
                "inbox": str(rt.paths.inbox), "renders": str(rt.paths.renders), "fts5": rt.store.fts,
                "settings_file": str(rt.paths.settings.source) if rt.paths.settings.source else None,
                "watch_folders": [str(f) for f in rt.paths.settings.watch_folders],
                "collections": rt.store.collections(), "python": sys.version.split()[0]})
        return 0
    return 2
