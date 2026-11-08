import tempfile
import unittest
from pathlib import Path

from querybook.config import SETTINGS_FILE, load_settings, paths, windows_default
from querybook.ingest import FolderSource


class ConfigTest(unittest.TestCase):
    def write(self, text):
        d = Path(tempfile.mkdtemp())
        (d / "querybook.ini").write_text(text, encoding="utf-8-sig")
        return d / "querybook.ini"

    def test_shipped_settings_keep_querybook_out_of_the_existing_store(self):
        st = load_settings(SETTINGS_FILE, windows=True)
        self.assertEqual(str(st.data_folder).replace("/", "\\"), "D:\\QueryBook")
        self.assertEqual(st.watch_folders, ())  # D:\\qb is far too large to re-scan; it needs a connector

    def test_windows_default_prefers_d_drive(self):
        self.assertEqual(str(windows_default(lambda p: p == "D:\\")).replace("/", "\\"), "D:\\QueryBook")
        self.assertNotIn("D:", str(windows_default(lambda p: False)))

    def test_watch_folders_parse_lines_and_semicolons(self):
        ini = self.write('[querybook]\ndata_folder = "D:\\QB"\nwatch_folders =\n    D:\\Data\n    E:\\More; D:\\Third\n'
                         "watch_interval_seconds = 30\n")
        st = load_settings(ini, windows=True)
        self.assertEqual(len(st.watch_folders), 3)
        self.assertEqual(st.watch_interval, 30.0)
        self.assertTrue(str(st.data_folder).startswith("D:"))

    def test_drive_paths_ignored_off_windows(self):
        ini = self.write("[querybook]\ndata_folder = D:\\QB\nwatch_folders = D:\\Data; /Users/me/notes\n")
        st = load_settings(ini, windows=False)
        self.assertIsNone(st.data_folder)
        self.assertEqual([str(p) for p in st.watch_folders], ["/Users/me/notes"])

    def test_watch_folder_is_read_without_modification(self):
        store = Path(tempfile.mkdtemp())
        (store / "history").mkdir()
        f = store / "history" / "note.txt"
        f.write_text("Hastings\nThe battle was fought in 1066.")
        before = f.stat().st_mtime_ns
        items = FolderSource(store, settle_seconds=0).poll()
        self.assertEqual((items[0].title, items[0].domain), ("Hastings", "history"))
        self.assertEqual(f.stat().st_mtime_ns, before)
        self.assertEqual(sorted(p.name for p in store.rglob("*")), ["history", "note.txt"])

    def test_watching_the_data_folder_skips_querybooks_own_files(self):
        home = Path(tempfile.mkdtemp())
        (home / "renders" / "job-1").mkdir(parents=True)
        (home / "renders" / "job-1" / "scene0.txt").write_text("Title card\nnot a document")
        (home / "inbox" / "history").mkdir(parents=True)
        (home / "inbox" / "history" / "dropped.txt").write_text("Dropped\nhandled by the inbox source")
        (home / "existing.md").write_text("# Existing note\nAlready on D: before QueryBook.")
        src = FolderSource(home, settle_seconds=0, exclude=(home / "inbox", home / "renders"))
        self.assertEqual([i.title for i in src.poll()], ["Existing note"])

    def test_explicit_home_wins(self):
        home = Path(tempfile.mkdtemp()) / "qb"
        self.assertEqual(paths(home).home, home)


if __name__ == "__main__":
    unittest.main()
