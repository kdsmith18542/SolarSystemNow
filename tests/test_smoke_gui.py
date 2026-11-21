"""GUI smoke test (offscreen platform)."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ssnow_desktop.main_window import MainWindow, SseListener  # noqa: E402


def test_gui_constructs(tmp_path, monkeypatch):
    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.close()
    app.processEvents()


def test_sse_listener_emits_ingest_complete(monkeypatch):
    """The remote-mode SSE listener surfaces server ingest events."""
    app = QApplication.instance() or QApplication([])

    frames = [
        'data: {"type": "connected"}',
        "",
        'data: {"type": "ingest_complete", "summary": {"ok": 1}}',
        "",
    ]

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield from frames

    def fake_stream(*a, **k):
        return FakeStream()

    monkeypatch.setattr(httpx, "stream", fake_stream)
    got: list = []
    listener = SseListener("http://localhost:8123", None)
    listener.ingest_ready.connect(got.append)
    listener.start()
    deadline = time.time() + 10
    while not got and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    listener.stop()
    listener.wait(3000)
    assert got and got[0].get("type") == "ingest_complete"
