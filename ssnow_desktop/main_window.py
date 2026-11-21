"""Main window: navigation, ingest worker, view stack."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ssnow_core.config import ensure_dirs
from ssnow_core.logging_config import get_logger
from ssnow_core.scheduler import run_due
from ssnow_core.store import Store

from ssnow_desktop import theme

logger = get_logger("desktop")
from ssnow_desktop.views import (
    EventsView,
    MapView,
    MoonView,
    NeoView,
    NowView,
    SettingsView,
    SourcesView,
    SunView,
)

VIEW_NAMES = ["Now", "Events", "Map", "Sun", "Moon", "Asteroids", "Sources", "Settings"]
VIEW_CLASSES = [NowView, EventsView, MapView, SunView, MoonView, NeoView, SourcesView, SettingsView]


class IngestWorker(QObject):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, store) -> None:
        super().__init__()
        self.store = store
        self.remote_base: str | None = getattr(store, "base_url", None) if getattr(store, "is_remote", False) else None

    def run(self) -> None:
        import httpx

        if self.remote_base:
            # Remote mode: the server ingests; the desktop just refreshes.
            try:
                token = (getattr(self.store, "token", None) or "").strip()
                headers = {"X-SSNOW-Token": token} if token else None
                resp = httpx.post(f"{self.remote_base}/api/ingest", headers=headers, timeout=600.0)
                resp.raise_for_status()
                data = resp.json()
                summary = data.get("summary")
                if not isinstance(summary, dict):
                    sources = data.get("sources") or []
                    summary = {
                        "ok": sum(1 for s in sources if s.get("ok")),
                        "failed": sum(1 for s in sources if not s.get("ok")),
                        "events": sum(int(s.get("events") or 0) for s in sources),
                        "observations": sum(int(s.get("observations") or 0) for s in sources),
                    }
                if hasattr(self.store, "prefetch"):
                    try:
                        self.store.prefetch()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Remote prefetch after ingest failed: %s", exc)
                self.finished.emit([_RemoteReport(summary)])
            except Exception as exc:  # noqa: BLE001
                self.error.emit(str(exc))
            return
        try:
            with httpx.Client() as client:
                reports = run_due(self.store, client)
            self.finished.emit(reports)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))


class _RemoteReport:
    """Pseudo-report wrapping the server's ingest summary for _on_finished."""

    ok = True
    events: list = []
    observations: list = []

    def __init__(self, summary: dict) -> None:
        self.summary = summary


class RemotePrefetchWorker(QObject):
    """Warm RemoteStore's read cache off the UI thread."""

    finished = Signal()
    error = Signal(str)

    def __init__(self, store) -> None:
        super().__init__()
        self.store = store

    def run(self) -> None:
        try:
            self.store.prefetch()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class SseListener(QThread):
    """Background SSE subscriber for remote-server mode.

    Listens to the server's /api/stream/live feed and emits `ingest_ready`
    whenever the server finishes an ingest cycle, so the desktop refreshes
    in sync with the web client instead of waiting for its 15-minute timer.
    Reconnects with backoff on disconnect; harmless against token-gated
    servers (SSE is GET-only, always public).
    """

    ingest_ready = Signal(dict)

    def __init__(self, base_url: str, parent=None) -> None:
        super().__init__(parent)
        self._base = base_url.rstrip("/")
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: C901
        import json as _json

        import httpx

        backoff = 5.0
        while not self._stop:
            try:
                with httpx.stream("GET", f"{self._base}/api/stream/live", timeout=httpx.Timeout(60.0, connect=10.0)) as resp:
                    resp.raise_for_status()
                    backoff = 5.0
                    data_lines: list[str] = []
                    for line in resp.iter_lines():
                        if self._stop:
                            return
                        if not line:
                            if data_lines:
                                payload = "\n".join(data_lines)
                                data_lines = []
                                try:
                                    msg = _json.loads(payload)
                                except Exception:
                                    continue
                                if isinstance(msg, dict) and msg.get("type") == "ingest_complete":
                                    self.ingest_ready.emit(msg)
                            continue
                        if line.startswith("data:"):
                            data_lines.append(line[5:].strip())
                # Clean EOF: do not hot-loop against a server that closes.
                if not self._stop:
                    logger.warning("SSE stream closed; reconnecting in %.0fs", backoff)
                    for _ in range(int(backoff * 2)):
                        if self._stop:
                            return
                        self.msleep(500)
                    backoff = min(backoff * 2.0, 300.0)
            except Exception as exc:  # noqa: BLE001
                if self._stop:
                    return
                logger.warning("SSE listener disconnected (%s); retry in %.0fs", exc, backoff)
                for _ in range(int(backoff * 2)):
                    if self._stop:
                        return
                    self.msleep(500)
                backoff = min(backoff * 2.0, 300.0)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        settings = QSettings("ssnow", "ssnow")
        self.remote_mode = bool(settings.value("remote_mode", False, type=bool))
        self.remote_base = str(settings.value("remote_base_url", "http://localhost:8123") or "http://localhost:8123")
        self._remote_fallback = False
        if self.remote_mode:
            from ssnow_core.remote import RemoteStore

            try:
                import httpx

                probe = httpx.get(f"{self.remote_base.rstrip('/')}/api/health", timeout=10.0)
                probe.raise_for_status()
                self.remote_token = str(settings.value("remote_token", "") or "")
                self.store = RemoteStore(self.remote_base, token=self.remote_token or None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Remote server %s unreachable (%s); falling back to standalone", self.remote_base, exc)
                self.remote_mode = False
                self._remote_fallback = True
                self.store = Store()
                from ssnow_core.seed import seed_if_empty

                seed_if_empty(self.store)
        else:
            self.store = Store()
            logger.info("Desktop store opened: %s", self.store.db_path)
            from ssnow_core.seed import seed_if_empty

            seed_if_empty(self.store)
        title = "Solar System Now — Real Data Dashboard" + (" (remote server)" if self.remote_mode else "")
        self.setWindowTitle(title)
        self.resize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.addItems(VIEW_NAMES)
        self.sidebar.setCurrentRow(0)
        self.sidebar.setFixedWidth(210)

        self.stack = QStackedWidget()
        self.views = []
        # In remote mode, prefetch in a worker before the first expensive
        # block of view reads (constructors refresh before the window shows).
        self.store.defer_initial_refresh = bool(self.remote_mode)
        for cls in VIEW_CLASSES:
            view = cls(self.store)
            self.views.append(view)
            self.stack.addWidget(view)
        self.store.defer_initial_refresh = False

        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.currentRowChanged.connect(self._on_view_changed)

        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack)

        bar = QHBoxLayout()
        bar.setContentsMargins(10, 6, 10, 6)
        bar.setSpacing(10)
        self.refresh_btn = QPushButton("Refresh now")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.setFixedWidth(130)
        self.refresh_btn.clicked.connect(self.start_ingest)
        self.stream_btn = QPushButton("Streamer Mode (F11)")
        self.stream_btn.setFixedWidth(170)
        self.stream_btn.clicked.connect(self.toggle_streamer_mode)
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("faint")
        if self._remote_fallback:
            self.status_label.setText("Remote server unreachable — using standalone local data")
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.stream_btn)
        bar.addStretch(1)
        bar.addWidget(self.status_label)

        self._top_container = QFrame()
        self._top_container.setObjectName("toolbar")
        self._top_container.setLayout(bar)
        self._top_container.setFixedHeight(46)

        # Streamer ribbon: big, legible status strip visible only in F11 mode.
        self._stream_banner = QFrame()
        self._stream_banner.setObjectName("streamBanner")
        self._stream_banner.setFixedHeight(66)
        banner_layout = QHBoxLayout(self._stream_banner)
        banner_layout.setContentsMargins(18, 8, 18, 8)
        banner_layout.setSpacing(26)
        self._stream_fields: dict[str, tuple[QLabel, QLabel]] = {}
        for key, label in (
            ("threat", "THREAT"),
            ("kp", "Kp"),
            ("bz", "Bz"),
            ("proton", "PROTON"),
            ("dst", "Dst"),
            ("aurora", "AURORA"),
            ("clock", "UTC"),
        ):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cap = QLabel(label)
            cap.setObjectName("streamLabel")
            val = QLabel("—")
            val.setObjectName("streamValue")
            cell.addWidget(cap)
            cell.addWidget(val)
            self._stream_fields[key] = (cap, val)
            banner_layout.addLayout(cell)
        banner_layout.addStretch(1)
        self._stream_banner.hide()

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_container)
        root.addWidget(central, 1)
        root.addWidget(self._stream_banner)
        self._root = QWidget()
        self._root.setLayout(root)
        self.setCentralWidget(self._root)

        self._thread: QThread | None = None
        self._worker: IngestWorker | None = None
        self._streamer_mode: bool = False
        self._last_banner_data: float = 0.0
        self._prefetch_thread: QThread | None = None
        self._prefetch_worker: RemotePrefetchWorker | None = None
        self._prefetch_refresh_views = False
        self._prefetch_refresh_alerts = False
        self._prefetch_again = False

        # System tray icon for desktop alerts
        try:
            self._tray_icon = QSystemTrayIcon(self)
            self._tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
            menu = QMenu(self)
            show_action = menu.addAction("Show / Restore")
            show_action.triggered.connect(self._restore_window)
            refresh_action = menu.addAction("Refresh now")
            refresh_action.triggered.connect(self.start_ingest)
            menu.addSeparator()
            quit_action = menu.addAction("Quit")
            quit_action.triggered.connect(QApplication.quit)
            self._tray_icon.setContextMenu(menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_icon.show()
        except Exception:
            self._tray_icon = None

        # Application-wide shortcuts so F11/Esc work from embedded WebEngine
        # and combo popups too.
        self._fs_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fs_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._fs_shortcut.activated.connect(self.toggle_streamer_mode)
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._esc_shortcut.activated.connect(self._exit_streamer_mode)

        if self.remote_mode:
            self._start_remote_prefetch(refresh_views=True, refresh_alerts=True)
        else:
            self.views[0].refresh()
            self._check_and_notify_alerts()

        # Auto-refresh timer: runs ingestion every 15 minutes
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(15 * 60 * 1000)
        self._refresh_timer.timeout.connect(self.start_ingest)
        self._refresh_timer.start()

        # Stream ribbon clock/status ticker (only does work in streamer mode).
        self._stream_clock = QTimer(self)
        self._stream_clock.setInterval(1000)
        self._stream_clock.timeout.connect(self._tick_stream_banner)
        self._stream_clock.start()

        # Keep the remote read-through cache warm without blocking the UI.
        self._remote_prefetch_timer = QTimer(self)
        self._remote_prefetch_timer.setInterval(60_000)
        self._remote_prefetch_timer.timeout.connect(self._start_remote_prefetch)
        if self.remote_mode:
            self._remote_prefetch_timer.start()

        # Remote mode: push-refresh via SSE instead of relying solely on the
        # 15-minute timer — this desktop follows server ingest cycles live.
        self._sse: SseListener | None = None
        if self.remote_mode:
            self._sse = SseListener(self.remote_base, self)
            self._sse.ingest_ready.connect(self._on_server_ingest)
            self._sse.start()

    def _tick_stream_banner(self) -> None:
        if not self._streamer_mode:
            return
        from datetime import datetime, timezone
        import time

        clock = self._stream_fields.get("clock")
        if clock:
            clock[1].setText(datetime.now(timezone.utc).strftime("%H:%M:%S"))
        # Data reads can block in remote mode; refresh them at a sane cadence.
        if time.time() - self._last_banner_data >= 15.0:
            self._update_stream_banner()

    def _on_view_changed(self, index: int) -> None:
        try:
            self.views[index].refresh()
        except Exception as exc:
            logger.warning("View %d refresh failed: %s", index, exc)

    def show_on_map(self, latitude: float, longitude: float) -> None:
        """Center the Map tab on an event (from EventsView Show on Map)."""
        try:
            idx = VIEW_NAMES.index("Map")
        except ValueError:
            return
        try:
            self.views[idx].focus(latitude, longitude)
        except Exception as exc:
            logger.warning("Map focus failed: %s", exc)
        self.sidebar.setCurrentRow(idx)
        self.stack.setCurrentIndex(idx)

    def _exit_streamer_mode(self) -> None:
        if self._streamer_mode:
            self.toggle_streamer_mode()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_window()

    def toggle_streamer_mode(self) -> None:
        self._streamer_mode = not self._streamer_mode
        if self._streamer_mode:
            self.sidebar.hide()
            self._top_container.hide()
            self._stream_banner.show()
            self.showFullScreen()
            self.stream_btn.setText("Exit Streamer (Esc)")
            self._update_stream_banner()
        else:
            self.sidebar.show()
            self._top_container.show()
            self._stream_banner.hide()
            self.showNormal()
            self.stream_btn.setText("Streamer Mode (F11)")

    def _update_stream_banner(self) -> None:
        """Refresh the big broadcast ribbon from the newest store values."""
        if not self._stream_fields:
            return
        import time

        def _series(series: str):
            try:
                return self.store.get_latest_observation("swpc", series)
            except Exception:
                return None

        fields = self._stream_fields
        try:
            kp = _series("swpc:kp")
            kp_v = kp.value if kp else None
            level = -1
            try:
                now_view = self.views[0]
                if hasattr(now_view, "dial"):
                    level = now_view.dial.level
            except Exception:
                pass
            threat_names = ("QUIET", "UNSETTLED", "ELEVATED", "STORM")
            threat_colors = (theme.OK, theme.WARN, theme.ORANGE, theme.DANGER)
            if 0 <= level <= 3:
                fields["threat"][1].setText(threat_names[level])
                fields["threat"][1].setStyleSheet(f"color: {threat_colors[level]};")
            else:
                fields["threat"][1].setText("NO DATA")
                fields["threat"][1].setStyleSheet(f"color: {theme.TEXT_FAINT};")

            fields["kp"][1].setText(f"{kp_v:.1f}" if kp_v is not None else "—")
            fields["kp"][1].setStyleSheet(
                f"color: {theme.DANGER if kp_v is not None and kp_v >= 6 else theme.WARN if kp_v is not None and kp_v >= 4 else theme.OK if kp_v is not None else theme.TEXT_FAINT};"
            )

            bz = _series("swpc:imf_bz_gsm")
            bz_v = bz.value if bz else None
            fields["bz"][1].setText(f"{bz_v:.1f} nT" if bz_v is not None else "—")
            fields["bz"][1].setStyleSheet(
                f"color: {theme.DANGER if bz_v is not None and bz_v <= -10 else theme.WARN if bz_v is not None and bz_v < 0 else theme.TEXT if bz_v is not None else theme.TEXT_FAINT};"
            )

            proton = _series("swpc:proton_flux_gte10MeV")
            p_v = proton.value if proton else None
            if p_v is None:
                s_scale = "—"
            elif p_v >= 100000:
                s_scale = "S5"
            elif p_v >= 10000:
                s_scale = "S4"
            elif p_v >= 1000:
                s_scale = "S3"
            elif p_v >= 100:
                s_scale = "S2"
            elif p_v >= 10:
                s_scale = "S1"
            else:
                s_scale = "—"
            fields["proton"][1].setText(s_scale)
            fields["proton"][1].setStyleSheet(
                f"color: {theme.DANGER if p_v is not None and p_v >= 1000 else theme.WARN if p_v is not None and p_v >= 10 else theme.TEXT if p_v is not None else theme.TEXT_FAINT};"
            )

            dst = _series("swpc:dst")
            dst_v = dst.value if dst else None
            fields["dst"][1].setText(f"{dst_v:.0f} nT" if dst_v is not None else "—")
            fields["dst"][1].setStyleSheet(
                f"color: {theme.DANGER if dst_v is not None and dst_v <= -100 else theme.WARN if dst_v is not None and dst_v <= -50 else theme.TEXT if dst_v is not None else theme.TEXT_FAINT};"
            )

            locations = [loc for loc in (self.store.get_setting("locations") or []) if isinstance(loc, dict)]
            legacy_loc = self.store.get_setting("location")
            loc = locations[0] if locations else (legacy_loc if isinstance(legacy_loc, dict) else {"lat": 51.5, "name": "Local"})
            try:
                lat = abs(float(loc.get("lat", 51.5)))
            except (TypeError, ValueError):
                lat = 51.5
            threshold = 1 if lat >= 65 else 2 if lat >= 60 else 4 if lat >= 55 else 6 if lat >= 50 else 7 if lat >= 45 else 8
            if kp_v is None:
                aurora_txt, aurora_color = "—", theme.TEXT_FAINT
            elif kp_v >= threshold:
                aurora_txt, aurora_color = "VISIBLE", theme.OK
            elif kp_v >= threshold - 1 and threshold > 1:
                aurora_txt, aurora_color = "HORIZON", theme.WARN
            else:
                aurora_txt, aurora_color = "UNLIKELY", theme.TEXT_FAINT
            fields["aurora"][1].setText(aurora_txt)
            fields["aurora"][1].setStyleSheet(f"color: {aurora_color};")

            from datetime import datetime, timezone

            fields["clock"][1].setText(datetime.now(timezone.utc).strftime("%H:%M:%S"))
            self._last_banner_data = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stream banner update failed: %s", exc)

    def _refresh_all_views(self) -> None:
        for index, view in enumerate(self.views):
            try:
                view.refresh()
            except Exception as exc:  # noqa: BLE001
                logger.warning("View %d refresh failed: %s", index, exc)

    def _start_remote_prefetch(self, refresh_views: bool = False, refresh_alerts: bool = False) -> None:
        if not self.remote_mode or not hasattr(self.store, "prefetch"):
            if refresh_views:
                self._refresh_all_views()
            if refresh_alerts:
                self._check_and_notify_alerts()
            return
        self._prefetch_refresh_views = self._prefetch_refresh_views or refresh_views
        self._prefetch_refresh_alerts = self._prefetch_refresh_alerts or refresh_alerts
        if self._prefetch_thread is not None and self._prefetch_thread.isRunning():
            self._prefetch_again = True
            return
        self._prefetch_thread = QThread()
        self._prefetch_worker = RemotePrefetchWorker(self.store)
        self._prefetch_worker.moveToThread(self._prefetch_thread)
        self._prefetch_thread.started.connect(self._prefetch_worker.run)
        self._prefetch_worker.error.connect(lambda message: logger.warning("Remote prefetch failed: %s", message))
        self._prefetch_worker.finished.connect(self._on_prefetch_finished)
        self._prefetch_worker.finished.connect(self._prefetch_thread.quit)
        self._prefetch_thread.finished.connect(self._on_prefetch_thread_finished)
        self._prefetch_thread.finished.connect(self._prefetch_worker.deleteLater)
        self._prefetch_thread.finished.connect(self._prefetch_thread.deleteLater)
        self._prefetch_thread.start()

    def _on_prefetch_finished(self) -> None:
        if self._prefetch_refresh_views:
            self._prefetch_refresh_views = False
            self._refresh_all_views()
        if self._prefetch_refresh_alerts:
            self._prefetch_refresh_alerts = False
            self._check_and_notify_alerts()
        if self._streamer_mode:
            self._update_stream_banner()

    def _on_prefetch_thread_finished(self) -> None:
        if self.sender() is self._prefetch_thread:
            self._prefetch_thread = None
            self._prefetch_worker = None
        if self._prefetch_again:
            self._prefetch_again = False
            self._start_remote_prefetch()

    def start_ingest(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("Ingesting…")
        self._thread = QThread()
        self._worker = IngestWorker(self.store)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.finished.connect(self._on_ingest_thread_finished)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_ingest_thread_finished(self) -> None:
        # PySide deletes the C++ QThread object via deleteLater; never keep a
        # stale Python reference that would raise on the next isRunning().
        # Only clear our own thread (a newer ingest may already have started).
        if self.sender() is self._thread:
            self._thread = None
            self._worker = None

    def _on_finished(self, reports) -> None:
        self.refresh_btn.setEnabled(True)
        remote_summary = None
        for r in reports:
            if isinstance(r, _RemoteReport):
                remote_summary = r.summary
                break
        if remote_summary is not None:
            ok, fail = remote_summary.get("ok", 0), remote_summary.get("failed", 0)
            events, obs = remote_summary.get("events", 0), remote_summary.get("observations", 0)
            self.status_label.setText(
                f"Server ingested {ok} sources ok, {fail} failed — {events} events, {obs} observations"
            )
        else:
            ok = sum(1 for r in reports if r.ok)
            fail = len(reports) - ok
            events = sum(len(r.events) for r in reports)
            obs = sum(len(r.observations) for r in reports)
            self.status_label.setText(
                f"Ingested {ok} sources ok, {fail} failed — {events} events, {obs} observations"
            )
        # Refresh all views so background and foreground views are up to date
        for i, view in enumerate(self.views):
            try:
                view.refresh()
            except Exception as exc:
                logger.warning("View %d refresh failed after ingest: %s", i, exc)

        self._check_and_notify_alerts()
        if self._streamer_mode:
            self._update_stream_banner()

    def _on_server_ingest(self, msg: dict) -> None:
        """Server pushed an ingest_complete event (SSE): refresh this desktop."""
        summary = msg.get("summary", {}) if isinstance(msg, dict) else {}
        ok, fail = summary.get("ok", "?"), summary.get("failed", "?")
        events, obs = summary.get("events", "?"), summary.get("observations", "?")
        self.status_label.setText(
            f"Live: server ingested {ok} sources ok, {fail} failed — {events} events, {obs} observations"
        )
        self._start_remote_prefetch(refresh_views=True, refresh_alerts=True)

    def _alerts_enabled(self, key: str) -> bool:
        """Desktop alert preferences (QSettings, default on)."""
        try:
            settings = QSettings("ssnow", "ssnow")
            if not bool(settings.value("alerts_enabled", True, type=bool)):
                return False
            return bool(settings.value(key, True, type=bool))
        except Exception:
            return True

    def _check_and_notify_alerts(self) -> None:
        if not self._alerts_enabled("alerts_spacewx") and not self._alerts_enabled("alerts_quakes") and not self._alerts_enabled("alerts_neo"):
            return
        alerts_spacewx = self._alerts_enabled("alerts_spacewx")
        alerts_quakes = self._alerts_enabled("alerts_quakes")
        alerts_neo = self._alerts_enabled("alerts_neo")
        try:
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            fresh_after = now - timedelta(hours=2)

            def _fresh(obs):
                return obs is not None and obs.ts is not None and obs.ts >= fresh_after

            # 1. Check for elevated Kp (geomagnetic storm >= 5.0, fresh only)
            kp_obs = self.store.get_latest_observation("swpc", "swpc:kp") if alerts_spacewx else None
            if _fresh(kp_obs) and kp_obs.value >= 5.0:
                val = kp_obs.value
                band = "severe" if val >= 7.0 else "storm"
                self.store.add_notification(
                    notif_id=f"kp-{kp_obs.ts.strftime('%Y%m%d')}-{band}",
                    event_id=None,
                    category="space_weather_alert",
                    title=f"Geomagnetic Storm Alert: Kp {val:.1f}",
                    severity="warning" if val < 7.0 else "critical",
                    fired_at=now,
                )

            # 2. Check for significant earthquakes (M >= 6.0, last 6 h)
            quakes = (
                self.store.query_events(
                    categories=["earthquake"],
                    min_magnitude=6.0,
                    start=now - timedelta(hours=6),
                    limit=20,
                )
                if alerts_quakes
                else []
            )
            for q in quakes:
                self.store.add_notification(
                    notif_id=f"quake-{q.id}",
                    event_id=q.id,
                    category="earthquake",
                    title=f"M{q.magnitude:.1f} Earthquake: {q.title}",
                    severity="warning" if (q.magnitude or 0) < 7.0 else "critical",
                    fired_at=now,
                )

            # 3. Upcoming close approaches: PHA or inside Moon orbit (<1 LD).
            try:
                neos = self.store.query_events(categories=["neo"], limit=500) if alerts_neo else []
                horizon = now + timedelta(days=7)
                for n in neos:
                    if n.occurred_at is None or n.occurred_at < now or n.occurred_at > horizon:
                        continue
                    ex = n.extra_json or {}
                    if (ex.get("kind") or "") == "sentry":
                        continue
                    ld = None
                    for key in ("dist_lunar", "miss_lunar"):
                        try:
                            if ex.get(key) not in (None, ""):
                                ld = float(ex.get(key))
                                break
                        except (TypeError, ValueError):
                            continue
                    hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate")) and not ex.get("is_comet")
                    if hazardous or (ld is not None and ld < 1.0):
                        sev = "critical" if (ld is not None and ld < 1.0) else "warning"
                        self.store.add_notification(
                            notif_id=f"neo-{n.id}",
                            event_id=n.id,
                            category="neo",
                            title=f"Close approach: {n.title}",
                            severity=sev,
                            fired_at=now,
                        )
            except Exception as exc:
                logger.warning("NEO alert check failed: %s", exc)

            # 3b. IMF Bz southward (auroral/storm coupling): Bz <= -5 nT.
            try:
                bz_obs = self.store.get_latest_observation("swpc", "swpc:imf_bz_gsm") if alerts_spacewx else None
                if _fresh(bz_obs) and bz_obs.value <= -5.0:
                    band = "severe" if bz_obs.value <= -10.0 else "storm"
                    self.store.add_notification(
                        notif_id=f"bz-{bz_obs.ts.strftime('%Y%m%d')}-{band}",
                        event_id=None,
                        category="space_weather_alert",
                        title=f"IMF Bz southward: {bz_obs.value:.1f} nT — aurora/storm coupling",
                        severity="warning" if bz_obs.value > -10.0 else "critical",
                        fired_at=now,
                    )
            except Exception as exc:
                logger.warning("Bz alert check failed: %s", exc)

            # 3c. Solar radiation storm (GOES protons >= 10 pfu = S1).
            try:
                p_obs = self.store.get_latest_observation("swpc", "swpc:proton_flux_gte10MeV") if alerts_spacewx else None
                if _fresh(p_obs) and p_obs.value >= 10.0:
                    v = p_obs.value
                    scale = (
                        "S5" if v >= 100000 else "S4" if v >= 10000 else "S3" if v >= 1000
                        else "S2" if v >= 100 else "S1"
                    )
                    self.store.add_notification(
                        notif_id=f"proton-{p_obs.ts.strftime('%Y%m%d')}-{scale}",
                        event_id=None,
                        category="space_weather_alert",
                        title=f"Solar radiation storm: {v:.0f} pfu @>=10 MeV ({scale})",
                        severity="warning" if v < 1000 else "critical",
                        fired_at=now,
                    )
            except Exception as exc:
                logger.warning("Proton alert check failed: %s", exc)

            # 3d. Dst storm (moderate <= -50 nT).
            try:
                d_obs = self.store.get_latest_observation("swpc", "swpc:dst") if alerts_spacewx else None
                if _fresh(d_obs) and d_obs.value <= -50.0:
                    v = d_obs.value
                    band = "intense" if v <= -100 else "moderate"
                    self.store.add_notification(
                        notif_id=f"dst-{d_obs.ts.strftime('%Y%m%d')}-{band}",
                        event_id=None,
                        category="geomagnetic_storm",
                        title=f"Geomagnetic storm (Dst {v:.0f} nT)",
                        severity="warning" if v > -100 else "critical",
                        fired_at=now,
                    )
            except Exception as exc:
                logger.warning("Dst alert check failed: %s", exc)

            # 4. Deliver pending notifications to desktop
            pending = self.store.pending_notifications()
            for n in pending:
                logger.info("Alert triggered: [%s] %s", n["severity"].upper(), n["title"])
                if self._tray_icon and QSystemTrayIcon.isSystemTrayAvailable():
                    icon = (
                        QSystemTrayIcon.MessageIcon.Critical
                        if n["severity"] == "critical"
                        else QSystemTrayIcon.MessageIcon.Warning
                    )
                    self._tray_icon.showMessage(
                        "Solar System Now Alert",
                        n["title"],
                        icon,
                        6000,
                    )
                else:
                    # No system tray: surface it in the app instead of silently
                    # dropping the alert.
                    self.status_label.setText(f"Alert: {n['title']}")
                self.store.mark_notification_delivered(n["id"])
        except Exception as exc:
            logger.warning("Alert check failed: %s", exc)

    def _on_error(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"Ingest error: {message}")

    def closeEvent(self, event) -> None:
        for timer_name in ("_refresh_timer", "_stream_clock", "_remote_prefetch_timer"):
            try:
                timer = getattr(self, timer_name, None)
                if timer is not None:
                    timer.stop()
            except Exception:
                pass
        try:
            if getattr(self, "_sse", None) is not None:
                self._sse.stop()
                self._sse.wait(5000)
        except Exception:
            pass
        try:
            if self._thread is not None and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(10000)
        except Exception:
            pass
        try:
            if self._prefetch_thread is not None and self._prefetch_thread.isRunning():
                self._prefetch_thread.quit()
                self._prefetch_thread.wait(10000)
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        super().closeEvent(event)
