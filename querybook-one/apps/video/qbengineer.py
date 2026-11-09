"""qbengineer — the Engineer: QueryBook reads its own program, suggests improvements to itself, and changes nothing until
the admin approves. No AI model: its programming skills are deterministic program analysis.

Skills (each a stated rule with the reason for it; the admin's decisions teach it which ones are wanted)
  Python, read with the language's own parser (ast): imports never used (fix), comparisons to None with == (fix),
  bare "except:" that also swallows Ctrl+C and shutdown (fix), mutable default arguments (advice), very long or very
  branchy functions (advice), notes left in the code — TODO / FIXME (advice).
  JavaScript (the pages): console.log and debugger left in (fix), functions defined but never used anywhere (advice).
  The running program: errors in its own log, by the file and line they came from (advice), and work that is slow,
  from its own activity record (advice).

Every suggestion is a proposal with its evidence. A fix carries the exact change (a unified diff). Nothing is applied
without the admin passphrase; then the change is first made in a copy of the program, compiled, and the program's whole
self-test is run on that copy. Only if it passes is the change made for real — the original files backed up, a revert
one click away, the result recorded. A shared core file is changed in every application that carries it (and in the
master copy when present). Advice, when approved, becomes a to-do item with its evidence.

Learning: per skill, the Engineer counts what the admin approves and rejects; proposals are ranked by that record, and
a skill the admin has rejected three times without approving any is muted (its new findings are kept, out of the way,
until the admin unmutes it). Standard library only.
"""
import ast, datetime, difflib, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading

import qbcore as core

VERSION = "1.0.0"
SCHEMA = ["""
CREATE TABLE proposals (
  id INTEGER PRIMARY KEY, fp TEXT NOT NULL UNIQUE, skill TEXT NOT NULL, file TEXT, line INTEGER, title TEXT NOT NULL, rationale TEXT,
  evidence TEXT, patch TEXT, fixable INTEGER NOT NULL, severity INTEGER NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
  decided TEXT, note TEXT, applied TEXT, test TEXT, backup TEXT, seen TEXT NOT NULL);
CREATE TABLE skill_stats (
  skill TEXT PRIMARY KEY, proposed INTEGER NOT NULL DEFAULT 0, approved INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
  applied INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0);
"""]

SKILLS = [
    {"id": "py-unused-import", "lang": "Python", "kind": "fix", "severity": 2, "name": "Imports never used",
     "why": "An unused import slows start-up, hides real dependencies and can fail on a computer that lacks the module."},
    {"id": "py-none-compare", "lang": "Python", "kind": "fix", "severity": 2, "name": "== None / != None",
     "why": "None is a single object: 'is None' is the correct test; '==' can be fooled by objects that redefine equality."},
    {"id": "py-bare-except", "lang": "Python", "kind": "fix", "severity": 3, "name": "Bare except:",
     "why": "A bare except also catches Ctrl+C and shutdown, so the program cannot be stopped cleanly; 'except Exception' does not."},
    {"id": "py-mutable-default", "lang": "Python", "kind": "advice", "severity": 3, "name": "Mutable default argument",
     "why": "A list or dict default is created once and shared by every call: changes leak from one call into the next."},
    {"id": "py-long-function", "lang": "Python", "kind": "advice", "severity": 1, "name": "Very long function",
     "why": "Functions over ~120 lines are hard to test and to change safely; split them into named steps."},
    {"id": "py-complex-function", "lang": "Python", "kind": "advice", "severity": 2, "name": "Very branchy function",
     "why": "Many branches (if/for/while/try/and/or) multiply the paths to test; simplify or split."},
    {"id": "code-todo", "lang": "Python/JavaScript", "kind": "advice", "severity": 1, "name": "TODO / FIXME left in the code",
     "why": "A note to finish something is unfinished work: do it or remove the note."},
    {"id": "js-console", "lang": "JavaScript", "kind": "fix", "severity": 1, "name": "console.log / debugger left in",
     "why": "Debug output slows the page and a debugger statement stops it whenever the developer tools are open."},
    {"id": "js-unused-function", "lang": "JavaScript", "kind": "advice", "severity": 1, "name": "Page function never used",
     "why": "A function nothing calls is dead weight in every page load and misleads whoever reads the code."},
    {"id": "run-errors", "lang": "the running program", "kind": "advice", "severity": 4, "name": "Errors in its own log",
     "why": "An error that happens in use, traced to the file and line it came from, is the most valuable thing to fix."},
    {"id": "run-slow", "lang": "the running program", "kind": "advice", "severity": 2, "name": "Slow work",
     "why": "Work that regularly takes many seconds, from the program's own activity record, is where speed matters."},
]
SKILL = {s["id"]: s for s in SKILLS}
CORE_FILES = ("qbcore.py", "qbcommons.py", "qbharvest.py", "qbonline.py", "qbdevices.py", "qbagents.py", "qbartifact.py", "qbengineer.py",
              "gcloud.py", os.path.join("ui", "qb.js"), os.path.join("ui", "qb.css"))
SKIP_DIRS = {"__pycache__", "vendor", "data", "backups", "espeak", "avatars_starter", "node_modules", ".git"}
MAX_FILE = 1_500_000


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Finding:
    def __init__(self, skill, file, line, key, title, rationale, evidence="", new_text=None):
        self.skill, self.file, self.line, self.key, self.title, self.rationale, self.evidence, self.new_text = \
            skill, file, line, key, title, rationale, evidence, new_text

    @property
    def fp(self):
        return hashlib.sha256(("%s|%s|%s" % (self.skill, self.file, self.key)).encode("utf-8")).hexdigest()[:24]


# ============================================================================ Python skills
def _lines(text):
    return text.split("\n")


def py_findings(rel, text):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [Finding("run-errors", rel, e.lineno or 1, "syntax", "The file does not parse: %s" % e.msg, "A syntax error stops the program.")]
    out, L = [], _lines(text)
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, ast.Attribute):
            b = n
            while isinstance(b, ast.Attribute):
                b = b.value
            if isinstance(b, ast.Name):
                used.add(b.id)
    exported = set(re.findall(r"""['"](\w+)['"]""", " ".join(L[i] for i in range(len(L)) if "__all__" in L[i])))
    alone = set()                                                # an import that is a block's only statement stays (the block needs it)
    for n in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            b = getattr(n, field, None)
            if isinstance(b, list) and len(b) == 1 and isinstance(b[0], (ast.Import, ast.ImportFrom)) and not isinstance(n, ast.Module):
                alone.add(id(b[0]))
    guarded = set()                                              # imports inside try: (availability checks) are left alone
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            for b in n.body:
                for m in ast.walk(b):
                    if isinstance(m, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(m))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)) and id(n) not in guarded and getattr(n, "module", None) != "__future__":
            if n.lineno != getattr(n, "end_lineno", n.lineno) or ";" in L[n.lineno - 1]:
                continue                                         # only single-line statements are rewritten
            names = [(a.asname or a.name).split(".")[0] for a in n.names]
            unused = [a for a, nm in zip(n.names, names) if nm != "*" and nm not in used and nm not in exported]
            if not unused:
                continue
            line = L[n.lineno - 1]
            keep = [a for a in n.names if a not in unused]
            ind = line[:len(line) - len(line.lstrip())]
            fmt = lambda a: a.name + (" as " + a.asname if a.asname else "")
            if keep:
                new_line = ind + ("import " if isinstance(n, ast.Import) else "from %s%s import " % ("." * n.level, n.module or "")) + ", ".join(fmt(a) for a in keep)
                if "#" in line:                                  # keep the line's own comment
                    new_line += "  " + line[line.index("#"):]
                nl = L[:n.lineno - 1] + [new_line] + L[n.lineno:]
            elif id(n) in alone:
                continue
            else:
                nl = L[:n.lineno - 1] + L[n.lineno:]
            gone = ", ".join(fmt(a) for a in unused)
            out.append(Finding("py-unused-import", rel, n.lineno, "import:" + gone + "@" + line.strip(), "Remove unused import: " + gone,
                               "Nothing in %s uses %s." % (rel, gone), line.strip(), "\n".join(nl)))
        elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in n.ops) and \
                any(isinstance(c, ast.Constant) and c.value is None for c in n.comparators):
            line = L[n.lineno - 1]
            if line.count("== None") + line.count("!= None") == 1:
                new = line.replace("!= None", "is not None").replace("== None", "is None")
                out.append(Finding("py-none-compare", rel, n.lineno, "none:" + line.strip(), "Compare to None with 'is'", SKILL["py-none-compare"]["why"],
                                   line.strip(), "\n".join(L[:n.lineno - 1] + [new] + L[n.lineno:])))
        elif isinstance(n, ast.ExceptHandler) and n.type is None:
            line = L[n.lineno - 1]
            if re.match(r"^\s*except\s*:", line):
                new = re.sub(r"^(\s*)except\s*:", r"\1except Exception:", line, count=1)
                out.append(Finding("py-bare-except", rel, n.lineno, "except:%d:%s" % (sum(1 for x in L[:n.lineno] if x.strip().startswith("except")), line.strip()),
                                   "Catch Exception instead of everything", SKILL["py-bare-except"]["why"], line.strip(), "\n".join(L[:n.lineno - 1] + [new] + L[n.lineno:])))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.args.defaults + n.args.kw_defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    out.append(Finding("py-mutable-default", rel, n.lineno, "mut:" + n.name, "Mutable default argument in %s()" % n.name,
                                       SKILL["py-mutable-default"]["why"] + " Use None and create it inside.", L[n.lineno - 1].strip()))
                    break
            size = (getattr(n, "end_lineno", n.lineno) or n.lineno) - n.lineno + 1
            if size > 120:
                out.append(Finding("py-long-function", rel, n.lineno, "long:" + n.name, "%s() is %d lines long" % (n.name, size),
                                   SKILL["py-long-function"]["why"], "def %s(...) — lines %d–%d" % (n.name, n.lineno, n.end_lineno)))
            branches = sum(1 for m in ast.walk(n) if isinstance(m, (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.IfExp, ast.ExceptHandler, ast.comprehension)))
            if branches > 40:
                out.append(Finding("py-complex-function", rel, n.lineno, "complex:" + n.name, "%s() has %d branches" % (n.name, branches),
                                   SKILL["py-complex-function"]["why"], "def %s(...)" % n.name))
    out += todo_findings(rel, L, "#")
    return out


def todo_findings(rel, L, mark):
    out = []
    for i, line in enumerate(L, 1):
        m = re.search(re.escape(mark) + r"\s*(TODO|FIXME|XXX)\b[:\s]*(.*)", line)
        if m:
            out.append(Finding("code-todo", rel, i, "todo:" + line.strip(), "%s: %s" % (m.group(1), m.group(2).strip()[:80] or "(no text)"),
                               SKILL["code-todo"]["why"], line.strip()))
    return out


# ============================================================================ JavaScript skills
def js_findings(rel, text, others):
    out, L = [], _lines(text)
    for i, line in enumerate(L, 1):
        s = line.strip()
        if re.match(r"^(console\.(log|debug)\(.*\);?|debugger;?)$", s):
            k = sum(1 for x in L[:i] if x.strip() == s)
            out.append(Finding("js-console", rel, i, "con:%d:%s" % (k, s), "Remove debug line: " + s[:60], SKILL["js-console"]["why"], s,
                               "\n".join(L[:i - 1] + L[i:])))
    defs = [(m.group(1), text[:m.start()].count("\n") + 1) for m in re.finditer(r"(?m)^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", text)]
    for name, ln in defs:
        uses = len(re.findall(r"(?<![\w$.])" + re.escape(name) + r"(?![\w$])", text)) - 1 + sum(len(re.findall(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", o)) for o in others)
        if uses <= 0:
            out.append(Finding("js-unused-function", rel, ln, "unusedfn:" + name, "Page function %s() is never used" % name,
                               SKILL["js-unused-function"]["why"], "function %s(…) in %s" % (name, rel)))
    out += todo_findings(rel, L, "//")
    return out


# ============================================================================ the Engineer
class Engineer:
    def __init__(self, app_folder, app_id, program_dir, log=None, store=None):
        self.folder = os.path.join(app_folder, "engineer")
        os.makedirs(self.folder, exist_ok=True)
        self.store = core.Store(self.folder, "engineer", SCHEMA, log)
        self.app_id, self.program_dir, self.log = app_id, os.path.abspath(program_dir), (log or (lambda *a: None))
        self.app_store = store                                   # the application's own database (its activity record)
        self.approvals = None
        self.enabled = None                                      # the Agents tab's pick (on / off)
        self.job = None
        self._lock = threading.Lock()

    # ---- reading its own program
    def _files(self):
        out = []
        for root, dirs, files in os.walk(self.program_dir):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for fn in sorted(files):
                if fn.endswith((".py", ".js", ".html", ".mjs")):
                    p = os.path.join(root, fn)
                    if os.path.getsize(p) <= MAX_FILE:
                        out.append(p)
        return out

    def _rel(self, p):
        return os.path.relpath(p, self.program_dir).replace(os.sep, "/")

    def _read(self, rel):
        with open(os.path.join(self.program_dir, rel), encoding="utf-8") as f:
            return f.read()

    def analyse(self):
        files = self._files()
        texts = {}
        for p in files:
            try:
                with open(p, encoding="utf-8") as f:
                    texts[self._rel(p)] = f.read()
            except (OSError, UnicodeDecodeError):
                pass
        found = []
        page_texts = {r: t for r, t in texts.items() if r.endswith((".js", ".html", ".mjs"))}
        for rel, text in texts.items():
            if rel.endswith(".py"):
                found += py_findings(rel, text)
            elif rel.endswith(".js"):
                found += js_findings(rel, text, [t for r, t in page_texts.items() if r != rel])
        found += self._log_findings() + self._slow_findings()
        return found

    def _log_findings(self):
        path = getattr(self.log, "path", None)
        if not path:
            return []
        groups = {}
        for p in (path + ".1", path):
            if not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()[-20000:]
            last = None
            for line in lines:
                m = re.search(r'File "([^"]+)", line (\d+), in ([\w<>]+)', line)
                if m:
                    fp = os.path.abspath(m.group(1))
                    if fp.startswith(self.program_dir):
                        last = (self._rel(fp), int(m.group(2)), m.group(3))
                    continue
                e = re.match(r"^\s*(\w+(?:Error|Exception|Warning)):?\s*(.*)$", line)
                if e and last:
                    k = last + (e.group(1),)
                    g = groups.setdefault(k, {"n": 0, "msg": e.group(2)[:200]})
                    g["n"] += 1
                    last = None
        out = []
        for (rel, ln, fn, exc), g in groups.items():
            out.append(Finding("run-errors", rel, ln, "err:%s:%d:%s" % (rel, ln, exc), "%s in %s() — %d time(s) in use" % (exc, fn, g["n"]),
                               SKILL["run-errors"]["why"], "%s:%d  %s: %s" % (rel, ln, exc, g["msg"])))
        return out

    def _slow_findings(self):
        st = self.app_store
        if st is None:
            return []
        try:
            rows = st.query("""SELECT task, COUNT(*) AS n, AVG(ms) AS avg_ms, MAX(ms) AS max_ms FROM qb_activity WHERE ms IS NOT NULL
                               GROUP BY task HAVING COUNT(*) >= 3 AND AVG(ms) > 3000 ORDER BY AVG(ms) DESC LIMIT 10""")
        except Exception:
            return []
        return [Finding("run-slow", None, None, "slow:" + r["task"], "“%s” takes %.1f s on average" % (r["task"], r["avg_ms"] / 1000),
                        SKILL["run-slow"]["why"], "%d runs, average %.1f s, longest %.1f s" % (r["n"], r["avg_ms"] / 1000, r["max_ms"] / 1000)) for r in rows]

    # ---- proposals
    def _stats(self):
        return {r["skill"]: r for r in self.store.query("SELECT * FROM skill_stats")}

    def scan(self):
        """Read the program and its records; new findings become proposals (findings already decided are not repeated)."""
        if self.enabled and not self.enabled():
            raise core.UserError("The Engineer is switched off — turn it on under Agents → Pick your agents.")
        found = self.analyse()
        stats, now, new = self._stats(), _now(), 0
        with self.store.write() as db:
            seen = set()
            for f in found:
                if f.fp in seen:
                    continue
                seen.add(f.fp)
                sk = SKILL[f.skill]
                patch = None
                if f.new_text is not None:
                    old = self._read(f.file)
                    patch = "".join(difflib.unified_diff(old.splitlines(True), (f.new_text + ("" if f.new_text.endswith("\n") or not old.endswith("\n") else "")).splitlines(True),
                                                         "a/" + f.file, "b/" + f.file, n=2))
                row = db.execute("SELECT id, status FROM proposals WHERE fp = ?", (f.fp,)).fetchone()
                if row:
                    db.execute("UPDATE proposals SET seen = ?, line = ?, patch = COALESCE(?, patch) WHERE id = ? AND status IN ('open','muted')",
                               (now, f.line, patch, row[0]))
                    continue
                muted = (stats.get(f.skill) or {}).get("muted")
                db.execute("""INSERT INTO proposals(fp, skill, file, line, title, rationale, evidence, patch, fixable, severity, status, created, seen)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (f.fp, f.skill, f.file, f.line, f.title, f.rationale, f.evidence, patch,
                                                                    1 if patch else 0, sk["severity"], "muted" if muted else "open", now, now))
                db.execute("INSERT INTO skill_stats(skill, proposed) VALUES(?, 1) ON CONFLICT(skill) DO UPDATE SET proposed = proposed + 1", (f.skill,))
                new += 1
            # findings that are gone (fixed by other means) close themselves
            gone = [r[0] for r in db.execute("SELECT id, fp FROM proposals WHERE status IN ('open','muted')").fetchall() if r[1] not in seen]
            for pid in gone:
                db.execute("UPDATE proposals SET status = 'resolved', decided = ?, note = 'no longer found' WHERE id = ?", (now, pid))
        return {"found": len(seen), "new": new, "resolved": len(gone)}

    def proposals(self, status=None, limit=300):
        stats = self._stats()
        rows = self.store.query("SELECT id, skill, file, line, title, rationale, evidence, fixable, severity, status, created, decided, note, applied FROM proposals" +
                                (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?", ((status, limit) if status else (limit,)))
        for r in rows:                                           # ranked by severity and by what the admin has wanted before
            s = stats.get(r["skill"]) or {}
            r["priority"] = round(r["severity"] * (1 + s.get("approved", 0)) / (1 + s.get("rejected", 0)), 2)
            r["skill_name"] = SKILL[r["skill"]]["name"]
        order = {"testing": 0, "open": 1, "accepted": 2, "failed": 3, "applied": 4}
        rows.sort(key=lambda r: (order.get(r["status"], 9), -r["priority"], r["id"]))
        return rows

    def proposal(self, pid):
        r = self.store.one("SELECT * FROM proposals WHERE id = ?", (int(pid),))
        if not r:
            raise core.UserError("No such proposal.")
        r["skill_info"] = SKILL[r["skill"]]
        r["test"] = json.loads(r["test"]) if r["test"] else None
        return r

    def status(self):
        stats = self._stats()
        counts = {r["status"]: r["n"] for r in self.store.query("SELECT status, COUNT(*) AS n FROM proposals GROUP BY status")}
        return {"version": VERSION, "skills": [dict(s, stats=stats.get(s["id"]) or {}) for s in SKILLS], "counts": counts, "job": self.job,
                "admin_set": bool(self.approvals and self.approvals.admin_set()), "program_dir": self.program_dir}

    def _admin(self, passphrase):
        if self.approvals is None or not self.approvals.admin_set():
            raise core.UserError("Set the admin passphrase first (Harvesting tab → Admin): every improvement needs the admin's approval.")
        self.approvals._require(passphrase or "")

    def _stat(self, db, skill, col):
        db.execute("INSERT INTO skill_stats(skill) VALUES(?) ON CONFLICT(skill) DO NOTHING", (skill,))
        db.execute("UPDATE skill_stats SET %s = %s + 1 WHERE skill = ?" % (col, col), (skill,))

    def reject(self, pid, passphrase, note=""):
        self._admin(passphrase)
        p = self.proposal(pid)
        if p["status"] not in ("open", "muted", "accepted", "failed"):
            raise core.UserError("This proposal is %s." % p["status"])
        with self.store.write() as db:
            db.execute("UPDATE proposals SET status = 'rejected', decided = ?, note = ? WHERE id = ?", (_now(), str(note or "")[:300], p["id"]))
            self._stat(db, p["skill"], "rejected")
            s = db.execute("SELECT approved, rejected FROM skill_stats WHERE skill = ?", (p["skill"],)).fetchone()
            if s and s[1] >= 3 and s[0] == 0:                    # the admin keeps saying no to this kind of suggestion
                db.execute("UPDATE skill_stats SET muted = 1 WHERE skill = ?", (p["skill"],))
                db.execute("UPDATE proposals SET status = 'muted' WHERE skill = ? AND status = 'open'", (p["skill"],))
        return self.proposal(pid)

    def unmute(self, skill, passphrase):
        self._admin(passphrase)
        with self.store.write() as db:
            db.execute("UPDATE skill_stats SET muted = 0 WHERE skill = ?", (skill,))
            db.execute("UPDATE proposals SET status = 'open' WHERE skill = ? AND status = 'muted'", (skill,))
        return {"skill": skill, "muted": False}

    def approve(self, pid, passphrase, note="", wait=False):
        """The admin approves. Advice becomes a to-do item; a fix is tested on a copy of the program and applied only if
        the whole self-test passes."""
        self._admin(passphrase)
        p = self.proposal(pid)
        if p["status"] not in ("open", "muted", "failed"):
            raise core.UserError("This proposal is %s." % p["status"])
        with self.store.write() as db:
            self._stat(db, p["skill"], "approved")
            if not p["fixable"]:
                db.execute("UPDATE proposals SET status = 'accepted', decided = ?, note = ? WHERE id = ?", (_now(), str(note or "")[:300], p["id"]))
        if not p["fixable"]:
            return self.proposal(pid)
        with self._lock:
            if self.job and self.job.get("state") == "running":
                raise core.UserError("Another change is being tested — wait for it to finish.")
            self.job = {"proposal": p["id"], "state": "running", "step": "preparing", "started": _now()}
        with self.store.write() as db:
            db.execute("UPDATE proposals SET status = 'testing', decided = ?, note = ? WHERE id = ?", (_now(), str(note or "")[:300], p["id"]))
        t = threading.Thread(target=self._apply, args=(p["id"],), name="engineer-apply", daemon=True)
        t.start()
        if wait:
            t.join()
        return self.proposal(pid)

    def _regenerate(self, p):
        """The change, made again on the file as it is now (other approved changes may have touched it)."""
        text = self._read(p["file"])
        fs = py_findings(p["file"], text) if p["file"].endswith(".py") else js_findings(p["file"], text, [
            open(f, encoding="utf-8").read() for f in self._files() if f.endswith((".js", ".html", ".mjs")) and self._rel(f) != p["file"]])
        for f in fs:
            if f.fp == p["fp"] and f.new_text is not None:
                return text, f.new_text
        return text, None

    def _targets(self, rel):
        """Where the file lives: here, and — for a shared core file — in the sibling applications and the master copy."""
        out = [os.path.join(self.program_dir, rel)]
        if rel.replace("/", os.sep) in CORE_FILES:
            root = os.path.dirname(self.program_dir)
            master = os.path.join(root, "_core", rel)
            if os.path.isfile(master):
                out.append(master)
            for d in sorted(os.listdir(root)):
                q = os.path.join(root, d, rel)
                if d != os.path.basename(self.program_dir) and os.path.isfile(os.path.join(root, d, "app.py")) and os.path.isfile(q):
                    out.append(q)
        return out

    def _step(self, s):
        if self.job:
            self.job["step"] = s

    def _apply(self, pid):
        p = self.proposal(pid)
        result = {"steps": []}
        stage = None
        try:
            old, new = self._regenerate(p)
            if new is None:
                raise RuntimeError("the finding is no longer in the file — nothing to change")
            new = new + ("\n" if old.endswith("\n") and not new.endswith("\n") else "")
            self._step("copying the program")
            stage = tempfile.mkdtemp(prefix="qb-engineer-")
            copy = os.path.join(stage, os.path.basename(self.program_dir))
            shutil.copytree(self.program_dir, copy, ignore=shutil.ignore_patterns("__pycache__", "data", "backups"))
            with open(os.path.join(copy, p["file"]), "w", encoding="utf-8") as f:
                f.write(new)
            self._step("checking the changed file")
            if p["file"].endswith(".py"):
                compile(new, p["file"], "exec")
            elif p["file"].endswith(".js") and shutil.which("node"):
                r = subprocess.run(["node", "--check", os.path.join(copy, p["file"])], capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    raise RuntimeError("the changed page script does not parse: " + (r.stderr or "")[-300:])
            result["steps"].append("the changed file compiles")
            self._step("running the whole self-test on the changed copy")
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
            r = subprocess.run([sys.executable, "-B", os.path.join(copy, "app.py"), "--selftest"], cwd=copy, capture_output=True, text=True, timeout=1500, **kw)
            out = (r.stdout or "") + (r.stderr or "")
            tail = [l for l in out.splitlines() if "checks passed" in l or "[FAIL]" in l][-12:]
            result["selftest"] = {"passed": r.returncode == 0, "summary": tail}
            if r.returncode != 0:
                raise RuntimeError("the self-test failed on the changed copy — nothing was changed")
            result["steps"].append("the whole self-test passed on the changed copy")
            self._step("applying, with a backup")
            bdir = os.path.join(self.folder, "backups", "%05d" % p["id"])
            os.makedirs(bdir, exist_ok=True)
            manifest = []
            for k, tgt in enumerate(self._targets(p["file"])):
                with open(tgt, encoding="utf-8") as f:
                    cur = f.read()
                if cur != old:                                   # a sibling copy that differs is left alone (and said so)
                    result["steps"].append("left unchanged (it differs): " + tgt)
                    continue
                b = os.path.join(bdir, "%d-%s" % (k, os.path.basename(tgt)))
                shutil.copy2(tgt, b)
                with open(tgt, "w", encoding="utf-8") as f:
                    f.write(new)
                manifest.append({"target": tgt, "backup": b, "sha_after": _sha(new)})
                result["steps"].append("changed: " + tgt)
            with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            result["restart"] = "Restart QueryBook to run the improved program."
            with self.store.write() as db:
                db.execute("UPDATE proposals SET status = 'applied', applied = ?, test = ?, backup = ? WHERE id = ?", (_now(), json.dumps(result), bdir, p["id"]))
                self._stat(db, p["skill"], "applied")
            self.log("engineer: applied proposal", p["id"], p["title"])
            self.job = {"proposal": p["id"], "state": "done", "step": "applied", "ended": _now()}
        except Exception as e:
            result["error"] = str(e)
            with self.store.write() as db:
                db.execute("UPDATE proposals SET status = 'failed', test = ? WHERE id = ?", (json.dumps(result), p["id"]))
                self._stat(db, p["skill"], "failed")
            self.log("engineer: proposal", p["id"], "not applied:", e)
            self.job = {"proposal": p["id"], "state": "failed", "step": str(e)[:200], "ended": _now()}
        finally:
            if stage:
                shutil.rmtree(stage, ignore_errors=True)

    def revert(self, pid, passphrase):
        self._admin(passphrase)
        p = self.proposal(pid)
        if p["status"] != "applied" or not p["backup"]:
            raise core.UserError("Only an applied change can be reverted.")
        with open(os.path.join(p["backup"], "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        notes = []
        for m in manifest:
            with open(m["target"], encoding="utf-8") as f:
                cur = f.read()
            if _sha(cur) != m["sha_after"]:
                notes.append("changed again since — restored anyway: " + m["target"])
            shutil.copy2(m["backup"], m["target"])
        with self.store.write() as db:
            db.execute("UPDATE proposals SET status = 'reverted', note = ? WHERE id = ?", ("; ".join(notes)[:300] or "restored from the backup", p["id"]))
        self.log("engineer: reverted proposal", p["id"])
        return self.proposal(pid)

    def done(self, pid, passphrase):
        """An accepted piece of advice has been carried out."""
        self._admin(passphrase)
        with self.store.write() as db:
            db.execute("UPDATE proposals SET status = 'done', applied = ? WHERE id = ? AND status = 'accepted'", (_now(), int(pid)))
        return self.proposal(pid)


def add_routes(api, eng):
    g, p = api.get, api.post
    g("/api/engineer/status")(lambda q: eng.status())
    p("/api/engineer/scan")(lambda q: eng.scan())
    g("/api/engineer/proposals")(lambda q: {"proposals": eng.proposals(q.get("status") or None)})
    g("/api/engineer/proposal")(lambda q: eng.proposal(q.get("id")))
    p("/api/engineer/approve")(lambda q: eng.approve(q.get("id"), q.get("passphrase"), q.get("note")))
    p("/api/engineer/reject")(lambda q: eng.reject(q.get("id"), q.get("passphrase"), q.get("note")))
    p("/api/engineer/revert")(lambda q: eng.revert(q.get("id"), q.get("passphrase")))
    p("/api/engineer/done")(lambda q: eng.done(q.get("id"), q.get("passphrase")))
    p("/api/engineer/unmute")(lambda q: eng.unmute(q.get("skill"), q.get("passphrase")))


def attach(app, app_id, program_dir):
    """Give an application its Engineer. Never stops the application if it cannot be opened."""
    try:
        app.engineer = Engineer(app.folder, app_id, program_dir, app.log, getattr(app, "store", None))
        app.engineer.approvals = getattr(getattr(app, "commons", None), "approvals", None)
        hub = getattr(app, "agents", None)
        if hub is not None:
            app.engineer.enabled = lambda: hub.settings()["enabled"].get("engineer", True)
        add_routes(app.api, app.engineer)
    except Exception as e:
        app.log("engineer unavailable:", repr(e))
        app.engineer = None
    return app.engineer
