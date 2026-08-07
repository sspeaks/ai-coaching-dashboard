import importlib.util
import os
import shutil
import stat
import unittest
from pathlib import Path


SOURCE = Path(os.environ["RETENTION_HELPER_SOURCE"])
SPEC = importlib.util.spec_from_file_location("retention_helper", SOURCE)
assert SPEC and SPEC.loader
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class RetentionHelperTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "retention-helper-runtime"
        shutil.rmtree(self.root, ignore_errors=True)
        (self.root / "data" / "media" / "session").mkdir(parents=True)
        (self.root / "data" / "deletion-audit.log").write_text("", encoding="utf-8")
        self.outside = self.root / "outside"
        self.outside.mkdir()
        (self.outside / "keep.wav").write_text("keep\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rejects_traversal_and_stationary_symlinks(self):
        os.symlink(
            self.outside / "keep.wav",
            self.root / "data" / "media" / "escape.wav",
        )
        for target in ("../outside/keep.wav", "/etc/passwd", "escape.wav"):
            with self.assertRaises(HELPER.RetentionError):
                HELPER.quarantine(str(self.root / "data"), target)
        self.assertEqual((self.outside / "keep.wav").read_text(), "keep\n")

    def test_ancestor_replacement_cannot_redirect_rename(self):
        target = self.root / "data" / "media" / "session" / "delete.wav"
        target.write_text("delete\n", encoding="utf-8")

        def replace_ancestor(stage):
            self.assertEqual(stage, "before_rename")
            session = self.root / "data" / "media" / "session"
            moved = self.root / "data" / "media" / "session-opened"
            session.rename(moved)
            os.symlink(self.outside, session)

        destination = HELPER.quarantine(
            str(self.root / "data"),
            "session/delete.wav",
            hook=replace_ancestor,
        )
        self.assertFalse(
            (self.root / "data" / "media" / "session-opened" / "delete.wav").exists()
        )
        self.assertTrue(
            (self.root / "data" / "media" / destination).is_file()
        )
        self.assertEqual((self.outside / "keep.wav").read_text(), "keep\n")
        self.assertTrue(
            stat.S_ISLNK(
                os.lstat(self.root / "data" / "media" / "session").st_mode
            )
        )

    def test_purge_unlinks_injected_symlink_without_following_it(self):
        quarantine = self.root / "data" / "media" / ".quarantine" / "bucket"
        quarantine.mkdir(parents=True)
        os.symlink(self.outside, quarantine / "outside-link")
        HELPER.purge(str(self.root / "data"))
        self.assertEqual((self.outside / "keep.wav").read_text(), "keep\n")
        self.assertEqual(HELPER.list_quarantine(str(self.root / "data")), [])


if __name__ == "__main__":
    unittest.main()
