"""Annotation panel and the floating drawing tool bar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget)

from cocseq.theme import PAL
from cocseq.ui.widgets import Card, IconButton, ScrubField, SectionTitle, Swatches, form_row

TOOLS = [
    ("", "hand", "선택/이동 (V)"),
    ("pen", "pen", "펜 (P)"),
    ("eraser", "eraser", "지우개 (E)"),
    ("line", "line", "직선 (Shift+L)"),
    ("arrow", "arrow", "화살표 (Shift+A)"),
    ("rect", "rect", "사각형 (Shift+R)"),
    ("ellipse", "ellipse", "원 (Shift+C)"),
    ("text", "text", "텍스트 (T)"),
    ("area", "select-area", "영역 선택 — 색 정보 (Shift+M)"),
]
PEN_COLORS = ["#FF4D5E", "#FFB23F", "#FFE45C", "#3DD68C", "#38C6F4", "#9C7BFF", "#FFFFFF"]


class ToolBar(QFrame):
    """Vertical pill of drawing tools floating over the left edge of the viewer."""

    toolChosen = Signal(str)
    undo = Signal()
    redo = Signal()
    clearFrame = Signal()
    colorClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AnnotationBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 6, 5, 6)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QToolButton] = {}
        for key, icon, tip in TOOLS:
            b = IconButton(icon, tip, checkable=True, size=18)
            b.setFixedSize(32, 32)
            b.clicked.connect(lambda _=False, k=key: self.toolChosen.emit(k))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            if key == "eraser" or key == "text":
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {PAL.line2}; margin: 3px 4px;")
                lay.addWidget(sep)
        self.color_btn = QToolButton()
        self.color_btn.setFixedSize(32, 26)
        self.color_btn.setToolTip("펜 색")
        self.color_btn.setCursor(Qt.PointingHandCursor)
        self.color_btn.clicked.connect(self.colorClicked)
        lay.addWidget(self.color_btn)
        for icon, tip, sig in (("undo", "실행 취소 (Ctrl+Z)", self.undo), ("redo", "다시 실행 (Ctrl+Shift+Z)", self.redo),
                               ("trash", "현재 프레임 주석 지우기", self.clearFrame)):
            b = IconButton(icon, tip, size=17)
            b.setFixedSize(32, 30)
            b.clicked.connect(sig)
            lay.addWidget(b)
        self.buttons[""].setChecked(True)
        self.set_color("#FF4D5E")

    def set_tool(self, tool: str) -> None:
        b = self.buttons.get(tool)
        if b is not None:
            b.setChecked(True)

    def set_color(self, color: str) -> None:
        self.color_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
        self.color_btn.setIcon(_dot_icon(color))
        self.color_btn.setIconSize(QSize(18, 18))


def _dot_icon(color: str):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    pm = QPixmap(36, 36)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(255, 255, 255, 90), 3))
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 28, 28)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


class AnnotatePanel(QWidget):
    toolChosen = Signal(str)
    styleChanged = Signal()                # color / size / fill / hold / ghost
    jumpRequested = Signal(int)
    undo = Signal()
    redo = Signal()
    clearFrame = Signal()
    clearAll = Signal()
    exportPdf = Signal()
    noteEdited = Signal(str)
    visibilityToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 12)
        lay.setSpacing(10)

        lay.addWidget(SectionTitle("도구"))
        grid = QGridLayout()
        grid.setSpacing(5)
        self.group = QButtonGroup(self)
        self.tool_buttons: dict[str, QToolButton] = {}
        for i, (key, icon, tip) in enumerate(TOOLS):
            b = IconButton(icon, tip, checkable=True, size=19)
            b.setFixedSize(40, 36)
            b.setStyleSheet(f"QToolButton {{ background: {PAL.bg3}; border: 1px solid {PAL.line}; border-radius: 9px; }}"
                            f"QToolButton:checked {{ background: {PAL.rgba(PAL.accent, 0.16)};"
                            f" border-color: {PAL.rgba(PAL.accent, 0.55)}; }}")
            b.clicked.connect(lambda _=False, k=key: self.toolChosen.emit(k))
            self.group.addButton(b)
            grid.addWidget(b, i // 5, i % 5)
            self.tool_buttons[key] = b
        lay.addLayout(grid)

        lay.addWidget(SectionTitle("스타일"))
        card = Card()
        self.swatches = Swatches(PEN_COLORS, PEN_COLORS[0])
        self.swatches.colorChanged.connect(self._style)
        card.lay.addWidget(self.swatches)
        self.size = ScrubField("굵기", 4.0, 1, 60, 0.1, 1, 4.0, suffix=" px", bar=True, width=150)
        self.size.valueChanged.connect(self._style)
        card.lay.addWidget(self.size)
        self.fill = QCheckBox("도형 안쪽 채우기")
        self.fill.toggled.connect(self._style)
        card.lay.addWidget(self.fill)
        self.hold = QSpinBox()
        self.hold.setRange(1, 100000)
        self.hold.setSuffix(" 프레임")
        self.hold.valueChanged.connect(self._style)
        card.lay.addWidget(form_row("유지", self.hold, 64))
        self.ghost = QSpinBox()
        self.ghost.setRange(0, 20)
        self.ghost.setSuffix(" 프레임")
        self.ghost.setToolTip("앞뒤 프레임의 주석을 흐리게 표시 (어니언 스킨)")
        self.ghost.valueChanged.connect(self._style)
        card.lay.addWidget(form_row("고스트", self.ghost, 64))
        self.visible = QCheckBox("주석 보이기")
        self.visible.setChecked(True)
        self.visible.toggled.connect(self.visibilityToggled)
        card.lay.addWidget(self.visible)
        lay.addWidget(card)

        head = QHBoxLayout()
        self.note_title = SectionTitle("프레임 노트")
        head.addWidget(self.note_title)
        head.addStretch(1)
        lay.addLayout(head)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("이 프레임에 대한 메모를 적으세요 (PDF에 함께 나갑니다)")
        self.note.setFixedHeight(76)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.setInterval(400)
        self._note_timer.timeout.connect(lambda: self.noteEdited.emit(self.note.toPlainText()))
        self.note.textChanged.connect(self._note_changed)
        lay.addWidget(self.note)

        lay.addWidget(SectionTitle("주석이 있는 프레임"))
        self.frames = QListWidget()
        self.frames.setMinimumHeight(120)
        self.frames.itemClicked.connect(lambda it: self.jumpRequested.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.frames, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        for text, sig, variant in (("실행 취소", self.undo, ""), ("다시 실행", self.redo, ""),
                                   ("프레임 지우기", self.clearFrame, "")):
            b = QPushButton(text)
            if variant:
                b.setProperty("variant", variant)
            b.clicked.connect(sig)
            row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(6)
        b_all = QPushButton("모두 지우기")
        b_all.setProperty("variant", "danger")
        b_all.clicked.connect(self.clearAll)
        row.addWidget(b_all)
        b_pdf = QPushButton("PDF로 내보내기")
        b_pdf.setProperty("variant", "primary")
        b_pdf.clicked.connect(self.exportPdf)
        row.addWidget(b_pdf, 1)
        lay.addLayout(row)

    def _note_changed(self) -> None:
        if not self._updating:
            self._note_timer.start()

    def _style(self, *_):
        if not self._updating:
            self.styleChanged.emit()

    def set_tool(self, tool: str) -> None:
        b = self.tool_buttons.get(tool)
        if b is not None:
            b.setChecked(True)

    def set_style(self, color: str, size: float, fill: bool, hold: int, ghost: int) -> None:
        self._updating = True
        self.swatches.set_color(color)
        self.size.setValue(size)
        self.fill.setChecked(fill)
        self.hold.setValue(hold)
        self.ghost.setValue(ghost)
        self._updating = False

    def style(self) -> tuple:
        return self.swatches.color(), self.size.value(), self.fill.isChecked(), self.hold.value(), self.ghost.value()

    def set_frames(self, store, current: int) -> None:
        self.frames.clear()
        if store is None:
            return
        for f in store.annotated_frames():
            n = len(store.frames.get(f, []))
            note = store.notes.get(f, "")
            text = f"{f}   ·   도형 {n}개" + (f"   ·   {note[:24]}" if note else "")
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, f)
            if f == current:
                it.setSelected(True)
            self.frames.addItem(it)

    def set_note(self, frame: int, text: str) -> None:
        if self.note.hasFocus() and self._note_timer.isActive():
            return
        self._updating = True
        self.note_title.setText(f"프레임 노트 · {frame}")
        if self.note.toPlainText() != text:
            self.note.setPlainText(text)
        self._updating = False
