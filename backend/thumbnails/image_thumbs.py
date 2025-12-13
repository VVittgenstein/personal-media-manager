from __future__ import annotations

import hashlib
import logging
import os
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.indexing.media_types import MediaTypes
from backend.scanner.sandbox import MediaRootSandbox, SandboxViolation, normalize_rel_path

logger = logging.getLogger(__name__)

ThumbKeyMode = Literal["mtime", "sha1"]


class ThumbError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class ThumbResult:
    cache_path: Path
    etag: str
    content_type: str
    source_mtime_ms: int | None


def _mtime_ms_from_stat(st: os.stat_result) -> int | None:
    try:
        return int(st.st_mtime * 1000)
    except Exception:
        return None


def _sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def default_thumb_cache_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "personal-pron-media-manager" / "cache" / "thumbs"

    root = os.environ.get("XDG_CACHE_HOME")
    if root:
        return Path(root) / "personal-pron-media-manager" / "thumbs"
    return Path.home() / ".cache" / "personal-pron-media-manager" / "thumbs"


class ThumbnailService:
    def __init__(
        self,
        *,
        media_root: Path,
        media_types: MediaTypes,
        cache_dir: Path | None = None,
        thumb_size: int = 320,
        thumb_quality: int = 82,
        key_mode: ThumbKeyMode = "mtime",
        workers: int = 2,
        queue_size: int = 2048,
    ) -> None:
        if thumb_size <= 0:
            raise ValueError("thumb_size must be > 0")
        if not (1 <= thumb_quality <= 95):
            raise ValueError("thumb_quality must be between 1 and 95")
        if workers <= 0:
            raise ValueError("workers must be > 0")
        if queue_size <= 0:
            raise ValueError("queue_size must be > 0")

        self._sandbox = MediaRootSandbox(media_root)
        self._media_types = media_types
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_thumb_cache_dir()
        self._thumb_size = int(thumb_size)
        self._thumb_quality = int(thumb_quality)
        self._key_mode: ThumbKeyMode = key_mode

        self._gen_sema = threading.Semaphore(workers)
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=queue_size)
        self._queued: set[str] = set()
        self._queued_lock = threading.Lock()
        self._stop = threading.Event()

        self._key_locks_lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

        self._threads: list[threading.Thread] = []
        for i in range(workers):
            t = threading.Thread(target=self._worker, name=f"thumb-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def close(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for _ in self._threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break
        for t in self._threads:
            t.join(timeout=2)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                self._queue.task_done()
                break

            try:
                self.ensure_thumb(item)
            except ThumbError as exc:
                logger.debug("thumbnail generation skipped/failed: %s (%s)", exc.code, exc.message)
            except Exception as exc:
                logger.exception("thumbnail generation crashed: %s", exc)
            finally:
                with self._queued_lock:
                    self._queued.discard(item)
                self._queue.task_done()

    def _key_lock(self, key: str) -> threading.Lock:
        with self._key_locks_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._key_locks[key] = lock
            return lock

    def _validate_rel_path(self, rel_path: str) -> str:
        try:
            return normalize_rel_path(rel_path)
        except SandboxViolation as exc:
            raise ThumbError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

    def _resolve_abs_image(self, rel_path: str) -> tuple[str, Path, os.stat_result]:
        rel_path = self._validate_rel_path(rel_path)
        if rel_path == "":
            raise ThumbError("INVALID_PATH", "path must not be MediaRoot root", http_status=400)

        ext = os.path.splitext(rel_path)[1].lower()
        if self._media_types.categorize_ext(ext) != "image":
            raise ThumbError("UNSUPPORTED_MEDIA_TYPE", f"not an image: {rel_path}", http_status=415)

        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise ThumbError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        try:
            st = os.stat(abs_path, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise ThumbError("NOT_FOUND", f"file not found: {rel_path}", http_status=404) from exc
        except OSError as exc:
            raise ThumbError("STAT_FAILED", f"cannot stat file: {exc}", http_status=404) from exc

        if not abs_path.is_file():
            raise ThumbError("NOT_A_FILE", f"not a file: {rel_path}", http_status=404)

        return rel_path, abs_path, st

    def _etag_and_cache_path(self, *, rel_path: str, abs_path: Path, st: os.stat_result) -> tuple[str, Path]:
        version = "v1"
        fmt = "jpeg"
        spec = f"{version}|{fmt}|s={self._thumb_size}|q={self._thumb_quality}"
        if self._key_mode == "sha1":
            src_id = _sha1_file(abs_path)
            key_src = f"{spec}|sha1|{src_id}".encode("utf-8")
        else:
            key_src = f"{spec}|mtime|{rel_path}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")

        etag = hashlib.sha1(key_src).hexdigest()
        cache_path = self._cache_dir / etag[:2] / etag[2:4] / f"{etag}.jpg"
        return etag, cache_path

    def get_cached(self, rel_path: str) -> ThumbResult | None:
        rel_path, abs_path, st = self._resolve_abs_image(rel_path)
        etag, cache_path = self._etag_and_cache_path(rel_path=rel_path, abs_path=abs_path, st=st)
        if cache_path.exists():
            return ThumbResult(
                cache_path=cache_path,
                etag=etag,
                content_type="image/jpeg",
                source_mtime_ms=_mtime_ms_from_stat(st),
            )
        return None

    def enqueue(self, rel_path: str) -> bool:
        rel_path = self._validate_rel_path(rel_path)
        with self._queued_lock:
            if rel_path in self._queued:
                return True
            try:
                self._queue.put_nowait(rel_path)
            except queue.Full:
                return False
            self._queued.add(rel_path)
            return True

    def enqueue_many(self, rel_paths: list[str]) -> dict[str, int]:
        accepted = 0
        skipped_cached = 0
        rejected = 0
        for raw in rel_paths:
            if not isinstance(raw, str):
                rejected += 1
                continue
            normalized = raw.strip()
            if not normalized:
                rejected += 1
                continue
            try:
                if self.get_cached(normalized) is not None:
                    skipped_cached += 1
                    continue
            except ThumbError:
                rejected += 1
                continue
            if self.enqueue(normalized):
                accepted += 1
            else:
                rejected += 1
        return {"accepted": accepted, "skipped_cached": skipped_cached, "rejected": rejected}

    def ensure_thumb(self, rel_path: str) -> ThumbResult:
        rel_path, abs_path, st = self._resolve_abs_image(rel_path)
        etag, cache_path = self._etag_and_cache_path(rel_path=rel_path, abs_path=abs_path, st=st)

        lock = self._key_lock(etag)
        with lock:
            if cache_path.exists():
                return ThumbResult(
                    cache_path=cache_path,
                    etag=etag,
                    content_type="image/jpeg",
                    source_mtime_ms=_mtime_ms_from_stat(st),
                )
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            acquired = self._gen_sema.acquire(timeout=30)
            if not acquired:
                raise ThumbError("THUMB_RATE_LIMITED", "thumbnail generation is busy; retry later", http_status=429)
            try:
                self._render_to_jpeg(abs_path=abs_path, out_path=cache_path)
            finally:
                self._gen_sema.release()

        return ThumbResult(
            cache_path=cache_path,
            etag=etag,
            content_type="image/jpeg",
            source_mtime_ms=_mtime_ms_from_stat(st),
        )

    def _render_to_jpeg(self, *, abs_path: Path, out_path: Path) -> None:
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        except ModuleNotFoundError as exc:
            raise ThumbError(
                "PILLOW_NOT_INSTALLED",
                "Pillow is required for thumbnail generation (pip install pillow).",
                http_status=503,
            ) from exc

        try:
            with Image.open(abs_path) as im:
                im = ImageOps.exif_transpose(im)
                if getattr(im, "is_animated", False):
                    try:
                        im.seek(0)
                    except EOFError:
                        pass
                im = im.convert("RGB")

                size = self._thumb_size
                bg_scale = max(size / im.width, size / im.height)
                bg_w = max(1, int(im.width * bg_scale))
                bg_h = max(1, int(im.height * bg_scale))
                bg = im.resize((bg_w, bg_h), resample=Image.Resampling.LANCZOS)
                left = max(0, (bg.width - size) // 2)
                top = max(0, (bg.height - size) // 2)
                bg = bg.crop((left, top, left + size, top + size))
                bg = bg.filter(ImageFilter.GaussianBlur(radius=max(2.0, size / 18)))
                bg = ImageEnhance.Brightness(bg).enhance(0.92)

                fg_scale = min(size / im.width, size / im.height)
                fg_w = max(1, int(im.width * fg_scale))
                fg_h = max(1, int(im.height * fg_scale))
                fg = im.resize((fg_w, fg_h), resample=Image.Resampling.LANCZOS)
                x = (size - fg.width) // 2
                y = (size - fg.height) // 2
                bg.paste(fg, (x, y))

                tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
                bg.save(
                    tmp_path,
                    format="JPEG",
                    quality=self._thumb_quality,
                    optimize=True,
                    progressive=True,
                )
                os.replace(tmp_path, out_path)
        except ThumbError:
            raise
        except Exception as exc:
            raise ThumbError("THUMBNAIL_FAILED", f"failed to generate thumbnail: {exc}", http_status=500) from exc

