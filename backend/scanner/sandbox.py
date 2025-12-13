from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


class SandboxViolation(ValueError):
    pass


_REPARSE_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _is_reparse_point(st: os.stat_result | None) -> bool:
    if st is None:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_ATTR)


def _norm_case_abs(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_within_root(*, root: Path, path: Path) -> bool:
    root_abs = _norm_case_abs(root)
    path_abs = _norm_case_abs(path)
    try:
        return os.path.commonpath([root_abs, path_abs]) == root_abs
    except ValueError:
        return False


_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def normalize_rel_path(rel_path: str) -> str:
    rel_path = rel_path.strip()
    if rel_path in {"", "."}:
        return ""

    rel_path = rel_path.replace("\\", "/")

    if rel_path.startswith("/"):
        raise SandboxViolation("rel_path must not be absolute")
    if rel_path.startswith("//"):
        raise SandboxViolation("rel_path must not be a UNC path")
    if _WIN_DRIVE_RE.match(rel_path):
        raise SandboxViolation("rel_path must not include a drive letter")

    parts = [p for p in rel_path.split("/") if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise SandboxViolation("rel_path must not contain '..'")
    normalized = "/".join(parts)
    if normalized in {"", "."}:
        return ""
    return normalized


@dataclass(frozen=True)
class MediaRootSandbox:
    media_root: Path

    def __post_init__(self) -> None:
        root = Path(self.media_root)
        if not root.exists():
            raise SandboxViolation(f"MediaRoot does not exist: {root}")
        if not root.is_dir():
            raise SandboxViolation(f"MediaRoot is not a directory: {root}")

        object.__setattr__(self, "media_root", root)

    @property
    def _root_abs(self) -> Path:
        return Path(_norm_case_abs(self.media_root))

    def to_abs_path(self, rel_path: str) -> Path:
        rel_path = normalize_rel_path(rel_path)
        if rel_path == "":
            return self.media_root

        abs_path = self.media_root.joinpath(*rel_path.split("/"))
        if not _is_within_root(root=self.media_root, path=abs_path):
            raise SandboxViolation("path escapes MediaRoot by string prefix check")

        self._reject_reparse_traversal(abs_path)
        return abs_path

    def to_abs_path_allow_missing(self, rel_path: str) -> Path:
        """Convert a normalized relative path to an absolute path within MediaRoot.

        Unlike `to_abs_path`, this method allows the final path (and/or deeper
        segments) to be missing on disk. It still validates that any existing
        prefix segments do not traverse symlinks/reparse points.
        """

        rel_path = normalize_rel_path(rel_path)
        if rel_path == "":
            return self.media_root

        abs_path = self.media_root.joinpath(*rel_path.split("/"))
        if not _is_within_root(root=self.media_root, path=abs_path):
            raise SandboxViolation("path escapes MediaRoot by string prefix check")

        self._reject_reparse_traversal_allow_missing(abs_path)
        return abs_path

    def _reject_reparse_traversal(self, abs_path: Path) -> None:
        root_abs = self._root_abs
        target_abs = Path(_norm_case_abs(abs_path))

        try:
            rel = target_abs.relative_to(root_abs)
        except ValueError as exc:
            raise SandboxViolation("path escapes MediaRoot") from exc

        current = root_abs
        for part in rel.parts:
            current = current / part
            try:
                st = os.stat(current, follow_symlinks=False)
            except OSError as exc:
                raise SandboxViolation(f"cannot stat path segment: {current}") from exc

            if os.path.islink(current) or _is_reparse_point(st):
                raise SandboxViolation(f"reparse/symlink segment is not allowed: {current}")

        try:
            resolved = abs_path.resolve(strict=True)
        except OSError:
            return

        if not _is_within_root(root=self.media_root, path=resolved):
            raise SandboxViolation("path resolves outside MediaRoot")

    def _reject_reparse_traversal_allow_missing(self, abs_path: Path) -> None:
        root_abs = self._root_abs
        target_abs = Path(_norm_case_abs(abs_path))

        try:
            rel = target_abs.relative_to(root_abs)
        except ValueError as exc:
            raise SandboxViolation("path escapes MediaRoot") from exc

        current = root_abs
        for part in rel.parts:
            current = current / part
            try:
                st = os.stat(current, follow_symlinks=False)
            except FileNotFoundError:
                break
            except OSError as exc:
                raise SandboxViolation(f"cannot stat path segment: {current}") from exc

            if os.path.islink(current) or _is_reparse_point(st):
                raise SandboxViolation(f"reparse/symlink segment is not allowed: {current}")

        try:
            resolved = abs_path.resolve(strict=True)
        except OSError:
            return

        if not _is_within_root(root=self.media_root, path=resolved):
            raise SandboxViolation("path resolves outside MediaRoot")
