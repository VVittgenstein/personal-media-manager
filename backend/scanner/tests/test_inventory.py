import os
import tempfile
import unittest
from pathlib import Path

from backend.scanner.inventory import scan_inventory
from backend.scanner.sandbox import MediaRootSandbox, SandboxViolation, normalize_rel_path


class TestInventoryScanner(unittest.TestCase):
    def test_scan_basic_and_skip_trash_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "a").mkdir(parents=True)
            (root / "a" / "b.txt").write_text("hi", encoding="utf-8")
            (root / "c.jpg").write_bytes(b"")
            (root / "_trash").mkdir(parents=True)
            (root / "_trash" / "trashed.mp4").write_bytes(b"123")

            result = scan_inventory(root)
            by_rel = {item.rel_path: item for item in result.items}

            self.assertIn("", by_rel)
            self.assertEqual(by_rel[""].kind, "dir")
            self.assertIn("a", by_rel)
            self.assertEqual(by_rel["a"].kind, "dir")
            self.assertIn("a/b.txt", by_rel)
            self.assertEqual(by_rel["a/b.txt"].kind, "file")
            self.assertEqual(by_rel["a/b.txt"].size_bytes, 2)
            self.assertIn("c.jpg", by_rel)
            self.assertEqual(by_rel["c.jpg"].size_bytes, 0)

            self.assertNotIn("_trash", by_rel)
            self.assertNotIn("_trash/trashed.mp4", by_rel)

    def test_scan_can_include_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "_trash").mkdir(parents=True)
            (root / "_trash" / "trashed.mp4").write_bytes(b"123")

            result = scan_inventory(root, skip_trash=False)
            rels = {item.rel_path for item in result.items}
            self.assertIn("_trash", rels)
            self.assertIn("_trash/trashed.mp4", rels)

    def test_symlink_dir_is_not_traversed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "MediaRoot"
            outside = base / "Outside"
            root.mkdir()
            outside.mkdir()
            (outside / "outside.txt").write_text("nope", encoding="utf-8")

            link = root / "link_out"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported in this environment")

            result = scan_inventory(root)
            rels = {item.rel_path for item in result.items}
            self.assertNotIn("link_out/outside.txt", rels)
            self.assertTrue(any(w.rel_path == "link_out" for w in result.warnings))
            self.assertGreaterEqual(result.stats.get("skipped_links", 0), 1)


class TestSandbox(unittest.TestCase):
    def test_normalize_rel_path(self) -> None:
        self.assertEqual(normalize_rel_path("a\\b"), "a/b")
        self.assertEqual(normalize_rel_path("."), "")

        with self.assertRaises(SandboxViolation):
            normalize_rel_path("../a")
        with self.assertRaises(SandboxViolation):
            normalize_rel_path("/a")
        with self.assertRaises(SandboxViolation):
            normalize_rel_path("C:\\a")

    def test_reject_symlink_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "MediaRoot"
            outside = base / "Outside"
            root.mkdir()
            outside.mkdir()

            link = root / "sym"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported in this environment")

            sandbox = MediaRootSandbox(root)
            with self.assertRaises(SandboxViolation):
                sandbox.to_abs_path("sym/file.txt")

    def test_to_abs_path_allow_missing_accepts_new_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir()

            sandbox = MediaRootSandbox(root)
            abs_path = sandbox.to_abs_path_allow_missing("newdir/file.txt")
            self.assertEqual(abs_path, root / "newdir" / "file.txt")

    def test_to_abs_path_allow_missing_rejects_existing_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "MediaRoot"
            outside = base / "Outside"
            root.mkdir()
            outside.mkdir()

            link = root / "sym"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported in this environment")

            sandbox = MediaRootSandbox(root)
            with self.assertRaises(SandboxViolation):
                sandbox.to_abs_path_allow_missing("sym/newdir")


if __name__ == "__main__":
    unittest.main()
