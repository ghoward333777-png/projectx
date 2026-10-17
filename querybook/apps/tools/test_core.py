#!/usr/bin/env python3
"""Tests of the shared core's data safety: concurrent writers, crash-safe transactions,
damage detection (the app refuses to write to a damaged database), backups and restore."""
import json, os, sys, tempfile, threading

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
    monitoring_tests(c)
    for app in ("language", "stem", "facts"):
        c.check("%s carries the current core" % app, core.core_matches_master(os.path.join(ROOT, app)))
    return c.report("Shared core")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
