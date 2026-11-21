"""Moon view."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFormLayout, QLabel, QVBoxLayout, QWidget

from .base_view import BaseView


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class PhaseDisk(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.illumination: float = 0.0
        self.phase_angle: float = 0.0  # 0 to 360 deg
        self.setFixedSize(220, 220)

    def set_phase(self, illumination: float, phase_angle: float | None = None) -> None:
        self.illumination = max(0.0, min(1.0, float(illumination)))
        if phase_angle is not None:
            self.phase_angle = float(phase_angle) % 360.0
        else:
            # Approximate angle from illumination if not provided
            self.phase_angle = 180.0 if self.illumination >= 0.99 else (math.acos(1.0 - 2.0 * self.illumination) * 180.0 / math.pi)
        self.update()

    def set_illumination(self, value: float) -> None:
        self.set_phase(value, None)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(12, 12, -12, -12)
        cx = rect.center().x()
        cy = rect.center().y()
        radius = min(rect.width(), rect.height()) / 2.0

        # Base dark moon disk (unlit basalt)
        painter.setPen(QPen(QColor("#334155"), 2))
        painter.setBrush(QColor("#0f172a"))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        if self.illumination <= 0.005:
            return  # New moon - completely dark

        # Waxing (0..180 deg, right side lit in Northern Hemisphere) vs Waning (180..360 deg, left side lit)
        is_waxing = self.phase_angle <= 180.0

        if self.illumination >= 0.995:
            # Full moon
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#fef08a"))
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
            return

        # Build lit crescent / gibbous path
        path = QPainterPath()
        steps = 40

        # 1. Circular limb from top (0, -R) to bottom (0, +R) on the lit side
        # Angle phi runs from -pi/2 to +pi/2
        outer_points: list[QPointF] = []
        for i in range(steps + 1):
            phi = -math.pi / 2.0 + (math.pi * i / steps)
            # x offset is positive for waxing (right side), negative for waning (left side)
            sign = 1.0 if is_waxing else -1.0
            x = cx + sign * radius * math.cos(phi)
            y = cy + radius * math.sin(phi)
            outer_points.append(QPointF(x, y))

        # 2. Terminator ellipse from bottom (0, +R) back to top (0, -R)
        # Terminator x coordinate is x = cx + R * cos(phi) * (-cos(phase_angle))
        # When phase_angle < 90 (crescent): cos(phase_angle) > 0, terminator bends towards lit limb
        # When phase_angle > 90 (gibbous): cos(phase_angle) < 0, terminator bends away from lit limb into unlit side
        terminator_factor = -math.cos(math.radians(self.phase_angle))
        inner_points: list[QPointF] = []
        for i in range(steps, -1, -1):
            phi = -math.pi / 2.0 + (math.pi * i / steps)
            sign = 1.0 if is_waxing else -1.0
            x = cx + sign * radius * math.cos(phi) * terminator_factor
            y = cy + radius * math.sin(phi)
            inner_points.append(QPointF(x, y))

        path.moveTo(outer_points[0])
        for pt in outer_points[1:]:
            path.lineTo(pt)
        for pt in inner_points:
            path.lineTo(pt)
        path.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fef08a"))  # Lunar warm yellow
        painter.drawPath(path)


class MoonView(BaseView):
    def __init__(self, store, parent=None) -> None:
        super().__init__(store, parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        self.phase_lbl = QLabel("—")
        self.phase_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_lbl.setStyleSheet("font-size: 34px; font-weight: 700; color: #0d6efd;")
        layout.addWidget(self.phase_lbl)

        self.disk = PhaseDisk()
        layout.addWidget(self.disk, alignment=Qt.AlignmentFlag.AlignCenter)

        form = QFormLayout()
        self.illum_lbl = QLabel("—")
        self.dist_lbl = QLabel("—")
        self.rise_lbl = QLabel("—")
        self.set_lbl = QLabel("—")
        self.source_lbl = QLabel("—")
        form.addRow("Illumination:", self.illum_lbl)
        form.addRow("Distance:", self.dist_lbl)
        form.addRow("Next rise (UTC):", self.rise_lbl)
        form.addRow("Next set (UTC):", self.set_lbl)
        form.addRow("Computed by:", self.source_lbl)
        layout.addLayout(form)
        layout.addStretch(1)

    def refresh(self) -> None:
        moon_state = self.store.get_setting("moon_state") or {}
        if moon_state:
            phase = moon_state.get("phase_name", "Moon")
            illum = moon_state.get("illumination")
            angle = moon_state.get("phase_angle")
            self.phase_lbl.setText(f"{phase} ({illum * 100:.0f}%)" if illum is not None else phase)
            self.disk.set_phase(illum if illum is not None else 0.0, angle)
            self.illum_lbl.setText(f"{illum * 100:.1f}%" if illum is not None else "—")
            self.dist_lbl.setText(f"{moon_state.get('distance_km', 0):,.0f} km")
            self.rise_lbl.setText(fmt_ts(moon_state.get("next_rise_utc")))
            self.set_lbl.setText(fmt_ts(moon_state.get("next_set_utc")))
            self.source_lbl.setText(moon_state.get("source", "—"))
        else:
            self.phase_lbl.setText("—")
            self.disk.set_phase(0.0)
            self.illum_lbl.setText("—")
            self.dist_lbl.setText("—")
            self.rise_lbl.setText("—")
            self.set_lbl.setText("—")
            self.source_lbl.setText("—")
