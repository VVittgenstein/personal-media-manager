from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sandbox import MediaRootSandbox, _is_reparse_point, _is_within_root

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryWarning:
    code: str
    rel_path: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "rel_path": self.rel_path, "message": self.message}


@dataclass(frozen=True)
class InventoryItem:
    rel_path: str
    kind: str  # "file" | "dir"
    size_bytes: int | None
    mtime_ms: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "mtime_ms": self.mtime_ms,
        }


@dataclass(frozen=True)
class InventoryResult:
    media_root: str
    scanned_at_ms: int
    items: list[InventoryItem]
    warnings: list[InventoryWarning]
    stats: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "media_root": self.media_root,
            "scanned_at_ms": self.scanned_at_ms,
            "items": [i.as_dict() for i in self.items],
            "warnings": [w.as_dict() for w in self.warnings],
            "stats": dict(self.stats),
        }


def _mtime_ms_from_stat(st: os.stat_result | None) -> int | None:
    if st is None:
        return None
    try:
        return int(st.st_mtime * 1000)
    except Exception:
        return None


def scan_inventory(
    media_root: str | Path,
    *,
    skip_trash: bool = True,
    trash_dir_name: str = "_trash",
) -> InventoryResult:
    sandbox = MediaRootSandbox(Path(media_root))
    root_path = sandbox.media_root

    scanned_at_ms = int(time.time() * 1000)
    items: list[InventoryItem] = []
    warnings: list[InventoryWarning] = []
    stats: dict[str, int] = {
        "dirs": 0,
        "files": 0,
        "skipped_trash": 0,
        "skipped_links": 0,
        "stat_errors": 0,
        "scandir_errors": 0,
    }

    try:
        root_st = os.stat(root_path, follow_symlinks=False)
    except OSError as exc:
        root_st = None
        warnings.append(
            InventoryWarning(
                code="ROOT_STAT_FAILED",
                rel_path="",
                message=f"cannot stat MediaRoot: {exc}",
            )
        )
        stats["stat_errors"] += 1

    items.append(
        InventoryItem(
            rel_path="",
            kind="dir",
            size_bytes=None,
            mtime_ms=_mtime_ms_from_stat(root_st),
        )
    )
    stats["dirs"] += 1

    stack: list[tuple[Path, str]] = [(root_path, "")]

    trash_name_norm = trash_dir_name.casefold()

    while stack:
        abs_dir, rel_dir = stack.pop()

        try:
            it = os.scandir(abs_dir)
        except OSError as exc:
            warning = InventoryWarning(code="SCANDIR_FAILED", rel_path=rel_dir, message=str(exc))
            warnings.append(warning)
            logger.warning("%s: %s (%s)", warning.code, warning.rel_path, warning.message)
            stats["scandir_errors"] += 1
            continue

        with it:
            for entry in it:
                child_rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                child_rel = child_rel.replace("\\", "/")

                if skip_trash:
                    first_segment = child_rel.split("/", 1)[0].casefold()
                    if first_segment == trash_name_norm:
                        stats["skipped_trash"] += 1
                        continue

                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    warning = InventoryWarning(code="STAT_FAILED", rel_path=child_rel, message=str(exc))
                    warnings.append(warning)
                    logger.warning("%s: %s (%s)", warning.code, warning.rel_path, warning.message)
                    stats["stat_errors"] += 1
                    continue

                is_link = entry.is_symlink() or _is_reparse_point(st)
                if is_link:
                    target_outside = False
                    try:
                        resolved = Path(entry.path).resolve(strict=False)
                        target_outside = not _is_within_root(root=root_path, path=resolved)
                    except OSError:
                        target_outside = False

                    code = "LINK_OUT_OF_BOUNDS" if target_outside else "LINK_SKIPPED"
                    warning = InventoryWarning(
                        code=code,
                        rel_path=child_rel,
                        message="symlink/junction skipped to prevent escaping MediaRoot",
                    )
                    warnings.append(warning)
                    logger.warning("%s: %s (%s)", warning.code, warning.rel_path, warning.message)
                    stats["skipped_links"] += 1
                    continue

                try:
                    if entry.is_dir(follow_symlinks=False):
                        items.append(
                            InventoryItem(
                                rel_path=child_rel,
                                kind="dir",
                                size_bytes=None,
                                mtime_ms=_mtime_ms_from_stat(st),
                            )
                        )
                        stats["dirs"] += 1
                        stack.append((Path(entry.path), child_rel))
                        continue

                    if entry.is_file(follow_symlinks=False):
                        items.append(
                            InventoryItem(
                                rel_path=child_rel,
                                kind="file",
                                size_bytes=int(st.st_size),
                                mtime_ms=_mtime_ms_from_stat(st),
                            )
                        )
                        stats["files"] += 1
                        continue

                    mode = st.st_mode
                    kind = "file" if stat.S_ISREG(mode) else "file"
                    items.append(
                        InventoryItem(
                            rel_path=child_rel,
                            kind=kind,
                            size_bytes=int(getattr(st, "st_size", 0)),
                            mtime_ms=_mtime_ms_from_stat(st),
                        )
                    )
                    stats["files"] += 1
                except OSError as exc:
                    warning = InventoryWarning(
                        code="ENTRY_PROCESS_FAILED",
                        rel_path=child_rel,
                        message=str(exc),
                    )
                    warnings.append(warning)
                    logger.warning("%s: %s (%s)", warning.code, warning.rel_path, warning.message)
                    stats["stat_errors"] += 1
                    continue

    return InventoryResult(
        media_root=os.fspath(root_path),
        scanned_at_ms=scanned_at_ms,
        items=items,
        warnings=warnings,
        stats=stats,
    )


def write_inventory_json(result: InventoryResult, out_path: str | Path | None) -> None:
    data = result.as_dict()
    text = json.dumps(data, ensure_ascii=False, indent=2)

    if out_path is None or str(out_path) == "-":
        try:
            print(text)
        except BrokenPipeError:
            return
        return

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
