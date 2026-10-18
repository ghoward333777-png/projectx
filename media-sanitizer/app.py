#!/usr/bin/env python3
"""Media Sanitizer - strip metadata from your own audio/video and re-export cleanly.

  python3 app.py serve [--host H] [--port P]       web UI + JSON API
  python3 app.py presets                           list presets
  python3 app.py validate                          check config/*.json
  python3 app.py probe FILE                        JSON metadata summary
  python3 app.py inspect PATH [--json]             what identifying data is in a file, and where
  python3 app.py run PATH... [--preset P] [--out DIR] [--report FILE]
  python3 app.py job SPEC.json                     run a JSON job spec
"""

import argparse
import json
import os
import sys

from sanitizer.config import ConfigError, load_presets, load_settings
from sanitizer.engine import describe, sanitize
from sanitizer.inspect import inspect
from sanitizer.files import collect_media
from sanitizer.probe import probe


def run_batch(paths, preset, out_dir, settings, presets, recursive=True):
    if preset not in presets:
        raise SystemExit(f"Unknown preset '{preset}'. Try: {', '.join(presets)}")
    files = collect_media(paths, settings, recursive)
    if not files:
        raise SystemExit("No media files found.")
    results = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path}", file=sys.stderr)
        try:
            report = sanitize(path, out_dir, preset, presets, settings)
            print(f"    -> {report['output']}  ({report['verdict']})", file=sys.stderr)
            results.append({"input": path, "status": "done", "report": report})
        except Exception as exc:
            print(f"    !! {exc}", file=sys.stderr)
            results.append({"input": path, "status": "failed", "error": str(exc)})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Strip metadata from audio/video files.")
    parser.add_argument("--settings", help="alternate settings.json")
    parser.add_argument("--presets", help="alternate presets.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="start the local web UI / JSON API")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    sub.add_parser("presets", help="list presets")
    sub.add_parser("validate", help="validate config files")
    p = sub.add_parser("probe", help="print a file's metadata as JSON")
    p.add_argument("file")
    p = sub.add_parser("inspect", help="report metadata, provenance, encoder strings and overlays with locations")
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true", help="full JSON instead of a summary")
    p = sub.add_parser("run", help="sanitize files and/or folders")
    p.add_argument("paths", nargs="+")
    p.add_argument("--preset")
    p.add_argument("--out")
    p.add_argument("--no-recursive", action="store_true")
    p.add_argument("--report", help="write the JSON results here (default: stdout)")
    p = sub.add_parser("job", help="run a JSON job spec")
    p.add_argument("spec")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.settings)
        presets = load_presets(args.presets)
    except ConfigError as exc:
        raise SystemExit(f"Config error: {exc}")

    if args.command == "validate":
        print(f"OK: {len(presets)} presets valid ({', '.join(presets)})")
    elif args.command == "presets":
        for name, cfg in presets.items():
            print(f"{name:20} {cfg['description']}")
    elif args.command == "probe":
        print(json.dumps(probe(args.file, settings["ffprobe"]), indent=2))
    elif args.command == "inspect":
        results = []
        for path in collect_media(args.paths, settings):
            result = dict(inspect(path, probe(path, settings["ffprobe"]), settings), path=path)
            results.append(result)
            if not args.json:
                print(path)
                for f in result["findings"]:
                    print("  - " + describe(f))
                if not result["findings"]:
                    print("  nothing found")
                print(f"  overlay check: {result['overlay_check']}")
        if args.json:
            print(json.dumps({"inspections": results}, indent=2))
        else:
            print("\nNot checkable from the file alone:")
            for line in results[0]["not_checked"] if results else []:
                print("  * " + line)
    elif args.command == "serve":
        from sanitizer.server import serve
        httpd, _ = serve(settings, presets, args.host, args.port)
        host, port = httpd.server_address[:2]
        print(f"Media Sanitizer running at http://{host}:{port}  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.server_close()
    else:
        if args.command == "job":
            with open(args.spec, encoding="utf-8") as fh:
                spec = json.load(fh)
            paths, preset = spec["inputs"], spec.get("preset")
            out, recursive, report_path = spec.get("output_dir"), spec.get("recursive", True), spec.get("report")
        else:
            paths, preset, out = args.paths, args.preset, args.out
            recursive, report_path = not args.no_recursive, args.report
        results = run_batch(paths, preset or settings["default_preset"],
                            os.path.expanduser(out or settings["default_output_dir"]),
                            settings, presets, recursive)
        payload = json.dumps({"results": results}, indent=2)
        if report_path:
            with open(report_path, "w", encoding="utf-8") as fh:
                fh.write(payload)
            print(f"Report written to {report_path}", file=sys.stderr)
        else:
            print(payload)
        return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
