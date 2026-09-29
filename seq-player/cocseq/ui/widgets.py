"""Reusable styled widgets."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from cocseq.theme import PAL, mono_font, ui_font


def _icon(name: str, size: int = 18, color: str | None = None):
    from cocseq import icons

    return icons.icon(name, color=color, size=size)


class IconButton(QToolButton):
    def __init__(self, icon_name: str, tooltip: str = "", checkable: bool = False, size: int = 18,
                 role: str | None = None, parent=None, color: str | None = None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = size
        self._color = color
        self.setIcon(_icon(icon_name, size, color))
        self.setIconSize(QSize(size, size))
        self.setCheckable(checkable)
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        if role:
            self.setProperty("role", role)

    def set_icon_name(self, name: str) -> None:
        if name != self._icon_name:
            self._icon_name = name
            self.setIcon(_icon(name, self._icon_size, self._color))

    def refresh_icon(self) -> None:
        self.setIcon(_icon(self._icon_name, self._icon_size, self._color))


class ScrubField(QWidget):
    """Compact number field: drag left/right to change, double-click to type, right-click to reset."""

    valueChanged = Signal(float)

    def __init__(self, label: str = "", value: float = 0.0, minimum: float = -1e9, maximum: float = 1e9,
                 step: float = 0.01, decimals: int = 2, default: float | None = None, icon: str = "",
                 suffix: str = "", bar: bool = False, parent=None, width: int = 112):
        super().__init__(parent)
        self.label = label
        self.icon_name = icon
        self._value = float(value)
        self.minimum, self.maximum = minimum, maximum
        self.step = step
        self.decimals = decimals
        self.default = value if default is None else default
        self.suffix = suffix
        self.bar = bar
        self._drag_x = None
        self._drag_v = 0.0
        self._moved = False
        self._hover = False
        self._edit: QLineEdit | None = None
        self.setFixedHeight(28)
        self.setMinimumWidth(width)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setCursor(Qt.SizeHorCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("좌우로 드래그해서 조절 · 더블클릭해서 입력 · 우클릭하면 기본값")

    def value(self) -> float:
        return self._value

    def setValue(self, v: float, emit: bool = False) -> None:
        v = max(self.minimum, min(self.maximum, float(v)))
        v = round(v, self.decimals)
        if v != self._value:
            self._value = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def reset(self) -> None:
        self.setValue(self.default, emit=True)

    def text(self) -> str:
        return f"{self._value:.{self.decimals}f}{self.suffix}"

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = PAL.qcolor("bg4") if (self._hover or self._drag_x is not None) else PAL.qcolor("bg3")
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 7, 7)
        if self.bar and self.maximum > self.minimum and math.isfinite(self.maximum - self.minimum):
            k = (self._value - self.minimum) / (self.maximum - self.minimum)
            fill = QRectF(r.left() + 1, r.top() + 1, max(0.0, (r.width() - 2) * k), r.height() - 2)
            p.setPen(Qt.NoPen)
            p.setBrush(PAL.qcolor("accent", 0.18))
            p.drawRoundedRect(fill, 6, 6)
        x = r.left() + 9
        if self.icon_name:
            from cocseq import icons

            pm = icons.pixmap(self.icon_name, 14, PAL.text3 if self._value == self.default else PAL.accent)
            p.drawPixmap(QPointF(x, r.center().y() - 7), pm)
            x += 19
        if self.label:
            p.setFont(ui_font(8.5, QFont.DemiBold))
            p.setPen(PAL.qcolor("text3"))
            p.drawText(QRectF(x, r.top(), r.width(), r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)
        p.setFont(mono_font(9, QFont.Medium))
        changed = abs(self._value - self.default) > 1e-9
        p.setPen(PAL.qcolor("accent") if changed else PAL.qcolor("text"))
        p.drawText(r.adjusted(0, 0, -9, 0), Qt.AlignVCenter | Qt.AlignRight, self.text())

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag_x = ev.position().x()
            self._drag_v = self._value
            self._moved = False
        elif ev.button() == Qt.RightButton:
            self.reset()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_x is None:
            return
        dx = ev.position().x() - self._drag_x
        if abs(dx) > 2:
            self._moved = True
        mult = 0.1 if ev.modifiers() & Qt.ShiftModifier else (10.0 if ev.modifiers() & Qt.ControlModifier else 1.0)
        self.setValue(self._drag_v + (dx / 2.0) * self.step * mult, emit=True)

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_x = None
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        self._start_edit()

    def wheelEvent(self, ev) -> None:
        d = 1 if ev.angleDelta().y() > 0 else -1
        mult = 0.1 if ev.modifiers() & Qt.ShiftModifier else 1.0
        self.setValue(self._value + d * self.step * 10 * mult, emit=True)

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._start_edit()
        elif ev.key() == Qt.Key_Up:
            self.setValue(self._value + self.step * 10, emit=True)
        elif ev.key() == Qt.Key_Down:
            self.setValue(self._value - self.step * 10, emit=True)
        else:
            super().keyPressEvent(ev)

    def _start_edit(self) -> None:
        if self._edit is not None:
            return
        e = QLineEdit(self)
        e.setText(f"{self._value:.{self.decimals}f}")
        e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        e.setGeometry(self.rect())
        e.setStyleSheet(f"QLineEdit {{ font-family: 'JetBrains Mono'; border: 1px solid {PAL.accent}; "
                        f"border-radius: 7px; padding: 0 8px; background: {PAL.bg3}; }}")
        e.selectAll()
        e.show()
        e.setFocus()
        e.editingFinished.connect(self._finish_edit)
        self._edit = e

    def _finish_edit(self) -> None:
        e = self._edit
        if e is None:
            return
        self._edit = None
        try:
            self.setValue(float(e.text().replace(",", ".")), emit=True)
        except ValueError:
            pass
        e.deleteLater()
        self.setFocus()


class Segmented(QFrame):
    """Pill of exclusive buttons."""

    changed = Signal(str)

    def __init__(self, options: list[tuple], parent=None, icon_size: int = 16):
        """options: [(key, text, tooltip, icon_name_or_None)]"""
        super().__init__(parent)
        self.setProperty("class", "seg")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        for opt in options:
            key, text = opt[0], opt[1]
            tip = opt[2] if len(opt) > 2 else ""
            icon_name = opt[3] if len(opt) > 3 else None
            b = QToolButton(self)
            b.setCheckable(True)
            b.setProperty("role", "seg")
            b.setCursor(Qt.PointingHandCursor)
            if icon_name:
                b.setIcon(_icon(icon_name, icon_size))
                b.setIconSize(QSize(icon_size, icon_size))
                if text:
                    b.setText(text)
                    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            else:
                b.setText(text)
                bold = ui_font(9, QFont.DemiBold)
                b.setMinimumWidth(int(QFontMetricsF(bold).horizontalAdvance(text)) + 18)
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
            self._group.addButton(b)
            lay.addWidget(b)
            self._buttons[key] = b
        if options:
            self._buttons[options[0][0]].setChecked(True)

    def set_value(self, key: str) -> None:
        b = self._buttons.get(key)
        if b is not None:
            b.setChecked(True)

    def value(self) -> str:
        for k, b in self._buttons.items():
            if b.isChecked():
                return k
        return ""

    def button(self, key: str) -> QToolButton | None:
        return self._buttons.get(key)


class SectionTitle(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper() if text.isascii() else text, parent)
        self.setProperty("class", "section")


class Card(QFrame):
    def __init__(self, parent=None, margins=(12, 10, 12, 12), spacing=8):
        super().__init__(parent)
        self.setProperty("class", "card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(spacing)


def hline() -> QFrame:
    f = QFrame()
    f.setProperty("class", "hline")
    f.setFixedHeight(1)
    return f


def vline() -> QFrame:
    f = QFrame()
    f.setProperty("class", "vline")
    f.setFixedWidth(1)
    f.setFixedHeight(20)
    return f


def muted(text: str, cls: str = "muted") -> QLabel:
    l = QLabel(text)
    l.setProperty("class", cls)
    return l


class ColorButton(QToolButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#FF4D5E", parent=None, size: int = 22):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("색 고르기")
        self.clicked.connect(self._pick)

    def color(self) -> str:
        return self._color.name()

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c.isValid():
            self._color = c
            self.update()

    def _pick(self) -> None:
        c = QColorDialog.getColor(self._color, self, "색 선택")
        if c.isValid():
            self._color = c
            self.update()
            self.colorChanged.emit(c.name())

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.5))
        p.setBrush(self._color)
        p.drawEllipse(r)


class Swatches(QWidget):
    """A row of preset colors (plus a custom picker)."""

    colorChanged = Signal(str)

    def __init__(self, colors: list[str], current: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._colors = colors
        self._current = current or colors[0]
        self._btns = []
        for c in colors:
            b = _Swatch(c, self)
            b.clicked.connect(lambda _=False, col=c: self.set_color(col, emit=True))
            lay.addWidget(b)
            self._btns.append(b)
        self.custom = ColorButton(self._current, self, 22)
        self.custom.colorChanged.connect(lambda c: self.set_color(c, emit=True))
        lay.addWidget(self.custom)
        lay.addStretch(1)
        self._refresh()

    def color(self) -> str:
        return self._current

    def set_color(self, c: str, emit: bool = False) -> None:
        self._current = QColor(c).name()
        self.custom.set_color(self._current)
        self._refresh()
        if emit:
            self.colorChanged.emit(self._current)

    def _refresh(self) -> None:
        for b in self._btns:
            b.selected = b.color.lower() == self._current.lower()
            b.update()


class _Swatch(QToolButton):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self.selected = False
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.selected:
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(r)


class PanelHeader(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(14, 0, 8, 0)
        self.lay.setSpacing(4)
        self.title = QLabel(title)
        self.title.setProperty("class", "title")
        self.lay.addWidget(self.title)
        self.lay.addStretch(1)

    def add(self, w: QWidget) -> QWidget:
        self.lay.addWidget(w)
        return w


def form_row(label: str, widget: QWidget, label_width: int = 86) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    l = QLabel(label)
    l.setProperty("class", "muted")
    l.setFixedWidth(label_width)
    lay.addWidget(l)
    lay.addWidget(widget, 1)
    return w


def stack_row(label: str, widget: QWidget) -> QWidget:
    """Small muted label above a full-width control (for narrow side panels)."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    l = QLabel(label)
    l.setProperty("class", "faint")
    lay.addWidget(l)
    lay.addWidget(widget)
    return w


class KeyCap(QWidget):
    """Small keyboard key badge."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        f = mono_font(8)
        self.setFixedSize(int(QFontMetricsF(f).horizontalAdvance(text) + 14), 20)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        p.setBrush(PAL.qcolor("bg3"))
        p.drawRoundedRect(r, 5, 5)
        p.setFont(mono_font(8))
        p.setPen(PAL.qcolor("text2"))
        p.drawText(r, Qt.AlignCenter, self.text)
