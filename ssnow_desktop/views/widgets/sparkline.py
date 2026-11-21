"""Simple sparkline chart widget."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ... import theme


class Sparkline(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.points: list[QPointF] = []
        self.min_value = 0.0
        self.max_value = 1.0
        self.color = QColor(theme.ACCENT)
        self.fill_color = QColor(56, 189, 248, 40)
        self.setMinimumHeight(70)

    def set_points(self, points: list[tuple[float, float]], min_value: float | None = None, max_value: float | None = None) -> None:
        self.points = [QPointF(x, y) for x, y in points]
        if min_value is not None:
            self.min_value = min_value
        if max_value is not None:
            self.max_value = max_value
        self.update()

    def paintEvent(self, event) -> None:
        if len(self.points) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = self.min_value, self.max_value
        if y_max == y_min:
            y_max = y_min + 1.0

        def to_pixel(p: QPointF) -> QPointF:
            nx = (p.x() - x_min) / (x_max - x_min) if x_max > x_min else 0.5
            ny = 1.0 - (p.y() - y_min) / (y_max - y_min)
            return QPointF(rect.left() + nx * rect.width(), rect.top() + ny * rect.height())

        pixels = [to_pixel(p) for p in self.points]

        from PySide6.QtGui import QPainterPath

        fill = QPainterPath()
        fill.moveTo(rect.left(), rect.bottom())
        for p in pixels:
            fill.lineTo(p)
        fill.lineTo(rect.right(), rect.bottom())
        fill.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.color.red(), self.color.green(), self.color.blue(), 40))
        painter.drawPath(fill)

        pen = QPen(self.color, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(1, len(pixels)):
            painter.drawLine(pixels[i - 1], pixels[i])
        for p in pixels:
            painter.drawEllipse(p, 3, 3)
