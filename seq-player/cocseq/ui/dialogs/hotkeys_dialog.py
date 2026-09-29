"""Keyboard shortcut editor.

Usage::

    dlg = HotkeysDialog(prefs.hotkeys, parent)
    if dlg.exec():
        prefs.hotkeys = dlg.result_overrides()   # only entries that differ from the defaults

A value of "" in the overrides means the action is explicitly unassigned. Assigning a key
that another action already uses shows an inline warning; on save the other action's key
is cleared.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from PySide6.QtCore import QEvent, QKeyCombination, QModelIndex, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel,
                               QLineEdit, QMenu, QPushButton, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from cocseq.hotkeys import ACTIONS, BY_ID
from cocseq.theme import PAL, mono_font, ui_font
from cocseq.ui.widgets import IconButton, KeyCap

KIND_ROLE = Qt.UserRole + 1     # "cat" | "action" | "warn"
ID_ROLE = Qt.UserRole + 2

KEY_COL_WIDTH = 250
RESET_COL_WIDTH = 40

_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock,
                  Qt.Key_NumLock, Qt.Key_ScrollLock, Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_Hyper_L,
                  Qt.Key_Hyper_R, Qt.Key_unknown}

_KEY_NAMES = {"PgUp": "Page Up", "PgDown": "Page Down", "Left": "←", "Right": "→", "Up": "↑", "Down": "↓",
              "Del": "Delete", "Ins": "Insert"}


def normalize(seq: str) -> str:
    """Canonical portable text of a key sequence ("" stays "")."""
    if not seq:
        return ""
    ks = QKeySequence(seq, QKeySequence.PortableText)
    text = ks.toString(QKeySequence.PortableText)
    return text or seq


def key_parts(seq: str) -> list[list[str]]:
    """[["Ctrl", "Shift", "S"], ...] — one list per key combination, for drawing key caps."""
    if not seq:
        return []
    ks = QKeySequence(seq, QKeySequence.PortableText)
    mac = sys.platform == "darwin"
    names = ((Qt.MetaModifier, "⌃"), (Qt.AltModifier, "⌥"), (Qt.ShiftModifier, "⇧"), (Qt.ControlModifier, "⌘")) \
        if mac else ((Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Alt"), (Qt.ShiftModifier, "Shift"),
                     (Qt.MetaModifier, "Meta"))
    out = []
    for i in range(ks.count()):
        comb = ks[i]
        mods = comb.keyboardModifiers()
        parts = [n for flag, n in names if mods & flag]
        key = QKeySequence(comb.key()).toString(QKeySequence.NativeText) or "?"
        parts.append(_KEY_NAMES.get(key, key))
        out.append(parts)
    if not out:
        out.append([seq])
    return out


def display_text(seq: str) -> str:
    return ", ".join("+".join(p) for p in key_parts(seq))


# --------------------------------------------------------------------------- key capture


class KeyCaptureEdit(QKeySequenceEdit):
    """Records exactly one key combination. Esc cancels, Backspace/Delete clears."""

    captured = Signal(str)     # portable text; "" = clear
    cancelled = Signal()

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self._done = False
        self._line = self.findChild(QLineEdit)
        if current:
            self.setKeySequence(QKeySequence(current, QKeySequence.PortableText))
        self._prepare_line()
        self.setFocusPolicy(Qt.StrongFocus)

    def _prepare_line(self) -> None:
        # QKeySequenceEdit resets its own placeholder; set ours after it.
        if self._line is not None:
            self._line.setPlaceholderText("새 키를 누르세요…")
            self._line.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            if not self._done:
                self._line.clear()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._prepare_line()

    def focusInEvent(self, ev) -> None:
        super().focusInEvent(ev)
        self._prepare_line()

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        mods = ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
        if key == Qt.Key_Escape and not mods:
            self._finish(None)
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete) and not mods:
            self._finish("")
            return
        if key in _MODIFIER_KEYS or key == 0:
            self._show_mods(mods)
            return
        if key == Qt.Key_Backtab:
            key = Qt.Key_Tab
            mods |= Qt.ShiftModifier
        try:
            comb = QKeyCombination(Qt.KeyboardModifier(mods), Qt.Key(key))
        except (TypeError, ValueError):
            return
        seq = QKeySequence(comb)
        self.setKeySequence(seq)
        self._finish(seq.toString(QKeySequence.PortableText))

    def keyReleaseEvent(self, ev) -> None:
        if not self._done:
            mods = ev.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            self._show_mods(mods)

    def _show_mods(self, mods) -> None:
        if self._line is None:
            return
        parts = [n for flag, n in ((Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Alt"),
                                   (Qt.ShiftModifier, "Shift"), (Qt.MetaModifier, "Meta")) if mods & flag]
        self._line.setText("+".join(parts) + "+…" if parts else "")

    def focusOutEvent(self, ev) -> None:
        super().focusOutEvent(ev)
        if not self._done and ev.reason() != Qt.PopupFocusReason:
            self._finish(None)

    def _finish(self, value: str | None) -> None:
        if self._done:
            return
        self._done = True
        if value is None:
            self.cancelled.emit()
        else:
            self.captured.emit(value)


# --------------------------------------------------------------------------- tree + painting


class _HotkeyTree(QTreeWidget):
    activateRequested = Signal(object)    # QTreeWidgetItem
    clearRequested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = QModelIndex()
        self.setMouseTracking(True)

    def keyPressEvent(self, ev) -> None:
        item = self.currentItem()
        if item is not None and ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not ev.modifiers():
            self.activateRequested.emit(item)
            return
        if item is not None and ev.key() in (Qt.Key_Backspace, Qt.Key_Delete) and not ev.modifiers():
            self.clearRequested.emit(item)
            return
        super().keyPressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        idx = self.indexAt(ev.position().toPoint())
        idx = idx.siblingAtColumn(0) if idx.isValid() else QModelIndex()
        if idx != self._hover:
            self._hover = idx
            self.viewport().update()
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover = QModelIndex()
        self.viewport().update()
        super().leaveEvent(ev)

    def drawRow(self, painter, option, index) -> None:
        kind = index.siblingAtColumn(0).data(KIND_ROLE)
        if kind == "action":
            first = index.siblingAtColumn(0)
            selected = self.selectionModel().isSelected(first)
            hovered = first == self._hover
            if selected or hovered:
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                r = QRectF(option.rect).adjusted(4, 1, -4, -1)
                c = PAL.qcolor("accent", 0.14) if selected else PAL.qcolor("bg4", 0.8)
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                painter.drawRoundedRect(r, 7, 7)
                painter.restore()
        super().drawRow(painter, option, index)


class _HotkeyDelegate(QStyledItemDelegate):
    def __init__(self, dialog: "HotkeysDialog"):
        super().__init__(dialog)
        self.dlg = dialog

    def sizeHint(self, option, index) -> QSize:
        kind = index.siblingAtColumn(0).data(KIND_ROLE)
        if kind == "cat":
            return QSize(100, 36)
        if kind == "warn":
            return QSize(100, 30)
        return QSize(100, 34)

    def paint(self, p: QPainter, option, index) -> None:
        kind = index.siblingAtColumn(0).data(KIND_ROLE)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect)
        if kind == "cat":
            self._paint_category(p, r, index)
        elif kind == "warn":
            self._paint_warning(p, r, index)
        elif kind == "action":
            if index.column() == 0:
                self._paint_label(p, r, index)
            elif index.column() == 1:
                self._paint_keys(p, r, index.siblingAtColumn(0).data(ID_ROLE))
        p.restore()

    def _paint_category(self, p, r: QRectF, index) -> None:
        from cocseq import icons

        tree = self.dlg.tree
        item = tree.itemFromIndex(index.siblingAtColumn(0))
        if index.row() > 0:
            p.setPen(QPen(PAL.qcolor("line"), 1))
            p.drawLine(r.left() + 10, r.top() + 0.5, r.right() - 10, r.top() + 0.5)
        expanded = item.isExpanded() if item is not None else True
        pm = icons.pixmap("chevron-down" if expanded else "chevron-right", 14, PAL.text3)
        p.drawPixmap(int(r.left() + 10), int(r.center().y() - 7), pm)
        f = ui_font(9.5, QFont.DemiBold)
        p.setFont(f)
        p.setPen(PAL.qcolor("text"))
        name = index.data(Qt.DisplayRole)
        x = r.left() + 32
        p.drawText(QRectF(x, r.top(), r.width(), r.height()), Qt.AlignVCenter | Qt.AlignLeft, name)
        w = QFontMetricsF(f).horizontalAdvance(name)
        visible, total, changed = self.dlg._category_counts(name)
        p.setFont(ui_font(8.5))
        p.setPen(PAL.qcolor("text3"))
        cnt = f"{visible}/{total}" if visible != total else f"{total}"
        p.drawText(QRectF(x + w + 8, r.top(), 120, r.height()), Qt.AlignVCenter | Qt.AlignLeft, cnt)
        if changed:
            txt = f"{changed}개 바뀜"
            fm = QFontMetricsF(ui_font(8, QFont.Bold))
            bw = fm.horizontalAdvance(txt) + 12
            badge = QRectF(r.right() - bw - 14, r.center().y() - 9, bw, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(PAL.qcolor("accent", 0.16))
            p.drawRoundedRect(badge, 5, 5)
            p.setFont(ui_font(8, QFont.Bold))
            p.setPen(PAL.qcolor("accent"))
            p.drawText(badge, Qt.AlignCenter, txt)

    def _paint_label(self, p, r: QRectF, index) -> None:
        aid = index.data(ID_ROLE)
        a = BY_ID.get(aid)
        x = r.left() + 34
        if a is not None and a.icon:
            from cocseq import icons

            pm = icons.pixmap(a.icon, 16, PAL.text3)
            p.drawPixmap(int(x), int(r.center().y() - 8), pm)
        x += 26
        p.setFont(ui_font(9.5))
        p.setPen(PAL.qcolor("text"))
        text = index.data(Qt.DisplayRole) or ""
        fm = QFontMetricsF(ui_font(9.5))
        avail = r.right() - x - 8
        p.drawText(QRectF(x, r.top(), avail, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(text, Qt.ElideRight, avail))

    def _paint_keys(self, p, r: QRectF, aid: str) -> None:
        if self.dlg._editing == aid:
            return
        seq = self.dlg._keys.get(aid, "")
        state = self.dlg._row_state(aid)
        x = r.left() + 6
        cy = r.center().y()
        if not seq:
            p.setFont(ui_font(9))
            p.setPen(PAL.qcolor("text3"))
            p.drawText(QRectF(x + 2, r.top(), r.width(), r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       "없음" if state != "modified" else "없음 (비움)")
            return
        f = mono_font(8.5, QFont.Medium)
        fm = QFontMetricsF(f)
        p.setFont(f)
        loser = state == "loser"
        if loser:
            p.setOpacity(0.45)
        for gi, group in enumerate(key_parts(seq)):
            if gi:
                p.setPen(PAL.qcolor("text3"))
                p.drawText(QRectF(x, r.top(), 12, r.height()), Qt.AlignCenter, ",")
                x += 12
            for part in group:
                w = max(22.0, fm.horizontalAdvance(part) + 14)
                chip = QRectF(x, cy - 10.5, w, 21)
                if state == "modified":
                    p.setPen(QPen(PAL.qcolor("accent", 0.6), 1))
                    p.setBrush(PAL.qcolor("accent", 0.13))
                elif state in ("winner", "clash"):
                    p.setPen(QPen(PAL.qcolor("warn", 0.7), 1))
                    p.setBrush(PAL.qcolor("warn", 0.12))
                else:
                    p.setPen(QPen(PAL.qcolor("line2"), 1))
                    p.setBrush(PAL.qcolor("bg3"))
                p.drawRoundedRect(chip.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
                # key cap bottom edge
                p.setPen(QPen(QColor(0, 0, 0, 70), 1))
                p.drawLine(chip.left() + 4, chip.bottom() - 0.5, chip.right() - 4, chip.bottom() - 0.5)
                p.setPen(PAL.qcolor("text"))
                p.drawText(chip, Qt.AlignCenter, part)
                x += w + 4
        if loser:
            p.setOpacity(1.0)
            p.setPen(QPen(PAL.qcolor("err", 0.85), 1.2))
            p.drawLine(r.left() + 4, cy, x - 2, cy)
            p.setFont(ui_font(8.5))
            p.setPen(PAL.qcolor("err"))
            p.drawText(QRectF(x + 4, r.top(), r.right() - x - 4, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       "저장하면 비워짐")

    def _paint_warning(self, p, r: QRectF, index) -> None:
        from cocseq import icons

        box = QRectF(r.left() + 34, r.top() + 2, r.width() - 48, r.height() - 6)
        p.setPen(Qt.NoPen)
        p.setBrush(PAL.qcolor("warn", 0.09))
        p.drawRoundedRect(box, 6, 6)
        pm = icons.pixmap("info", 14, PAL.warn)
        p.drawPixmap(int(box.left() + 8), int(box.center().y() - 7), pm)
        p.setFont(ui_font(8.8))
        p.setPen(PAL.qcolor("warn"))
        text = index.data(Qt.DisplayRole) or ""
        fm = QFontMetricsF(ui_font(8.8))
        avail = box.width() - 38
        p.drawText(QRectF(box.left() + 28, box.top(), avail, box.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(text, Qt.ElideRight, avail))


# --------------------------------------------------------------------------- dialog


def _qss() -> str:
    P = PAL
    return f"""
QTreeWidget#HotkeyTree {{
    background: {P.bg2};
    border: 1px solid {P.line};
    border-radius: 12px;
    padding: 4px 0;
}}
QTreeWidget#HotkeyTree::item,
QTreeWidget#HotkeyTree::item:hover,
QTreeWidget#HotkeyTree::item:selected {{
    background: transparent;
    border: none;
    padding: 0;
}}
QTreeWidget#HotkeyTree::branch {{ background: transparent; border: none; image: none; }}
QTreeWidget#HotkeyTree QHeaderView {{ background: transparent; border: none; }}
QTreeWidget#HotkeyTree QHeaderView::section {{
    background: {P.bg2};
    color: {P.text3};
    border: none;
    border-bottom: 1px solid {P.line};
    padding: 4px 8px 8px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QTreeWidget#HotkeyTree QHeaderView::section:first {{ padding-left: 60px; border-top-left-radius: 12px; }}
QTreeWidget#HotkeyTree QHeaderView::section:middle {{ padding-left: 7px; }}
QLabel#HkTitle {{ font-size: 18px; font-weight: 600; color: {P.text}; }}
QLabel#HkSub {{ color: {P.text3}; font-size: 11.5px; }}
QLabel#HkHint {{ color: {P.text3}; font-size: 11px; }}
QLabel#HkEmpty {{ color: {P.text3}; font-size: 12px; background: transparent; }}
QLabel#HkBadge {{
    background: {P.rgba(P.accent, 0.16)};
    color: {P.accent};
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QLineEdit#HkSearch {{
    background: {P.bg2};
    border: 1px solid {P.line2};
    border-radius: 9px;
    padding: 7px 10px 7px 6px;
    font-size: 12.5px;
}}
QLineEdit#HkSearch:focus {{ border-color: {P.rgba(P.accent, 0.55)}; background: {P.bg2}; }}
QWidget#HkFooter {{ background: {P.bg1}; border-top: 1px solid {P.line}; }}
QWidget#HkEditorHost {{ background: transparent; }}
KeyCaptureEdit QLineEdit, QKeySequenceEdit QLineEdit {{
    background: {P.bg1};
    border: 1px solid {P.accent};
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11.5px;
    color: {P.text};
}}
"""


class HotkeysDialog(QDialog):
    """Edit keyboard shortcuts. ``result_overrides()`` returns {action id: key text} for changed actions."""

    def __init__(self, overrides: dict, parent=None):
        super().__init__(parent)
        self._input = dict(overrides or {})
        self._defaults = {a.id: normalize(a.default) for a in ACTIONS}
        self._keys: dict[str, str] = {}
        for a in ACTIONS:
            if a.id in self._input:
                self._keys[a.id] = normalize(str(self._input[a.id] or ""))
            else:
                self._keys[a.id] = self._defaults[a.id]
        self._order: list[str] = []          # edit order, most recent last (decides who keeps a clashing key)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._cats: dict[str, QTreeWidgetItem] = {}
        self._reset_buttons: dict[str, IconButton] = {}
        self._warn_items: list[QTreeWidgetItem] = []
        self._winners: dict[str, list[str]] = {}
        self._losers: dict[str, str] = {}
        self._clashes: dict[str, list[str]] = {}
        self._editing: str | None = None
        self._editor: KeyCaptureEdit | None = None
        self._editor_host: QWidget | None = None
        self._effective: dict[str, str] = {}
        self._collapsed: set[str] = set()

        self.setWindowTitle("단축키")
        self.setModal(True)
        self.resize(760, 620)
        self.setMinimumSize(620, 460)
        self.setStyleSheet(_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(24, 20, 24, 12)
        bv.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(12)
        from cocseq import icons

        ic = QLabel()
        ic.setPixmap(icons.pixmap("keyboard", 26, PAL.text2))
        ic.setFixedSize(30, 30)
        head.addWidget(ic, 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        t = QLabel("단축키")
        t.setObjectName("HkTitle")
        s = QLabel("동작을 더블클릭하거나 Enter를 눌러 새 키를 입력하세요")
        s.setObjectName("HkSub")
        tv.addWidget(t)
        tv.addWidget(s)
        head.addLayout(tv, 1)
        self.badge = QLabel()
        self.badge.setObjectName("HkBadge")
        head.addWidget(self.badge, 0, Qt.AlignVCenter)
        bv.addLayout(head)
        bv.addSpacing(16)

        self.search = QLineEdit()
        self.search.setObjectName("HkSearch")
        self.search.setPlaceholderText("동작 이름이나 키로 찾기  (예: 재생, Ctrl+S, F5)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", size=16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._search_changed)
        self.search.returnPressed.connect(self._focus_first_visible)
        self.search.installEventFilter(self)
        bv.addWidget(self.search)
        bv.addSpacing(10)

        self.tree = _HotkeyTree()
        self.tree.setObjectName("HotkeyTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["동작", "단축키", ""])
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.resizeSection(1, KEY_COL_WIDTH)
        hdr.resizeSection(2, RESET_COL_WIDTH)
        hdr.setSectionsClickable(False)
        hdr.setSectionsMovable(False)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setItemsExpandable(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setItemDelegate(_HotkeyDelegate(self))
        self.tree.itemClicked.connect(self._item_clicked)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._activate(it))
        self.tree.activateRequested.connect(self._activate)
        self.tree.clearRequested.connect(self._clear_item)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemExpanded.connect(self._expanded_changed)
        self.tree.itemCollapsed.connect(self._expanded_changed)
        bv.addWidget(self.tree, 1)

        self.empty = QLabel("", self.tree.viewport())
        self.empty.setObjectName("HkEmpty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()

        bv.addSpacing(10)
        hints = QHBoxLayout()
        hints.setSpacing(6)
        for key, what in (("Enter", "바꾸기"), ("Backspace", "지우기"), ("Esc", "입력 취소")):
            hints.addWidget(KeyCap(key))
            h = QLabel(what)
            h.setObjectName("HkHint")
            hints.addWidget(h)
            hints.addSpacing(10)
        hints.addStretch(1)
        tip = QLabel("같은 키를 쓰는 다른 동작은 저장할 때 비워집니다")
        tip.setObjectName("HkHint")
        hints.addWidget(tip)
        bv.addLayout(hints)
        root.addWidget(body, 1)

        footer = QWidget()
        footer.setObjectName("HkFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.setSpacing(8)
        self.btn_defaults = QPushButton("모두 기본값으로")
        self.btn_defaults.setProperty("variant", "ghost")
        self.btn_defaults.setIcon(icons.icon("refresh", size=16))
        self.btn_defaults.setIconSize(QSize(15, 15))
        self.btn_defaults.setToolTip("모든 단축키를 처음 상태로 되돌립니다")
        self.btn_defaults.clicked.connect(self.reset_all)
        fl.addWidget(self.btn_defaults)
        fl.addStretch(1)
        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setMinimumWidth(76)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("저장")
        self.btn_save.setProperty("variant", "primary")
        self.btn_save.setMinimumWidth(86)
        self.btn_save.clicked.connect(self.accept)
        for b in (self.btn_defaults, self.btn_cancel, self.btn_save):
            b.setAutoDefault(False)
            b.setDefault(False)
            b.setCursor(Qt.PointingHandCursor)
        fl.addWidget(self.btn_cancel)
        fl.addWidget(self.btn_save)
        root.addWidget(footer)

        self._build_items()
        self._refresh()

    # ------------------------------------------------------------ public API

    def result_overrides(self) -> dict:
        """{action id: key text} for every action whose key differs from its default ("" = unassigned).

        Keys taken over by another action in this dialog are cleared. Entries for action ids
        this version does not know are kept as they were.
        """
        out = {k: v for k, v in self._input.items() if k not in BY_ID}
        for aid, key in self.effective_keys().items():
            if key != self._defaults[aid]:
                out[aid] = key
        return out

    def effective_keys(self) -> dict:
        """Every action's key as it will be saved (conflicts resolved)."""
        return {aid: ("" if aid in self._losers else k) for aid, k in self._keys.items()}

    def set_key(self, action_id: str, key: str) -> None:
        """Assign ``key`` to an action as if the user typed it ("" clears)."""
        if action_id not in self._keys:
            return
        self._keys[action_id] = normalize(key)
        if action_id in self._order:
            self._order.remove(action_id)
        self._order.append(action_id)
        self._refresh()

    def reset_action(self, action_id: str) -> None:
        self.set_key(action_id, self._defaults.get(action_id, ""))

    def reset_all(self) -> None:
        self._cancel_edit()
        self._keys = dict(self._defaults)
        self._order.clear()
        self._refresh()

    def conflicts(self) -> dict:
        """{action that keeps the key: [actions that will be cleared]}"""
        return {k: list(v) for k, v in self._winners.items()}

    # ------------------------------------------------------------ building

    def _build_items(self) -> None:
        cats: dict[str, list] = {}
        for a in ACTIONS:
            cats.setdefault(a.category, []).append(a)
        for cat, actions in cats.items():
            ci = QTreeWidgetItem([cat, "", ""])
            ci.setData(0, KIND_ROLE, "cat")
            ci.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(ci)
            ci.setFirstColumnSpanned(True)
            self._cats[cat] = ci
            for a in actions:
                it = QTreeWidgetItem([a.label, "", ""])
                it.setData(0, KIND_ROLE, "action")
                it.setData(0, ID_ROLE, a.id)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                ci.addChild(it)
                self._items[a.id] = it
                btn = IconButton("refresh", "기본값으로 되돌리기", size=14)
                btn.setFixedSize(26, 26)
                btn.setFocusPolicy(Qt.NoFocus)
                btn.clicked.connect(lambda _c=False, aid=a.id: self.reset_action(aid))
                host = QWidget()
                host.setObjectName("HkEditorHost")
                hl = QHBoxLayout(host)
                hl.setContentsMargins(0, 0, 8, 0)
                hl.addStretch(1)
                hl.addWidget(btn)
                self.tree.setItemWidget(it, 2, host)
                self._reset_buttons[a.id] = btn
            ci.setExpanded(True)

    # ------------------------------------------------------------ state

    def _compute_conflicts(self) -> None:
        by_key: dict[str, list[str]] = defaultdict(list)
        for aid, k in self._keys.items():
            if k:
                by_key[k].append(aid)
        self._winners, self._losers, self._clashes = {}, {}, {}
        rank = {aid: i for i, aid in enumerate(self._order)}
        for _k, ids in by_key.items():
            if len(ids) < 2:
                continue
            edited = [a for a in ids if a in rank]
            if edited:
                w = max(edited, key=lambda a: rank[a])
                others = [a for a in ids if a != w]
                self._winners[w] = others
                for a in others:
                    self._losers[a] = w
            else:
                for a in ids:
                    self._clashes[a] = [b for b in ids if b != a]

    def _row_state(self, aid: str) -> str:
        if aid in self._losers:
            return "loser"
        if aid in self._winners:
            return "winner"
        if aid in self._clashes:
            return "clash"
        if self._keys.get(aid, "") != self._defaults.get(aid, ""):
            return "modified"
        return "default"

    def _category_counts(self, cat: str) -> tuple[int, int, int]:
        ci = self._cats.get(cat)
        if ci is None:
            return 0, 0, 0
        total = visible = changed = 0
        for i in range(ci.childCount()):
            ch = ci.child(i)
            if ch.data(0, KIND_ROLE) != "action":
                continue
            total += 1
            if not ch.isHidden():
                visible += 1
            aid = ch.data(0, ID_ROLE)
            if self._effective.get(aid, "") != self._defaults[aid]:
                changed += 1
        return visible, total, changed

    def _refresh(self) -> None:
        self._compute_conflicts()
        self._effective = self.effective_keys()
        # warning rows
        for w in self._warn_items:
            parent = w.parent()
            if parent is not None:
                parent.removeChild(w)
        self._warn_items.clear()
        for aid, others in list(self._winners.items()) + list(self._clashes.items()):
            it = self._items[aid]
            names = ", ".join(f"'{BY_ID[o].label}'" for o in others)
            if aid in self._winners:
                msg = f"이미 {names}에 쓰이고 있습니다 — 저장하면 그쪽 단축키는 비워집니다"
            else:
                msg = f"{names}와(과) 같은 키입니다 — 한쪽을 바꾸세요"
            wi = QTreeWidgetItem([msg, "", ""])
            wi.setData(0, KIND_ROLE, "warn")
            wi.setData(0, ID_ROLE, aid)
            wi.setFlags(Qt.NoItemFlags)
            wi.setToolTip(0, msg)
            parent = it.parent()
            parent.insertChild(parent.indexOfChild(it) + 1, wi)
            wi.setFirstColumnSpanned(True)
            wi.setHidden(it.isHidden())
            self._warn_items.append(wi)
        # per-row bits
        for aid, it in self._items.items():
            state = self._row_state(aid)
            btn = self._reset_buttons[aid]
            btn.setVisible(self._keys[aid] != self._defaults[aid] or state == "loser")
            a = BY_ID[aid]
            dflt = display_text(self._defaults[aid]) or "없음"
            tip = f"{a.label}\n기본값: {dflt}"
            if state == "loser":
                tip += f"\n'{BY_ID[self._losers[aid]].label}'에 키를 넘겨주고 저장하면 비워집니다"
            it.setToolTip(0, tip)
            it.setToolTip(1, tip)
        n = sum(1 for aid, k in self._effective.items() if k != self._defaults[aid])
        self.badge.setText(f"{n}개 바뀜")
        self.badge.setVisible(n > 0)
        self._apply_filter(self.search.text())
        self.tree.viewport().update()

    # ------------------------------------------------------------ filtering

    def _matches(self, aid: str, q: str) -> bool:
        a = BY_ID[aid]
        key = self._keys.get(aid, "")
        hay = " ".join((a.label, a.id, a.category, key, display_text(key),
                        QKeySequence(key, QKeySequence.PortableText).toString(QKeySequence.NativeText)
                        if key else "")).lower()
        return all(tok in hay for tok in q.split())

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()
        any_visible = False
        for cat, ci in self._cats.items():
            cat_hit = bool(q) and q in cat.lower()
            vis = 0
            for i in range(ci.childCount()):
                ch = ci.child(i)
                if ch.data(0, KIND_ROLE) != "action":
                    continue
                show = not q or cat_hit or self._matches(ch.data(0, ID_ROLE), q)
                ch.setHidden(not show)
                vis += show
            for w in self._warn_items:
                owner = self._items.get(w.data(0, ID_ROLE))
                if owner is not None and w.parent() is ci:
                    w.setHidden(owner.isHidden())
            ci.setHidden(vis == 0)
            any_visible |= vis > 0
            want = True if q else cat not in self._collapsed
            if ci.isExpanded() != want:
                self.tree.blockSignals(True)
                ci.setExpanded(want)
                self.tree.blockSignals(False)
        if any_visible:
            self.empty.hide()
        else:
            self.empty.setText(f"'{text.strip()}'에 맞는 동작이 없습니다")
            self.empty.setGeometry(self.tree.viewport().rect())
            self.empty.show()
        self.tree.viewport().update()

    def _search_changed(self, text: str) -> None:
        self._apply_filter(text)
        self.tree.scrollToTop()

    def _expanded_changed(self, item: QTreeWidgetItem) -> None:
        if self.search.text().strip():
            return
        cat = item.text(0)
        if item.isExpanded():
            self._collapsed.discard(cat)
        else:
            self._collapsed.add(cat)

    def _focus_first_visible(self) -> None:
        for aid, it in self._items.items():
            if not it.isHidden() and not it.parent().isHidden():
                self.tree.setCurrentItem(it)
                self.tree.setFocus()
                return

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.search and ev.type() == QEvent.KeyPress:
            if ev.key() == Qt.Key_Down:
                self._focus_first_visible()
                return True
            if ev.key() == Qt.Key_Escape and self.search.text():
                self.search.clear()
                return True
        return super().eventFilter(obj, ev)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self.empty.isVisible():
            self.empty.setGeometry(self.tree.viewport().rect())

    # ------------------------------------------------------------ interaction

    def _item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.data(0, KIND_ROLE) == "cat":
            item.setExpanded(not item.isExpanded())

    def _activate(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, KIND_ROLE)
        if kind == "cat":
            item.setExpanded(not item.isExpanded())
        elif kind == "action":
            self.begin_edit(item.data(0, ID_ROLE))

    def _clear_item(self, item: QTreeWidgetItem) -> None:
        if item.data(0, KIND_ROLE) == "action":
            self.set_key(item.data(0, ID_ROLE), "")

    def begin_edit(self, aid: str) -> KeyCaptureEdit | None:
        it = self._items.get(aid)
        if it is None:
            return None
        self._cancel_edit()
        self._editing = aid
        host = QWidget()
        host.setObjectName("HkEditorHost")
        hl = QHBoxLayout(host)
        hl.setContentsMargins(2, 4, 6, 4)
        ed = KeyCaptureEdit(self._keys.get(aid, ""))
        hl.addWidget(ed)
        host.setFocusProxy(ed)
        ed.captured.connect(lambda key, a=aid: self._end_edit(a, key))
        ed.cancelled.connect(lambda a=aid: self._end_edit(a, None))
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)
        self.tree.setItemWidget(it, 1, host)
        ed.setFocus(Qt.OtherFocusReason)
        self._editor = ed
        self._editor_host = host
        self.tree.viewport().update()
        return ed

    def _end_edit(self, aid: str, key: str | None) -> None:
        if self._editing != aid:
            return
        self._editing = None
        self._editor = None
        it = self._items[aid]
        host, self._editor_host = self._editor_host, None
        # Removing the widget deletes it; do it after the key event that triggered us returns.
        QTimer.singleShot(0, lambda: self._drop_editor(it, host))
        if key is not None:
            self.set_key(aid, key)
        else:
            self.tree.viewport().update()
        self.tree.setFocus(Qt.OtherFocusReason)

    def _drop_editor(self, it: QTreeWidgetItem, host: QWidget | None) -> None:
        if host is not None and self.tree.itemWidget(it, 1) is host:
            self.tree.removeItemWidget(it, 1)

    def _cancel_edit(self) -> None:
        if self._editing is not None:
            if self._editor is not None:
                self._editor._done = True
            aid = self._editing
            self._editing = None
            self._editor = None
            self._editor_host = None
            self.tree.removeItemWidget(self._items[aid], 1)
            self.tree.viewport().update()

    def _context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, KIND_ROLE) != "action":
            return
        aid = item.data(0, ID_ROLE)
        from cocseq import icons

        m = QMenu(self)
        m.addAction(icons.icon("keyboard", size=16), "단축키 바꾸기…", lambda: self.begin_edit(aid))
        m.addAction(icons.icon("close", size=16), "단축키 지우기", lambda: self.set_key(aid, ""))
        reset = m.addAction(icons.icon("refresh", size=16), "기본값으로 되돌리기", lambda: self.reset_action(aid))
        reset.setEnabled(self._keys[aid] != self._defaults[aid])
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def reject(self) -> None:
        if self._editing is not None:
            self._cancel_edit()
            return
        super().reject()

    def accept(self) -> None:
        self._cancel_edit()
        super().accept()
