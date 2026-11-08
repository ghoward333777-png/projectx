"""Build a miniature QueryBook suite data folder (the shape of D:\\QB) with the suite's own schema."""

import json
import sqlite3
from pathlib import Path

from querybook.core.legacy import shard_fp
from tests.suite_schema import COMMONS_SCHEMA, SHARD_SCHEMA

SHARD_FACTS = {
    "wikidata-dump-1": ("history", [("Marie Curie", "date of birth", "1867-11-07"), ("Marie Curie", "award received", "Nobel Prize in Physics"),
                                    ("Paris", "country", "France"), ("Printing press", "inventor", "Johannes Gutenberg")]),
    "pubchem-computed": ("stem", [("Water", "molecular formula", "H2O"), ("Water", "molecular weight", "18.015")]),
    "tatoeba-cc0": ("language", [("Ephemeral", "example sentence", "Fame is ephemeral.")]),
}


def build_suite_folder(folder: Path, *, extra_bulk: int = 0) -> Path:
    commons = folder / "commons"
    (commons / "shards").mkdir(parents=True)
    for d in ("language", "stem", "facts", "control", "video"):
        (folder / d).mkdir()
    db = sqlite3.connect(commons / "commons.sqlite")
    db.executescript(COMMONS_SCHEMA)
    now = "2026-11-08T12:00:00Z"
    db.execute("INSERT INTO facts (fingerprint, domain, subject, predicate, object, statement, origin_app, status, confidence, created, updated)"
               " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               ("f" * 64, "history", "Marie Curie", "born in", "Warsaw", "Marie Curie was born in Warsaw.", "facts", "corroborated", 0.9, now, now))
    db.execute("INSERT INTO evidence (fact_id, app, agent, method, source, verdict, at) VALUES (1,'facts','curator','sourced','Britannica 1911','supports',?)", (now,))
    db.commit()
    db.close()
    for key, (area, facts) in SHARD_FACTS.items():
        rows = list(facts) + ([(f"Item {i}", "instance of", "thing") for i in range(extra_bulk)] if key == "wikidata-dump-1" else [])
        sh = sqlite3.connect(commons / "shards" / f"{key}.sqlite")
        sh.executescript(SHARD_SCHEMA)
        preds = {p: i + 1 for i, p in enumerate(sorted({p for _, p, _ in rows}))}
        sh.executemany("INSERT INTO predicates (id, name) VALUES (?,?)", [(i, p) for p, i in preds.items()])
        sh.executemany("INSERT INTO facts (fp, s, p, o, part, row) VALUES (?,?,?,?,1,?)",
                       [(shard_fp(area, s, p, o), s, preds[p], o, n) for n, (s, p, o) in enumerate(rows)])
        sh.executemany("INSERT INTO meta (key, value) VALUES (?,?)",
                       [("facts", json.dumps(len(rows))), ("state", json.dumps("done"))])
        sh.commit()
        sh.close()
    return folder


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) of every file the suite owns (everything outside querybook-next)."""
    return {str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in folder.rglob("*") if p.is_file() and "querybook-next" not in p.parts}
