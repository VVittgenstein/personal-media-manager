from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BackendConfig:
    media_root: str | None = None
    host: str | None = None
    port: int | None = None


def default_backend_config_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "config" / "backend.json"


def _get_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{key} must be a string")
        value = value.strip()
        if not value:
            return None
        return value
    return None


def _get_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key not in data:
            continue
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{key} must be an integer")
        if not 0 <= value <= 65535:
            raise ValueError(f"{key} must be between 0 and 65535")
        return value
    return None


def load_backend_config(path: str | Path | None = None) -> BackendConfig:
    """Load backend runtime config.

    If path is None, tries default path (config/backend.json) and returns empty config
    when not present.
    """

    if path is None:
        default_path = default_backend_config_path()
        if not default_path.exists():
            return BackendConfig()
        path = default_path

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"backend config not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("backend config must be a JSON object")

    media_root = _get_str(data, "media_root", "mediaRoot", "MediaRoot")
    host = _get_str(data, "host", "bind_host", "bindHost")
    port = _get_int(data, "port")

    return BackendConfig(media_root=media_root, host=host, port=port)

