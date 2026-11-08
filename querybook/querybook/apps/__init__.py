"""The four domain apps. Each is self-contained (its own enrichment, its own
answer format, its own UI page) and shares only the FQL store."""

from __future__ import annotations

from querybook.apps.base import DomainApp, QueryContext
from querybook.apps.history import HistoryApp
from querybook.apps.language import LanguageApp
from querybook.apps.stem import StemApp
from querybook.apps.video import VideoApp

ALL_APPS: dict[str, type[DomainApp]] = {
    "language": LanguageApp,
    "stem": StemApp,
    "history": HistoryApp,
    "video": VideoApp,
}


def build_apps(keys: list[str] | None = None) -> dict[str, DomainApp]:
    keys = keys or list(ALL_APPS)
    unknown = [k for k in keys if k not in ALL_APPS]
    if unknown:
        raise ValueError(f"Unknown app(s): {', '.join(unknown)}. Choose from {', '.join(ALL_APPS)}")
    return {k: ALL_APPS[k]() for k in keys}


__all__ = ["ALL_APPS", "DomainApp", "QueryContext", "build_apps"]
