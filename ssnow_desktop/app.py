"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ssnow_core.config import config_dir
from ssnow_core.logging_config import setup_logging

from . import theme
from .main_window import MainWindow


def run(argv=None) -> int:
    setup_logging(log_dir=config_dir() / "logs")
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Solar System Now")
    app.setOrganizationName("ss-now")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
