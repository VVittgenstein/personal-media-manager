from __future__ import annotations

from typing import Any, Iterable

from .media_index import AlbumSummary, ImageFile, MediaFile, MediaIndex, OtherFile

SearchType = str

_ALL_SEARCH_TYPES: set[SearchType] = {"album", "image", "video", "game", "other"}


def normalize_search_query(query: str) -> str:
    query = query.strip().replace("\\", "/")
    return " ".join(query.split())


def parse_search_types(value: str | None) -> set[SearchType]:
    if value is None:
        return set(_ALL_SEARCH_TYPES)
    if not isinstance(value, str):
        raise TypeError("types must be a string")

    items = []
    for chunk in value.split(","):
        item = chunk.strip().lower()
        if item:
            items.append(item)

    if not items:
        return set(_ALL_SEARCH_TYPES)

    types = set(items)
    invalid = sorted(t for t in types if t not in _ALL_SEARCH_TYPES)
    if invalid:
        raise ValueError(f"invalid types: {', '.join(invalid)}")
    return types


def _tokens(query: str) -> list[str]:
    return [token for token in query.lower().split() if token]


def _matches(tokens: list[str], haystack: str) -> bool:
    if not tokens:
        return False
    for token in tokens:
        if token not in haystack:
            return False
    return True


def _album_haystack(album: AlbumSummary) -> str:
    return f"{album.name} {album.rel_path} {album.title}".lower()


def _file_haystack(item: MediaFile) -> str:
    _head, _sep, basename = item.rel_path.rpartition("/")
    return f"{basename} {item.rel_path} {item.folder_rel_path}".lower()


def _image_haystack(item: ImageFile) -> str:
    return _file_haystack(item)


def _other_haystack(item: OtherFile) -> str:
    return _file_haystack(item)


def search_media_index(
    index: MediaIndex,
    query: str,
    *,
    limit: int = 50,
    types: Iterable[SearchType] | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    normalized = normalize_search_query(query)
    tokens = _tokens(normalized)
    if not tokens:
        return []

    requested_types = set(types) if types is not None else set(_ALL_SEARCH_TYPES)
    results: list[dict[str, Any]] = []

    def _append(kind: SearchType, payload: dict[str, Any]) -> None:
        if len(results) >= limit:
            return
        payload["kind"] = kind
        results.append(payload)

    if "album" in requested_types:
        for album in index.albums:
            if _matches(tokens, _album_haystack(album)):
                _append("album", album.as_dict())
                if len(results) >= limit:
                    return results

    if "video" in requested_types:
        for video in index.videos:
            if _matches(tokens, _file_haystack(video)):
                _append("video", video.as_dict())
                if len(results) >= limit:
                    return results

    if "image" in requested_types:
        for img in index.images:
            if _matches(tokens, _image_haystack(img)):
                _append("image", img.as_dict())
                if len(results) >= limit:
                    return results

    if "game" in requested_types:
        for game in index.games:
            if _matches(tokens, _other_haystack(game)):
                _append("game", game.as_dict())
                if len(results) >= limit:
                    return results

    if "other" in requested_types:
        for other in index.others:
            if _matches(tokens, _other_haystack(other)):
                _append("other", other.as_dict())
                if len(results) >= limit:
                    return results

    return results
