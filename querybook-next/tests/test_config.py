import tempfile
import unittest
from pathlib import Path

from querybook.config import DATA_FOLDER_FILE, DataFolderMissing, read_data_folder_file, resolve


class DataFolderTest(unittest.TestCase):
    def tmp(self):
        return Path(tempfile.mkdtemp())

    def test_shipped_data_folder_is_d_qb(self):
        self.assertEqual(read_data_folder_file(DATA_FOLDER_FILE), "D:\\QB")

    def test_layout_follows_the_suite(self):
        folder = self.tmp()
        p = resolve(folder)
        self.assertEqual(p.commons, folder / "commons")
        self.assertEqual(p.shards, folder / "commons" / "shards")
        self.assertEqual(p.home, folder / "querybook-next")
        (folder / "commons.sqlite").write_bytes(b"")
        self.assertEqual(resolve(folder).commons, folder)  # shared facts kept directly in the folder

    def test_missing_drive_refuses_to_start(self):
        with self.assertRaises(DataFolderMissing):
            resolve(self.tmp() / "not-connected")

    def test_data_folder_file_is_read_and_drive_paths_ignored_off_windows(self):
        d = self.tmp()
        f = d / "data-folder.txt"
        f.write_text("\ufeff# comment\nD:\\QB\n", encoding="utf-8")
        self.assertEqual(read_data_folder_file(f), "D:\\QB")
        self.assertEqual(resolve(data_file=f, windows=False).folder, Path.home() / "QueryBook-Data")
        with self.assertRaises(DataFolderMissing):  # on Windows without a D: drive: refuse, never split the data
            resolve(data_file=f, windows=True)


if __name__ == "__main__":
    unittest.main()
