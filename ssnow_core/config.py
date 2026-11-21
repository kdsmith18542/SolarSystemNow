"""Runtime path configuration (XDG-compliant, overridable)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ss-now"
SCHEMA_VERSION = 1


def env_dir(name: str, default: str) -> Path:
    base = os.environ.get(name)
    if base:
        return Path(base)
    return Path(default)


def data_dir() -> Path:
    return env_dir(
        "SSNOW_DATA_DIR",
        str((Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_NAME)),
    )


def config_dir() -> Path:
    return env_dir("SSNOW_CONFIG_DIR", str(Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME))


def cache_dir() -> Path:
    return env_dir("SSNOW_CACHE_DIR", str(Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME))


def ensure_dirs() -> None:
    for directory in (data_dir(), config_dir(), cache_dir()):
        directory.mkdir(parents=True, exist_ok=True)


def default_db_path() -> Path:
    return data_dir() / "ssnow.sqlite"


def default_snapshot_dir() -> Path:
    return data_dir() / "snapshots"


def default_asset_dir() -> Path:
    return cache_dir() / "assets"


def default_ephemeris_path() -> Path:
    return data_dir() / "de421.bsp"
