"""Sources health view."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

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
        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh now")
        self.refresh_btn.clicked.connect(self._ingest_all)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Source", "Domain", "Last attempt", "Last success", "Failures", "Next due", "Last error"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        states = self.store.all_source_states()
        self.table.setRowCount(len(states))
        for row, state in enumerate(states):
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
            self.table.setItem(row, 4, QTableWidgetItem(str(state.consecutive_failures)))
            self.table.setItem(row, 5, QTableWidgetItem(fmt_ts(state.next_due)))
            self.table.setItem(row, 6, QTableWidgetItem(state.last_error or "—"))

    def _ingest_all(self) -> None:
        window = self.window()
        if hasattr(window, "start_ingest"):
            window.start_ingest()
