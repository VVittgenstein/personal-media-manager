from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OperationLogEntry:
    id: str
    ts_ms: int
    op: str  # "delete" | "move" | "archive" | "restore" | "purge"
    src_rel_path: str
    dst_rel_path: str | None
    is_dir: bool
    success: bool
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts_ms": self.ts_ms,
            "op": self.op,
            "src_rel_path": self.src_rel_path,
            "dst_rel_path": self.dst_rel_path,
            "is_dir": self.is_dir,
            "success": self.success,
            "error": self.error,
        }


class OperationLogStore:
    def __init__(self, *, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, entry: OperationLogEntry) -> None:
        line = json.dumps(entry.as_dict(), ensure_ascii=False)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.write("\n")

    def record(
        self,
        *,
        op: str,
        src_rel_path: str,
        dst_rel_path: str | None,
        is_dir: bool,
        success: bool,
        error: str | None,
        ts_ms: int | None = None,
        entry_id: str | None = None,
    ) -> OperationLogEntry:
        entry = OperationLogEntry(
            id=entry_id or str(uuid.uuid4()),
            ts_ms=ts_ms or int(time.time() * 1000),
            op=op,
            src_rel_path=src_rel_path,
            dst_rel_path=dst_rel_path,
            is_dir=is_dir,
            success=success,
            error=error,
        )
        self.append(entry)
        return entry

