import json
import tempfile
import threading
import unittest
from base64 import b64decode
from http.client import HTTPConnection
from pathlib import Path

from backend.api.server import _Handler, _IndexCache, _MediaApiServer
from backend.indexing.media_types import MediaTypes
from backend.security.fileops import FileOpsService
from backend.security.operation_log import OperationLogStore
from backend.thumbnails.image_thumbs import ThumbnailService


class TestApiServer(unittest.TestCase):
    def _post_json(self, conn: HTTPConnection, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        conn.request(
            "POST",
            path,
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        return resp.status, data

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
            server.fileops = FileOpsService(
                media_root=root,
                log_store=OperationLogStore(path=Path(tmp) / "oplog.jsonl"),
                confirm_secret=b"test-secret",
            )

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

    def test_fileops_delete_and_move_require_confirm_and_write_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "MediaRoot"
            root.mkdir(parents=True)
            (root / "a.txt").write_text("hello", encoding="utf-8")

            cache = _IndexCache(
                media_root=root,
                media_types=MediaTypes.defaults(),
                include_trash=False,
            )

            log_path = tmp_path / "operation-log.jsonl"
            server: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
            server.index_cache = cache
            server.fileops = FileOpsService(
                media_root=root,
                log_store=OperationLogStore(path=log_path),
                confirm_secret=b"test-secret",
            )

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=2)

            try:
                status, preview = self._post_json(conn, "/api/move", {})
                self.assertEqual(status, 400)
                self.assertIn("error", preview)

                status, preview = self._post_json(
                    conn,
                    "/api/move",
                    {"src": "a.txt", "dst": "moved/a.txt", "create_parents": True},
                )
                self.assertEqual(status, 200)
                self.assertTrue(preview.get("confirm_required"))
                token = preview.get("confirm_token")
                self.assertIsInstance(token, str)

                status, moved = self._post_json(
                    conn,
                    "/api/move",
                    {
                        "src": "a.txt",
                        "dst": "moved/a.txt",
                        "create_parents": True,
                        "confirm": True,
                        "confirm_token": token,
                    },
                )
                self.assertEqual(status, 200)
                self.assertTrue(moved.get("executed"))
                self.assertTrue((root / "moved" / "a.txt").exists())

                status, del_preview = self._post_json(
                    conn,
                    "/api/delete",
                    {"path": "moved/a.txt"},
                )
                self.assertEqual(status, 200)
                del_token = del_preview.get("confirm_token")
                self.assertIsInstance(del_token, str)

                status, deleted = self._post_json(
                    conn,
                    "/api/delete",
                    {"path": "moved/a.txt", "confirm": True, "confirm_token": del_token},
                )
                self.assertEqual(status, 200)
                self.assertTrue(deleted.get("executed"))
                self.assertFalse((root / "moved" / "a.txt").exists())

                lines = log_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertGreaterEqual(len(lines), 2)
                last = json.loads(lines[-1])
                self.assertEqual(last.get("op"), "delete")
                self.assertTrue(last.get("success"))
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_thumbnail_endpoint_generates_and_uses_etag(self) -> None:
        try:
            import PIL  # noqa: F401
        except ModuleNotFoundError:
            pillow_available = False
        else:
            pillow_available = True

        png_1x1 = b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQI12P4//8/AwAI/AL+X9aZVwAAAABJRU5ErkJggg=="
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir(parents=True)
            (root / "loose.png").write_bytes(png_1x1)

            cache = _IndexCache(
                media_root=root,
                media_types=MediaTypes.defaults(),
                include_trash=False,
            )

            server: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
            server.index_cache = cache
            server.fileops = FileOpsService(
                media_root=root,
                log_store=OperationLogStore(path=Path(tmp) / "oplog.jsonl"),
                confirm_secret=b"test-secret",
            )
            server.thumbs = ThumbnailService(
                media_root=root,
                media_types=MediaTypes.defaults(),
                cache_dir=Path(tmp) / "thumb-cache",
                thumb_size=64,
                thumb_quality=80,
                workers=1,
            )

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            try:
                conn.request("GET", "/api/thumb?path=loose.png")
                resp = conn.getresponse()
                body = resp.read()
                if pillow_available:
                    self.assertEqual(resp.status, 200)
                    self.assertTrue(body.startswith(b"\xff\xd8"))
                    etag = resp.headers.get("ETag")
                    self.assertIsInstance(etag, str)

                    conn.request("GET", "/api/thumb?path=loose.png", headers={"If-None-Match": etag})
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 304)
                else:
                    self.assertEqual(resp.status, 503)
                    data = json.loads(body.decode("utf-8"))
                    self.assertEqual(data.get("error", {}).get("code"), "PILLOW_NOT_INSTALLED")

                status, warm = self._post_json(conn, "/api/thumbs/warm", {"paths": ["loose.png"]})
                self.assertEqual(status, 202)
                self.assertTrue(warm.get("ok"))
                self.assertIn("accepted", warm)
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
