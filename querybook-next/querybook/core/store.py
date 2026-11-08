"""FQL document store — the common database every QueryBook app writes to.

An embedded, file-based store (SQLite in WAL mode underneath) that holds
schemaless documents grouped in named collections, with:

* deterministic document ids derived from content (re-ingesting the same text
  is a no-op, so harvesters can poll as often as they like);
* a full-text index (FTS5, LIKE fallback) for `Collection.search()`;
* an append-only `changes` journal that is the real-time event stream. Because
  the journal lives in the database file, separate app processes (the
  standalone Language/STEM/History/Video apps) all see each other's writes.

The FQL language itself lives in querybook.core.fql; this module only stores.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from querybook.core.model import ChangeEvent, Document
from querybook.core.text import STOPWORDS, fnv1a64, tokenize

COLLECTION_NAME = re.compile(r"^[A-Z][A-Za-z0-9_]{0,63}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id   TEXT NOT NULL,
    coll TEXT NOT NULL,
    data TEXT NOT NULL,
    hash TEXT NOT NULL,
    ts   INTEGER NOT NULL,
    PRIMARY KEY (coll, id)
);
CREATE INDEX IF NOT EXISTS documents_hash ON documents (coll, hash);
CREATE TABLE IF NOT EXISTS changes (
    seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    type   TEXT NOT NULL,
    coll   TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    title  TEXT NOT NULL DEFAULT '',
    ts     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class StoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def now_us() -> int:
    return time.time_ns() // 1000


def doc_title(data: dict[str, Any]) -> str:
    for key in ("title", "term", "name", "url"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:200]
    return ""


def _strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)


def _fts_body(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(data):
        if key not in ("title", "url", "source", "domain", "srt"):
            _strings(data[key], parts)
    return " ".join(parts)[:200_000]


class FQLStore:
    """Thread-safe (one SQLite connection per thread) and multi-process safe (WAL)."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conns: dict[int, sqlite3.Connection] = {}  # one connection per thread, keyed by thread id
        self._conns_lock = threading.Lock()
        self._write_lock = threading.Lock()
        conn = self._conn()
        conn.executescript(SCHEMA)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5("
                "coll UNINDEXED, id UNINDEXED, title, body, tokenize='unicode61 remove_diacritics 2')"
            )
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False  # Python builds without FTS5 still work, just slower search

    # -- connection -----------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        tid = threading.get_ident()
        with self._conns_lock:
            conn = self._conns.get(tid)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=15000")
            with self._conns_lock:
                self._conns[tid] = conn
        return conn

    def close(self) -> None:
        with self._conns_lock:
            conns, self._conns = list(self._conns.values()), {}
        for conn in conns:
            conn.close()

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction (BEGIN IMMEDIATE … COMMIT/ROLLBACK): an RAII guard in Rust."""
        with self._write_lock:
            conn = self._conn()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    @staticmethod
    def _row_doc(row: sqlite3.Row) -> Document:
        return Document(id=row["id"], coll=row["coll"], ts=row["ts"], hash=row["hash"],
                        data=json.loads(row["data"]))

    @staticmethod
    def _check_coll(coll: str) -> None:
        if not COLLECTION_NAME.match(coll or ""):
            raise StoreError("invalid_collection",
                             f"Collection names start with a capital letter and use letters, digits or _: {coll!r}")

    def _index(self, conn: sqlite3.Connection, doc: Document) -> None:
        if self.fts:
            conn.execute("DELETE FROM documents_fts WHERE coll=? AND id=?", (doc.coll, doc.id))
            conn.execute("INSERT INTO documents_fts (coll, id, title, body) VALUES (?,?,?,?)",
                         (doc.coll, doc.id, doc_title(doc.data), _fts_body(doc.data)))

    @staticmethod
    def _journal(conn: sqlite3.Connection, kind: str, doc: Document) -> None:
        conn.execute("INSERT INTO changes (type, coll, doc_id, title, ts) VALUES (?,?,?,?,?)",
                     (kind, doc.coll, doc.id, doc_title(doc.data), doc.ts))

    # -- writes ---------------------------------------------------------
    def create(self, coll: str, data: dict[str, Any], *, content_hash: str | None = None,
               doc_id: str | None = None) -> tuple[Document, bool]:
        """Insert a document; returns (doc, created). Same content => same doc, created=False."""
        self._check_coll(coll)
        if not isinstance(data, dict):
            raise StoreError("invalid_document", "A document must be an object")
        data = {k: v for k, v in data.items() if k not in ("id", "coll", "ts")}
        body = canonical_json(data)
        h = content_hash or fnv1a64(body.encode("utf-8"))
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM documents WHERE coll=? AND hash=? LIMIT 1", (coll, h)).fetchone()
            if row is not None:
                return self._row_doc(row), False
            new_id = doc_id or str(int(fnv1a64(f"{coll}:{h}".encode()), 16) % 10**18)
            if conn.execute("SELECT 1 FROM documents WHERE coll=? AND id=?", (coll, new_id)).fetchone():
                raise StoreError("id_exists", f"{coll} already has a document with id {new_id}")
            doc = Document(id=new_id, coll=coll, ts=now_us(), hash=h, data=data)
            conn.execute("INSERT INTO documents (id, coll, data, hash, ts) VALUES (?,?,?,?,?)",
                         (doc.id, coll, body, h, doc.ts))
            self._index(conn, doc)
            self._journal(conn, "add", doc)
            return doc, True

    def update(self, coll: str, doc_id: str, patch: dict[str, Any], *, replace: bool = False) -> Document | None:
        """Merge `patch` into the document (null removes a field), or replace it outright."""
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM documents WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
            if row is None:
                return None
            data = {} if replace else json.loads(row["data"])
            for k, v in patch.items():
                if k in ("id", "coll", "ts"):
                    continue
                if v is None:
                    data.pop(k, None)
                else:
                    data[k] = v
            body = canonical_json(data)
            doc = Document(id=doc_id, coll=coll, ts=now_us(), hash=fnv1a64(body.encode()), data=data)
            conn.execute("UPDATE documents SET data=?, hash=?, ts=? WHERE coll=? AND id=?",
                         (body, doc.hash, doc.ts, coll, doc_id))
            self._index(conn, doc)
            self._journal(conn, "update", doc)
            return doc

    def delete(self, coll: str, doc_id: str) -> bool:
        with self._tx() as conn:
            row = conn.execute("SELECT * FROM documents WHERE coll=? AND id=?", (coll, doc_id)).fetchone()
            if row is None:
                return False
            doc = self._row_doc(row)
            conn.execute("DELETE FROM documents WHERE coll=? AND id=?", (coll, doc_id))
            if self.fts:
                conn.execute("DELETE FROM documents_fts WHERE coll=? AND id=?", (coll, doc_id))
            self._journal(conn, "remove", Document(doc.id, coll, now_us(), doc.hash, doc.data))
            return True

    # -- reads ----------------------------------------------------------
    def get(self, coll: str, doc_id: str) -> Document | None:
        row = self._conn().execute("SELECT * FROM documents WHERE coll=? AND id=?", (coll, str(doc_id))).fetchone()
        return self._row_doc(row) if row else None

    def scan(self, coll: str, batch: int = 500) -> Iterator[Document]:
        """All documents of a collection in insertion order, fetched lazily in batches."""
        last = 0
        conn = self._conn()
        while True:
            rows = conn.execute("SELECT rowid AS r, * FROM documents WHERE coll=? AND rowid>? ORDER BY rowid LIMIT ?",
                                (coll, last, batch)).fetchall()
            if not rows:
                return
            for row in rows:
                yield self._row_doc(row)
            last = rows[-1]["r"]

    def count(self, coll: str) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM documents WHERE coll=?", (coll,)).fetchone()[0]

    def search(self, coll: str | None, text: str, limit: int = 50) -> list[Document]:
        """Relevance-ranked full-text search (BM25, title weighted 4x)."""
        toks = list(dict.fromkeys(tokenize(text)))
        toks = [t for t in toks if t not in STOPWORDS] or toks  # "the printing press" -> printing, press
        if not toks:
            return []
        conn = self._conn()
        if self.fts:
            match = " OR ".join('"' + t.replace('"', "") + '"' for t in toks[:16])
            sql = ("SELECT d.* FROM documents_fts f JOIN documents d ON d.coll=f.coll AND d.id=f.id "
                   "WHERE documents_fts MATCH ?" + (" AND f.coll=?" if coll else "") +
                   " ORDER BY bm25(documents_fts, 0.0, 0.0, 4.0, 1.0), d.id LIMIT ?")
            args: tuple = (match, coll, limit) if coll else (match, limit)
            return [self._row_doc(r) for r in conn.execute(sql, args).fetchall()]
        like = [f"%{t}%" for t in toks[:6]]
        where = " OR ".join("lower(data) LIKE ?" for _ in like)
        sql = "SELECT * FROM documents WHERE (" + where + ")" + (" AND coll=?" if coll else "") + " ORDER BY rowid LIMIT ?"
        return [self._row_doc(r) for r in conn.execute(sql, (*like, *((coll,) if coll else ()), limit)).fetchall()]

    def collections(self) -> dict[str, int]:
        rows = self._conn().execute("SELECT coll, COUNT(*) AS n FROM documents GROUP BY coll ORDER BY coll").fetchall()
        return {r["coll"]: r["n"] for r in rows}

    # -- change feed ----------------------------------------------------
    def latest_seq(self) -> int:
        return self._conn().execute("SELECT COALESCE(MAX(seq), 0) FROM changes").fetchone()[0]

    def changes_since(self, seq: int, limit: int = 200, coll: str | None = None) -> list[ChangeEvent]:
        sql = "SELECT * FROM changes WHERE seq>?" + (" AND coll=?" if coll else "") + " ORDER BY seq LIMIT ?"
        args = (seq, coll, limit) if coll else (seq, limit)
        return [ChangeEvent(seq=r["seq"], type=r["type"], coll=r["coll"], id=r["doc_id"], ts=r["ts"], title=r["title"])
                for r in self._conn().execute(sql, args).fetchall()]
