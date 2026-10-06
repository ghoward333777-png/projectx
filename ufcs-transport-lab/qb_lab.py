#!/usr/bin/env python3
"""QueryBook UFCS-FQL Lab: one-click launcher for Windows (Python standard library only).

Double-click START_LAB.bat, or run:

    python qb_lab.py              set up (first run only) and start the dashboard
    python qb_lab.py check        plain-English health check, changes nothing
    python qb_lab.py --no-video   skip the ffmpeg download (about 200 MB)
    python qb_lab.py --port 9000  use another port

The first run downloads three portable programs into this folder's runtime\\
folder: PHP 8.3 (about 32 MB, from windows.php.net), ffmpeg (about 200 MB, from
BtbN/FFmpeg-Builds on GitHub) and zstd (about 2 MB, from GitHub). Each download is checked against its
published SHA-256 before use. Nothing is installed system-wide, nothing needs admin
rights, and deleting the folder removes everything.

It also works on macOS and Linux with a PHP 8.1+ already installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

LAB = Path(__file__).resolve().parent
RUNTIME = LAB / "runtime"
PHP_DIR = RUNTIME / "php"
BIN_DIR = RUNTIME / "bin"
DOWNLOADS = RUNTIME / "downloads"
WINDOWS = os.name == "nt"

PHP_SERIES = "8.3"
PHP_INDEX = "https://windows.php.net/downloads/releases/releases.json"
PHP_BASE = "https://windows.php.net/downloads/releases/"
FFMPEG_RELEASES = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
ZSTD_ZIP = "https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-v1.5.7-win64.zip"
ZSTD_SHA256 = "acb4e8111511749dc7a3ebedca9b04190e37a17afeb73f55d4425dbf0b90fad9"
PHP_EXTENSIONS = ["mbstring", "sodium", "gd", "zip", "openssl", "fileinfo"]
USER_AGENT = "QueryBook-UFCS-Lab-launcher"


def say(msg: str = "") -> None:
    print(msg, flush=True)


def problem(msg: str, *fix: str) -> None:
    say("")
    say("[PROBLEM] " + msg)
    for line in fix:
        say("          " + line)
    say("")
    sys.exit(1)


# --- downloads ----------------------------------------------------------------

def fetch(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(url: str, dest: Path, sha256: str, label: str) -> Path:
    """Download to dest (resumable by re-running), verify SHA-256, return dest."""
    if dest.is_file() and sha256_of(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    say(f"  downloading {label} ...")
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done, last = 0, 0.0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if time.time() - last > 1 or done == total:
                    last = time.time()
                    pct = f"{done * 100 // total:3d}%" if total else ""
                    print(f"\r    {done / 1e6:7.1f} MB {pct}", end="", flush=True)
        print()
    except OSError as e:
        problem(f"Could not download {label}: {e}",
                "Check the internet connection (or a company proxy), then run START_LAB.bat again.",
                f"Address: {url}")
    got = sha256_of(part)
    if got != sha256.lower():
        part.unlink(missing_ok=True)
        problem(f"The {label} download did not match its published fingerprint, so it was deleted.",
                "This is usually a broken download. Run START_LAB.bat again.")
    part.replace(dest)
    return dest


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def php_release() -> tuple[str, str]:
    """(download URL, sha256) of the newest PHP 8.3 NTS x64 build for Windows."""
    try:
        index = json.loads(fetch(PHP_INDEX))
    except (OSError, ValueError) as e:
        problem(f"Could not read the PHP release list: {e}",
                "Check the internet connection, then run START_LAB.bat again.")
    series = index.get(PHP_SERIES) or {}
    builds = sorted(k for k in series if k.startswith("nts-vs") and k.endswith("-x64"))
    if not builds:
        problem(f"windows.php.net lists no PHP {PHP_SERIES} 64-bit build right now.",
                "Try again later, or install PHP 8.1+ yourself from https://windows.php.net/download")
    z = series[builds[-1]]["zip"]
    return PHP_BASE + z["path"], z["sha256"]


def setup_php() -> Path:
    exe = PHP_DIR / "php.exe"
    if not exe.is_file():
        say("Setting up PHP (first run only)")
        url, sha = php_release()
        zpath = download(url, DOWNLOADS / url.rsplit("/", 1)[1], sha, "PHP " + PHP_SERIES)
        tmp = RUNTIME / "php.new"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        shutil.rmtree(PHP_DIR, ignore_errors=True)
        tmp.replace(PHP_DIR)
    write_php_ini()
    ensure_vc_runtime(exe)
    return exe


VC_REDIST = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def php_runs(exe: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run([str(exe), "-n", "-v"], capture_output=True, text=True, timeout=60)
    except OSError as e:
        return False, str(e)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0 and "VCRUNTIME" not in out and out.startswith("PHP "), out.strip()


def ensure_vc_runtime(exe: Path) -> None:
    """PHP for Windows needs Microsoft's Visual C++ 2015-2022 runtime (x64).
    Most PCs have it; when this one does not, install it (Windows asks once)."""
    ok, out = php_runs(exe)
    if ok:
        return
    say("PHP needs the Microsoft Visual C++ runtime, which this PC does not have yet.")
    say("Downloading it from Microsoft. Windows will ask for permission to install it.")
    dest = DOWNLOADS / "vc_redist.x64.exe"
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    try:
        dest.write_bytes(fetch(VC_REDIST, timeout=300))
    except OSError as e:
        problem(f"Could not download the Visual C++ runtime: {e}",
                "Install it yourself from https://aka.ms/vs/17/release/vc_redist.x64.exe",
                "then double-click START_LAB.bat again.")
    # Start-Process -Verb RunAs shows the standard Windows permission prompt and waits.
    ps = ("Start-Process -Wait -Verb RunAs -FilePath '" + str(dest).replace("'", "''")
          + "' -ArgumentList '/install','/passive','/norestart'")
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        problem(f"Could not start the Visual C++ runtime installer: {e}",
                f"Double-click {dest} yourself, then double-click START_LAB.bat again.")
    ok, out = php_runs(exe)
    if not ok:
        problem("PHP still does not start after installing the Visual C++ runtime.",
                "Restart the PC and double-click START_LAB.bat again.",
                "PHP said: " + (out.splitlines()[0] if out else "nothing"))


def write_php_ini() -> None:
    """php.ini next to php.exe, so every PHP process the lab starts finds it.
    Rewritten on every start, so the folder can be moved."""
    ext_dir = PHP_DIR / "ext"
    lines = [
        "; Written by qb_lab.py on every start. Edit qb_lab.py instead.",
        f'extension_dir = "{ext_dir}"',
        *[f"extension={e}" for e in PHP_EXTENSIONS if (ext_dir / f"php_{e}.dll").is_file()],
        "zend_extension=opcache" if (ext_dir / "php_opcache.dll").is_file() else "",
        "memory_limit = 2G",
        "upload_max_filesize = 256M",
        "post_max_size = 256M",
        "max_execution_time = 0",
        "date.timezone = UTC",
        f'curl.cainfo = "{PHP_DIR / "extras" / "ssl" / "cacert.pem"}"' if (PHP_DIR / "extras" / "ssl" / "cacert.pem").is_file() else "",
    ]
    (PHP_DIR / "php.ini").write_text("\n".join(l for l in lines if l) + "\n", encoding="utf-8")


def setup_ffmpeg() -> None:
    if (BIN_DIR / "ffmpeg.exe").is_file() and (BIN_DIR / "ffprobe.exe").is_file():
        return
    say("Setting up ffmpeg for video (first run only, about 200 MB)")
    try:
        sums = fetch(FFMPEG_RELEASES + "checksums.sha256").decode()
    except OSError as e:
        problem(f"Could not read the ffmpeg release list: {e}",
                "Check the internet connection, or start without video: py qb_lab.py --no-video")
    # Newest stable full build, e.g. ffmpeg-n9.0-latest-win64-gpl-9.0.zip (has x264, x265, SVT-AV1, Opus).
    builds = []
    for line in sums.splitlines():
        parts = line.split()
        m = re.fullmatch(r"ffmpeg-n(\d+)\.(\d+)-latest-win64-gpl-[\d.]+\.zip", parts[-1]) if len(parts) == 2 else None
        if m:
            builds.append(((int(m.group(1)), int(m.group(2))), parts[1], parts[0]))
    if not builds:
        problem("The ffmpeg release list has no Windows build right now.",
                "Try again later, or start without video: py qb_lab.py --no-video")
    _, name, sha = max(builds)
    zpath = download(FFMPEG_RELEASES + name, DOWNLOADS / name, sha, "ffmpeg")
    extract_exes(zpath, ["ffmpeg.exe", "ffprobe.exe"])


def setup_zstd() -> None:
    if (BIN_DIR / "zstd.exe").is_file():
        return
    say("Setting up zstd (first run only, about 2 MB)")
    zpath = download(ZSTD_ZIP, DOWNLOADS / "zstd-win64.zip", ZSTD_SHA256, "zstd")
    extract_exes(zpath, ["zstd.exe"])


def extract_exes(zpath: Path, names: list[str]) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath) as z:
        for name in names:
            member = next((m for m in z.namelist() if m.endswith("/" + name) or m == name), None)
            if member is None:
                problem(f"{name} was not in the download {zpath.name}.", "Delete the runtime folder and run START_LAB.bat again.")
            with z.open(member) as src, open(BIN_DIR / name, "wb") as dst:
                shutil.copyfileobj(src, dst)


# --- PHP selection ------------------------------------------------------------

def system_php() -> str:
    php = shutil.which("php")
    if php and subprocess.run([php, "-r", "exit(PHP_VERSION_ID >= 80100 ? 0 : 1);"]).returncode == 0:
        return php
    return ""


def choose_php(no_video: bool, offline_ok: bool = False) -> str:
    if WINDOWS:
        if offline_ok and not (PHP_DIR / "php.exe").is_file():
            return ""
        exe = str(setup_php())
        if not offline_ok:
            setup_zstd()
            if not no_video:
                setup_ffmpeg()
        return exe
    php = system_php()
    if not php and not offline_ok:
        problem("PHP 8.1 or newer is not installed.", "Run ./install.sh (Linux or macOS), or: docker compose up")
    return php


def lab_env() -> dict[str, str]:
    env = dict(os.environ)
    if BIN_DIR.is_dir():
        env["PATH"] = str(BIN_DIR) + os.pathsep + env.get("PATH", "")
    if WINDOWS and PHP_DIR.is_dir():
        env["PATH"] = str(PHP_DIR) + os.pathsep + env["PATH"]
        env["PHPRC"] = str(PHP_DIR)
    return env


# --- commands -------------------------------------------------------------------

def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def cmd_check() -> int:
    say("QueryBook UFCS-FQL Lab - health check (changes nothing)")
    say("")
    ok = sys.version_info >= (3, 8)
    say(f"[{'OK' if ok else 'PROBLEM'}] Python {sys.version.split()[0]}")
    php = choose_php(no_video=True, offline_ok=True)
    if not php:
        say("[PROBLEM] PHP is not set up yet.")
        say("          Double-click START_LAB.bat: it downloads a private copy on first run.")
        return 1
    say(f"[OK] PHP: {php}")
    for tool in ("ffmpeg.exe", "zstd.exe") if WINDOWS else ():
        have = (BIN_DIR / tool).is_file()
        say(f"[{'OK' if have else 'OPTIONAL'}] {tool}" + ("" if have else " not downloaded yet (START_LAB.bat fetches it)"))
    say(f"[{'OK' if port_free(8091) else 'OPTIONAL'}] port 8091 " + ("is free" if port_free(8091) else "is busy: the lab may already be running, or use --port"))
    say("")
    say("Detailed check from the lab itself:")
    say("")
    return subprocess.run([php, str(LAB / "bin" / "doctor.php")], cwd=LAB, env=lab_env()).returncode


def cmd_start(port: int, no_video: bool, open_browser: bool) -> int:
    if sys.version_info < (3, 8):
        problem("This launcher needs Python 3.8 or newer.", "Install it from https://www.python.org/downloads/")
    php = choose_php(no_video)
    env = lab_env()
    doctor = subprocess.run([php, str(LAB / "bin" / "doctor.php")], cwd=LAB, env=env, capture_output=True, text=True)
    if doctor.returncode != 0:
        say(doctor.stdout + doctor.stderr)
        problem("The lab's own check found something missing (marked [NEED] above).")
    if not port_free(port):
        problem(f"Port {port} is already in use.",
                "The lab may already be running: open http://127.0.0.1:%d" % port,
                "Or start on another port:  python qb_lab.py --port 9000")
    url = f"http://127.0.0.1:{port}/"
    say("")
    say("=" * 60)
    say(f"  QueryBook UFCS-FQL Lab is running:  {url}")
    say("  Leave this window open while you use it. Close it to stop.")
    say("=" * 60)
    say("")
    server = subprocess.Popen([php, "-S", f"127.0.0.1:{port}", "-t", str(LAB / "web")], cwd=LAB, env=env)
    if open_browser:
        for _ in range(50):
            if not port_free(port):
                webbrowser.open(url)
                break
            time.sleep(0.1)
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="QueryBook UFCS-FQL Lab launcher")
    ap.add_argument("command", nargs="?", default="start", choices=["start", "check", "setup"])
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--no-video", action="store_true", help="skip the ffmpeg download")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    os.chdir(LAB)
    if a.command == "check":
        return cmd_check()
    if a.command == "setup":
        php = choose_php(a.no_video)
        return subprocess.run([php, str(LAB / "bin" / "doctor.php")], cwd=LAB, env=lab_env()).returncode
    return cmd_start(a.port, a.no_video, not a.no_browser)


if __name__ == "__main__":
    sys.exit(main())
