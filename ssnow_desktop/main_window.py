"""Main window: navigation, ingest worker, view stack."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
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

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store

    def run(self) -> None:
        import httpx

        with httpx.Client() as client:
            reports = run_due(self.store, client)
        self.finished.emit(reports)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_dirs()
        self.store = Store()
        from ssnow_core.seed import seed_if_empty

        seed_if_empty(self.store)
        self.setWindowTitle("Solar System Now — Real Data Dashboard")
        self.resize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.addItems(VIEW_NAMES)
        self.sidebar.setCurrentRow(0)
        self.sidebar.setFixedWidth(210)
        self.sidebar.setStyleSheet(
            "QListWidget { background: #1f1f1f; color: #eee; border: none; font-size: 14px; }"
            "QListWidget::item { padding: 10px 14px; border-bottom: 1px solid #333; }"
            "QListWidget::item:selected { background: #0d6efd; color: white; }"
        )

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
        self.refresh_btn.setFixedWidth(120)
        self.refresh_btn.clicked.connect(self.start_ingest)
        self.stream_btn = QPushButton("Streamer Mode (F11)")
        self.stream_btn.setFixedWidth(150)
        self.stream_btn.clicked.connect(self.toggle_streamer_mode)
        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("color: #666;")
        bar.addWidget(self.refresh_btn)
        bar.addWidget(self.stream_btn)
        bar.addStretch(1)
        bar.addWidget(self.status_label)

        self._top_container = QWidget()
        self._top_container.setLayout(bar)
        self._top_container.setFixedHeight(44)
        self._top_container.setStyleSheet("background: #f5f5f5; border-bottom: 1px solid #ccc;")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_container)
        root.addWidget(central)
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

    def _on_view_changed(self, index: int) -> None:
        try:
            self.views[index].refresh()
        except Exception as exc:
            logger.warning("View %d refresh failed: %s", index, exc)

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
            self.showFullScreen()
            self.stream_btn.setText("Exit Streamer (Esc)")
        else:
            self.sidebar.show()
            self._top_container.show()
            self.showNormal()
            self.stream_btn.setText("Streamer Mode (F11)")

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
