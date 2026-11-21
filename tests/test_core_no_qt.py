"""Ensure the core library never pulls in Qt."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ssnow_core"
FORBIDDEN = ("PySide6", "PyQt6", "QtWebEngine", "PyQt5")


def test_core_has_no_qt_imports():
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text()
        for token in FORBIDDEN:
            assert token not in text, f"{path} references {token}"
