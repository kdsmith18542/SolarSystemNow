"""GUI smoke test (offscreen platform)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ssnow_desktop.main_window import MainWindow  # noqa: E402


def test_gui_constructs(tmp_path, monkeypatch):
    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.close()
    app.processEvents()
