"""Build the sample-ebook library: each book in apps/shell/library/<id>/ (meta.json, the Project Gutenberg text, modern.json)
becomes book.json.gz — chapters, numbered sections, Fact Units with anchors and fingerprints, and the modern layer linked to
the exact Fact Units it judges. Deterministic: the same inputs always give the same file.

    python tools/build_library.py          build every book
    python tools/build_library.py --check  fail if a book.json.gz is not what the inputs make (run by the tests)

Every modern entry's "match" patterns must each find at least one Fact Unit, or the build stops — so a 1903-vs-today
row is always tied to a sentence that really is in the book.
"""
import gzip
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "apps", "shell", "library")
sys.path.insert(0, os.path.join(ROOT, "apps", "_core"))
import bookq  # noqa: E402
import qbbooks  # noqa: E402


def build(folder):
    """one book folder -> its book.json document (the same assembly the Control Panel's Book Harvester uses)"""
    with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    text = read_text(folder, meta["text"])
    modern = None
    mp = os.path.join(folder, "modern.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            modern = json.load(f)
    try:
        return qbbooks.assemble(meta, text, modern)
    except ValueError as e:
        raise SystemExit(str(e))


def read_text(folder, name):
    path = os.path.join(folder, name)
    if name.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return f.read().decode("utf-8")
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv):
    check = "--check" in argv
    bad = 0
    for name in sorted(os.listdir(LIB)):
        folder = os.path.join(LIB, name)
        if not os.path.isfile(os.path.join(folder, "meta.json")):
            continue
        data = build(folder)
        out = os.path.join(folder, "book.json.gz")
        if check:
            try:
                with gzip.open(out, "rb") as f:
                    same = f.read().decode("utf-8") == data
            except OSError:
                same = False
            if not same:
                print("%s: book.json.gz is out of date — run python tools/build_library.py" % name)
                bad += 1
        else:
            with gzip.GzipFile(out, "wb", mtime=0) as f:      # mtime 0: the same inputs give the same bytes
                f.write(data.encode("utf-8"))
            b = json.loads(data)
            print("%-24s %4d chapters %6d Fact Units %3d people %3d modern" % (
                name, len(b["chapters"]), len(b["units"]), len(b["people"]), len(b["modern"])))
    cards = []
    for name in sorted(os.listdir(LIB)):
        bp = os.path.join(LIB, name, "book.json.gz")
        if os.path.isfile(bp):
            with gzip.open(bp, "rb") as f:
                c = bookq.overview(json.loads(f.read().decode("utf-8")))
            c.pop("chapters", None)
            cards.append(c)
    cards.sort(key=lambda c: (0 if c.get("kind") == "nonfiction" else 1, c.get("title") or ""))
    catalog = json.dumps({"books": cards}, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    cp = os.path.join(LIB, "catalog.json")
    if check:
        try:
            with open(cp, encoding="utf-8") as f:
                if f.read() != catalog:
                    print("catalog.json is out of date — run python tools/build_library.py")
                    bad += 1
        except OSError:
            print("catalog.json is missing — run python tools/build_library.py")
            bad += 1
    else:
        with open(cp, "w", encoding="utf-8", newline="\n") as f:
            f.write(catalog)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
