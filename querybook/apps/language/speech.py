"""Optional offline speech through espeak-ng.

The page speaks with the browser's own voices first (Windows, macOS and most Linux desktops
include voices for many languages). When the browser has no voice for a language, the page
asks this module, which uses espeak-ng if it is installed — on the PATH, in an `espeak`
folder next to this program (the Windows build from the earlier QueryBook works), or at the
path in the QB_ESPEAK environment variable. espeak-ng also gives a phonetic (IPA) spelling.
Nothing here is required: without espeak-ng the application works and says so.
"""
import os, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
_found = None


def find_espeak():
    global _found
    if _found is not None:
        return _found or None
    cands = [os.environ.get("QB_ESPEAK") or "", os.path.join(HERE, "espeak", "espeak-ng.exe"), os.path.join(HERE, "espeak", "espeak-ng"),
             shutil.which("espeak-ng") or "", shutil.which("espeak") or ""]
    for c in cands:
        if c and os.path.isfile(c):
            _found = c
            return c
    _found = ""
    return None


def _run(args, timeout=15):
    exe = find_espeak()
    if not exe:
        return None
    env = dict(os.environ)
    data = os.path.join(os.path.dirname(exe), "espeak-ng-data")
    if os.path.isdir(data):
        env["ESPEAK_DATA_PATH"] = os.path.dirname(exe)
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}      # no console window on Windows
    try:
        p = subprocess.run([exe] + args, capture_output=True, timeout=timeout, env=env, **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def speak_wav(text, voice, rate=150):
    """WAV bytes for `text`, or None when espeak-ng is not available."""
    text = " ".join(str(text or "").split())[:300]
    if not text:
        return None
    return _run(["-v", voice, "-s", str(int(rate)), "--stdout", "--", text])


def ipa(text, voice):
    out = _run(["-q", "--ipa", "-v", voice, "--", " ".join(str(text or "").split())[:200]])
    return out.decode("utf-8", "replace").strip() if out else None


def status():
    exe = find_espeak()
    return {"espeak": bool(exe), "path": exe}


def ipa_many(words, voice, chunk=400):
    """Phonetic spellings for many words with one espeak-ng call per chunk (one output line per word).
    Returns a list aligned with `words` (None where unavailable). Falls back to one call per word if lines do not line up."""
    exe = find_espeak()
    words = [" ".join(str(w).split()) for w in words]
    if not exe or not words:
        return [None] * len(words)
    out = []
    for i in range(0, len(words), chunk):
        part = words[i:i + chunk]
        env = dict(os.environ)
        data = os.path.join(os.path.dirname(exe), "espeak-ng-data")
        if os.path.isdir(data):
            env["ESPEAK_DATA_PATH"] = os.path.dirname(exe)
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
        try:
            p = subprocess.run([exe, "-q", "--ipa", "-v", voice], input="\n".join(part), capture_output=True, text=True,
                               timeout=60, env=env, encoding="utf-8", **kw)
            lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
        except (OSError, subprocess.TimeoutExpired):
            lines = []
        if len(lines) == len(part):
            out += lines
        else:
            out += [ipa(w, voice) for w in part]
    return out
