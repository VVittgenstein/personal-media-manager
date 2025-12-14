from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.indexing.media_index import build_media_index  # noqa: E402
from backend.indexing.media_types import MediaTypes  # noqa: E402
from backend.thumbnails.album_covers import AlbumCoverService  # noqa: E402
from backend.thumbnails.image_thumbs import ThumbKeyMode, ThumbnailService  # noqa: E402
from backend.thumbnails.video_mosaics import VideoMosaicService  # noqa: E402


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _cpu_model() -> str | None:
    text = _read_text(Path("/proc/cpuinfo"))
    if not text:
        return None
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip() == "model name":
            return v.strip() or None
    return None


def _mem_total_bytes() -> int | None:
    text = _read_text(Path("/proc/meminfo"))
    if not text:
        return None
    for line in text.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            kb = int(parts[1])
        except ValueError:
            return None
        return kb * 1024
    return None


def _rss_bytes() -> int | None:
    text = _read_text(Path("/proc/self/status"))
    if not text:
        return None
    for line in text.splitlines():
        if not line.startswith("VmRSS:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            kb = int(parts[1])
        except ValueError:
            return None
        return kb * 1024
    return None


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return float(values_sorted[f])
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return float(d0 + d1)


def _now_iso_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _format_bytes(n: int | None) -> str | None:
    if n is None:
        return None
    value = float(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if value >= 100:
        return f"{value:.0f} {units[unit]}"
    if value >= 10:
        return f"{value:.1f} {units[unit]}"
    return f"{value:.2f} {units[unit]}"


@dataclass(frozen=True)
class BenchConfig:
    media_root: Path
    thumb_size: int
    thumb_quality: int
    thumb_workers: int
    thumb_key: ThumbKeyMode
    repeats: int
    sample_images: int | None


def bench_index(cfg: BenchConfig) -> dict[str, Any]:
    times_s: list[float] = []
    rss_before = _rss_bytes()
    index = None
    for _ in range(max(1, cfg.repeats)):
        t0 = time.perf_counter()
        index = build_media_index(cfg.media_root, media_types=MediaTypes.defaults(), include_trash=False)
        times_s.append(time.perf_counter() - t0)
    rss_after = _rss_bytes()

    assert index is not None
    counts = {
        "albums": len(index.albums),
        "images": len(index.images),
        "scattered_images": len(index.scattered_images),
        "videos": len(index.videos),
        "games": len(index.games),
        "others": len(index.others),
    }
    return {
        "repeats": int(cfg.repeats),
        "times_s": times_s,
        "p50_s": statistics.median(times_s),
        "p95_s": _percentile(times_s, 95),
        "min_s": min(times_s),
        "max_s": max(times_s),
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "rss_before_human": _format_bytes(rss_before),
        "rss_after_human": _format_bytes(rss_after),
        "stats": dict(index.stats),
        "counts": {k: v for k, v in counts.items() if v is not None},
    }


def _iter_sample(rel_paths: list[str], limit: int | None) -> list[str]:
    if limit is None:
        return rel_paths
    if limit <= 0:
        return []
    return rel_paths[:limit]


def bench_thumbs(cfg: BenchConfig, *, rel_paths: list[str], cache_dir: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    paths = _iter_sample(rel_paths, cfg.sample_images)
    pool_size = max(1, cfg.thumb_workers * 2)

    def run_direct(*, service: ThumbnailService) -> dict[str, Any]:
        errors = 0
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=pool_size) as ex:
            futs = [ex.submit(service.ensure_thumb, rel) for rel in paths]
            for fut in as_completed(futs):
                try:
                    fut.result()
                except Exception:
                    errors += 1
        dt = time.perf_counter() - t0
        rate = (len(paths) / dt) if dt > 0 else None
        return {"count": len(paths), "errors": errors, "took_s": dt, "rate_items_per_s": rate}

    def run_batch(*, service: ThumbnailService) -> dict[str, Any]:
        # Uses internal queue join to mimic /api/thumbs/warm behavior.
        t0 = time.perf_counter()
        stats = service.enqueue_many(paths)
        service._queue.join()  # noqa: SLF001
        dt = time.perf_counter() - t0
        count = stats.get("accepted", 0) + stats.get("skipped_cached", 0)
        rate = (count / dt) if dt > 0 else None
        return {"enqueue_stats": stats, "took_s": dt, "rate_items_per_s": rate}

    def make_service(cache_dir_: Path) -> ThumbnailService:
        return ThumbnailService(
            media_root=cfg.media_root,
            media_types=MediaTypes.defaults(),
            cache_dir=cache_dir_,
            thumb_size=cfg.thumb_size,
            thumb_quality=cfg.thumb_quality,
            key_mode=cfg.thumb_key,
            workers=cfg.thumb_workers,
        )

    rss_before = _rss_bytes()

    direct_cache = cache_dir / "direct"
    direct_cache.mkdir(parents=True, exist_ok=True)
    thumbs_direct = make_service(direct_cache)
    try:
        direct_cold = run_direct(service=thumbs_direct)
        rss_after_direct_cold = _rss_bytes()
        direct_warm = run_direct(service=thumbs_direct)
        rss_after_direct_warm = _rss_bytes()
    finally:
        thumbs_direct.close()

    batch_cache = cache_dir / "batch"
    batch_cache.mkdir(parents=True, exist_ok=True)
    thumbs_batch = make_service(batch_cache)
    try:
        batch_cold = run_batch(service=thumbs_batch)
        rss_after_batch_cold = _rss_bytes()
        batch_warm = run_batch(service=thumbs_batch)
        rss_after_batch_warm = _rss_bytes()
    finally:
        thumbs_batch.close()

    return {
        "config": {
            "thumb_size": cfg.thumb_size,
            "thumb_quality": cfg.thumb_quality,
            "thumb_workers": cfg.thumb_workers,
            "thumb_key": cfg.thumb_key,
            "pool_size": pool_size,
            "sample_images": cfg.sample_images,
        },
        "direct_cold": direct_cold,
        "direct_warm": direct_warm,
        "batch_cold": batch_cold,
        "batch_warm": batch_warm,
        "rss_before_bytes": rss_before,
        "rss_after_direct_cold_bytes": rss_after_direct_cold,
        "rss_after_direct_warm_bytes": rss_after_direct_warm,
        "rss_after_batch_cold_bytes": rss_after_batch_cold,
        "rss_after_batch_warm_bytes": rss_after_batch_warm,
        "rss_before_human": _format_bytes(rss_before),
        "rss_after_direct_cold_human": _format_bytes(rss_after_direct_cold),
        "rss_after_direct_warm_human": _format_bytes(rss_after_direct_warm),
        "rss_after_batch_cold_human": _format_bytes(rss_after_batch_cold),
        "rss_after_batch_warm_human": _format_bytes(rss_after_batch_warm),
    }


def bench_album_covers(cfg: BenchConfig, *, album_rel_paths: list[str], cache_dir: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    covers = AlbumCoverService(
        media_root=cfg.media_root,
        media_types=MediaTypes.defaults(),
        cache_dir=cache_dir,
        cover_size=cfg.thumb_size,
        cover_quality=cfg.thumb_quality,
        key_mode=cfg.thumb_key,
    )

    paths = album_rel_paths
    t0 = time.perf_counter()
    errors = 0
    for rel in paths:
        try:
            covers.ensure_cover(rel)
        except Exception:
            errors += 1
    dt = time.perf_counter() - t0
    rate = (len(paths) / dt) if dt > 0 else None
    return {"count": len(paths), "errors": errors, "took_s": dt, "rate_items_per_s": rate}


def bench_video_mosaics(cfg: BenchConfig, *, video_rel_paths: list[str], cache_dir: Path) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    mosaics = VideoMosaicService(
        media_root=cfg.media_root,
        media_types=MediaTypes.defaults(),
        cache_dir=cache_dir,
        mosaic_size=cfg.thumb_size,
        mosaic_quality=cfg.thumb_quality,
        key_mode=cfg.thumb_key,
        gen_workers=max(1, cfg.thumb_workers // 2),
    )

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None:
        return {"skipped": True, "reason": "ffmpeg not found on PATH", "ffprobe_found": bool(ffprobe)}

    t0 = time.perf_counter()
    errors = 0
    for rel in video_rel_paths:
        try:
            mosaics.ensure_mosaic(rel)
        except Exception:
            errors += 1
    dt = time.perf_counter() - t0
    rate = (len(video_rel_paths) / dt) if dt > 0 else None
    return {
        "skipped": False,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "count": len(video_rel_paths),
        "errors": errors,
        "took_s": dt,
        "rate_items_per_s": rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run perf spike benchmarks for indexing + thumbnails.")
    parser.add_argument("--media-root", required=True, help="MediaRoot to benchmark.")
    parser.add_argument("--repeats", type=int, default=3, help="Index build repeats.")
    parser.add_argument("--sample-images", type=int, default=2000, help="Limit images for thumb benches (0=skip).")

    parser.add_argument("--thumb-size", type=int, default=320)
    parser.add_argument("--thumb-quality", type=int, default=82)
    parser.add_argument("--thumb-workers", type=int, default=2)
    parser.add_argument("--thumb-key", choices=["mtime", "sha1"], default="mtime")

    parser.add_argument("--out", required=False, help="Write JSON result to this file path.")
    args = parser.parse_args()

    media_root = Path(args.media_root)
    if not media_root.exists() or not media_root.is_dir():
        raise SystemExit(f"invalid --media-root: {media_root}")

    cfg = BenchConfig(
        media_root=media_root,
        thumb_size=int(args.thumb_size),
        thumb_quality=int(args.thumb_quality),
        thumb_workers=int(args.thumb_workers),
        thumb_key=str(args.thumb_key),  # type: ignore[assignment]
        repeats=max(1, int(args.repeats)),
        sample_images=(None if args.sample_images is None else int(args.sample_images)),
    )

    index = build_media_index(cfg.media_root, media_types=MediaTypes.defaults(), include_trash=False)
    image_rel_paths = [it.rel_path for it in index.images]
    album_rel_paths = [a.rel_path for a in index.albums]
    video_rel_paths = [v.rel_path for v in index.videos]

    if cfg.sample_images is not None and cfg.sample_images <= 0:
        cfg = BenchConfig(
            media_root=cfg.media_root,
            thumb_size=cfg.thumb_size,
            thumb_quality=cfg.thumb_quality,
            thumb_workers=cfg.thumb_workers,
            thumb_key=cfg.thumb_key,
            repeats=cfg.repeats,
            sample_images=0,
        )

    with tempfile.TemporaryDirectory(prefix="ppm-perf-cache-") as tmp:
        cache_dir = Path(tmp)
        out: dict[str, Any] = {
            "meta": {
                "generated_at": _now_iso_utc(),
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "cpu_model": _cpu_model(),
                "mem_total_bytes": _mem_total_bytes(),
                "mem_total_human": _format_bytes(_mem_total_bytes()),
            },
            "dataset": {
                "media_root": str(cfg.media_root),
                "counts": {
                    "albums": len(album_rel_paths),
                    "images": len(image_rel_paths),
                    "videos": len(video_rel_paths),
                },
            },
            "index": bench_index(cfg),
        }

        if cfg.sample_images is None or cfg.sample_images > 0:
            out["thumbnails"] = bench_thumbs(cfg, rel_paths=image_rel_paths, cache_dir=cache_dir / "thumbs")
        out["album_covers"] = bench_album_covers(cfg, album_rel_paths=album_rel_paths, cache_dir=cache_dir / "covers")
        out["video_mosaics"] = bench_video_mosaics(cfg, video_rel_paths=video_rel_paths, cache_dir=cache_dir / "mosaics")

    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
