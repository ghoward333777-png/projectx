"""Read-only access to the existing QueryBook store (the suite's Commons and bulk shards).

Mirrors the suite's own definitions exactly (querybook/apps/_core in the suite):

* qbcore.norm(x)        = " ".join(str(x or "").strip().lower().split())
* qbcore.fingerprint(*p) = sha256("|".join(norm(x) for x in p)).hexdigest()
* shard key             = bytes.fromhex(fingerprint(area, s, p, o))[:16]
* shard home            = COMMONS/shards/<dataset>.sqlite; a newer working copy may be in
                          ~/QueryBook-Work/<sha256(abspath(COMMONS).lower())[:10]>/ (qbbulk.work_dir)
* areas                 = {"language": "language", "stem": "stem", "facts": "history"}

Every connection is opened with SQLite's mode=ro: nothing here can change the suite's files.
The fingerprint functions are mirrored in rust/querybook-core (golden vectors in contracts/).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

AREA = {"language": "language", "stem": "stem", "facts": "history"}
# Dataset keys of the suite's bulk catalogue (qbbulk.catalog) and the app each belongs to.
DATASET_APP = {
    "pubchem-computed": "stem", "ncbi-taxonomy": "stem", "noaa-ghcn-daily": "stem", "usda-fooddata-central": "stem",
    "mit-ocw": "stem", "usgs-gnis": "facts", "calendar-scaffold": "facts", "wikidata-series": "facts",
    "wikidata-lattice": "facts", "tatoeba-cc0": "language",
}
DOMAIN_OF_APP = {"language": "language", "stem": "stem", "facts": "history"}


def norm(x: Any) -> str:
    return " ".join(str(x or "").strip().lower().split())


def fingerprint(parts: list[Any]) -> str:
    """qbcore.fingerprint(*parts); takes a list here so the signature is a Rust slice."""
    return hashlib.sha256("|".join(norm(p) for p in parts).encode("utf-8")).hexdigest()


def shard_fp(area: str, s: Any, p: Any, o: Any) -> bytes:
    return bytes.fromhex(fingerprint([area, s, p, o]))[:16]


def dataset_app(key: str) -> str:
    if key.startswith("wikidata-dump-") or key.startswith("wikidata"):
        return "facts"
    return DATASET_APP.get(key, "facts")


def work_dir(commons: Path, *, env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    setting = env.get("QB_WORK_FOLDER")
    if setting == "off":
        return None
    if setting:
        base = Path(setting)
    else:
        drive = os.path.splitdrive(os.path.abspath(commons))[0].upper()
        system = (env.get("SystemDrive") or "").upper()
        if not (drive and system and drive != system):
            return None
        base = Path(os.path.expanduser("~")) / "QueryBook-Work"
    return base / hashlib.sha256(os.path.abspath(commons).lower().encode()).hexdigest()[:10]


def _ro(path: Path) -> sqlite3.Connection:
    """A read-only connection. Callers must close it (contextlib.closing): on Windows an open
    handle locks the file, and the suite's copier must be able to replace its working copies."""
    conn = sqlite3.connect("file:%s?mode=ro" % urllib.request.pathname2url(str(path)), uri=True, timeout=5,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass(frozen=True)
class ShardInfo:
    key: str
    path: Path
    app: str
    area: str
    facts: int
    state: str
    working_copy: bool

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "app": self.app, "area": self.area, "domain": DOMAIN_OF_APP.get(self.app, "history"),
                "facts": self.facts, "state": self.state, "working_copy": self.working_copy, "path": str(self.path)}


class LegacyStore:
    """The suite's facts, read in place. Safe while the suite is harvesting (read-only, WAL readers)."""

    def __init__(self, commons: Path, *, env: dict[str, str] | None = None) -> None:
        self.commons = Path(commons)
        self.env = env
        self._pred_cache: dict[str, dict[int, str]] = {}
        self._shards: tuple[float, list[ShardInfo]] = (0.0, [])
        self._lock = threading.Lock()
        self.cache_seconds = 30.0  # the data drive may be a USB disk: read the counts at most every 30 s

    # -- discovery --------------------------------------------------------
    @property
    def available(self) -> bool:
        return (self.commons / "commons.sqlite").is_file() or (self.commons / "shards").is_dir()

    def shard_path(self, key: str) -> Path:
        wd = work_dir(self.commons, env=self.env)
        if wd is not None and (wd / f"{key}.sqlite").is_file():
            return wd / f"{key}.sqlite"
        return self.commons / "shards" / f"{key}.sqlite"

    def shard_keys(self) -> list[str]:
        folder = self.commons / "shards"
        if not folder.is_dir():
            return []
        return sorted(p.stem for p in folder.glob("*.sqlite") if not p.name.startswith("_"))

    def shards(self) -> list[ShardInfo]:
        with self._lock:
            at, cached = self._shards
            if cached and time.monotonic() - at < self.cache_seconds:
                return cached
            fresh = self._read_shards()
            self._shards = (time.monotonic(), fresh)
            return fresh

    def _read_shards(self) -> list[ShardInfo]:
        out = []
        for key in self.shard_keys():
            path = self.shard_path(key)
            facts, state = 0, "unknown"
            try:
                with contextlib.closing(_ro(path)) as db:
                    meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
                facts = int(json.loads(meta.get("facts", "0")) or 0)
                state = str(json.loads(meta.get("state", '"unknown"')))
            except (sqlite3.Error, ValueError, TypeError):
                state = "busy"
            app = dataset_app(key)
            out.append(ShardInfo(key, path, app, AREA.get(app, "history"), facts, state,
                                 path.parent != self.commons / "shards"))
        return out

    def total_facts(self) -> int:
        return sum(s.facts for s in self.shards()) + self.commons_count()

    # -- bulk shards ----------------------------------------------------------
    def _predicates(self, key: str, db: sqlite3.Connection) -> dict[int, str]:
        if key not in self._pred_cache:
            try:
                self._pred_cache[key] = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM predicates")}
            except sqlite3.Error:
                self._pred_cache[key] = {}
        return self._pred_cache[key]

    def _fact(self, info: ShardInfo, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        preds = self._predicates(info.key, db)
        return {"id": row["fp"].hex(), "coll": "Facts", "dataset": info.key, "app": info.app,
                "domain": DOMAIN_OF_APP.get(info.app, "history"), "subject": row["s"],
                "predicate": preds.get(row["p"], str(row["p"])), "object": row["o"], "part": row["part"], "row": row["row"]}

    def facts_by_subject(self, subject: str, limit: int = 100, keys: list[str] | None = None) -> list[dict[str, Any]]:
        """Uses each shard's facts_s index; tries the text as given, then title case."""
        out: list[dict[str, Any]] = []
        variants = list(dict.fromkeys([subject, subject.strip(), subject.strip().title()]))
        for info in self.shards():
            if keys and info.key not in keys:
                continue
            try:
                with contextlib.closing(_ro(info.path)) as db:
                    for v in variants:
                        for row in db.execute("SELECT * FROM facts WHERE s = ? LIMIT ?", (v, limit - len(out))):
                            out.append(self._fact(info, db, row))
                        if len(out) >= limit:
                            return out
            except sqlite3.Error:
                continue
        return out

    def fact_exists(self, area: str, s: str, p: str, o: str) -> list[str]:
        """Which shards already hold this exact fact (by the suite's own fingerprint)."""
        fp = shard_fp(area, s, p, o)
        hits = []
        for info in self.shards():
            if info.area != norm(area):
                continue
            try:
                with contextlib.closing(_ro(info.path)) as db:
                    if db.execute("SELECT 1 FROM facts WHERE fp = ?", (fp,)).fetchone():
                        hits.append(info.key)
            except sqlite3.Error:
                continue
        return hits

    def scan_facts(self, keys: list[str] | None = None) -> Iterator[dict[str, Any]]:
        """Lazy scan in key order. Callers must bound it (take/first): a full pass reads ~a billion rows."""
        for info in self.shards():
            if keys and info.key not in keys:
                continue
            try:
                db = _ro(info.path)
            except sqlite3.Error:
                continue
            try:
                for row in db.execute("SELECT * FROM facts"):
                    yield self._fact(info, db, row)
            except sqlite3.Error:
                continue
            finally:
                db.close()

    # -- the Commons ----------------------------------------------------------
    def _commons(self) -> sqlite3.Connection | None:
        path = self.commons / "commons.sqlite"
        if not path.is_file():
            return None
        try:
            return _ro(path)
        except sqlite3.Error:
            return None

    @staticmethod
    def _commons_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["id"], d["coll"] = str(d.pop("id")), "Commons"
        return d

    def commons_count(self) -> int:
        db = self._commons()
        if db is None:
            return 0
        try:
            return int(db.execute("SELECT max(id) FROM facts").fetchone()[0] or 0)  # cheap; counting is slow on a USB drive
        except sqlite3.Error:
            return 0
        finally:
            db.close()

    def commons_by_subject(self, subject: str, limit: int = 100) -> list[dict[str, Any]]:
        db = self._commons()
        if db is None:
            return []
        try:
            out = []
            for v in dict.fromkeys([subject, subject.strip(), subject.strip().title(), subject.strip().lower()]):
                out += [self._commons_row(r) for r in
                        db.execute("SELECT * FROM facts WHERE subject = ? LIMIT ?", (v, limit - len(out)))]
                if len(out) >= limit:
                    break
            return out
        except sqlite3.Error:
            return []
        finally:
            db.close()

    def commons_get(self, fact_id: str) -> dict[str, Any] | None:
        db = self._commons()
        if db is None:
            return None
        try:
            row = db.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
            if row is None:
                return None
            fact = self._commons_row(row)
            fact["evidence"] = [dict(r) for r in db.execute(
                "SELECT app, method, source, licence, url, verdict, detail, at FROM evidence WHERE fact_id = ?", (fact_id,))]
            return fact
        except sqlite3.Error:
            return None
        finally:
            db.close()

    def scan_commons(self) -> Iterator[dict[str, Any]]:
        db = self._commons()
        if db is None:
            return
        try:
            for row in db.execute("SELECT * FROM facts ORDER BY id"):
                yield self._commons_row(row)
        except sqlite3.Error:
            return
        finally:
            db.close()
