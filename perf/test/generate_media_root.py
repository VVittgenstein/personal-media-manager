from __future__ import annotations

import argparse
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path


def _parse_sizes(raw: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for part in (raw or "").split(","):
        part = part.strip().lower()
        if not part:
            continue
        if "x" not in part:
            raise argparse.ArgumentTypeError(f"invalid size: {part} (expected WxH)")
        w_raw, h_raw = part.split("x", 1)
        try:
            w = int(w_raw)
            h = int(h_raw)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid size: {part} (expected WxH)") from exc
        if w <= 0 or h <= 0:
            raise argparse.ArgumentTypeError(f"invalid size: {part} (W/H must be > 0)")
        out.append((w, h))
    if not out:
        raise argparse.ArgumentTypeError("sizes must not be empty")
    return out


def _ensure_clean_dir(path: Path, *, force: bool) -> None:
    if path.exists():
        if not force:
            raise SystemExit(f"output path already exists: {path} (use --force to overwrite)")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _generate_images(
    *,
    out_dir: Path,
    rel_dir: str,
    count: int,
    sizes: list[tuple[int, int]],
    rng: random.Random,
    fmt: str,
    jpeg_quality: int,
    pattern: str,
    prefix: str,
) -> int:
    try:
        from PIL import Image, ImageOps
    except ModuleNotFoundError as exc:
        raise SystemExit("Pillow is required: pip install -r backend/requirements.txt") from exc

    written = 0
    ext = "jpg" if fmt == "jpeg" else "png"
    for i in range(count):
        w, h = rng.choice(sizes)

        if pattern == "solid":
            color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            im = Image.new("RGB", (w, h), color)
        else:
            if pattern == "noise":
                base = Image.effect_noise((w, h), sigma=64.0).convert("L")
            else:
                base = Image.linear_gradient("L").resize((w, h))
                if rng.random() < 0.5:
                    base = base.transpose(Image.Transpose.ROTATE_90)
            c1 = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            c2 = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            im = ImageOps.colorize(base, c1, c2).convert("RGB")

        name = f"{prefix}_{i:05d}.{ext}"
        path = out_dir / rel_dir / name if rel_dir else out_dir / name

        tmp = path.with_suffix(path.suffix + ".tmp")
        if fmt == "png":
            im.save(tmp, format="PNG", compress_level=6)
        else:
            im.save(tmp, format="JPEG", quality=jpeg_quality, optimize=False, progressive=False)
        os.replace(tmp, path)
        im.close()
        written += 1

    return written


@dataclass(frozen=True)
class DatasetSpec:
    albums: int
    images_per_album: int
    scattered_images: int
    videos: int
    others: int


def _make_dummy_files(*, out_dir: Path, rel_dir: str, count: int, ext: str, rng: random.Random) -> int:
    written = 0
    for i in range(count):
        rel_name = f"{ext.strip('.').lower()}_{i:05d}{ext}"
        rel_path = f"{rel_dir}/{rel_name}" if rel_dir else rel_name
        payload = f"{rel_name}\nseed={rng.getrandbits(64)}\n".encode("utf-8")
        _write_atomic(out_dir / rel_path, payload)
        written += 1
    return written


def build_dataset(
    *,
    out_dir: Path,
    spec: DatasetSpec,
    sizes: list[tuple[int, int]],
    seed: int,
    image_format: str,
    jpeg_quality: int,
    pattern: str,
) -> dict[str, int]:
    rng = random.Random(int(seed))

    stats: dict[str, int] = {"albums": 0, "images": 0, "videos": 0, "others": 0}

    albums_root = "Albums"
    for i in range(spec.albums):
        album_rel = f"{albums_root}/Album-{i:04d}"
        (out_dir / album_rel).mkdir(parents=True, exist_ok=True)
        stats["albums"] += 1
        stats["images"] += _generate_images(
            out_dir=out_dir,
            rel_dir=album_rel,
            count=spec.images_per_album,
            sizes=sizes,
            rng=rng,
            fmt=image_format,
            jpeg_quality=jpeg_quality,
            pattern=pattern,
            prefix="img",
        )

    stats["images"] += _generate_images(
        out_dir=out_dir,
        rel_dir="",
        count=spec.scattered_images,
        sizes=sizes,
        rng=rng,
        fmt=image_format,
        jpeg_quality=jpeg_quality,
        pattern=pattern,
        prefix="scattered",
    )

    stats["videos"] += _make_dummy_files(out_dir=out_dir, rel_dir="Videos", count=spec.videos, ext=".mp4", rng=rng)
    stats["others"] += _make_dummy_files(out_dir=out_dir, rel_dir="Others", count=spec.others, ext=".txt", rng=rng)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a reproducible MediaRoot dataset for perf testing.")
    parser.add_argument("--out", required=True, help="Output MediaRoot directory to create.")
    parser.add_argument("--force", action="store_true", help="Overwrite output directory if it exists.")

    parser.add_argument("--albums", type=int, default=200, help="Number of album folders to create.")
    parser.add_argument("--images-per-album", type=int, default=40, help="Number of images per album.")
    parser.add_argument("--scattered-images", type=int, default=2000, help="Number of scattered images in MediaRoot.")
    parser.add_argument("--videos", type=int, default=500, help="Number of dummy video files.")
    parser.add_argument("--others", type=int, default=500, help="Number of dummy other files.")

    parser.add_argument(
        "--sizes",
        type=_parse_sizes,
        default=_parse_sizes("640x360,360x640,800x800,1024x768,768x1024"),
        help="Comma-separated list of image sizes to sample from (e.g. 640x360,360x640).",
    )
    parser.add_argument("--seed", type=int, default=20251212, help="Random seed for reproducibility.")
    parser.add_argument("--image-format", choices=["jpeg", "png"], default="jpeg", help="Image output format.")
    parser.add_argument("--jpeg-quality", type=int, default=78, help="JPEG quality when --image-format=jpeg.")
    parser.add_argument(
        "--pattern",
        choices=["gradient", "solid", "noise"],
        default="gradient",
        help="Image content pattern (gradient is fast and deterministic).",
    )

    args = parser.parse_args()

    if args.albums < 0 or args.images_per_album < 0 or args.scattered_images < 0 or args.videos < 0 or args.others < 0:
        raise SystemExit("counts must be >= 0")
    if args.image_format == "jpeg" and not (1 <= args.jpeg_quality <= 95):
        raise SystemExit("--jpeg-quality must be between 1 and 95")

    out_dir = Path(args.out)
    _ensure_clean_dir(out_dir, force=bool(args.force))

    stats = build_dataset(
        out_dir=out_dir,
        spec=DatasetSpec(
            albums=int(args.albums),
            images_per_album=int(args.images_per_album),
            scattered_images=int(args.scattered_images),
            videos=int(args.videos),
            others=int(args.others),
        ),
        sizes=list(args.sizes),
        seed=int(args.seed),
        image_format=str(args.image_format),
        jpeg_quality=int(args.jpeg_quality),
        pattern=str(args.pattern),
    )

    total_images = stats["albums"] * int(args.images_per_album) + int(args.scattered_images)
    print("MediaRoot generated:")
    print(f"  path:   {out_dir}")
    print(f"  albums: {stats['albums']}")
    print(f"  images: {stats['images']} (expected {total_images})")
    print(f"  videos: {stats['videos']}")
    print(f"  others: {stats['others']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

