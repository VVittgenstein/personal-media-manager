import json
import os
import tempfile
import threading
import unittest
from base64 import b64decode
from http.client import HTTPConnection
from pathlib import Path

from backend.api.server import _Handler, _IndexCache, _MediaApiServer, _bind_http_server
from backend.indexing.media_types import MediaTypes
from backend.security.fileops import FileOpsService
from backend.security.operation_log import OperationLogStore
from backend.thumbnails.album_covers import AlbumCoverService
from backend.thumbnails.image_thumbs import ThumbnailService
from backend.thumbnails.video_mosaics import VideoMosaicService


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

    def test_bind_http_server_auto_skips_ports_in_use(self) -> None:
        occupied: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
        try:
            in_use_port = occupied.server_address[1]
            bound: _MediaApiServer = _bind_http_server(
                "127.0.0.1",
                in_use_port,
                conflict_mode="auto",
                search_limit=50,
            )
            try:
                self.assertNotEqual(bound.server_address[1], in_use_port)
            finally:
                bound.server_close()
        finally:
            occupied.server_close()

    def test_bind_http_server_fail_raises_when_port_in_use(self) -> None:
        occupied: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
        try:
            in_use_port = occupied.server_address[1]
            with self.assertRaises(OSError):
                _bind_http_server(
                    "127.0.0.1",
                    in_use_port,
                    conflict_mode="fail",
                    search_limit=1,
                )
        finally:
            occupied.server_close()

    def test_spa_shell_serves_index_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir(parents=True)

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
                conn.request("GET", "/")
                resp = conn.getresponse()
                body = resp.read().decode("utf-8", errors="replace")
                self.assertEqual(resp.status, 200)
                self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                self.assertIn("Personal Media Manager", body)

                conn.request("GET", "/images")
                resp = conn.getresponse()
                body = resp.read().decode("utf-8", errors="replace")
                self.assertEqual(resp.status, 200)
                self.assertIn("text/html", resp.headers.get("Content-Type", ""))
                self.assertIn("id=\"app\"", body)

                conn.request("GET", "/styles.css")
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 200)
                self.assertIn("text/css", resp.headers.get("Content-Type", ""))

                conn.request("GET", "/app.js")
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 200)
                self.assertTrue(
                    resp.headers.get("Content-Type", "").startswith(("text/javascript", "application/javascript"))
                )
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_album_images_lists_images_in_album(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            (root / "album").mkdir(parents=True)
            (root / "album" / "b.JPG").write_bytes(b"")
            (root / "album" / "a.png").write_bytes(b"")
            (root / "album" / "note.txt").write_bytes(b"hello")

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
                conn.request("GET", "/api/album-images?path=album")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["album_rel_path"], "album")
                self.assertEqual(data["count"], 2)
                self.assertEqual(data["items"], ["album/a.png", "album/b.JPG"])
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_album_images_missing_album_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir(parents=True)

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
                conn.request("GET", "/api/album-images?path=missing-album")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 404)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["error"]["code"], "NOT_FOUND")
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_album_images_rejects_symlinked_album_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "MediaRoot"
            root.mkdir(parents=True)
            outside = tmp_path / "Outside"
            outside.mkdir(parents=True)
            (outside / "a.jpg").write_bytes(b"")

            try:
                os.symlink(outside, root / "album", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks not supported: {exc}")

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
                conn.request("GET", "/api/album-images?path=album")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 400)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(data["error"]["code"], "SANDBOX_VIOLATION")
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_media_endpoint_serves_video_and_supports_range_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MediaRoot"
            root.mkdir(parents=True)
            (root / "v.mp4").write_bytes(b"0123456789")
            (root / "note.txt").write_text("hello", encoding="utf-8")

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
                conn.request("GET", "/api/media?path=v.mp4")
                resp = conn.getresponse()
                body = resp.read()
                self.assertEqual(resp.status, 200)
                self.assertEqual(body, b"0123456789")
                self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")

                conn.request("GET", "/api/media?path=v.mp4", headers={"Range": "bytes=2-5"})
                resp = conn.getresponse()
                body = resp.read()
                self.assertEqual(resp.status, 206)
                self.assertEqual(body, b"2345")
                self.assertEqual(resp.headers.get("Content-Range"), "bytes 2-5/10")

                conn.request("GET", "/api/media?path=v.mp4", headers={"Range": "bytes=999-"})
                resp = conn.getresponse()
                body = resp.read()
                self.assertEqual(resp.status, 416)
                self.assertEqual(body, b"")
                self.assertEqual(resp.headers.get("Content-Range"), "bytes */10")

                conn.request("GET", "/api/media?path=note.txt")
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(resp.status, 415)
                self.assertEqual(data["error"]["code"], "UNSUPPORTED_MEDIA_TYPE")
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

    def test_album_cover_endpoint_generates_uses_etag_and_invalidates_on_change(self) -> None:
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
            (root / "album").mkdir(parents=True)
            for name in ["a.png", "b.png", "c.png", "d.png"]:
                (root / "album" / name).write_bytes(png_1x1)

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
            server.album_covers = AlbumCoverService(
                media_root=root,
                media_types=MediaTypes.defaults(),
                cache_dir=Path(tmp) / "thumb-cache",
                cover_size=64,
                cover_quality=80,
            )

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            try:
                conn.request("GET", "/api/album-cover?path=album")
                resp = conn.getresponse()
                body = resp.read()
                if pillow_available:
                    self.assertEqual(resp.status, 200)
                    self.assertTrue(body.startswith(b"\xff\xd8"))
                    etag = resp.headers.get("ETag")
                    self.assertIsInstance(etag, str)

                    conn.request("GET", "/api/album-cover?path=album", headers={"If-None-Match": etag})
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 304)

                    (root / "album" / "e.png").write_bytes(png_1x1)
                    conn.request("GET", "/api/album-cover?path=album")
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 200)
                    etag_after = resp.headers.get("ETag")
                    self.assertIsInstance(etag_after, str)
                    self.assertNotEqual(etag_after, etag)
                else:
                    self.assertEqual(resp.status, 503)
                    data = json.loads(body.decode("utf-8"))
                    self.assertEqual(data.get("error", {}).get("code"), "PILLOW_NOT_INSTALLED")
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_video_mosaic_endpoint_uses_etag_and_invalidates_on_change(self) -> None:
        try:
            import PIL  # noqa: F401
        except ModuleNotFoundError:
            pillow_available = False
        else:
            pillow_available = True

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "MediaRoot"
            root.mkdir(parents=True)
            video_path = root / "v.mp4"
            video_path.write_bytes(b"not-a-real-video")

            bin_dir = tmp_path / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "ffprobe").write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.write('10.0\\n')\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            (bin_dir / "ffmpeg").write_text(
                "#!/usr/bin/env python3\n"
                "import base64\n"
                "import pathlib\n"
                "import sys\n"
                "png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQI12P4//8/AwAI/AL+X9aZVwAAAABJRU5ErkJggg==')\n"
                "out = pathlib.Path(sys.argv[-1])\n"
                "out.parent.mkdir(parents=True, exist_ok=True)\n"
                "out.write_bytes(png)\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            os.chmod(bin_dir / "ffprobe", 0o755)
            os.chmod(bin_dir / "ffmpeg", 0o755)

            orig_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(bin_dir) + os.pathsep + orig_path
            self.addCleanup(lambda: os.environ.__setitem__("PATH", orig_path))

            cache = _IndexCache(
                media_root=root,
                media_types=MediaTypes.defaults(),
                include_trash=False,
            )

            server: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
            server.index_cache = cache
            server.fileops = FileOpsService(
                media_root=root,
                log_store=OperationLogStore(path=tmp_path / "oplog.jsonl"),
                confirm_secret=b"test-secret",
            )
            server.video_mosaics = VideoMosaicService(
                media_root=root,
                media_types=MediaTypes.defaults(),
                cache_dir=tmp_path / "thumb-cache",
                mosaic_size=64,
                mosaic_quality=80,
                gen_workers=1,
            )

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            try:
                conn.request("GET", "/api/video-mosaic?path=v.mp4")
                resp = conn.getresponse()
                body = resp.read()
                if pillow_available:
                    self.assertEqual(resp.status, 200)
                    self.assertTrue(body.startswith(b"\xff\xd8"))
                    etag = resp.headers.get("ETag")
                    self.assertIsInstance(etag, str)

                    conn.request("GET", "/api/video-mosaic?path=v.mp4", headers={"If-None-Match": etag})
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 304)

                    video_path.write_bytes(b"changed")
                    conn.request("GET", "/api/video-mosaic?path=v.mp4")
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 200)
                    etag_after = resp.headers.get("ETag")
                    self.assertIsInstance(etag_after, str)
                    self.assertNotEqual(etag_after, etag)
                else:
                    self.assertEqual(resp.status, 503)
                    data = json.loads(body.decode("utf-8"))
                    self.assertEqual(data.get("error", {}).get("code"), "PILLOW_NOT_INSTALLED")
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)

    def test_video_mosaic_endpoint_serves_cached_without_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "MediaRoot"
            root.mkdir(parents=True)
            (root / "v.mp4").write_bytes(b"not-a-real-video")

            empty_bin = tmp_path / "bin"
            empty_bin.mkdir(parents=True)
            orig_path = os.environ.get("PATH", "")
            os.environ["PATH"] = str(empty_bin)
            self.addCleanup(lambda: os.environ.__setitem__("PATH", orig_path))

            cache = _IndexCache(
                media_root=root,
                media_types=MediaTypes.defaults(),
                include_trash=False,
            )

            server: _MediaApiServer = _MediaApiServer(("127.0.0.1", 0), _Handler)
            server.index_cache = cache
            server.fileops = FileOpsService(
                media_root=root,
                log_store=OperationLogStore(path=tmp_path / "oplog.jsonl"),
                confirm_secret=b"test-secret",
            )
            server.video_mosaics = VideoMosaicService(
                media_root=root,
                media_types=MediaTypes.defaults(),
                cache_dir=tmp_path / "thumb-cache",
                mosaic_size=64,
                mosaic_quality=80,
                gen_workers=1,
            )

            rel_path, abs_path, st = server.video_mosaics._resolve_abs_video("v.mp4")
            etag, cache_path = server.video_mosaics._etag_and_cache_path(
                rel_path=rel_path,
                abs_path=abs_path,
                st=st,
            )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"\xff\xd8\xff\xd9")

            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()

            host, port = server.server_address
            conn = HTTPConnection(host, port, timeout=5)

            try:
                conn.request("GET", "/api/video-mosaic?path=v.mp4")
                resp = conn.getresponse()
                body = resp.read()
                self.assertEqual(resp.status, 200)
                self.assertTrue(body.startswith(b"\xff\xd8"))
                self.assertEqual(resp.headers.get("ETag"), f"\"{etag}\"")

                conn.request("GET", "/api/video-mosaic?path=v.mp4", headers={"If-None-Match": f"\"{etag}\""})
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 304)
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                t.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
