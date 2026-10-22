"""Avatar library: talking faces made from portraits, for the Speech lab and any narration.

Every avatar is a portrait plus its 478 3D face landmarks (x, y and depth, measured in the browser by the bundled
face tracker). The page animates it with all 52 ARKit face channels from the Visual Speech Engine — jaw, lips,
cheeks, nose, eyes, gaze, blinks, brows and tongue — and turns the head in 3D using the landmarks' depth.

Whose face it is decides what is needed:
  * synthetic  — an AI-generated portrait of nobody: the admin confirms it shows no real person;
  * consented  — a real person: their name and their consent are recorded (use Author personas for their voice);
Everything an avatar says is labelled as a synthetic avatar.
"""
import base64, datetime, hashlib, json, os, re, shutil, struct, zipfile

import qbcore as core

SCHEMA = ["""
CREATE TABLE avatars (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, name TEXT NOT NULL, tags TEXT, source TEXT NOT NULL, attestation TEXT NOT NULL,
  image TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, width INTEGER, height INTEGER, landmarks TEXT, quality TEXT,
  voice TEXT, notes TEXT, hidden INTEGER NOT NULL DEFAULT 0);
""", """
CREATE TABLE delivery_flags (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, avatar_id INTEGER NOT NULL, t REAL, box TEXT, reason TEXT NOT NULL, note TEXT,
  source TEXT NOT NULL, state TEXT, script TEXT, renderer TEXT, status TEXT NOT NULL DEFAULT 'open', resolved TEXT, history TEXT);
CREATE INDEX delivery_flags_av ON delivery_flags(avatar_id, status);
CREATE TABLE delivery_checks (
  id INTEGER PRIMARY KEY, created TEXT NOT NULL, avatar_id INTEGER NOT NULL, script TEXT, duration REAL, score INTEGER, spans TEXT,
  reference TEXT, renderer TEXT);
"""]
# what a person can flag in a delivery; the first five are measured by the delivery check (and the learning loop works on
# them), the rest need a person's eyes — each flag stays open until someone marks it fixed
FLAG_REASONS = {"background": "the background moves", "region": "the forehead / head region moves for no reason",
                "lips": "lip shape (flat lower lip, swollen lips, pucker, spread)", "hair": "the hair separates from the head",
                "fold": "a smear, tear or fold in the picture", "teeth": "teeth or tongue look wrong", "sync": "the mouth is out of sync with the voice",
                "eyes": "eyes or blinks look wrong", "brows": "brows move too much or too little", "head": "head movement unnatural",
                "body": "body movement unnatural", "other": "something else (say what in the note)"}
REFERENCE_KEYS = ("brow_inner_sd", "brow_outer_sd", "blinks_per_min", "yaw_range", "pitch_range", "roll_range", "gap_mean", "gap_p90", "smile_p50", "upper_lift")
SOURCES = {"synthetic": "AI-generated portrait — shows no real person", "consented": "a real person who agreed (name and consent recorded)"}
LABEL = "Synthetic avatar — AI-generated"
MAX_BYTES = 20 * 1024 * 1024
MAX_TURN_FRAMES = 400


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _kind(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _size(data, kind):
    try:
        if kind == "png":
            return struct.unpack(">II", data[16:24])
        if kind == "jpg":
            i = 2
            while i < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                mk = data[i + 1]
                if mk in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    except struct.error:
        pass
    return None, None


def _name_from_file(fn):
    base = os.path.splitext(os.path.basename(fn))[0]
    base = re.sub(r"[_-]+", " ", base)
    base = re.sub(r"(\D)(\d+)$", r"\1 \2", base).strip()
    return base[:1].upper() + base[1:] if base else "Avatar"


def quality(landmarks, width=None, height=None, body=False):
    """What makes a portrait animate well. Returns a list of problems (empty = good)."""
    out = []
    if not landmarks or len(landmarks) < 468:
        return ["no face found — use a clear, front-facing portrait"]
    P = lambda i: landmarks[i]
    d = lambda a, b: ((P(a)[0] - P(b)[0]) ** 2 + (P(a)[1] - P(b)[1]) ** 2) ** 0.5
    if d(13, 14) > 0.08 * d(61, 291):
        out.append("mouth open in the portrait — a closed, neutral mouth animates more naturally")
    r = (P(1)[0] - P(234)[0]) / ((P(454)[0] - P(234)[0]) or 1e-6)
    if abs(r - 0.5) > 0.12:
        out.append("face turned to one side — front-facing works best")
    fh = abs(P(152)[1] - P(10)[1])
    if fh < 0.25 and not body:                                # a full-body avatar shows the whole figure on purpose
        out.append("face small in the picture (%.0f%% of its height) — crop closer for more detail" % (100 * fh))
    if len(landmarks[0]) < 3:
        out.append("no depth measured — re-analyse to enable 3D head motion")
    return out


class Library:
    def __init__(self, app_folder, log=None):
        self.folder = os.path.join(app_folder, "avatars")
        os.makedirs(self.folder, exist_ok=True)
        self.store = core.Store(self.folder, "avatars", SCHEMA, log)

    # ---------------------------------------------------------------- adding
    def add(self, data, name=None, source="synthetic", attest=False, tags=None, subject=None, consent=False, filename=None):
        if source not in SOURCES:
            raise core.UserError("Source must be 'synthetic' or 'consented'.")
        if source == "synthetic" and not attest:
            raise core.UserError("Confirm that the portrait is AI-generated and shows no real person.")
        if source == "consented" and (not consent or not (subject or "").strip()):
            raise core.UserError("A real person's face needs their name and their consent.")
        if not data or len(data) > MAX_BYTES:
            raise core.UserError("The image is empty or larger than 20 MB.")
        kind = _kind(data)
        if not kind:
            raise core.UserError("Use a PNG, JPEG or WebP image.")
        sha = hashlib.sha256(data).hexdigest()
        old = self.store.one("SELECT id FROM avatars WHERE sha256 = ?", (sha,))
        if old:
            return {"id": old["id"], "duplicate": True}
        w, h = _size(data, kind)
        att = {"source": source, "statement": SOURCES[source], "confirmed_by": "admin", "at": _now(),
               **({"subject": subject.strip()[:120], "consent": True} if source == "consented" else {})}
        name = " ".join(str(name or (_name_from_file(filename) if filename else "Avatar")).split())[:80]
        with self.store.write() as db:
            aid = db.execute("""INSERT INTO avatars(created, name, tags, source, attestation, image, sha256, width, height)
                                VALUES(?,?,?,?,?,?,?,?,?)""", (_now(), name, json.dumps(tags or []), source, json.dumps(att), "pending", sha, w, h)).lastrowid
            fn = "portrait.%s" % kind
            d = os.path.join(self.folder, str(aid))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, fn), "wb") as f:
                f.write(data)
            db.execute("UPDATE avatars SET image = ? WHERE id = ?", (fn, aid))
        return {"id": aid, "name": name, "duplicate": False}

    def install_starter(self, folder):
        """Install the bundled starter faces (already analysed) once; avatars the admin later deletes stay deleted."""
        mf = os.path.join(folder, "manifest.json")
        if not os.path.isfile(mf):
            return {"installed": 0}
        mark = os.path.join(self.folder, "starter-installed.json")
        with open(mf, encoding="utf-8") as f:
            man = json.load(f)
        for sha in man.get("removed", []):                        # withdrawn from the set: take it out of installs too
            r = self.store.one("SELECT id FROM avatars WHERE sha256 = ? AND tags LIKE '%\"starter\"%'", (sha,))
            if r:
                self.delete(r["id"])
        done = {}
        if os.path.isfile(mark):
            with open(mark, encoding="utf-8") as f:
                done = json.load(f)
        if done.get("version") == man.get("version"):
            return {"installed": 0}
        n = 0
        for a in man.get("avatars", []):
            p = os.path.join(folder, os.path.basename(a["file"]))
            if not os.path.isfile(p):
                continue
            with open(p, "rb") as f:
                r = self.add(f.read(), a.get("name"), "synthetic", True, tags=["starter"] + (["body"] if a.get("kind") == "body" else []), filename=a["file"])
            if a.get("anatomy") and not os.path.isfile(os.path.join(self.folder, str(r["id"]), "anatomy.json")):
                self.set_anatomy(r["id"], a["anatomy"])
            for old in man.get("removed_reference") or []:       # a bundled clip measured again: the earlier entry goes
                if old in {x["clip"] for x in (self.reference(r["id"]) or {"clips": []})["clips"]}:
                    self.reference_remove(r["id"], old)
            for c in a.get("reference") or []:                    # the person's own reference clips, already measured
                have = {x["clip"] for x in (self.reference(r["id"]) or {"clips": []})["clips"]}
                if c["clip"] not in have:
                    self.reference_add(r["id"], c["clip"], c["stats"], c["frames"])
            moves = ([{"slug": "turn-around", "dir": a["turn"]}] if a.get("turn") else []) + list(a.get("motions") or [])
            for mv in moves:                                     # the person's recorded moves (also added to earlier installs)
                src = os.path.join(folder, os.path.basename(mv["dir"]))
                dst = self._motion_dir(r["id"], mv["slug"])
                if os.path.isdir(src) and not os.path.isfile(self._meta_file(dst)):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
            if not r["duplicate"]:
                with self.store.write() as db:
                    att = json.loads(db.execute("SELECT attestation FROM avatars WHERE id = ?", (r["id"],)).fetchone()[0])
                    att.update(confirmed_by="bundled starter set", note=man.get("note", ""))
                    db.execute("UPDATE avatars SET attestation = ? WHERE id = ?", (json.dumps(att), r["id"]))
                if a.get("landmarks"):
                    self.set_landmarks(r["id"], a["landmarks"])
                n += 1
        with open(mark, "w", encoding="utf-8") as f:
            json.dump({"version": man.get("version"), "at": _now(), "installed": n}, f)
        return {"installed": n}

    def import_path(self, path, source="synthetic", attest=False, kind="face"):
        """A folder or a .zip of portraits on this computer (PNG / JPEG / WebP; other files are skipped)."""
        path = os.path.abspath(os.path.expanduser(path or ""))
        items = []
        if os.path.isdir(path):
            for fn in sorted(os.listdir(path)):
                p = os.path.join(path, fn)
                if os.path.isfile(p) and not os.path.islink(p) and fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    with open(p, "rb") as f:
                        items.append((fn, f.read(MAX_BYTES + 1)))
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for info in sorted(z.infolist(), key=lambda i: i.filename):
                    fn = info.filename
                    if info.is_dir() or not fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) or info.file_size > MAX_BYTES:
                        continue
                    items.append((os.path.basename(fn), z.read(info)))
        else:
            raise core.UserError("Give a folder or a .zip file of portraits.")
        return self._many(items, source, attest, kind)

    def import_files(self, files, source="synthetic", attest=False, kind="face"):
        items = [(f.get("name") or "avatar", base64.b64decode(str(f.get("data_b64") or "").split(",", 1)[-1])) for f in files or []]
        return self._many(items, source, attest, kind)

    def _many(self, items, source, attest, kind="face"):
        added, dup, failed = [], 0, []
        for fn, data in items:
            try:
                r = self.add(data, None, source, attest, tags=["body"] if kind == "body" else None, filename=fn)
                if r["duplicate"]:
                    dup += 1
                else:
                    added.append(r["id"])
            except core.UserError as e:
                failed.append({"file": fn, "error": str(e)})
                if "Confirm" in str(e) or "consent" in str(e):
                    raise
        return {"added": len(added), "ids": added, "duplicates": dup, "failed": failed}

    # ---------------------------------------------------------------- reading / editing
    def _row(self, r, landmarks=False):
        r = dict(r)
        r["tags"] = json.loads(r["tags"] or "[]")
        r["attestation"] = json.loads(r["attestation"])
        r["quality"] = json.loads(r["quality"]) if r["quality"] else None
        r["voice"] = json.loads(r["voice"]) if r["voice"] else None
        r["analysed"] = bool(r["landmarks"])
        r["kind"] = "body" if "body" in r["tags"] else "face"     # full-body avatar (whole figure moves) or a face portrait
        r["turn"] = os.path.isfile(os.path.join(self.folder, str(r["id"]), "turn", "turn.json"))
        md = os.path.join(self.folder, str(r["id"]), "motions")
        r["motions"] = (["turn-around"] if r["turn"] else []) + (sorted(x for x in os.listdir(md) if os.path.isfile(os.path.join(md, x, "motion.json"))) if os.path.isdir(md) else [])
        qp = os.path.join(self.folder, str(r["id"]), "qc.json")
        r["qc"] = None
        if os.path.isfile(qp):
            try:
                with open(qp, encoding="utf-8") as f:
                    r["qc"] = json.load(f)
            except (OSError, ValueError):
                pass
        r["label"] = LABEL if r["source"] == "synthetic" else "Avatar of %s — with consent" % r["attestation"].get("subject", "")
        if landmarks:
            r["landmarks"] = json.loads(r["landmarks"]) if r["landmarks"] else None
        else:
            r.pop("landmarks", None)
        return r

    def list(self, include_hidden=False):
        rows = self.store.query("SELECT * FROM avatars" + ("" if include_hidden else " WHERE hidden = 0") + " ORDER BY name, id")
        return [self._row(r) for r in rows]

    def get(self, aid):
        r = self.store.one("SELECT * FROM avatars WHERE id = ?", (int(aid),))
        if not r:
            raise core.UserError("No such avatar.")
        return self._row(r, landmarks=True)

    def image_path(self, aid):
        r = self.store.one("SELECT image FROM avatars WHERE id = ?", (int(aid),))
        if not r:
            raise core.UserError("No such avatar.")
        return os.path.join(self.folder, str(int(aid)), os.path.basename(r["image"]))

    def set_landmarks(self, aid, landmarks):
        if not isinstance(landmarks, list) or len(landmarks) < 468:
            q = ["no face found — use a clear, front-facing portrait"]
            lm = None
        else:
            lm = [[round(float(p[0]), 5), round(float(p[1]), 5), round(float(p[2]) if len(p) > 2 else 0.0, 5)] for p in landmarks[:478]]
            r = self.store.one("SELECT width, height, tags FROM avatars WHERE id = ?", (int(aid),))
            q = quality(lm, r and r["width"], r and r["height"], body=bool(r and "body" in json.loads(r["tags"] or "[]")))
        try:
            os.remove(os.path.join(self.folder, str(int(aid)), "qc.json"))
        except OSError:
            pass
        with self.store.write() as db:
            db.execute("UPDATE avatars SET landmarks = ?, quality = ? WHERE id = ?", (json.dumps(lm) if lm else None, json.dumps(q), int(aid)))
        return {"id": int(aid), "quality": q, "points": len(lm) if lm else 0}

    def crop(self, aid, data):
        """Replace the working portrait with a close crop of the face (full-length photos animate badly); the original is kept."""
        kind = _kind(data or b"")
        if not kind or len(data) > MAX_BYTES:
            raise core.UserError("Send the crop as a PNG, JPEG or WebP image.")
        r = self.store.one("SELECT image FROM avatars WHERE id = ?", (int(aid),))
        if not r:
            raise core.UserError("No such avatar.")
        d = os.path.join(self.folder, str(int(aid)))
        old = os.path.join(d, os.path.basename(r["image"]))
        if os.path.isfile(old) and not os.path.basename(old).startswith("original."):
            os.replace(old, os.path.join(d, "original" + os.path.splitext(old)[1]))
        fn = "face.%s" % kind
        with open(os.path.join(d, fn), "wb") as f:
            f.write(data)
        w, h = _size(data, kind)
        with self.store.write() as db:
            db.execute("UPDATE avatars SET image = ?, width = ?, height = ?, landmarks = NULL, quality = NULL WHERE id = ?", (fn, w, h, int(aid)))
        return {"id": int(aid), "width": w, "height": h}

    def set_qc(self, aid, qc):
        """The movement check the page ran on this face (anatomy limits, folds, crossing lips) and any per-face tuning."""
        self.get(aid)
        q = {"ok": bool(qc.get("ok")), "issues": [str(x)[:120] for x in (qc.get("issues") or [])][:40], "tuned": {str(k)[:40]: float(v) for k, v in (qc.get("tuned") or {}).items()},
             "range": qc.get("range") or {}, "poses": int(qc.get("poses") or 0), "lip_line": qc.get("lip_line") or {},
             "aesthetic": qc.get("aesthetic") or {}, "at": _now()}
        d = os.path.join(self.folder, str(int(aid)))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "qc.json"), "w", encoding="utf-8") as f:
            json.dump(q, f)
        return q

    # ---------------------------------------------------------------- motions (full body): the person's own recorded moves
    # Each motion is a run of frames from a video of the person (a turnaround, a stretch, a walk …), aligned by the page to
    # this avatar's framing, with a name and the words that set it off in a script. "turn-around" keeps its original
    # folder (turn/), so turnarounds stored by earlier versions stay where they are.
    @staticmethod
    def _slug(slug):
        s = re.sub(r"[^a-z0-9]+", "-", str(slug or "").lower()).strip("-")[:40]
        if not s:
            raise core.UserError("Name the move (for example: turn around, stretch, walk).")
        return s

    def _motion_dir(self, aid, slug):
        self.get(aid)
        s = self._slug(slug)
        return os.path.join(self.folder, str(int(aid)), "turn" if s == "turn-around" else os.path.join("motions", s))

    @staticmethod
    def _meta_file(d):
        return os.path.join(d, "turn.json" if os.path.basename(d) == "turn" else "motion.json")

    def motion_put(self, aid, slug, i, data):
        """One frame of a motion, already aligned by the page (JPEG)."""
        i = int(i)
        if not 0 <= i < MAX_TURN_FRAMES:
            raise core.UserError("A move holds at most %d frames." % MAX_TURN_FRAMES)
        if _kind(data or b"") != "jpg" or len(data) > 2 * 1024 * 1024:
            raise core.UserError("Send each frame as a JPEG under 2 MB.")
        d = self._motion_dir(aid, slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%03d.jpg" % i), "wb") as f:
            f.write(data)
        return {"id": int(aid), "frame": i}

    def motion_set(self, aid, slug, meta):
        """Finish a motion: its name and trigger words, timing, the alignment used, each frame's head angle (None = hidden)."""
        d = self._motion_dir(aid, slug)
        n = int(meta.get("frames") or 0)
        if n < 4 or any(not os.path.isfile(os.path.join(d, "%03d.jpg" % i)) for i in range(n)):
            raise core.UserError("The frames of this move did not all arrive — import it again.")
        for fn in os.listdir(d):                                  # frames left over from a longer earlier version
            if fn.endswith(".jpg") and int(fn[:3]) >= n:
                os.remove(os.path.join(d, fn))
        s = self._slug(slug)
        words = [" ".join(str(w).lower().split())[:40] for w in (meta.get("words") or []) if str(w).strip()][:12]
        m = {"slug": s, "name": " ".join(str(meta.get("name") or s.replace("-", " ")).split())[:40], "words": words or ([s.replace("-", " ")]),
             "frames": n, "fps": float(meta.get("fps") or 12), "width": int(meta.get("width") or 0), "height": int(meta.get("height") or 0),
             "face_h": float(meta.get("face_h") or 0.2), "face_cy": float(meta.get("face_cy") or 0.25), "align": str(meta.get("align") or "track")[:10],
             "yaw": [None if v is None else round(float(v), 1) for v in (meta.get("yaw") or [])][:n], "start": max(0, min(n - 1, int(meta.get("start") or 0))),
             "end": max(0, min(n - 1, int(meta["end"]) if meta.get("end") is not None else n - 1)), "source": str(meta.get("source") or "")[:200], "at": _now()}
        if meta.get("take_of"):                                 # another take of a move: she alternates between them
            m["take_of"] = self._slug(meta["take_of"])
        with open(self._meta_file(d), "w", encoding="utf-8") as f:
            json.dump(m, f)
        return m

    def motion(self, aid, slug):
        p = self._meta_file(self._motion_dir(aid, slug))
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        if self._slug(slug) == "turn-around":                     # stored before moves had names
            m.setdefault("slug", "turn-around"); m.setdefault("name", "turn around"); m.setdefault("words", ["turn around"]); m.setdefault("align", "track")
        return m

    # -- the delivery check, flags and the reference clips (Speech → Check delivery; Avatar studio → Flags / Reference)
    def flag_add(self, aid, meta, thumb=None):
        self.get(aid)
        reason = meta.get("reason") if meta.get("reason") in FLAG_REASONS else "other"
        box = meta.get("box")
        if box is not None and not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            raise core.UserError("The flagged region must be a box [x, y, width, height].")
        with self.store.write() as db:
            fid = db.execute("""INSERT INTO delivery_flags(created, avatar_id, t, box, reason, note, source, state, script, renderer, history)
                                VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (_now(), int(aid), float(meta.get("t") or 0), json.dumps(box), reason,
                                                                 str(meta.get("note") or "")[:1000], "check" if meta.get("source") == "check" else "you",
                                                                 json.dumps(meta.get("state") or None), str(meta.get("script") or "")[:4000],
                                                                 str(meta.get("renderer") or "")[:40], json.dumps([]))).lastrowid
        if thumb:
            d = os.path.join(self.folder, str(int(aid)), "flags")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "%d.jpg" % fid), "wb") as f:
                f.write(thumb)
        return self.flag(fid)

    def flag(self, fid):
        r = self.store.one("SELECT * FROM delivery_flags WHERE id = ?", (int(fid),))
        if not r:
            raise core.UserError("That flag no longer exists.")
        for k in ("box", "state", "history"):
            r[k] = json.loads(r[k]) if r[k] else None
        r["reason_text"] = FLAG_REASONS.get(r["reason"], r["reason"])
        r["measured"] = r["reason"] in ("background", "region", "lips", "hair", "fold")
        r["has_thumb"] = os.path.isfile(self.flag_thumb(r["avatar_id"], fid))
        return r

    def flag_thumb(self, aid, fid):
        return os.path.join(self.folder, str(int(aid)), "flags", "%d.jpg" % int(fid))

    def flags(self, aid=None, status=None):
        q, a = "SELECT id FROM delivery_flags WHERE 1 = 1", []
        if aid:
            q += " AND avatar_id = ?"; a.append(int(aid))
        if status:
            q += " AND status = ?"; a.append(status)
        return [self.flag(r["id"]) for r in self.store.query(q + " ORDER BY id DESC LIMIT 500", a)]

    def flag_set(self, fid, status=None, note=None, recheck=None):
        """Mark a flag fixed / still wrong / won't fix, or record a re-check (its measurement under the current renderer)."""
        f = self.flag(fid)
        hist = f["history"] or []
        if recheck is not None:
            hist.append({"at": _now(), "recheck": recheck})
        if status:
            if status not in ("open", "fixed", "wontfix"):
                raise core.UserError("A flag is open, fixed or won't fix.")
            hist.append({"at": _now(), "status": status, "note": str(note or "")[:500]})
        with self.store.write() as db:
            db.execute("UPDATE delivery_flags SET status = ?, resolved = ?, history = ? WHERE id = ?",
                       (status or f["status"], _now() if status in ("fixed", "wontfix") else f["resolved"], json.dumps(hist[-50:]), int(fid)))
        return self.flag(fid)

    def flag_delete(self, fid):
        f = self.flag(fid)
        with self.store.write() as db:
            db.execute("DELETE FROM delivery_flags WHERE id = ?", (int(fid),))
        p = self.flag_thumb(f["avatar_id"], fid)
        if os.path.isfile(p):
            os.remove(p)
        return {"deleted": int(fid)}

    def check_add(self, aid, r):
        self.get(aid)
        with self.store.write() as db:
            cid = db.execute("""INSERT INTO delivery_checks(created, avatar_id, script, duration, score, spans, reference, renderer)
                                VALUES(?,?,?,?,?,?,?,?)""", (_now(), int(aid), str(r.get("script") or "")[:4000], float(r.get("duration") or 0),
                                                           int(r.get("score") or 0), json.dumps(r.get("spans") or [])[:200000],
                                                           json.dumps(r.get("reference") or None), str(r.get("renderer") or "")[:40])).lastrowid
            db.execute("DELETE FROM delivery_checks WHERE avatar_id = ? AND id NOT IN (SELECT id FROM delivery_checks WHERE avatar_id = ? ORDER BY id DESC LIMIT 200)",
                       (int(aid), int(aid)))
        return {"id": cid}

    def checks(self, aid, limit=30):
        rows = self.store.query("SELECT * FROM delivery_checks WHERE avatar_id = ? ORDER BY id DESC LIMIT ?", (int(aid), int(limit)))
        for r in rows:
            r["spans"] = json.loads(r["spans"] or "[]"); r["reference"] = json.loads(r["reference"] or "null")
        return rows

    def reference(self, aid):
        p = os.path.join(self.folder, str(int(aid)), "reference.json")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def reference_add(self, aid, clip, stats, frames):
        """One reference clip of the person speaking, measured by the face tracker; the reference is the frame-weighted
        mean over all clips (more clips: a steadier picture of how she really moves)."""
        self.get(aid)
        st = {k: float(stats[k]) for k in REFERENCE_KEYS if isinstance(stats.get(k), (int, float))}
        if len(st) < 5 or int(frames or 0) < 24:
            raise core.UserError("The clip was too short, or no face was found in it (at least a second of a visible face is needed).")
        ref = self.reference(aid) or {"clips": []}
        ref["clips"] = [c for c in ref["clips"] if c["clip"] != str(clip)[:160]] + [{"clip": str(clip)[:160], "frames": int(frames), "stats": st, "at": _now()}]
        tot = sum(c["frames"] for c in ref["clips"])
        ref["stats"] = {k: round(sum(c["stats"][k] * c["frames"] for c in ref["clips"] if k in c["stats"]) /
                              max(1, sum(c["frames"] for c in ref["clips"] if k in c["stats"])), 4) for k in REFERENCE_KEYS}
        ref.update(frames=tot, at=_now())
        with open(os.path.join(self.folder, str(int(aid)), "reference.json"), "w", encoding="utf-8") as f:
            json.dump(ref, f)
        return ref

    def reference_remove(self, aid, clip):
        ref = self.reference(aid) or {"clips": []}
        keep = [c for c in ref["clips"] if c["clip"] != clip]
        p = os.path.join(self.folder, str(int(aid)), "reference.json")
        if os.path.isfile(p):
            os.remove(p)
        out = None
        for c in keep:
            out = self.reference_add(aid, c["clip"], c["stats"], c["frames"])
        return out

    def motions(self, aid):
        base = os.path.join(self.folder, str(int(aid)))
        slugs = (["turn-around"] if os.path.isfile(os.path.join(base, "turn", "turn.json")) else []) + \
                sorted(x for x in (os.listdir(os.path.join(base, "motions")) if os.path.isdir(os.path.join(base, "motions")) else [])
                       if os.path.isfile(os.path.join(base, "motions", x, "motion.json")))
        return [self.motion(aid, x) for x in slugs]

    def motion_frame(self, aid, slug, i):
        p = os.path.join(self._motion_dir(aid, slug), "%03d.jpg" % int(i))
        if not os.path.isfile(p):
            raise core.UserError("No such frame.")
        return p

    def motion_delete(self, aid, slug):
        shutil.rmtree(self._motion_dir(aid, slug), ignore_errors=True)
        return {"deleted": True}

    # the person's proportions, learned from all their footage (face height per shoulder width, head top, body height):
    # aligns a new video where the face is seldom seen
    def anatomy(self, aid):
        p = os.path.join(self.folder, str(int(aid)), "anatomy.json")
        if not os.path.isfile(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def set_anatomy(self, aid, a):
        self.get(aid)
        keep = {k: float(a[k]) for k in ("face_per_width", "headtop", "height_per_face", "x_off") if isinstance(a.get(k), (int, float))}
        keep.update(frames=int(a.get("frames") or 0), videos=[str(v)[:120] for v in (a.get("videos") or [])][:50], at=_now())
        with open(os.path.join(self.folder, str(int(aid)), "anatomy.json"), "w", encoding="utf-8") as f:
            json.dump(keep, f)
        return keep

    # the turnaround, as earlier versions called it
    def turn_put(self, aid, i, data):
        return self.motion_put(aid, "turn-around", i, data)

    def turn_set(self, aid, meta):
        return self.motion_set(aid, "turn-around", dict(meta, name=meta.get("name") or "turn around", words=meta.get("words") or ["turn around"]))

    def turn(self, aid):
        return self.motion(aid, "turn-around")

    def turn_frame(self, aid, i):
        return self.motion_frame(aid, "turn-around", i)

    def turn_delete(self, aid):
        return self.motion_delete(aid, "turn-around")

    def update(self, aid, name=None, tags=None, voice=None, notes=None, hidden=None):
        self.get(aid)
        sets, args = [], []
        if name is not None:
            sets.append("name = ?"); args.append(" ".join(str(name).split())[:80] or "Avatar")
        if tags is not None:
            sets.append("tags = ?"); args.append(json.dumps([str(t)[:40] for t in tags][:12]))
        if voice is not None:
            sets.append("voice = ?"); args.append(json.dumps({k: voice[k] for k in ("engine", "voice", "model", "lang", "pitch_hz", "rate") if k in voice}))
        if notes is not None:
            sets.append("notes = ?"); args.append(str(notes)[:500])
        if hidden is not None:
            sets.append("hidden = ?"); args.append(1 if hidden else 0)
        if sets:
            with self.store.write() as db:
                db.execute("UPDATE avatars SET %s WHERE id = ?" % ", ".join(sets), args + [int(aid)])
        return self.get(aid)

    def delete(self, aid):
        self.get(aid)
        shutil.rmtree(os.path.join(self.folder, str(int(aid))), ignore_errors=True)
        with self.store.write() as db:
            db.execute("DELETE FROM avatars WHERE id = ?", (int(aid),))
        return {"deleted": True}
