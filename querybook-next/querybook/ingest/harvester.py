"""Continuous harvesting: one background thread polls every source on its own
interval. Feed sources are configured as documents in the `Source` collection,
so `Source.create({kind: "feed", url: "...", domain: "history", interval: 600})`
in any app's FQL console starts harvesting within seconds — no restart."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from querybook.ingest.pipeline import IngestPipeline
from querybook.ingest.sources import FeedSource


@dataclass
class SourceState:
    source: Any
    interval: float
    next_due: float = 0.0
    last_poll: float | None = None
    last_error: str | None = None
    added: int = 0
    duplicates: int = 0
    origin: str = "config"

    def to_json(self) -> dict[str, Any]:
        return {"name": self.source.name, "kind": self.source.kind, "interval_s": self.interval,
                "last_poll": self.last_poll, "last_error": self.last_error, "added": self.added,
                "duplicates": self.duplicates, "origin": self.origin}


@dataclass
class Harvester:
    pipeline: IngestPipeline
    sources: list[tuple[Any, float]] = field(default_factory=list)
    sync_seconds: float = 5.0

    def __post_init__(self) -> None:
        self.states = [SourceState(s, max(0.25, i)) for s, i in self.sources]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sync = 0.0

    def sync_db_sources(self) -> None:
        """Pick up feeds declared in the Source collection (added or removed at runtime)."""
        wanted: dict[str, tuple[str, str | None, float]] = {}
        for doc in self.pipeline.store.scan("Source"):
            d = doc.data
            if d.get("kind") == "feed" and d.get("url") and d.get("enabled", True):
                wanted[d["url"]] = (d["url"], d.get("domain"), float(d.get("interval", 600)))
        current = {s.source.url: s for s in self.states if s.origin == "db"}
        for url, (u, domain, interval) in wanted.items():
            if url not in current:
                self.states.append(SourceState(FeedSource(u, domain), max(30.0, interval), origin="db"))
        self.states = [s for s in self.states if s.origin != "db" or s.source.url in wanted]

    def poll_state(self, st: SourceState) -> None:
        st.last_poll = time.time()
        try:
            for item in st.source.poll():
                res = self.pipeline.ingest(item)
                if res.status == "added":
                    st.added += 1
                elif res.status == "duplicate":
                    st.duplicates += 1
            st.last_error = None
        except Exception as exc:  # a broken feed must never stop the other sources
            st.last_error = f"{type(exc).__name__}: {exc}"
            self.pipeline.log_error(st.source.name, st.last_error)

    def run_once(self) -> dict[str, Any]:
        self.sync_db_sources()
        for st in self.states:
            self.poll_state(st)
        return self.status()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            if now - self._last_sync >= self.sync_seconds:
                self._last_sync = now
                try:
                    self.sync_db_sources()
                except Exception:
                    pass
            for st in list(self.states):
                if now >= st.next_due:
                    self.poll_state(st)
                    st.next_due = time.monotonic() + st.interval
            self._stop.wait(0.25)

    def start(self) -> "Harvester":
        if not self._thread:
            self._thread = threading.Thread(target=self._loop, name="querybook-harvester", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        return {"running": bool(self._thread and self._thread.is_alive()),
                "sources": [s.to_json() for s in self.states], "totals": dict(self.pipeline.stats)}
