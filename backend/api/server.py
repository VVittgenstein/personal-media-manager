from __future__ import annotations

import argparse
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.indexing.media_index import MediaIndex, build_media_index
from backend.indexing.media_types import MediaTypes, load_media_types
from backend.security.fileops import FileOpsError, FileOpsService
from backend.security.operation_log import OperationLogStore

logger = logging.getLogger(__name__)


class _IndexCache:
    def __init__(
        self,
        *,
        media_root: Path,
        media_types: MediaTypes,
        include_trash: bool,
    ) -> None:
        self._media_root = media_root
        self._media_types = media_types
        self._include_trash = include_trash
        self._lock = threading.Lock()
        self._index: MediaIndex | None = None

    @property
    def media_root(self) -> Path:
        return self._media_root

    def get(self, *, refresh: bool) -> MediaIndex:
        if not refresh and self._index is not None:
            return self._index

        with self._lock:
            if not refresh and self._index is not None:
                return self._index
            self._index = build_media_index(
                self._media_root,
                media_types=self._media_types,
                include_trash=self._include_trash,
            )
            return self._index


class _MediaApiServer(ThreadingHTTPServer):
    index_cache: _IndexCache
    fileops: FileOpsService


class _Handler(BaseHTTPRequestHandler):
    server: _MediaApiServer

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        refresh = query.get("refresh", ["0"])[0] in {"1", "true", "True", "yes"}

        try:
            index = self.server.index_cache.get(refresh=refresh)
        except Exception as exc:
            logger.exception("failed to build index: %s", exc)
            self._send_error(500, "INDEX_BUILD_FAILED", str(exc))
            return

        if path == "/api/albums":
            self._send_json(
                200,
                {
                    "media_root": index.media_root,
                    "scanned_at_ms": index.scanned_at_ms,
                    "items": [a.as_dict() for a in index.albums],
                },
            )
            return

        if path == "/api/scattered":
            self._send_json(
                200,
                {
                    "media_root": index.media_root,
                    "scanned_at_ms": index.scanned_at_ms,
                    "items": [i.as_dict() for i in index.scattered_images],
                },
            )
            return

        if path == "/api/videos":
            self._send_json(
                200,
                {
                    "media_root": index.media_root,
                    "scanned_at_ms": index.scanned_at_ms,
                    "items": [v.as_dict() for v in index.videos],
                },
            )
            return

        if path == "/api/others":
            self._send_json(
                200,
                {
                    "media_root": index.media_root,
                    "scanned_at_ms": index.scanned_at_ms,
                    "games": [g.as_dict() for g in index.games],
                    "others": [o.as_dict() for o in index.others],
                },
            )
            return

        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return

        self._send_error(404, "NOT_FOUND", f"unknown endpoint: {path}")

    def _read_json_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError:
            raise FileOpsError("INVALID_CONTENT_LENGTH", "invalid Content-Length header")

        if length <= 0:
            return {}

        raw = self.rfile.read(length)
        if not raw:
            return {}

        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise FileOpsError("INVALID_JSON", f"invalid JSON body: {exc}")
        if not isinstance(data, dict):
            raise FileOpsError("INVALID_JSON", "JSON body must be an object")
        return data

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path not in {"/api/delete", "/api/move"}:
            self._send_error(404, "NOT_FOUND", f"unknown endpoint: {path}")
            return

        try:
            body = self._read_json_body()
        except FileOpsError as exc:
            self._send_error(exc.http_status, exc.code, exc.message)
            return

        try:
            if path == "/api/delete":
                result = self.server.fileops.delete(body)
            else:
                result = self.server.fileops.move(body)
        except FileOpsError as exc:
            self._send_error(exc.http_status, exc.code, exc.message)
            return
        except Exception as exc:
            logger.exception("file operation failed: %s", exc)
            self._send_error(500, "FILEOPS_FAILED", str(exc))
            return

        self._send_json(result.http_status, result.payload)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def run_server(
    *,
    media_root: str | Path,
    host: str,
    port: int,
    include_trash: bool,
    media_types_config: str | Path | None,
    warm_index: bool,
    operation_log_path: str | Path | None,
) -> None:
    media_types = load_media_types(media_types_config)
    cache = _IndexCache(
        media_root=Path(media_root),
        media_types=media_types,
        include_trash=include_trash,
    )

    if warm_index:
        cache.get(refresh=True)

    server: _MediaApiServer = _MediaApiServer((host, port), _Handler)
    server.index_cache = cache
    default_log_path = Path(__file__).resolve().parents[1] / "data" / "operation-log.jsonl"
    log_store = OperationLogStore(path=operation_log_path or default_log_path)
    server.fileops = FileOpsService(
        media_root=cache.media_root,
        log_store=log_store,
        confirm_secret=secrets.token_bytes(32),
    )
    logger.info("serving on http://%s:%s (MediaRoot=%s)", host, port, cache.media_root)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local media API server (MVP).")
    parser.add_argument("--media-root", required=True, help="Absolute path to MediaRoot directory.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000).")
    parser.add_argument(
        "--include-trash",
        action="store_true",
        help="Include MediaRoot/_trash in scan (default: ignored).",
    )
    parser.add_argument(
        "--media-types-config",
        default=None,
        help="Path to media-types.json (default: ./config/media-types.json if exists).",
    )
    parser.add_argument(
        "--no-warm-index",
        action="store_true",
        help="Do not build index on startup (default: warm index).",
    )
    parser.add_argument(
        "--operation-log",
        default=None,
        help="Path to operation log JSONL (default: backend/data/operation-log.jsonl).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    run_server(
        media_root=args.media_root,
        host=args.host,
        port=args.port,
        include_trash=args.include_trash,
        media_types_config=args.media_types_config,
        warm_index=not args.no_warm_index,
        operation_log_path=args.operation_log,
    )
    return 0
