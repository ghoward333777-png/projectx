from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from querybook.core.fql import Evaluator, FQLError
from querybook.core.fql.evaluator import to_json


def fql_str(value: str) -> str:
    """Quote a Python string as an FQL string literal (JSON escapes are valid FQL)."""
    return json.dumps(value, ensure_ascii=False)


@dataclass
class QueryContext:
    """What an app gets for one query: the shared store and a log of the FQL it ran."""

    store: Any
    renders_dir: Path | None = None
    fql_log: list[str] = field(default_factory=list)

    def fql(self, src: str, *, write: bool = False) -> Any:
        """Run FQL and return plain JSON data; every query is shown to the user in the UI."""
        self.fql_log.append(src)
        return to_json(Evaluator(self.store, readonly=not write, limit=500).evaluate(src), 500)

    def docs(self, src: str) -> list[dict[str, Any]]:
        out = self.fql(src)
        if isinstance(out, dict) and "data" in out:
            out = out["data"]
        if isinstance(out, dict):
            out = [out]
        return [d for d in (out or []) if isinstance(d, dict)]


def source_ref(doc: dict[str, Any]) -> dict[str, Any]:
    return {"id": doc.get("id"), "coll": doc.get("coll"), "title": doc.get("title") or doc.get("term") or "",
            "source": doc.get("source", ""), "url": doc.get("url", "")}


class DomainApp:
    key = "base"
    title = "QueryBook"
    collection = "Library"
    tagline = ""
    placeholder = "Ask a question"
    examples: tuple[str, ...] = ()

    def enrich(self, title: str, body: str) -> dict[str, Any]:
        return {}

    def respond(self, ctx: QueryContext, query: str) -> dict[str, Any]:
        raise NotImplementedError

    def answer(self, query: str, ctx: QueryContext) -> dict[str, Any]:
        """Uniform envelope around the domain-specific payload (see contracts/domain-response)."""
        started = time.perf_counter()
        query = (query or "").strip()
        try:
            payload = self.respond(ctx, query) if query else {"kind": "empty", "summary": "Type a question to begin."}
        except FQLError as exc:
            payload = {"kind": "error", "summary": exc.message, "error": exc.to_json()}
        base = {"domain": self.key, "app": self.title, "query": query, "sources": []}
        base.update(payload)
        base["fql"] = list(ctx.fql_log)
        base["took_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return base

    def describe(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "collection": self.collection,
                "tagline": self.tagline, "placeholder": self.placeholder, "examples": list(self.examples)}
