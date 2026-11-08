"""The seams where a Rust implementation can replace the Python one.

Each Protocol uses only plain data in its signatures. A PyO3 module that
exposes the same method names drops in without the callers noticing.
"""

from __future__ import annotations

from typing import Any, Iterator, Protocol

from querybook.core.model import ChangeEvent, Document, RawItem


class DocumentStore(Protocol):
    def create(self, coll: str, data: dict[str, Any], *, content_hash: str | None = None,
               doc_id: str | None = None) -> tuple[Document, bool]: ...
    def get(self, coll: str, doc_id: str) -> Document | None: ...
    def update(self, coll: str, doc_id: str, patch: dict[str, Any]) -> Document | None: ...
    def delete(self, coll: str, doc_id: str) -> bool: ...
    def scan(self, coll: str) -> Iterator[Document]: ...
    def search(self, coll: str | None, text: str, limit: int = 50) -> list[Document]: ...
    def changes_since(self, seq: int, limit: int = 200, coll: str | None = None) -> list[ChangeEvent]: ...
    def latest_seq(self) -> int: ...
    def collections(self) -> dict[str, int]: ...


class Source(Protocol):
    name: str
    kind: str

    def poll(self) -> list[RawItem]: ...


class DomainApp(Protocol):
    key: str
    title: str
    collection: str

    def enrich(self, title: str, body: str) -> dict[str, Any]: ...
    def answer(self, query: str, ctx: Any) -> dict[str, Any]: ...
