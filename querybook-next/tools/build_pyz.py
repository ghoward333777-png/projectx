"""Build querybook-next.pyz: the whole app as ONE runnable Python file (standard library only).

    python tools/build_pyz.py            -> dist/querybook-next.pyz

Run it with `python querybook-next.pyz` (Windows: double-click works; the Python installer
associates .pyz files with the py launcher). On first start it unpacks itself once into a
per-user cache folder and runs from there. A data-folder.txt placed beside the .pyz wins over
the built-in one (D:\\QB). The build is deterministic: same sources, byte-identical file.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_SUFFIXES = {".py", ".html", ".css", ".js", ".json", ".txt"}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

BOOTSTRAP = r'''"""QueryBook Next {version} — single-file launcher. See README.md in the project for details."""
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

BUILD = "{build}"


def cache_root() -> Path:
    env = os.environ.get("QB_CACHE_DIR")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "QueryBook-Next"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "QueryBook-Next"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "querybook-next"


def unpack(pyz: Path) -> Path:
    target = cache_root() / ("app-" + BUILD)
    if (target / ".complete").is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="unpack-", dir=target.parent))
    with zipfile.ZipFile(pyz) as zf:
        for name in zf.namelist():
            if name.startswith("app/") and not name.endswith("/"):
                dest = tmp / name[4:]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
    (tmp / ".complete").write_text(BUILD, encoding="utf-8")
    try:
        tmp.rename(target)
    except OSError:  # another start unpacked it at the same moment
        shutil.rmtree(tmp, ignore_errors=True)
    return target


def main() -> int:
    if sys.version_info < (3, 10):
        print("QueryBook Next needs Python 3.10 or newer: https://www.python.org/downloads/")
        return 1
    pyz = Path(sys.argv[0]).resolve()
    app = unpack(pyz)
    beside = pyz.parent / "data-folder.txt"
    if beside.is_file():  # the user's own setting wins over the built-in D:\QB
        shutil.copyfile(beside, app / "data-folder.txt")
    sys.path.insert(0, str(app))
    from querybook.cli import main as cli_main
    return cli_main(sys.argv[1:] or ["serve", "--open"])


if __name__ == "__main__":
    raise SystemExit(main())
'''


def sources() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for path in sorted((ROOT / "querybook").rglob("*")):
        if path.is_file() and path.suffix in INCLUDE_SUFFIXES and "__pycache__" not in path.parts:
            files.append(("app/" + path.relative_to(ROOT).as_posix(), path.read_bytes()))
    files.append(("app/data-folder.txt", (ROOT / "data-folder.txt").read_bytes()))
    return files


def build(out: Path) -> Path:
    from querybook import __version__

    files = sources()
    digest = hashlib.sha256()
    for name, data in files:
        digest.update(name.encode() + b"\0" + data + b"\0")
    bootstrap = BOOTSTRAP.replace("{version}", __version__).replace("{build}", f"{__version__}-{digest.hexdigest()[:12]}")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        fh.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, data in [("__main__.py", bootstrap.encode("utf-8"))] + files:
                info = zipfile.ZipInfo(name, FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                zf.writestr(info, data)
    tmp.replace(out)
    out.chmod(0o755)
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "querybook-next.pyz"
    print(build(target))
