"""Shared visual theme for the desktop app (dark mission-control palette).

One palette, one stylesheet, applied at QApplication level. Views must not
hard-code light colors: use object names (card, cardValue, cardMeta, chip...)
and the semantic constants below so the whole app stays consistent.
"""

from __future__ import annotations

# ---- palette ---------------------------------------------------------------
BG = "#070b14"
BG_ALT = "#0b1220"
PANEL = "#0f172a"
PANEL_ALT = "#131d33"
BORDER = "#1e293b"
BORDER_HI = "#334155"
TEXT = "#e2e8f0"
TEXT_DIM = "#94a3b8"
TEXT_FAINT = "#64748b"

ACCENT = "#38bdf8"      # cyan — primary/nominal
OK = "#4ade80"          # green — quiet/healthy
WARN = "#fbbf24"        # amber — elevated
DANGER = "#f87171"      # red — storm/critical
VIOLET = "#a78bfa"      # geomagnetic
PINK = "#f472b6"        # CME
ORANGE = "#fb923c"      # fireball
LIME = "#a3e635"        # asteroids

FONT_STACK = '"Inter", "Segoe UI", "Noto Sans", system-ui, sans-serif'
MONO_STACK = '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace'

# Severity -> color, used by cards, chips and the threat dial.
SEVERITY = {
    "quiet": OK,
    "unsettled": WARN,
    "elevated": ORANGE,
    "storm": DANGER,
    "info": ACCENT,
}

STYLESHEET = f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background: {BG};
}}
QLabel {{
    background: transparent;
}}
QLabel#h1 {{ font-size: 26px; font-weight: 700; color: {TEXT}; }}
QLabel#h2 {{ font-size: 17px; font-weight: 600; color: {TEXT}; }}
QLabel#cardTitle {{
    font-size: 11px; font-weight: 700; color: {TEXT_DIM};
    text-transform: uppercase; letter-spacing: 1px;
}}
QLabel#cardValue {{ font-size: 30px; font-weight: 700; color: {TEXT}; }}
QLabel#cardMeta {{ font-size: 11px; color: {TEXT_FAINT}; }}
QLabel#chip {{
    font-size: 11px; font-weight: 700; color: {BG};
    background: {ACCENT}; border-radius: 9px; padding: 2px 10px;
}}
QLabel#muted {{ color: {TEXT_DIM}; }}
QLabel#faint {{ color: {TEXT_FAINT}; font-size: 11px; }}
QLabel#source {{ color: {TEXT_FAINT}; font-size: 10px; }}
QLabel#streamValue {{ font-size: 24px; font-weight: 800; }}
QLabel#streamLabel {{ font-size: 10px; font-weight: 700; color: {TEXT_FAINT}; letter-spacing: 1px; }}
QLabel#streamTitle {{ font-size: 12px; font-weight: 700; color: {TEXT_DIM}; letter-spacing: 2px; }}

QFrame#card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#streamBanner {{
    background: {BG_ALT};
    border-top: 1px solid {BORDER_HI};
}}
QFrame#toolbar {{
    background: {BG_ALT};
    border-bottom: 1px solid {BORDER};
}}

QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER_HI};
    border-radius: 7px;
    padding: 6px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {BORDER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BG_ALT}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
QPushButton#primary {{
    background: {ACCENT}; color: {BG}; border: none; font-weight: 700;
}}
QPushButton#primary:hover {{ background: #7dd3fc; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER_HI};
    border-radius: 7px;
    padding: 5px 9px;
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT}; border: 1px solid {BORDER_HI};
    selection-background-color: {BORDER}; outline: none;
}}

QCheckBox {{ spacing: 7px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER_HI}; background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QListWidget#sidebar {{
    background: {BG_ALT};
    border: none;
    font-size: 13px;
    outline: none;
}}
QListWidget#sidebar::item {{
    padding: 10px 16px;
    border-bottom: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QListWidget#sidebar::item:hover {{ background: {PANEL}; color: {TEXT}; }}
QListWidget#sidebar::item:selected {{
    background: {PANEL_ALT};
    color: {ACCENT};
    border-left: 3px solid {ACCENT};
}}

QTableWidget {{
    background: {PANEL};
    alternate-background-color: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: {BORDER_HI};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {BG_ALT};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER_HI};
    padding: 7px 9px;
    font-size: 11px;
    font-weight: 700;
}}
QTableWidget::item {{ padding: 4px 8px; }}

QTextBrowser {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; border-radius: 5px; min-width: 24px; }}

QToolTip {{
    background: {PANEL_ALT}; color: {TEXT};
    border: 1px solid {BORDER_HI}; padding: 4px 8px;
}}
QMessageBox {{ background: {PANEL}; }}
"""


def card_style(accent: str | None = None) -> str:
    """Per-card frame style with an optional severity accent rail."""
    rail = accent or BORDER
    return (
        f"QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER};"
        f" border-left: 3px solid {rail}; border-radius: 10px; }}"
    )
