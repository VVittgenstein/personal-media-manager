from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
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

    @property
    def media_root(self) -> Path:
        return self._sandbox.media_root

    def delete(self, request: dict[str, Any]) -> FileOpsResult:
        rel_path = request.get("path")
        if not isinstance(rel_path, str):
            raise FileOpsError("INVALID_REQUEST", "missing or invalid 'path' (string required)")

        rel_path = normalize_rel_path(rel_path)
        if rel_path == "":
            raise FileOpsError("ROOT_FORBIDDEN", "refusing to delete MediaRoot root", http_status=403)

        try:
            abs_path = self._sandbox.to_abs_path(rel_path)
        except SandboxViolation as exc:
            raise FileOpsError("SANDBOX_VIOLATION", str(exc), http_status=400) from exc

        info = _file_info(abs_path)

        token_payload = {
            "op": "delete",
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
                    "confirm_required": True,
                    "preview": {
                        "src_rel_path": rel_path,
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

        log_entry: OperationLogEntry | None = None
        try:
            if info["is_dir"]:
                shutil.rmtree(abs_path)
            else:
                abs_path.unlink()
            log_entry = self._log_store.record(
                op="delete",
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
                    "executed": True,
                    "src_rel_path": rel_path,
                    "dst_rel_path": None,
                    "log": log_entry.as_dict(),
                },
            )
        except Exception as exc:
            log_entry = self._log_store.record(
                op="delete",
                src_rel_path=rel_path,
                dst_rel_path=None,
                is_dir=bool(info["is_dir"]),
                success=False,
                error=str(exc),
            )
            raise FileOpsError("DELETE_FAILED", str(exc), http_status=500) from exc

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
