"""Base view class."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


class BaseView(QWidget):
    def __init__(self, store, parent=None) -> None:
        super().__init__(parent)
        self.store = store

    def refresh(self) -> None:
        return None
