import tempfile
import unittest
from pathlib import Path

from backend.indexing.media_index import build_media_index
from backend.indexing.search import search_media_index


class TestSearchIndex(unittest.TestCase):
    def test_search_media_index_matches_across_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "AlbumOne").mkdir(parents=True)
            (root / "AlbumOne" / "1.jpg").write_bytes(b"")
            (root / "loose-image.png").write_bytes(b"")
            (root / "video-sample.mp4").write_bytes(b"123")
            (root / "game.exe").write_bytes(b"")
            (root / "doc.txt").write_text("hi", encoding="utf-8")

            index = build_media_index(root)

            albums = search_media_index(index, "albumone", types={"album"})
            self.assertEqual([hit["rel_path"] for hit in albums], ["AlbumOne"])

            videos = search_media_index(index, "video sample", types={"video"})
            self.assertEqual([hit["rel_path"] for hit in videos], ["video-sample.mp4"])

            images = search_media_index(index, "1.jpg", types={"image"})
            self.assertEqual([hit["rel_path"] for hit in images], ["AlbumOne/1.jpg"])
            self.assertEqual(images[0]["album_rel_path"], "AlbumOne")

            mixed = search_media_index(index, "loose", limit=10)
            self.assertTrue(any(hit["kind"] == "image" for hit in mixed))

    def test_search_media_index_returns_empty_on_blank_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir(parents=True)
            index = build_media_index(root)
            self.assertEqual(search_media_index(index, "   "), [])


if __name__ == "__main__":
    unittest.main()
