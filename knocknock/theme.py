"""Apple-style (macOS / iOS) palette and stylesheet, with light and dark themes.

Usage:
    theme.set_mode("dark")                  # switch the active theme ("light" / "dark" / "auto")
    app.setStyleSheet(theme.build_qss(13))  # build the stylesheet
    theme.palette().text_primary            # read a colour from the active theme
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtGui import QColor, QGuiApplication

from . import i18n

FONT_STACK = (
    '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", '
    '"PingFang SC", "Helvetica Neue", sans-serif'
)

MODES = ("light", "dark")


def mode_labels() -> Dict[str, str]:
    """Localised display names for the themes (including "auto").

    Theme names are user-facing copy rather than palette data, so the
    translations live in i18n; this is a thin pass-through so UI code does not
    need to import both modules.
    """
    return i18n.theme_labels()


# ---------------------------------------------------------------- palette
@dataclass(frozen=True)
class Palette:
    name: str
    is_dark: bool

    accent: str
    accent_hover: str
    accent_pressed: str
    accent_soft: str          # tinted accent background (badges, selected states)
    accent_text: str          # accent-coloured text on a tinted background

    bg_card: str
    bg_subtle: str
    bg_subtle_hover: str
    bg_subtle_pressed: str
    bg_result: str
    bg_dialog: str
    bg_field: str             # field background while focused
    bg_disabled: str

    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_on_accent: str

    border: str
    separator: str
    shadow_alpha: int

    success: str
    warning: str
    danger: str

    scrollbar: str
    scrollbar_hover: str
    tooltip_bg: str
    tooltip_text: str
    tooltip_border: str


LIGHT = Palette(
    name="light",
    is_dark=False,
    accent="#0A84FF",
    accent_hover="#0071E3",
    accent_pressed="#0060C0",
    accent_soft="rgba(10, 132, 255, 0.12)",
    accent_text="#0A84FF",
    bg_card="rgba(255, 255, 255, 0.985)",
    bg_subtle="#F2F2F7",
    bg_subtle_hover="#E8E8ED",
    bg_subtle_pressed="#DCDCE1",
    bg_result="#FAFAFC",
    bg_dialog="#FFFFFF",
    bg_field="#FFFFFF",
    bg_disabled="#C7C7CC",
    text_primary="#1D1D1F",
    text_secondary="#6E6E73",
    text_tertiary="#8E8E93",
    text_on_accent="#FFFFFF",
    border="rgba(0, 0, 0, 0.07)",
    separator="#EDEDF0",
    shadow_alpha=48,
    success="#34C759",
    warning="#FF9F0A",
    danger="#FF3B30",
    scrollbar="rgba(0, 0, 0, 0.18)",
    scrollbar_hover="rgba(0, 0, 0, 0.30)",
    tooltip_bg="#FFFFFF",
    tooltip_text="#1D1D1F",
    tooltip_border="rgba(0, 0, 0, 0.12)",
)

DARK = Palette(
    name="dark",
    is_dark=True,
    accent="#0A84FF",
    accent_hover="#3D9BFF",
    accent_pressed="#0060C0",
    accent_soft="rgba(10, 132, 255, 0.22)",
    accent_text="#64B5FF",
    bg_card="rgba(30, 30, 32, 0.985)",
    bg_subtle="#2C2C2E",
    bg_subtle_hover="#3A3A3C",
    bg_subtle_pressed="#48484A",
    bg_result="#232326",
    bg_dialog="#1E1E20",
    bg_field="#2C2C2E",
    bg_disabled="#48484A",
    text_primary="#F2F2F7",
    text_secondary="#A1A1A6",
    text_tertiary="#8E8E93",
    text_on_accent="#FFFFFF",
    border="rgba(255, 255, 255, 0.10)",
    separator="#3A3A3C",
    shadow_alpha=105,
    success="#30D158",
    warning="#FFD60A",
    danger="#FF453A",
    scrollbar="rgba(255, 255, 255, 0.22)",
    scrollbar_hover="rgba(255, 255, 255, 0.36)",
    tooltip_bg="#3A3A3C",
    tooltip_text="#F2F2F7",
    tooltip_border="rgba(255, 255, 255, 0.14)",
)

_PALETTES = {"light": LIGHT, "dark": DARK}
_current = "light"


# ---------------------------------------------------------------- theme state
def system_mode() -> str:
    """Return the current OS colour scheme (colorScheme() needs Qt 6.5+)."""
    try:
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme()
        if scheme == scheme.ColorScheme.Dark:
            return "dark"
        if scheme == scheme.ColorScheme.Light:
            return "light"
    except (AttributeError, RuntimeError):
        pass
    return "light"


def resolve_mode(setting: Optional[str]) -> str:
    """Resolve a configured theme value (possibly "auto") to "light" / "dark"."""
    value = (setting or "light").strip().lower()
    if value == "auto":
        return system_mode()
    return value if value in MODES else "light"


def set_mode(setting: Optional[str]) -> str:
    """Set the active theme and return the mode that actually took effect."""
    global _current
    _current = resolve_mode(setting)
    return _current


def mode() -> str:
    return _current


def palette() -> Palette:
    return _PALETTES[_current]


def is_dark() -> bool:
    return palette().is_dark


def shadow_color() -> QColor:
    color = QColor(0, 0, 0)
    color.setAlpha(palette().shadow_alpha)
    return color


# ---------------------------------------------------------------- stylesheet
def build_qss(font_size: int = 13, mode_setting: Optional[str] = None) -> str:
    """Return the application stylesheet. Passing mode_setting also switches the theme."""
    if mode_setting is not None:
        set_mode(mode_setting)

    p = palette()
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: {font_size}px;
    color: {p.text_primary};
}}

QWidget {{
    background: transparent;
}}

/* Dialogs and message boxes need an opaque background, otherwise the desktop shows through */
QDialog, QMessageBox {{
    background: {p.bg_dialog};
}}
QMessageBox QLabel {{
    color: {p.text_primary};
}}
QMessageBox QPushButton {{
    background: {p.bg_subtle};
    color: {p.text_primary};
    border: none;
    border-radius: 8px;
    padding: 6px 18px;
    min-width: 64px;
}}
QMessageBox QPushButton:hover {{ background: {p.bg_subtle_hover}; }}

/* ---------------------------------------------------- settings dialog tabs */
QTabWidget::pane {{
    border: 1px solid {p.separator};
    border-radius: 10px;
    background: {p.bg_dialog};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 7px 14px;
    margin-right: 4px;
    border-radius: 8px;
    color: {p.text_secondary};
}}
QTabBar::tab:hover {{ color: {p.text_primary}; }}
QTabBar::tab:selected {{
    background: {p.bg_subtle};
    color: {p.text_primary};
    font-weight: 600;
}}

/* ---------------------------------------------------- main card */
QFrame#Card {{
    background: {p.bg_card};
    border: 1px solid {p.border};
    border-radius: 16px;
}}

/* ---------------------------------------------------- header */
QLabel#Title {{
    font-size: {font_size + 1}px;
    font-weight: 600;
    color: {p.text_primary};
}}
QLabel#Subtitle {{
    color: {p.text_tertiary};
    font-size: {font_size - 2}px;
}}
QLabel#Hint {{
    color: {p.text_tertiary};
    font-size: {font_size - 2}px;
}}

/* ---------------------------------------------------- icon buttons */
QPushButton#IconBtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0px;
}}
QPushButton#IconBtn:hover {{
    background: {p.bg_subtle};
}}
QPushButton#IconBtn:pressed {{
    background: {p.bg_subtle_hover};
}}
QPushButton#IconBtn:checked {{
    background: {p.accent_soft};
}}

/* ---------------------------------------------------- preset chips */
QPushButton#Chip {{
    background: {p.bg_subtle};
    border: none;
    border-radius: 13px;
    padding: 5px 12px;
    color: {p.text_primary};
    font-size: {font_size - 1}px;
}}
QPushButton#Chip:hover {{
    background: {p.bg_subtle_hover};
}}
QPushButton#Chip:pressed {{
    background: {p.bg_subtle_pressed};
}}

/* ---------------------------------------------------- primary / ghost buttons */
QPushButton#Primary {{
    background: {p.accent};
    color: {p.text_on_accent};
    border: none;
    border-radius: 10px;
    padding: 7px 18px;
    font-weight: 600;
}}
QPushButton#Primary:hover   {{ background: {p.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {p.accent_pressed}; }}
QPushButton#Primary:disabled {{ background: {p.bg_disabled}; color: {p.text_on_accent}; }}

QPushButton#Ghost {{
    background: transparent;
    color: {p.text_secondary};
    border: none;
    border-radius: 10px;
    padding: 7px 12px;
}}
QPushButton#Ghost:hover {{ background: {p.bg_subtle}; }}
QPushButton#Ghost:disabled {{ color: {p.bg_disabled}; }}

/* ---------------------------------------------------- text input */
QTextEdit#Input {{
    background: {p.bg_subtle};
    color: {p.text_primary};
    border: 1px solid transparent;
    border-radius: 11px;
    padding: 8px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}
QTextEdit#Input:focus {{
    background: {p.bg_field};
    border: 1px solid {p.accent};
}}

/* ---------------------------------------------------- context preview */
QFrame#Context {{
    background: {p.bg_subtle};
    border: none;
    border-radius: 11px;
}}
QLabel#ContextText {{
    color: {p.text_secondary};
    font-size: {font_size - 1}px;
}}
QLabel#Badge {{
    background: {p.accent_soft};
    color: {p.accent_text};
    border-radius: 6px;
    padding: 1px 7px;
    font-size: {font_size - 3}px;
    font-weight: 600;
}}

/* ---------------------------------------------------- result area */
QTextBrowser#Result {{
    background: {p.bg_result};
    color: {p.text_primary};
    border: 1px solid {p.separator};
    border-radius: 11px;
    padding: 8px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}
QTextBrowser#Result a {{ color: {p.accent_text}; }}

/* ---------------------------------------------------- scrollbars */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px 4px 0px;
}}
QScrollBar::handle:vertical {{
    background: {p.scrollbar};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {p.scrollbar_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0px 4px 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p.scrollbar};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {p.scrollbar_hover}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------------------------------------------------- separator */
QFrame#Separator {{
    background: {p.separator};
    border: none;
    max-height: 1px;
}}

/* ---------------------------------------------------- tray menu / tooltip */
QMenu {{
    background: {p.bg_dialog};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 26px 6px 12px;
    border-radius: 6px;
    color: {p.text_primary};
}}
QMenu::item:selected {{
    background: {p.accent};
    color: {p.text_on_accent};
}}
QMenu::item:disabled {{ color: {p.text_tertiary}; }}
QMenu::separator {{
    height: 1px;
    background: {p.separator};
    margin: 5px 8px;
}}
QToolTip {{
    background: {p.tooltip_bg};
    color: {p.tooltip_text};
    border: 1px solid {p.tooltip_border};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ---------------------------------------------------- settings dialog */
QDialog#Settings {{
    background: {p.bg_dialog};
}}
QLabel#FieldLabel {{
    color: {p.text_secondary};
    font-size: {font_size - 1}px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.bg_subtle};
    color: {p.text_primary};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    background: {p.bg_field};
    border: 1px solid {p.accent};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.bg_dialog};
    color: {p.text_primary};
    border: 1px solid {p.border};
    border-radius: 8px;
    selection-background-color: {p.accent};
    selection-color: {p.text_on_accent};
    outline: none;
}}
QCheckBox {{ spacing: 7px; color: {p.text_primary}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid {p.bg_disabled};
    background: {p.bg_field};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border: 1px solid {p.accent};
    image: none;
}}
QTableWidget {{
    background: {p.bg_result};
    color: {p.text_primary};
    border: 1px solid {p.separator};
    border-radius: 9px;
    gridline-color: {p.separator};
}}
QHeaderView::section {{
    background: {p.bg_subtle};
    border: none;
    border-bottom: 1px solid {p.separator};
    padding: 6px;
    color: {p.text_secondary};
}}
QTextEdit#SystemPrompt {{
    background: {p.bg_subtle};
    color: {p.text_primary};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 9px;
}}
QTextEdit#SystemPrompt:focus {{ background: {p.bg_field}; border: 1px solid {p.accent}; }}
"""
