"""Where VeriWave keeps what it makes: generated files, code projects and the conversation log.

Folder: $VERIWAVE_DATA, else QueryBook's data folder (data-folder.txt) + /veriwave, else veriwave/data-local. Every
creation gets an id (a counter and a slug of its prompt) and a folder of its own; nothing is ever overwritten.

Lean:
    def idOf (n : Nat) (prompt : String) : String :=
      let s := String.mk ((slug prompt).toList.take 40)
      let num := toString n
      String.mk (List.replicate (6 - num.length) '0') ++ num ++ "-" ++ (if s.isEmpty then "item" else s)
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import zipfile

from . import core

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.dirname(ROOT)


def data_root() -> str:
    """the data folder, chosen by the rule above

    Lean:
        def chooseRoot (env qb fallback : String) : String :=
          if env != "" then env else if qb != "" then qb ++ "/veriwave" else fallback
        #guard chooseRoot "" "D:/QB" "x" == "D:/QB/veriwave"                -- py: data_root() != ""
    """
    env = os.environ.get("VERIWAVE_DATA", "")
    if env:
        return os.path.abspath(env)
    qb = os.path.join(REPO, "querybook-one", "apps", "data-folder.txt")
    try:
        with open(qb, encoding="utf-8-sig") as f:
            lines = [ln.strip().strip('"') for ln in f.read().split("\n") if ln.strip() and not ln.strip().startswith("#")]
        if lines and os.path.isdir(lines[0]):
            return os.path.join(os.path.abspath(lines[0]), "veriwave")
    except OSError:
        pass
    return os.path.join(ROOT, "data-local")


def new_id(n: int, prompt: str) -> str:
    """'000042-a-red-fox': the counter padded to six digits, then up to 40 characters of the prompt's slug

    Lean:
        #guard idOf 42 "A red fox!" == "000042-a-red-fox"                    -- py: new_id(42, "A red fox!") == "000042-a-red-fox"
        #guard idOf 7 "***" == "000007-item"                                 -- py: new_id(7, "***") == "000007-item"
    """
    s = core.slug(prompt)[:40]
    return str(n).rjust(6, "0") + "-" + (s if s else "item")


def zip_files(files: dict[str, str]) -> bytes:
    """a code project as a zip, files in sorted order with a fixed timestamp (same files, same bytes)

    Lean:
        def strictlySorted : List String → Bool
          | a :: rest@(b :: _) => decide (a < b) && strictlySorted rest
          | _ => true
        #guard strictlySorted ["README.md", "index.html"]                    -- py: zip_files({"index.html": "", "README.md": ""}) == zip_files({"README.md": "", "index.html": ""})
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return buf.getvalue()


def okrel_check(parts: list[str]) -> bool:
    """every part of a relative path is a plain name (no '', '.', '..' or backslash)

    Lean:
        def okPart (p : String) : Bool := p != "" && p != "." && p != ".." && !(p.contains '\\')
        def okRel (parts : List String) : Bool := !parts.isEmpty && parts.all okPart
        #guard okRel ["a", "b.svg"] && !okRel ["a", ""]                       -- py: okrel_check(["a", "b.svg"]) and not okrel_check(["a", ""])
    """
    return bool(parts) and all(p not in ("", ".", "..") and "\\" not in p for p in parts)


def resolve(items: str, iid: str, name: str) -> str | None:
    """the file behind /out/<id>/<name> inside the creations folder, or None (unsafe path or no such file)

    Lean:
        theorem okRel_no_parent (ps : List String) (h : okRel ps = true) : ".." ∉ ps := by
          intro hm
          simp [okRel, List.all_eq_true] at h
          have := h.2 ".." hm
          simp [okPart] at this
        #guard !okRel ["x", "..", "y"]                                        -- py: resolve("/nowhere", "x", "../y") is None
    """
    parts = [iid] + name.split("/")
    if not okrel_check(parts):
        return None
    path = os.path.join(items, *parts)
    return path if os.path.isfile(path) else None


def out_url(iid: str, name: str) -> str:
    """the URL a creation's file is served at

    Lean:
        #guard outUrl "a" "b" == "/out/a/b"                                    -- py: out_url("a", "b") == "/out/a/b"
    """
    return "/out/" + iid + "/" + name


def log_line(entry: dict) -> str:
    """one conversation-log line: compact JSON and a newline

    Lean:
        #guard logLine "{}" == "{}\n"                                         -- py: log_line({}) == "{}\n"
    """
    return json.dumps(entry, ensure_ascii=False) + "\n"


class Store:
    """the creations folder and the conversation log

    Lean:
        structure StoreState where
          counter : Nat
        def StoreState.bump (s : StoreState) : StoreState := ⟨s.counter + 1⟩
        theorem bump_grows (s : StoreState) : s.counter < s.bump.counter := Nat.lt_succ_self _
    """

    def __init__(self, root: str) -> None:
        """Lean:
            def startCounter (existing : List Nat) : Nat := existing.foldl max 0
            #guard startCounter [3, 9, 4] == 9                               -- py: Store.highest(["000003-a", "000009-b", "x"]) == 9
        """
        self.root = root
        self.lock = threading.Lock()
        self.items = os.path.join(root, "items")
        os.makedirs(self.items, exist_ok=True)
        self.counter = Store.highest(sorted(os.listdir(self.items)))

    @staticmethod
    def highest(names: list[str]) -> int:
        """the largest counter among existing item folders

        Lean:
            def leadingNumber (s : String) : Nat := (s.takeWhile Char.isDigit).toNat!
            #guard leadingNumber "000009-b" == 9                              -- py: Store.highest(["000009-b"]) == 9
        """
        best = 0
        for n in names:
            digits = n.split("-", 1)[0]
            if digits.isdigit() and digits.isascii():
                best = max(best, int(digits))
        return best

    def save(self, kind: str, prompt: str, files: dict[str, bytes], meta: dict) -> dict:
        """a new creation folder with its files and a meta.json; returns its id and file URLs (/out/<id>/<file>)

        Lean:
            def outUrl (id file : String) : String := "/out/" ++ id ++ "/" ++ file
            #guard outUrl "000001-x" "image.svg" == "/out/000001-x/image.svg"   -- py: out_url("000001-x", "image.svg") == "/out/000001-x/image.svg"
        """
        with self.lock:
            self.counter += 1
            iid = new_id(self.counter, prompt)
        folder = os.path.join(self.items, iid)
        os.makedirs(folder, exist_ok=True)
        urls: dict[str, str] = {}
        for name, data in files.items():
            path = os.path.join(folder, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            urls[name] = out_url(iid, name)
        record: dict = {"id": iid, "kind": kind, "prompt": prompt, "at": int(time.time()), "files": sorted(files)}
        for k in meta:
            record[k] = meta[k]
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
        return {"id": iid, "urls": urls}

    def file_path(self, iid: str, name: str) -> str | None:
        """the on-disk path for /out/<id>/<name>, or None when it would leave the creations folder or doesn't exist

        Lean:
            #guard !okRel ["..", "etc"]                                       -- py: resolve("/nowhere", "..", "etc") is None
        """
        return resolve(self.items, iid, name)

    def list_items(self, limit: int) -> list[dict]:
        """the newest creations first

        Lean:
            def newestFirst (ids : List String) (limit : Nat) : List String := ids.reverse.take limit
            theorem newestFirst_len (ids : List String) (n : Nat) : (newestFirst ids n).length ≤ n := List.length_take_le _ _
        """
        out: list[dict] = []
        for iid in sorted(os.listdir(self.items), reverse=True)[:limit]:
            try:
                with open(os.path.join(self.items, iid, "meta.json"), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                continue
        return out

    def log(self, entry: dict) -> None:
        """one line appended to the conversation log (JSON lines)

        Lean:
            def logLine (json : String) : String := json ++ "\n"
            #guard (logLine "{}").endsWith "\n"                               -- py: log_line({}) == "{}\n"
        """
        with self.lock, open(os.path.join(self.root, "conversation.jsonl"), "a", encoding="utf-8") as f:
            f.write(log_line(entry))
