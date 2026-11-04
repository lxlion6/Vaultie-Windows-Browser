"""Local-only storage management tests. No browser or internet needed."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage_manager as sm


class StorageManagerTests(unittest.TestCase):
    def test_limits_use_decimal_gigabytes(self):
        self.assertEqual(sm.CLEAN_AT, 3_800_000_000)
        self.assertEqual(sm.HARD_LIMIT, 5_000_000_000)

    def test_cleanup_preserves_user_files_and_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Downloads").mkdir()
            (root / "Downloads" / "private.pdf").write_bytes(b"important")
            (root / "bookmarks.json").write_bytes(b"bookmarks")
            (root / "settings.json").write_bytes(b"settings")
            (root / "filterliste.txt").write_bytes(b"filters")
            (root / "session").mkdir()
            (root / "session" / "Cache").mkdir()
            (root / "session" / "Cache" / "asset.bin").write_bytes(b"x" * 400)
            (root / "cache").mkdir()
            (root / "cache" / "temporary.bin").write_bytes(b"y" * 200)
            budget = sm.StorageBudget(root)
            before, after, removed = budget.check(force=True)
            self.assertEqual(removed, 600)
            self.assertEqual(before - after, 600)
            self.assertTrue((root / "Downloads" / "private.pdf").exists())
            self.assertEqual((root / "bookmarks.json").read_bytes(), b"bookmarks")
            self.assertEqual((root / "settings.json").read_bytes(), b"settings")
            self.assertEqual((root / "filterliste.txt").read_bytes(), b"filters")

    def test_triggers_at_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = sm.StorageBudget(directory)
            with patch.object(budget, "size", return_value=sm.CLEAN_AT):
                with patch("storage_manager.clean_temporary", return_value=10) as cleanup:
                    budget.check()
                    cleanup.assert_called_once()

    def test_declines_download_above_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = sm.StorageBudget(directory)
            with patch.object(budget, "check", return_value=(sm.HARD_LIMIT - 100, sm.HARD_LIMIT - 100, 0)):
                self.assertFalse(budget.can_download(200))
                self.assertTrue(budget.can_download(100))
                self.assertTrue(budget.can_download(None))


if __name__ == "__main__":
    unittest.main()
