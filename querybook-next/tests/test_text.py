import shutil
import subprocess
import unittest
from pathlib import Path

from querybook.core.model import DOMAINS
from querybook.core.text import classify, content_hash, keywords, normalize, normalize_paragraphs, sentences, tokenize

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "contracts" / "golden_text.tsv"
RUST_BIN = ROOT / "rust" / "querybook-core" / "target" / "release" / "querybook-core"


def unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            c = s[i + 1]
            if c == "u":
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append({"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}[c])
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def golden_rows():
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            yield line.split("\t")


class TextKernelTest(unittest.TestCase):
    def test_golden_vectors(self):
        rows = list(golden_rows())
        self.assertGreaterEqual(len(rows), 10)
        for raw, norm, h, domain, scores in rows:
            text = unescape(raw)
            with self.subTest(raw=raw):
                self.assertEqual(normalize(text), norm)
                self.assertEqual(content_hash(text), h)
                d, sc = classify(text)
                self.assertEqual(d, domain)
                self.assertEqual(",".join(str(sc[k]) for k in DOMAINS), scores)

    def test_tokenize_and_keywords(self):
        self.assertEqual(tokenize("F = m*a, Newton's 2nd!"), ["f", "m", "a", "newton", "s", "2nd"])
        self.assertEqual(keywords("press press printing the the the gutenberg", 2), ["press", "gutenberg"])

    def test_paragraphs_and_sentences(self):
        self.assertEqual(normalize_paragraphs("a  b\r\n\r\n\r\n c​ d "), "a b\n\nc d")
        self.assertEqual(sentences("One. Two? Three!\n\nFour."), ["One.", "Two?", "Three!", "Four."])

    def test_hash_ignores_whitespace_and_case(self):
        self.assertEqual(content_hash("Hello  World"), content_hash("hello world\n"))

    @unittest.skipUnless(RUST_BIN.is_file(), "build rust/querybook-core with `cargo build --release` to run parity")
    def test_rust_binary_parity(self):
        rows = list(golden_rows())
        proc = subprocess.run([str(RUST_BIN), "kernel"], input="\n".join(r[0] for r in rows) + "\n",
                              capture_output=True, text=True, check=True)
        self.assertEqual(proc.stdout.splitlines(), ["\t".join(r[1:]) for r in rows])

    @unittest.skipUnless(shutil.which("cargo"), "cargo not installed")
    def test_lexicons_are_shared_with_rust(self):
        src = (ROOT / "rust" / "querybook-core" / "src" / "text.rs").read_text()
        self.assertIn('include_str!("../../../querybook/core/lexicons.txt")', src)


if __name__ == "__main__":
    unittest.main()
