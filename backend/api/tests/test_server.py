import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from backend.api.server import _Handler, _IndexCache, _MediaApiServer
from backend.indexing.media_types import MediaTypes


class TestApiServer(unittest.TestCase):
    def test_endpoints_return_expected_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "album").mkdir(parents=True)
            (root / "album" / "1.jpg").write_bytes(b"")
            (root / "loose.jpg").write_bytes(b"")
            (root / "v.mp4").write_bytes(b"123")

            cache = _IndexCache(
                media_root=root,
                media_types=MediaTypes.defaults(),
                include_trash=False,
            )

            server: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
            server.index_cache = cache

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=2)

            try:
                conn.request("GET", "/api/albums")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                albums = json.loads(resp.read().decode("utf-8"))
                self.assertIn("items", albums)

                conn.request("GET", "/api/scattered")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                scattered = json.loads(resp.read().decode("utf-8"))
                self.assertIn("items", scattered)

                conn.request("GET", "/api/videos")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                videos = json.loads(resp.read().decode("utf-8"))
                self.assertIn("items", videos)

                conn.request("GET", "/api/others")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                others = json.loads(resp.read().decode("utf-8"))
                self.assertIn("games", others)
                self.assertIn("others", others)
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

