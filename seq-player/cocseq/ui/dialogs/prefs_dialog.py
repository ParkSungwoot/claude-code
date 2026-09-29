"""Preferences dialog: a navigation rail on the left, one scrolling page of cards per topic.

Usage::

    dlg = PreferencesDialog(store.prefs, parent)
    if dlg.exec():
        new = dlg.result_prefs()          # modified deep copy; the passed object is untouched
        changed = dlg.changed_fields()    # names of the Prefs fields the user changed
"""

from __future__ import annotations

import copy
import os
from dataclasses import fields as dc_fields
from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QDoubleValidator, QFont, QIcon, QPainter, QPainterPath,
                           QPen, QPixmap, QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QApplication, QButtonGroup, QComboBox,
                               QDialog, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QStackedWidget, QStyledItemDelegate, QVBoxLayout, QWidget)

from cocseq import APP_NAME, __version__
from cocseq.prefs import Prefs
from cocseq.theme import ACCENT_PRESETS, PAL, mono_font, ui_font
from cocseq.ui.widgets import ColorButton, IconButton, SectionTitle, Segmented, Swatches
from cocseq.utils import fps_label, total_ram_bytes

# --------------------------------------------------------------------------- constants

FPS_PRESETS = ["23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60"]

HUD_ITEMS = [
    ("name", "파일 이름"),
    ("frame", "프레임"),
    ("timecode", "타임코드"),
    ("resolution", "해상도"),
    ("fps", "FPS"),
    ("layer", "레이어"),
    ("colorspace", "색공간"),
    ("exposure", "노출/감마"),
    ("memory", "캐시 메모리"),
    ("directory", "폴더"),
]

SAFE_AREA_RATIOS = [("", "없음"), ("16:9", "16:9"), ("1.85", "1.85 : 1"), ("2.39", "2.39 : 1"),
                    ("4:3", "4:3"), ("1:1", "1:1"), ("9:16", "9:16 (세로)")]

BACKGROUNDS = [
    ("dark", "어두운 회색", "#131417"),
    ("black", "검정", "#000000"),
    ("gray", "회색", "#2E2E2E"),
    ("checker", "체커보드", ""),
    ("custom", "사용자 색", ""),
]

PEN_COLORS = ["#FF4D5E", "#FFB23F", "#FFE45C", "#3DD68C", "#38C6F4", "#9C7BFF", "#FFFFFF"]

# Fields whose change only takes effect after the app restarts.
RESTART_FIELDS = {"single_instance"}

_HEADER_ROLE = Qt.UserRole + 20
_VALUE_ROLE = Qt.UserRole + 21
_MISSING_ROLE = Qt.UserRole + 22
_BROWSE = "__browse__"


def _dialog_qss() -> str:
    P = PAL
    acc = P.accent
    return f"""
QWidget#PrefsNavPane {{
    background: {P.bg2};
    border-right: 1px solid {P.line};
}}
QListWidget#PrefsNav {{
    background: transparent;
    border: none;
    padding: 0;
}}
QListWidget#PrefsNav::item {{
    height: 34px;
    padding: 0 8px;
    margin: 1px 0;
    border: none;
    border-radius: 8px;
    color: {P.text2};
}}
QListWidget#PrefsNav::item:hover {{ background: {P.bg4}; color: {P.text}; }}
QListWidget#PrefsNav::item:selected {{ background: {P.rgba(acc, 0.14)}; color: {P.text}; }}
QLabel#NavTitle {{ font-size: 14px; font-weight: 600; color: {P.text}; }}
QLabel#NavFoot {{ color: {P.text3}; font-size: 10.5px; }}
QWidget#PrefsHeader {{ background: {P.bg1}; }}
QLabel#PageTitle {{ font-size: 18px; font-weight: 600; color: {P.text}; }}
QLabel#PageSub {{ color: {P.text3}; font-size: 11.5px; }}
QWidget#PrefsFooter {{ background: {P.bg1}; border-top: 1px solid {P.line}; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox[missing="true"] {{ color: {P.warn}; border-color: {P.rgba(P.warn, 0.45)}; }}
QFrame#PrefsCard {{
    background: {P.bg2};
    border: 1px solid {P.line};
    border-radius: 12px;
}}
QFrame#CardSep {{ background: {P.line}; border: none; min-height: 1px; max-height: 1px; }}
QLabel#OptTitle {{ color: {P.text}; font-size: 12.5px; }}
QLabel#OptTitle:disabled, QLabel#OptDesc:disabled {{ color: {P.text3}; }}
QLabel#OptDesc {{ color: {P.text3}; font-size: 11px; }}
QLabel#OptHint {{ color: {P.text3}; font-size: 11px; }}
QLabel#OptValue {{ font-family: "JetBrains Mono", "Consolas"; font-size: 11px; color: {P.text}; }}
QLabel#PathLabel {{
    font-family: "JetBrains Mono", "Consolas";
    font-size: 10.5px;
    color: {P.text2};
    background: {P.bg1};
    border: 1px solid {P.line};
    border-radius: 6px;
    padding: 4px 8px;
}}
QLabel#RestartBadge {{
    background: {P.rgba(P.warn, 0.14)};
    color: {P.warn};
    border-radius: 5px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: 700;
}}
QFrame#Stepper {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 7px;
}}
QFrame#Stepper:hover {{ background: {P.bg4}; }}
QFrame#Stepper QSpinBox, QFrame#Stepper QDoubleSpinBox {{
    background: transparent;
    border: none;
    padding: 0 2px;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 11.5px;
}}
QFrame#Stepper QToolButton {{ border-radius: 5px; padding: 2px; }}
QFrame#ChoiceTile {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 10px;
}}
QFrame#ChoiceTile:hover {{ border-color: {P.text3}; }}
QFrame#ChoiceTile[checked="true"] {{
    background: {P.rgba(acc, 0.10)};
    border: 1px solid {P.rgba(acc, 0.65)};
}}
QFrame#ChoiceTile QRadioButton {{ font-weight: 600; background: transparent; }}
QPushButton[chip="true"] {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    border-radius: 14px;
    padding: 4px 12px 4px 10px;
    color: {P.text2};
    min-height: 18px;
    text-align: left;
}}
QPushButton[chip="true"]:hover {{ background: {P.bg4}; color: {P.text}; }}
QPushButton[chip="true"]:checked {{
    background: {P.rgba(acc, 0.14)};
    border-color: {P.rgba(acc, 0.55)};
    color: {P.text};
}}
QPushButton[chip="true"]:disabled {{ color: {P.text3}; background: {P.bg2}; border-color: {P.line}; }}
"""


# --------------------------------------------------------------------------- small widgets


class ToggleSwitch(QAbstractButton):
    """iOS-style on/off switch."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(36, 20)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(36, 20)

    def _animate(self, on: bool) -> None:
        end = 1.0 if on else 0.0
        self._anim.stop()
        if not self.isVisible():
            self._set_pos(end)
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(end)
        self._anim.start()

    def _set_pos(self, v) -> None:
        self._pos = float(v)
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        off = PAL.qcolor("bg5")
        on = PAL.qcolor("accent")
        t = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * t),
                       int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(QPen(PAL.qcolor("line2"), 1) if t < 0.5 else Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.hasFocus() and self.focusPolicy() != Qt.NoFocus and self._keyboard_focus:
            p.setPen(QPen(PAL.qcolor("accent", 0.6), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - 6 - d) * t
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(x, r.top() + 3.6, d, d))
        p.setBrush(QColor("#FFFFFF") if self.isEnabled() else PAL.qcolor("text3"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))

    _keyboard_focus = False

    def focusInEvent(self, ev) -> None:
        self._keyboard_focus = ev.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(ev)

    def focusOutEvent(self, ev) -> None:
        self._keyboard_focus = False
        super().focusOutEvent(ev)


class Stepper(QFrame):
    """Number field with - / + buttons (spin box buttons are hidden by the theme)."""

    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, step: float = 1, decimals: int = 0,
                 suffix: str = "", width: int = 112, parent=None):
        super().__init__(parent)
        self.setObjectName("Stepper")
        self.setFixedSize(width, 30)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(0)
        self.minus = IconButton("minus", "줄이기", size=14)
        self.plus = IconButton("plus", "늘리기", size=14)
        for b in (self.minus, self.plus):
            b.setFixedSize(24, 24)
            b.setAutoRepeat(True)
            b.setFocusPolicy(Qt.NoFocus)
        if decimals:
            self.spin: QAbstractSpinBox = QDoubleSpinBox()
            self.spin.setDecimals(decimals)
        else:
            self.spin = QSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setKeyboardTracking(False)
        if suffix:
            self.spin.setSuffix(suffix)
        self.minus.clicked.connect(self.spin.stepDown)
        self.plus.clicked.connect(self.spin.stepUp)
        self.spin.valueChanged.connect(lambda v: self.valueChanged.emit(float(v)))
        lay.addWidget(self.minus)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.plus)

    def value(self) -> float:
        return float(self.spin.value())

    def setValue(self, v: float) -> None:
        if isinstance(self.spin, QSpinBox):
            self.spin.setValue(int(round(v)))
        else:
            self.spin.setValue(float(v))


class SliderField(QWidget):
    """Slider with a live value read-out on its right."""

    valueChanged = Signal(int)

    def __init__(self, minimum: int, maximum: int, fmt: Callable[[int], str], width: int = 250,
                 value_width: int = 46, parent=None):
        super().__init__(parent)
        self._fmt = fmt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setFixedHeight(22)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.label = QLabel()
        self.label.setObjectName("OptValue")
        self.label.setFixedWidth(value_width)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.setFixedWidth(width)
        self.slider.valueChanged.connect(self._changed)
        self._changed(self.slider.value())

    def _changed(self, v: int) -> None:
        self.label.setText(self._fmt(v))
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int) -> None:
        self.slider.setValue(int(v))
        self.label.setText(self._fmt(self.slider.value()))


class ChoiceTile(QFrame):
    """A bordered, clickable radio option with a one-line description."""

    def __init__(self, title: str, desc: str, group: QButtonGroup, icon_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ChoiceTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 11)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(0)
        self.radio = QRadioButton(title)
        self.radio.setCursor(Qt.PointingHandCursor)
        group.addButton(self.radio)
        top.addWidget(self.radio)
        top.addStretch(1)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(_pix(icon_name, 16, PAL.text3))
            top.addWidget(ic)
        lay.addLayout(top)
        d = QLabel(desc)
        d.setObjectName("OptDesc")
        d.setWordWrap(True)
        d.setContentsMargins(24, 0, 0, 0)
        lay.addWidget(d)
        lay.addStretch(1)
        self.radio.toggled.connect(self._sync)
        self._sync(self.radio.isChecked())

    def _sync(self, on: bool) -> None:
        self.setProperty("checked", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.radio.setChecked(True)
        super().mouseReleaseEvent(ev)


class _CustomSwatch(ColorButton):
    """Rainbow ring that opens the colour picker; filled with the colour when it is not a preset."""

    def __init__(self, presets: list[str], parent=None):
        super().__init__("#FFFFFF", parent, 22)
        self._presets = {QColor(c).name().lower() for c in presets}
        self._is_custom = False
        self.setToolTip("직접 고르기…")

    def sync(self, color: str) -> None:
        self.set_color(color)
        self._is_custom = QColor(color).name().lower() not in self._presets
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self._is_custom:
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.adjusted(1, 1, -1, -1))
        inner = r.adjusted(3, 3, -3, -3)
        g = QConicalGradient(r.center(), 90)
        for i, c in enumerate(("#FF4D5E", "#FFB23F", "#FFE45C", "#3DD68C", "#38C6F4", "#9C7BFF", "#FF4D5E")):
            g.setColorAt(i / 6, QColor(c))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(inner)
        core = inner.adjusted(2.5, 2.5, -2.5, -2.5)
        if self._is_custom:
            p.setBrush(self._color)
            p.drawEllipse(core)
        else:
            p.setBrush(PAL.qcolor("bg2"))
            p.drawEllipse(core)
            p.setPen(QPen(PAL.qcolor("text2"), 1.4, Qt.SolidLine, Qt.RoundCap))
            c = core.center()
            p.drawLine(c.x() - 2.5, c.y(), c.x() + 2.5, c.y())
            p.drawLine(c.x(), c.y() - 2.5, c.x(), c.y() + 2.5)


class SwatchRow(Swatches):
    """Swatches whose custom picker reads as a picker (not a copy of the selected preset)."""

    def __init__(self, colors: list[str], current: str = "", names: list[str] | None = None, parent=None):
        super().__init__(colors, current, parent)
        self.custom.hide()
        self.picker = _CustomSwatch(colors, self)
        lay = self.layout()
        lay.insertWidget(lay.count() - 1, self.picker)
        self.picker.colorChanged.connect(lambda c: self.set_color(c, emit=True))
        self.picker.sync(self.color())
        for btn, name in zip(getattr(self, "_btns", []), names or colors):
            btn.setToolTip(name)

    def set_color(self, c: str, emit: bool = False) -> None:
        super().set_color(c, emit)
        if hasattr(self, "picker"):
            self.picker.sync(self.color())


class _GroupDelegate(QStyledItemDelegate):
    """Draws group header rows (disabled items) as small caps labels in a combo popup."""

    def paint(self, painter, option, index) -> None:
        if index.data(_HEADER_ROLE):
            painter.save()
            r = QRectF(option.rect)
            if index.row() > 0:
                painter.setPen(QPen(PAL.qcolor("line2"), 1))
                painter.drawLine(r.left() + 6, r.top() + 3.5, r.right() - 6, r.top() + 3.5)
            painter.setFont(ui_font(7.5, QFont.Bold))
            painter.setPen(PAL.qcolor("text3"))
            painter.drawText(r.adjusted(10, 6, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, index.data(Qt.DisplayRole))
            painter.restore()
            return
        super().paint(painter, option, index)

    def sizeHint(self, option, index) -> QSize:
        s = super().sizeHint(option, index)
        if index.data(_HEADER_ROLE):
            return QSize(s.width(), 28)
        return QSize(s.width(), max(s.height(), 26))


class ValueCombo(QComboBox):
    """Combo whose items carry a value; optional group headers; keeps unknown values visible."""

    def __init__(self, width: int = 220, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setItemDelegate(_GroupDelegate(self))
        self.setMaxVisibleItems(18)
        self.setFixedWidth(width)
        self.setCursor(Qt.PointingHandCursor)
        self._entries: list[tuple[str, str, str]] = []   # (group, value, text)
        self._grouped = False
        self.setProperty("missing", "false")
        self.currentIndexChanged.connect(lambda _i: self._sync_missing())

    def populate(self, entries, value: str | None = None, grouped: bool = False) -> None:
        """entries: [(value, text)] or, with grouped=True, [(group, value, text)]."""
        if not grouped:
            entries = [("", v, t) for v, t in entries]
        self._entries = list(entries)
        self._grouped = grouped
        self._rebuild(self.value() if value is None else value)

    def _rebuild(self, value: str) -> None:
        self.blockSignals(True)
        self._model.clear()
        known = {v for _, v, _ in self._entries}
        if value not in known and (value or not self._entries):
            it = QStandardItem(f"{value or '—'} (없음)")
            it.setData(value, _VALUE_ROLE)
            it.setData(True, _MISSING_ROLE)
            it.setForeground(PAL.qcolor("warn"))
            it.setToolTip("현재 목록에 없는 값입니다. 다른 값을 고르지 않으면 그대로 저장됩니다.")
            self._model.appendRow(it)
        if self._grouped and len({g for g, _, _ in self._entries}) > 1:
            order: list[str] = []
            buckets: dict[str, list] = {}
            for g, v, t in self._entries:
                if g not in buckets:
                    order.append(g)
                    buckets[g] = []
                buckets[g].append((v, t))
            for g in order:
                h = QStandardItem((g or "기타").replace("/", " / "))
                h.setFlags(Qt.NoItemFlags)
                h.setData(True, _HEADER_ROLE)
                self._model.appendRow(h)
                for v, t in buckets[g]:
                    self._append(v, t)
        else:
            for _, v, t in self._entries:
                self._append(v, t)
        if not self._select(value):
            for row in range(self._model.rowCount()):
                if not self._model.item(row).data(_HEADER_ROLE):
                    self.setCurrentIndex(row)
                    break
        self.blockSignals(False)
        self._sync_missing()

    def _append(self, v: str, t: str) -> None:
        it = QStandardItem(t)
        it.setData(v, _VALUE_ROLE)
        it.setToolTip(t)
        self._model.appendRow(it)

    def _select(self, value: str) -> bool:
        for row in range(self._model.rowCount()):
            it = self._model.item(row)
            if not it.data(_HEADER_ROLE) and it.data(_VALUE_ROLE) == value:
                self.setCurrentIndex(row)
                return True
        return False

    def value(self) -> str:
        v = self.currentData(_VALUE_ROLE)
        return "" if v is None else str(v)

    def set_value(self, value: str) -> None:
        if not self._select(value):
            self._rebuild(value)
            self.currentIndexChanged.emit(self.currentIndex())

    def is_missing(self) -> bool:
        it = self._model.item(self.currentIndex()) if self.currentIndex() >= 0 else None
        return bool(it) and bool(it.data(_MISSING_ROLE))

    def _sync_missing(self) -> None:
        flag = "true" if self.is_missing() else "false"
        if self.property("missing") != flag:
            self.setProperty("missing", flag)
            self.style().unpolish(self)
            self.style().polish(self)
        self.setToolTip("현재 목록에 없는 값입니다 — 다른 값을 고르지 않으면 그대로 저장됩니다"
                        if flag == "true" else self.currentText())


class ElidedLabel(QLabel):
    """Single-line label that elides its text in the middle to fit (full text in the tooltip)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(10)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._elide()

    def _elide(self) -> None:
        avail = self.contentsRect().width() - 18
        text = self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(20, avail))
        super().setText(text)


class _WheelGuard(QObject):
    """Wheel over an unfocused input scrolls the page instead of changing the value."""

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            w = obj.parentWidget()
            while w is not None and not isinstance(w, QScrollArea):
                w = w.parentWidget()
            if w is not None:
                QApplication.sendEvent(w.verticalScrollBar(), ev)
            return True
        return False


def _pix(name: str, size: int, color: str) -> QPixmap:
    from cocseq import icons

    return icons.pixmap(name, size, color)


def _nav_icon(name: str) -> QIcon:
    ic = QIcon()
    for dpr in (1.0, 2.0):
        from cocseq import icons

        ic.addPixmap(icons.pixmap(name, 18, PAL.text2, dpr), QIcon.Normal)
        ic.addPixmap(icons.pixmap(name, 18, PAL.text, dpr), QIcon.Active)
        ic.addPixmap(icons.pixmap(name, 18, PAL.accent, dpr), QIcon.Selected)
    return ic


def _chip_icon(color: str, checker: bool = False) -> QIcon:
    pm = QPixmap(28, 28)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(1, 1, 12, 12)
    if checker:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3D3D3D"))
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(QColor("#282828"))
        for i in range(2):
            for j in range(2):
                if (i + j) % 2:
                    p.drawRect(QRectF(1 + i * 6, 1 + j * 6, 6, 6))
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(r, 3, 3)
    p.setPen(QPen(QColor(255, 255, 255, 50), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------------------- page building blocks


class SettingsCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PrefsCard")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 2, 0, 2)
        self.lay.setSpacing(0)
        self._rows = 0

    def add(self, row: QWidget) -> QWidget:
        if self._rows:
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(16, 0, 16, 0)
            sep = QFrame()
            sep.setObjectName("CardSep")
            sep.setFixedHeight(1)
            hl.addWidget(sep)
            self.lay.addWidget(holder)
        self.lay.addWidget(row)
        self._rows += 1
        return row


class OptionRow(QWidget):
    """Title (+ one-line description) on the left, control on the right, optional content below."""

    def __init__(self, title: str, desc: str = "", control: QWidget | None = None,
                 below: QWidget | None = None, badge: str = "", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 11, 16, 12)
        lay.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(18)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("OptTitle")
        head.addWidget(self.title)
        if badge:
            b = QLabel(badge)
            b.setObjectName("RestartBadge")
            head.addWidget(b)
        head.addStretch(1)
        texts.addLayout(head)
        self.desc: QLabel | None = None
        if desc:
            self.desc = QLabel(desc)
            self.desc.setObjectName("OptDesc")
            self.desc.setWordWrap(True)
            texts.addWidget(self.desc)
        top.addLayout(texts, 1)
        self.control = control
        if control is not None:
            top.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(top)
        if below is not None:
            lay.addWidget(below)

    def set_desc(self, text: str) -> None:
        if self.desc is not None:
            self.desc.setText(text)

    def mouseReleaseEvent(self, ev) -> None:
        # Clicking the text of a switch row flips the switch.
        if (isinstance(self.control, ToggleSwitch) and self.control.isEnabled()
                and ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint())):
            self.control.toggle()
        super().mouseReleaseEvent(ev)


class _Page(QScrollArea):
    def __init__(self, key: str, title: str, subtitle: str, icon: str):
        super().__init__()
        self.key, self.title, self.subtitle, self.icon = key, title, subtitle, icon
        self.fields: list[str] = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("PrefsPageBody")
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(28, 4, 24, 24)
        self.v.setSpacing(0)
        self.setWidget(body)
        self._sections = 0

    def section(self, title: str) -> SettingsCard:
        t = SectionTitle(title)
        t.setContentsMargins(2, 14 if self._sections else 6, 0, 6)
        self.v.addWidget(t)
        card = SettingsCard()
        self.v.addWidget(card)
        self._sections += 1
        return card

    def finish(self) -> None:
        self.v.addStretch(1)


# --------------------------------------------------------------------------- dialog


class PreferencesDialog(QDialog):
    """Edit a copy of the preferences. ``result_prefs()`` returns the edited copy."""

    PAGES = ("general", "playback", "cache", "color", "viewer", "audio", "annotation")

    def __init__(self, prefs: Prefs, parent=None):
        super().__init__(parent)
        self._orig = prefs
        self._work = copy.deepcopy(prefs)
        self._defaults = Prefs()
        self._bindings: dict[str, tuple[Callable[[], object], Callable[[object], None]]] = {}
        self._pages: list[_Page] = []
        self._ocio_key: tuple | None = None
        self._ocio_mgr = None
        self._loading = False
        self._wheel_guard = _WheelGuard(self)

        self.setWindowTitle("환경 설정")
        self.setModal(True)
        self.resize(860, 600)
        self.setMinimumSize(760, 480)
        self.setStyleSheet(_dialog_qss())

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_nav())

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        header = QWidget()
        header.setObjectName("PrefsHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hv = QVBoxLayout(header)
        hv.setContentsMargins(28, 22, 28, 10)
        hv.setSpacing(3)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.page_sub = QLabel()
        self.page_sub.setObjectName("PageSub")
        hv.addWidget(self.page_title)
        hv.addWidget(self.page_sub)
        rv.addWidget(header)

        self.stack = QStackedWidget()
        rv.addWidget(self.stack, 1)
        rv.addWidget(self._build_footer())
        root.addWidget(right, 1)

        for build in (self._page_general, self._page_playback, self._page_cache, self._page_color,
                      self._page_viewer, self._page_audio, self._page_annotation):
            page = build()
            page.finish()
            self._pages.append(page)
            self.stack.addWidget(page)
            item = QListWidgetItem(_nav_icon(page.icon), page.title)
            item.setSizeHint(QSize(0, 36))
            self.nav.addItem(item)

        for w in self.findChildren(QWidget):
            if isinstance(w, (QComboBox, QAbstractSpinBox, QSlider)):
                w.setFocusPolicy(Qt.StrongFocus)
                w.installEventFilter(self._wheel_guard)

        self._load_all(self._work)
        self.nav.currentRowChanged.connect(self._show_page)
        self.nav.setCurrentRow(0)
        self._show_page(0)

    # ------------------------------------------------------------ public API

    def result_prefs(self) -> Prefs:
        """A deep copy of the passed prefs with every edited field applied."""
        out = copy.deepcopy(self._orig)
        for name, (getter, _setter) in self._bindings.items():
            setattr(out, name, copy.deepcopy(getter()))
        return out

    def changed_fields(self) -> set[str]:
        """Names of the Prefs fields whose value differs from the passed prefs."""
        res = self.result_prefs()
        return {f.name for f in dc_fields(Prefs) if getattr(res, f.name) != getattr(self._orig, f.name)}

    def restart_required(self) -> bool:
        return bool(self.changed_fields() & RESTART_FIELDS)

    def current_page(self) -> str:
        return self._pages[self.stack.currentIndex()].key

    def set_page(self, key: str) -> None:
        for i, p in enumerate(self._pages):
            if p.key == key:
                self.nav.setCurrentRow(i)
                return

    def reset_page(self) -> None:
        """Put every field of the visible page back to its default."""
        page = self._pages[self.stack.currentIndex()]
        self._loading = True
        try:
            for name in page.fields:
                self._bindings[name][1](copy.deepcopy(getattr(self._defaults, name)))
        finally:
            self._loading = False
        if page.key == "color":
            self._reload_ocio(force=True)
            for name in ("cs_float", "cs_int", "cs_movie", "display", "view"):
                self._bindings[name][1](getattr(self._defaults, name))
        self._refresh_dependents()

    # ------------------------------------------------------------ chrome

    def _build_nav(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("PrefsNavPane")
        pane.setAttribute(Qt.WA_StyledBackground, True)
        pane.setFixedWidth(208)
        v = QVBoxLayout(pane)
        v.setContentsMargins(12, 18, 12, 14)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 0)
        head.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(_pix("settings", 20, PAL.text))
        head.addWidget(ic)
        t = QLabel("환경 설정")
        t.setObjectName("NavTitle")
        head.addWidget(t)
        head.addStretch(1)
        v.addLayout(head)
        v.addSpacing(16)
        self.nav = QListWidget()
        self.nav.setObjectName("PrefsNav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setSpacing(0)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setCursor(Qt.PointingHandCursor)
        self.nav.setFocusPolicy(Qt.StrongFocus)
        v.addWidget(self.nav, 1)
        foot = QLabel(f"{APP_NAME}  {__version__}")
        foot.setObjectName("NavFoot")
        foot.setContentsMargins(8, 0, 0, 0)
        v.addWidget(foot)
        return pane

    def _build_footer(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("PrefsFooter")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 12, 20, 12)
        h.setSpacing(8)
        self.btn_reset = QPushButton("기본값으로")
        self.btn_reset.setProperty("variant", "ghost")
        from cocseq import icons

        self.btn_reset.setIcon(icons.icon("refresh", size=16))
        self.btn_reset.setIconSize(QSize(15, 15))
        self.btn_reset.setToolTip("이 페이지의 설정만 기본값으로 되돌립니다")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setAutoDefault(False)
        self.btn_reset.clicked.connect(self.reset_page)
        h.addWidget(self.btn_reset)
        h.addStretch(1)
        self.footer_note = QLabel("")
        self.footer_note.setObjectName("OptHint")
        h.addWidget(self.footer_note)
        h.addSpacing(8)
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setAutoDefault(False)
        self.btn_cancel.setMinimumWidth(76)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("저장")
        self.btn_save.setProperty("variant", "primary")
        self.btn_save.setMinimumWidth(86)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)
        h.addWidget(self.btn_cancel)
        h.addWidget(self.btn_save)
        return bar

    def _show_page(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        page = self._pages[row]
        self.page_title.setText(page.title)
        self.page_sub.setText(page.subtitle)

    # ------------------------------------------------------------ binding helpers

    def _bind(self, page: _Page, name: str, getter: Callable[[], object], setter: Callable[[object], None]) -> None:
        page.fields.append(name)
        self._bindings[name] = (getter, setter)

    def _bind_color(self, page: _Page, name: str, getter: Callable[[], str], setter: Callable[[object], None]) -> None:
        """Colours come back as #RRGGBB; an unchanged colour keeps the original spelling."""

        def get() -> str:
            v = QColor(getter()).name().upper()
            o = getattr(self._orig, name, "")
            return o if isinstance(o, str) and QColor(o).isValid() and QColor(o).name().upper() == v else v

        self._bind(page, name, get, setter)

    def _switch(self, page: _Page, card: SettingsCard, name: str, title: str, desc: str = "",
                badge: str = "") -> ToggleSwitch:
        sw = ToggleSwitch()
        card.add(OptionRow(title, desc, sw, badge=badge))
        self._bind(page, name, sw.isChecked, lambda v, s=sw: s.setChecked(bool(v)))
        return sw

    def _segmented(self, page: _Page, card: SettingsCard, name: str, title: str, desc: str,
                   options: list[tuple], convert: Callable = str, min_width: int = 0) -> Segmented:
        seg = Segmented(options)
        if min_width:
            for opt in options:
                seg.button(opt[0]).setMinimumWidth(min_width)
        card.add(OptionRow(title, desc, seg))
        self._bind(page, name, lambda s=seg: convert(s.value()), lambda v, s=seg: s.set_value(str(v)))
        return seg

    def _load_all(self, prefs: Prefs) -> None:
        self._loading = True
        try:
            for name, (_g, setter) in self._bindings.items():
                if name in ("cs_float", "cs_int", "cs_movie", "display", "view"):
                    continue
                setter(copy.deepcopy(getattr(prefs, name)))
        finally:
            self._loading = False
        self._reload_ocio(force=True, values={n: getattr(prefs, n) for n in
                                              ("cs_float", "cs_int", "cs_movie", "display", "view")})
        self._refresh_dependents()

    def _refresh_dependents(self) -> None:
        self._update_background_controls()
        self._update_cache_hint()
        self._update_pen_preview()

    # ------------------------------------------------------------ pages

    def _page_general(self) -> _Page:
        page = _Page("general", "일반", "창, 파일 열기, 강조 색", "settings")
        card = page.section("창")
        self._switch(page, card, "single_instance", "새 파일을 이미 열린 창에서 열기",
                     "탐색기에서 파일을 열면 새 창을 띄우지 않고 지금 창에 추가합니다", badge="재시작 후 적용")
        self._switch(page, card, "open_maximized", "최대화된 창으로 시작", "다음 실행부터 창을 화면 가득 엽니다")

        card = page.section("파일")
        self._switch(page, card, "auto_detect_sequence", "시퀀스 자동 인식",
                     "파일 하나를 열면 같은 시퀀스의 프레임 전체를 인식합니다")
        st = Stepper(0, 50, 1, suffix=" 개", width=112)
        card.add(OptionRow("최근 항목 개수", "파일 메뉴에 보여 줄 최근 파일·세션 수", st))
        self._bind(page, "recent_max", lambda: int(st.value()), st.setValue)

        card = page.section("모양")
        presets = list(ACCENT_PRESETS.items())
        sw = SwatchRow([c for _, c in presets], self._work.accent, [n for n, _ in presets])
        card.add(OptionRow("강조 색", "버튼, 선택 표시, 재생 헤드에 쓰는 색", sw))
        self._bind_color(page, "accent", sw.color, lambda v: sw.set_color(str(v)))
        return page

    def _page_playback(self) -> _Page:
        page = _Page("playback", "재생", "재생 속도와 방식, 시간 표시, 비교", "play")
        card = page.section("기본 재생")

        fps = QComboBox()
        fps.setEditable(True)
        fps.addItems(FPS_PRESETS)
        fps.setValidator(QDoubleValidator(0.1, 1000.0, 3, fps))
        fps.setInsertPolicy(QComboBox.NoInsert)
        fps.setFixedWidth(112)
        fps.lineEdit().setFont(mono_font(9))
        fps.setToolTip("목록에서 고르거나 직접 입력하세요 (예: 23.976)")
        card.add(OptionRow("기본 FPS", "파일에 속도 정보가 없을 때(이미지 시퀀스 등) 사용합니다", fps))

        def get_fps() -> float:
            try:
                v = float(fps.currentText().replace(",", "."))
            except ValueError:
                return float(self._orig.default_fps)
            return v if v > 0 else float(self._orig.default_fps)

        self._bind(page, "default_fps", get_fps, lambda v: fps.setEditText(fps_label(float(v))))

        self._segmented(page, card, "loop_mode", "반복 방식", "끝에 닿았을 때의 동작",
                        [("loop", "반복", "처음으로 돌아가 계속 재생", "loop"),
                         ("once", "한 번", "끝에서 멈춤", "loop-once"),
                         ("pingpong", "왕복", "끝에서 방향을 바꿔 재생", "pingpong")])
        self._switch(page, card, "autoplay_on_open", "열면 바로 재생", "클립을 열자마자 재생을 시작합니다")
        self._switch(page, card, "playlist_continuous", "다음 클립 이어서 재생",
                     "마지막 프레임 뒤에 플레이리스트의 다음 클립을 재생합니다")

        card = page.section("프레임 처리")
        grp = QButtonGroup(self)
        tiles = QWidget()
        tl = QHBoxLayout(tiles)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(10)
        t_all = ChoiceTile("모든 프레임 재생", "건너뛰지 않음 · 느리면 속도가 떨어짐", grp, "film")
        t_rt = ChoiceTile("실시간 유지", "속도 유지 · 늦은 프레임은 건너뜀", grp, "speed")
        tl.addWidget(t_all)
        tl.addWidget(t_rt)
        card.add(OptionRow("느릴 때 재생 방식", "디스크나 디코딩이 느려 제 속도를 낼 수 없을 때", below=tiles))
        self._bind(page, "play_all_frames", t_all.radio.isChecked,
                   lambda v: (t_all.radio if v else t_rt.radio).setChecked(True))
        self._segmented(page, card, "missing_frame", "누락 프레임", "시퀀스 중간에 빠진 프레임을 보여 주는 방법",
                        [("black", "검은 화면+표시", "검은 화면에 '누락' 표시"),
                         ("hold", "이전 프레임 유지", "바로 앞 프레임을 계속 보여 줌")])

        card = page.section("시간 표시")
        self._segmented(page, card, "time_display", "시간 단위", "타임라인과 현재 위치 표시에 쓸 단위",
                        [("frames", "프레임"), ("timecode", "타임코드"), ("seconds", "초")], min_width=44)
        self._segmented(page, card, "movie_start_frame", "동영상 시작 프레임", "동영상 첫 프레임의 번호",
                        [("0", "0"), ("1", "1")], convert=int, min_width=40)

        card = page.section("비교")
        cb = ValueCombo(200)
        cb.populate([("relative", "시작 프레임 기준"), ("absolute", "같은 프레임 번호")])
        card.add(OptionRow("A/B 프레임 맞춤", "A와 B의 프레임 번호가 다를 때 어떻게 맞출지", cb))
        self._bind(page, "compare_align", cb.value, lambda v: cb.set_value(str(v)))
        return page

    def _page_cache(self) -> _Page:
        page = _Page("cache", "캐시·성능", "메모리 캐시와 읽기 스레드", "cache")
        ram_gb = total_ram_bytes() / 1024 ** 3
        self._ram_gb = ram_gb
        max_gb = max(1.0, min(ram_gb, 256.0))
        max_gb = int(max_gb * 2) / 2.0

        card = page.section("메모리 캐시")
        below = QWidget()
        bl = QVBoxLayout(below)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        line = QHBoxLayout()
        line.setSpacing(14)
        self.cache_slider = QSlider(Qt.Horizontal)
        self.cache_slider.setRange(1, int(max_gb * 2))
        self.cache_slider.setFixedHeight(22)
        self.cache_slider.setCursor(Qt.PointingHandCursor)
        self.cache_spin = Stepper(0.5, max_gb, 0.5, decimals=1, suffix=" GB", width=124)
        line.addWidget(self.cache_slider, 1)
        line.addWidget(self.cache_spin)
        bl.addLayout(line)
        self.cache_hint = QLabel()
        self.cache_hint.setObjectName("OptHint")
        self.cache_hint.setTextFormat(Qt.RichText)
        bl.addWidget(self.cache_hint)
        card.add(OptionRow("캐시 크기", f"재생할 프레임을 미리 읽어 두는 메모리 · 이 컴퓨터 {ram_gb:.1f} GB",
                           below=below))

        def slider_moved(v: int) -> None:
            if abs(self.cache_spin.value() - v / 2.0) > 1e-6:
                self.cache_spin.setValue(v / 2.0)
            self._update_cache_hint()

        def spin_changed(v: float) -> None:
            iv = int(round(v * 2))
            if self.cache_slider.value() != iv:
                self.cache_slider.blockSignals(True)
                self.cache_slider.setValue(iv)
                self.cache_slider.blockSignals(False)
            self._update_cache_hint()

        self.cache_slider.valueChanged.connect(slider_moved)
        self.cache_spin.valueChanged.connect(spin_changed)

        def set_cache(v) -> None:
            v = max(0.5, min(max_gb, round(float(v) * 2) / 2.0))
            self.cache_spin.setValue(v)
            spin_changed(v)

        self._bind(page, "cache_gb", lambda: float(self.cache_spin.value()), set_cache)

        behind = SliderField(0, 50, lambda v: f"{v}%", width=250)
        card.add(OptionRow("뒤쪽 캐시 비율",
                           "뒤로 이동하거나 거꾸로 재생할 때를 위해 현재 프레임 뒤쪽에 남겨 둘 캐시 비율", behind))
        self._bind(page, "cache_behind_ratio", lambda: round(behind.value() / 100.0, 3),
                   lambda v: behind.setValue(int(round(float(v) * 100))))

        card = page.section("디코딩")
        cores = os.cpu_count() or 4
        st = Stepper(1, 32, 1, suffix="", width=112)
        card.add(OptionRow("읽기 스레드", f"파일을 동시에 읽고 디코딩할 스레드 수 · CPU 코어 {cores}개 "
                                          "· 너무 많으면 디스크가 오히려 느려질 수 있습니다", st))
        self._bind(page, "reader_threads", lambda: int(st.value()), st.setValue)
        return page

    def _update_cache_hint(self) -> None:
        if not hasattr(self, "cache_hint"):
            return
        gb = self.cache_spin.value()
        pct = gb / max(self._ram_gb, 1e-6) * 100
        if pct > 80:
            col, msg = PAL.err, "다른 프로그램이 쓸 메모리가 부족해질 수 있습니다"
        elif pct > 60:
            col, msg = PAL.warn, "여유 메모리가 적어질 수 있습니다"
        else:
            col, msg = PAL.ok, "보통 전체 메모리의 40–60%가 적당합니다"
        self.cache_hint.setText(
            f'<span style="color:{col}">●</span>&nbsp; 전체 메모리의 '
            f'<span style="color:{PAL.text}">{pct:.0f}%</span> &nbsp;·&nbsp; {msg}')

    def _page_color(self) -> _Page:
        from cocseq.color.ocio_mgr import BUILTIN_CONFIGS

        page = _Page("color", "컬러 관리", "OpenColorIO 설정과 기본 색공간", "palette")
        self._builtin_configs = list(BUILTIN_CONFIGS)

        card = page.section("OCIO 설정")
        self.cfg_combo = QComboBox()
        self.cfg_combo.setFixedWidth(260)
        self.cfg_combo.setCursor(Qt.PointingHandCursor)
        below = QWidget()
        bl = QVBoxLayout(below)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.cfg_path = ElidedLabel()
        self.cfg_path.setObjectName("PathLabel")
        bl.addWidget(self.cfg_path)
        self.cfg_status = QLabel()
        self.cfg_status.setObjectName("OptHint")
        self.cfg_status.setTextFormat(Qt.RichText)
        self.cfg_status.setWordWrap(True)
        bl.addWidget(self.cfg_status)
        card.add(OptionRow("설정 파일", "색공간 목록과 디스플레이 변환을 정의하는 OCIO 설정", self.cfg_combo,
                           below=below))
        self._cfg_prev = 0
        self.cfg_combo.currentIndexChanged.connect(self._cfg_changed)

        env = os.environ.get("OCIO", "")
        self.prefer_env = ToggleSwitch()
        shown = env if len(env) <= 44 else "…" + env[-42:]
        env_desc = (f"$OCIO = {shown}" if env else "$OCIO: 설정 안 됨") + " · 켜면 위 설정 대신 환경 변수의 설정을 씁니다"
        row = OptionRow("$OCIO 환경 변수 우선", env_desc, self.prefer_env)
        if row.desc is not None and env:
            row.desc.setToolTip(env)
        card.add(row)
        self._bind(page, "ocio_prefer_env", self.prefer_env.isChecked,
                   lambda v: self.prefer_env.setChecked(bool(v)))
        self._bind(page, "ocio_config", self._cfg_value, self._set_cfg_value)
        self.prefer_env.toggled.connect(lambda _on: self._reload_ocio())

        card = page.section("기본 입력 색공간")
        self.cs_combos: dict[str, ValueCombo] = {}
        for name, title, desc in (
                ("cs_float", "실수 이미지", "EXR, HDR 등 16/32비트 float 이미지"),
                ("cs_int", "8/16비트 이미지", "PNG, JPEG, TIFF, DPX 등 정수 이미지"),
                ("cs_movie", "동영상", "MOV, MP4 등 동영상 파일")):
            cb = ValueCombo(270)
            card.add(OptionRow(title, desc, cb))
            self.cs_combos[name] = cb
            self._bind(page, name, cb.value, lambda v, c=cb: c.set_value(str(v)))

        card = page.section("화면 출력")
        self.display_combo = ValueCombo(270)
        self.view_combo = ValueCombo(270)
        card.add(OptionRow("디스플레이", "모니터의 색 표준", self.display_combo))
        card.add(OptionRow("뷰", "장면 색을 화면에 옮기는 방법 (톤 매핑 등)", self.view_combo))
        self._bind(page, "display", self.display_combo.value, lambda v: self._set_display(str(v)))
        self._bind(page, "view", self.view_combo.value, lambda v: self.view_combo.set_value(str(v)))
        self.display_combo.currentIndexChanged.connect(lambda _i: self._display_changed())
        return page

    # -- OCIO helpers

    def _fill_cfg_combo(self, custom: str = "") -> None:
        cb = self.cfg_combo
        cb.blockSignals(True)
        cb.clear()
        for label, uri in self._builtin_configs:
            cb.addItem(label, uri)
            cb.setItemData(cb.count() - 1, uri, Qt.ToolTipRole)
        if custom and custom not in [u for _, u in self._builtin_configs]:
            label = os.path.basename(custom) or custom
            if not os.path.exists(custom) and not custom.startswith("ocio://"):
                label += " (찾을 수 없음)"
            cb.addItem(label, custom)
            cb.setItemData(cb.count() - 1, custom, Qt.ToolTipRole)
        cb.insertSeparator(cb.count())
        cb.addItem("파일에서…", _BROWSE)
        cb.blockSignals(False)

    def _cfg_value(self) -> str:
        v = self.cfg_combo.currentData()
        if v == _BROWSE or v is None:
            v = self.cfg_combo.itemData(self._cfg_prev)
        return str(v or "")

    def _set_cfg_value(self, uri: str) -> None:
        uri = str(uri or "")
        self._fill_cfg_combo(uri)
        idx = self.cfg_combo.findData(uri) if uri else 0
        self.cfg_combo.blockSignals(True)
        self.cfg_combo.setCurrentIndex(max(0, idx))
        self.cfg_combo.blockSignals(False)
        self._cfg_prev = self.cfg_combo.currentIndex()
        if not self._loading:
            self._reload_ocio()

    def _cfg_changed(self, idx: int) -> None:
        if self.cfg_combo.itemData(idx) == _BROWSE:
            start = self._cfg_value()
            start_dir = os.path.dirname(start) if start and not start.startswith("ocio://") else ""
            path, _ = QFileDialog.getOpenFileName(self, "OCIO 설정 파일 선택", start_dir,
                                                  "OCIO 설정 (*.ocio);;모든 파일 (*)")
            if path:
                self._set_cfg_value(path)
            else:
                self.cfg_combo.blockSignals(True)
                self.cfg_combo.setCurrentIndex(self._cfg_prev)
                self.cfg_combo.blockSignals(False)
            return
        self._cfg_prev = idx
        self._reload_ocio()

    def _reload_ocio(self, force: bool = False, values: dict | None = None) -> None:
        from cocseq.color.ocio_mgr import ColorManager

        uri = self._cfg_value()
        prefer = self.prefer_env.isChecked()
        env = os.environ.get("OCIO", "")
        key = (uri, bool(prefer and env))
        if not force and (self._loading or key == self._ocio_key):
            return
        self._ocio_key = key
        if values is None:
            values = {n: self.cs_combos[n].value() for n in self.cs_combos}
            values["display"] = self.display_combo.value()
            values["view"] = self.view_combo.value()

        mgr = ColorManager()
        ok = mgr.load(uri, prefer)
        self._ocio_mgr = mgr
        used = mgr.uri if ok else ""
        self.cfg_path.setText(used or uri or "—")
        if not ok:
            self.cfg_status.setText(f'<span style="color:{PAL.err}">●</span>&nbsp; 설정을 불러오지 못했습니다'
                                    f' — {_html(mgr.error or "OpenColorIO 없음")}')
        else:
            n_cs, n_disp = len(mgr.colorspaces()), len(mgr.displays())
            counts = f"색공간 {n_cs}개 · 디스플레이 {n_disp}개"
            if prefer and env and used == env:
                msg = f'<span style="color:{PAL.ok}">●</span>&nbsp; $OCIO 설정을 쓰는 중 · {counts}'
            elif used != uri:
                msg = (f'<span style="color:{PAL.warn}">●</span>&nbsp; 이 설정을 불러오지 못해 '
                       f'{_html(mgr.config_label())}(으)로 대신합니다 · {counts}')
                self.cfg_status.setToolTip(mgr.error)
            else:
                msg = f'<span style="color:{PAL.ok}">●</span>&nbsp; 불러옴 · {counts}'
            self.cfg_status.setText(msg)

        entries = [(fam, name, name) for fam, name in mgr.colorspaces()]
        for n, cb in self.cs_combos.items():
            cb.populate(entries, values.get(n, ""), grouped=True)
        self.display_combo.blockSignals(True)
        self.display_combo.populate([(d, d) for d in mgr.displays()], values.get("display", ""))
        self.display_combo.blockSignals(False)
        self._fill_views(values.get("view", ""))

    def _fill_views(self, keep: str) -> None:
        mgr = self._ocio_mgr
        views = mgr.views(self.display_combo.value()) if mgr is not None else []
        self.view_combo.populate([(v, v) for v in views], keep)

    def _set_display(self, v: str) -> None:
        keep = self.view_combo.value()
        self.display_combo.blockSignals(True)
        self.display_combo.set_value(v)
        self.display_combo.blockSignals(False)
        self._fill_views(keep)

    def _display_changed(self) -> None:
        # The user picked another display: keep the view when it exists there, else use its default.
        mgr = self._ocio_mgr
        cur = self.view_combo.value()
        disp = self.display_combo.value()
        views = mgr.views(disp) if mgr is not None else []
        if cur not in views and views:
            try:
                cur = mgr.default_view(disp)
            except Exception:
                cur = views[0]
            if cur not in views:
                cur = views[0]
        self._fill_views(cur)

    # -- viewer

    def _page_viewer(self) -> _Page:
        page = _Page("viewer", "화면", "배경, HUD, 확대 필터, 화면비 가이드", "hud")
        card = page.section("배경")
        self.bg_combo = ValueCombo(170)
        self.bg_color = ColorButton(self._work.background_color, size=26)
        self.bg_color.setToolTip("사용자 배경색 고르기")
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(8)
        wl.addWidget(self.bg_color)
        wl.addWidget(self.bg_combo)
        card.add(OptionRow("배경", "이미지 바깥과 투명한 부분에 보이는 배경", wrap))
        self._populate_bg()
        self.bg_combo.currentIndexChanged.connect(lambda _i: self._update_background_controls())
        self.bg_color.colorChanged.connect(lambda _c: self._populate_bg())
        self._bind(page, "background", self.bg_combo.value, lambda v: self.bg_combo.set_value(str(v)))
        self._bind_color(page, "background_color", self.bg_color.color, self._set_bg_color)

        self.checker_step = Stepper(4, 128, 2, suffix=" px", width=112)
        self.checker_row = OptionRow("체커보드 칸 크기", "체커보드 배경의 한 칸 크기 (화면 픽셀)", self.checker_step)
        card.add(self.checker_row)
        self._bind(page, "checker_size", lambda: int(self.checker_step.value()), self.checker_step.setValue)

        card = page.section("HUD")
        self._switch(page, card, "hud", "기본으로 HUD 표시", "화면 모서리에 파일 정보를 겹쳐 보여 줍니다")
        chips = QWidget()
        grid = QGridLayout(chips)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.hud_chips: dict[str, QPushButton] = {}
        from cocseq import icons

        blank_pm = QPixmap(13, 13)
        blank_pm.fill(Qt.transparent)
        blank = QIcon(blank_pm)

        for i, (key, label) in enumerate(HUD_ITEMS):
            b = QPushButton(label)
            b.setProperty("chip", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoDefault(False)
            b.setIconSize(QSize(13, 13))
            b.setIcon(blank)
            b.toggled.connect(lambda on, btn=b: btn.setIcon(
                icons.icon("check", color=PAL.accent, size=13) if on else blank))
            grid.addWidget(b, i // 5, i % 5)
            self.hud_chips[key] = b
        card.add(OptionRow("표시 항목", "HUD에 보여 줄 정보를 고르세요", below=chips))

        def get_hud() -> list:
            known = [k for k, _ in HUD_ITEMS]
            out = [k for k in known if self.hud_chips[k].isChecked()]
            extra = [k for k in self._hud_extra if k not in known]
            return out + extra

        def set_hud(v) -> None:
            v = list(v or [])
            self._hud_extra = [k for k in v if k not in self.hud_chips]
            for k, b in self.hud_chips.items():
                b.setChecked(k in v)

        self._hud_extra: list = []
        self._bind(page, "hud_items", get_hud, set_hud)

        card = page.section("보기")
        self._switch(page, card, "filter_linear", "부드럽게 확대 (선형 필터)",
                     "끄면 확대했을 때 픽셀이 네모 그대로 보입니다")
        self._switch(page, card, "zoom_to_fit_on_open", "열 때 화면에 맞추기", "새 클립을 열면 창 크기에 맞춰 확대/축소합니다")
        ratio = ValueCombo(150)
        ratio.populate(SAFE_AREA_RATIOS)
        card.add(OptionRow("화면비 가이드", "안전 영역을 켤 때 함께 그릴 화면비 테두리", ratio))
        self._bind(page, "safe_area_ratio", ratio.value, lambda v: ratio.set_value(str(v)))
        return page

    def _populate_bg(self) -> None:
        cur = self.bg_combo.value() or "dark"
        self.bg_combo.blockSignals(True)
        self.bg_combo.populate([(k, t) for k, t, _ in BACKGROUNDS], cur)
        for row in range(self.bg_combo.count()):
            key = self.bg_combo.itemData(row, _VALUE_ROLE)
            col = next((c for k, _t, c in BACKGROUNDS if k == key), "")
            if key == "checker":
                ic = _chip_icon("", checker=True)
            elif key == "custom":
                ic = _chip_icon(self.bg_color.color())
            elif col:
                ic = _chip_icon(col)
            else:
                continue
            self.bg_combo.setItemIcon(row, ic)
        self.bg_combo.blockSignals(False)

    def _set_bg_color(self, v) -> None:
        self.bg_color.set_color(str(v))
        self._populate_bg()

    def _update_background_controls(self) -> None:
        if not hasattr(self, "bg_combo"):
            return
        key = self.bg_combo.value()
        self.bg_color.setVisible(key == "custom")
        self.checker_row.setEnabled(key == "checker")

    # -- audio

    def _page_audio(self) -> _Page:
        from cocseq import icons

        page = _Page("audio", "오디오", "출력 장치와 소리", "audio")
        card = page.section("출력")
        self.audio_combo = ValueCombo(240)
        refresh = IconButton("refresh", "장치 목록 새로 고침", size=16)
        refresh.setFixedSize(30, 30)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(6)
        wl.addWidget(refresh)
        wl.addWidget(self.audio_combo)
        card.add(OptionRow("출력 장치", "소리를 내보낼 장치", wrap))
        refresh.clicked.connect(lambda: self._fill_audio(self.audio_combo.value()))
        self._fill_audio(self._work.audio_device)
        self._bind(page, "audio_device", self.audio_combo.value, lambda v: self._fill_audio(str(v)))

        vol = SliderField(0, 100, lambda v: f"{v}%", width=250)
        vol_wrap = QWidget()
        vl = QHBoxLayout(vol_wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(10)
        vic = QLabel()
        vic.setPixmap(icons.pixmap("volume", 16, PAL.text3))
        vl.addWidget(vic)
        vl.addWidget(vol)
        card.add(OptionRow("음량", "", vol_wrap))
        self._bind(page, "volume", lambda: round(vol.value() / 100.0, 3),
                   lambda v: vol.setValue(int(round(float(v) * 100))))
        self._switch(page, card, "muted", "소리 끄기", "시작할 때 소리를 끈 상태로 둡니다")

        card = page.section("스크럽")
        self._switch(page, card, "audio_scrub", "스크럽 오디오",
                     "프레임을 옮길 때마다 그 위치의 소리를 짧게 들려줍니다")
        return page

    def _fill_audio(self, keep: str) -> None:
        try:
            from cocseq.media.audio import output_devices

            devices = output_devices()
        except Exception:
            devices = []
        entries = [("", "시스템 기본")] + [(d, d) for d in dict.fromkeys(devices)]
        self.audio_combo.populate(entries, keep)

    # -- annotation

    def _page_annotation(self) -> _Page:
        page = _Page("annotation", "주석", "그리기 도구의 기본값", "pen")
        card = page.section("펜")
        sw = SwatchRow(PEN_COLORS, self._work.pen_color,
                       ["빨강", "주황", "노랑", "초록", "하늘", "보라", "흰색"])
        card.add(OptionRow("기본 색", "새로 그리는 선과 도형의 색", sw))
        self._bind_color(page, "pen_color", sw.color, lambda v: sw.set_color(str(v)))
        self._pen_swatches = sw

        self.pen_preview = _PenPreview()
        size = SliderField(1, 40, lambda v: f"{v} px", width=220, value_width=46)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(12)
        wl.addWidget(self.pen_preview)
        wl.addWidget(size)
        card.add(OptionRow("기본 굵기", "펜과 도형 선의 두께", wrap))
        self._pen_size = size
        self._bind(page, "pen_size", lambda: float(size.value()), lambda v: size.setValue(int(round(float(v)))))
        size.valueChanged.connect(lambda _v: self._update_pen_preview())
        sw.colorChanged.connect(lambda _c: self._update_pen_preview())

        card = page.section("고스트")
        st = Stepper(0, 10, 1, suffix=" 프레임", width=124)
        card.add(OptionRow("고스트 프레임", "앞뒤 프레임의 주석을 흐리게 함께 보여 줍니다 · 0이면 끔", st))
        self._bind(page, "ghost_frames", lambda: int(st.value()), st.setValue)
        return page

    def _update_pen_preview(self) -> None:
        if hasattr(self, "pen_preview"):
            self.pen_preview.set(self._pen_swatches.color(), self._pen_size.value())


class _PenPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(76, 34)
        self._color = QColor("#FF4D5E")
        self._size = 4

    def set(self, color: str, size: int) -> None:
        self._color = QColor(color)
        self._size = size
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(PAL.qcolor("line"), 1))
        p.setBrush(PAL.qcolor("bg1"))
        p.drawRoundedRect(r, 8, 8)
        w = max(1.0, min(r.height() - 8, float(self._size)))
        pad = 8 + w / 2
        path = QPainterPath()
        y0, y1 = r.center().y() + 4, r.center().y() - 4
        path.moveTo(r.left() + pad, y0)
        path.cubicTo(r.center().x() - 6, y0 + 8, r.center().x() + 6, y1 - 8, r.right() - pad, y1)
        p.setClipRect(r.adjusted(1, 1, -1, -1))
        p.setPen(QPen(self._color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
