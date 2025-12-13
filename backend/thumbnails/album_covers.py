from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.indexing.media_types import MediaTypes
from backend.scanner.sandbox import MediaRootSandbox, SandboxViolation, normalize_rel_path

from .image_thumbs import ThumbKeyMode

logger = logging.getLogger(__name__)


class AlbumCoverError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class AlbumCoverResult:
    cache_path: Path
    etag: str
    content_type: str
    source_mtime_ms: int | None
    cover_image_rel_paths: list[str]


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


class AlbumCoverService:
    def __init__(
        self,
        *,
        media_root: Path,
        media_types: MediaTypes,
        cache_dir: Path,
        cover_size: int,
        cover_quality: int,
        key_mode: ThumbKeyMode = "mtime",
    ) -> None:
        if cover_size <= 0:
            raise ValueError("cover_size must be > 0")
        if not (1 <= cover_quality <= 95):
            raise ValueError("cover_quality must be between 1 and 95")

        self._sandbox = MediaRootSandbox(media_root)
        self._media_types = media_types
        self._cache_dir = Path(cache_dir) / "album-covers"
        self._cover_size = int(cover_size)
        self._cover_quality = int(cover_quality)
        self._key_mode: ThumbKeyMode = key_mode

        self._key_locks_lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def close(self) -> None:
        return

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
            raise AlbumCoverError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

    def _resolve_abs_image(self, rel_path: str) -> tuple[str, Path, os.stat_result]:
        rel_path = self._validate_rel_path(rel_path)
        if rel_path == "":
            raise AlbumCoverError("INVALID_PATH", "path must not be MediaRoot root", http_status=400)

        ext = os.path.splitext(rel_path)[1].lower()
        if self._media_types.categorize_ext(ext) != "image":
            raise AlbumCoverError("UNSUPPORTED_MEDIA_TYPE", f"not an image: {rel_path}", http_status=415)

        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise AlbumCoverError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        try:
            st = os.stat(abs_path, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise AlbumCoverError("NOT_FOUND", f"file not found: {rel_path}", http_status=404) from exc
        except OSError as exc:
            raise AlbumCoverError("STAT_FAILED", f"cannot stat file: {exc}", http_status=404) from exc

        if not abs_path.is_file():
            raise AlbumCoverError("NOT_A_FILE", f"not a file: {rel_path}", http_status=404)

        return rel_path, abs_path, st

    def _resolve_abs_album_dir(self, album_rel_path: str) -> tuple[str, Path, os.stat_result]:
        album_rel_path = self._validate_rel_path(album_rel_path)
        try:
            abs_dir = self._sandbox.to_abs_path(album_rel_path)
        except SandboxViolation as exc:
            raise AlbumCoverError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        try:
            st = os.stat(abs_dir, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise AlbumCoverError("NOT_FOUND", f"album not found: {album_rel_path}", http_status=404) from exc
        except OSError as exc:
            raise AlbumCoverError("STAT_FAILED", f"cannot stat album: {exc}", http_status=404) from exc

        if not abs_dir.is_dir():
            raise AlbumCoverError("NOT_A_DIR", f"not a directory: {album_rel_path}", http_status=404)

        return album_rel_path, abs_dir, st

    def _list_album_images(self, *, album_rel_path: str, abs_dir: Path) -> list[str]:
        candidates: list[str] = []
        try:
            with os.scandir(abs_dir) as it:
                for entry in it:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(entry.name)[1].lower()
                    if self._media_types.categorize_ext(ext) != "image":
                        continue
                    if album_rel_path:
                        rel = f"{album_rel_path}/{entry.name}"
                    else:
                        rel = entry.name
                    candidates.append(rel)
        except FileNotFoundError as exc:
            raise AlbumCoverError("NOT_FOUND", f"album not found: {album_rel_path}", http_status=404) from exc
        except OSError as exc:
            raise AlbumCoverError("READ_DIR_FAILED", f"cannot read album directory: {exc}", http_status=500) from exc
        return candidates

    def _select_cover_images(
        self,
        *,
        album_rel_path: str,
        album_mtime_ns: int,
        album_listing_hash: str,
        candidates: list[str],
    ) -> list[str]:
        if not candidates:
            raise AlbumCoverError("ALBUM_EMPTY", f"album has no images: {album_rel_path}", http_status=404)

        seed_src = (
            f"v1|{album_rel_path}|m={album_mtime_ns}|n={len(candidates)}|h={album_listing_hash}".encode("utf-8")
        )
        seed = int(hashlib.sha1(seed_src).hexdigest(), 16)
        rng = random.Random(seed)

        if len(candidates) >= 4:
            return rng.sample(candidates, k=4)

        chosen = rng.sample(candidates, k=len(candidates))
        while len(chosen) < 4:
            chosen.append(rng.choice(candidates))
        return chosen[:4]

    def _etag_and_cache_path(
        self,
        *,
        album_rel_path: str,
        album_stat: os.stat_result,
        album_image_count: int,
        album_listing_hash: str,
        cover_image_rel_paths: list[str],
    ) -> tuple[str, Path]:
        version = "v1"
        fmt = "jpeg"
        layout = "2x2"
        style = "blur-fit"
        spec = f"{version}|{fmt}|layout={layout}|style={style}|s={self._cover_size}|q={self._cover_quality}"

        parts: list[str] = []
        if self._key_mode == "sha1":
            for rel in cover_image_rel_paths:
                _rel, abs_path, _st = self._resolve_abs_image(rel)
                parts.append(_sha1_file(abs_path))
            key_src = (
                f"{spec}|sha1|album={album_rel_path}|m={album_stat.st_mtime_ns}|n={album_image_count}|h={album_listing_hash}|{'|'.join(parts)}".encode(
                    "utf-8"
                )
            )
        else:
            for rel in cover_image_rel_paths:
                rel, _abs_path, st = self._resolve_abs_image(rel)
                parts.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
            key_src = (
                f"{spec}|mtime|album={album_rel_path}|m={album_stat.st_mtime_ns}|n={album_image_count}|h={album_listing_hash}|{'|'.join(parts)}".encode(
                    "utf-8"
                )
            )

        etag = hashlib.sha1(key_src).hexdigest()
        cache_path = self._cache_dir / etag[:2] / etag[2:4] / f"{etag}.jpg"
        return etag, cache_path

    def get_cached(self, album_rel_path: str) -> AlbumCoverResult | None:
        album_rel_path, abs_dir, album_st = self._resolve_abs_album_dir(album_rel_path)
        candidates = sorted(set(self._list_album_images(album_rel_path=album_rel_path, abs_dir=abs_dir)))
        listing_hash = hashlib.sha1("\0".join(candidates).encode("utf-8")).hexdigest()
        cover_image_rel_paths = self._select_cover_images(
            album_rel_path=album_rel_path,
            album_mtime_ns=getattr(album_st, "st_mtime_ns", int(album_st.st_mtime * 1_000_000_000)),
            album_listing_hash=listing_hash,
            candidates=candidates,
        )
        etag, cache_path = self._etag_and_cache_path(
            album_rel_path=album_rel_path,
            album_stat=album_st,
            album_image_count=len(candidates),
            album_listing_hash=listing_hash,
            cover_image_rel_paths=cover_image_rel_paths,
        )
        if cache_path.exists():
            return AlbumCoverResult(
                cache_path=cache_path,
                etag=etag,
                content_type="image/jpeg",
                source_mtime_ms=_mtime_ms_from_stat(album_st),
                cover_image_rel_paths=cover_image_rel_paths,
            )
        return None

    def ensure_cover(self, album_rel_path: str) -> AlbumCoverResult:
        album_rel_path, abs_dir, album_st = self._resolve_abs_album_dir(album_rel_path)
        candidates = sorted(set(self._list_album_images(album_rel_path=album_rel_path, abs_dir=abs_dir)))
        listing_hash = hashlib.sha1("\0".join(candidates).encode("utf-8")).hexdigest()
        cover_image_rel_paths = self._select_cover_images(
            album_rel_path=album_rel_path,
            album_mtime_ns=getattr(album_st, "st_mtime_ns", int(album_st.st_mtime * 1_000_000_000)),
            album_listing_hash=listing_hash,
            candidates=candidates,
        )
        etag, cache_path = self._etag_and_cache_path(
            album_rel_path=album_rel_path,
            album_stat=album_st,
            album_image_count=len(candidates),
            album_listing_hash=listing_hash,
            cover_image_rel_paths=cover_image_rel_paths,
        )

        lock = self._key_lock(etag)
        with lock:
            if cache_path.exists():
                return AlbumCoverResult(
                    cache_path=cache_path,
                    etag=etag,
                    content_type="image/jpeg",
                    source_mtime_ms=_mtime_ms_from_stat(album_st),
                    cover_image_rel_paths=cover_image_rel_paths,
                )

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._render_cover_to_jpeg(
                    cover_image_rel_paths=cover_image_rel_paths,
                    out_path=cache_path,
                )
            except AlbumCoverError:
                raise
            except Exception as exc:
                logger.exception("album cover rendering failed: %s", exc)
                raise AlbumCoverError(
                    "ALBUM_COVER_FAILED",
                    f"failed to generate album cover: {exc}",
                    http_status=500,
                ) from exc

        return AlbumCoverResult(
            cache_path=cache_path,
            etag=etag,
            content_type="image/jpeg",
            source_mtime_ms=_mtime_ms_from_stat(album_st),
            cover_image_rel_paths=cover_image_rel_paths,
        )

    def _render_cover_to_jpeg(self, *, cover_image_rel_paths: list[str], out_path: Path) -> None:
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        except ModuleNotFoundError as exc:
            raise AlbumCoverError(
                "PILLOW_NOT_INSTALLED",
                "Pillow is required for album cover generation (pip install pillow).",
                http_status=503,
            ) from exc

        cover_size = self._cover_size
        w_left = cover_size // 2
        w_right = cover_size - w_left
        h_top = cover_size // 2
        h_bottom = cover_size - h_top
        slots = [
            (0, 0, w_left, h_top),
            (w_left, 0, w_right, h_top),
            (0, h_top, w_left, h_bottom),
            (w_left, h_top, w_right, h_bottom),
        ]

        def render_tile(*, abs_path: Path, out_w: int, out_h: int) -> Image.Image:
            with Image.open(abs_path) as im:
                im = ImageOps.exif_transpose(im)
                if getattr(im, "is_animated", False):
                    try:
                        im.seek(0)
                    except EOFError:
                        pass
                im = im.convert("RGB")

                bg_scale = max(out_w / im.width, out_h / im.height)
                bg_w = max(1, int(im.width * bg_scale))
                bg_h = max(1, int(im.height * bg_scale))
                bg = im.resize((bg_w, bg_h), resample=Image.Resampling.LANCZOS)
                left = max(0, (bg.width - out_w) // 2)
                top = max(0, (bg.height - out_h) // 2)
                bg = bg.crop((left, top, left + out_w, top + out_h))
                bg = bg.filter(ImageFilter.GaussianBlur(radius=max(2.0, min(out_w, out_h) / 18)))
                bg = ImageEnhance.Brightness(bg).enhance(0.92)

                fg_scale = min(out_w / im.width, out_h / im.height)
                fg_w = max(1, int(im.width * fg_scale))
                fg_h = max(1, int(im.height * fg_scale))
                fg = im.resize((fg_w, fg_h), resample=Image.Resampling.LANCZOS)
                x = (out_w - fg.width) // 2
                y = (out_h - fg.height) // 2
                bg.paste(fg, (x, y))
                return bg

        tiles: list[Image.Image] = []
        for rel in cover_image_rel_paths[:4]:
            _rel, abs_path, _st = self._resolve_abs_image(rel)
            tile_w, tile_h = slots[len(tiles)][2], slots[len(tiles)][3]
            tiles.append(render_tile(abs_path=abs_path, out_w=tile_w, out_h=tile_h))

        mosaic = Image.new("RGB", (cover_size, cover_size))
        for slot, tile in zip(slots, tiles, strict=False):
            x, y, _w, _h = slot
            mosaic.paste(tile, (x, y))

        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        mosaic.save(
            tmp_path,
            format="JPEG",
            quality=self._cover_quality,
            optimize=True,
            progressive=True,
        )
        os.replace(tmp_path, out_path)
