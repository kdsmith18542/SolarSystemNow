"""Centralized logging configuration for ssnow."""
from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path


class _UtcFormatter(logging.Formatter):
    converter = time.gmtime


def setup_logging(log_dir: Path | None = None, level: str = "INFO") -> None:
    """Configure root logger with console + rotating file handler."""
    root = logging.getLogger("ssnow")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root.handlers:
        return  # Already configured

    fmt = _UtcFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler (if log_dir provided)
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "ssnow.log",
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the ssnow namespace."""
    return logging.getLogger(f"ssnow.{name}")
