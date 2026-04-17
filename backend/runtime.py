from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def data_dir() -> Path:
    return _path_from_env("MODEL_COUNCIL_DATA_DIR", APP_ROOT / "data")


def settings_path() -> Path:
    return data_dir() / "settings.json"


def conversations_dir() -> Path:
    return data_dir() / "conversations"


def debug_dir() -> Path:
    return data_dir() / "debug"


def frontend_dist_dir() -> Path:
    return _path_from_env("MODEL_COUNCIL_FRONTEND_DIST", APP_ROOT / "frontend" / "dist")


def host() -> str:
    return os.getenv("MODEL_COUNCIL_HOST", "127.0.0.1")


def port() -> int:
    raw = os.getenv("MODEL_COUNCIL_PORT", "8000")
    try:
        return int(raw)
    except ValueError:
        return 8000


def desktop_mode() -> bool:
    return os.getenv("MODEL_COUNCIL_DESKTOP_MODE", "").lower() in {"1", "true", "yes", "on"}
