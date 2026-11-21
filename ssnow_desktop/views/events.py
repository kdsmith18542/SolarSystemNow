"""Events list view."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

from .base_view import BaseView
from .. import theme

CATEGORIES = [
    "All",
    "earthquake",
    "volcano",
    "wildfire",
    "storm",
    "flood",
    "space_weather_alert",
    "geomagnetic_storm",
    "cme",
    "solar_flare",
    "neo",
    "fireball",
    "severe_outlook",
    "weather_alert",
    "other",
]

CATEGORY_COLORS = {
    "earthquake": theme.DANGER,
    "volcano": theme.ORANGE,
    "wildfire": "#ef4444",
    "storm": "#60a5fa",
    "flood": "#22d3ee",
    "space_weather_alert": "#e879f9",
    "geomagnetic_storm": theme.VIOLET,
    "cme": theme.PINK,
    "solar_flare": theme.WARN,
    "neo": theme.LIME,
    "fireball": theme.ORANGE,
    "severe_outlook": "#facc15",
    "weather_alert": theme.ACCENT,
    "other": theme.TEXT_DIM,
}


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class DetailDialog(QDialog):
    def __init__(self, event, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(event.title)
        self.resize(740, 520)
        layout = QVBoxLayout(self)

        browser = QTextBrowser()
        extra = ""
        if event.extra_json:
            import json

            extra = f"<pre>{json.dumps(event.extra_json, indent=2)}</pre>"
        ex = event.extra_json or {}
        badges: list[str] = []
        if ex.get("tsunami") in (1, True, "1"):
            badges.append("🌊 TSUNAMI FLAG — check USGS/PTWC")
        if ex.get("alert"):
            badges.append(f"PAGER alert: {ex.get('alert')}")
        if ex.get("felt"):
            badges.append(f"Felt reports: {ex.get('felt')}")
        if ex.get("severity"):
            badges.append(f"NWS severity: {ex.get('severity')} · {ex.get('certainty', '')}/{ex.get('urgency', '')}")
        if ex.get("expires"):
            badges.append(f"Expires: {ex.get('expires')}")
        if ex.get("hazardous") or ex.get("hazardous_candidate"):
            kind = ex.get("kind", "asteroid")
            ld = ex.get("dist_lunar") or ex.get("miss_lunar")
            badges.append(f"⚠️ POTENTIALLY HAZARDOUS {kind} — {ld} LD")
        if ex.get("is_comet"):
            badges.append("☄️ Comet close approach (JPL CAD)")
        if ex.get("kind") == "sentry":
            badges.append(f"🎯 Sentry impact watch: PS {ex.get('ps_cum')} · IP {ex.get('impact_probability')} · {ex.get('year_range')}")
        if ex.get("kind") == "lsr":
            badges.append(f"⛈️ Storm report: {ex.get('typetext')} via {ex.get('wfo')} ({ex.get('source')})")
        if ex.get("speed") or ex.get("type"):
            badges.append(f"CME: speed {ex.get('speed')} km/s · type {ex.get('type')} · half-angle {ex.get('half_angle')}")
        badge_html = f"<p><b>{' · '.join(badges)}</b></p>" if badges else ""
        instruction = f"<p><b>Instruction:</b> {ex.get('instruction')}</p>" if ex.get("instruction") else ""
        mag_text = (
            f"{event.magnitude:.1f} {event.magnitude_unit or ''}".strip()
            if event.magnitude is not None
            else "—"
        )
        geo_text = (
            f"{event.latitude:.2f}, {event.longitude:.2f}"
            if event.latitude is not None and event.longitude is not None
            else "—"
        )
        depth_text = f"{event.depth_km:.1f} km" if event.depth_km is not None else "—"
        html = f"""
        <h2>{event.title}</h2>
        <p><b>Source:</b> {event.source} &nbsp;|&nbsp; <b>Category:</b> {event.category} &nbsp;|&nbsp; <b>Upstream ID:</b> {event.upstream_id}</p>
        <p><b>Occurred:</b> {fmt_ts(event.occurred_at)} &nbsp;|&nbsp; <b>Updated:</b> {fmt_ts(event.updated_at)}</p>
        <p><b>Magnitude:</b> {mag_text} &nbsp;|&nbsp; <b>Depth:</b> {depth_text} &nbsp;|&nbsp; <b>Lat/Lon:</b> {geo_text}</p>
        <p><b>Description:</b> {event.description or '—'}</p>
        {badge_html}
        {instruction}
        <p><b>Extra:</b> {extra}</p>
        """
        if event.url:
            html += f"<p><a href='{event.url}'>Open source page</a></p>"
        browser.setHtml(html)
        browser.setOpenExternalLinks(True)
        layout.addWidget(browser)

        buttons = QHBoxLayout()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addStretch(1)
        if event.latitude is not None and event.longitude is not None:
            show = QPushButton("Show on Map")
            show.setToolTip("Center the Map tab on this event")
            show.clicked.connect(lambda: self._show_on_map(event))
            buttons.addWidget(show)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _show_on_map(self, event) -> None:
        mw = self.window()
        show = getattr(mw, "show_on_map", None)
        if callable(show):
            show(event.latitude, event.longitude)
        self.accept()


class EventsView(BaseView):
    def __init__(self, store) -> None:
        super().__init__(store)
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.addItems(CATEGORIES)
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(7)
        self.days_spin.setSuffix(" days")
        self.mag_spin = QDoubleSpinBox()
        self.mag_spin.setRange(0, 12)
        self.mag_spin.setDecimals(1)
        self.mag_spin.setValue(0)
        self.mag_spin.setSuffix(" M")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self.refresh)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setToolTip("Export the currently loaded events to CSV")
        self.export_btn.clicked.connect(self._export_csv)
        toolbar.addWidget(QLabel("Category:"))
        toolbar.addWidget(self.category_combo)
        toolbar.addWidget(QLabel("Within:"))
        toolbar.addWidget(self.days_spin)
        toolbar.addWidget(QLabel("Min magnitude:"))
        toolbar.addWidget(self.mag_spin)
        toolbar.addWidget(self.apply_btn)
        toolbar.addWidget(self.export_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Time (UTC)", "Source", "Category", "Magnitude", "Title", "Place / detail"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self.days_spin.value())
        category = self.category_combo.currentText()
        categories = None if category == "All" else [category]
        min_magnitude = self.mag_spin.value() or None
        events = self.store.query_events(
            start=start,
            end=end,
            categories=categories,
            min_magnitude=min_magnitude,
            limit=500,
        )
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(events))
        for row, event in enumerate(events):
            self.table.setItem(row, 0, QTableWidgetItem(fmt_ts(event.occurred_at)))
            self.table.setItem(row, 1, QTableWidgetItem(event.source))
            cat_item = QTableWidgetItem(event.category)
            cat_color = CATEGORY_COLORS.get(event.category, theme.TEXT_DIM)
            cat_item.setForeground(QColor(cat_color))
            self.table.setItem(row, 2, cat_item)
            mag_text = (
                f"{event.magnitude:.1f} {event.magnitude_unit or ''}".strip()
                if event.magnitude is not None
                else "—"
            )
            mag_item = QTableWidgetItem(mag_text)
            mag_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            seismic_unit = (event.magnitude_unit or "M") in ("M", "ML", "Mb", "MbLg", "Ms", "Mw", "md", "MLv", "")
            if seismic_unit and event.magnitude is not None and event.magnitude >= 6:
                mag_item.setForeground(QColor(theme.DANGER))
            elif seismic_unit and event.magnitude is not None and event.magnitude >= 4:
                mag_item.setForeground(QColor(theme.WARN))
            self.table.setItem(row, 3, mag_item)
            self.table.setItem(row, 4, QTableWidgetItem(event.title))
            detail = (
                f"{event.latitude:.2f}, {event.longitude:.2f}"
                if event.latitude is not None and event.longitude is not None
                else (event.upstream_id or "")
            )
            self.table.setItem(row, 5, QTableWidgetItem(detail))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, event)
        self.table.setSortingEnabled(True)

    def _on_double_clicked(self, index) -> None:
        item = self.table.item(index.row(), 0)
        event = item.data(Qt.ItemDataRole.UserRole)
        dlg = DetailDialog(event, self)
        dlg.exec()

    def _export_csv(self) -> None:
        import csv

        dest, _ = QFileDialog.getSaveFileName(self, "Export events to CSV", "ssnow-events.csv", "*.csv")
        if not dest:
            return
        try:
            with open(dest, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["id", "source", "category", "title", "occurred_at", "latitude", "longitude", "magnitude", "magnitude_unit", "url"])
                for row in range(self.table.rowCount()):
                    event = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                    writer.writerow(
                        [
                            event.id, event.source, event.category, event.title,
                            fmt_ts(event.occurred_at), event.latitude, event.longitude,
                            event.magnitude, event.magnitude_unit, event.url,
                        ]
                    )
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export", f"Exported {self.table.rowCount()} events to {dest}")
