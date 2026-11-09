"""Optional offline speech through espeak-ng.

espeak-ng is the default voice. The official espeak-ng 1.51 Windows build is bundled in the
`espeak` folder (program, library, the Microsoft runtime it needs, and data for all 17
languages and the voice variants), so Windows needs no installation — as in the prototype.
macOS and Linux use the system espeak-ng (GET-VOICES-MAC.command / apt install espeak-ng).
espeak-ng also gives the phonetic (IPA) spelling.
"""
import os, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
_found = None


BUNDLED = os.path.join(HERE, "espeak")          # the official espeak-ng 1.51 Windows build ships here


def find_espeak():
    """The prototype's order: the copy BUNDLED with the app (Windows), then QB_ESPEAK, then the PATH,
    then the usual install folders. On macOS/Linux the bundled Windows .exe is skipped."""
    global _found
    if _found is not None:
        return _found or None
    cands = []
    if os.name == "nt":
        cands.append(os.path.join(BUNDLED, "espeak-ng.exe"))
    cands += [os.environ.get("QB_ESPEAK") or "", shutil.which("espeak-ng") or "", shutil.which("espeak") or "",
              r"C:\Program Files\eSpeak NG\espeak-ng.exe", r"C:\Program Files (x86)\eSpeak NG\espeak-ng.exe",
              "/opt/homebrew/bin/espeak-ng", "/usr/local/bin/espeak-ng", "/usr/bin/espeak-ng"]
    for c in cands:
        if c and os.path.isfile(c):
            _found = c
            return c
    _found = ""
    return None


def bundled_in_use():
    exe = find_espeak()
    return bool(exe) and os.path.normcase(os.path.dirname(os.path.abspath(exe))) == os.path.normcase(os.path.abspath(BUNDLED))


def cmd(args):
    """Full command line for espeak-ng: the bundled copy is told where its data is (--path), as in the prototype."""
    exe = find_espeak()
    return [exe] + (["--path=" + BUNDLED] if bundled_in_use() else []) + list(args)


def _kw():
    return {"creationflags": 0x08000000} if os.name == "nt" else {}      # no console window on Windows


def _run(args, timeout=15):
    if not find_espeak():
        return None
    try:
        p = subprocess.run(cmd(args), capture_output=True, timeout=timeout, **_kw())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def version():
    out = _run(["--version"], 5)
    return out.decode("utf-8", "replace").strip().splitlines()[0][:120] if out else None


def synth(args, text, timeout=60):
    """Run espeak-ng with `args` and return the WAV bytes it wrote.

    Always through a temporary FILE (-w), never through stdout: on Windows a program's stdout is in
    text mode, which inserts a carriage-return byte before every line-feed byte of the audio and
    turns speech into noise. A file is written in binary on every system (as the prototype did)."""
    if not find_espeak():
        return None
    import tempfile
    fd, path = tempfile.mkstemp(prefix="qb-voice-", suffix=".wav")
    os.close(fd)
    try:
        p = subprocess.run(cmd(list(args) + ["-w", path, "--", text]), capture_output=True, timeout=timeout, **_kw())
        if p.returncode != 0:
            raise RuntimeError("espeak-ng failed: %s" % p.stderr.decode("utf-8", "replace")[:200])
        with open(path, "rb") as f:
            data = f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return check_wav(data)


def check_wav(data):
    """Refuse audio damaged by a text-mode conversion (the 'scratchy noise' fault) instead of playing it."""
    if not data or data[:4] != b"RIFF":
        raise RuntimeError("espeak-ng returned no audio")
    i = data.find(b"data")
    body = data[i + 8:] if i > 0 else data[44:]
    lf = body.count(b"\n")
    if lf > 50 and body.count(b"\r\n") == lf:
        raise RuntimeError("the audio was damaged by a text-mode conversion (every line-feed byte has a carriage return before it)")
    return data


def speak_wav(text, voice, rate=150):
    """WAV bytes for `text`, or None when espeak-ng is not available."""
    text = " ".join(str(text or "").split())[:300]
    if not text:
        return None
    try:
        return synth(["-v", voice, "-s", str(int(rate))], text, 15)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None


def ipa(text, voice):
    out = _run(["-q", "--ipa", "-v", voice, "--", " ".join(str(text or "").split())[:200]])
    return out.decode("utf-8", "replace").strip() if out else None


def status():
    exe = find_espeak()
    return {"espeak": bool(exe), "path": exe, "bundled": bundled_in_use(), "version": version() if exe else None,
            "hint": None if exe else ("Windows: the bundled voice is missing from the espeak folder — reinstall the app. "
                                      "Mac: double-click GET-VOICES-MAC.command. Linux: sudo apt install espeak-ng.")}


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
        try:
            p = subprocess.run(cmd(["-q", "--ipa", "-v", voice]), input="\n".join(part), capture_output=True, text=True,
                               timeout=60, encoding="utf-8", **_kw())
            lines = [l.strip() for l in p.stdout.splitlines() if l.strip()]
        except (OSError, subprocess.TimeoutExpired):
            lines = []
        if len(lines) == len(part):
            out += lines
        else:
            out += [ipa(w, voice) for w in part]
    return out


_VOICES = {}


def voices():
    """every language espeak-ng can speak here: [{code, name, file, dict}] (dict: its pronunciation dictionary is present;
    without one espeak-ng spells words letter by letter in that language's sounds)"""
    exe = find_espeak()
    if not exe:
        return []
    if exe in _VOICES:
        return _VOICES[exe]
    out = _run(["--voices"], 20)
    rows = []
    data = os.path.join(BUNDLED, "espeak-ng-data") if bundled_in_use() else None
    have = {f[:-5] for f in os.listdir(data) if f.endswith("_dict")} if data and os.path.isdir(data) else None
    for line in (out or b"").decode("utf-8", "replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        code, name, fil = parts[1], parts[3].replace("_", " "), parts[4]
        base = code.split("-")[0]
        rows.append({"code": code, "name": name, "file": fil,
                     "dict": True if have is None else (base in have or code.replace("-", "_") in have or fil.split("/")[-1] in have)})
    rows.sort(key=lambda r: r["name"].lower())
    _VOICES[exe] = rows
    return rows


SCRIPTS = [("ja", r"[぀-ヿ]"), ("ko", r"[가-힯]"), ("cmn", r"[一-鿿]"), ("ru", r"[Ѐ-ӿ]"),
           ("el", r"[Ͱ-Ͽ]"), ("he", r"[֐-׿]"), ("ar", r"[؀-ۿ]"), ("hi", r"[ऀ-ॿ]"),
           ("bn", r"[ঀ-৿]"), ("ta", r"[஀-௿]"), ("th", r"[฀-๿]"), ("ka", r"[Ⴀ-ჿ]"),
           ("hy", r"[԰-֏]"), ("am", r"[ሀ-፿]")]


def detect_voice(text):
    """a likely espeak-ng language for the text: by its writing system, then by its small grammar words (17 languages)"""
    import re as _re
    for code, pat in SCRIPTS:
        if _re.search(pat, text or ""):
            return code, "writing system"
    try:
        import function_words as fw
        votes = {}
        for w in _re.findall(r"[^\W\d_]+", (text or "").lower()):
            for lang in fw.INDEX.get(w, ()):
                votes[lang] = votes.get(lang, 0) + 1
        if votes:
            best = max(sorted(votes), key=lambda k: votes[k])
            import vocab
            return vocab.LANGUAGES.get(best, {}).get("espeak", best), "grammar words"
    except Exception:
        pass
    return None, None


def speak_any(text, voice, rate=160, pitch=50, variant=""):
    """WAV bytes for longer texts in any espeak-ng language (voice + optional variant such as f3 or m2)"""
    text = " ".join(str(text or "").split())[:5000]
    if not text:
        return None
    v = voice + ("+" + variant if variant else "")
    return synth(["-v", v, "-s", str(int(rate)), "-p", str(int(pitch))], text, 120)
