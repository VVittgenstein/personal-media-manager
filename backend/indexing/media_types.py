from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_IMAGE_EXTS = [
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".avif",
    ".svg",
]

DEFAULT_VIDEO_EXTS = [
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".ts",
]

DEFAULT_GAME_EXTS = [
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".lnk",
    ".url",
]


def _normalize_ext_list(values: Any) -> set[str]:
    if not isinstance(values, list):
        raise TypeError("expected a JSON array of extensions")
    exts: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            raise TypeError("extension must be a string")
        ext = raw.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            raise ValueError(f"invalid extension (must start with '.'): {raw!r}")
        exts.add(ext)
    return exts


@dataclass(frozen=True)
class MediaTypes:
    image_exts: set[str]
    video_exts: set[str]
    game_exts: set[str]

    @classmethod
    def defaults(cls) -> "MediaTypes":
        return cls(
            image_exts=set(DEFAULT_IMAGE_EXTS),
            video_exts=set(DEFAULT_VIDEO_EXTS),
            game_exts=set(DEFAULT_GAME_EXTS),
        )

    def categorize_ext(self, ext: str) -> str:
        ext = ext.lower()
        if ext in self.image_exts:
            return "image"
        if ext in self.video_exts:
            return "video"
        if ext in self.game_exts:
            return "game"
        return "other"


def default_media_types_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "config" / "media-types.json"


def load_media_types(config_path: str | Path | None = None) -> MediaTypes:
    defaults = MediaTypes.defaults()

    path = default_media_types_config_path() if config_path is None else Path(config_path)
    if not path.exists():
        return defaults

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("media types config must be a JSON object")

    image_exts = defaults.image_exts
    video_exts = defaults.video_exts
    game_exts = defaults.game_exts

    if "images" in data:
        image_exts = _normalize_ext_list(data["images"])
    if "videos" in data:
        video_exts = _normalize_ext_list(data["videos"])
    if "games" in data:
        game_exts = _normalize_ext_list(data["games"])

    return MediaTypes(image_exts=image_exts, video_exts=video_exts, game_exts=game_exts)

