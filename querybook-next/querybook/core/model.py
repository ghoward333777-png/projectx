"""Plain-data records shared by every layer.

Everything that crosses a module boundary is one of these frozen dataclasses or
JSON-compatible values (dict/list/str/int/float/bool/None). That keeps each
boundary a straight translation to a Rust struct + serde (see contracts/).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOMAINS: tuple[str, ...] = ("language", "stem", "history", "video")

# One FQL collection per domain, plus system collections.
DOMAIN_COLLECTIONS: dict[str, str] = {
    "language": "Language",
    "stem": "Stem",
    "history": "History",
    "video": "Video",
}
SYSTEM_COLLECTIONS: tuple[str, ...] = ("Source", "IngestLog")


@dataclass(frozen=True)
class Document:
    id: str
    coll: str
    ts: int  # microseconds since the Unix epoch
    hash: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "coll": self.coll, "ts": self.ts}
        out.update(self.data)
        return out


@dataclass(frozen=True)
class ChangeEvent:
    seq: int
    type: str  # "add" | "update" | "remove"
    coll: str
    id: str
    ts: int
    title: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"seq": self.seq, "type": self.type, "coll": self.coll,
                "id": self.id, "ts": self.ts, "title": self.title}


@dataclass(frozen=True)
class RawItem:
    """Something a harvester found, before normalisation and classification."""

    body: str
    title: str = ""
    source: str = "manual"
    url: str = ""
    domain: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    status: str  # "added" | "duplicate" | "rejected"
    domain: str = ""
    coll: str = ""
    id: str = ""
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {"status": self.status, "domain": self.domain, "coll": self.coll,
                "id": self.id, "reason": self.reason}
