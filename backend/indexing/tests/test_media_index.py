import tempfile
import unittest
from pathlib import Path

from backend.indexing.media_index import build_media_index


class TestMediaIndex(unittest.TestCase):
    def test_classify_albums_scattered_videos_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "travel" / "beach").mkdir(parents=True)
            (root / "travel" / "food").mkdir(parents=True)
            (root / "temp" / "raw").mkdir(parents=True)
            (root / "_trash").mkdir(parents=True)

            (root / "travel" / "beach" / "1.jpg").write_bytes(b"")
            (root / "travel" / "beach" / "2.png").write_bytes(b"")
            (root / "travel" / "beach" / "v.mp4").write_bytes(b"123")
            (root / "travel" / "food" / "a.jpg").write_bytes(b"")
            (root / "travel" / "preview.png").write_bytes(b"")

            (root / "temp" / "x.jpg").write_bytes(b"")
            (root / "temp" / "raw" / "note.txt").write_text("hi", encoding="utf-8")

            (root / "loose.jpg").write_bytes(b"")
            (root / "video.mp4").write_bytes(b"123")
            (root / "game.exe").write_bytes(b"")
            (root / "doc.txt").write_text("doc", encoding="utf-8")

            (root / "_trash" / "trashed.jpg").write_bytes(b"")
            (root / "_trash" / "trashed.mp4").write_bytes(b"123")

            index = build_media_index(root)

            self.assertEqual(
                [a.rel_path for a in index.albums],
                ["temp", "travel/beach", "travel/food"],
            )
            album_by_rel = {a.rel_path: a for a in index.albums}
            self.assertEqual(album_by_rel["travel/beach"].image_count, 2)
            self.assertEqual(album_by_rel["travel/food"].image_count, 1)
            self.assertEqual(album_by_rel["temp"].image_count, 1)

            self.assertEqual(
                {i.rel_path for i in index.scattered_images},
                {"loose.jpg", "travel/preview.png"},
            )
            self.assertEqual(
                {v.rel_path for v in index.videos},
                {"travel/beach/v.mp4", "video.mp4"},
            )
            self.assertEqual({g.rel_path for g in index.games}, {"game.exe"})
            self.assertEqual(
                {o.rel_path for o in index.others},
                {"doc.txt", "temp/raw/note.txt"},
            )

            all_returned = (
                {i.rel_path for i in index.scattered_images}
                | {v.rel_path for v in index.videos}
                | {g.rel_path for g in index.games}
                | {o.rel_path for o in index.others}
            )
            self.assertNotIn("_trash/trashed.jpg", all_returned)
            self.assertNotIn("_trash/trashed.mp4", all_returned)


if __name__ == "__main__":
    unittest.main()

