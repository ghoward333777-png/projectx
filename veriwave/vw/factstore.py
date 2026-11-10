"""VeriWave's default fact connection: QueryBook's facts on the data drive (D:\\QB), read directly and read-only.

Three kinds of store are found under the root and searched together:
* UFCS stores (QueryBook v9.64, ufcs_store.py): <store>/index.sqlite, table nuc(fp, subject, predicate, object, trust,
  block) with subjects normalised to lower case and the (subject, predicate) index. Looked for at the root and in its
  usual sub-folders (store, mystore, ufcs, QueryBook/store …) and anywhere two levels down.
* The suite's Commons: commons/commons.sqlite, table facts(subject, predicate, object, statement, status …).
* The suite's bulk shards: commons/shards/<dataset>.sqlite, tables facts(fp, s, p, o …) and predicates(id, name).

Every connection is SQLite mode=ro: VeriWave never writes to, moves or copies QueryBook's facts (CLAUDE.md rule for
D:\\QB). Lookups use the stores' own indexes (exact subject, then subject prefix), so a store of millions or billions of
facts answers in milliseconds.

Root: $VERIWAVE_FACTS, else QueryBook's data-folder.txt, else D:\\QB when it exists.

Lean:
    inductive Kind where | ufcs | commons | shard
    deriving Repr, BEq, DecidableEq
    structure Hit where
      subj : String
      pred : String
      obj : String
      trust : Nat
    deriving Repr, BEq
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.request

from . import core, verdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
SUBFOLDERS = ["", "store", "mystore", "ufcs", "UFCS", "QueryBook/store", "querybook/store", "QueryBook/mystore",
              ".querybook/store", "querybook-next"]
SKIP = {"commons", "shards", "blocks", "backups", "veriwave", "__pycache__", "items", "logs", "media", "avatars"}


def default_root() -> str:
    """where the facts are: $VERIWAVE_FACTS, else QueryBook's data-folder.txt, else D:\\QB if it exists, else ''

    Lean:
        def chooseFactRoot (env dataFolder : String) (dqbExists : Bool) : String :=
          if env != "" then env else if dataFolder != "" then dataFolder else if dqbExists then "D:\\QB" else ""
        #guard chooseFactRoot "" "" true == "D:\\QB"                        -- py: choose_root("", "", True) == "D:\\QB"
        #guard chooseFactRoot "E:\\Facts" "D:\\QB" true == "E:\\Facts"      -- py: choose_root("E:\\Facts", "D:\\QB", True) == "E:\\Facts"
    """
    env = os.environ.get("VERIWAVE_FACTS", "")
    folder = ""
    try:
        with open(os.path.join(REPO, "querybook-one", "apps", "data-folder.txt"), encoding="utf-8-sig") as f:
            lines = [ln.strip().strip('"') for ln in f.read().split("\n") if ln.strip() and not ln.strip().startswith("#")]
        folder = lines[0] if lines else ""
    except OSError:
        folder = ""
    return choose_root(env, folder, os.path.isdir("D:\\QB"))


def choose_root(env: str, data_folder: str, dqb_exists: bool) -> str:
    """the rule of default_root, without the I/O

    Lean:
        #guard chooseFactRoot "" "F:\\QB" false == "F:\\QB"                  -- py: choose_root("", "F:\\QB", False) == "F:\\QB"
    """
    if env:
        return env
    if data_folder:
        return data_folder
    return "D:\\QB" if dqb_exists else ""


def norm(text: str) -> str:
    """how a UFCS store writes subjects: lower case, single spaces (ufcs_store._norm)

    Lean:
        -- ASCII model of ufcs_store._norm (Python lower-cases all of Unicode; Lean's String.toLower is ASCII)
        def ufcsNorm (s : String) : String := " ".intercalate ((s.toLower.split (· == ' ')).filter (· != ""))
        #guard ufcsNorm "  Marie   Curie " == "marie curie"               -- py: norm("  Marie   Curie ") == "marie curie"
    """
    return " ".join(text.strip().lower().split())


def variants(subject: str) -> list[str]:
    """the spellings a subject is looked up under: as given, trimmed, Title Case, lower case (each once)

    Lean:
        def dedup : List String → List String
          | [] => []
          | x :: xs => if xs.contains x then dedup xs else x :: dedup xs
        theorem dedup_le (xs : List String) : (dedup xs).length ≤ xs.length := by
          induction xs with
          | nil => exact Nat.le_refl 0
          | cons x xs ih => unfold dedup; split <;> simp <;> omega
        #guard (dedup ["a", "b", "a"]).length == 2                         -- py: len(variants("x")) == 2
    """
    s = subject.strip()
    out: list[str] = []
    for v in (subject, s, title(s), s.lower()):
        if v and v not in out:
            out.append(v)
    return out


def title(text: str) -> str:
    """Title Case: the first letter of every space-separated word upper-cased, the rest lower-cased

    Lean:
        def titleWord (w : String) : String := match w.toList with
          | [] => ""
          | c :: cs => String.mk (c.toUpper :: cs.map Char.toLower)
        def titleOf (s : String) : String := " ".intercalate ((s.split (· == ' ')).map titleWord)
        #guard titleOf "marie curie" == "Marie Curie"                       -- py: title("marie curie") == "Marie Curie"
    """
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split(" "))


def ufcs_trust(t: object) -> int:
    """a UFCS trust value (0.0 to 1.0) as a whole percentage, clamped to 0..100

    Lean:
        -- trust in thousandths, rounded half up to a percentage
        def ufcsTrust (milli : Int) : Int := clamp 0 100 ((milli + 5) / 10)
        theorem ufcsTrust_range (m : Int) : 0 ≤ ufcsTrust m ∧ ufcsTrust m ≤ 100 := clamp_in 0 100 _ (by decide)
        #guard ufcsTrust 950 == 95                                          -- py: ufcs_trust(0.95) == 95
        #guard ufcsTrust 1700 == 100                                        -- py: ufcs_trust(1.7) == 100
    """
    try:
        x = float(t)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return verdict.DEFAULT_TRUST
    return core.clamp(0, 100, int((x * 1000 + 5) // 10))


def prefix_end(prefix: str) -> str:
    """the upper bound of an index range scan for 'starts with prefix'

    Lean:
        def prefixEnd (p : String) : String := p ++ "\uFFFF"
        #guard (prefixEnd "rome").startsWith "rome"                         -- py: prefix_end("rome") == "rome\uffff"
    """
    return prefix + "\uffff"


def ro(path: str) -> sqlite3.Connection:
    """a read-only SQLite connection (mode=ro): nothing VeriWave does can change QueryBook's files

    Lean:
        def roUri (path : String) : String := "file:" ++ path ++ "?mode=ro"
        #guard (roUri "x").endsWith "?mode=ro"                              -- py: RO_MODE == "?mode=ro"
    """
    conn = sqlite3.connect("file:" + urllib.request.pathname2url(path) + RO_MODE, uri=True, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


RO_MODE = "?mode=ro"


def has_table(path: str, table: str) -> bool:
    """whether a SQLite file has a table (False for anything unreadable)

    Lean:
        def hasTableOf (tables : List String) (t : String) : Bool := tables.contains t
        #guard hasTableOf ["fp", "nuc"] "nuc"                               -- py: has_table("/no/such/file.sqlite", "nuc") is False
    """
    if not os.path.isfile(path):
        return False
    try:
        conn = ro(path)
        try:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def find_ufcs(root: str) -> list[str]:
    """every UFCS store under the root: the usual sub-folders first, then any folder up to two levels down

    Lean:
        def joinPath (root sub : String) : String := if sub == "" then root else root ++ "/" ++ sub
        #guard joinPath "D:/QB" "store" == "D:/QB/store"                     -- py: find_ufcs("/no/such/root") == []
    """
    if not root or not os.path.isdir(root):
        return []
    found: list[str] = []
    for sub in SUBFOLDERS:
        p = os.path.normpath(os.path.join(root, *sub.split("/"))) if sub else os.path.normpath(root)
        if p not in found and has_table(os.path.join(p, "index.sqlite"), "nuc"):
            found.append(p)
    try:
        level1 = sorted(e for e in os.listdir(root) if e not in SKIP and os.path.isdir(os.path.join(root, e)))
    except OSError:
        level1 = []
    for a in level1:
        pa = os.path.normpath(os.path.join(root, a))
        if pa not in found and has_table(os.path.join(pa, "index.sqlite"), "nuc"):
            found.append(pa)
        try:
            level2 = sorted(e for e in os.listdir(pa) if e not in SKIP and os.path.isdir(os.path.join(pa, e)))
        except OSError:
            level2 = []
        for b in level2:
            pb = os.path.normpath(os.path.join(pa, b))
            if pb not in found and has_table(os.path.join(pb, "index.sqlite"), "nuc"):
                found.append(pb)
    return found


def dedupe(facts: list[dict]) -> list[dict]:
    """facts with each (subject, predicate, object) once, ignoring case, spacing and Wikidata ids; first one kept

    Lean:
        def factKey (h : Hit) : String × String × String := (norm h.subj, lower h.pred, norm h.obj)
        def dedupeAux : List (String × String × String) → List Hit → List Hit
          | _, [] => []
          | seen, h :: hs => if seen.contains (factKey h) then dedupeAux seen hs else h :: dedupeAux (factKey h :: seen) hs
        def dedupeHits (hs : List Hit) : List Hit := dedupeAux [] hs
        #guard (dedupeHits [⟨"Rome", "inception", "753 BC", 90⟩, ⟨"rome (Q220)", "Inception", "753 bc", 70⟩]).length == 1   -- py: len(dedupe([{"subject": "Rome", "predicate": "inception", "object": "753 BC"}, {"subject": "rome (Q220)", "predicate": "Inception", "object": "753 bc"}])) == 1
    """
    seen: list[tuple[str, str, str]] = []
    out: list[dict] = []
    for f in facts:
        k = (verdict.norm(str(f.get("subject") or "")), core.lower(str(f.get("predicate") or "")), verdict.norm(str(f.get("object") or "")))
        if k not in seen:
            seen.append(k)
            out.append(f)
    return out


class FactStore:
    """QueryBook's facts on the data drive, read-only; discovery and counts are refreshed at most every 30 seconds

    Lean:
        def countTotal (ufcs : List Nat) (c : Nat) (shards : List Nat) : Nat := ufcs.foldl (· + ·) 0 + c + shards.foldl (· + ·) 0
        #guard countTotal [1200000] 0 [] == 1200000                         -- py: FactStore("").status()["facts"] == 0
    """

    def __init__(self, root: str) -> None:
        """Lean:
            def CACHE_SECONDS : Nat := 30
        """
        self.root = root
        self.lock = threading.Lock()
        self.at = 0.0
        self.ufcs: list[dict] = []
        self.commons = ""
        self.commons_facts = 0
        self.shards: list[dict] = []
        self.preds: dict[str, dict[int, str]] = {}

    def refresh(self) -> None:
        """find the stores and read their counts (cheap: max(rowid), max(id) and the shards' own meta)

        Lean:
            def stale (now t0 : Nat) : Bool := decide (t0 + CACHE_SECONDS ≤ now) || t0 == 0
            #guard stale 100 60 && !stale 70 60                             -- py: FactStore("").refresh() is None
        """
        with self.lock:
            if self.at and time.monotonic() - self.at < 30:
                return
            self.at = time.monotonic()
            ufcs: list[dict] = []
            for p in find_ufcs(self.root):
                n = 0
                try:
                    conn = ro(os.path.join(p, "index.sqlite"))
                    try:
                        n = int(conn.execute("SELECT max(rowid) FROM nuc").fetchone()[0] or 0)
                    finally:
                        conn.close()
                except sqlite3.Error:
                    n = 0
                ufcs.append({"path": p, "facts": n})
            self.ufcs = ufcs
            commons = ""
            for c in (os.path.join(self.root, "commons", "commons.sqlite"), os.path.join(self.root, "commons.sqlite")):
                if self.root and has_table(c, "facts"):
                    commons = c
                    break
            self.commons = commons
            self.commons_facts = 0
            if commons:
                try:
                    conn = ro(commons)
                    try:
                        self.commons_facts = int(conn.execute("SELECT max(id) FROM facts").fetchone()[0] or 0)
                    finally:
                        conn.close()
                except sqlite3.Error:
                    self.commons_facts = 0
            shards: list[dict] = []
            folder = os.path.join(self.root, "commons", "shards") if self.root else ""
            if folder and os.path.isdir(folder):
                for fn in sorted(os.listdir(folder)):
                    if not fn.endswith(".sqlite") or fn.startswith("_"):
                        continue
                    path = os.path.join(folder, fn)
                    n = 0
                    try:
                        conn = ro(path)
                        try:
                            row = conn.execute("SELECT value FROM meta WHERE key='facts'").fetchone()
                            n = int(str(row[0]).strip('"')) if row is not None and str(row[0]).strip('"').isdigit() else 0
                        finally:
                            conn.close()
                    except sqlite3.Error:
                        n = 0
                    shards.append({"key": fn[:-7], "path": path, "facts": n})
            self.shards = shards

    def status(self) -> dict:
        """what is connected: the root, each store with its fact count, and the total

        Lean:
            #guard countTotal [1000000, 250000] 10 [5] == 1250015            -- py: FactStore("/no/such/root").status()["connected"] is False
        """
        self.refresh()
        total = sum(u["facts"] for u in self.ufcs) + self.commons_facts + sum(s["facts"] for s in self.shards)
        return {"root": self.root, "connected": bool(self.ufcs or self.commons or self.shards), "facts": total,
                "ufcs": self.ufcs, "commons": {"path": self.commons, "facts": self.commons_facts} if self.commons else None,
                "shards": [{"key": s["key"], "facts": s["facts"]} for s in self.shards],
                "root_exists": bool(self.root) and os.path.isdir(self.root)}

    def lookup(self, subject: str, limit: int) -> list[dict]:
        """facts about a subject from every store: exact subject first, then subjects starting with it; best trust first

        Lean:
            def byTrust (a b : Hit) : Bool := decide (a.trust ≥ b.trust)
            theorem lookup_bounded (xs : List Hit) (n : Nat) : (xs.take n).length ≤ n := List.length_take_le _ _
            #guard (([⟨"a", "p", "x", 90⟩, ⟨"a", "p", "y", 50⟩] : List Hit).take 1).length == 1   -- py: FactStore("/no/such/root").lookup("Rome", 5) == []
        """
        self.refresh()
        s = subject.strip()
        if not s or limit <= 0:
            return []
        out: list[dict] = []
        for u in self.ufcs:
            out += self.ufcs_lookup(u["path"], s, limit)
        if self.commons:
            out += self.commons_lookup(s, limit)
        for sh in self.shards:
            if len(out) >= limit * 3:
                break
            out += self.shard_lookup(sh, s, limit)
        out = dedupe(out)
        exact = [f for f in out if norm(str(f["subject"])) == norm(s) or verdict.norm(str(f["subject"])) == norm(s)]
        rest = [f for f in out if f not in exact]
        exact.sort(key=lambda f: -int(f["trust"]))
        rest.sort(key=lambda f: -int(f["trust"]))
        return (exact + rest)[:limit]

    def links(self, fact: dict, limit: int) -> dict:
        """Ontology Mesh linkage of one Fact Unit: its siblings (same subject) and its onward links (facts about its object)

        Lean:
            def onward (obj : String) (facts : List Hit) : List Hit := facts.filter (fun h => ufcsNorm h.subj == ufcsNorm obj)
            theorem onward_sub (o : String) (fs : List Hit) : (onward o fs).length ≤ fs.length := List.length_filter_le _ _
            #guard (onward "France" [⟨"france", "capital", "Paris", 90⟩, ⟨"spain", "capital", "Madrid", 90⟩]).length == 1   -- py: FactStore("/no/such").links({"subject": "x", "predicate": "p", "object": "y"}, 3) == {"siblings": [], "onward": [], "inbound": "not indexed"}
        """
        subj = str(fact.get("subject") or "")
        obj = verdict.strip_qids(str(fact.get("object") or ""))
        key = (verdict.norm(subj), core.lower(str(fact.get("predicate") or "")), verdict.norm(obj))
        sib = [f for f in self.lookup(subj, limit + 1)
               if (verdict.norm(str(f["subject"])), core.lower(str(f["predicate"])), verdict.norm(str(f["object"]))) != key][:limit]
        onward = [f for f in self.lookup(obj, limit) if norm(verdict.strip_qids(str(f["subject"]))) == norm(obj)] if obj else []
        slim = lambda f: {"subject": str(f["subject"]), "predicate": str(f["predicate"]), "object": str(f["object"]), "trust": int(f["trust"]),
                          "where": str(f["where"])}
        return {"siblings": [slim(f) for f in sib], "onward": [slim(f) for f in onward], "inbound": "not indexed"}

    def ufcs_lookup(self, path: str, subject: str, limit: int) -> list[dict]:
        """one UFCS store: subject = norm(subject) on its index, then the subject-prefix range

        Lean:
            def ufcsWhere : String := "subject = ? ORDER BY trust DESC LIMIT ?"
            #guard ufcsWhere.startsWith "subject = ?"                       -- py: FactStore("").ufcs_lookup("/no/such", "x", 3) == []
        """
        rows: list[sqlite3.Row] = []
        try:
            conn = ro(os.path.join(path, "index.sqlite"))
        except sqlite3.Error:
            return []
        try:
            key = norm(subject)
            rows = list(conn.execute("SELECT subject, predicate, object, trust, fp, block FROM nuc WHERE subject = ? ORDER BY trust DESC LIMIT ?",
                                     (key, limit)))
            if len(rows) < limit:
                rows += list(conn.execute("SELECT subject, predicate, object, trust, fp, block FROM nuc WHERE subject > ? AND subject < ? LIMIT ?",
                                          (key, prefix_end(key), limit - len(rows))))
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        where = "UFCS store (" + path + ")"
        return [{"subject": str(r["subject"]), "predicate": str(r["predicate"]), "object": str(r["object"]), "trust": ufcs_trust(r["trust"]),
                 "where": where, "status": "", "packet": {"kind": "ufcs", "store": path, "fp": str(r["fp"]), "block": int(r["block"] or 0),
                                                          "raw_trust": float(r["trust"] or 0.0)}} for r in rows]

    def commons_lookup(self, subject: str, limit: int) -> list[dict]:
        """the Commons: each spelling of the subject on its (subject, predicate) index

        Lean:
            #guard statusTrust "unsourced" == 65                             -- py: verdict.status_trust("unsourced") == 65
        """
        out: list[dict] = []
        try:
            conn = ro(self.commons)
        except sqlite3.Error:
            return []
        try:
            for v in variants(subject):
                for r in conn.execute("SELECT id, fingerprint, domain, origin_app, subject, predicate, object, statement, status FROM facts WHERE subject = ? LIMIT ?",
                                      (v, limit - len(out))):
                    out.append({"subject": str(r["subject"]), "predicate": str(r["predicate"]), "object": str(r["object"]),
                                "statement": str(r["statement"] or ""), "status": str(r["status"] or ""),
                                "trust": verdict.status_trust(str(r["status"] or "")), "where": "Shared facts (Commons, " + self.root + ")",
                                "packet": {"kind": "commons", "store": self.commons, "fp": str(r["fingerprint"] or ""), "id": int(r["id"]),
                                           "domain": str(r["domain"] or ""), "origin": str(r["origin_app"] or "")}})
                if len(out) >= limit:
                    break
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        return out

    def shard_lookup(self, sh: dict, subject: str, limit: int) -> list[dict]:
        """one bulk shard: each spelling exactly, then 'Name (Q…)' labels, on its facts_s index

        Lean:
            def labelPrefix (s : String) : String := s ++ " ("
            #guard labelPrefix "Rome" == "Rome ("                             -- py: FactStore("").shard_lookup({"key": "k", "path": "/no/such.sqlite"}, "Rome", 3) == []
        """
        out: list[dict] = []
        try:
            conn = ro(sh["path"])
        except sqlite3.Error:
            return []
        try:
            key = sh["key"]
            if key not in self.preds:
                try:
                    self.preds[key] = {int(r["id"]): str(r["name"]) for r in conn.execute("SELECT id, name FROM predicates")}
                except sqlite3.Error:
                    self.preds[key] = {}
            names = self.preds[key]
            for v in variants(subject):
                q = list(conn.execute("SELECT fp, s, p, o FROM facts WHERE s = ? LIMIT ?", (v, limit - len(out))))
                if len(out) + len(q) < limit:
                    q += list(conn.execute("SELECT fp, s, p, o FROM facts WHERE s > ? AND s < ? LIMIT ?",
                                           (v + " (", prefix_end(v + " ("), limit - len(out) - len(q))))
                for r in q:
                    out.append({"subject": str(r["s"]), "predicate": names.get(int(r["p"]), str(r["p"])), "object": str(r["o"]),
                                "trust": 70, "status": "harvested", "where": "Bulk dataset " + key + " (" + self.root + ")",
                                "packet": {"kind": "shard", "store": sh["path"], "fp": bytes(r["fp"]).hex() if r["fp"] is not None else "",
                                           "dataset": key}})
                if len(out) >= limit:
                    break
        except sqlite3.Error:
            pass
        finally:
            conn.close()
        return out


def ufcs_fingerprint(subject: str, predicate: str, obj: str, polarity: str) -> str:
    """a Fact Unit's semantic fingerprint exactly as ufcs_store.py computes it: SHA-256 of norm(s)|norm(p)|norm(o)|polarity

    Lean:
        -- SHA-256 is an external primitive; Lean fixes the text it is taken over
        def fingerprintInput (s p o pol : String) : String := ufcsNorm s ++ "|" ++ ufcsNorm p ++ "|" ++ ufcsNorm o ++ "|" ++ pol
        #guard fingerprintInput "Printing  Press" "Inventor" "Johannes Gutenberg" "+" == "printing press|inventor|johannes gutenberg|+"   -- py: fingerprint_input("Printing  Press", "Inventor", "Johannes Gutenberg", "+") == "printing press|inventor|johannes gutenberg|+"
    """
    return hashlib.sha256(fingerprint_input(subject, predicate, obj, polarity).encode()).hexdigest()


def fingerprint_input(subject: str, predicate: str, obj: str, polarity: str) -> str:
    """the canonical text a UFCS semantic fingerprint is taken over

    Lean:
        #guard fingerprintInput "a" "b" "c" "-" == "a|b|c|-"                 -- py: fingerprint_input("a", "b", "c", "-") == "a|b|c|-"
    """
    return norm(subject) + "|" + norm(predicate) + "|" + norm(obj) + "|" + polarity


def rph(fps: list[str]) -> str:
    """the response provenance hash ufcs_store.fql() gives a result: SHA-256 of RPH|fp1|fp2…

    Lean:
        def rphInput (fps : List String) : String := "|".intercalate ("RPH" :: fps)
        #guard rphInput ["a", "b"] == "RPH|a|b"                               -- py: rph_input(["a", "b"]) == "RPH|a|b"
    """
    return hashlib.sha256(rph_input(fps).encode()).hexdigest()


def rph_input(fps: list[str]) -> str:
    """the text the response provenance hash is taken over

    Lean:
        #guard rphInput [] == "RPH"                                           -- py: rph_input([]) == "RPH"
    """
    return "|".join(["RPH"] + fps)


def verify_packet(fact: dict) -> dict:
    """UFCS packet tracking for one fact: the stored fingerprint, the one recomputed from its nucleus, and whether they agree

    Lean:
        def verifies (stored computedPos computedNeg : String) : String :=
          if stored == computedPos then "+" else if stored == computedNeg then "-" else ""
        #guard verifies "x" "x" "y" == "+"                                    -- py: verify_packet({"subject": "a", "predicate": "b", "object": "c", "packet": {"kind": "ufcs", "fp": ufcs_fingerprint("a", "b", "c", "+")}})["polarity"] == "+"
        #guard verifies "z" "x" "y" == ""                                     -- py: verify_packet({"subject": "a", "predicate": "b", "object": "c", "packet": {"kind": "ufcs", "fp": "z"}})["verified"] is False
    """
    pk = dict(fact.get("packet") or {})
    s, p, o = str(fact.get("subject") or ""), str(fact.get("predicate") or ""), str(fact.get("object") or "")
    pos = ufcs_fingerprint(s, p, o, "+")
    neg = ufcs_fingerprint(s, p, o, "-")
    stored = str(pk.get("fp") or "")
    pol = "+" if stored == pos else "-" if stored == neg else ""
    out = {"kind": str(pk.get("kind") or "app"), "store": str(pk.get("store") or ""), "stored_fp": stored, "computed_fp": pos,
           "polarity": pol, "verified": bool(pol), "nucleus": {"subject": s, "predicate": p, "object": o},
           "fingerprint_input": fingerprint_input(s, p, o, pol or "+")}
    for k in ("block", "id", "dataset", "domain", "origin", "raw_trust"):
        if k in pk:
            out[k] = pk[k]
    if out["kind"] == "ufcs" and "block" in pk:
        out["block_file"] = "blocks/block_%05d.jsonl.gz" % int(pk["block"])
    if out["kind"] != "ufcs":
        out["verified"] = False
        out["note"] = ("QueryBook's Commons and bulk shards use the suite's own fingerprint (qbcore), not the UFCS one; "
                       "the stored identifier is shown as recorded.")
    return out


def find_packet(store: str, block: int, fp: str, seconds: float) -> dict | None:
    """the full UFCS packet (FUID, sources, certification, temporal, safety) read from its block, or None

    Lean:
        def blockName (n : Nat) : String :=
          let d := toString n
          "block_" ++ String.mk (List.replicate (5 - d.length) '0') ++ d ++ ".jsonl.gz"
        #guard blockName 7 == "block_00007.jsonl.gz"                          -- py: "block_%05d.jsonl.gz" % 7 == "block_00007.jsonl.gz"
    """
    path = os.path.join(store, "blocks", "block_%05d.jsonl.gz" % block)
    if not os.path.isfile(path) or len(fp) != 64:
        return None
    needle = '"semantic_fingerprint":"' + fp + '"'
    end = time.monotonic() + seconds
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if needle in line:
                    data = json.loads(line)
                    return data if isinstance(data, dict) else None
                if i % 20000 == 0 and time.monotonic() > end:
                    return {"_timeout": True}
    except (OSError, ValueError, EOFError):
        return None
    return None
