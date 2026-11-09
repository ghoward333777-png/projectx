"""Build QueryBook.zip for Windows with Python inside (no install, no PATH).

    python tools/build_windows_bundle.py [embed-zip] [out.zip]

Contents:  QueryBook/START-QueryBook.bat   double-click this
           QueryBook/querybook-next.pyz    the app (tools/build_pyz.py)
           QueryBook/python/               python.org's embeddable Python (unchanged)
           QueryBook/READ-ME.txt
The embeddable Python is downloaded from python.org when no path is given and is
checked against the SHA-256 python.org publishes for that release.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_VERSION = "3.13.17"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
EMBED_SHA256 = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"  # python.org SBOM for 3.13.17
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

START_BAT = (
    "@echo off\r\n"
    "rem QueryBook Next - double-click to start. Python is included in the python folder.\r\n"
    "cd /d \"%~dp0\"\r\n"
    "\"%~dp0python\\python.exe\" \"%~dp0querybook-next.pyz\" %*\r\n"
    "if errorlevel 1 pause\r\n"
)

README = (
    "QueryBook Next\r\n"
    "\r\n"
    "1. Unzip this file (right-click > Extract All).\r\n"
    "2. Open the QueryBook folder and double-click START-QueryBook.bat\r\n"
    "3. Your browser opens QueryBook. Keep the black window open while you use it.\r\n"
    "\r\n"
    "Python is included - nothing to install.\r\n"
    "It reads your facts on D:\\QB and never changes them.\r\n"
)


def embed_zip(path: str | None) -> bytes:
    data = Path(path).read_bytes() if path else urllib.request.urlopen(EMBED_URL, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EMBED_SHA256:
        raise SystemExit(f"Embeddable Python checksum mismatch: {digest}")
    return data


def build(embed: bytes, out: Path) -> Path:
    sys.path.insert(0, str(ROOT / "tools"))
    import build_pyz

    pyz = build_pyz.build(out.parent / "querybook-next.pyz.tmp-build")
    entries: list[tuple[str, bytes]] = [
        ("QueryBook/START-QueryBook.bat", START_BAT.encode()),
        ("QueryBook/READ-ME.txt", README.encode()),
        ("QueryBook/querybook-next.pyz", pyz.read_bytes()),
    ]
    import io
    with zipfile.ZipFile(io.BytesIO(embed)) as src:
        for name in sorted(src.namelist()):
            if not name.endswith("/"):
                entries.append(("QueryBook/python/" + name, src.read(name)))
    pyz.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in entries:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    src = sys.argv[1] if len(sys.argv) > 1 else None
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "dist" / "QueryBook.zip"
    print(build(embed_zip(src), target))
