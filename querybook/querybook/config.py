"""Per-platform paths. Windows, macOS and Linux each get their conventional data folder."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORTS = {"hub": 8090, "language": 8091, "stem": 8092, "history": 8093, "video": 8094}


def default_home() -> Path:
    override = os.environ.get("QUERYBOOK_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "QueryBook"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "QueryBook"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "querybook"


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "querybook.fqldb"

    @property
    def inbox(self) -> Path:
        return self.home / "inbox"

    @property
    def renders(self) -> Path:
        return self.home / "renders"

    def ensure(self) -> "Paths":
        for folder in (self.home, self.renders, self.inbox,
                       *(self.inbox / d for d in ("language", "stem", "history", "video"))):
            folder.mkdir(parents=True, exist_ok=True)
        return self


def paths(home: str | Path | None = None) -> Paths:
    return Paths(Path(home).expanduser() if home else default_home()).ensure()
