"""Colors, fonts and the application style sheet."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from cocseq.utils import resource_path

UI_FONT = "Pretendard"
MONO_FONT = "JetBrains Mono"

ACCENT_PRESETS = {
    "코랄": "#FF7A45",
    "블루": "#4C8DFF",
    "민트": "#2FD1B0",
    "바이올렛": "#9C7BFF",
    "로즈": "#FF5C8A",
    "앰버": "#FFB23F",
}


@dataclass
class Palette:
    bg0: str = "#0B0C0F"      # viewer surround
    bg1: str = "#111318"      # window
    bg2: str = "#161920"      # panels, bars
    bg3: str = "#1D2129"      # inputs, cards
    bg4: str = "#252A33"      # hover
    bg5: str = "#2F3540"      # pressed
    line: str = "#262B34"
    line2: str = "#343B47"
    text: str = "#E8EAEE"
    text2: str = "#A2A8B3"
    text3: str = "#6C737F"
    accent: str = "#FF7A45"
    b: str = "#38C6F4"        # compare "B" clip
    ok: str = "#3DD68C"
    warn: str = "#FFC857"
    err: str = "#FF5C6C"

    def accent_hover(self) -> str:
        return QColor(self.accent).lighter(115).name()

    def accent_pressed(self) -> str:
        return QColor(self.accent).darker(115).name()

    def rgba(self, color: str, alpha: float) -> str:
        c = QColor(color)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"

    def qcolor(self, name: str, alpha: float = 1.0) -> QColor:
        c = QColor(getattr(self, name))
        c.setAlphaF(alpha)
        return c


PAL = Palette()


def set_accent(color: str) -> None:
    if QColor(color).isValid():
        PAL.accent = QColor(color).name()


def load_fonts() -> None:
    folder = resource_path("assets", "fonts")
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith((".otf", ".ttf")):
            QFontDatabase.addApplicationFont(os.path.join(folder, name))


def ui_font(size: float = 9.5, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(UI_FONT)
    f.setFamilies([UI_FONT, "Malgun Gothic", "Segoe UI", "Apple SD Gothic Neo", "Noto Sans CJK KR"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting if sys.platform == "darwin" else QFont.PreferVerticalHinting)
    return f


def mono_font(size: float = 9.0, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(MONO_FONT)
    f.setFamilies([MONO_FONT, "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setStyleHint(QFont.Monospace)
    return f


def apply_palette(app: QApplication) -> None:
    p = QPalette()
    c = PAL.qcolor
    p.setColor(QPalette.Window, c("bg1"))
    p.setColor(QPalette.WindowText, c("text"))
    p.setColor(QPalette.Base, c("bg3"))
    p.setColor(QPalette.AlternateBase, c("bg2"))
    p.setColor(QPalette.Text, c("text"))
    p.setColor(QPalette.PlaceholderText, c("text3"))
    p.setColor(QPalette.Button, c("bg3"))
    p.setColor(QPalette.ButtonText, c("text"))
    p.setColor(QPalette.BrightText, c("text"))
    p.setColor(QPalette.Highlight, c("accent"))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ToolTipBase, c("bg4"))
    p.setColor(QPalette.ToolTipText, c("text"))
    p.setColor(QPalette.Link, c("accent"))
    p.setColor(QPalette.Mid, c("line2"))
    p.setColor(QPalette.Dark, c("bg0"))
    p.setColor(QPalette.Light, c("bg5"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c("text3"))
    app.setPalette(p)


def style_sheet() -> str:
    P = PAL
    acc = P.accent
    acc_soft = P.rgba(acc, 0.16)
    acc_line = P.rgba(acc, 0.55)
    return f"""
* {{
    outline: 0;
}}
QWidget {{
    color: {P.text};
    font-family: "{UI_FONT}", "Malgun Gothic", "Segoe UI";
    font-size: 12px;
}}
QMainWindow, QDialog {{
    background: {P.bg1};
}}
QMainWindow::separator {{
    background: {P.line};
    width: 1px; height: 1px;
}}
QToolTip {{
    background: {P.bg4};
    color: {P.text};
    border: 1px solid {P.line2};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ---------- menus ---------- */
QMenuBar {{
    background: {P.bg1};
    border: none;
    padding: 2px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
    border-radius: 6px;
    color: {P.text2};
}}
QMenuBar::item:selected {{ background: {P.bg4}; color: {P.text}; }}
QMenuBar::item:pressed {{ background: {P.bg5}; color: {P.text}; }}
QMenu {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 6px;
    color: {P.text};
}}
QMenu::item:selected {{ background: {acc_soft}; color: {P.text}; }}
QMenu::item:disabled {{ color: {P.text3}; }}
QMenu::separator {{ height: 1px; background: {P.line2}; margin: 5px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::indicator:checked {{
    image: none;
    background: {acc};
    border-radius: 4px;
}}
QMenu::right-arrow {{ width: 8px; height: 8px; }}

/* ---------- bars ---------- */
QToolBar {{
    background: {P.bg2};
    border: none;
    border-bottom: 1px solid {P.line};
    spacing: 4px;
    padding: 4px 8px;
}}
QToolBar::separator {{
    background: {P.line2};
    width: 1px;
    margin: 6px 6px;
}}
QToolBar QToolButton#qt_toolbar_ext_button {{
    background: {P.bg3};
    border-radius: 6px;
}}
QStatusBar {{
    background: {P.bg2};
    border-top: 1px solid {P.line};
    color: {P.text2};
    min-height: 24px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {P.text2}; padding: 0 6px; }}

/* ---------- buttons ---------- */
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px;
    color: {P.text2};
}}
QToolButton:hover {{ background: {P.bg4}; color: {P.text}; }}
QToolButton:pressed {{ background: {P.bg5}; }}
QToolButton:checked {{
    background: {acc_soft};
    color: {acc};
    border: 1px solid {P.rgba(acc, 0.35)};
}}
QToolButton:disabled {{ color: {P.text3}; }}
QToolButton[popupMode="1"], QToolButton[popupMode="2"] {{ padding-right: 14px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[role="text"] {{
    padding: 4px 10px;
    background: {P.bg3};
    border: 1px solid {P.line};
    color: {P.text};
}}
QToolButton[role="text"]:hover {{ background: {P.bg4}; }}

QPushButton {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 7px;
    padding: 6px 14px;
    color: {P.text};
    min-height: 16px;
}}
QPushButton:hover {{ background: {P.bg4}; border-color: {P.line2}; }}
QPushButton:pressed {{ background: {P.bg5}; }}
QPushButton:checked {{ background: {acc_soft}; border-color: {acc_line}; color: {acc}; }}
QPushButton:disabled {{ color: {P.text3}; background: {P.bg2}; border-color: {P.line}; }}
QPushButton[variant="primary"] {{
    background: {acc};
    border: 1px solid {acc};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {P.accent_hover()}; border-color: {P.accent_hover()}; }}
QPushButton[variant="primary"]:pressed {{ background: {P.accent_pressed()}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {P.text2}; }}
QPushButton[variant="ghost"]:hover {{ background: {P.bg4}; color: {P.text}; }}
QPushButton[variant="danger"] {{ color: {P.err}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QKeySequenceEdit {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {acc};
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {P.line2}; background: {P.bg4}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {acc_line};
    background: {P.bg3};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {P.text3}; background: {P.bg2}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0; border: none;
}}
QLineEdit[role="frame"] {{
    font-family: "{MONO_FONT}", "Consolas";
    font-size: 13px;
    font-weight: 500;
    background: {P.bg1};
    border: 1px solid {P.line2};
    padding: 3px 6px;
    color: {P.text};
}}

QComboBox {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 7px;
    padding: 4px 26px 4px 9px;
    min-height: 18px;
    color: {P.text};
}}
QComboBox:hover {{ background: {P.bg4}; }}
QComboBox:on {{ border-color: {acc_line}; }}
QComboBox:disabled {{ color: {P.text3}; background: {P.bg2}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url("{_chevron_path()}");
    width: 10px; height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {acc_soft};
    selection-color: {P.text};
    outline: 0;
}}
QComboBox QAbstractItemView::item {{
    min-height: 24px;
    padding: 2px 8px;
    border-radius: 5px;
}}
QComboBox[role="toolbar"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {P.text2};
    padding-left: 6px;
}}
QComboBox[role="toolbar"]:hover {{ background: {P.bg4}; color: {P.text}; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {P.text}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px;
    background: {P.bg3};
    border: 1px solid {P.line2};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {acc_line}; }}
QCheckBox::indicator:checked {{
    background: {acc};
    border-color: {acc};
    image: url("{_check_path()}");
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 #FFFFFF, stop:0.35 #FFFFFF, stop:0.45 {acc}, stop:1 {acc});
    border-color: {acc};
}}
QCheckBox:disabled {{ color: {P.text3}; }}

QSlider::groove:horizontal {{
    height: 4px;
    background: {P.bg5};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {acc};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 3px solid {acc};
    width: 8px; height: 8px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ border-width: 2px; width: 10px; height: 10px; margin: -6px 0; }}
QSlider::groove:vertical {{ width: 4px; background: {P.bg5}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {acc}; border-radius: 2px; }}
QSlider::handle:vertical {{
    background: #FFFFFF; border: 3px solid {acc};
    width: 8px; height: 8px; margin: 0 -6px; border-radius: 7px;
}}

QProgressBar {{
    background: {P.bg3};
    border: 1px solid {P.line};
    border-radius: 6px;
    text-align: center;
    color: {P.text};
    min-height: 14px;
}}
QProgressBar::chunk {{ background: {acc}; border-radius: 5px; }}

/* ---------- views ---------- */
QListView, QTreeView, QTableView, QListWidget, QTreeWidget, QTableWidget {{
    background: {P.bg2};
    border: 1px solid {P.line};
    border-radius: 8px;
    alternate-background-color: {P.bg2};
    selection-background-color: {acc_soft};
    selection-color: {P.text};
    gridline-color: {P.line};
}}
QListView::item, QTreeView::item {{ padding: 3px 4px; border-radius: 6px; }}
QListView::item:hover, QTreeView::item:hover {{ background: {P.bg4}; }}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {acc_soft};
    color: {P.text};
}}
QHeaderView::section {{
    background: {P.bg2};
    color: {P.text3};
    border: none;
    border-bottom: 1px solid {P.line};
    padding: 5px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background: {P.bg2}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {P.text3};
    padding: 7px 12px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {P.text2}; }}
QTabBar::tab:selected {{ color: {P.text}; border-bottom: 2px solid {acc}; }}

QGroupBox {{
    background: {P.bg2};
    border: 1px solid {P.line};
    border-radius: 10px;
    margin-top: 18px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {P.text2};
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {P.bg5}; min-height: 30px; border-radius: 3px; }}
QScrollBar::handle:vertical:hover {{ background: {P.text3}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {P.bg5}; min-width: 30px; border-radius: 3px; }}
QScrollBar::handle:horizontal:hover {{ background: {P.text3}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {P.line}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ---------- custom classes ---------- */
QLabel[class="muted"] {{ color: {P.text2}; }}
QLabel[class="faint"] {{ color: {P.text3}; }}
QLabel[class="title"] {{ font-size: 15px; font-weight: 600; color: {P.text}; }}
QLabel[class="section"] {{
    color: {P.text3};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
    padding: 6px 0 2px 0;
}}
QLabel[class="mono"] {{ font-family: "{MONO_FONT}", "Consolas"; font-size: 11px; color: {P.text2}; }}
QLabel[class="badge"] {{
    background: {acc_soft};
    color: {acc};
    border-radius: 5px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}}
QFrame[class="card"] {{
    background: {P.bg3};
    border: 1px solid {P.line};
    border-radius: 10px;
}}
QFrame[class="panel"] {{
    background: {P.bg2};
    border: none;
}}
QFrame[class="rail"] {{
    background: {P.bg1};
    border-left: 1px solid {P.line};
}}
QFrame[class="hline"] {{ background: {P.line}; max-height: 1px; min-height: 1px; border: none; }}
QFrame[class="vline"] {{ background: {P.line2}; max-width: 1px; min-width: 1px; border: none; }}
QToolButton[role="rail"] {{
    border-radius: 9px;
    padding: 7px;
    color: {P.text3};
}}
QToolButton[role="rail"]:hover {{ color: {P.text}; background: {P.bg3}; }}
QToolButton[role="rail"]:checked {{ color: {acc}; background: {acc_soft}; border: none; }}
QToolButton[role="transport"] {{ border-radius: 8px; padding: 5px; color: {P.text2}; }}
QToolButton[role="transport"]:hover {{ color: {P.text}; background: {P.bg4}; }}
QToolButton[role="play"] {{
    background: {acc};
    border-radius: 17px;
    padding: 7px;
    color: #FFFFFF;
}}
QToolButton[role="play"]:hover {{ background: {P.accent_hover()}; }}
QToolButton[role="play"]:pressed {{ background: {P.accent_pressed()}; }}
QToolButton[role="seg"] {{
    border-radius: 6px;
    padding: 3px 8px;
    color: {P.text2};
    font-weight: 600;
    min-width: 14px;
}}
QToolButton[role="seg"]:checked {{ background: {P.bg5}; color: {P.text}; border: 1px solid {P.line2}; }}
QFrame[class="seg"] {{
    background: {P.bg1};
    border: 1px solid {P.line};
    border-radius: 8px;
}}
QWidget#SidePanel {{ background: {P.bg2}; }}
QWidget#PanelHeader {{ background: {P.bg2}; border-bottom: 1px solid {P.line}; }}
QWidget#Transport {{ background: {P.bg2}; border-top: 1px solid {P.line}; }}
QWidget#AnnotationBar {{
    background: {P.rgba(P.bg2, 0.94)};
    border: 1px solid {P.line2};
    border-radius: 12px;
}}
"""


_TMP_ASSETS: dict[str, str] = {}


def _write_asset(name: str, svg: str) -> str:
    """Style sheets need image files; write tiny SVGs once into a temp folder."""
    import tempfile

    key = name + svg
    if key in _TMP_ASSETS:
        return _TMP_ASSETS[key]
    folder = os.path.join(tempfile.gettempdir(), "cocseq_ui")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    path = path.replace("\\", "/")
    _TMP_ASSETS[key] = path
    return path


def _chevron_path() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
        f'<path d="M3 4.5 L6 7.5 L9 4.5" fill="none" stroke="{PAL.text2}" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    return _write_asset("chevron.svg", svg)


def _check_path() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        '<path d="M3.5 8.5 L6.5 11.5 L12.5 4.5" fill="none" stroke="#FFFFFF" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
    return _write_asset("check.svg", svg)


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    apply_palette(app)
    app.setFont(ui_font())
    app.setStyleSheet(style_sheet())
