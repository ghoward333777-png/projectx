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
"""]
SOURCES = {"synthetic": "AI-generated portrait — shows no real person", "consented": "a real person who agreed (name and consent recorded)"}
LABEL = "Synthetic avatar — AI-generated"
MAX_BYTES = 20 * 1024 * 1024


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


def quality(landmarks, width=None, height=None):
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
    if fh < 0.25:
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
                r = self.add(f.read(), a.get("name"), "synthetic", True, tags=["starter"], filename=a["file"])
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

    def import_path(self, path, source="synthetic", attest=False):
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
        return self._many(items, source, attest)

    def import_files(self, files, source="synthetic", attest=False):
        items = [(f.get("name") or "avatar", base64.b64decode(str(f.get("data_b64") or "").split(",", 1)[-1])) for f in files or []]
        return self._many(items, source, attest)

    def _many(self, items, source, attest):
        added, dup, failed = [], 0, []
        for fn, data in items:
            try:
                r = self.add(data, None, source, attest, filename=fn)
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
            r = self.store.one("SELECT width, height FROM avatars WHERE id = ?", (int(aid),))
            q = quality(lm, r and r["width"], r and r["height"])
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
