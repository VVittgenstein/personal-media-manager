from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from backend.indexing.media_types import MediaTypes
from backend.scanner.sandbox import MediaRootSandbox, SandboxViolation, normalize_rel_path

from .image_thumbs import ThumbKeyMode, _sha1_file

logger = logging.getLogger(__name__)


class VideoMosaicError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class VideoMosaicResult:
    cache_path: Path
    etag: str
    content_type: str
    source_mtime_ms: int | None
    frame_timestamps_s: list[float]


def _mtime_ms_from_stat(st: os.stat_result) -> int | None:
    try:
        return int(st.st_mtime * 1000)
    except Exception:
        return None


def _format_ffmpeg_missing_message() -> str:
    return (
        "FFmpeg is required for video mosaic thumbnails but was not found. "
        "Install ffmpeg and ensure the 'ffmpeg' command is available on PATH "
        "(Windows: add ffmpeg/bin to PATH; macOS: brew install ffmpeg; Linux: apt/yum/pacman install ffmpeg)."
    )


class VideoMosaicService:
    def __init__(
        self,
        *,
        media_root: Path,
        media_types: MediaTypes,
        cache_dir: Path,
        mosaic_size: int = 320,
        mosaic_quality: int = 82,
        key_mode: ThumbKeyMode = "mtime",
        ffmpeg_cmd: str | None = None,
        ffprobe_cmd: str | None = None,
        gen_workers: int = 1,
    ) -> None:
        if mosaic_size <= 0:
            raise ValueError("mosaic_size must be > 0")
        if not (1 <= mosaic_quality <= 95):
            raise ValueError("mosaic_quality must be between 1 and 95")
        if gen_workers <= 0:
            raise ValueError("gen_workers must be > 0")

        self._sandbox = MediaRootSandbox(media_root)
        self._media_types = media_types
        self._cache_dir = Path(cache_dir) / "video-mosaics"
        self._mosaic_size = int(mosaic_size)
        self._mosaic_quality = int(mosaic_quality)
        self._key_mode: ThumbKeyMode = key_mode
        self._ffmpeg_cmd = ffmpeg_cmd
        self._ffprobe_cmd = ffprobe_cmd

        self._gen_sema = threading.Semaphore(gen_workers)
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
            raise VideoMosaicError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

    def _resolve_abs_video(self, rel_path: str) -> tuple[str, Path, os.stat_result]:
        rel_path = self._validate_rel_path(rel_path)
        if rel_path == "":
            raise VideoMosaicError("INVALID_PATH", "path must not be MediaRoot root", http_status=400)

        ext = os.path.splitext(rel_path)[1].lower()
        if self._media_types.categorize_ext(ext) != "video":
            raise VideoMosaicError("UNSUPPORTED_MEDIA_TYPE", f"not a video: {rel_path}", http_status=415)

        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise VideoMosaicError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        try:
            st = os.stat(abs_path, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise VideoMosaicError("NOT_FOUND", f"file not found: {rel_path}", http_status=404) from exc
        except OSError as exc:
            raise VideoMosaicError("STAT_FAILED", f"cannot stat file: {exc}", http_status=404) from exc

        if not abs_path.is_file():
            raise VideoMosaicError("NOT_A_FILE", f"not a file: {rel_path}", http_status=404)

        return rel_path, abs_path, st

    def _resolve_ffmpeg(self) -> str | None:
        if self._ffmpeg_cmd is not None:
            return self._ffmpeg_cmd
        return shutil.which("ffmpeg")

    def _resolve_ffprobe(self) -> str | None:
        if self._ffprobe_cmd is not None:
            return self._ffprobe_cmd
        return shutil.which("ffprobe")

    def _ffprobe_duration_seconds(self, abs_video_path: Path) -> float | None:
        ffprobe = self._resolve_ffprobe()
        if ffprobe is None:
            return None

        cmd = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(abs_video_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        except Exception as exc:
            logger.debug("ffprobe failed to run: %s", exc)
            return None
        if proc.returncode != 0:
            return None
        raw = (proc.stdout or "").strip()
        try:
            dur = float(raw)
        except ValueError:
            return None
        if dur <= 0:
            return None
        return dur

    def _select_frame_timestamps(self, duration_s: float | None) -> list[float]:
        if duration_s is None:
            return [0.0, 1.0, 2.0, 3.0]
        safe_end = max(0.0, duration_s - 0.05)
        picks = [duration_s * 0.05, duration_s * 0.25, duration_s * 0.5, duration_s * 0.75]
        out: list[float] = []
        for t in picks:
            if t < 0:
                t = 0.0
            if t > safe_end:
                t = safe_end
            out.append(float(t))
        return out

    def _etag_and_cache_path(self, *, rel_path: str, abs_path: Path, st: os.stat_result) -> tuple[str, Path]:
        version = "v1"
        fmt = "jpeg"
        spec = f"{version}|{fmt}|s={self._mosaic_size}|q={self._mosaic_quality}|frames=4"
        if self._key_mode == "sha1":
            src_id = _sha1_file(abs_path)
            key_src = f"{spec}|sha1|{src_id}".encode("utf-8")
        else:
            key_src = f"{spec}|mtime|{rel_path}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8")

        etag = hashlib.sha1(key_src).hexdigest()
        cache_path = self._cache_dir / etag[:2] / etag[2:4] / f"{etag}.jpg"
        return etag, cache_path

    def get_cached(self, rel_path: str) -> VideoMosaicResult | None:
        rel_path, abs_path, st = self._resolve_abs_video(rel_path)
        etag, cache_path = self._etag_and_cache_path(rel_path=rel_path, abs_path=abs_path, st=st)
        if cache_path.exists():
            duration_s = self._ffprobe_duration_seconds(abs_path)
            return VideoMosaicResult(
                cache_path=cache_path,
                etag=etag,
                content_type="image/jpeg",
                source_mtime_ms=_mtime_ms_from_stat(st),
                frame_timestamps_s=self._select_frame_timestamps(duration_s),
            )
        return None

    def ensure_mosaic(self, rel_path: str) -> VideoMosaicResult:
        rel_path, abs_path, st = self._resolve_abs_video(rel_path)

        duration_s = self._ffprobe_duration_seconds(abs_path)
        timestamps = self._select_frame_timestamps(duration_s)
        etag, cache_path = self._etag_and_cache_path(rel_path=rel_path, abs_path=abs_path, st=st)

        lock = self._key_lock(etag)
        with lock:
            if cache_path.exists():
                return VideoMosaicResult(
                    cache_path=cache_path,
                    etag=etag,
                    content_type="image/jpeg",
                    source_mtime_ms=_mtime_ms_from_stat(st),
                    frame_timestamps_s=timestamps,
                )

            ffmpeg = self._resolve_ffmpeg()
            if ffmpeg is None:
                raise VideoMosaicError("FFMPEG_NOT_AVAILABLE", _format_ffmpeg_missing_message(), http_status=503)

            cache_path.parent.mkdir(parents=True, exist_ok=True)

            acquired = self._gen_sema.acquire(timeout=60)
            if not acquired:
                raise VideoMosaicError(
                    "VIDEO_MOSAIC_RATE_LIMITED",
                    "video mosaic generation is busy; retry later",
                    http_status=429,
                )
            try:
                self._render_to_jpeg(
                    ffmpeg=ffmpeg,
                    abs_video_path=abs_path,
                    out_path=cache_path,
                    timestamps=timestamps,
                )
            finally:
                self._gen_sema.release()

        return VideoMosaicResult(
            cache_path=cache_path,
            etag=etag,
            content_type="image/jpeg",
            source_mtime_ms=_mtime_ms_from_stat(st),
            frame_timestamps_s=timestamps,
        )

    def _extract_frame_png(
        self,
        *,
        ffmpeg: str,
        abs_video_path: Path,
        timestamp_s: float,
        out_path: Path,
    ) -> None:
        timestamp_s = max(0.0, float(timestamp_s))
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{timestamp_s:.3f}",
            "-i",
            str(abs_video_path),
            "-an",
            "-sn",
            "-dn",
            "-frames:v",
            "1",
            "-f",
            "image2",
            "-c:v",
            "png",
            str(out_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        except FileNotFoundError as exc:
            raise VideoMosaicError("FFMPEG_NOT_AVAILABLE", _format_ffmpeg_missing_message(), http_status=503) from exc
        except subprocess.TimeoutExpired as exc:
            raise VideoMosaicError("FFMPEG_TIMEOUT", f"ffmpeg timed out extracting frame: {exc}", http_status=504) from exc
        except Exception as exc:
            raise VideoMosaicError("FFMPEG_FAILED", f"ffmpeg failed extracting frame: {exc}", http_status=502) from exc

        if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size <= 0:
            stderr = (proc.stderr or "").strip()
            msg = stderr if stderr else "ffmpeg failed to extract frame"
            raise VideoMosaicError("FFMPEG_FAILED", msg, http_status=502)

    def _render_to_jpeg(
        self,
        *,
        ffmpeg: str,
        abs_video_path: Path,
        out_path: Path,
        timestamps: list[float],
    ) -> None:
        try:
            from PIL import Image, ImageEnhance, ImageFilter
        except ModuleNotFoundError as exc:
            raise VideoMosaicError(
                "PILLOW_NOT_INSTALLED",
                "Pillow is required for video mosaic generation (pip install pillow).",
                http_status=503,
            ) from exc

        mosaic_size = self._mosaic_size
        w_left = mosaic_size // 2
        w_right = mosaic_size - w_left
        h_top = mosaic_size // 2
        h_bottom = mosaic_size - h_top
        slots = [
            (0, 0, w_left, h_top),
            (w_left, 0, w_right, h_top),
            (0, h_top, w_left, h_bottom),
            (w_left, h_top, w_right, h_bottom),
        ]

        def render_tile(*, frame_path: Path, out_w: int, out_h: int) -> Image.Image:
            with Image.open(frame_path) as im:
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

        with tempfile.TemporaryDirectory(prefix="video-mosaic-") as tmp:
            tmp_dir = Path(tmp)
            frame_paths: list[Path] = []
            for i, t in enumerate((timestamps or [])[:4]):
                out_frame = tmp_dir / f"f{i}.png"
                try:
                    self._extract_frame_png(
                        ffmpeg=ffmpeg,
                        abs_video_path=abs_video_path,
                        timestamp_s=t,
                        out_path=out_frame,
                    )
                except VideoMosaicError:
                    out_frame = tmp_dir / f"f{i}_fallback.png"
                    self._extract_frame_png(
                        ffmpeg=ffmpeg,
                        abs_video_path=abs_video_path,
                        timestamp_s=0.0,
                        out_path=out_frame,
                    )
                frame_paths.append(out_frame)

            while len(frame_paths) < 4:
                out_frame = tmp_dir / f"f{len(frame_paths)}_fallback.png"
                self._extract_frame_png(
                    ffmpeg=ffmpeg,
                    abs_video_path=abs_video_path,
                    timestamp_s=0.0,
                    out_path=out_frame,
                )
                frame_paths.append(out_frame)

            tiles: list[Image.Image] = []
            for frame_path in frame_paths[:4]:
                tile_w, tile_h = slots[len(tiles)][2], slots[len(tiles)][3]
                tiles.append(render_tile(frame_path=frame_path, out_w=tile_w, out_h=tile_h))

            mosaic = Image.new("RGB", (mosaic_size, mosaic_size))
            for slot, tile in zip(slots, tiles, strict=False):
                x, y, _w, _h = slot
                mosaic.paste(tile, (x, y))

            tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            mosaic.save(
                tmp_path,
                format="JPEG",
                quality=self._mosaic_quality,
                optimize=True,
                progressive=True,
            )
            os.replace(tmp_path, out_path)
