"""Where QueryBook Next finds its data: the existing QueryBook store (e.g. D:\\QB).

It follows the QueryBook suite's own rules, so both use one data drive:

* The data folder is named by `data-folder.txt` beside the launchers (one line,
  e.g. `D:\\QB`), or by QB_DATA_FOLDER, or by --home.
* The shared facts (the Commons) are in FOLDER\\commons, or in FOLDER itself when
  FOLDER\\commons.sqlite exists (QB_COMMONS_DATA overrides, as in the suite).
  The bulk datasets are in COMMONS\\shards\\<dataset>.sqlite.
* QueryBook Next keeps its own data in FOLDER\\querybook-next. It never writes
  in the suite's folders (commons, language, stem, facts, control, video).
* If the data folder is named but cannot be found (an external drive that is not
  connected), nothing starts: data is never split between two drives.
* With no data folder named, the suite's default ~/QueryBook-Data is used.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORTS = {"hub": 8090, "language": 8091, "stem": 8092, "history": 8093, "video": 8094}
APP_ROOT = Path(__file__).resolve().parent.parent
DATA_FOLDER_FILE = APP_ROOT / "data-folder.txt"
OWN_FOLDER = "querybook-next"


class DataFolderMissing(RuntimeError):
    pass


def read_data_folder_file(path: Path = DATA_FOLDER_FILE) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip().strip('"')
        if line and not line.startswith("#"):
            return line
    return None


@dataclass(frozen=True)
class Paths:
    folder: Path          # the QueryBook data folder, e.g. D:\QB
    commons: Path         # the shared facts folder, e.g. D:\QB\commons
    named: bool = False   # True when the folder came from data-folder.txt / env / --home

    @property
    def home(self) -> Path:
        return self.folder / OWN_FOLDER

    @property
    def db(self) -> Path:
        return self.home / "querybook.fqldb"

    @property
    def inbox(self) -> Path:
        return self.home / "inbox"

    @property
    def renders(self) -> Path:
        return self.home / "renders"

    @property
    def commons_db(self) -> Path:
        return self.commons / "commons.sqlite"

    @property
    def shards(self) -> Path:
        return self.commons / "shards"

    def ensure(self) -> "Paths":
        for folder in (self.home, self.renders, self.inbox,
                       *(self.inbox / d for d in ("language", "stem", "history", "video"))):
            folder.mkdir(parents=True, exist_ok=True)
        return self


def _is_drive_path(p: str) -> bool:
    return len(p) >= 2 and p[1] == ":" and p[0].isalpha()


def resolve(home: str | Path | None = None, *, data_file: Path = DATA_FOLDER_FILE,
            windows: bool | None = None) -> Paths:
    windows = sys.platform.startswith("win") if windows is None else windows
    from_file = read_data_folder_file(data_file)
    if from_file and not windows and _is_drive_path(from_file):
        from_file = None  # "D:\\QB" means nothing on a Mac: use the usual folder there
    named = home or os.environ.get("QB_DATA_FOLDER") or from_file
    if named:
        folder = Path(named).expanduser()
        if not folder.is_dir():
            raise DataFolderMissing(
                f"The QueryBook data folder {folder} cannot be found. If it is on an external drive, connect the "
                f"drive and start again. To use the usual folder instead, delete {data_file.name}.")
    else:
        folder = Path.home() / "QueryBook-Data"
    env_commons = os.environ.get("QB_COMMONS_DATA")
    if env_commons:
        commons = Path(env_commons).expanduser()
    elif (folder / "commons.sqlite").is_file():
        commons = folder
    else:
        commons = folder / "commons"
    return Paths(folder, commons, bool(named))


def paths(home: str | Path | None = None, *, data_file: Path = DATA_FOLDER_FILE) -> Paths:
    return resolve(home, data_file=data_file).ensure()
