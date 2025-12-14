from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.scanner.sandbox import MediaRootSandbox, SandboxViolation, normalize_rel_path

from .operation_log import OperationLogEntry, OperationLogStore


class FileOpsError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _mtime_ms_from_stat(st: os.stat_result) -> int | None:
    try:
        return int(st.st_mtime * 1000)
    except Exception:
        return None


def _file_info(abs_path: Path) -> dict[str, Any]:
    try:
        st = os.stat(abs_path, follow_symlinks=False)
    except OSError as exc:
        raise FileOpsError("STAT_FAILED", f"cannot stat path: {exc}", http_status=404) from exc

    is_dir = os.path.isdir(abs_path)
    size_bytes = None if is_dir else int(getattr(st, "st_size", 0))
    return {
        "is_dir": bool(is_dir),
        "size_bytes": size_bytes,
        "mtime_ms": _mtime_ms_from_stat(st),
    }


def _canonical_json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac_token(*, secret: bytes, payload: dict[str, Any]) -> str:
    digest = hmac.new(secret, _canonical_json(payload), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _split_parent(rel_path: str) -> tuple[str, str]:
    head, _sep, tail = rel_path.rpartition("/")
    return head, tail


def _is_subpath(*, parent_abs: Path, child_abs: Path) -> bool:
    parent_norm = os.path.normcase(os.path.abspath(os.fspath(parent_abs)))
    child_norm = os.path.normcase(os.path.abspath(os.fspath(child_abs)))
    try:
        return os.path.commonpath([parent_norm, child_norm]) == parent_norm
    except ValueError:
        return False


TRASH_DIR_NAME = "_trash"
TRASH_META_FILENAME = "meta.json"
TRASH_RETENTION_DAYS = 10
TRASH_CLEANUP_THROTTLE_SEC = 60 * 60
_REPARSE_ATTR = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


def _is_reparse_point(st: os.stat_result | None) -> bool:
    if st is None:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_ATTR)


def _safe_remove_path(abs_path: Path) -> None:
    st = os.stat(abs_path, follow_symlinks=False)
    if os.path.islink(abs_path) or _is_reparse_point(st):
        try:
            abs_path.unlink()
        except IsADirectoryError:
            abs_path.rmdir()
        return

    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(abs_path)
    else:
        abs_path.unlink()


@dataclass(frozen=True)
class FileOpsResult:
    http_status: int
    payload: dict[str, Any]


class FileOpsService:
    def __init__(
        self,
        *,
        media_root: Path,
        log_store: OperationLogStore,
        confirm_secret: bytes,
    ) -> None:
        self._sandbox = MediaRootSandbox(media_root)
        self._log_store = log_store
        self._confirm_secret = confirm_secret
        self._last_trash_cleanup_monotonic_s = 0.0
        self._ensure_trash_dir()
        self._maybe_cleanup_trash(force=True)

    @property
    def media_root(self) -> Path:
        return self._sandbox.media_root

    def _ensure_trash_dir(self) -> Path:
        trash_rel = TRASH_DIR_NAME
        trash_candidate = self.media_root / trash_rel
        if trash_candidate.exists():
            try:
                checked = self._sandbox.to_abs_path(trash_rel)
            except SandboxViolation as exc:
                raise FileOpsError("TRASH_SANDBOX_VIOLATION", str(exc), http_status=400) from exc
            if not checked.is_dir():
                raise FileOpsError("TRASH_NOT_DIR", f"{trash_rel} exists but is not a directory", http_status=409)
            return checked

        try:
            trash_candidate.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise FileOpsError("TRASH_CREATE_FAILED", f"failed to create {trash_rel}: {exc}", http_status=500) from exc

        try:
            checked = self._sandbox.to_abs_path(trash_rel)
        except SandboxViolation as exc:
            raise FileOpsError("TRASH_SANDBOX_VIOLATION", str(exc), http_status=400) from exc
        return checked

    def _trash_entry_dir_rel(self, *, token: str) -> str:
        return f"{TRASH_DIR_NAME}/{token}"

    def _trash_entry_meta_abs(self, *, entry_dir_abs: Path) -> Path:
        return entry_dir_abs / TRASH_META_FILENAME

    def _write_json_file(self, abs_path: Path, data: dict[str, Any]) -> None:
        abs_path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    def _read_trash_meta(self, *, entry_dir_abs: Path) -> dict[str, Any]:
        meta_abs = self._trash_entry_meta_abs(entry_dir_abs=entry_dir_abs)
        try:
            raw = meta_abs.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileOpsError("TRASH_META_MISSING", "trash entry metadata is missing", http_status=404) from exc
        except OSError as exc:
            raise FileOpsError("TRASH_META_READ_FAILED", f"cannot read trash metadata: {exc}", http_status=500) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FileOpsError("TRASH_META_INVALID", f"invalid trash metadata JSON: {exc}", http_status=500) from exc
        if not isinstance(data, dict):
            raise FileOpsError("TRASH_META_INVALID", "trash metadata must be a JSON object", http_status=500)
        return data

    def _maybe_cleanup_trash(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_trash_cleanup_monotonic_s < TRASH_CLEANUP_THROTTLE_SEC:
            return
        self._last_trash_cleanup_monotonic_s = now
        try:
            self._cleanup_trash(retention_days=TRASH_RETENTION_DAYS)
        except Exception:
            # Cleanup failures must not break the main app flow; best-effort only.
            return

    def _cleanup_trash(self, *, retention_days: int) -> None:
        retention_ms = int(retention_days) * 24 * 60 * 60 * 1000
        now_ms = int(time.time() * 1000)
        trash_abs = self._ensure_trash_dir()

        try:
            entries = list(trash_abs.iterdir())
        except FileNotFoundError:
            return
        except OSError:
            return

        for entry in entries:
            try:
                st = os.stat(entry, follow_symlinks=False)
                entry_mtime_ms = _mtime_ms_from_stat(st) or now_ms
            except OSError:
                continue

            archived_at_ms = entry_mtime_ms
            meta = None
            is_dir = stat.S_ISDIR(st.st_mode) and not os.path.islink(entry) and not _is_reparse_point(st)
            if is_dir:
                try:
                    meta = self._read_trash_meta(entry_dir_abs=entry)
                except FileOpsError:
                    meta = None
                else:
                    try:
                        archived_at_ms = int(meta.get("archived_at_ms") or archived_at_ms)
                    except Exception:
                        archived_at_ms = archived_at_ms

            if now_ms - archived_at_ms <= retention_ms:
                continue

            entry_rel_path = f"{TRASH_DIR_NAME}/{entry.name}"
            try:
                _safe_remove_path(entry)

                if meta and isinstance(meta.get("dst_rel_path"), str) and meta.get("dst_rel_path"):
                    log_src_rel = str(meta["dst_rel_path"])
                else:
                    log_src_rel = entry_rel_path

                self._log_store.record(
                    op="purge",
                    src_rel_path=log_src_rel,
                    dst_rel_path=None,
                    is_dir=bool(is_dir),
                    success=True,
                    error=None,
                )
            except Exception as exc:
                self._log_store.record(
                    op="purge",
                    src_rel_path=entry_rel_path,
                    dst_rel_path=None,
                    is_dir=bool(is_dir),
                    success=False,
                    error=str(exc),
                )
                continue

    def delete(self, request: dict[str, Any]) -> FileOpsResult:
        rel_path = request.get("path")
        if not isinstance(rel_path, str):
            raise FileOpsError("INVALID_REQUEST", "missing or invalid 'path' (string required)")

        rel_path = normalize_rel_path(rel_path)
        if rel_path == "":
            raise FileOpsError("ROOT_FORBIDDEN", "refusing to delete MediaRoot root", http_status=403)
        if rel_path == TRASH_DIR_NAME:
            raise FileOpsError(
                "TRASH_ROOT_FORBIDDEN",
                "refusing to delete trash root (use /api/trash/empty instead)",
                http_status=403,
            )

        self._maybe_cleanup_trash(force=False)

        if rel_path.startswith(f"{TRASH_DIR_NAME}/"):
            return self._purge_from_trash(request, rel_path=rel_path)
        return self._archive_to_trash(request, rel_path=rel_path)

    def _archive_to_trash(self, request: dict[str, Any], *, rel_path: str) -> FileOpsResult:
        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        info = _file_info(abs_path)

        token_payload = {
            "op": "archive",
            "src_rel_path": rel_path,
            "dst_rel_path": None,
            "is_dir": info["is_dir"],
            "size_bytes": info["size_bytes"],
            "mtime_ms": info["mtime_ms"],
        }
        expected_token = _hmac_token(secret=self._confirm_secret, payload=token_payload)
        base_name = rel_path.rsplit("/", 1)[-1]
        trash_entry_rel = self._trash_entry_dir_rel(token=expected_token)
        dst_rel_path = f"{trash_entry_rel}/{base_name}"

        confirm = bool(request.get("confirm", False))
        token = request.get("confirm_token")
        if not confirm:
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "delete",
                    "delete_mode": "archive",
                    "confirm_required": True,
                    "preview": {
                        "src_rel_path": rel_path,
                        "dst_rel_path": dst_rel_path,
                        **info,
                    },
                    "confirm_token": expected_token,
                },
            )

        if not isinstance(token, str) or not token:
            raise FileOpsError("CONFIRM_TOKEN_REQUIRED", "missing 'confirm_token' for confirmed operation")
        if token != expected_token:
            raise FileOpsError(
                "STALE_CONFIRM_TOKEN",
                "confirm_token does not match current file state; re-fetch preview and confirm again",
                http_status=409,
            )

        self._ensure_trash_dir()
        try:
            entry_dir_abs = self._sandbox.to_abs_path_allow_missing(trash_entry_rel)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        if entry_dir_abs.exists():
            raise FileOpsError("TRASH_ENTRY_EXISTS", "trash entry already exists; retry delete preview", http_status=409)

        try:
            entry_dir_abs.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            raise FileOpsError("TRASH_CREATE_FAILED", f"cannot create trash entry: {exc}", http_status=500) from exc

        abs_dst = entry_dir_abs / base_name
        dst_rel_path = f"{TRASH_DIR_NAME}/{entry_dir_abs.name}/{base_name}"
        meta = {
            "version": 1,
            "archived_at_ms": int(time.time() * 1000),
            "src_rel_path": rel_path,
            "dst_rel_path": dst_rel_path,
            "payload_name": base_name,
            "is_dir": bool(info["is_dir"]),
            "size_bytes": info["size_bytes"],
            "mtime_ms": info["mtime_ms"],
        }

        try:
            try:
                abs_path.rename(abs_dst)
            except OSError:
                shutil.move(os.fspath(abs_path), os.fspath(abs_dst))

            self._write_json_file(self._trash_entry_meta_abs(entry_dir_abs=entry_dir_abs), meta)

            log_entry = self._log_store.record(
                op="archive",
                src_rel_path=rel_path,
                dst_rel_path=dst_rel_path,
                is_dir=bool(info["is_dir"]),
                success=True,
                error=None,
            )
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "delete",
                    "delete_mode": "archive",
                    "executed": True,
                    "src_rel_path": rel_path,
                    "dst_rel_path": dst_rel_path,
                    "log": log_entry.as_dict(),
                },
            )
        except Exception as exc:
            self._log_store.record(
                op="archive",
                src_rel_path=rel_path,
                dst_rel_path=dst_rel_path,
                is_dir=bool(info["is_dir"]),
                success=False,
                error=str(exc),
            )
            try:
                if entry_dir_abs.exists():
                    shutil.rmtree(entry_dir_abs)
            except Exception:
                pass
            raise FileOpsError("ARCHIVE_FAILED", str(exc), http_status=500) from exc

    def _purge_from_trash(self, request: dict[str, Any], *, rel_path: str) -> FileOpsResult:
        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        if rel_path == TRASH_DIR_NAME:
            raise FileOpsError(
                "TRASH_ROOT_FORBIDDEN",
                "refusing to delete trash root (use /api/trash/empty instead)",
                http_status=403,
            )

        info = _file_info(abs_path)

        token_payload = {
            "op": "purge",
            "src_rel_path": rel_path,
            "dst_rel_path": None,
            "is_dir": info["is_dir"],
            "size_bytes": info["size_bytes"],
            "mtime_ms": info["mtime_ms"],
        }
        expected_token = _hmac_token(secret=self._confirm_secret, payload=token_payload)

        confirm = bool(request.get("confirm", False))
        token = request.get("confirm_token")
        if not confirm:
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "delete",
                    "delete_mode": "purge",
                    "confirm_required": True,
                    "preview": {
                        "src_rel_path": rel_path,
                        "dst_rel_path": None,
                        **info,
                    },
                    "confirm_token": expected_token,
                },
            )

        if not isinstance(token, str) or not token:
            raise FileOpsError("CONFIRM_TOKEN_REQUIRED", "missing 'confirm_token' for confirmed operation")
        if token != expected_token:
            raise FileOpsError(
                "STALE_CONFIRM_TOKEN",
                "confirm_token does not match current file state; re-fetch preview and confirm again",
                http_status=409,
            )

        try:
            if info["is_dir"]:
                shutil.rmtree(abs_path)
            else:
                abs_path.unlink()
            log_entry = self._log_store.record(
                op="purge",
                src_rel_path=rel_path,
                dst_rel_path=None,
                is_dir=bool(info["is_dir"]),
                success=True,
                error=None,
            )
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "delete",
                    "delete_mode": "purge",
                    "executed": True,
                    "src_rel_path": rel_path,
                    "dst_rel_path": None,
                    "log": log_entry.as_dict(),
                },
            )
        except Exception as exc:
            self._log_store.record(
                op="purge",
                src_rel_path=rel_path,
                dst_rel_path=None,
                is_dir=bool(info["is_dir"]),
                success=False,
                error=str(exc),
            )
            raise FileOpsError("PURGE_FAILED", str(exc), http_status=500) from exc

    def trash_restore(self, request: dict[str, Any]) -> FileOpsResult:
        rel_path = request.get("path")
        if not isinstance(rel_path, str):
            raise FileOpsError("INVALID_REQUEST", "missing or invalid 'path' (string required)")

        rel_path = normalize_rel_path(rel_path)
        if rel_path == "":
            raise FileOpsError("INVALID_PATH", "path must not be MediaRoot root", http_status=400)
        if rel_path == TRASH_DIR_NAME:
            raise FileOpsError("TRASH_ROOT_FORBIDDEN", "refusing to restore trash root", http_status=400)
        if not rel_path.startswith(f"{TRASH_DIR_NAME}/"):
            raise FileOpsError("NOT_IN_TRASH", "path must be inside MediaRoot/_trash", http_status=400)

        self._maybe_cleanup_trash(force=False)

        parts = rel_path.split("/")
        if len(parts) < 2 or not parts[1]:
            raise FileOpsError("INVALID_PATH", "invalid trash path", http_status=400)

        entry_dir_rel = "/".join(parts[:2])
        try:
            entry_dir_abs = self._sandbox.to_abs_path(entry_dir_rel)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc
        if not entry_dir_abs.is_dir():
            raise FileOpsError("TRASH_ENTRY_NOT_DIR", "trash entry is not a directory", http_status=409)

        meta = self._read_trash_meta(entry_dir_abs=entry_dir_abs)
        src_original = meta.get("src_rel_path")
        payload_name = meta.get("payload_name")
        if not isinstance(src_original, str) or not src_original:
            raise FileOpsError("TRASH_META_INVALID", "trash metadata missing src_rel_path", http_status=500)
        if not isinstance(payload_name, str) or not payload_name:
            raise FileOpsError("TRASH_META_INVALID", "trash metadata missing payload_name", http_status=500)
        if normalize_rel_path(src_original).startswith(f"{TRASH_DIR_NAME}/"):
            raise FileOpsError("TRASH_META_INVALID", "trash metadata src_rel_path points into _trash", http_status=500)

        payload_abs = entry_dir_abs / payload_name
        payload_rel = f"{entry_dir_rel}/{payload_name}"
        info = _file_info(payload_abs)

        dst_rel_path = normalize_rel_path(src_original)
        dst_parent_rel, dst_name = _split_parent(dst_rel_path)
        if dst_name == "":
            raise FileOpsError("INVALID_PATH", "invalid restore destination path", http_status=500)

        try:
            dst_parent_abs = self._sandbox.to_abs_path_allow_missing(dst_parent_rel)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        abs_dst = (dst_parent_abs if dst_parent_rel != "" else self.media_root) / dst_name
        if abs_dst.exists():
            raise FileOpsError("DST_EXISTS", "restore destination already exists", http_status=409)

        token_payload = {
            "op": "restore",
            "src_rel_path": payload_rel,
            "dst_rel_path": dst_rel_path,
            "is_dir": info["is_dir"],
            "size_bytes": info["size_bytes"],
            "mtime_ms": info["mtime_ms"],
        }
        expected_token = _hmac_token(secret=self._confirm_secret, payload=token_payload)

        confirm = bool(request.get("confirm", False))
        token = request.get("confirm_token")
        if not confirm:
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "restore",
                    "confirm_required": True,
                    "preview": {
                        "src_rel_path": payload_rel,
                        "dst_rel_path": dst_rel_path,
                        **info,
                    },
                    "confirm_token": expected_token,
                },
            )

        if not isinstance(token, str) or not token:
            raise FileOpsError("CONFIRM_TOKEN_REQUIRED", "missing 'confirm_token' for confirmed operation")
        if token != expected_token:
            raise FileOpsError(
                "STALE_CONFIRM_TOKEN",
                "confirm_token does not match current file state; re-fetch preview and confirm again",
                http_status=409,
            )

        try:
            if dst_parent_rel != "":
                abs_parent_to_create = self.media_root.joinpath(*dst_parent_rel.split("/"))
                abs_parent_to_create.mkdir(parents=True, exist_ok=True)

            if dst_parent_rel != "":
                try:
                    dst_parent_abs_checked = self._sandbox.to_abs_path(dst_parent_rel)
                except SandboxViolation as exc:
                    raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc
            else:
                dst_parent_abs_checked = self.media_root

            abs_dst = dst_parent_abs_checked / dst_name
            if abs_dst.exists():
                raise FileOpsError("DST_EXISTS", "restore destination already exists", http_status=409)

            try:
                payload_abs.rename(abs_dst)
            except OSError:
                shutil.move(os.fspath(payload_abs), os.fspath(abs_dst))

            try:
                meta_abs = self._trash_entry_meta_abs(entry_dir_abs=entry_dir_abs)
                meta_abs.unlink(missing_ok=True)
                entry_dir_abs.rmdir()
            except Exception:
                pass

            log_entry = self._log_store.record(
                op="restore",
                src_rel_path=payload_rel,
                dst_rel_path=dst_rel_path,
                is_dir=bool(info["is_dir"]),
                success=True,
                error=None,
            )
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "restore",
                    "executed": True,
                    "src_rel_path": payload_rel,
                    "dst_rel_path": dst_rel_path,
                    "log": log_entry.as_dict(),
                },
            )
        except FileOpsError:
            raise
        except Exception as exc:
            self._log_store.record(
                op="restore",
                src_rel_path=payload_rel,
                dst_rel_path=dst_rel_path,
                is_dir=bool(info["is_dir"]),
                success=False,
                error=str(exc),
            )
            raise FileOpsError("RESTORE_FAILED", str(exc), http_status=500) from exc

    def trash_empty(self, request: dict[str, Any]) -> FileOpsResult:
        self._maybe_cleanup_trash(force=False)
        trash_abs = self._ensure_trash_dir()

        try:
            entries = sorted([p.name for p in trash_abs.iterdir()])
        except FileNotFoundError:
            entries = []
        except OSError as exc:
            raise FileOpsError("TRASH_LIST_FAILED", f"cannot list trash: {exc}", http_status=500) from exc

        try:
            st = os.stat(trash_abs, follow_symlinks=False)
            trash_mtime_ms = _mtime_ms_from_stat(st)
        except OSError:
            trash_mtime_ms = None

        entries_blob = "\n".join(entries).encode("utf-8")
        entries_sha1 = hashlib.sha1(entries_blob).hexdigest()
        token_payload = {
            "op": "trash_empty",
            "entries_sha1": entries_sha1,
            "count": len(entries),
            "trash_mtime_ms": trash_mtime_ms,
        }
        expected_token = _hmac_token(secret=self._confirm_secret, payload=token_payload)

        confirm = bool(request.get("confirm", False))
        token = request.get("confirm_token")
        if not confirm:
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "trash_empty",
                    "confirm_required": True,
                    "preview": {
                        "trash_rel_path": TRASH_DIR_NAME,
                        "count": len(entries),
                        "retention_days": TRASH_RETENTION_DAYS,
                    },
                    "confirm_token": expected_token,
                },
            )

        if not isinstance(token, str) or not token:
            raise FileOpsError("CONFIRM_TOKEN_REQUIRED", "missing 'confirm_token' for confirmed operation")
        if token != expected_token:
            raise FileOpsError(
                "STALE_CONFIRM_TOKEN",
                "confirm_token does not match current trash state; re-fetch preview and confirm again",
                http_status=409,
            )

        removed = 0
        try:
            for name in entries:
                abs_entry = trash_abs / name
                try:
                    _safe_remove_path(abs_entry)
                    removed += 1
                except FileNotFoundError:
                    continue

            log_entry = self._log_store.record(
                op="purge",
                src_rel_path=TRASH_DIR_NAME,
                dst_rel_path=None,
                is_dir=True,
                success=True,
                error=None,
            )
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "trash_empty",
                    "executed": True,
                    "removed": removed,
                    "log": log_entry.as_dict(),
                },
            )
        except Exception as exc:
            self._log_store.record(
                op="purge",
                src_rel_path=TRASH_DIR_NAME,
                dst_rel_path=None,
                is_dir=True,
                success=False,
                error=str(exc),
            )
            raise FileOpsError("TRASH_EMPTY_FAILED", str(exc), http_status=500) from exc

    def move(self, request: dict[str, Any]) -> FileOpsResult:
        src = request.get("src")
        dst = request.get("dst")
        if not isinstance(src, str) or not isinstance(dst, str):
            raise FileOpsError("INVALID_REQUEST", "missing or invalid 'src'/'dst' (string required)")

        src = normalize_rel_path(src)
        dst = normalize_rel_path(dst)
        if src == "" or dst == "":
            raise FileOpsError("INVALID_PATH", "src/dst must not be MediaRoot root", http_status=400)

        try:
            abs_src = self._sandbox.to_abs_path(src)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        src_info = _file_info(abs_src)

        dst_parent_rel, dst_name = _split_parent(dst)
        if dst_name == "":
            raise FileOpsError("INVALID_PATH", "dst must not be a directory path", http_status=400)

        if src_info["is_dir"]:
            abs_dst_candidate = self.media_root.joinpath(*dst.split("/"))
            if _is_subpath(parent_abs=abs_src, child_abs=abs_dst_candidate) and abs_src != abs_dst_candidate:
                raise FileOpsError("INVALID_MOVE", "refusing to move a directory into itself", http_status=400)

        create_parents = bool(request.get("create_parents", False))
        try:
            dst_parent_abs_candidate = self._sandbox.to_abs_path_allow_missing(dst_parent_rel)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        if dst_parent_rel != "" and dst_parent_abs_candidate.exists() and not dst_parent_abs_candidate.is_dir():
            raise FileOpsError("DST_PARENT_NOT_DIR", "destination parent is not a directory", http_status=409)

        if dst_parent_rel != "" and not dst_parent_abs_candidate.exists() and not create_parents:
            raise FileOpsError(
                "DST_PARENT_MISSING",
                "destination parent directory does not exist (set create_parents=true to create it)",
                http_status=409,
            )

        abs_dst_candidate = dst_parent_abs_candidate / dst_name
        if abs_dst_candidate.exists():
            raise FileOpsError("DST_EXISTS", "destination already exists", http_status=409)

        token_payload = {
            "op": "move",
            "src_rel_path": src,
            "dst_rel_path": dst,
            "is_dir": src_info["is_dir"],
            "size_bytes": src_info["size_bytes"],
            "mtime_ms": src_info["mtime_ms"],
            "create_parents": bool(create_parents),
        }
        expected_token = _hmac_token(secret=self._confirm_secret, payload=token_payload)

        confirm = bool(request.get("confirm", False))
        token = request.get("confirm_token")
        if not confirm:
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "move",
                    "confirm_required": True,
                    "preview": {
                        "src_rel_path": src,
                        "dst_rel_path": dst,
                        "create_parents": bool(create_parents),
                        **src_info,
                    },
                    "confirm_token": expected_token,
                },
            )

        if not isinstance(token, str) or not token:
            raise FileOpsError("CONFIRM_TOKEN_REQUIRED", "missing 'confirm_token' for confirmed operation")
        if token != expected_token:
            raise FileOpsError(
                "STALE_CONFIRM_TOKEN",
                "confirm_token does not match current file state; re-fetch preview and confirm again",
                http_status=409,
            )

        try:
            if create_parents and dst_parent_rel != "":
                abs_parent_to_create = self.media_root.joinpath(*dst_parent_rel.split("/"))
                abs_parent_to_create.mkdir(parents=True, exist_ok=True)

            if dst_parent_rel != "":
                try:
                    dst_parent_abs_checked = self._sandbox.to_abs_path(dst_parent_rel)
                except SandboxViolation as exc:
                    raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc
            else:
                dst_parent_abs_checked = self.media_root

            abs_dst = dst_parent_abs_checked / dst_name
            if abs_dst.exists():
                raise FileOpsError("DST_EXISTS", "destination already exists", http_status=409)

            try:
                abs_src.rename(abs_dst)
            except OSError:
                shutil.move(os.fspath(abs_src), os.fspath(abs_dst))

            log_entry = self._log_store.record(
                op="move",
                src_rel_path=src,
                dst_rel_path=dst,
                is_dir=bool(src_info["is_dir"]),
                success=True,
                error=None,
            )
            return FileOpsResult(
                http_status=200,
                payload={
                    "ok": True,
                    "action": "move",
                    "executed": True,
                    "src_rel_path": src,
                    "dst_rel_path": dst,
                    "log": log_entry.as_dict(),
                },
            )
        except Exception as exc:
            self._log_store.record(
                op="move",
                src_rel_path=src,
                dst_rel_path=dst,
                is_dir=bool(src_info["is_dir"]),
                success=False,
                error=str(exc),
            )
            raise FileOpsError("MOVE_FAILED", str(exc), http_status=500) from exc
