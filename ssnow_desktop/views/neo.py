"""Asteroids & Comets close-approach tracker view.

Data: category="neo" events from NeoWs (keyed) + JPL CAD (keyless, asteroids+comets).
No orbital-element propagation here: the orbit panel is an explicitly labelled
distance schematic (log LD scale), not a true ephemeris, to respect the
no-fabricated-data invariant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .base_view import BaseView

AU_KM = 149597870.7
LUNAR_KM = 384400.0


def _f(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def neo_record(event) -> dict:
    ex = event.extra_json or {}
    ld = _f(ex.get("dist_lunar"))
    if ld is None:
        ld = _f(ex.get("miss_lunar"))
    km = _f(ex.get("dist_km"))
    if km is None:
        km = _f(ex.get("miss_km"))
    if km is None and ld is not None:
        km = ld * LUNAR_KM
    if ld is None and km is not None:
        ld = km / LUNAR_KM
    vel = _f(ex.get("velocity_km_s"))
    size = _f(ex.get("diameter_km"))
    if size is None:
        lo, hi = _f(ex.get("diameter_km_min")), _f(ex.get("diameter_km_max"))
        if lo is not None or hi is not None:
            size = ((lo or hi or 0) + (hi or lo or 0)) / 2.0
    hazardous = bool(ex.get("hazardous") or ex.get("hazardous_candidate"))
    kind = ex.get("kind")
    if not kind:
        kind = "comet" if ex.get("is_comet") else "asteroid"
    if kind == "sentry":
        try:
            hazardous = float(ex.get("ps_cum", -99)) >= -5.0
        except (TypeError, ValueError):
            hazardous = False
    name = ex.get("fullname") or ex.get("des") or event.title
    return {
        "event": event,
        "name": str(name).strip(),
        "kind": kind,
        "ld": ld,
        "km": km,
        "vel": vel,
        "size_km": size,
        "hazardous": hazardous,
        "date": event.occurred_at,
    }


def human_size(size_km: float | None) -> str:
    if size_km is None:
        return "—"
    m = size_km * 1000.0
    if m < 1:
        return f"{m * 100:.0f} cm"
    if m < 30:
        return f"~{m:.0f} m (house)"
    if m < 100:
        return f"~{m:.0f} m (airliner)"
    if m < 300:
        return f"~{m:.0f} m (stadium)"
    if m < 1000:
        return f"~{m:.0f} m (skyscraper+)"
    return f"~{size_km:.1f} km (mountain)"


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class LDRadar(QWidget):
    """Horizontal Lunar-Distance strip: Earth at left, Moon line at 1 LD."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(86)
        self._items: list[dict] = []

    def set_items(self, items: list[dict]) -> None:
        self._items = items[:12]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#0b1020"))
        # Scale: 0..max(5, max LD) linear; Moon at 1 LD marked.
        max_ld = 5.0
        for it in self._items:
            if it["ld"] is not None:
                max_ld = max(max_ld, min(it["ld"], 40.0))
        def x_for(ld: float) -> int:
            frac = max(0.0, min(ld, max_ld)) / max_ld
            return int(50 + frac * (w - 70))

        painter.setPen(QPen(QColor("#334155"), 2))
        painter.drawLine(50, h // 2, w - 20, h // 2)
        # Earth
        painter.setBrush(QColor("#3b82f6"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(28, h // 2 - 10, 20, 20)
        painter.setPen(QPen(QColor("#bfdbfe")))
        painter.setFont(QFont("Sans", 9))
        painter.drawText(18, h - 8, "Earth")
        # Moon line at 1 LD
        mx = x_for(1.0)
        painter.setPen(QPen(QColor("#e2e8f0"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(mx, 8, mx, h - 20)
        painter.setPen(QPen(QColor("#e2e8f0")))
        painter.drawText(mx - 30, 16, "Moon 1 LD")
        # Items
        for i, it in enumerate(self._items):
            if it["ld"] is None:
                continue
            x = x_for(min(it["ld"], max_ld))
            y = h // 2 - 18 + (i % 3) * 12
            color = QColor("#ef4444") if it["hazardous"] else (QColor("#22d3ee") if it["kind"] == "comet" else QColor("#a3e635"))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(x - 4, y - 4, 8, 8)
            painter.setPen(QPen(QColor("#e2e8f0")))
            painter.drawText(x + 6, y + 4, f"{it['name'][:22]} · {it['ld']:.1f} LD")


class OrbitSchematic(QWidget):
    """Top-down inner-solar-system distance schematic (NOT a true orbit plot)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._items: list[dict] = []

    def set_items(self, items: list[dict]) -> None:
        self._items = items[:8]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#020617"))
        cx, cy = w // 2, h // 2
        base = min(w, h) // 2 - 16
        # Sun
        painter.setBrush(QColor("#fbbf24"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(cx - 12, cy - 12, 24, 24)
        painter.setPen(QPen(QColor("#fbbf24")))
        painter.drawText(cx - 12, cy + 28, "Sun")
        # Planet orbits (schematic circles, labelled)
        for frac, color, label in (
            (0.25, "#9ca3af", "Mercury"),
            (0.42, "#fb923c", "Venus"),
            (0.60, "#3b82f6", "Earth"),
            (0.80, "#ef4444", "Mars"),
        ):
            r = int(base * frac)
            painter.setPen(QPen(QColor(color), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        # Earth marker at fixed angle; asteroids placed by LD on spiral angle
        earth_r = int(base * 0.60)
        ex, ey = cx + earth_r, cy
        painter.setBrush(QColor("#3b82f6"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(ex - 5, ey - 5, 10, 10)
        for i, it in enumerate(self._items):
            if it["ld"] is None:
                continue
            # Log-scale radius beyond Earth orbit for visibility; schematic only.
            ld = max(it["ld"], 0.05)
            frac = 0.60 + min(math.log10(ld + 1.0) / math.log10(41.0), 1.0) * 0.35
            r = base * frac
            ang = math.radians(200 + i * (140 / max(len(self._items), 1)))
            x, y = cx + r * math.cos(ang), cy + r * math.sin(ang)
            color = QColor("#ef4444") if it["hazardous"] else (QColor("#22d3ee") if it["kind"] == "comet" else QColor("#a3e635"))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(x) - 4, int(y) - 4, 8, 8)
            painter.setPen(QPen(QColor("#e2e8f0")))
            painter.drawText(int(x) + 6, int(y) + 4, it["name"][:20])
        painter.setPen(QPen(QColor("#64748b")))
        painter.drawText(8, h - 8, "Schematic distances only — not true orbits. Sources: JPL CAD + NeoWs.")


class NeoView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.header = QLabel("—")
        self.header.setObjectName("h2")
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.radar = LDRadar()
        layout.addWidget(self.radar)

        self.orbit = OrbitSchematic()
        layout.addWidget(self.orbit)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Approach (UTC)", "LD", "km", "Vel km/s", "Size / Hazard"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.attr = QLabel("NASA JPL CNEOS NeoWs + SBDB CAD · distances in Lunar Distances (1 LD = 384,400 km)")
        self.attr.setObjectName("source")
        self.attr.setWordWrap(True)
        layout.addWidget(self.attr)

    def refresh(self) -> None:
        events = self.store.query_events(categories=["neo"], limit=500)
        recs = [neo_record(e) for e in events]
        # Sort: closest first; unknown distance last; then by date.
        recs.sort(key=lambda r: (r["ld"] is None, r["ld"] if r["ld"] is not None else 1e9))
        pha = sum(1 for r in recs if r["hazardous"])
        under_moon = sum(1 for r in recs if r["ld"] is not None and r["ld"] < 1.0)
        comets = sum(1 for r in recs if r["kind"] == "comet")
        sentry = sum(1 for r in recs if r["kind"] == "sentry")
        self.header.setText(
            f"Close approaches tracked: {len(recs)} · {pha} potentially hazardous · "
            f"{under_moon} inside Moon orbit (<1 LD) · {comets} comets · {sentry} Sentry watch"
        )
        self.radar.set_items(recs)
        self.orbit.set_items(recs)
        self.table.setRowCount(len(recs))
        for row, r in enumerate(recs):
            ev = r["event"]
            self.table.setItem(row, 0, QTableWidgetItem(r["name"][:60]))
            self.table.setItem(row, 1, QTableWidgetItem(r["kind"]))
            self.table.setItem(row, 2, QTableWidgetItem(fmt_ts(r["date"])))
            self.table.setItem(row, 3, QTableWidgetItem(f"{r['ld']:.2f}" if r["ld"] is not None else "—"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{r['km']:,.0f}" if r["km"] is not None else "—"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{r['vel']:.1f}" if r["vel"] is not None else "—"))
            size_txt = human_size(r["size_km"])
            if r["kind"] == "sentry":
                ps = (r["event"].extra_json or {}).get("ps_cum")
                size_txt += f" · IMPACT WATCH PS {ps}"
            elif r["hazardous"]:
                size_txt += " · PHA"
            item = QTableWidgetItem(size_txt)
            if r["hazardous"]:
                item.setBackground(QColor("#fef2f2"))
                item.setForeground(QColor("#b91c1c"))
            self.table.setItem(row, 6, item)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, ev)
