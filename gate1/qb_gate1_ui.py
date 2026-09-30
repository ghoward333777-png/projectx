#!/usr/bin/env python3
"""
qb_gate1_ui.py — Gate 1 UI-render check (zero JS errors).

Boots the REAL frozen-baseline qb_api server against a small throwaway store,
drives a headless Chromium (Node Playwright) over every page route, and fails if
any page emits a JavaScript console error or an uncaught page error. This is the
check that proves the dashboard/Language Lab actually render — the class of
"dead link / blank screen" defect that bit us before Gate 0.

Self-contained: starts and stops the server within this one process, so nothing
is left running between tool calls.

Run:  python qb_gate1_ui.py
Exit: 0 iff every page renders with zero JS errors; non-zero otherwise (2 = env
      missing browser/node — reported as SKIP, not a false failure).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import shutil
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.normpath(os.path.join(HERE, "..", "prototype", "QueryBook-baseline-v9.15"))
NODE_BIN = "/opt/node22/bin/node"
NODE_MODULES = "/opt/node22/lib/node_modules"
ROUTES = ["/dashboard", "/language", "/chat", "/console", "/guide"]

NODE_SCRIPT = r"""
const {chromium} = require('playwright');
(async () => {
  const base = process.argv[2];
  const routes = process.argv.slice(3);
  const browser = await chromium.launch({headless: true});
  const out = [];
  for (const r of routes) {
    const page = await browser.newPage();
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
    page.on('pageerror', e => errors.push('pageerror: ' + (e && e.message ? e.message : String(e))));
    let status = null;
    try {
      const resp = await page.goto(base + r, {waitUntil: 'load', timeout: 20000});
      status = resp ? resp.status() : null;
      await page.waitForTimeout(2500);   // let interval polling fire at least once
    } catch (e) {
      errors.push('navigation: ' + e.message);
    }
    await page.close();
    out.push({route: r, status, errors});
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error('FATAL ' + (e && e.message ? e.message : e)); process.exit(3); });
"""


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _benign(err):
    e = err.lower()
    return "favicon" in e            # a missing favicon is not an app defect


def prepare_store(d):
    """Seed a small store so every page has real data to render (no empty-state noise)."""
    sys.path.insert(0, BASELINE)
    import ufcs_store as store
    import qb_language as lang
    store.harvest_into(d, 3000)                    # facts for the dashboard/console
    text = lang.corpus_chunk(0) + " " + lang.corpus_chunk(1)
    lang.learn(d, text=text)                       # Phase 1 model for the Language Lab
    lang.ground_words(d, lang.learned_words(d, 30))  # Phase 2 groundings


def main():
    if not os.path.exists(NODE_BIN) or not os.path.isdir(os.path.join(NODE_MODULES, "playwright")):
        print("SKIP: Node Playwright not available in this environment.")
        return 2

    tmp = tempfile.mkdtemp(prefix="qb_gate1_ui_")
    store_dir = os.path.join(tmp, "store")
    os.makedirs(store_dir, exist_ok=True)
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    proc = None
    try:
        print("=" * 74)
        print("QueryBook Gate 1 — UI render check (zero JS errors)")
        print("baseline: QueryBook-baseline-v9.15   base: %s" % base)
        print("=" * 74)
        print("  seeding a throwaway store …", flush=True)
        prepare_store(store_dir)

        env = dict(os.environ)
        env["QB_BIND"] = "127.0.0.1:%d" % port
        env["QB_DATA_DIR"] = store_dir
        proc = subprocess.Popen([sys.executable, "qb_api.py"], cwd=BASELINE, env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # wait for the server to answer /api/health
        up = False
        for _ in range(60):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:
                time.sleep(0.5)
        if not up:
            print("  FAIL: server did not come up on %s" % base)
            return 1
        print("  server up; driving Chromium over %d routes …" % len(ROUTES), flush=True)

        env2 = dict(os.environ)
        env2["NODE_PATH"] = NODE_MODULES
        script_path = os.path.join(tmp, "drive.js")
        with open(script_path, "w") as fh:
            fh.write(NODE_SCRIPT)
        cp = subprocess.run([NODE_BIN, script_path, base] + ROUTES,
                            env=env2, capture_output=True, text=True, timeout=180)
        if cp.returncode != 0:
            print("  FAIL: browser driver errored:\n%s\n%s" % (cp.stdout[-800:], cp.stderr[-800:]))
            return 1
        results = json.loads(cp.stdout.strip().splitlines()[-1])

        all_ok = True
        for res in results:
            real = [e for e in res["errors"] if not _benign(e)]
            ok = (res["status"] == 200) and not real
            all_ok = all_ok and ok
            print("  %s %s  (HTTP %s, %d JS error%s)"
                  % ("PASS" if ok else "FAIL", res["route"], res["status"],
                     len(real), "" if len(real) == 1 else "s"))
            for e in real:
                print("        %s" % e[:200])
        print("=" * 74)
        print("UI RENDER RESULT: %s" % ("GREEN ✓" if all_ok else "RED ✗"))
        print("=" * 74)
        return 0 if all_ok else 1
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
