"""Where QueryBook keeps its data, and which existing folders it reads from.

Order of precedence for the data folder:
  1. --home on the command line
  2. QUERYBOOK_HOME environment variable
  3. data_folder in querybook.ini (next to run_windows.bat / run_mac.command)
  4. Windows: D:\\QueryBook when a D: drive exists, otherwise %LOCALAPPDATA%\\QueryBook
     macOS:   ~/Library/Application Support/QueryBook
     Linux:   ~/.local/share/querybook

watch_folders in querybook.ini lists existing folders (for example a store
already on D:) that the harvester reads continuously. QueryBook only reads
those folders; it never writes, moves or deletes anything in them.
"""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PORTS = {"hub": 8090, "language": 8091, "stem": 8092, "history": 8093, "video": 8094}
APP_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = APP_ROOT / "querybook.ini"


@dataclass(frozen=True)
class Settings:
    data_folder: Path | None = None
    watch_folders: tuple[Path, ...] = ()
    watch_interval: float = 10.0
    source: Path | None = None  # the ini file these came from, if any


def _usable(p: str, windows: bool) -> bool:
    """A Windows drive path (D:\\…) means nothing on a Mac; skip it there instead of making a folder called 'D:'."""
    is_drive = len(p) >= 2 and p[1] == ":" and p[0].isalpha()
    return windows or not is_drive


def load_settings(path: Path = SETTINGS_FILE, *, windows: bool | None = None) -> Settings:
    windows = sys.platform.startswith("win") if windows is None else windows
    if not path.is_file():
        return Settings()
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(path, encoding="utf-8-sig")  # tolerate the BOM Windows Notepad may add
    sec = cp["querybook"] if cp.has_section("querybook") else {}
    data = (sec.get("data_folder") or "").strip().strip('"')
    data = data if _usable(data, windows) else ""
    raw = [p.strip().strip('"') for p in (sec.get("watch_folders") or "").replace(";", "\n").splitlines()]
    watches = tuple(Path(p).expanduser() for p in raw if p and _usable(p, windows))
    try:
        interval = max(1.0, float(sec.get("watch_interval_seconds") or 10))
    except ValueError:
        interval = 10.0
    return Settings(Path(data).expanduser() if data else None, watches, interval, path)


def windows_default(drive_exists=os.path.isdir) -> Path:
    if drive_exists("D:\\"):
        return Path("D:\\QueryBook")
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "QueryBook"


def default_home(settings: Settings | None = None) -> Path:
    override = os.environ.get("QUERYBOOK_HOME")
    if override:
        return Path(override).expanduser()
    settings = settings or load_settings()
    if settings.data_folder:
        return settings.data_folder
    if sys.platform.startswith("win"):
        return windows_default()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "QueryBook"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "querybook"


@dataclass(frozen=True)
class Paths:
    home: Path
    settings: Settings = field(default_factory=Settings)

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


def paths(home: str | Path | None = None, settings: Settings | None = None) -> Paths:
    settings = settings if settings is not None else load_settings()
    root = Path(home).expanduser() if home else default_home(settings)
    return Paths(root, settings).ensure()
