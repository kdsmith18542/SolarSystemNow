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
        if not getattr(self.store, "defer_initial_refresh", False):
            self.refresh()

    def refresh(self) -> None:
        from ssnow_core.sources.registry import all_specs

        states = {state.source_id: state for state in self.store.all_source_states()}
        specs = all_specs()
        enabled = [spec for spec in specs if spec.enabled]
        rows = []
        for spec in specs:
            state = states.get(spec.id)
            rows.append((spec, state))
        healthy = sum(
            1
            for spec, state in rows
            if spec.enabled and state is not None and state.last_success is not None and state.consecutive_failures == 0
        )
        failing = sum(1 for spec, state in rows if spec.enabled and state is not None and state.consecutive_failures > 0)
        never_run = sum(1 for spec, state in rows if spec.enabled and (state is None or state.last_attempt is None))
        summary = f"{healthy}/{len(enabled)} sources healthy"
        if failing:
            summary += f" · {failing} failing"
        if never_run:
            summary += f" · {never_run} never run"
        self.summary_lbl.setText(summary)
        self.summary_lbl.setStyleSheet(
            f"color: {theme.OK if failing == 0 else theme.WARN if failing <= 2 else theme.DANGER};"
        )

        self.table.setRowCount(len(rows))
        for row, (spec, state) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(spec.id + ("" if spec.enabled else " (disabled)")))
            self.table.setItem(row, 1, QTableWidgetItem(spec.domain))
            self.table.setItem(row, 2, QTableWidgetItem(fmt_ts(state.last_attempt) if state else "—"))
            self.table.setItem(row, 3, QTableWidgetItem(fmt_ts(state.last_success) if state else "—"))

            failures = state.consecutive_failures if state else 0
            fail_item = QTableWidgetItem(str(failures))
            fail_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            if not spec.enabled:
                fail_item.setForeground(QColor(theme.TEXT_FAINT))
            elif failures == 0:
                fail_item.setForeground(QColor(theme.OK))
            elif failures <= 2:
                fail_item.setForeground(QColor(theme.WARN))
            else:
                fail_item.setForeground(QColor(theme.DANGER))
            self.table.setItem(row, 4, fail_item)

            self.table.setItem(row, 5, QTableWidgetItem(fmt_ts(state.next_due) if state else "—"))
            last_error = state.last_error if state and state.last_error else "—"
            err_item = QTableWidgetItem(last_error)
            if last_error != "—":
                err_item.setForeground(QColor(theme.WARN))
            self.table.setItem(row, 6, err_item)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(6, 420)

    def _ingest_all(self) -> None:
        window = self.window()
        if hasattr(window, "start_ingest"):
            window.start_ingest()
