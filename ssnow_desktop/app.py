"""Desktop application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run(argv=None) -> int:
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Solar System Now")
    app.setOrganizationName("ss-now")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
