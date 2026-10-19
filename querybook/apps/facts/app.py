#!/usr/bin/env python3
"""QueryBook History & News — a dedicated application for facts from sources written by people.

Every fact carries its sources: a book, an encyclopedia, a newspaper, a government record, an
archive. Sources from AI services are refused. Facts that disagree are kept side by side and
marked disputed — the application never picks a winner on its own. News headlines from feeds
you choose are stored as what an outlet reported, not as established fact, until you add them.

Start:      python app.py            (opens http://127.0.0.1:8103/)
Self-test:  python app.py --selftest
More:       python app.py --help
"""
import csv, io, json, os, re, sqlite3, sys, tempfile, urllib.parse

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import qbcore as core
import qbcommons as cm
import qbdevices
import harvest
import gcloud
import dates
import sources as S

APP_ID = "facts"
APP_NAME = "QueryBook History & News"
VERSION = "1.8.0"
PORT = 8103
program_dir = HERE

CATEGORIES = ["History", "News", "People", "Places", "Science history", "Culture", "Art", "Politics and law", "Sport", "Other"]
SINGLE_VALUED = {"born on", "died on", "born in", "died in", "date", "happened on", "took place on", "founded on", "founded in",
                 "signed on", "began on", "ended on", "capital", "opened on", "closed on", "elected on", "crowned on", "launched on",
                 "date of birth", "date of death", "place of birth", "place of death", "inception", "year"}
DETERMINISTIC_OLD = {"equals", "area", "circumference", "perimeter", "in_century", "in_decade", "is_leap_year", "days_in_common_year", "hex"}
OLD_SKIP_SOURCES = {"SRC-NEWS-SAMPLE"}          # bundled example headlines in the old prototype — not real news
OLD_KIND = "old QueryBook store (needs checking)"

SCHEMA = ["""
CREATE TABLE sources (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, url TEXT, author TEXT, published TEXT, notes TEXT,
  fingerprint TEXT NOT NULL UNIQUE, created TEXT NOT NULL
);
CREATE TABLE facts (
  id INTEGER PRIMARY KEY, statement TEXT NOT NULL, subject TEXT NOT NULL, predicate TEXT, object TEXT, category TEXT NOT NULL,
  date_text TEXT, date_sort INTEGER, date_precision TEXT, date_month INTEGER, date_day INTEGER, end_text TEXT, end_sort INTEGER,
  place TEXT, disputed INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
  created TEXT NOT NULL, updated TEXT NOT NULL
);
CREATE INDEX facts_date ON facts(date_sort);
CREATE INDEX facts_md ON facts(date_month, date_day);
CREATE INDEX facts_sp ON facts(subject, predicate);
CREATE INDEX facts_cat ON facts(category);
CREATE TABLE fact_sources (
  fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  quote TEXT, page TEXT, added TEXT NOT NULL, PRIMARY KEY (fact_id, source_id)
);
CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE, created TEXT NOT NULL, last_fetched TEXT, last_status TEXT);
CREATE TABLE headlines (
  id INTEGER PRIMARY KEY, feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE, title TEXT NOT NULL, link TEXT,
  published TEXT, summary TEXT, fetched TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE, fact_id INTEGER
);
CREATE INDEX headlines_feed ON headlines(feed_id);
CREATE TABLE imports (id INTEGER PRIMARY KEY, kind TEXT, origin TEXT, started TEXT, finished TEXT, read INTEGER, added INTEGER,
  merged INTEGER, skipped INTEGER, note TEXT)
""", """
ALTER TABLE headlines ADD COLUMN author TEXT;
"""]
YT_SEARCH = "https://www.youtube.com/results?search_query="
YT_SINGLE = "https://www.youtube.com/#videos-added-by-link"

STATUS_SQL = """CASE
  WHEN NOT EXISTS (SELECT 1 FROM fact_sources fs WHERE fs.fact_id = f.id) THEN 'needs source'
  WHEN NOT EXISTS (SELECT 1 FROM fact_sources fs JOIN sources s ON s.id = fs.source_id WHERE fs.fact_id = f.id AND s.kind <> '%s') THEN 'needs checking'
  ELSE 'sourced' END""" % OLD_KIND


class App:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.log = core.make_logger(folder, APP_ID)
        self.store = core.Store(folder, APP_ID, SCHEMA, self.log)
        self.google = gcloud.Google(gcloud.Settings(folder), self.log)
        self.fts = self._setup_fts()
        self.jobs = core.Jobs(self.log, self.store)
        self.api = core.Api()
        self.diag = core.Diagnostics(APP_ID, APP_NAME, VERSION, HERE, self.store, self.log, self.jobs, self._health)
        self.monitor = core.Monitor(folder, APP_ID, APP_NAME, VERSION, self.log)
        self.log.hooks.append(self.monitor.on_error)
        core.add_diagnostics(self.api, self.diag, self.monitor, HERE)
        self._routes()
        cm.attach(self, APP_ID, harvest.FactsAdapter(self, dates, OLD_KIND, SINGLE_VALUED))
        qbdevices.attach(self, APP_ID, PORT)
        try:
            self.store.backup("startup")
        except Exception as e:
            self.log("startup backup failed:", e)

    def _setup_fts(self):
        if self.store.read_only:
            return False
        try:
            with self.store.write() as db:
                db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(statement, subject, object, place,
                              content='facts', content_rowid='id', tokenize='unicode61 remove_diacritics 2')""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                              INSERT INTO facts_fts(rowid, statement, subject, object, place) VALUES (new.id, new.statement, new.subject, new.object, new.place); END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                              INSERT INTO facts_fts(facts_fts, rowid, statement, subject, object, place) VALUES ('delete', old.id, old.statement, old.subject, old.object, old.place); END""")
                db.execute("""CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                              INSERT INTO facts_fts(facts_fts, rowid, statement, subject, object, place) VALUES ('delete', old.id, old.statement, old.subject, old.object, old.place);
                              INSERT INTO facts_fts(rowid, statement, subject, object, place) VALUES (new.id, new.statement, new.subject, new.object, new.place); END""")
            return True
        except sqlite3.OperationalError as e:
            self.log("full-text search unavailable (using simple search):", e)
            return False

    # ------------------------------------------------------------------ sources
    def _source_id(self, db, src):
        name = (src.get("name") or "").strip()
        kind = src.get("kind") or ""
        url = (src.get("url") or "").strip()
        try:
            S.check_source(name, kind, url)
        except S.SourceError as e:
            raise core.UserError(str(e))
        fp = core.fingerprint(name, url or kind)
        row = db.execute("SELECT id FROM sources WHERE fingerprint = ?", (fp,)).fetchone()
        if row:
            return row[0]
        cur = db.execute("INSERT INTO sources(name, kind, url, author, published, notes, fingerprint, created) VALUES(?,?,?,?,?,?,?,?)",
                         (name, kind, url or None, (src.get("author") or "").strip() or None, (src.get("published") or "").strip() or None,
                          (src.get("notes") or "").strip() or None, fp, core.now_iso()))
        return cur.lastrowid

    # ------------------------------------------------------------------ facts
    def _clean(self, f):
        statement = " ".join(str(f.get("statement") or "").split())
        subject = " ".join(str(f.get("subject") or "").split())
        predicate = " ".join(str(f.get("predicate") or "").split()).lower()
        obj = " ".join(str(f.get("object") or "").split())
        if not statement and subject and predicate and obj:
            statement = "%s %s %s." % (subject, predicate, obj)
        if not statement:
            raise core.UserError("Write the fact as a sentence, for example: The Magna Carta was sealed at Runnymede in June 1215.")
        if not subject:
            raise core.UserError("Say who or what the fact is about (the subject).")
        if len(statement) > 2000:
            raise core.UserError("Keep a fact under 2,000 characters; split longer passages into several facts.")
        category = f.get("category") or "Other"
        if category not in CATEGORIES:
            raise core.UserError("Unknown category.")
        try:
            d = dates.parse(f.get("date"))
            e = dates.parse(f.get("end_date"))
        except dates.DateError as ex:
            raise core.UserError(str(ex))
        if d and e and e["sort"] < d["sort"]:
            raise core.UserError("The end date is before the start date.")
        place = " ".join(str(f.get("place") or "").split()) or None
        fp = core.fingerprint(subject, predicate, obj) if predicate and obj else core.fingerprint("statement", statement)
        return dict(statement=statement, subject=subject, predicate=predicate or None, object=obj or None, category=category,
                    date_text=d["label"] if d else None, date_sort=d["sort"] if d else None, date_precision=d["precision"] if d else None,
                    date_month=d["month"] if d else None, date_day=d["day"] if d else None, end_text=e["label"] if e else None,
                    end_sort=e["sort"] if e else None, place=place, fingerprint=fp)

    def add_fact(self, f, srcs, origin="entered by hand", db=None):
        """Add a fact with its sources. The same fact added again gains the new sources (corroboration)."""
        c = self._clean(f)
        srcs = [s for s in (srcs or []) if (s.get("name") or "").strip()]

        def run(db):
            row = db.execute("SELECT id FROM facts WHERE fingerprint = ?", (c["fingerprint"],)).fetchone()
            merged = bool(row)
            if row:
                fid = row[0]
            else:
                cols = list(c) + ["origin", "created", "updated"]
                vals = [c[k] for k in c] + [origin, core.now_iso(), core.now_iso()]
                fid = db.execute("INSERT INTO facts(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), vals).lastrowid
            for s in srcs:
                sid = self._source_id(db, s)
                db.execute("INSERT OR IGNORE INTO fact_sources(fact_id, source_id, quote, page, added) VALUES(?,?,?,?,?)",
                           (fid, sid, (s.get("quote") or "").strip() or None, (s.get("page") or "").strip() or None, core.now_iso()))
            self._mark_disputes(db, c["subject"], c["predicate"])
            return fid, merged
        if db is not None:
            return run(db)
        with self.store.write() as d:
            return run(d)

    def _mark_disputes(self, db, subject, predicate):
        if not predicate or predicate not in SINGLE_VALUED:
            return
        rows = db.execute("SELECT id, object FROM facts WHERE lower(subject) = lower(?) AND predicate = ?", (subject, predicate)).fetchall()
        distinct = {core.norm(r[1]) for r in rows}
        flag = 1 if len(distinct) > 1 else 0
        db.executemany("UPDATE facts SET disputed = ? WHERE id = ?", [(flag, r[0]) for r in rows])

    def update_fact(self, fid, f):
        c = self._clean(f)
        with self.store.write() as db:
            old = db.execute("SELECT subject, predicate FROM facts WHERE id = ?", (fid,)).fetchone()
            if not old:
                raise core.UserError("That fact no longer exists.")
            clash = db.execute("SELECT id FROM facts WHERE fingerprint = ? AND id <> ?", (c["fingerprint"], fid)).fetchone()
            if clash:
                raise core.UserError("The same fact already exists (number %d). Add your source to that one instead." % clash[0])
            sets = ", ".join("%s = ?" % k for k in c) + ", updated = ?"
            db.execute("UPDATE facts SET %s WHERE id = ?" % sets, [c[k] for k in c] + [core.now_iso(), fid])
            self._mark_disputes(db, old[0], old[1])
            self._mark_disputes(db, c["subject"], c["predicate"])
        return {"ok": True}

    def delete_fact(self, fid):
        with self.store.write() as db:
            old = db.execute("SELECT subject, predicate FROM facts WHERE id = ?", (fid,)).fetchone()
            if not old:
                return {"deleted": 0}
            db.execute("DELETE FROM facts WHERE id = ?", (fid,))
            db.execute("UPDATE headlines SET fact_id = NULL WHERE fact_id = ?", (fid,))
            self._mark_disputes(db, old[0], old[1])
        return {"deleted": 1}

    def fact(self, fid):
        f = self.store.one("SELECT f.*, %s AS status FROM facts f WHERE f.id = ?" % STATUS_SQL, (fid,))
        if not f:
            raise core.UserError("That fact no longer exists.")
        f["sources"] = self.store.query("""SELECT s.*, fs.quote, fs.page FROM fact_sources fs JOIN sources s ON s.id = fs.source_id
                                           WHERE fs.fact_id = ? ORDER BY s.name""", (fid,))
        f["others"] = []
        if f["predicate"]:
            f["others"] = self.store.query("""SELECT id, statement, object, date_text, disputed FROM facts
                                              WHERE lower(subject) = lower(?) AND predicate = ? AND id <> ? ORDER BY id LIMIT 20""",
                                           (f["subject"], f["predicate"], fid))
        return f

    def search(self, p):
        where, args = [], []
        q = (p.get("q") or "").strip()
        if q:
            if self.fts:
                terms = [t for t in re.findall(r"\w+", q, re.UNICODE)][:12]
                if terms:
                    where.append("f.id IN (SELECT rowid FROM facts_fts WHERE facts_fts MATCH ?)")
                    args.append(" AND ".join('"%s"*' % t.replace('"', "") for t in terms))
            else:
                for t in q.split()[:8]:
                    where.append("(f.statement LIKE ? OR f.subject LIKE ? OR f.object LIKE ? OR f.place LIKE ?)")
                    args += ["%" + t + "%"] * 4
        if p.get("category"):
            where.append("f.category = ?")
            args.append(p["category"])
        if p.get("disputed") in ("1", 1, True, "true"):
            where.append("f.disputed = 1")
        for key, op in (("from", ">="), ("to", "<=")):
            if p.get(key):
                try:
                    d = dates.parse(p[key])
                except dates.DateError as e:
                    raise core.UserError(str(e))
                where.append("f.date_sort %s ?" % op)
                args.append(d["sort"] if op == ">=" else d["sort"] + (9999 if d["precision"] in ("year", "decade", "century") else 0)
                            + (90000 if d["precision"] == "decade" else 0) + (990000 if d["precision"] == "century" else 0))
        if p.get("month") and p.get("day"):
            where.append("f.date_month = ? AND f.date_day = ?")
            args += [int(p["month"]), int(p["day"])]
        status = p.get("status")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        base = "SELECT f.id, f.statement, f.subject, f.category, f.date_text, f.date_sort, f.place, f.disputed, f.origin, %s AS status, " \
               "(SELECT count(*) FROM fact_sources fs WHERE fs.fact_id = f.id) AS source_count FROM facts f%s" % (STATUS_SQL, w)
        if status:
            base = "SELECT * FROM (%s) WHERE status = ?" % base
            args.append(status)
        order = "date_sort IS NULL, date_sort, id" if p.get("order") == "date" else "id DESC"
        limit = max(1, min(500, int(p.get("limit") or 50)))
        offset = max(0, int(p.get("offset") or 0))
        rows = self.store.query("SELECT * FROM (%s) ORDER BY %s LIMIT ? OFFSET ?" % (base, order), args + [limit, offset])
        total = self.store.scalar("SELECT count(*) FROM (%s)" % base, args, 0)
        return {"facts": rows, "total": total}

    # ------------------------------------------------------------------ news feeds
    def add_feed(self, name, url):
        try:
            if S.is_ai_url(url):
                raise S.SourceError("That address belongs to an AI service.")
            u = (url or "").strip()
            if not re.match(r"^https?://", u):
                raise S.SourceError("The feed address must start with http:// or https://")
        except S.SourceError as e:
            raise core.UserError(str(e))
        with self.store.write() as db:
            db.execute("INSERT OR IGNORE INTO feeds(name, url, created) VALUES(?,?,?)", ((name or u).strip(), u, core.now_iso()))
        return {"ok": True}

    # ------------------------------------------------------------------ YouTube (Google YouTube Data API v3): videos as "reported by" items
    def _yt_items(self, videos):
        return [{"title": v["title"], "link": v["url"], "published": v["published"], "author": v["channel"],
                 "summary": "Video by %s · %s · %s views%s%s" % (v["channel"], (v["duration"] or "").replace("PT", "").lower(), "{:,}".format(v["views"]),
                                                                " · captions" if v["captions"] else "", (" — " + v["description"][:240]) if v["description"] else "")}
                for v in videos]

    def _yt_call(self, fn):
        if not self.google.s.api_key():
            raise core.UserError("Add your Google API key first (Diagnostics → Google Cloud), with the YouTube Data API v3 enabled.")
        try:
            return fn()
        except gcloud.GoogleError as e:
            raise core.UserError("YouTube: %s" % e)

    def youtube_search_feed(self, q):
        q = " ".join(str(q or "").split())
        if not q:
            raise core.UserError("Type what to search YouTube for.")
        url = YT_SEARCH + urllib.parse.quote_plus(q)
        with self.store.write() as db:
            db.execute("INSERT OR IGNORE INTO feeds(name, url, created) VALUES(?,?,?)", ("YouTube: " + q, url, core.now_iso()))
        fid = self.store.one("SELECT id FROM feeds WHERE url = ?", (url,))["id"]
        return self.fetch_feed(fid)

    def youtube_add_video(self, link):
        vid = gcloud.youtube_id(link)
        if not vid:
            raise core.UserError("That is not a YouTube video link.")
        videos = self._yt_call(lambda: self.google.youtube_videos([vid]))
        if not videos:
            raise core.UserError("YouTube has no public video with that link.")
        with self.store.write() as db:
            db.execute("INSERT OR IGNORE INTO feeds(name, url, created) VALUES(?,?,?)", ("YouTube: videos added by link", YT_SINGLE, core.now_iso()))
        fid = self.store.one("SELECT id FROM feeds WHERE url = ?", (YT_SINGLE,))["id"]
        r = self._store_headlines(fid, self._yt_items(videos), "ok: video added")
        self.store.activity("YouTube video added", "ok", videos[0]["title"][:120])
        return dict(r, video=videos[0])

    def fetch_feed(self, feed_id):
        feed = self.store.one("SELECT * FROM feeds WHERE id = ?", (feed_id,))
        if not feed:
            raise core.UserError("No such feed.")
        if feed["url"].startswith(YT_SEARCH):
            q = urllib.parse.unquote_plus(feed["url"][len(YT_SEARCH):])
            try:
                videos = self._yt_call(lambda: self.google.youtube_search(q, 25))
            except core.UserError as e:
                with self.store.write() as db:
                    db.execute("UPDATE feeds SET last_fetched = ?, last_status = ? WHERE id = ?", (core.now_iso(), str(e), feed_id))
                raise
            return self._store_headlines(feed_id, self._yt_items(videos), "ok: %d videos" % len(videos))
        if feed["url"] == YT_SINGLE:
            return {"new_headlines": 0, "status": "videos are added one by one by link"}
        try:
            title, items = S.fetch_feed(feed["url"])
            status = "ok: %d items" % len(items)
        except S.SourceError as e:
            with self.store.write() as db:
                db.execute("UPDATE feeds SET last_fetched = ?, last_status = ? WHERE id = ?", (core.now_iso(), str(e), feed_id))
            raise core.UserError(str(e))
        return self._store_headlines(feed_id, items, status)

    def _store_headlines(self, feed_id, items, status):
        added = 0
        with self.store.write() as db:
            for it in items:
                fp = core.fingerprint(it["link"] or it["title"])
                cur = db.execute("""INSERT OR IGNORE INTO headlines(feed_id, title, link, published, summary, fetched, fingerprint, author)
                                    VALUES(?,?,?,?,?,?,?,?)""", (feed_id, it["title"], it["link"], it["published"], it["summary"], core.now_iso(), fp, it.get("author")))
                added += cur.rowcount
            db.execute("UPDATE feeds SET last_fetched = ?, last_status = ? WHERE id = ?", (core.now_iso(), status, feed_id))
        return {"new_headlines": added, "status": status}

    def promote(self, hid, p):
        h = self.store.one("SELECT h.*, f.name AS feed_name, f.url AS feed_url FROM headlines h JOIN feeds f ON f.id = h.feed_id WHERE h.id = ?", (hid,))
        if not h:
            raise core.UserError("No such headline.")
        when = p.get("date") or _feed_date(h["published"])
        fact = {"statement": p.get("statement") or h["title"], "subject": p.get("subject") or h["title"][:120], "category": p.get("category") or "News",
                "date": when, "place": p.get("place")}
        yt = h["feed_url"].startswith(YT_SEARCH) or h["feed_url"] == YT_SINGLE
        src = {"name": p.get("source_name") or (h["author"] if yt and h["author"] else h["feed_name"]),
               "kind": p.get("source_kind") or ("video channel" if yt else "newspaper"), "url": h["link"],
               "published": h["published"], "quote": h["title"]}
        if yt and not p.get("category"):
            fact["category"] = "News"
        with self.store.write() as db:
            fid, merged = self.add_fact(fact, [src], "news feed", db=db)
            db.execute("UPDATE headlines SET fact_id = ? WHERE id = ?", (fid, hid))
        return {"fact_id": fid, "merged": merged}

    # ------------------------------------------------------------------ imports
    def import_csv(self, text):
        rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        if not rows:
            raise core.UserError("The CSV has no rows. The first line must be the column names (statement, subject, date, source_name, source_kind, …).")
        errors, ok = [], []
        for i, r in enumerate(rows, start=2):
            r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            f = {k: r.get(k) for k in ("statement", "subject", "predicate", "object", "date", "end_date", "place", "category")}
            f["category"] = f.get("category") or "Other"
            src = {"name": r.get("source_name"), "kind": r.get("source_kind"), "url": r.get("source_url"), "author": r.get("source_author"),
                   "published": r.get("source_published"), "quote": r.get("quote"), "page": r.get("page")}
            try:
                self._clean(f)
                if src["name"]:
                    S.check_source(src["name"], src["kind"], src["url"])
                ok.append((f, [src] if src["name"] else []))
            except (core.UserError, S.SourceError) as e:
                errors.append({"line": i, "error": str(e)})
        if errors:
            return {"added": 0, "merged": 0, "errors": errors[:100], "error_count": len(errors),
                    "note": "Nothing was added. Fix the lines listed and import again."}
        self.store.backup("before-csv-import", force=True)
        added = merged = 0
        with self.store.write() as db:
            for f, srcs in ok:
                _, m = self.add_fact(f, srcs, "CSV import", db=db)
                merged += m
                added += not m
            db.execute("INSERT INTO imports(kind, origin, started, finished, read, added, merged, skipped, note) VALUES(?,?,?,?,?,?,?,?,?)",
                       ("csv", "CSV file", core.now_iso(), core.now_iso(), len(rows), added, merged, 0, "complete"))
        return {"added": added, "merged": merged, "errors": [], "error_count": 0}

    def import_old(self, folder, progress, stop):
        store = core.find_old_store(folder)
        if not store:
            raise core.UserError("No old QueryBook store found in that folder (looked for blocks\\ and manifest.json).")
        self.store.backup("before-import", force=True)
        read = added = merged = skipped = 0
        started = core.now_iso()
        batch = []

        def flush():
            nonlocal added, merged, skipped
            if not batch:
                return
            with self.store.write() as db:
                for f, srcs in batch:
                    try:
                        _, m = self.add_fact(f, srcs, "old QueryBook store", db=db)
                        merged += m
                        added += not m
                    except core.UserError:
                        skipped += 1
            batch.clear()

        for rec in core.iter_old_records(store, None, stop):
            read += 1
            if rec["domain"] in ("mathematics", "arithmetic", "geometry", "language") or rec["predicate"] in DETERMINISTIC_OLD:
                skipped += 1
            else:
                src = rec.get("source") or {}
                if src.get("id") in OLD_SKIP_SOURCES or rec["predicate"] == "sample_reports":
                    skipped += 1
                else:
                    pred = rec["predicate"].replace("_", " ").strip()
                    f = {"statement": "%s — %s — %s" % (rec["subject"], pred, rec["object"]), "subject": rec["subject"],
                         "predicate": pred, "object": rec["object"], "category": _category(rec["domain"])}
                    m = re.fullmatch(r"year (\d{1,4})", rec["subject"].strip())
                    if m:
                        f["date"] = m.group(1)
                        f["subject"] = rec["object"]
                        f["statement"] = "%s: %s" % (m.group(1), rec["object"])
                    url = ((rec.get("raw") or {}).get("sources") or [{}])[0].get("url") if rec.get("raw") else None
                    if url and S.is_ai_url(url):
                        skipped += 1
                        continue
                    name = src.get("name") or "old QueryBook store"
                    batch.append((f, [{"name": name, "kind": OLD_KIND, "url": url if url and re.match(r"^https?://", url) else None}]))
            if len(batch) >= 2000:
                flush()
            if read % 1000 == 0:
                progress(read, None, "read %s · added %s" % (format(read, ","), format(added, ",")))
        flush()
        note = "stopped by user" if stop() else "complete"
        with self.store.write() as db:
            db.execute("INSERT INTO imports(kind, origin, started, finished, read, added, merged, skipped, note) VALUES(?,?,?,?,?,?,?,?,?)",
                       ("old store", store, started, core.now_iso(), read, added, merged, skipped, note))
        self.store.backup("after-import", force=True)
        return {"old_store": store, "records_read": read, "added": added, "already_present": merged, "skipped": skipped, "note": note}

    # ------------------------------------------------------------------ diagnostics
    def _health(self):
        C = core._check
        out = [C("search", "Full-text search", "ok" if self.fts else "warn", "available" if self.fts else "not available in this Python; simple search is used")]
        ok = dates.parse("15 March 44 BC")["sort"] < dates.parse("AD 1")["sort"] and S.is_ai_url("https://chatgpt.com/x")
        out.append(C("rules", "Date reading and source rules", "ok" if ok else "fail"))
        if not self.store.read_only:
            bad = self.store.query("SELECT name FROM feeds WHERE last_status IS NOT NULL AND last_status NOT LIKE 'ok%'")
            out.append(C("feeds", "News feeds", "warn" if bad else "ok", ("last fetch failed for %d feed(s)" % len(bad)) if bad else "no fetch problems"))
        yl = self.google.last.get("youtube")
        if not self.google.s.api_key():
            out.append(C("youtube", "YouTube (Google)", "ok", "not set up (optional) — add the Google API key on this page"))
        else:
            out.append(C("youtube", "YouTube (Google)", "ok" if not yl or yl["ok"] else "warn",
                         ("last search %s: %s (%.2f s)" % (yl["at"], "ok" if yl["ok"] else yl["detail"], yl["seconds"])) if yl else "key set; not used yet"))
        return out

    # ------------------------------------------------------------------ routes
    def _routes(self):
        a = self.api

        @a.get("/api/status")
        def status(p):
            st = {r["status"]: r["n"] for r in self.store.query("SELECT status, count(*) n FROM (SELECT %s AS status FROM facts f) GROUP BY status" % STATUS_SQL)}
            return {"app": APP_NAME, "version": VERSION, "store": self.store.status(), "health": (self.diag.last or {}).get("overall"), "facts": st, "facts_total": sum(st.values()),
                    "disputed": self.store.scalar("SELECT count(*) FROM facts WHERE disputed = 1", default=0),
                    "sources": self.store.scalar("SELECT count(*) FROM sources", default=0), "full_text_search": self.fts,
                    "job": self.jobs.status()["state"]}

        @a.get("/api/options")
        def options(p):
            return {"categories": CATEGORIES, "source_kinds": S.KIND_ORDER[:-1], "single_valued": sorted(SINGLE_VALUED),
                    "suggested_feeds": [{"name": n, "url": u} for n, u in S.SUGGESTED_FEEDS]}

        @a.get("/api/facts")
        def facts(p):
            return self.search(p)

        @a.get("/api/fact")
        def fact(p):
            return self.fact(int(p.get("id")))

        @a.post("/api/fact/add")
        def add(p):
            fid, merged = self.add_fact(p.get("fact") or {}, p.get("sources") or [])
            return {"id": fid, "merged": merged}

        @a.post("/api/fact/update")
        def update(p):
            return self.update_fact(int(p.get("id")), p.get("fact") or {})

        @a.post("/api/fact/delete")
        def delete(p):
            return self.delete_fact(int(p.get("id")))

        @a.post("/api/fact/add-source")
        def add_source(p):
            fid = int(p.get("id"))
            with self.store.write() as db:
                if not db.execute("SELECT 1 FROM facts WHERE id = ?", (fid,)).fetchone():
                    raise core.UserError("That fact no longer exists.")
                sid = self._source_id(db, p.get("source") or {})
                s = p.get("source") or {}
                db.execute("INSERT OR IGNORE INTO fact_sources(fact_id, source_id, quote, page, added) VALUES(?,?,?,?,?)",
                           (fid, sid, (s.get("quote") or "").strip() or None, (s.get("page") or "").strip() or None, core.now_iso()))
            return {"ok": True}

        @a.post("/api/fact/remove-source")
        def remove_source(p):
            with self.store.write() as db:
                db.execute("DELETE FROM fact_sources WHERE fact_id = ? AND source_id = ?", (int(p.get("id")), int(p.get("source_id"))))
            return {"ok": True}

        @a.get("/api/sources")
        def sources(p):
            return {"sources": self.store.query("""SELECT s.*, (SELECT count(*) FROM fact_sources fs WHERE fs.source_id = s.id) AS facts
                                                  FROM sources s ORDER BY s.name LIMIT 1000""")}

        @a.get("/api/feeds")
        def feeds(p):
            return {"feeds": self.store.query("SELECT f.*, (SELECT count(*) FROM headlines h WHERE h.feed_id = f.id) AS headlines FROM feeds f ORDER BY name")}

        @a.post("/api/feeds/add")
        def feed_add(p):
            return self.add_feed(p.get("name"), p.get("url"))

        @a.post("/api/feeds/remove")
        def feed_remove(p):
            with self.store.write() as db:
                db.execute("DELETE FROM feeds WHERE id = ?", (int(p.get("id")),))
            return {"ok": True}

        @a.post("/api/feeds/fetch")
        def feed_fetch(p):
            return self.fetch_feed(int(p.get("id")))

        @a.post("/api/youtube/search")
        def yt_search(p):
            return self.youtube_search_feed(p.get("q"))

        @a.post("/api/youtube/add")
        def yt_add(p):
            return self.youtube_add_video(p.get("url"))

        @a.get("/api/headlines")
        def headlines(p):
            args, w = [], ""
            if p.get("feed"):
                w, args = " WHERE h.feed_id = ?", [int(p["feed"])]
            return {"headlines": self.store.query("""SELECT h.*, f.name AS feed_name FROM headlines h JOIN feeds f ON f.id = h.feed_id%s
                                                    ORDER BY h.id DESC LIMIT 200""" % w, args)}

        @a.post("/api/headlines/promote")
        def promote(p):
            return self.promote(int(p.get("id")), p)

        @a.post("/api/import-csv")
        def import_csv(p):
            return self.import_csv(p.get("text") or "")

        @a.get("/api/old-store-hint")
        def old_store_hint(p):
            hints = core.old_store_hints()
            return {"folder": hints[0] if hints else "", "all": hints}

        @a.get("/api/old-store")
        def old_store(p):
            s = core.find_old_store(p.get("folder", ""))
            if not s:
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains blocks\\ and manifest.json.")
            return core.old_store_summary(s)

        @a.post("/api/import-old")
        def import_old(p):
            folder = p.get("folder", "")
            if not core.find_old_store(folder):
                raise core.UserError("No old QueryBook store found there. Choose the folder that contains blocks\\ and manifest.json.")
            return self.jobs.start("Import from the old store", lambda prog, stop: self.import_old(folder, prog, stop))

        @a.get("/api/imports")
        def imports(p):
            return {"imports": self.store.query("SELECT * FROM imports ORDER BY id DESC LIMIT 20")}

        @a.get("/api/job")
        def job(p):
            return self.jobs.status()

        @a.post("/api/job/stop")
        def job_stop(p):
            self.jobs.stop()
            return {"ok": True}

        @a.post("/api/backup")
        def backup(p):
            return {"backup": os.path.basename(self.store.backup("manual", force=True) or "")}

        @a.get("/api/backups")
        def backups(p):
            return {"backups": [{"name": b["name"], "kb": b["bytes"] // 1024} for b in self.store.backups()], "folder": self.store.backup_dir}

        @a.get("/api/export.csv")
        def export_csv(p):
            buf = io.StringIO()
            w = csv.writer(buf)
            cols = ["id", "statement", "subject", "predicate", "object", "date", "end_date", "place", "category", "disputed", "status",
                    "source_name", "source_kind", "source_url", "source_author", "source_published", "quote", "page"]
            w.writerow(cols)
            rows = self.store.query("""SELECT f.*, %s AS status, s.name AS source_name, s.kind AS source_kind, s.url AS source_url,
                                       s.author AS source_author, s.published AS source_published, fs.quote, fs.page
                                       FROM facts f LEFT JOIN fact_sources fs ON fs.fact_id = f.id LEFT JOIN sources s ON s.id = fs.source_id
                                       ORDER BY f.id""" % STATUS_SQL)
            for r in rows:
                r["date"], r["end_date"] = r["date_text"], r["end_text"]
                w.writerow([r.get(c) for c in cols])
            return buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"


def _category(domain):
    return {"history": "History", "news": "News", "culture": "Culture", "art": "Art", "geography": "Places",
            "people": "People", "science": "Science history", "politics": "Politics and law", "sport": "Sport"}.get((domain or "").lower(), "Other")


def _feed_date(published):
    """RSS dates look like 'Fri, 16 Oct 2026 09:30:00 GMT'; Atom like '2026-10-16T09:30:00Z'."""
    s = published or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return "%s-%s-%s" % m.groups()
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", s)
    if m and m.group(2).lower()[:3] in dates.MONTHS:
        return "%s %s %s" % m.groups()
    return None


def open_app(folder=None):
    return App(folder or core.data_folder(APP_ID, HERE))


# ---------------------------------------------------------------------- self-test
def selftest():
    import gzip
    c = core.Checks()
    c.check("shared core matches the master copy", core.core_matches_master(HERE))
    for t, label in [("15 June 1215", "15 June 1215"), ("44 BC", "44 BC"), ("1990s", "1990s"), ("12th century", "12th century"), ("c. 1200", "c. 1200")]:
        c.check("date %s" % t, dates.parse(t)["label"] == label)
    c.check("dates sort BC before AD", dates.parse("15 March 44 BC")["sort"] < dates.parse("1 BC")["sort"] < dates.parse("AD 1")["sort"])
    for bad in ("30 February 2000", "29 February 1900", "year zero", "0"):
        try:
            dates.parse(bad)
            c.check("refuses date %s" % bad, False)
        except dates.DateError:
            c.check("refuses date %s" % bad, True)
    c.check("AI address refused", S.is_ai_url("https://chatgpt.com/share/abc") and S.is_ai_url("https://www.perplexity.ai/x"))
    c.check("ordinary address accepted", not S.is_ai_url("https://www.britannica.com/event/Magna-Carta"))
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Example Wire</title>
      <item><title>Council approves budget</title><link>https://news.example.org/a</link><pubDate>Fri, 16 Oct 2026 09:30:00 GMT</pubDate>
      <description>&lt;p&gt;The council voted 7&#8211;2.&lt;/p&gt;</description></item></channel></rss>"""
    title, items = S.parse_feed(rss)
    c.check("RSS feed read", title == "Example Wire" and items[0]["title"] == "Council approves budget" and items[0]["summary"] == "The council voted 7–2.")
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom Example</title><entry><title>Bridge reopens</title>
      <link href="https://ex.org/b"/><updated>2026-10-15T08:00:00Z</updated><summary>Repairs done.</summary></entry></feed>"""
    t2, it2 = S.parse_feed(atom)
    c.check("Atom feed read", t2 == "Atom Example" and it2[0]["link"] == "https://ex.org/b")
    try:
        S.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><title>&a;</title></channel></rss>')
        c.check("feed with XML entities refused", False)
    except S.SourceError:
        c.check("feed with XML entities refused", True)
    with tempfile.TemporaryDirectory() as tmp:
        app = App(os.path.join(tmp, "data"))
        c.check("harvest team attached to the shared database (Commons)", app.team is not None and ("GET", "/api/commons/status") in app.api.routes and ("GET", "/api/harvest/status") in app.api.routes and app.commons.registry.source("webster-1913") is not None
                and app.devices is not None and ("GET", "/api/devices/openapi.json") in app.api.routes
                and app.commons.store.path.startswith(os.environ.get("QB_COMMONS_DATA", "?")))
        book = {"name": "Magna Carta: The Foundation of Freedom 1215–2015", "kind": "book", "author": "N. Vincent (ed.)"}
        fid, merged = app.add_fact({"statement": "The Magna Carta was sealed by King John at Runnymede.", "subject": "Magna Carta",
                                    "predicate": "sealed on", "object": "15 June 1215", "date": "15 June 1215", "place": "Runnymede",
                                    "category": "History"}, [book])
        c.check("fact with a source is 'sourced'", app.fact(fid)["status"] == "sourced")
        fid2, merged2 = app.add_fact({"statement": "The Magna Carta was sealed by King John at Runnymede.", "subject": "Magna Carta",
                                      "predicate": "sealed on", "object": "15 June 1215", "category": "History"},
                                     [{"name": "British Library", "kind": "museum or library", "url": "https://www.bl.uk/magna-carta"}])
        c.check("same fact again is merged and gains a source", fid2 == fid and merged2 and len(app.fact(fid)["sources"]) == 2)
        try:
            app.add_fact({"statement": "x", "subject": "x", "category": "History"}, [{"name": "notes", "kind": "website (written by people)", "url": "https://chat.openai.com/c/1"}])
            c.check("AI source refused", False)
        except core.UserError:
            c.check("AI source refused", True)
        c.check("refused fact left nothing behind", app.search({"q": "x"})["total"] == 0)
        n1, _ = app.add_fact({"statement": "Person A was born in 1900.", "subject": "Person A", "predicate": "born on", "object": "1900",
                              "date": "1900", "category": "People"}, [{"name": "Register 1", "kind": "government record"}])
        n2, _ = app.add_fact({"statement": "Person A was born in 1901.", "subject": "Person A", "predicate": "born on", "object": "1901",
                              "date": "1901", "category": "People"}, [{"name": "Newspaper obituary", "kind": "newspaper"}])
        c.check("conflicting facts are both kept and marked disputed", app.fact(n1)["disputed"] == 1 and app.fact(n2)["disputed"] == 1)
        app.delete_fact(n2)
        c.check("dispute clears when the conflict is removed", app.fact(n1)["disputed"] == 0)
        nid, _ = app.add_fact({"statement": "An unsourced note.", "subject": "Note", "category": "Other"}, [])
        c.check("fact without a source is 'needs source'", app.fact(nid)["status"] == "needs source")
        c.check("search finds by word", app.search({"q": "runnymede"})["total"] == 1)
        c.check("search by date range", app.search({"from": "1200", "to": "1299"})["total"] == 1)
        c.check("on this day", app.search({"month": 6, "day": 15})["total"] == 1)
        r = app.import_csv("statement,subject,date,category,source_name,source_kind,source_url\n"
                           "The Berlin Wall fell.,Berlin Wall,9 November 1989,History,Encyclopaedia entry,encyclopedia,https://example.org/wall\n")
        c.check("CSV import", r["added"] == 1, r)
        r = app.import_csv("statement,subject,date,category,source_name,source_kind\nGood row,Good,1990,History,Book,book\nBad row,Bad,30 February 2000,History,Book,book\n")
        c.check("CSV with a bad line adds nothing and names the line", r["added"] == 0 and r["errors"][0]["line"] == 3, r)
        app.add_feed("Example Wire", "https://news.example.org/rss")
        feed_id = app.store.scalar("SELECT id FROM feeds")
        app._store_headlines(feed_id, items, "ok")
        hid = app.store.scalar("SELECT id FROM headlines")
        pr = app.promote(hid, {})
        pf = app.fact(pr["fact_id"])
        c.check("headline added as a news fact with its outlet as source", pf["category"] == "News" and pf["sources"][0]["name"] == "Example Wire"
                and pf["date_text"] == "16 October 2026")
        old = os.path.join(tmp, "oldstore")
        os.makedirs(os.path.join(old, "blocks"))
        recs = [({"subject": "year 1066", "predicate": "recorded_event", "object": "Norman conquest of England"}, "history", {"id": "SRC-HIST", "name": "Public-domain historical reference"}),
                ({"subject": "Mona Lisa", "predicate": "painted_by", "object": "Leonardo da Vinci"}, "art", {"id": "SRC-ART", "name": "Public-domain art reference"}),
                ({"subject": "Example Daily", "predicate": "sample_reports", "object": "a council approved a transit line"}, "news", {"id": "SRC-NEWS-SAMPLE", "name": "Bundled EXAMPLE"}),
                ({"subject": "12²", "predicate": "equals", "object": "144"}, "mathematics", {"id": "SRC-GEN"}),
                ({"subject": "year 1999", "predicate": "is_leap_year", "object": "no"}, "history", {"id": "SRC-GEN"})]
        with gzip.open(os.path.join(old, "blocks", "block_00000.jsonl.gz"), "wt", encoding="utf-8") as f:
            for n, d, s in recs:
                f.write(json.dumps({"nucleus": n, "domain": d, "sources": [s], "certification": {"trust_score": 0.9}}) + "\n")
        mtime = os.path.getmtime(os.path.join(old, "blocks", "block_00000.jsonl.gz"))
        res = app.import_old(old, lambda *a: None, lambda: False)
        c.check("old store: history and art kept, examples and maths skipped", res["added"] == 2 and res["skipped"] == 3, res)
        dated = app.search({"q": "Norman"})["facts"]
        c.check("old store: 'year 1066' becomes a dated fact", dated and dated[0]["date_text"] == "1066" and dated[0]["status"] == "needs checking", dated)
        c.check("old store untouched", os.path.getmtime(os.path.join(old, "blocks", "block_00000.jsonl.gz")) == mtime
                and not os.path.exists(os.path.join(old, "index.sqlite")))
        c.check("database integrity", app.store.scalar("PRAGMA integrity_check") == "ok")
        c.check("backups written", len(app.store.backups()) >= 2)
        c.check("user interface present", os.path.exists(os.path.join(HERE, "ui", "index.html")))
        c.check("full-text search active", app.fts)
    _youtube_selftest(c)
    return c.report(APP_NAME)


def _youtube_selftest(c):
    """YouTube as a source, against a stand-in for the YouTube Data API."""
    import http.server, threading as _th
    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("X-Goog-Api-Key")))
            if self.path.startswith("/youtube/v3/search"):
                body = {"items": [{"id": {"videoId": "AAAAAAAAAAA"}}, {"id": {"videoId": "BBBBBBBBBBB"}}]}
            else:
                ids = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))["id"].split(",")
                body = {"items": [{"id": i, "snippet": {"title": "Apollo 11 footage %s" % i[0], "channelTitle": "NASA", "channelId": "UC1",
                                                        "publishedAt": "2019-07-16T12:00:00Z", "description": "Archive film."},
                                   "contentDetails": {"duration": "PT12M5S", "caption": "true"}, "statistics": {"viewCount": "1234"}} for i in ids]}
            out = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(out))); self.end_headers()
            self.wfile.write(out)
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    saved = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy", "QB_GCP_BASE_YOUTUBE", "GOOGLE_API_KEY", "GEMINI_API_KEY")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    os.environ["QB_GCP_BASE_YOUTUBE"] = "http://127.0.0.1:%d" % srv.server_address[1]
    os.environ.pop("GOOGLE_API_KEY", None); os.environ.pop("GEMINI_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            a = App(tmp)
            try:
                a.youtube_search_feed("apollo 11")
                c.check("YouTube: without a Google key the app says what to do", False)
            except core.UserError as e:
                c.check("YouTube: without a Google key the app says what to do", "Google API key" in str(e))
            a.google.s.save({"api_key": "AIzaYTSECRET-0000000000"})
            r = a.youtube_search_feed("apollo 11")
            hs = a.store.query("SELECT * FROM headlines ORDER BY id")
            c.check("YouTube: a search becomes a feed of 'reported by' videos with channel, date and link",
                    r["new_headlines"] == 2 and hs[0]["author"] == "NASA" and hs[0]["link"].endswith("AAAAAAAAAAA") and hs[0]["fact_id"] is None)
            c.check("YouTube: the key goes to Google only in the request header", all(k == "AIzaYTSECRET-0000000000" for _, k in calls) and not any("AIzaYT" in p for p, _ in calls))
            pr = a.promote(hs[0]["id"], {})
            src = a.store.query("SELECT s.* FROM sources s JOIN fact_sources fs ON fs.source_id = s.id WHERE fs.fact_id = ?", (pr["fact_id"],))
            c.check("YouTube: 'Add as fact' records the channel as a 'video channel' source", src and src[0]["name"] == "NASA" and src[0]["kind"] == "video channel")
            v = a.youtube_add_video("https://youtu.be/CCCCCCCCCCC")
            c.check("YouTube: a single video can be added by its link", v["video"]["id"] == "CCCCCCCCCCC" and a.store.scalar("SELECT count(*) FROM headlines") == 3)
            dg = {x["id"]: x for x in a._health()}
            c.check("YouTube: diagnostics report the last search", dg["youtube"]["status"] == "ok" and "last search" in dg["youtube"]["detail"])
            c.check("YouTube: the key never appears in the activity log", "AIzaYT" not in json.dumps(a.store.activities(200)))
    finally:
        srv.shutdown()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    sys.exit(core.run_cli(sys.modules[__name__]))
