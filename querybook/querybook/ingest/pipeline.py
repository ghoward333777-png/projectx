"""normalise → dedupe → classify → domain enrichment → store. Synchronous and
deterministic; called by harvesters (continuous) and the HTTP push endpoint
(real time)."""

from __future__ import annotations

import threading
from typing import Any

from querybook.core.model import DOMAIN_COLLECTIONS, DOMAINS, IngestResult, RawItem
from querybook.core.store import now_us
from querybook.core.text import classify, content_hash, normalize, normalize_paragraphs

MAX_BODY = 500_000


class IngestPipeline:
    def __init__(self, store: Any, apps: dict[str, Any]):
        self.store = store
        self.apps = apps  # every domain's enrichment runs, whether or not its UI is open
        self._lock = threading.Lock()
        self.stats = {"added": 0, "duplicate": 0, "rejected": 0}

    def _count(self, status: str) -> None:
        with self._lock:
            self.stats[status] = self.stats.get(status, 0) + 1

    def ingest(self, item: RawItem) -> IngestResult:
        title = normalize(item.title or "")[:300]
        body = normalize_paragraphs(item.body or "")[:MAX_BODY]
        if not body and not title:
            self._count("rejected")
            return IngestResult("rejected", reason="empty item")
        if not body:
            body = title
        h = content_hash(f"{title}\n{body}")
        auto = item.domain not in DOMAINS
        domain, scores = classify(f"{title} {body}") if auto else (item.domain, {})
        coll = DOMAIN_COLLECTIONS[domain]
        if not title:
            title = body.split("\n", 1)[0][:90]
        data: dict[str, Any] = {"title": title, "body": body, "source": item.source, "url": item.url,
                                "domain": domain, "classified": {"auto": auto, "scores": scores},
                                "ingested_us": now_us()}
        app = self.apps.get(domain)
        if app is not None:
            data.update(app.enrich(title, body))
        data.update(item.fields or {})
        doc, created = self.store.create(coll, data, content_hash=h)
        status = "added" if created else "duplicate"
        self._count(status)
        return IngestResult(status, domain=domain, coll=coll, id=doc.id)

    def log_error(self, source: str, message: str) -> None:
        self.store.create("IngestLog", {"level": "error", "source": source, "message": message[:2000], "ts_us": now_us()})
