"""Compare panel: choose B (and C/D for tiles), mode and mode options."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from cocseq.theme import PAL
from cocseq.ui.widgets import Card, IconButton, ScrubField, SectionTitle, Segmented, form_row, muted

MODES = [
    ("A", "A", "a-letter", "A만 보기"),
    ("B", "B", "b-letter", "B만 보기"),
    ("wipe", "와이프", "wipe", "와이프 — 드래그로 위치, Shift+드래그로 각도"),
    ("overlay", "오버레이", "overlay", "B를 반투명하게 겹쳐 보기"),
    ("difference", "차이", "difference", "A와 B의 차이"),
    ("horizontal", "좌우", "side-by-side", "좌우로 나란히"),
    ("vertical", "위아래", "top-bottom", "위아래로 나란히"),
    ("tile", "타일", "tile", "최대 4개 클립을 격자로"),
]


class ComparePanel(QWidget):
    modeChosen = Signal(str)
    bChosen = Signal(object)            # source or None
    extraChosen = Signal(int, object)   # slot index 2/3, source or None
    swapRequested = Signal()
    optionsChanged = Signal()           # wipe/overlay/difference numbers edited
    alignChanged = Signal(str)
    offsetChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: list = []
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 12)
        lay.setSpacing(10)

        lay.addWidget(SectionTitle("클립"))
        card = Card()
        self.a_label = QLabel("—")
        self.a_label.setStyleSheet("font-weight: 600;")
        card.lay.addWidget(form_row(self._chip("A", PAL.accent), self.a_label, 26))
        self.b_combo = QComboBox()
        self.b_combo.activated.connect(lambda i: self._pick(1, i))
        brow = QHBoxLayout()
        brow.addWidget(self.b_combo, 1)
        b_swap = IconButton("pingpong", "A와 B 바꾸기 (Ctrl+Shift+B)", size=16)
        b_swap.clicked.connect(self.swapRequested)
        brow.addWidget(b_swap)
        wb = QWidget()
        wb.setLayout(brow)
        brow.setContentsMargins(0, 0, 0, 0)
        card.lay.addWidget(form_row(self._chip("B", PAL.b), wb, 26))
        self.c_combo = QComboBox()
        self.c_combo.activated.connect(lambda i: self._pick(2, i))
        self.d_combo = QComboBox()
        self.d_combo.activated.connect(lambda i: self._pick(3, i))
        self.c_row = form_row(self._chip("C", "#B38CFF"), self.c_combo, 26)
        self.d_row = form_row(self._chip("D", "#3DD68C"), self.d_combo, 26)
        card.lay.addWidget(self.c_row)
        card.lay.addWidget(self.d_row)
        lay.addWidget(card)

        lay.addWidget(SectionTitle("비교 방식"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.mode_buttons: dict[str, QToolButton] = {}
        from PySide6.QtCore import QSize

        from cocseq import icons

        for i, (key, text, icon_name, tip) in enumerate(MODES):
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(icons.icon(icon_name, size=20))
            b.setIconSize(QSize(20, 20))
            b.setText(text)
            b.setToolTip(tip)
            b.setMinimumSize(50, 54)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QToolButton {{ background: {PAL.bg3}; border: 1px solid {PAL.line}; border-radius: 9px;"
                            f" font-size: 11px; color: {PAL.text2}; }}"
                            f"QToolButton:hover {{ background: {PAL.bg4}; }}"
                            f"QToolButton:checked {{ background: {PAL.rgba(PAL.accent, 0.16)};"
                            f" border-color: {PAL.rgba(PAL.accent, 0.55)}; color: {PAL.accent}; }}")
            b.clicked.connect(lambda _=False, k=key: self.modeChosen.emit(k))
            grid.addWidget(b, i // 4, i % 4)
            self.mode_buttons[key] = b
        lay.addLayout(grid)

        lay.addWidget(SectionTitle("옵션"))
        card = Card()
        self.wipe_x = ScrubField("와이프 가로", 50.0, 0, 100, 0.2, 1, 50.0, suffix="%", bar=True, width=150)
        self.wipe_y = ScrubField("와이프 세로", 50.0, 0, 100, 0.2, 1, 50.0, suffix="%", bar=True, width=150)
        self.wipe_angle = ScrubField("와이프 각도", 0.0, -180, 180, 0.5, 1, 0.0, suffix="°", width=150)
        self.overlay = ScrubField("오버레이 불투명도", 50.0, 0, 100, 0.5, 0, 50.0, suffix="%", bar=True, width=150)
        self.diff_gain = ScrubField("차이 증폭", 1.0, 1, 100, 0.05, 1, 1.0, suffix="×", width=150)
        for w in (self.wipe_x, self.wipe_y, self.wipe_angle, self.overlay, self.diff_gain):
            w.valueChanged.connect(self._opt)
            card.lay.addWidget(w)
        lay.addWidget(card)

        lay.addWidget(SectionTitle("프레임 맞춤"))
        card = Card()
        self.align = Segmented([("relative", "시작 프레임 기준"), ("absolute", "같은 프레임 번호")])
        self.align.changed.connect(self.alignChanged)
        card.lay.addWidget(self.align)
        self.offset = ScrubField("B 프레임 오프셋", 0, -100000, 100000, 0.25, 0, 0, suffix=" f", width=150)
        self.offset.valueChanged.connect(lambda v: self.offsetChanged.emit(int(v)))
        card.lay.addWidget(self.offset)
        card.lay.addWidget(muted("B 클립이 더 짧으면 마지막 프레임을 유지합니다.", "faint"))
        lay.addWidget(card)
        lay.addStretch(1)

    def _chip(self, text: str, color: str) -> str:
        return text

    # ---------------------------------------------------------------- sync

    def set_state(self, sources: list, a, slots: list, mode: str, viewer, align: str, offset: int) -> None:
        """slots: [B, C, D] sources or None."""
        self._updating = True
        self._sources = list(sources)
        self.a_label.setText(a.name if a is not None else "—")
        for combo, current in ((self.b_combo, slots[0]), (self.c_combo, slots[1]), (self.d_combo, slots[2])):
            combo.clear()
            combo.addItem("없음", None)
            for s in sources:
                if s is a:
                    continue
                combo.addItem(s.name, s.id)
            idx = combo.findData(current.id) if current is not None else 0
            combo.setCurrentIndex(max(0, idx))
        tile = mode == "tile"
        self.c_row.setVisible(tile)
        self.d_row.setVisible(tile)
        for k, b in self.mode_buttons.items():
            b.setChecked(k == mode)
        self.wipe_x.setValue(viewer.wipe_pos.x() * 100)
        self.wipe_y.setValue(viewer.wipe_pos.y() * 100)
        self.wipe_angle.setValue(viewer.wipe_angle)
        self.overlay.setValue(viewer.overlay_opacity * 100)
        self.diff_gain.setValue(viewer.diff_gain)
        for w, show in ((self.wipe_x, mode == "wipe"), (self.wipe_y, mode == "wipe"), (self.wipe_angle, mode == "wipe"),
                        (self.overlay, mode == "overlay"), (self.diff_gain, mode == "difference")):
            w.setEnabled(show)
        self.align.set_value(align)
        self.offset.setValue(offset)
        self._viewer = viewer
        self._updating = False

    def sync_wipe(self, viewer) -> None:
        self._updating = True
        self.wipe_x.setValue(viewer.wipe_pos.x() * 100)
        self.wipe_y.setValue(viewer.wipe_pos.y() * 100)
        self.wipe_angle.setValue(viewer.wipe_angle)
        self._updating = False

    def _pick(self, slot: int, index: int) -> None:
        combo = {1: self.b_combo, 2: self.c_combo, 3: self.d_combo}[slot]
        sid = combo.itemData(index)
        src = next((s for s in self._sources if s.id == sid), None)
        if slot == 1:
            self.bChosen.emit(src)
        else:
            self.extraChosen.emit(slot, src)

    def _opt(self, *_):
        if self._updating or not hasattr(self, "_viewer"):
            return
        from PySide6.QtCore import QPointF

        v = self._viewer
        v.wipe_pos = QPointF(self.wipe_x.value() / 100, self.wipe_y.value() / 100)
        v.wipe_angle = self.wipe_angle.value()
        v.overlay_opacity = self.overlay.value() / 100
        v.diff_gain = self.diff_gain.value()
        v.update()
        self.optionsChanged.emit()
