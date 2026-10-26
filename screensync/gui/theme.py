"""Colour tokens and the application stylesheet.

The palette follows the app icon: a deep night-blue base with a cyan → violet
→ pink → amber glow used sparingly for accents and live light previews.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


GLOW = ("#22D3EE", "#7C5CFF", "#EC4899", "#FB923C")


@dataclass(frozen=True)
class Tokens:
    dark: bool
    window: str
    sidebar: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    text: str
    secondary: str
    tertiary: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_soft: str
    success: str
    success_soft: str
    danger: str
    danger_soft: str
    warning: str


DARK = Tokens(
    dark=True,
    window="#0B0E1A",
    sidebar="#0E1222",
    surface="#141a2e",
    surface_alt="#1B2139",
    surface_hover="#222944",
    border="#262E4A",
    text="#EEF0FA",
    secondary="#A0A8C4",
    tertiary="#6C7495",
    accent="#7C5CFF",
    accent_hover="#9177FF",
    accent_text="#FFFFFF",
    accent_soft="#2A2457",
    success="#34D399",
    success_soft="#123A33",
    danger="#F87171",
    danger_soft="#3D1C26",
    warning="#FBBF24",
)

LIGHT = Tokens(
    dark=False,
    window="#F4F5FA",
    sidebar="#EBEDF6",
    surface="#FFFFFF",
    surface_alt="#F5F6FB",
    surface_hover="#ECEEF7",
    border="#E0E3EE",
    text="#141826",
    secondary="#596079",
    tertiary="#8A90A6",
    accent="#6A4CF5",
    accent_hover="#5A3CE8",
    accent_text="#FFFFFF",
    accent_soft="#ECE8FF",
    success="#0E9F6E",
    success_soft="#E3F6EE",
    danger="#DC3B3B",
    danger_soft="#FDECEC",
    warning="#B7791F",
)


def system_prefers_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return True
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        value = scheme()
        if value == Qt.ColorScheme.Dark:
            return True
        if value == Qt.ColorScheme.Light:
            return False
    return app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def current_tokens() -> Tokens:
    return DARK if system_prefers_dark() else LIGHT


def palette_for(tokens: Tokens) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens.window,
        QPalette.ColorRole.WindowText: tokens.text,
        QPalette.ColorRole.Base: tokens.surface_alt,
        QPalette.ColorRole.AlternateBase: tokens.surface,
        QPalette.ColorRole.Text: tokens.text,
        QPalette.ColorRole.Button: tokens.surface_alt,
        QPalette.ColorRole.ButtonText: tokens.text,
        QPalette.ColorRole.Highlight: tokens.accent,
        QPalette.ColorRole.HighlightedText: tokens.accent_text,
        QPalette.ColorRole.ToolTipBase: tokens.surface_alt,
        QPalette.ColorRole.ToolTipText: tokens.text,
        QPalette.ColorRole.PlaceholderText: tokens.tertiary,
        QPalette.ColorRole.Link: tokens.accent,
    }
    for role, colour in roles.items():
        palette.setColor(role, QColor(colour))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens.tertiary))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens.tertiary))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(tokens.tertiary))
    return palette


def stylesheet(t: Tokens) -> str:
    return f"""
* {{
    outline: none;
}}
QWidget {{
    color: {t.text};
    font-size: 13px;
}}
QMainWindow, QDialog, QWidget#Content {{
    background: {t.window};
}}
QWidget#Sidebar {{
    background: {t.sidebar};
    border-right: 1px solid {t.border};
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QFrame[card="true"] {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 16px;
}}
QFrame[inset="true"] {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 12px;
}}
QFrame[inset="true"][selected="true"] {{
    border: 2px solid {t.accent};
}}
QFrame[inset="true"][clickable="true"]:hover {{
    background: {t.surface_hover};
}}
QFrame[divider="true"] {{
    background: {t.border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

QLabel {{
    background: transparent;
}}
QLabel[role="display"] {{
    font-size: 26px;
    font-weight: 700;
}}
QLabel[role="title"] {{
    font-size: 17px;
    font-weight: 650;
}}
QLabel[role="heading"] {{
    font-size: 14px;
    font-weight: 650;
}}
QLabel[role="subtitle"] {{
    color: {t.secondary};
    font-size: 13px;
}}
QLabel[role="caption"] {{
    color: {t.tertiary};
    font-size: 11px;
    font-weight: 650;
    letter-spacing: 0.6px;
}}
QLabel[role="hint"] {{
    color: {t.secondary};
    font-size: 12px;
}}
QLabel[role="value"] {{
    font-size: 13px;
    font-weight: 600;
}}
QLabel[role="metric"] {{
    font-size: 20px;
    font-weight: 650;
}}
QLabel[role="mono"] {{
    color: {t.secondary};
    font-family: "SF Mono", "Cascadia Mono", "Consolas", "Menlo", monospace;
    font-size: 12px;
}}
QLabel[role="brand"] {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel[badge="true"] {{
    background: {t.accent_soft};
    color: {t.accent if not t.dark else t.text};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 650;
}}
QLabel[badge="live"] {{
    background: {t.success_soft};
    color: {t.success};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#Toast {{
    background: {t.surface_hover};
    border: 1px solid {t.border};
    border-radius: 12px;
    padding: 10px 16px;
    font-weight: 600;
}}
QLabel#Toast[level="error"] {{
    background: {t.danger_soft};
    color: {t.danger};
}}
QLabel#Toast[level="success"] {{
    background: {t.success_soft};
    color: {t.success};
}}

QPushButton {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {t.surface_hover};
}}
QPushButton:disabled {{
    color: {t.tertiary};
}}
QPushButton[kind="primary"] {{
    background: {t.accent};
    border: 1px solid {t.accent};
    color: {t.accent_text};
}}
QPushButton[kind="primary"]:hover {{
    background: {t.accent_hover};
    border-color: {t.accent_hover};
}}
QPushButton[kind="danger"] {{
    background: {t.danger_soft};
    border: 1px solid {t.danger_soft};
    color: {t.danger};
}}
QPushButton[kind="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.secondary};
}}
QPushButton[kind="ghost"]:hover {{
    background: {t.surface_hover};
    color: {t.text};
}}
QPushButton[kind="hero"] {{
    background: {t.accent};
    border: none;
    color: {t.accent_text};
    border-radius: 14px;
    padding: 12px 26px;
    font-size: 14px;
    font-weight: 700;
}}
QPushButton[kind="hero"]:hover {{
    background: {t.accent_hover};
}}
QPushButton[kind="hero"][running="true"] {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    color: {t.text};
}}
QPushButton[kind="hero"][running="true"]:hover {{
    background: {t.danger_soft};
    border-color: {t.danger_soft};
    color: {t.danger};
}}
QPushButton[segment="true"] {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px 12px;
    color: {t.secondary};
}}
QPushButton[segment="true"]:hover {{
    color: {t.text};
}}
QPushButton[segment="true"]:checked {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
}}
QFrame#SegmentTrack {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
}}
QPushButton[section="true"] {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 6px 2px;
    font-size: 14px;
    font-weight: 650;
}}
QPushButton[link="true"] {{
    background: transparent;
    border: none;
    color: {t.accent if not t.dark else t.accent_hover};
    padding: 2px 0;
    text-align: left;
}}
QPushButton[link="true"]:hover {{
    text-decoration: underline;
}}

QComboBox {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 7px 12px;
    min-width: 150px;
}}
QComboBox:hover {{
    background: {t.surface_hover};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {t.surface};
    border: 1px solid {t.border};
    selection-background-color: {t.accent_soft};
    selection-color: {t.text};
    padding: 4px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: 10px;
    padding: 8px 10px;
    selection-background-color: {t.accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {t.accent};
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {t.surface_hover};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {t.accent};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 1px solid {t.border};
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    border: 2px solid {t.accent};
}}
QSlider::sub-page:horizontal:disabled {{
    background: {t.tertiary};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border};
    border-radius: 3px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.tertiary};
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    height: 0;
}}

QListWidget {{
    background: transparent;
    border: none;
}}
QToolTip {{
    background: {t.surface_alt};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 6px 8px;
}}
QMenu {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {t.accent_soft};
}}
"""
