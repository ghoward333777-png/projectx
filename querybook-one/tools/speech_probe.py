#!/usr/bin/env python3
"""Speech probe: change one thing at a time, drastically, and see which change moves the outcome.

    python tools/speech_probe.py [whisper|long|all] [--quick]

whisper — every voice name × voice option × sentence × speed, through the raw voice name (as before the fix) and the
          resolved one (the fix), each made 3 times: did espeak-ng drop the option (same audio as no option)? do the
          3 copies differ (randomness)? what does the voice measurement call it?
long    — long recordings through the app's own transcribe_long against a stand-in Google server: one-at-a-time vs
          concurrent server × 1/4/8 pieces at once × 60/125/300 s, 3 times each: seconds taken and any error.
Prints tables; on GitHub Actions also writes them to the job summary and speech-probe.json.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(ROOT, "apps", "language")
sys.path.insert(0, LANG)
os.chdir(LANG)
import speech  # noqa: E402
import voicedsp as V  # noqa: E402

QUICK = "--quick" in sys.argv
OUT: list[str] = []
DATA: dict = {}


def say(line: str = "") -> None:
    print(line, flush=True)
    OUT.append(line)


def md5(b: bytes | None) -> str:
    return hashlib.md5(b or b"").hexdigest()[:8]


def whisper_probe() -> None:
    names = ["en", "en-us", "en-gb", "en-uk", "gmw/en", "gmw/en-US"]
    options = ["whisper", "whisperf", "female_whisper", "f3", "croak", "grandpa"]
    texts = ["Hello there. This is a short test of the voice.", "The quick brown fox jumps over the lazy dog."]
    rates = [150, 260]
    if QUICK:
        names, options, texts, rates = names[:3], options[:3], texts[:1], rates[:1]
    real = speech.resolve_voice
    say("## Whisper / voice options — espeak-ng: %s" % speech.version())
    say("")
    say("| voice | option | path | sent to espeak | dropped (same as no option) | 3 copies differ | measured as (voiced %) |")
    say("|---|---|---|---|---|---|---|")
    rows = []
    for path in ("raw", "resolved"):
        speech.resolve_voice = real if path == "resolved" else (lambda v: v)
        for n in names:
            for o in options:
                dropped = differ = 0
                labels = []
                for t in texts:
                    for r in rates:
                        plain = speech.speak_wav(t, n, r)
                        copies = [speech.speak_wav(t, n + "+" + o, r) for _ in range(3)]
                        dropped += copies[0] == plain
                        differ += len({md5(c) for c in copies}) > 1
                        if "whisper" in o and copies[0]:
                            m = V.measure(copies[0])
                            labels.append("%s (%d)" % (m["vocal_mode"]["label"], round(100 * m["vocal"]["voiced_ratio"])))
                k = len(texts) * len(rates)
                row = {"voice": n, "option": o, "path": path, "sent": speech.resolve_voice(n + "+" + o), "dropped": dropped, "differ": differ, "of": k, "labels": labels}
                rows.append(row)
                say("| %s | %s | %s | %s | %d of %d | %d of %d | %s |" % (n, o, path, row["sent"], dropped, k, differ, k, ", ".join(labels) or "—"))
    speech.resolve_voice = real
    DATA["whisper"] = rows
    bad_raw = [(r["voice"], r["option"]) for r in rows if r["path"] == "raw" and r["dropped"]]
    bad_fix = [(r["voice"], r["option"]) for r in rows if r["path"] == "resolved" and r["dropped"]]
    say("")
    say("**Dropped before the fix:** %s" % (bad_raw or "none"))
    say("**Dropped after the fix:** %s" % (bad_fix or "none"))
    say("**Randomness (copies differ):** %s" % ([(r["voice"], r["option"], r["path"]) for r in rows if r["differ"]] or "none"))
    say("")


def long_probe() -> None:
    import app  # the Language app itself: its SpeechLab is what the self-test uses
    reply = json.dumps({"results": [{"alternatives": [{"transcript": "good morning", "confidence": 0.9, "words": [
        {"word": "good", "startTime": "0.20s", "endTime": "0.50s", "confidence": 0.92},
        {"word": "morning", "startTime": "0.55s", "endTime": "1.10s", "confidence": 0.88}]}], "languageCode": "en-us"}]}).encode()

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

    servers = {"one-at-a-time": http.server.HTTPServer, "concurrent": http.server.ThreadingHTTPServer}
    workers = [1, 4, 8]
    lengths = [60, 125, 300]
    reps = 3
    if QUICK:
        workers, lengths, reps = [4], [125], 1
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    say("## Long recordings — %s, Python %s" % (sys.platform, sys.version.split()[0]))
    say("")
    say("| server | pieces at once | length | runs ok | seconds (each run) | errors |")
    say("|---|---|---|---|---|---|")
    rows = []
    wavs = {s: V.tone_wav(f0=140, seconds=s, gaps=tuple((k * 10 - 0.6, k * 10) for k in range(1, int(s // 10) + 1))) for s in lengths}
    with tempfile.TemporaryDirectory() as d:
        S = app.App(d).speech
        S.google.s.save({"api_key": "AIzaPROBE-123456"})
        for sname, cls in servers.items():
            srv = cls(("127.0.0.1", 0), H)
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            os.environ["QB_GCP_BASE_SPEECH"] = "http://127.0.0.1:%d" % srv.server_address[1]
            for w in workers:
                for s in lengths:
                    times, errors, ok = [], [], 0
                    for _ in range(reps):
                        t = time.time()
                        r = S.transcribe_long(wavs[s], "en", "pieces", workers=w)
                        times.append(round(time.time() - t, 2))
                        if r.get("error"):
                            errors.append(str(r["error"])[:80])
                        elif r.get("pieces", 0) >= 2 and r.get("duration_s", 0) >= s - 1:
                            ok += 1
                    rows.append({"server": sname, "workers": w, "seconds": s, "ok": ok, "of": reps, "times": times, "errors": errors})
                    say("| %s | %d | %d s | %d of %d | %s | %s |" % (sname, w, s, ok, reps, ", ".join(map(str, times)), "; ".join(errors) or "—"))
            srv.shutdown()
            srv.server_close()
    DATA["long"] = rows
    say("")


if __name__ == "__main__":
    what = next((a for a in sys.argv[1:] if not a.startswith("-")), "all")
    if not speech.find_espeak() and what in ("whisper", "all"):
        say("espeak-ng not found — whisper probe skipped")
    elif what in ("whisper", "all"):
        whisper_probe()
    if what in ("long", "all"):
        long_probe()
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")
    with open(os.path.join(ROOT, "speech-probe.json"), "w", encoding="utf-8") as f:
        json.dump(DATA, f, indent=1)
