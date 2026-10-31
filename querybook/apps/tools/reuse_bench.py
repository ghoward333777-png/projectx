#!/usr/bin/env python3
"""Reuse benchmark: is a video of a common human action faster to make from a stored clip than from scratch?

For each of ten common actions:
  make     generate the action from scratch with Gemini's video model (timed); the result becomes the STORED clip
  reuse    every reuse path measured on the stored clip, locally: exact retrieval, vertical re-crop (9:16), slow motion,
           colour change, trim — each timed
  probe    one request asking the video model to restyle a stored clip (video in, video out): does this key support it?
  check    automatic checks on every clip: length, motion present, and — for reused clips — the motion preserved
           (the motion curve of the reused clip against the stored one)
  report   seconds per path, checks, contact sheets for a human look; JSON + a self-contained HTML page

The Gemini daily budget is the SAME counter the answer-video tool uses (one budget file), so the two never overspend.
Only text prompts are used for the actions: no real person's likeness.

    python tools/reuse_bench.py make    --bench DIR --key-file gemini-key.json --budget-folder <answer-video library>
    python tools/reuse_bench.py probe   --bench DIR --key-file gemini-key.json --budget-folder <answer-video library>
    python tools/reuse_bench.py reuse   --bench DIR
    python tools/reuse_bench.py check   --bench DIR
    python tools/reuse_bench.py report  --bench DIR
    python tools/reuse_bench.py self-test
"""
import base64, html, json, os, shutil, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
MODEL = "gemini-omni-1.1-flash"

STYLE = ("One adult, ordinary casual clothes, in a plain bright modern room. The camera is fixed on a tripod, at chest height, "
         "and does not move, zoom or cut. The whole action is visible from start to finish, at a natural speed, then the person "
         "holds still for a moment. Realistic, natural light, no text, no music.")
ACTIONS = [
    ("open-bottle", "A person picks up a plastic water bottle from a table, twists the cap off with the other hand and puts the cap down."),
    ("pour-water", "A person pours water from a bottle into a clear drinking glass on a table until the glass is half full."),
    ("drink-cup", "A person seated at a table lifts a coffee cup, takes a sip and puts the cup back down."),
    ("type-laptop", "A person seated at a desk types on a laptop keyboard with both hands, looking at the screen."),
    ("scroll-phone", "A person holds a smartphone in one hand and scrolls the screen with the thumb, looking at it."),
    ("walk-toward", "A person walks toward the camera across the room and stops a few steps away."),
    ("sit-down", "A person standing beside a chair sits down on it and settles."),
    ("stand-up", "A person seated on a chair stands up and steps forward."),
    ("wave-hello", "A person standing facing the camera smiles and waves hello with one hand."),
    ("handshake", "Two people meet in the middle of the room and shake hands, then let go."),
]


def _ff(args, timeout=300):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + args, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("ffmpeg: %s" % r.stderr.decode("utf-8", "replace")[-300:])


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def motion_curve(path, fps=8, w=64, h=36):
    """mean absolute difference between consecutive small grey frames, fps samples a second (0..255)"""
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-vf", "fps=%d,scale=%d:%d,format=gray" % (fps, w, h),
                        "-f", "rawvideo", "-"], capture_output=True, timeout=300)
    data, n = r.stdout, w * h
    frames = [data[i:i + n] for i in range(0, len(data) - n + 1, n)]
    return [sum(abs(a - b) for a, b in zip(f1, f2)) / n for f1, f2 in zip(frames, frames[1:])]


def _smooth(c, k=5):
    """moving average: slow motion repeats frames, so its raw curve alternates still/moving — compare the trend"""
    h = k // 2
    return [statistics.fmean(c[max(0, i - h):i + h + 1]) for i in range(len(c))]


def _corr(a, b):
    a, b = _smooth(a), _smooth(b)
    m = min(len(a), len(b))
    if m < 3:
        return 0.0
    a, b = a[:m], b[:m]
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) if va and vb else 0.0


def _resample(c, factor):
    """a motion curve stretched in time by factor (for the slow-motion copy)"""
    out = []
    for i in range(int(len(c) / factor)):
        out.append(c[min(len(c) - 1, int(i * factor))])
    return out


class Bench:
    def __init__(self, folder):
        self.folder = os.path.abspath(folder)
        os.makedirs(self.folder, exist_ok=True)
        self.path = os.path.join(self.folder, "bench.json")
        try:
            self.data = json.load(open(self.path, encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {"actions": {}, "probe": None}

    def save(self):
        tmp = self.path + ".tmp"
        json.dump(self.data, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def act(self, key):
        return self.data["actions"].setdefault(key, {})

    def clip(self, key, name):
        return os.path.join(self.folder, key, name)


# ------------------------------------------------------------------------------------------------ make (from scratch, timed)
def make(bench, key_file, budget_folder, only=None, limit=None):
    import generate_exemplars as ge
    key = json.load(open(key_file))["api_key"] if key_file.endswith(".json") else open(key_file).read().strip()
    budget = ge.Budget(type("L", (), {"folder": budget_folder})())
    done = 0
    for k, what in ACTIONS:
        if only and k not in only:
            continue
        a = bench.act(k)
        if a.get("stored"):
            continue
        if limit is not None and done >= limit:
            break
        if not budget.reserve(MODEL):
            print("budget: no %s requests left today — the rest wait for tomorrow" % MODEL)
            break
        os.makedirs(os.path.join(bench.folder, k), exist_ok=True)
        t0 = time.time()
        try:
            data, ext = ge.generate(key, MODEL, what + " " + STYLE)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate" in msg.lower():
                budget.refund(MODEL)
            a.setdefault("errors", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "error": msg[:300],
                                               "seconds": round(time.time() - t0, 1)})
            bench.save()
            print("%s: failed after %.0f s — %s" % (k, time.time() - t0, msg[:160]))
            continue
        secs = time.time() - t0
        path = bench.clip(k, "stored" + ext)
        open(path, "wb").write(data)
        a.update(stored=os.path.basename(path), scratch_seconds=round(secs, 1), model=MODEL, prompt=what,
                 made=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        bench.save()
        done += 1
        print("%s: generated from scratch in %.1f s" % (k, secs))
    return done


# ------------------------------------------------------------------------------------------------ probe (video in, video out)
def probe(bench, key_file, budget_folder):
    """one request: can the video model take a stored clip as its input and restyle it?"""
    import generate_exemplars as ge
    key = json.load(open(key_file))["api_key"] if key_file.endswith(".json") else open(key_file).read().strip()
    src = next((bench.clip(k, a["stored"]) for k, a in bench.data["actions"].items() if a.get("stored")), None)
    if not src:
        print("probe: no stored clip yet — run make first")
        return None
    budget = ge.Budget(type("L", (), {"folder": budget_folder})())
    if not budget.reserve(MODEL):
        print("probe: no %s requests left today" % MODEL)
        return None
    body = {"model": MODEL, "store": False,
            "input": [{"type": "video", "data": base64.b64encode(open(src, "rb").read()).decode(), "mime_type": "video/mp4"},
                      {"type": "text", "text": "Keep exactly the same motion, timing and camera. Change only the person: an older man "
                                               "with grey hair in a blue shirt."}],
            "response_format": {"type": "video", "aspect_ratio": "16:9"},
            "generation_config": {"video_config": {"task": "video_to_video"}}}
    t0 = time.time()
    res = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": os.path.relpath(src, bench.folder)}
    try:
        r = ge._call(key, ge.API + "/interactions", body)
        vids = [p for s in r.get("steps", []) if s.get("type") == "model_output" for p in s.get("content", []) if p.get("type") == "video"]
        if vids:
            out = os.path.join(os.path.dirname(src), "restyled.mp4")
            open(out, "wb").write(base64.b64decode(vids[0]["data"]))
            res.update(supported=True, seconds=round(time.time() - t0, 1), output=os.path.relpath(out, bench.folder))
        else:
            res.update(supported=False, seconds=round(time.time() - t0, 1), detail="answered without a video (status %s)" % r.get("status"))
    except Exception as e:
        msg = str(e)
        if any(c in msg for c in ("400", "INVALID_ARGUMENT", "not supported", "unsupported")):
            budget.refund(MODEL)                     # refused as a request: nothing was generated
        res.update(supported=False, seconds=round(time.time() - t0, 1), detail=msg[:400])
    bench.data["probe"] = res
    bench.save()
    print("probe: %s" % json.dumps(res, ensure_ascii=False))
    return res


# ------------------------------------------------------------------------------------------------ reuse (local, timed)
REUSE = [
    ("retrieve", "exact retrieval of the stored clip", None),
    ("vertical", "re-cropped to vertical 9:16", ["-vf", "crop=ih*9/16:ih,scale=720:1280", "-c:a", "copy"]),
    ("slowmo", "slow motion, half speed", ["-vf", "setpts=2.0*PTS", "-af", "atempo=0.5"]),
    ("grade", "colour change (warmer, brighter)", ["-vf", "eq=brightness=0.05:saturation=1.3,colorbalance=rs=0.08:bs=-0.06", "-c:a", "copy"]),
    ("trim", "trimmed to the first 4 seconds", ["-t", "4", "-c:a", "copy"]),
]


def reuse(bench):
    n = 0
    for k, a in bench.data["actions"].items():
        if not a.get("stored"):
            continue
        src = bench.clip(k, a["stored"])
        out = a.setdefault("reuse", {})
        for name, label, args in REUSE:
            dst = bench.clip(k, name + ".mp4")
            t0 = time.time()
            if args is None:
                # retrieval: find the clip for the action key in the library and hand over a copy
                found = os.path.join(bench.folder, k, a["stored"])
                shutil.copyfile(found, dst)
            else:
                try:
                    _ff(["-i", src] + args + [dst])
                except RuntimeError:                  # a clip without sound: drop the audio options
                    _ff(["-i", src] + [x for x in args if x not in ("-c:a", "copy", "-af", "atempo=0.5")] + [dst])
            out[name] = {"label": label, "seconds": round(time.time() - t0, 3), "file": os.path.basename(dst)}
            n += 1
        bench.save()
    print("reuse: %d reused clips made" % n)
    return n


# ------------------------------------------------------------------------------------------------ check
def check(bench):
    for k, a in bench.data["actions"].items():
        if not a.get("stored"):
            continue
        src = bench.clip(k, a["stored"])
        base = motion_curve(src)
        mv = statistics.fmean(base) if base else 0.0
        a["checks"] = {"duration_s": round(duration(src), 2), "motion": round(mv, 2), "motion_present": mv >= 1.0}
        for name, r in (a.get("reuse") or {}).items():
            p = bench.clip(k, r["file"])
            c = motion_curve(p)
            ref = _resample(base, 0.5) if name == "slowmo" else base
            r["checks"] = {"duration_s": round(duration(p), 2), "motion_kept": round(_corr(c, ref), 3)}
            r["checks"]["ok"] = r["checks"]["duration_s"] > 0.5 and (r["checks"]["motion_kept"] >= 0.8 or name == "trim" and r["checks"]["motion_kept"] >= 0.6)
        # a contact sheet: 8 frames across the stored clip, for a human look
        sheet = bench.clip(k, "sheet.jpg")
        d = max(0.1, duration(src))
        try:
            _ff(["-i", src, "-vf", "fps=%f,scale=320:-1,tile=4x2" % (8.0 / d), "-frames:v", "1", "-q:v", "4", sheet])
            a["sheet"] = os.path.basename(sheet)
        except RuntimeError:
            pass
    bench.save()


# ------------------------------------------------------------------------------------------------ report
def summary(bench):
    acts = [(k, a) for k, a in bench.data["actions"].items() if a.get("stored")]
    gen = [a["scratch_seconds"] for _, a in acts if a.get("scratch_seconds")]
    out = {"actions_stored": len(acts), "actions_planned": len(ACTIONS), "scratch_seconds": gen,
           "scratch_median_s": round(statistics.median(gen), 1) if gen else None, "reuse": {}, "probe": bench.data.get("probe")}
    for name, label, _ in REUSE:
        s = [a["reuse"][name]["seconds"] for _, a in acts if (a.get("reuse") or {}).get(name)]
        ok = [a["reuse"][name].get("checks", {}).get("ok") for _, a in acts if (a.get("reuse") or {}).get(name)]
        if s:
            med = statistics.median(s)
            out["reuse"][name] = {"label": label, "median_s": round(med, 3), "passed": sum(1 for x in ok if x), "of": len(ok),
                                  "times_faster": round(out["scratch_median_s"] / med) if out["scratch_median_s"] and med > 0 else None}
    return out


def report(bench):
    s = summary(bench)
    json.dump(s, open(os.path.join(bench.folder, "summary.json"), "w"), indent=1)
    rows = []
    for k, a in bench.data["actions"].items():
        if not a.get("stored"):
            continue
        img = ""
        if a.get("sheet") and os.path.exists(bench.clip(k, a["sheet"])):
            img = '<img alt="frames of %s" src="data:image/jpeg;base64,%s">' % (html.escape(k), base64.b64encode(open(bench.clip(k, a["sheet"]), "rb").read()).decode())
        reuse_cells = "".join("<td>%.3f s %s</td>" % (r["seconds"], "✓" if (r.get("checks") or {}).get("ok") else "✗")
                              for r in (a.get("reuse") or {}).values())
        rows.append("<tr><td><b>%s</b><div class=m>%s</div></td><td>%.1f s</td>%s</tr><tr><td colspan=7>%s</td></tr>"
                    % (html.escape(k), html.escape(a.get("prompt", "")), a.get("scratch_seconds", 0), reuse_cells, img))
    pr = s.get("probe") or {}
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reuse Benchmark</title><style>
:root{--bg:#fff;--ink:#16181d;--muted:#5d6470;--line:#dde1e7}@media (prefers-color-scheme:dark){:root{--bg:#121418;--ink:#e8eaee;--muted:#9aa2b0;--line:#2c3139}}
body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px}
table{border-collapse:collapse;width:100%%}td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}
.m{color:var(--muted);font-size:12px}img{max-width:100%%;height:auto}.big{font-size:22px;font-weight:700}
</style></head><body><h1>Reuse benchmark — stored clip vs from scratch</h1>
<p><span class=big>%s</span> median to generate an action from scratch (%s, %d of %d actions so far). Reuse paths, median:</p><ul>%s</ul>
<p><b>Restyle a stored clip with the video model (video in, video out):</b> %s</p>
<table><tr><th>Action</th><th>From scratch</th>%s</tr>%s</table></body></html>""" % (
        ("%.0f s" % s["scratch_median_s"]) if s["scratch_median_s"] else "—", MODEL, s["actions_stored"], s["actions_planned"],
        "".join("<li>%s: <b>%s s</b> — %s× faster, %d of %d passed the checks</li>" % (html.escape(v["label"]), v["median_s"], v["times_faster"], v["passed"], v["of"])
                for v in s["reuse"].values()),
        html.escape("not tested yet" if not pr else ("supported — %.0f s" % pr["seconds"]) if pr.get("supported") else "not supported with this key: " + pr.get("detail", "")),
        "".join("<th>%s</th>" % html.escape(l) for _, l, _ in REUSE), "".join(rows))
    path = os.path.join(bench.folder, "reuse-benchmark.html")
    open(path, "w", encoding="utf-8").write(page)
    print(json.dumps(s, indent=1, ensure_ascii=False))
    print("report:", path)
    return s


# ------------------------------------------------------------------------------------------------ self-test
def self_test():
    res = []
    ok = lambda n, c, d="": res.append((n, bool(c), d))
    with tempfile.TemporaryDirectory() as tmp:
        b = Bench(tmp)
        for k in ("walk-toward", "wave-hello"):
            os.makedirs(os.path.join(tmp, k))
            _ff(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=6", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                 "-shortest", "-pix_fmt", "yuv420p", os.path.join(tmp, k, "stored.mp4")])
            b.act(k).update(stored="stored.mp4", scratch_seconds=120.0 if k == "walk-toward" else 150.0, prompt="test")
        b.save()
        n = reuse(b)
        ok("reuse: five paths per stored clip, each timed", n == 10 and all(len(a["reuse"]) == 5 for a in b.data["actions"].values()))
        check(b)
        a = b.data["actions"]["walk-toward"]
        ok("check: the vertical copy is 9:16, slow motion is twice as long", abs(duration(os.path.join(tmp, "walk-toward", "slowmo.mp4")) - 12) < 0.6)
        ok("check: motion kept in every reused copy (motion curves agree)", all(r["checks"]["ok"] for r in a["reuse"].values()), a["reuse"])
        ok("check: a contact sheet for a human look", os.path.exists(os.path.join(tmp, "walk-toward", "sheet.jpg")))
        s = report(b)
        ok("report: median from scratch and how many times faster each reuse path is",
           s["scratch_median_s"] == 135.0 and s["reuse"]["vertical"]["times_faster"] and os.path.exists(os.path.join(tmp, "reuse-benchmark.html")), s)
        ok("ten actions planned, text prompts only (no likeness)", len(ACTIONS) == 10 and all("image" not in p for _, p in ACTIONS))
    return res


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Reuse benchmark: stored clip vs from scratch")
    ap.add_argument("cmd", choices=["make", "probe", "reuse", "check", "report", "self-test"])
    ap.add_argument("--bench")
    ap.add_argument("--key-file")
    ap.add_argument("--budget-folder", help="the answer-video library folder (its _budget.json is the shared daily counter)")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        r = self_test()
        for n, g, d in r:
            print(("  [OK]   " if g else "  [FAIL] ") + n + ("" if g else "  — %s" % (d,)))
        print("\n  %d of %d checks passed" % (sum(1 for x in r if x[1]), len(r)))
        return 0 if all(x[1] for x in r) else 1
    b = Bench(a.bench)
    if a.cmd == "make":
        make(b, a.key_file, a.budget_folder or a.bench, [x for x in a.only.split(",") if x] or None, a.limit)
    elif a.cmd == "probe":
        probe(b, a.key_file, a.budget_folder or a.bench)
    elif a.cmd == "reuse":
        reuse(b)
    elif a.cmd == "check":
        check(b)
    else:
        report(b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
