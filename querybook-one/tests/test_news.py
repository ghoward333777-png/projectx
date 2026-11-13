"""Names in the news (apps/_core/qbnews.py) — the extractor of the news lattice. Text is the machine reading of old newspaper
pages: no punctuation, broken words. A name is kept only when shaped like one; the reason comes from the words around it."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apps", "_core"))
import qbnews  # noqa: E402

PAGE = ("Pres Harvey Jordan of the Southern Cotton Association will speak in this city March 8th GREENVILLE MISS SATURDAY MARCH 4 1905 "
        "ASSAULT AND ROBBERY Alonzo White was arrested Friday and charged before Judge Robinson Hearing Continued Mr A M Shelby of the plantation "
        "THEODORE ROOSEVELT TAKES OATH OF OFFICE President Sworn in on Steps of the Capitol by Chief Justice Fuller Fairbanks Was Installed "
        "U S WEATHER BUREAU WASHINGTON D C Mar 3 Mrs Jane L Stanford died at Honolulu General Strike While Japanese advance DOUGLAS ARIZONA")


class NamesTest(unittest.TestCase):
    def setUp(self):
        self.m = {x["name"]: x for x in qbnews.mentions(PAGE)}

    def test_names_shaped_like_names_are_found(self):
        for name in ("Harvey Jordan", "Alonzo White", "Judge Robinson", "A. M. Shelby", "Theodore Roosevelt", "Justice Fuller", "Jane L. Stanford"):
            self.assertIn(name, self.m)

    def test_headline_words_initials_and_places_are_not_names(self):
        for junk in ("Robinson Hearing", "President Sworn", "Fuller Fairbanks", "U. S. Weather", "D. C. Mar", "Gen. Strike", "Strike While", "Douglas Arizona"):
            self.assertNotIn(junk, self.m)

    def test_the_reason_is_read_from_the_words_around_the_name(self):
        self.assertEqual(self.m["Harvey Jordan"]["reason"], "spoke")
        self.assertEqual(self.m["Jane L. Stanford"]["reason"], "died")
        self.assertEqual(self.m["Alonzo White"]["reason"], "arrested or tried, as reported")     # a report, never a finding
        self.assertIn("Alonzo White was arrested Friday", self.m["Alonzo White"]["context"])      # the paper's own words are kept

    def test_a_name_with_nothing_said_about_it_is_only_mentioned(self):
        self.assertEqual(qbnews.mentions("the list included Oscar Schneider and others of the town")[0]["reason"], "mentioned")

    def test_what_is_recorded(self):
        self.assertEqual(qbnews.paper_of("Image 1 of The Greenville times (Greenville, Miss.), March 4, 1905"), "The Greenville times (Greenville, Miss.)")
        o = qbnews.fact_object("1905-03-04", "The Greenville times (Greenville, Miss.)", 1, self.m["Harvey Jordan"])
        self.assertTrue(o.startswith("1905-03-04 — The Greenville times (Greenville, Miss.), p. 1 — spoke — “"))


if __name__ == "__main__":
    unittest.main()
