#!/usr/bin/env python3
"""Tests of the shared core's data safety: concurrent writers, crash-safe transactions,
damage detection (the app refuses to write to a damaged database), backups and restore."""
import json, os, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
import qbcore as core

SCHEMA = ["CREATE TABLE t (id INTEGER PRIMARY KEY, k TEXT UNIQUE, v INTEGER)"]


class FakeGitHub:
    """A stand-in for api.github.com's issue endpoints, recording what the application sends."""

    def __init__(self, token="github_pat_TESTTOKEN0123456789abcdef"):
        import http.server, json as _json
        self.token, self.issues, self.comments, self.requests, self.down = token, {}, [], [], False
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                b = _json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _handle(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = _json.loads(self.rfile.read(n) or b"null") if n else None
                outer.requests.append((method, self.path, self.headers.get("Authorization"), body))
                if outer.down:
                    return self._reply(503, {"message": "down"})
                if self.headers.get("Authorization") != "Bearer " + outer.token:
                    return self._reply(401, {"message": "Bad credentials"})
                parts = self.path.split("?")[0].strip("/").split("/")
                if parts[:1] != ["repos"] or len(parts) < 4 or parts[3] != "issues":
                    return self._reply(404, {"message": "Not Found"})
                if method == "GET" and len(parts) == 4:
                    return self._reply(200, [i for i in outer.issues.values() if i["state"] == "open"])
                if method == "GET" and len(parts) == 5:
                    i = outer.issues.get(int(parts[4]))
                    return self._reply(200, i) if i else self._reply(404, {"message": "Not Found"})
                if method == "POST" and len(parts) == 4:
                    num = len(outer.issues) + 1
                    outer.issues[num] = {"number": num, "title": body["title"], "body": body["body"], "state": "open",
                                         "html_url": "https://github.com/%s/%s/issues/%d" % (parts[1], parts[2], num)}
                    return self._reply(201, outer.issues[num])
                if method == "POST" and len(parts) == 6 and parts[5] == "comments":
                    outer.comments.append((int(parts[4]), body["body"]))
                    return self._reply(201, {"html_url": "https://github.com/x/y/issues/%s#c%d" % (parts[4], len(outer.comments))})
                return self._reply(404, {"message": "Not Found"})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def range_tests(c):
    """Audio and video answers honour byte ranges, so players can seek inside them."""
    import urllib.request as _u
    api = core.Api()
    blob = bytes(range(256)) * 40
    api.get("/api/clip")(lambda p: (blob, "audio/wav"))
    with tempfile.TemporaryDirectory() as ui:
        httpd = core.ThreadingHTTPServer(("127.0.0.1", 0), core.make_handler(api, ui, lambda *a: None, "T"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = "http://127.0.0.1:%d/api/clip" % httpd.server_address[1]
        def get(rng=None):
            rq = _u.Request(url, headers={"Range": rng} if rng else {})
            try:
                with _u.urlopen(rq, timeout=5) as r:
                    return r.status, r.headers, r.read()
            except _u.HTTPError as e:
                return e.code, e.headers, e.read()
        st, h, b = get()
        c.check("audio answers say they can be sought (Accept-Ranges)", st == 200 and h.get("Accept-Ranges") == "bytes" and b == blob)
        st, h, b = get("bytes=100-199")
        c.check("a byte range returns exactly that part (206)", st == 206 and b == blob[100:200] and h.get("Content-Range") == "bytes 100-199/%d" % len(blob))
        st, h, b = get("bytes=-10")
        c.check("a suffix range returns the last bytes", st == 206 and b == blob[-10:])
        st, h, b = get("bytes=999999-")
        c.check("a range past the end is refused (416)", st == 416)
        httpd.shutdown()


def power_tests(c):
    import tempfile, time as _t
    with tempfile.TemporaryDirectory() as tmp:
        log = core.make_logger(tmp, "t")
        pw = core.Power(log, tmp, "t")
        pw.session_start("1.0")
        c.check("power: a clean first start is not flagged", not pw.state.get("previous_unclean"))
        pw2 = core.Power(log, tmp, "t")
        pw2.session_start("1.0")                                    # the first never ended: like a sleep, crash or power cut
        c.check("power: a run that did not stop cleanly is noticed at the next start", bool(pw2.state.get("previous_unclean")))
        pw2.session_end()
        c.check("power: a clean stop removes the marker", not os.path.exists(pw2.marker))
        os.environ["QB_ALLOW_SLEEP"] = "1"
        c.check("power: QB_ALLOW_SLEEP=1 lets the computer sleep", pw2.keep_awake()["keep_awake"] is False)
        del os.environ["QB_ALLOW_SLEEP"]
        r = pw2.system_check()
        c.check("power: the system-log check always answers (never fails start-up)", isinstance(r, dict) and "events" in r and "advice" in r)
        real = _t.time
        ticks = iter([1000.0, 1000.0, 1010.0, 1200.0] + [1210.0] * 50)
        _t_sleep = _t.sleep
        core.time.time = lambda: next(ticks)
        core.time.sleep = lambda s: None
        try:
            th = pw2.watch(every=10, gap=45)
            import threading as _th
            for x in _th.enumerate():
                if x.name == "qb-heartbeat":
                    x.join(0.3)
        finally:
            core.time.time, core.time.sleep = real, _t_sleep
        txt = open(log.path, encoding="utf-8").read()
        c.check("power: a gap in the heartbeat is logged as sleep/pause", any(x["seconds"] == 190 for x in pw2.state["sleeps"]) and "paused for 190 s" in txt, pw2.state["sleeps"])
        c.check("power: every session is marked in the log file", txt.count("==== session start") == 2 and "==== session end" in txt)


def monitoring_tests(c):
    gh = FakeGitHub()
    os.environ["QB_GITHUB_API"] = gh.url
    with tempfile.TemporaryDirectory() as tmp:
        log = core.make_logger(tmp, "t")
        st = core.Store(tmp, "t", SCHEMA, log)
        st.backup("start", force=True)
        prog = os.path.join(tmp, "prog")
        for f in core.REQUIRED_FILES:
            os.makedirs(os.path.dirname(os.path.join(prog, f)) or prog, exist_ok=True)
            open(os.path.join(prog, f), "w").close()
        jobs = core.Jobs(log)
        extra = lambda: [core._check("app", "Application sample", "ok", "fine")]
        d = core.Diagnostics("t", "Test App", "9.9", prog, st, log, jobs, extra)
        r = d.run()
        c.check("diagnostics: healthy application reports OK", r["overall"] == "ok", [x for x in r["checks"] if x["status"] != "ok"])
        c.check("diagnostics: all standard checks present", {"python", "files", "writable", "disk", "database", "schema", "size", "backup", "errors", "jobs", "app"} <= {x["id"] for x in r["checks"]})
        m = core.Monitor(tmp, "t", "Test App", "9.9", log)
        log.hooks.append(m.on_error)
        c.check("monitor: off until a token is given", m.due(r) is None)
        try:
            m.configure(enabled=True)
            c.check("monitor: cannot be switched on without a token", False)
        except core.UserError:
            c.check("monitor: cannot be switched on without a token", True)
        m.configure(enabled=True, repo="https://github.com/owner/repo", token="github_pat_WRONGTOKEN0123456789abcdef", label="office PC!")
        c.check("monitor: repository address and label cleaned", m.cfg["repo"] == "owner/repo" and m.cfg["label"] == "office PC")
        try:
            m.send("Test", r)
            c.check("monitor: a wrong token is reported plainly", False)
        except core.MonitorError as e:
            c.check("monitor: a wrong token is reported plainly", "refused the token" in str(e), str(e))
        m.configure(token=gh.token)
        c.check("monitor: token never shown back in full", gh.token not in json.dumps(m.public()) and m.public()["token_set"])
        url = m.send("Test", r)
        c.check("monitor: first report creates the issue and comments on it", len(gh.issues) == 1 and len(gh.comments) == 1 and url, url)
        c.check("monitor: issue title names the application and computer", gh.issues[1]["title"] == "[QueryBook monitor] Test App · office PC")
        m.send("Check-in", r)
        c.check("monitor: later reports reuse the same issue", len(gh.issues) == 1 and gh.comments[-1][0] == 1)
        m2 = core.Monitor(tmp, "t", "Test App", "9.9", log)
        m2.cfg.pop("issue_number")
        m2.send("Check-in", r)
        c.check("monitor: finds its open issue again by title", len(gh.issues) == 1)
        # schedule: daily check-in
        t0 = 1_000_000.0
        m.cfg["last_heartbeat_ts"] = t0
        c.check("monitor: no check-in within the day", m.due(r, t0 + 3600) is None)
        c.check("monitor: check-in after a day", m.due(r, t0 + 86400) == ("Check-in", None))
        m.configure(frequency="problems")
        c.check("monitor: 'problems only' sends no check-in", m.due(r, t0 + 86400 * 3) is None)
        # a problem: an error is logged -> immediate report, then not repeated for 6 hours
        home = os.path.expanduser("~")
        log("ERROR", "GET", "/api/x", "ValueError('bad value in %s')" % os.path.join(home, "private", "notes.txt"), "Traceback | line 2 | " + gh.token)
        c.check("monitor: a logged error wakes the monitor", m._wake.is_set())
        n0 = len(gh.comments)
        url = m.tick(d, now=t0 + 10)
        body = gh.comments[-1][1]
        c.check("monitor: problem report sent at once", len(gh.comments) == n0 + 1 and "Problem" in body and "WARN" in body, body[:200])
        c.check("monitor: report hides the home folder, the token and the traceback",
                home not in body and gh.token not in body and "line 2" not in body and "~" in body, body)
        m.tick(d, now=t0 + 60)
        c.check("monitor: the same problem is not repeated within 6 hours", len(gh.comments) == n0 + 1)
        m.tick(d, now=t0 + 7 * 3600)
        c.check("monitor: still unresolved after 6 hours -> reminded", len(gh.comments) == n0 + 2)
        # GitHub unreachable -> report waits, then goes out with the next one
        gh.down = True
        log("ERROR", "second failure")
        m.tick(d, now=t0 + 8 * 3600)
        c.check("monitor: report waits when GitHub cannot be reached", len(m.cfg["outbox"]) == 1 and "not sent" in m.cfg["last_status"])
        gh.down = False
        m.send("Check-in", d.run())
        c.check("monitor: waiting report is delivered first", m.cfg["outbox"] == [] and len(gh.comments) == n0 + 4)
        sent = json.dumps([b for _, b in gh.comments])
        c.check("monitor: no request carried anything but the issue title/body/comment", all(set((b or {}).keys()) <= {"title", "body"} for _, _, _, b in gh.requests))
        c.check("monitor: settings file not readable by others", os.name == "nt" or (os.stat(m.path).st_mode & 0o077) == 0)
        m.disconnect()
        c.check("monitor: removing the token switches it off", not m.cfg["token"] and not m.cfg["enabled"] and m.due(d.run()) is None)
        # damaged database shows as a failure in the diagnostics
        st.read_only, st.damage = True, "simulated"
        c.check("diagnostics: damaged database is a failure", d.run()["overall"] == "fail")
    os.environ.pop("QB_GITHUB_API", None)
    gh.httpd.shutdown()


# ---------------------------------------------------------------------------- Google Cloud against a stand-in server
def _rsa_test_key(bits=1024):
    """A real RSA key made here (test only), returned as a PKCS#8 PEM plus its public numbers."""
    import random
    rnd = random.Random(20261017)

    def prime(b):
        while True:
            n = rnd.getrandbits(b) | (1 << (b - 1)) | 1
            if all(n % q for q in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11)):
                d, r = n - 1, 0
                while d % 2 == 0:
                    d //= 2; r += 1
                ok = True
                for a in (2, 3, 5, 7, 11, 13, 17, 19, 23):
                    x = pow(a, d, n)
                    if x in (1, n - 1):
                        continue
                    for _ in range(r - 1):
                        x = pow(x, 2, n)
                        if x == n - 1:
                            break
                    else:
                        ok = False; break
                if ok:
                    return n
    e = 65537
    while True:
        p, q = prime(bits // 2), prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            break
    n, d = p * q, pow(e, -1, phi)

    def tlv(tag, body):
        ln = len(body)
        L = bytes([ln]) if ln < 128 else bytes([0x80 | ((ln.bit_length() + 7) // 8)]) + ln.to_bytes((ln.bit_length() + 7) // 8, "big")
        return bytes([tag]) + L + body

    def INT(v):
        b = v.to_bytes((v.bit_length() + 8) // 8, "big")
        return tlv(0x02, b)
    rsa = tlv(0x30, b"".join(INT(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))))
    alg = tlv(0x30, tlv(0x06, bytes.fromhex("2a864886f70d010101")) + b"\x05\x00")
    der = tlv(0x30, INT(0) + alg + tlv(0x04, rsa))
    import base64 as _b
    pem = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(_b.b64encode(der).decode()[i:i + 64] for i in range(0, len(_b.b64encode(der)), 64)) + "\n-----END PRIVATE KEY-----\n"
    return pem, n, e


def google_tests(c):
    import http.server, base64, hashlib, gcloud, urllib.parse
    pem, n, e = _rsa_test_key()
    seen = {"tokens": 0, "bad_sig": 0, "objects": {}, "sessions": {}, "metrics": [], "alerts": 0, "speech": 0, "yt": 0}

    def verify_jwt(jwt):
        h, cl, sig = jwt.split(".")
        pad = lambda x: x + "=" * (-len(x) % 4)
        s_int = int.from_bytes(base64.urlsafe_b64decode(pad(sig)), "big")
        em = pow(s_int, e, n).to_bytes((n.bit_length() + 7) // 8, "big")
        want = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256((h + "." + cl).encode()).digest()
        return em.endswith(want) and em.startswith(b"\x00\x01\xff"), json.loads(base64.urlsafe_b64decode(pad(cl)))

    class G(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body=b"", ctype="application/json", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers(); self.wfile.write(body)

        def authed(self):
            return self.headers.get("Authorization") == "Bearer ya29.test-token"

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
            if u.path == "/token":
                f = dict(urllib.parse.parse_qsl(body.decode()))
                ok, claims = verify_jwt(f["assertion"])
                if not ok:
                    seen["bad_sig"] += 1
                    return self.send(400, {"error": "invalid_grant"})
                seen["tokens"] += 1; seen["claims"] = claims
                return self.send(200, {"access_token": "ya29.test-token", "expires_in": 3600})
            if not self.authed() and "speech" not in u.path:
                return self.send(401, {"error": {"message": "no token"}})
            if u.path.startswith("/upload/storage/v1/b/"):
                sid = "s%d" % len(seen["sessions"])
                seen["sessions"][sid] = {"name": q["name"], "data": b""}
                return self.send(200, b"", extra={"Location": "http://%s/session/%s" % (self.headers["Host"], sid)})
            if u.path.endswith("/timeSeries"):
                seen["metrics"].append(json.loads(body)); return self.send(200, {})
            if u.path.endswith("/alertPolicies"):
                seen["alerts"] += 1; b = json.loads(body); b["name"] = "projects/p/alertPolicies/1"; return self.send(200, b)
            if u.path == "/v1/speech:longrunningrecognize":
                b = json.loads(body)
                seen["lr_uri"], seen["lr_auth"], seen["lr_polls"] = b["audio"]["uri"], self.authed(), 0
                seen["lr_object_present"] = b["audio"]["uri"].split("/", 3)[3] in seen["objects"]
                return self.send(200, {"name": "op-123"})
            if u.path == "/v1/speech:recognize":
                seen["speech"] += 1
                if self.headers.get("X-Goog-Api-Key") != "AIzaTESTKEY0000000000000000000000000000":
                    return self.send(403, {"error": {"message": "bad key"}})
                cfg = json.loads(body)["config"]
                seen["speech_cfg"] = cfg
                alts = [{"transcript": "hello there", "confidence": 0.93,
                         "words": [{"word": "hello", "startTime": "0.100s", "endTime": "0.450s", "confidence": 0.95},
                                   {"word": "there", "startTime": "0.500s", "endTime": "0.900s", "confidence": 0.91}]}]
                if cfg.get("maxAlternatives", 1) > 1:
                    alts.append({"transcript": "yellow there", "confidence": 0.41})
                return self.send(200, {"results": [{"alternatives": alts, "languageCode": "en-us"}]})
            return self.send(404, {"error": {"message": "no route"}})

        def do_PUT(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            sid = self.path.rsplit("/", 1)[1]
            s = seen["sessions"][sid]
            s["data"] += body
            total = int(self.headers["Content-Range"].split("/")[1])
            if len(s["data"]) < total:
                return self.send(308, b"", extra={"Range": "bytes=0-%d" % (len(s["data"]) - 1)})
            md5 = base64.b64encode(hashlib.md5(s["data"]).digest()).decode()
            seen["objects"][s["name"]] = s["data"]
            seen["chunks"] = seen.get("chunks", 0) + 1
            return self.send(200, {"name": s["name"], "size": str(total), "md5Hash": md5})

        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
            if u.path.startswith("/youtube/v3/"):
                seen["yt"] += 1
                if u.path.endswith("/search"):
                    return self.send(200, {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]})
                return self.send(200, {"items": [{"id": "dQw4w9WgXcQ", "snippet": {"title": "A talk", "channelTitle": "A Channel", "channelId": "C1",
                                                  "publishedAt": "2009-10-25T06:57:33Z", "description": "d"},
                                                  "contentDetails": {"duration": "PT3M33S", "caption": "true"}, "statistics": {"viewCount": "5"}}]})
            if not self.authed():
                return self.send(401, {"error": {"message": "no token"}})
            if u.path == "/v1/operations/op-123":
                seen["lr_polls"] += 1
                if seen["lr_polls"] < 2:
                    return self.send(200, {"name": "op-123", "metadata": {"progressPercent": 50}})
                return self.send(200, {"name": "op-123", "done": True, "response": {"results": [{"alternatives": [{"transcript": "long recording words", "confidence": 0.9,
                                       "words": [{"word": "long", "startTime": "1.500s", "endTime": "1.900s"}]}], "languageCode": "en-us"}]}})
            parts = u.path.split("/")
            if u.path.startswith("/storage/v1/b/") and len(parts) == 5:
                return self.send(200, {"name": parts[4], "location": "EU"})
            if u.path.endswith("/o"):
                items = [{"name": k, "size": str(len(v)), "updated": "2026-10-17T00:00:00Z", "md5Hash": base64.b64encode(hashlib.md5(v).digest()).decode()}
                         for k, v in seen["objects"].items() if k.startswith(q.get("prefix", ""))]
                return self.send(200, {"items": items})
            if "/o/" in u.path and q.get("alt") == "media":
                name = urllib.parse.unquote(u.path.split("/o/", 1)[1])
                return self.send(200, seen["objects"][name], "application/octet-stream")
            return self.send(404, {"error": {"message": "no route"}})

        def do_DELETE(self):
            name = urllib.parse.unquote(self.path.split("/o/", 1)[1])
            seen["objects"].pop(name, None)
            self.send(204)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), G)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base_url = "http://127.0.0.1:%d" % srv.server_address[1]
    saved = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    for svc in ("storage", "monitoring", "speech", "youtube", "token"):
        os.environ["QB_GCP_BASE_" + svc.upper()] = base_url
    SA = {"type": "service_account", "project_id": "qb-test", "private_key_id": "kid123", "private_key": pem,
          "client_email": "querybook@qb-test.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token"}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            S = gcloud.Settings(tmp)
            try:
                S.save({"service_account_json": json.dumps({"type": "service_account", "client_email": "x", "private_key": "nope"})})
                c.check("google: a broken service account file is refused", False)
            except Exception:
                c.check("google: a broken service account file is refused", True)
            S.save({"api_key": "AIzaTESTKEY0000000000000000000000000000", "service_account_json": json.dumps(SA), "bucket": "gs://qb-backups/",
                    "storage_on": True, "monitoring_on": True, "keep": 2})
            pub = json.dumps(S.public())
            c.check("google: settings saved privately and reported without secrets", "AIzaTEST" not in pub and "PRIVATE KEY" not in pub
                    and S.public()["bucket"] == "qb-backups" and S.public()["project_id"] == "qb-test")
            if os.name != "nt":
                c.check("google: settings file is readable by the owner only", os.stat(S.path).st_mode & 0o077 == 0)
            G_ = gcloud.Google(S)
            tok = G_.token()
            c.check("google: service-account sign-in — the RS256 signature made here verifies with the public key",
                    tok == "ya29.test-token" and seen["tokens"] == 1 and seen["bad_sig"] == 0 and seen["claims"]["iss"] == SA["client_email"])
            G_.token()
            c.check("google: the access token is reused until it expires", seen["tokens"] == 1)
            big = os.path.join(tmp, "big.sqlite")
            with open(big, "wb") as f:
                f.write(os.urandom(5 * 1024 * 1024 + 123))
            meta = G_.upload(big, "querybook/t/h/big.sqlite")
            c.check("google: resumable upload in 2 MiB chunks, MD5 checked against the file", meta["md5Hash"] and seen["objects"]["querybook/t/h/big.sqlite"] == open(big, "rb").read())
            G_.download("querybook/t/h/big.sqlite", os.path.join(tmp, "back.sqlite"))
            c.check("google: download from Cloud Storage is MD5-checked", open(os.path.join(tmp, "back.sqlite"), "rb").read() == open(big, "rb").read())
            G_.write_metrics("t", "h", {"health": 0, "uptime_hours": 1.5})
            ts = seen["metrics"][-1]["timeSeries"]
            c.check("google: Cloud Monitoring metrics written with app and host labels",
                    {t["metric"]["type"] for t in ts} == {"custom.googleapis.com/querybook/health", "custom.googleapis.com/querybook/uptime_hours"}
                    and ts[0]["metric"]["labels"] == {"app": "t", "host": "h"} and ts[0]["resource"]["labels"]["project_id"] == "qb-test")
            al = G_.create_alert("t", "Test")
            c.check("google: alert policy for a silent or failing application", seen["alerts"] == 1 and len(al["conditions"]) == 2)
            import io, wave as _w
            b = io.BytesIO()
            with _w.open(b, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00\x00" * 16000)
            r = G_.recognize(b.getvalue(), "en-US")
            c.check("google: Speech-to-Text returns words with timings and confidence",
                    r["transcript"] == "hello there" and r["words"][1]["start_s"] == 0.5 and seen["speech_cfg"]["enableWordTimeOffsets"] and seen["speech_cfg"]["sampleRateHertz"] == 16000)
            r2 = G_.recognize(b.getvalue(), "en-US", alternatives=5)
            c.check("google: Speech-to-Text alternatives for the whole clip (the camera chooses between them)",
                    seen["speech_cfg"]["maxAlternatives"] == 5 and [a["transcript"] for a in r2["alternatives"]] == ["hello there", "yellow there"]
                    and "maxAlternatives" not in json.dumps(seen.get("first_cfg", {})))
            import tempfile as _tf
            with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as f_:
                f_.write(b.getvalue()); wp = f_.name
            old_poll = os.environ.get("QB_POLL_S"); os.environ["QB_POLL_S"] = "0.01"
            prog = []
            try:
                rl = G_.recognize_long(wp, "en-US", lambda what, frac: prog.append((what, frac)))
            finally:
                os.remove(wp)
                if old_poll is None:
                    os.environ.pop("QB_POLL_S", None)
                else:
                    os.environ["QB_POLL_S"] = old_poll
            c.check("google: long audio goes to the bucket (MD5-checked), a long-running job transcribes it with progress, the copy is deleted",
                    rl["transcript"] == "long recording words" and rl["words"][0]["start_s"] == 1.5 and seen["lr_uri"].startswith("gs://qb-backups/querybook-speech/")
                    and seen["lr_auth"] and seen["lr_object_present"] and not any(k.startswith("querybook-speech/") for k in seen["objects"])
                    and ("transcribing", 0.5) in prog and any(w_ == "uploading" for w_, _ in prog))
            c.check("google: the service account's sign-in covers Speech-to-Text", "cloud-platform" in seen["claims"]["scope"])
            v = G_.youtube_search("talk", 3)
            c.check("google: YouTube search returns video, channel, date and link", v and v[0]["channel"] == "A Channel" and v[0]["url"].endswith("dQw4w9WgXcQ"))
            c.check("google: video ids are read from any YouTube link form", gcloud.youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
                    and gcloud.youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3") == "dQw4w9WgXcQ")
            # the application path: every backup goes to the bucket, newest N kept, diagnostics see it
            st = core.Store(tmp, "t", SCHEMA)
            link = core.CloudLink(st, "t", "Test", lambda *a: None)
            link.settings, link.g = S, G_
            st.cloud = link
            for i in range(3):
                with st.write() as db:
                    db.execute("INSERT INTO t(k, v) VALUES(?, 1)", ("cloud-%d" % i,))
                st.backup("c%d" % i, force=True)
                for _ in range(100):
                    if not link._busy:
                        break
                    time.sleep(0.05)
            names = [x["name"] for x in G_.list(link.prefix())]
            c.check("google: every backup is uploaded in the background and only the newest 2 are kept in the bucket",
                    len(names) == 2 and names[0].endswith(os.path.basename(st.backups()[0]["path"])), names)
            ck = {x["id"]: x for x in link.checks()}
            c.check("google: diagnostics confirm sign-in and that the newest backup is in Cloud Storage",
                    ck["google_auth"]["status"] == "ok" and ck["cloud_backup"]["status"] == "ok", ck.get("cloud_backup"))
            logged = json.dumps(st.activities(500))
            c.check("google: no key, private key or token appears in the activity log", "AIzaTEST" not in logged and "PRIVATE KEY" not in logged and "ya29" not in logged)
            S.save({"bucket": "missing-bucket"})
            os.environ["QB_GCP_BASE_STORAGE"] = "http://127.0.0.1:9"          # unreachable
            link.upload_backup(st.backups()[0]["path"])
            ck = {x["id"]: x for x in link.checks()}
            c.check("google: a failed upload is reported by diagnostics", ck["cloud_backup"]["status"] == "fail")
    finally:
        srv.shutdown()
        for svc in ("storage", "monitoring", "speech", "youtube", "token"):
            os.environ.pop("QB_GCP_BASE_" + svc.upper(), None)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def setup_script_tests(c):
    """The one-paste Cloud Shell setup, run against a stand-in gcloud that records every call."""
    import shutil, subprocess, gcloud
    if not shutil.which("bash"):
        c.check("setup script: skipped (no bash on this computer — it runs in Google Cloud Shell)", True)
        return
    pem, n, e = _rsa_test_key()
    sa = {"type": "service_account", "project_id": "fleet-test", "private_key_id": "k1", "private_key": pem,
          "client_email": "querybook-apps@fleet-test.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token"}
    for allow_keys in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
            log = os.path.join(tmp, "calls.log")
            with open(os.path.join(tmp, "sa.json"), "w") as f:
                json.dump(sa, f)
            shim = r"""#!/bin/bash
echo "$*" >> "%(log)s"
case "$*" in
  "config get-value project") echo fleet-test ;;
  "services api-keys list"*) [ -f "%(tmp)s/key-made" ] && echo projects/1/locations/global/keys/abc ;;
  "services api-keys create"*) touch "%(tmp)s/key-made" ;;
  "services api-keys get-key-string"*) echo AIzaSETUPKEY000000000000000000000000000 ;;
  "storage buckets describe"*) exit 1 ;;
  "iam service-accounts describe"*) exit 1 ;;
  "iam service-accounts keys create"*) %(keys)s ;;
esac
exit 0
""" % {"log": log, "tmp": tmp, "keys": ('cp "%s/sa.json" "$5"' % tmp) if allow_keys else "exit 1"}
            with open(os.path.join(bindir, "gcloud"), "w") as f:
                f.write(shim)
            os.chmod(os.path.join(bindir, "gcloud"), 0o755)
            env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"])
            r = subprocess.run(["bash", "-c", gcloud.SETUP_SCRIPT], capture_output=True, text=True, env=env, timeout=60)
            calls = open(log).read()
            line = [l for l in r.stdout.splitlines() if l.startswith("QBSETUP-")]
            vals = gcloud.decode_setup_code(line[0]) if line else {}
            st = gcloud.Settings(tmp)
            if vals:
                st.save(vals)
            pub = st.public()
            if allow_keys:
                c.check("setup script: enables the APIs, makes a RESTRICTED key, a bucket and a service account with only storage + monitoring roles",
                        "services enable texttospeech.googleapis.com" in calls and "--api-target=service=youtube.googleapis.com" in calls
                        and "storage buckets create gs://querybook-backups-fleet-test" in calls and "roles/storage.objectAdmin" in calls
                        and "roles/monitoring.editor" in calls and "roles/owner" not in calls and "roles/editor " not in calls, r.stdout[-300:])
                c.check("setup script: its one setup code configures the key, bucket, service account and switches backups and reports on",
                        pub["api_key_set"] and pub["bucket"] == "querybook-backups-fleet-test" and pub["service_account"]["client_email"].startswith("querybook-apps@")
                        and pub["storage_on"] and pub["monitoring_on"])
                c.check("setup script: the key appears only inside the setup code, nowhere else on screen",
                        "AIzaSETUPKEY" not in "\n".join(l for l in r.stdout.splitlines() if not l.startswith("QBSETUP-")))
            else:
                c.check("setup script: where service-account keys are forbidden it still delivers the API key, backups to Google stay off",
                        pub["api_key_set"] and not pub["service_account"] and not pub["storage_on"], r.stdout[-300:])
    try:
        gcloud.decode_setup_code("QBSETUP-not-base64!!")
        c.check("setup code: a damaged code is refused with a clear message", False)
    except ValueError as e:
        c.check("setup code: a damaged code is refused with a clear message", "copy the whole line" in str(e))


def first_run_tests(c):
    """A personalised copy's google-setup.json is moved into the private settings and deleted."""
    import types, gcloud
    with tempfile.TemporaryDirectory() as tmp:
        prog = os.path.join(tmp, "prog", "language"); os.makedirs(prog)
        data = os.path.join(tmp, "data"); os.makedirs(data)
        with open(os.path.join(prog, "google-setup.json"), "w") as f:
            json.dump({"api_key": "AIzaFIRSTRUNTEST000000000000000000000000"}, f)
        st = core.Store(data, "t", SCHEMA)
        diag = types.SimpleNamespace(store=st, app_id="language", app_name="Test", log=lambda *a: None, started=time.time())
        link = core.CloudLink(st, "language", "Test", lambda *a: None)
        saved = {k: os.environ.get(k) for k in ("QB_STEM_DATA", "QB_FACTS_DATA")}
        os.environ["QB_STEM_DATA"], os.environ["QB_FACTS_DATA"] = os.path.join(tmp, "stem"), os.path.join(tmp, "facts")
        try:
            core._first_run_google(link, diag, prog)
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        c.check("first run: a key shipped with a personal copy is installed for all three apps and the file is deleted",
                not os.path.exists(os.path.join(prog, "google-setup.json")) and gcloud.Settings(data).api_key().startswith("AIzaFIRSTRUN")
                and gcloud.Settings(os.path.join(tmp, "facts")).api_key().startswith("AIzaFIRSTRUN"))
        c.check("first run: the key is not written to the activity log", "AIzaFIRSTRUN" not in json.dumps(st.activities(50)))


def main():
    c = core.Checks()
    with tempfile.TemporaryDirectory() as tmp:
        st = core.Store(tmp, "t", SCHEMA)
        # 16 threads x 200 writes, each its own transaction
        errors = []

        def worker(n):
            try:
                for i in range(200):
                    with st.write() as db:
                        db.execute("INSERT INTO t(k, v) VALUES(?, ?)", ("%d-%d" % (n, i), i))
            except Exception as e:
                errors.append(repr(e))
        ts = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        c.check("16 concurrent writers, 3,200 writes, no errors", not errors and st.scalar("SELECT count(*) FROM t") == 3200, errors[:3])
        # a failing transaction leaves nothing behind
        try:
            with st.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES('partial', 1)")
                db.execute("INSERT INTO t(k, v) VALUES('0-0', 1)")       # violates UNIQUE -> whole transaction rolls back
        except Exception:
            pass
        c.check("a failed transaction is rolled back completely", st.scalar("SELECT count(*) FROM t WHERE k = 'partial'") == 0)
        b1 = st.backup("test", force=True)
        c.check("backup written and checked", b1 and os.path.exists(b1))
        c.check("unchanged data is not backed up twice", st.backup("again") == b1)
        for i in range(12):
            with st.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES(?, 0)", ("extra-%d" % i,))
            st.backup("n%d" % i, force=True)
        c.check("only the newest %d backups are kept" % core.BACKUPS_KEPT, len(st.backups()) == core.BACKUPS_KEPT)
        good = st.backups()[0]["path"]
        st.conn().close()
        st._local.db = None
        # damage the database file
        with open(st.path, "r+b") as f:
            f.seek(0)
            f.write(b"\x00" * 100)
        for ext in ("-wal", "-shm"):
            if os.path.exists(st.path + ext):
                os.remove(st.path + ext)
        st2 = core.Store(tmp, "t", SCHEMA)
        c.check("damaged database is detected at start-up", st2.read_only and st2.damage)
        try:
            with st2.write() as db:
                db.execute("INSERT INTO t(k, v) VALUES('x', 1)")
            c.check("damaged database refuses writes", False)
        except core.DatabaseDamaged:
            c.check("damaged database refuses writes", True)
        st2.restore(good)
        c.check("damaged file kept aside, not deleted", any(n.startswith("t.sqlite.replaced-") for n in os.listdir(tmp)))
        st3 = core.Store(tmp, "t", SCHEMA)
        c.check("restore from backup gives a working database", not st3.read_only and st3.scalar("SELECT count(*) FROM t") >= 3200)
        with st3.write() as db:
            db.execute("INSERT INTO t(k, v) VALUES('after-restore', 1)")
        c.check("writes work again after restore", st3.scalar("SELECT count(*) FROM t WHERE k = 'after-restore'") == 1)
        c.check("schema version recorded", st3.meta_get("schema_version") == "1")
        # redundancy: the backup mirror
        with tempfile.TemporaryDirectory() as mdir:
            st3.set_mirror(mdir)
            bm = st3.backup("mirror-test", force=True)
            mb = st3.mirror_backups()
            c.check("every backup gets a verified copy in the mirror", mb and mb[0]["name"] == os.path.basename(bm) and core._sha256(mb[0]["path"]) == core._sha256(bm))
            os.remove(bm)
            st3.conn().close(); st3._local.db = None
            st3.restore(mb[0]["path"])
            st4 = core.Store(tmp, "t", SCHEMA)
            c.check("a mirror copy restores the database when the primary backup is gone", not st4.read_only and st4.scalar("SELECT count(*) FROM t WHERE k = 'after-restore'") == 1)
            try:
                st4.set_mirror(os.path.join(tmp, "inside"))
                c.check("a mirror inside the data folder is refused", False)
            except core.UserError:
                c.check("a mirror inside the data folder is refused", True)
            st4.set_mirror("off")
            c.check("the mirror can be switched off", st4.mirror_dir() is None)
    range_tests(c)
    power_tests(c)
    monitoring_tests(c)
    google_tests(c)
    setup_script_tests(c)
    first_run_tests(c)
    for app in ("language", "stem", "facts"):
        c.check("%s carries the current core" % app, core.core_matches_master(os.path.join(ROOT, app)))
        c.check("%s carries the current Google module" % app, open(os.path.join(ROOT, app, "gcloud.py"), "rb").read() == open(os.path.join(ROOT, "_core", "gcloud.py"), "rb").read())
    return c.report("Shared core")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
