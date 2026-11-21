"""Main window: navigation, ingest worker, view stack."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
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
                resp = httpx.post(f"{self.remote_base}/api/ingest", timeout=120.0)
                resp.raise_for_status()
                summary = resp.json().get("summary", {})
                self.finished.emit([_RemoteReport(summary)])
            except Exception as exc:  # noqa: BLE001
                self.error.emit(str(exc))
            return
        with httpx.Client() as client:
            reports = run_due(self.store, client)
        self.finished.emit(reports)


class _RemoteReport:
    """Pseudo-report wrapping the server's ingest summary for _on_finished."""

    ok = True
    events: list = []
    observations: list = []

    def __init__(self, summary: dict) -> None:
        self.summary = summary


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        settings = QSettings("ssnow", "ssnow")
        self.remote_mode = bool(settings.value("remote_mode", False, type=bool))
        self.remote_base = str(settings.value("remote_base_url", "http://localhost:8123") or "http://localhost:8123")
        if self.remote_mode:
            from ssnow_core.remote import RemoteStore

            try:
                import httpx

                probe = httpx.get(f"{self.remote_base.rstrip('/')}/api/health", timeout=10.0)
                probe.raise_for_status()
                self.store = RemoteStore(self.remote_base)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Remote server %s unreachable (%s); falling back to standalone", self.remote_base, exc)
                self.remote_mode = False
                self.store = Store()
                from ssnow_core.seed import seed_if_empty

                seed_if_empty(self.store)
        else:
            self.store = Store()
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
        for cls in VIEW_CLASSES:
            view = cls(self.store)
            self.views.append(view)
            self.stack.addWidget(view)

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

        # System tray icon for desktop alerts
        try:
            self._tray_icon = QSystemTrayIcon(self)
            self._tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_icon.show()
        except Exception:
            self._tray_icon = None

        self.views[0].refresh()

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

    def _tick_stream_banner(self) -> None:
        if self._streamer_mode:
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

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F11:
            self.toggle_streamer_mode()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._streamer_mode:
            self.toggle_streamer_mode()
            event.accept()
            return
        super().keyPressEvent(event)

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
        def _series(series: str, source: str = "swpc"):
            try:
                rows = self.store.get_series(source, series, limit=1)
                return rows[-1] if rows else None
            except Exception:
                return None

        fields = self._stream_fields
        try:
            kp = _series("swpc:kp")
            kp_v = kp.value if kp else 0.0
            level = 0
            try:
                now_view = self.views[0]
                if hasattr(now_view, "dial"):
                    level = now_view.dial.level
            except Exception:
                pass
            threat_names = ("QUIET", "UNSETTLED", "ELEVATED", "STORM")
            threat_colors = (theme.OK, theme.WARN, theme.ORANGE, theme.DANGER)
            fields["threat"][1].setText(threat_names[level])
            fields["threat"][1].setStyleSheet(f"color: {threat_colors[level]};")

            fields["kp"][1].setText(f"{kp_v:.1f}")
            fields["kp"][1].setStyleSheet(
                f"color: {theme.DANGER if kp_v >= 6 else theme.WARN if kp_v >= 4 else theme.OK};"
            )

            bz = _series("swpc:imf_bz_gsm")
            bz_v = bz.value if bz else 0.0
            fields["bz"][1].setText(f"{bz_v:.1f} nT")
            fields["bz"][1].setStyleSheet(
                f"color: {theme.DANGER if bz_v <= -10 else theme.WARN if bz_v < 0 else theme.TEXT};"
            )

            proton = _series("swpc:proton_flux_gte10MeV")
            p_v = proton.value if proton else 0.0
            s_scale = "S4" if p_v >= 10000 else "S3" if p_v >= 1000 else "S2" if p_v >= 100 else "S1" if p_v >= 10 else "—"
            fields["proton"][1].setText(s_scale)
            fields["proton"][1].setStyleSheet(
                f"color: {theme.DANGER if p_v >= 1000 else theme.WARN if p_v >= 10 else theme.TEXT};"
            )

            dst = _series("swpc:dst")
            dst_v = dst.value if dst else 0.0
            fields["dst"][1].setText(f"{dst_v:.0f} nT")
            fields["dst"][1].setStyleSheet(
                f"color: {theme.DANGER if dst_v <= -100 else theme.WARN if dst_v <= -50 else theme.TEXT};"
            )

            locations = self.store.get_setting("locations") or []
            loc = locations[0] if locations else {"lat": 51.5, "name": "Local"}
            lat = abs(float(loc.get("lat", 51.5)))
            threshold = 1 if lat >= 65 else 2 if lat >= 60 else 4 if lat >= 55 else 6 if lat >= 50 else 7 if lat >= 45 else 8
            if kp_v >= threshold:
                aurora_txt, aurora_color = "VISIBLE", theme.OK
            elif kp_v >= threshold - 1 and threshold > 1:
                aurora_txt, aurora_color = "HORIZON", theme.WARN
            else:
                aurora_txt, aurora_color = "UNLIKELY", theme.TEXT_FAINT
            fields["aurora"][1].setText(aurora_txt)
            fields["aurora"][1].setStyleSheet(f"color: {aurora_color};")

            from datetime import datetime, timezone

            fields["clock"][1].setText(datetime.now(timezone.utc).strftime("%H:%M:%S"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stream banner update failed: %s", exc)

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
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

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

    def _check_and_notify_alerts(self) -> None:
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            # 1. Check for elevated Kp (geomagnetic storm >= 5.0)
            kp_obs = self.store.latest_observations("swpc", "swpc:kp")
            if kp_obs and kp_obs[0].value >= 5.0:
                notif_id = f"kp-{kp_obs[0].ts.strftime('%Y%m%d%H%M')}"
                val = kp_obs[0].value
                self.store.add_notification(
                    notif_id=notif_id,
                    event_id=None,
                    category="space_weather_alert",
                    title=f"Geomagnetic Storm Alert: Kp {val:.1f}",
                    severity="warning" if val < 7.0 else "critical",
                    fired_at=now,
                )

            # 2. Check for significant earthquakes (M >= 6.0)
            quakes = self.store.query_events(categories=["earthquake"], min_magnitude=6.0, limit=5)
            for q in quakes:
                notif_id = f"quake-{q.id}"
                self.store.add_notification(
                    notif_id=notif_id,
                    event_id=q.id,
                    category="earthquake",
                    title=f"M{q.magnitude:.1f} Earthquake: {q.title}",
                    severity="warning" if (q.magnitude or 0) < 7.0 else "critical",
                    fired_at=now,
                )

            # 3. Close-approach alerts: PHA or inside Moon orbit (<1 LD)
            try:
                neos = self.store.query_events(categories=["neo"], limit=100)
                for n in neos:
                    ex = n.extra_json or {}
                    ld = None
                    for key in ("dist_lunar", "miss_lunar"):
                        try:
                            if ex.get(key) not in (None, ""):
                                ld = float(ex.get(key))
                                break
                        except (TypeError, ValueError):
                            continue
                    hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate"))
                    if hazardous or (ld is not None and ld < 1.0):
                        notif_id = f"neo-{n.id}"
                        sev = "critical" if (ld is not None and ld < 1.0) else "warning"
                        self.store.add_notification(
                            notif_id=notif_id,
                            event_id=n.id,
                            category="neo",
                            title=f"Asteroid pass: {n.title}",
                            severity=sev,
                            fired_at=now,
                        )
            except Exception as exc:
                logger.warning("NEO alert check failed: %s", exc)

            # 3b. IMF Bz southward (auroral/storm coupling): Bz <= -5 nT.
            try:
                bz_obs = self.store.latest_observations("swpc", "swpc:imf_bz_gsm")
                if bz_obs and bz_obs[0].value <= -5.0:
                    notif_id = f"bz-{bz_obs[0].ts.strftime('%Y%m%d%H%M')}"
                    self.store.add_notification(
                        notif_id=notif_id,
                        event_id=None,
                        category="space_weather_alert",
                        title=f"IMF Bz southward: {bz_obs[0].value:.1f} nT — aurora/storm coupling",
                        severity="warning" if bz_obs[0].value > -10.0 else "critical",
                        fired_at=now,
                    )
            except Exception as exc:
                logger.warning("Bz alert check failed: %s", exc)

            # 3c. Solar radiation storm (GOES protons >= 10 pfu = S1).
            try:
                p_obs = self.store.latest_observations("swpc", "swpc:proton_flux_gte10MeV")
                if p_obs and p_obs[0].value >= 10.0:
                    v = p_obs[0].value
                    notif_id = f"proton-{p_obs[0].ts.strftime('%Y%m%d%H%M')}"
                    self.store.add_notification(
                        notif_id=notif_id,
                        event_id=None,
                        category="space_weather_alert",
                        title=f"Solar radiation storm: {v:.0f} pfu @>=10 MeV",
                        severity="warning" if v < 1000 else "critical",
                        fired_at=now,
                    )
            except Exception as exc:
                logger.warning("Proton alert check failed: %s", exc)

            # 3d. Dst storm (moderate <= -50 nT).
            try:
                d_obs = self.store.latest_observations("swpc", "swpc:dst")
                if d_obs and d_obs[0].value <= -50.0:
                    v = d_obs[0].value
                    notif_id = f"dst-{d_obs[0].ts.strftime('%Y%m%d%H%M')}"
                    self.store.add_notification(
                        notif_id=notif_id,
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
                self.store.mark_notification_delivered(n["id"])
        except Exception as exc:
            logger.warning("Alert check failed: %s", exc)

    def _on_error(self, message: str) -> None:
        self.refresh_btn.setEnabled(True)
        self.status_label.setText(f"Ingest error: {message}")

    def closeEvent(self, event) -> None:
        try:
            if hasattr(self, "_refresh_timer"):
                self._refresh_timer.stop()
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        super().closeEvent(event)
