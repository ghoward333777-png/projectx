"""The Language Lab's languages: every language of QueryBook Translate's registry that QueryBook can translate and speak.

Translation, best first:
  1 offline   the Translate dictionary packs (12 languages) and the Language Builder's word lists (17 languages) —
              every word shows where it came from
  2 online    Google Translate (Cloud Translation API, the Google key saved under Diagnostics -> Google Cloud), else
              Gemini (the Gemini key) — used when a language has no offline data, or the offline result has gaps;
              labelled as such
Speech, best first: the espeak-ng voice for the language (about 100 languages), else the browser's own voice for it
(Windows / Edge have voices for many more) — the page falls back by itself.
Standard library only.
"""
import json, os, re, subprocess, threading, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "ui", "translate", "data", "languages.json")
CATALOG = os.path.join(HERE, "ui", "translate", "packs", "catalog.json")
# registry codes whose espeak-ng language code differs
ESPEAK_ALIASES = {"zh": "cmn", "fil": "tl", "nb": "nb", "no": "nb", "he": "he", "ms": "ms", "fa": "fa", "yue": "yue", "sr": "sr", "pt": "pt",
                  "jv": "jv", "ceb": "", "qu": "qu", "nv": "", "co": "", "ny": "", "ha": "", "yo": "", "zu": "", "so": "", "ps": "", "km": "", "lo": ""}
_CACHE = {}
_LOCK = threading.Lock()


def registry():
    with open(REGISTRY, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("languages", []) if isinstance(d, dict) else d


def pack_languages():
    try:
        with open(CATALOG, encoding="utf-8") as f:
            return sorted({p["lang"] for p in json.load(f).get("packs") or []})
    except (OSError, ValueError):
        return []


def espeak_languages(espeak_path):
    """the language codes espeak-ng has voices for ('en', 'en-us', 'cmn', ...) — read once from `espeak-ng --voices`"""
    with _LOCK:
        if "espeak" in _CACHE:
            return _CACHE["espeak"]
        codes = set()
        if espeak_path:
            try:
                out = subprocess.run([espeak_path, "--voices"], capture_output=True, text=True, timeout=20).stdout
                for line in out.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        codes.add(parts[1].lower())
            except (OSError, subprocess.SubprocessError):
                pass
        _CACHE["espeak"] = codes
        return codes


def espeak_voice(code, espeak_codes):
    """the espeak-ng voice for a registry language code, or '' when espeak-ng has none"""
    c = ESPEAK_ALIASES.get(code, code)
    if not c:
        return ""
    if c in espeak_codes:
        return c
    pref = [x for x in espeak_codes if x.split("-")[0] == c]
    return sorted(pref, key=len)[0] if pref else ""


def languages(builder, espeak_path, cloud):
    """builder: the Language Builder's 17 languages {code: {name, native, espeak}}; cloud: whether online translation is set up.
    Returns the Lab's list: the Builder's languages first, then every registry language QueryBook can translate."""
    codes = espeak_languages(espeak_path)
    packs = set(pack_languages())
    out, seen = [], set()
    reg = {l["code"]: l for l in registry()}
    order = list(builder) + [c for c in reg if c not in builder]
    for code in order:
        r = reg.get(code, {})
        b = builder.get(code) or {}
        offline = code in packs or code in builder
        voice = b.get("espeak") or espeak_voice(code, codes)
        if not (offline or cloud):
            continue                               # nothing could translate it here: left out rather than shown broken
        dialects = r.get("dialects") or []
        out.append({"code": code, "name": b.get("name") or r.get("name") or code, "native": b.get("native") or r.get("native") or "",
                    "speech": dialects[0][0] if dialects else code, "espeak": voice, "offline": offline,
                    "words": code in builder, "pack": code in packs, "script": r.get("script") or "Latn"})
        seen.add(code)
    return out


# --------------------------------------------------------------------------- online translation
def _post(url, body, headers, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except Exception:
            msg = ""
        raise RuntimeError("HTTP %d %s" % (e.code, msg or e.reason))


def google_translate(key, text, src, tgt, url="https://translation.googleapis.com/language/translate/v2"):
    r = _post(url + "?key=" + urllib.parse.quote(key), {"q": text, "source": src, "target": tgt, "format": "text"}, {})
    t = ((r.get("data") or {}).get("translations") or [{}])[0].get("translatedText") or ""
    if not t:
        raise RuntimeError("no translation returned")
    return t


def gemini_translate(key, text, src_name, tgt_name, model="gemini-3.5-flash",
                     url="https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"):
    prompt = ("Translate the following text from %s into %s. Reply with the translation only — no quotes, notes or "
              "transliteration.\n\n%s" % (src_name, tgt_name, text))
    r = _post(url % model if "%s" in url else url, {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, {"x-goog-api-key": key})
    cand = (r.get("candidates") or [{}])[0]
    t = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])).strip()
    if not t:
        raise RuntimeError("no translation returned")
    return t


def cloud_translate(keys, text, src, tgt, names, urls=None):
    """keys: {"google": api key, "gemini": api key}. Google Translate first, then Gemini. Returns {text, by} or raises."""
    urls = urls or {k: v for k, v in (("google", os.environ.get("QB_TEST_GOOGLE_TR_URL")), ("gemini", os.environ.get("QB_TEST_GEMINI_TR_URL"))) if v}
    why = []
    if keys.get("google"):
        try:
            return {"text": google_translate(keys["google"], text, src, tgt, urls.get("google", "https://translation.googleapis.com/language/translate/v2")),
                    "by": "Google Translate"}
        except (RuntimeError, OSError, ValueError) as e:
            why.append("Google Translate: %s" % e)
    if keys.get("gemini"):
        try:
            return {"text": gemini_translate(keys["gemini"], text, names.get(src, src), names.get(tgt, tgt),
                                             url=urls.get("gemini", "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent")),
                    "by": "Gemini (AI translation)"}
        except (RuntimeError, OSError, ValueError) as e:
            why.append("Gemini: %s" % e)
    raise RuntimeError("; ".join(why) or "no Google or Gemini key is saved (Speech -> Voice providers, or Diagnostics -> Google Cloud)")


def control_panel_key(service):
    """a key saved in the Control Panel (Harvesting -> API keys: api-keys.json in the commons folder)"""
    folder = os.environ.get("QB_COMMONS_DATA") or ""
    for p in (os.path.join(folder, "api-keys.json"), os.path.join(os.path.dirname(folder), "commons", "api-keys.json")) if folder else ():
        try:
            with open(p, encoding="utf-8") as f:
                v = (json.load(f) or {}).get(service)
            if v:
                return v
        except (OSError, ValueError):
            continue
    return ""


def self_test():
    import http.server, socketserver, tempfile
    results = []
    builder = {"en": {"name": "English", "native": "English", "espeak": "en"}, "es": {"name": "Spanish", "native": "Español", "espeak": "es"}}
    _CACHE["espeak"] = {"en", "en-us", "es", "fr", "cmn", "sw", "pl"}
    try:
        off = languages(builder, "", False)
        on = languages(builder, "", True)
        results.append(("without online translation: the Builder's languages and the dictionary packs only (nothing shown that cannot be translated)",
                        {l["code"] for l in off} == {"en", "es"} | set(pack_languages()) and all(l["offline"] for l in off)))
        results.append(("with online translation: every registry language (over 100), Builder languages first",
                        len(on) > 100 and [l["code"] for l in on[:2]] == ["en", "es"]))
        zh = next(l for l in on if l["code"] == "zh")
        sw = next(l for l in on if l["code"] == "sw")
        results.append(("espeak-ng voices found by language (Chinese -> cmn, Swahili -> sw); a language without one is marked for the browser voice",
                        zh["espeak"] == "cmn" and sw["espeak"] == "sw" and next(l for l in on if l["code"] == "yo")["espeak"] == ""))
        results.append(("each language carries its speech tag for the browser (dialect: en -> en-US)", on[0]["speech"] == "en-US"))
    finally:
        _CACHE.pop("espeak", None)
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if self.path.startswith("/google-fail"):
                out, code = {"error": {"message": "API not enabled"}}, 403
            elif self.path.startswith("/google"):
                out, code = {"data": {"translations": [{"translatedText": "Habari za asubuhi"}]}}, 200
            else:
                out, code = {"candidates": [{"content": {"parts": [{"text": "Habari za asubuhi, rafiki"}]}}]}, 200
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        r = cloud_translate({"google": "g"}, "Good morning", "en", "sw", {}, {"google": base + "/google"})
        results.append(("Google Translate: source and target sent, the translation returned and labelled", r == {"text": "Habari za asubuhi", "by": "Google Translate"}
                        and seen[-1][1] == {"q": "Good morning", "source": "en", "target": "sw", "format": "text"}))
        r = cloud_translate({"google": "g", "gemini": "k"}, "Good morning, friend", "en", "sw", {"en": "English", "sw": "Swahili"},
                            {"google": base + "/google-fail", "gemini": base + "/gemini"})
        results.append(("Google refuses -> Gemini translates (labelled as AI)", r["by"].startswith("Gemini") and "Swahili" in seen[-1][1]["contents"][0]["parts"][0]["text"]))
        try:
            cloud_translate({}, "x", "en", "sw", {})
            results.append(("no key: says which key to add", False))
        except RuntimeError as e:
            results.append(("no key: says which key to add", "key" in str(e)))
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "api-keys.json"), "w") as f:
            json.dump({"gemini": "cp-key"}, f)
        old = os.environ.get("QB_COMMONS_DATA")
        os.environ["QB_COMMONS_DATA"] = tmp
        try:
            results.append(("a key saved in the Control Panel is found", control_panel_key("gemini") == "cp-key"))
        finally:
            if old is None:
                os.environ.pop("QB_COMMONS_DATA", None)
            else:
                os.environ["QB_COMMONS_DATA"] = old
    finally:
        srv.shutdown()
    for name, ok in results:
        print("  [%s] %s" % ("OK" if ok else "FAIL", name))
    passed = sum(1 for _, ok in results if ok)
    print("\n  %d of %d checks passed" % (passed, len(results)))
    return passed == len(results)


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_test() else 1)
