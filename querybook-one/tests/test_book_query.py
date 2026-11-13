"""Book Query and the sample-ebook library (apps/shell/bookq.py, apps/shell/library, tools/build_library.py)."""
import gzip
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "apps", "shell", "library")
sys.path.insert(0, os.path.join(ROOT, "apps", "shell"))
import bookq  # noqa: E402

_CACHE = {}


def load(book_id):
    if book_id not in _CACHE:
        with gzip.open(os.path.join(LIB, book_id, "book.json.gz"), "rb") as f:
            b = json.loads(f.read().decode("utf-8"))
        _CACHE[book_id] = (b, bookq.index(b))
    return _CACHE[book_id]


def ask(book_id, q):
    b, i = load(book_id)
    return bookq.answer(b, i, q)


class LibraryTest(unittest.TestCase):
    def test_built_files_match_their_sources(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_library.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_library(self):
        with open(os.path.join(LIB, "catalog.json"), encoding="utf-8") as f:
            books = json.load(f)["books"]
        ids = {b["id"] for b in books}
        self.assertEqual(len(books), 22)
        self.assertFalse(any("darwin" in i for i in ids))               # the user's decision: no Darwin
        self.assertEqual(sum(1 for b in books if b["kind"] == "fiction"), 10)
        for b in books:
            # every edition names its source and says the source does not endorse it (two Bibles come from eBible.org)
            self.assertRegex(b["provenance"]["rights"], r"Not endorsed by (Project Gutenberg|eBible\.org)", b["id"])
            self.assertIn("ublic domain", b["provenance"]["rights"], b["id"])
            self.assertGreater(b["units"], 1000, b["id"])
            text = gzip.open(os.path.join(LIB, b["id"], "text.txt.gz")).read().decode("utf-8")
            self.assertNotIn("*** START OF THE PROJECT GUTENBERG", text, b["id"])   # the edition carries no PG licence or trademark text

    def test_every_answer_line_is_anchored(self):
        r = ask("comstock-astronomy", "What is a light year?")
        self.assertTrue(r["passages"])
        for p in r["passages"]:
            self.assertTrue(p["anchor"].startswith("Chapter "), p["anchor"])
            self.assertTrue(p["unit"].startswith("FU-"))


class ComstockTest(unittest.TestCase):
    def test_two_layers(self):
        r = ask("comstock-astronomy", "Show me everything science has discovered or corrected since this textbook was published")
        self.assertEqual(r["intent"], "since")
        self.assertGreaterEqual(len(r["assertions"]), 15)
        self.assertTrue(all(a["status"] in ("Refined", "Superseded", "Incorrect") for a in r["assertions"]))
        self.assertTrue(all(a["sources"] and a["book"] for a in r["assertions"]))
        self.assertGreaterEqual(len(r["new_since"]), 10)
        r = ask("comstock-astronomy", "Which statements in Chapter X are still considered correct?")
        self.assertEqual(r["chapter"], 10)
        self.assertTrue(all(a["status"] == "Confirmed" for a in r["assertions"]))
        r = ask("comstock-astronomy", "Explain why the shrinking of the sun was reasonable in 1903 but is no longer accepted")
        self.assertIn("fusion", r["lead"])

    def test_retrieval(self):
        r = ask("comstock-astronomy", "How did Neptune come to be discovered?")
        self.assertIn("Discovery Of Neptune", r["passages"][0]["anchor"])
        r = ask("comstock-astronomy", "How far away is the sun?")
        self.assertIn("93,000,000 miles", r["lead"])
        self.assertEqual(r["assertions"][0]["id"], "sun-distance")
        self.assertTrue(ask("comstock-astronomy", "xylophone quartet")["lead"].startswith("The book does not say"))


class NarrativeTest(unittest.TestCase):
    def test_war_and_peace(self):
        r = ask("tolstoy-war-peace", "Show the relationship network around Pierre")
        self.assertEqual(r["intent"], "network")
        self.assertIn(r["edges"][0]["with"], ("Natásha Rostóva", "Prince Andrew Bolkónski"))
        r = ask("tolstoy-war-peace", "Trace the Rostov family")              # no accents typed
        self.assertEqual(r["intent"], "trace")
        self.assertGreater(len(r["chapters"]), 100)
        r = ask("tolstoy-war-peace", "Separate fictional characters from historical figures")
        self.assertTrue(any(p["name"] == "Kutúzov" and p["group"] == "historical" for p in r["people"]))
        self.assertTrue(any(p["name"].startswith("Pierre") and p["group"] == "fictional" for p in r["people"]))
        self.assertIn("Borodin", ask("tolstoy-war-peace", "the battle of Borodino")["passages"][0]["text"])

    def test_holmes_evidence_in_story_order(self):
        r = ask("doyle-sherlock-holmes", "Separate observed evidence from Holmes's deduction in The Red-Headed League")
        self.assertEqual(r["intent"], "evidence")
        self.assertIn("Red-headed League", r["passages"][0]["anchor"])
        self.assertTrue(all(p["reasoning"] in ("observed", "deduced") for p in r["passages"]))
        units = [p["unit"] for p in r["passages"]]
        b, _ = load("doyle-sherlock-holmes")
        pos = {u["id"]: k for k, u in enumerate(b["units"])}
        self.assertEqual([pos[u] for u in units], sorted(pos[u] for u in units))

    def test_front_matter_is_not_an_appearance(self):
        r = ask("austen-pride", "Trace the Bennet family")
        self.assertTrue(r["chapters"][0]["name"].startswith("Chapter I"))

    def test_history_beside_fiction(self):
        r = ask("dickens-two-cities", "Separate fictional events from real history")
        self.assertTrue(any(a["id"] == "bastille" for a in r["assertions"]))
        r = ask("gibbon-decline-fall", "What causes does Gibbon give for the decline of Rome?")
        self.assertIn("immoderate greatness", r["lead"])
        self.assertTrue(any(a["id"] == "decline-causes" for a in r["assertions"]))


class ParserTest(unittest.TestCase):
    def test_sentences_and_quantities(self):
        s = bookq.sentences("We have found (§ 141) that it requires light 8m. 18s. to come from the sun, i. e., 93,000,000 miles. Fig. 86 shows it.")
        self.assertEqual(len(s), 2)
        self.assertEqual([q["raw"] for q in bookq.quantities(s[0])], ["8m.", "18s.", "93,000,000 miles"])   # 8 minutes 18 seconds, and the distance

    def test_contents_pages_and_parts(self):
        text = "\n".join(["VOLUME ONE", "", "Chapter I: Alpha.", "", "Chapter II: Beta.", "", "VOLUME TWO", "", "Chapter III: Gamma.", "", "",
                         "Chapter I: Alpha.", "", "x " * 200, "", "Chapter II: Beta.", "", "y " * 200, "", "VOLUME TWO", "", "Chapter III: Gamma.", "", "z " * 200])
        ch = bookq.parse(text, {"parts": [r"VOLUME [A-Z]+"], "chapters": [r"Chapter [IVX]+: .*"], "first_part": "Volume One", "min_chars": 100})
        self.assertEqual([(c["part"], c["label"]) for c in ch if c["n"]],
                         [("Volume One", "Chapter I: Alpha"), ("Volume One", "Chapter II: Beta"), ("Volume Two", "Chapter III: Gamma")])

    def test_years(self):
        units = [{"kind": "assertion", "text": "Odoacer ruled from A.D. 476; Caesar died 44 B.C.; Borodino was in 1812."}]
        self.assertEqual([y for y, _ in bookq.years(units, 10)], [476, -44, 1812])


if __name__ == "__main__":
    unittest.main()


class WindowLibraryTest(unittest.TestCase):
    """the one window's Book Query page: the library list, a book's card, reading a chapter"""

    def test_list_card_and_chapter(self):
        import shell
        lib = shell.Library([LIB, ""])
        books = lib.list()
        self.assertEqual(len(books), 22)
        wp = next(b for b in books if b["id"] == "tolstoy-war-peace")
        self.assertIn("Pierre Bezúkhov", wp["top_people"])
        self.assertIn("Rostóv", wp["families"])
        ch = lib.chapter("comstock-astronomy", 9)
        self.assertEqual(ch["chapter"]["label"], "Chapter IX")
        self.assertEqual((ch["prev"], ch["next"]), (8, 10))
        self.assertTrue(all(u["id"].startswith("FU-") for p in ch["paragraphs"] for u in p["units"]))
        with self.assertRaises(ValueError):
            lib.get("darwin-origin")


class AnswerEngineTest(unittest.TestCase):
    """the answer engine without a key (the rules) — one book and several; the model path is tested in qbcompose's self-test"""

    def test_one_and_several_books(self):
        import shell
        lib = shell.Library([LIB, ""])

        class S:
            library = lib
            root = ""
        r = shell.book_ask(S, {"book": "melville-moby-dick", "q": "Why does Ahab hunt the white whale?", "ai": False})
        c = r["composed"]
        self.assertTrue(c["answered"])
        self.assertEqual(c["by"], "rules")
        self.assertIn("Ahab", c["answer"])
        labels = {p["label"] for p in c["evidence"]}
        self.assertTrue(set(c["answer_cites"]) <= labels)
        m = shell.book_ask(S, {"books": ["melville-moby-dick", "shelley-frankenstein", "stoker-dracula"], "q": "What does each book say about revenge?", "ai": False})
        self.assertTrue(m["multi"])
        self.assertEqual({p["label"].split("-")[0] for p in m["composed"]["evidence"]}, {"B1", "B2", "B3"})
        self.assertEqual(len(m["composed"]["by_book"]), 3)
        lst = shell.book_ask(S, {"book": "tolstoy-war-peace", "q": "Show the relationship network around Pierre"})
        self.assertNotIn("composed", lst)                  # list questions keep their exact lists
        self.assertTrue(lst["edges"])
