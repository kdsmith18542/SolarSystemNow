"""End-to-end remote-mode test: real ssnow-web server + RemoteStore + token + SSE.

Unlike test_remote.py (HTTP mocked), this starts the actual server process on
a free port with an isolated data directory, write-token protection enabled,
and every source pre-marked as not-due so POST /api/ingest is instant and
network-free while still broadcasting ingest_complete over SSE.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx  # noqa: E402
import pytest  # noqa: E402

from ssnow_core.remote import RemoteStore  # noqa: E402
from ssnow_core.store import Store  # noqa: E402
from ssnow_core.sources.registry import SPECS  # noqa: E402

TOKEN = "e2e-secret-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(base: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/api/health", timeout=2.0).status_code == 200:
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    raise AssertionError(f"ssnow-web did not become healthy at {base}")


def test_remote_mode_end_to_end(tmp_path):
    data = tmp_path / "data"
    config = tmp_path / "config"
    cache = tmp_path / "cache"

    # Pre-create the database and mark every source as not-yet-due so the
    # ingest triggered below never performs network fetches.
    boot = Store(db_path=data / "ssnow.sqlite", snapshots_dir=data / "snapshots", assets_dir=cache / "assets")
    now = datetime.now(timezone.utc)
    later = (now + timedelta(days=30)).isoformat()
    with boot.transaction() as c:
        for source_id in SPECS:
            c.execute(
                "INSERT OR REPLACE INTO source_state"
                "(source_id, last_attempt, last_success, last_error, consecutive_failures, next_due, records_ingested)"
                " VALUES (?, ?, ?, NULL, 0, ?, 0)",
                (source_id, now.isoformat(), now.isoformat(), later),
            )
    boot.close()

    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "SSNOW_DATA_DIR": str(data),
        "SSNOW_CONFIG_DIR": str(config),
        "SSNOW_CACHE_DIR": str(cache),
        "SSNOW_API_TOKEN": TOKEN,
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "ssnow_web.server", "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_health(base)

        # Public reads work without the token (first-run seeding gives data).
        events = httpx.get(f"{base}/api/events?limit=50", timeout=10.0)
        assert events.status_code == 200 and events.json()["count"] > 0

        # Writes require the token.
        assert httpx.post(f"{base}/api/settings", json={"retention_days": 30}, timeout=10.0).status_code == 403
        assert (
            httpx.post(
                f"{base}/api/settings", json={"retention_days": 30}, headers={"X-SSNOW-Token": "wrong"}, timeout=10.0
            ).status_code
            == 403
        )

        # RemoteStore with the token exercises the same read/write paths as the desktop.
        remote = RemoteStore(base, token=TOKEN)
        try:
            assert remote.query_events(limit=10)
            assert remote.stats()["events"] > 0
            remote.set_setting("retention_days", 30)
            assert remote.get_setting("retention_days") == 30
        finally:
            remote.close()

        # RemoteStore without the token can read but not write.
        anonymous = RemoteStore(base)
        try:
            assert anonymous.query_events(limit=5)
            with pytest.raises(Exception):
                anonymous.set_setting("retention_days", 14)
        finally:
            anonymous.close()

        # SSE: the desktop listener receives ingest_complete from the real server.
        from PySide6.QtWidgets import QApplication

        from ssnow_desktop.main_window import SseListener

        app = QApplication.instance() or QApplication([])
        received: list = []
        listener = SseListener(base)
        listener.ingest_ready.connect(received.append)
        listener.start()
        try:
            resp = httpx.post(f"{base}/api/ingest", headers={"X-SSNOW-Token": TOKEN}, timeout=60.0)
            assert resp.status_code == 200
            assert resp.json()["sources"] == []  # nothing due: no network

            deadline = time.time() + 20.0
            while not received and time.time() < deadline:
                app.processEvents()
                time.sleep(0.05)
            assert received, "SSE listener did not receive ingest_complete"
            msg = received[0]
            assert msg["type"] == "ingest_complete"
            assert msg["summary"] == {"ok": 0, "failed": 0, "events": 0, "observations": 0}
        finally:
            listener.stop()
            listener.wait(3000)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
