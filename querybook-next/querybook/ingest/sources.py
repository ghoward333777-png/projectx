"""Harvest sources. Each poll() returns only what is new since the last poll."""

from __future__ import annotations

import csv
import html
import io
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from querybook.core.model import DOMAINS, RawItem

TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
DATA_SUFFIXES = {".json", ".jsonl", ".csv"}
TAG = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return html.unescape(TAG.sub(" ", text or "")).strip()


def item_from_obj(obj: dict[str, Any], *, source: str, domain: str | None) -> RawItem | None:
    if not isinstance(obj, dict):
        return None
    body = obj.get("body") or obj.get("text") or obj.get("content") or obj.get("description") or ""
    title = obj.get("title") or obj.get("term") or obj.get("name") or ""
    known = {"body", "text", "content", "description", "title", "name", "domain", "url", "fields"}
    fields = dict(obj.get("fields") or {})
    fields.update({k: v for k, v in obj.items() if k not in known})
    d = obj.get("domain") if obj.get("domain") in DOMAINS else domain
    return RawItem(body=str(body), title=str(title), source=source, url=str(obj.get("url", "")), domain=d, fields=fields)


def parse_file(path: Path, *, source: str, domain: str | None) -> list[RawItem]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        lines = raw.strip().splitlines()
        if not lines:
            return []
        title = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip() or title
        return [RawItem(body=body, title=title, source=source, domain=domain)]
    if suffix == ".json":
        data = json.loads(raw)
        objs = data if isinstance(data, list) else [data]
    elif suffix == ".jsonl":
        objs = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:  # .csv
        objs = list(csv.DictReader(io.StringIO(raw)))
    return [it for it in (item_from_obj(o, source=source, domain=domain) for o in objs) if it]


class FolderSource:
    """Watches a drop folder. Files in <root>/<domain>/ are filed under that domain;
    files elsewhere are auto-classified. Polling (stdlib only) works identically on
    Windows (NTFS), macOS (APFS) and Linux."""

    kind = "folder"

    MAX_FILE_BYTES = 20_000_000

    def __init__(self, root: Path, name: str = "inbox", settle_seconds: float = 0.4,
                 exclude: tuple[Path, ...] = ()) -> None:
        self.root = Path(root)
        self.name = name
        self.exclude = tuple(Path(e).resolve() for e in exclude)  # e.g. QueryBook's own inbox/renders
        self.settle = settle_seconds
        self.seen: dict[str, tuple[int, int]] = {}

    def poll(self) -> list[RawItem]:
        items: list[RawItem] = []
        if not self.root.is_dir():
            return items
        now = time.time()
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in TEXT_SUFFIXES | DATA_SUFFIXES:
                continue
            if self.exclude and any(ex == path.resolve() or ex in path.resolve().parents for ex in self.exclude):
                continue
            st = path.stat()
            sig = (st.st_mtime_ns, st.st_size)
            key = str(path)
            # On Windows a just-written file's mtime can be a hair ahead of time.time(); with settle 0 accept it.
            settling = self.settle > 0 and now - st.st_mtime < self.settle
            if self.seen.get(key) == sig or settling or st.st_size > self.MAX_FILE_BYTES:
                continue
            rel = path.relative_to(self.root)
            hint = rel.parts[0] if len(rel.parts) > 1 and rel.parts[0] in DOMAINS else None
            try:
                items += parse_file(path, source=f"folder:{rel.as_posix()}", domain=hint)
                self.seen[key] = sig
            except (ValueError, OSError, csv.Error) as exc:
                self.seen[key] = sig
                raise RuntimeError(f"{rel.as_posix()}: {exc}") from exc
        return items


class FeedSource:
    """RSS 2.0 / Atom feed. Remembers entry ids so each entry is ingested once."""

    kind = "feed"

    def __init__(self, url: str, domain: str | None = None, name: str | None = None, timeout: float = 20) -> None:
        self.url = url
        self.domain = domain if domain in DOMAINS else None
        self.name = name or url
        self.timeout = timeout
        self.seen: set[str] = set()

    def fetch(self) -> bytes:
        req = urllib.request.Request(self.url, headers={"User-Agent": "QueryBook/0.1 (+harvester)"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read(5_000_000)

    def parse(self, xml_bytes: bytes) -> list[RawItem]:
        root = ET.fromstring(xml_bytes)
        items: list[RawItem] = []
        atom = "{http://www.w3.org/2005/Atom}"
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag not in ("item", "entry"):
                continue

            def text(names: tuple[str, ...]) -> str:
                for n in names:
                    node = el.find(n) if not n.startswith("atom:") else el.find(atom + n[5:])
                    if node is not None and (node.text or "").strip():
                        return node.text.strip()
                return ""

            link = text(("link",))
            if not link:
                link_el = el.find(atom + "link")
                link = link_el.get("href", "") if link_el is not None else ""
            uid = text(("guid", "atom:id")) or link or text(("title", "atom:title"))
            if not uid or uid in self.seen:
                continue
            self.seen.add(uid)
            body = strip_html(text(("description", "atom:summary", "atom:content",
                                    "{http://purl.org/rss/1.0/modules/content/}encoded")))
            title = strip_html(text(("title", "atom:title")))
            items.append(RawItem(body=body or title, title=title, source=f"feed:{self.name}", url=link, domain=self.domain))
        return items

    def poll(self) -> list[RawItem]:
        return self.parse(self.fetch())
