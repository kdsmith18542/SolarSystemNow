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


def test_alert_preferences_gate_notifications(tmp_path, monkeypatch):
    """Desktop alert toggles suppress notification creation per category."""
    from datetime import datetime, timezone

    from PySide6.QtCore import QSettings

    from ssnow_core.models import Event, Observation

    monkeypatch.setenv("SSNOW_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    settings = QSettings("ssnow", "ssnow")
    originals = {k: settings.value(k, None) for k in ("alerts_enabled", "alerts_spacewx", "alerts_quakes", "alerts_neo")}
    try:
        window = MainWindow()
        try:
            now = datetime.now(timezone.utc)
            window.store.upsert_observations(
                [Observation(source="swpc", series="swpc:kp", ts=now, value=7.0, unit="Kp")]
            )
            window.store.upsert_events(
                [
                    Event(
                        id="test:quake-m6", source="usgs", upstream_id="x", category="earthquake",
                        title="M 6.5 test quake", occurred_at=now, latitude=1.0, longitude=2.0,
                        magnitude=6.5, magnitude_unit="M",
                    )
                ]
            )

            def generated() -> list[str]:
                with window.store.transaction() as c:
                    return [r[0] for r in c.execute("SELECT id FROM notifications").fetchall()]

            def clear() -> None:
                with window.store.transaction() as c:
                    c.execute("DELETE FROM notifications")

            for key in ("alerts_enabled", "alerts_spacewx", "alerts_quakes", "alerts_neo"):
                settings.setValue(key, True)

            window._check_and_notify_alerts()
            ids = generated()
            assert any(i.startswith("kp-") for i in ids)
            assert any(i.startswith("quake-") for i in ids)

            # Master switch off: nothing is generated.
            clear()
            settings.setValue("alerts_enabled", False)
            window._check_and_notify_alerts()
            assert generated() == []

            # Quake category off: space weather still fires, quake does not.
            clear()
            settings.setValue("alerts_enabled", True)
            settings.setValue("alerts_quakes", False)
            window._check_and_notify_alerts()
            ids = generated()
            assert any(i.startswith("kp-") for i in ids)
            assert not any(i.startswith("quake-") for i in ids)
        finally:
            window.close()
            app.processEvents()
    finally:
        for key, value in originals.items():
            if value is None:
                settings.remove(key)
            else:
                settings.setValue(key, value)
