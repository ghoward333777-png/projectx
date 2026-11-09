#!/usr/bin/env python3
"""Rebuild language/data/bilingual.json.gz from the MUSE bilingual dictionaries.

MUSE (Facebook AI Research, CC BY-NC 4.0): https://github.com/facebookresearch/MUSE — the
"ground-truth bilingual dictionaries" en-xx.txt, one "english foreign" pair per line.
Only English words in the bundled frequency list (language/data/english_dictionary.json.gz)
are kept, up to MAX_FORMS translations each, in MUSE's order. Run once; the result is bundled.
"""
import gzip, json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "language", "data")
URL = "https://dl.fbaipublicfiles.com/arrival/dictionaries/en-%s.txt"
LANGS = ["es", "fr", "de", "it", "pt", "nl", "sv", "da", "no", "fi", "pl", "cs", "el", "ro", "hu", "ca"]
MAX_FORMS = 4

if __name__ == "__main__":
    words = set(json.load(gzip.open(os.path.join(DATA, "english_dictionary.json.gz"))))
    out = {"_meta": {"source": "MUSE bilingual dictionaries (Facebook AI Research), ground-truth en-xx dictionaries",
                     "license": "CC BY-NC 4.0", "url": "https://github.com/facebookresearch/MUSE",
                     "note": "Demonstration data for non-commercial use; replace with a permissively licensed source before any commercial release.",
                     "languages": LANGS}}
    for lang in LANGS:
        with urllib.request.urlopen(URL % lang, timeout=120) as r:
            text = r.read().decode("utf-8", "replace")
        d = {}
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) != 2:
                continue
            en, fw = parts[0].lower(), parts[1]
            if en in words and en.isalpha() and fw.lower() != en:
                forms = d.setdefault(en, [])
                if fw not in forms and len(forms) < MAX_FORMS:
                    forms.append(fw)
        out[lang] = d
        print("%s: %d English words" % (lang, len(d)), flush=True)
    raw = json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(os.path.join(DATA, "bilingual.json.gz"), "wb", mtime=0) as f:
        f.write(raw)
    print("wrote bilingual.json.gz: %d KB" % (os.path.getsize(os.path.join(DATA, "bilingual.json.gz")) // 1024))
