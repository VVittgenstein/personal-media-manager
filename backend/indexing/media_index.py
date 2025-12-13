from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.scanner.inventory import InventoryResult, scan_inventory

from .media_types import MediaTypes, load_media_types


def _parent_rel_path(rel_path: str) -> str | None:
    if rel_path == "":
        return None
    head, _sep, _tail = rel_path.rpartition("/")
    return head


def _depth(rel_path: str) -> int:
    if rel_path == "":
        return 0
    return rel_path.count("/") + 1


def _basename(rel_path: str) -> str:
    if rel_path == "":
        return ""
    _head, _sep, tail = rel_path.rpartition("/")
    return tail


def _folder_of_file(rel_path: str) -> str:
    head, _sep, _tail = rel_path.rpartition("/")
    return head


@dataclass
class AlbumSummary:
    rel_path: str
    name: str
    title: str
    image_count: int
    mtime_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "name": self.name,
            "title": self.title,
            "image_count": self.image_count,
            "mtime_ms": self.mtime_ms,
        }


@dataclass
class MediaFile:
    rel_path: str
    folder_rel_path: str
    ext: str
    size_bytes: int | None
    mtime_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "folder_rel_path": self.folder_rel_path,
            "ext": self.ext,
            "size_bytes": self.size_bytes,
            "mtime_ms": self.mtime_ms,
        }


@dataclass
class OtherFile(MediaFile):
    category: str  # "game" | "other"

    def as_dict(self) -> dict[str, Any]:
        base = super().as_dict()
        base["category"] = self.category
        return base


@dataclass
class MediaIndex:
    media_root: str
    scanned_at_ms: int
    albums: list[AlbumSummary]
    scattered_images: list[MediaFile]
    videos: list[MediaFile]
    games: list[OtherFile]
    others: list[OtherFile]
    stats: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "media_root": self.media_root,
            "scanned_at_ms": self.scanned_at_ms,
            "albums": [a.as_dict() for a in self.albums],
            "scattered_images": [i.as_dict() for i in self.scattered_images],
            "videos": [v.as_dict() for v in self.videos],
            "games": [g.as_dict() for g in self.games],
            "others": [o.as_dict() for o in self.others],
            "stats": dict(self.stats),
        }


@dataclass
class _FolderAgg:
    rel_path: str
    parent_rel_path: str | None
    depth: int
    child_folder_rel_paths: list[str]
    image_count_direct: int
    video_count_direct: int
    other_count_direct: int
    has_image_descendant: bool
    mtime_ms: int | None


def classify_inventory(inventory: InventoryResult, *, media_types: MediaTypes) -> MediaIndex:
    folders: dict[str, _FolderAgg] = {}

    for item in inventory.items:
        if item.kind != "dir":
            continue
        rel = item.rel_path
        folders[rel] = _FolderAgg(
            rel_path=rel,
            parent_rel_path=_parent_rel_path(rel),
            depth=_depth(rel),
            child_folder_rel_paths=[],
            image_count_direct=0,
            video_count_direct=0,
            other_count_direct=0,
            has_image_descendant=False,
            mtime_ms=item.mtime_ms,
        )

    for folder in list(folders.values()):
        if folder.parent_rel_path is None:
            continue
        parent = folders.get(folder.parent_rel_path)
        if parent is None:
            continue
        parent.child_folder_rel_paths.append(folder.rel_path)

    images: list[MediaFile] = []
    videos: list[MediaFile] = []
    games: list[OtherFile] = []
    others: list[OtherFile] = []

    for item in inventory.items:
        if item.kind != "file":
            continue
        rel = item.rel_path
        folder_rel = _folder_of_file(rel)
        ext = os.path.splitext(rel)[1].lower()
        kind = media_types.categorize_ext(ext)

        folder = folders.get(folder_rel)
        if folder is None:
            continue

        if kind == "image":
            images.append(
                MediaFile(
                    rel_path=rel,
                    folder_rel_path=folder_rel,
                    ext=ext,
                    size_bytes=item.size_bytes,
                    mtime_ms=item.mtime_ms,
                )
            )
            folder.image_count_direct += 1
            continue

        if kind == "video":
            videos.append(
                MediaFile(
                    rel_path=rel,
                    folder_rel_path=folder_rel,
                    ext=ext,
                    size_bytes=item.size_bytes,
                    mtime_ms=item.mtime_ms,
                )
            )
            folder.video_count_direct += 1
            continue

        category = "game" if kind == "game" else "other"
        other_entry = OtherFile(
            rel_path=rel,
            folder_rel_path=folder_rel,
            ext=ext,
            size_bytes=item.size_bytes,
            mtime_ms=item.mtime_ms,
            category=category,
        )
        if category == "game":
            games.append(other_entry)
        else:
            others.append(other_entry)
        folder.other_count_direct += 1

    for folder in sorted(folders.values(), key=lambda f: f.depth, reverse=True):
        has = False
        for child_rel in folder.child_folder_rel_paths:
            child = folders[child_rel]
            if child.image_count_direct > 0 or child.has_image_descendant:
                has = True
                break
        folder.has_image_descendant = has

    albums_by_rel: dict[str, AlbumSummary] = {}
    for folder in folders.values():
        if folder.rel_path == "":
            continue
        if folder.image_count_direct <= 0:
            continue
        if folder.has_image_descendant:
            continue
        rel = folder.rel_path
        albums_by_rel[rel] = AlbumSummary(
            rel_path=rel,
            name=_basename(rel),
            title=rel,
            image_count=folder.image_count_direct,
            mtime_ms=folder.mtime_ms,
        )

    album_rels = set(albums_by_rel.keys())
    scattered: list[MediaFile] = []
    for img in images:
        current = img.folder_rel_path
        owning_album = None
        while True:
            if current in album_rels:
                owning_album = current
                break
            parent = _parent_rel_path(current)
            if parent is None:
                break
            current = parent

        if owning_album is None:
            scattered.append(img)

    albums = [albums_by_rel[k] for k in sorted(albums_by_rel.keys())]
    scattered.sort(key=lambda f: f.rel_path)
    videos.sort(key=lambda f: f.rel_path)
    games.sort(key=lambda f: f.rel_path)
    others.sort(key=lambda f: f.rel_path)

    return MediaIndex(
        media_root=inventory.media_root,
        scanned_at_ms=inventory.scanned_at_ms,
        albums=albums,
        scattered_images=scattered,
        videos=videos,
        games=games,
        others=others,
        stats=dict(inventory.stats),
    )


def build_media_index(
    media_root: str | Path,
    *,
    media_types: MediaTypes | None = None,
    media_types_config: str | Path | None = None,
    include_trash: bool = False,
) -> MediaIndex:
    if media_types is None:
        media_types = load_media_types(media_types_config)
    inventory = scan_inventory(media_root, skip_trash=not include_trash)
    return classify_inventory(inventory, media_types=media_types)
