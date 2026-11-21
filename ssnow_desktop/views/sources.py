"""Sources health view."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from .. import theme
from .base_view import BaseView


def fmt_ts(value) -> str:
    if value is None:
        return "—"
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class SourcesView(BaseView):
    def __init__(self, store) -> None:
        super().__init__(store)
        layout = QVBoxLayout(self)

        summary = QHBoxLayout()
        self.summary_lbl = QLabel("—")
        self.summary_lbl.setObjectName("h2")
        summary.addWidget(self.summary_lbl)
        summary.addStretch(1)
        self.refresh_btn = QPushButton("Ingest all due now")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(self._ingest_all)
        summary.addWidget(self.refresh_btn)
        layout.addLayout(summary)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Source", "Domain", "Last attempt", "Last success", "Failures", "Next due", "Last error"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        states = self.store.all_source_states()
        enabled_flags = []
        for state in states:
            try:
                from ssnow_core.sources.registry import spec_for

                enabled_flags.append(bool(spec_for(state.source_id).enabled))
            except Exception:
                enabled_flags.append(True)
        enabled = [s for s, en in zip(states, enabled_flags) if en]
        healthy = [s for s in enabled if s.consecutive_failures == 0]
        failing = len(enabled) - len(healthy)
        if failing == 0:
            self.summary_lbl.setText(f"{len(healthy)}/{len(enabled)} sources healthy")
            self.summary_lbl.setStyleSheet(f"color: {theme.OK};")
        else:
            self.summary_lbl.setText(f"{len(healthy)}/{len(enabled)} sources healthy · {failing} failing")
            self.summary_lbl.setStyleSheet(f"color: {theme.WARN if failing <= 2 else theme.DANGER};")

        self.table.setRowCount(len(states))
        for row, (state, is_enabled) in enumerate(zip(states, enabled_flags)):
            self.table.setItem(row, 0, QTableWidgetItem(state.source_id))
            spec = None
            try:
                from ssnow_core.sources.registry import spec_for

                spec = spec_for(state.source_id)
            except Exception:
                spec = None
            domain = spec.domain if spec else "—"
            self.table.setItem(row, 1, QTableWidgetItem(domain))
            self.table.setItem(row, 2, QTableWidgetItem(fmt_ts(state.last_attempt)))
            self.table.setItem(row, 3, QTableWidgetItem(fmt_ts(state.last_success)))

            fails = str(state.consecutive_failures)
            fail_item = QTableWidgetItem(fails)
            fail_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if not is_enabled:
                fail_item.setForeground(QColor(theme.TEXT_FAINT))
            elif state.consecutive_failures == 0:
                fail_item.setForeground(QColor(theme.OK))
            elif state.consecutive_failures <= 2:
                fail_item.setForeground(QColor(theme.WARN))
            else:
                fail_item.setForeground(QColor(theme.DANGER))
            self.table.setItem(row, 4, fail_item)

            self.table.setItem(row, 5, QTableWidgetItem(fmt_ts(state.next_due)))
            err_item = QTableWidgetItem(state.last_error or "—")
            if state.last_error:
                err_item.setForeground(QColor(theme.WARN))
            self.table.setItem(row, 6, err_item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(6, 420)

    def _ingest_all(self) -> None:
        window = self.window()
        if hasattr(window, "start_ingest"):
            window.start_ingest()
