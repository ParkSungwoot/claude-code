"""Color management panel: OCIO input/display/view/look, LUT, exposure/gamma and alpha."""

from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from cocseq.ui.widgets import Card, IconButton, ScrubField, SectionTitle, Segmented, muted, stack_row


def fill_colorspace_combo(combo: QComboBox, colors, current: str) -> None:
    """Colour spaces grouped by family, with the family as a disabled header row."""
    combo.blockSignals(True)
    combo.clear()
    last_family = None
    model = combo.model()
    for family, name in colors.colorspaces():
        fam = family.split("/")[0] if family else "기타"
        if fam != last_family:
            combo.addItem(f"— {fam} —")
            item = model.item(combo.count() - 1)
            item.setEnabled(False)
            last_family = fam
        combo.addItem(name, name)
    i = combo.findData(current)
    if i < 0 and current:
        combo.addItem(f"{current} (없음)", current)
        i = combo.count() - 1
    combo.setCurrentIndex(max(0, i))
    combo.blockSignals(False)


class ColorPanel(QWidget):
    changed = Signal()                  # DisplaySettings edited
    colorspaceChosen = Signal(str)      # input colour space of the current clip
    configRequested = Signal()          # open preferences on the colour page

    def __init__(self, display, colors, parent=None):
        super().__init__(parent)
        self.display = display
        self.colors = colors
        self._updating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 8, 10, 12)
        lay.setSpacing(10)

        # --- OCIO
        lay.addWidget(SectionTitle("컬러 관리 (OCIO)"))
        card = Card()
        self.config_label = muted("")
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(self.config_label, 1)
        b_cfg = QPushButton("설정 변경")
        b_cfg.setProperty("variant", "ghost")
        b_cfg.clicked.connect(self.configRequested)
        cfg_row.addWidget(b_cfg)
        card.lay.addLayout(cfg_row)
        self.cs_combo = QComboBox()
        self.cs_combo.setMaxVisibleItems(24)
        self.cs_combo.activated.connect(self._cs_chosen)
        card.lay.addWidget(stack_row("입력 색공간 (현재 클립)", self.cs_combo))
        self.display_combo = QComboBox()
        self.display_combo.activated.connect(self._display_chosen)
        card.lay.addWidget(stack_row("디스플레이", self.display_combo))
        self.view_combo = QComboBox()
        self.view_combo.activated.connect(self._view_chosen)
        card.lay.addWidget(stack_row("뷰", self.view_combo))
        self.look_combo = QComboBox()
        self.look_combo.activated.connect(self._look_chosen)
        card.lay.addWidget(stack_row("룩 (Look)", self.look_combo))
        lut_row = QHBoxLayout()
        self.lut_label = muted("LUT 없음", "faint")
        lut_row.addWidget(self.lut_label, 1)
        b_lut = QPushButton("LUT…")
        b_lut.setToolTip(".cube · .3dl · .csp · .spi3d 등")
        b_lut.clicked.connect(self._pick_lut)
        lut_row.addWidget(b_lut)
        self.b_lut_clear = IconButton("close", "LUT 해제", size=15)
        self.b_lut_clear.clicked.connect(self._clear_lut)
        lut_row.addWidget(self.b_lut_clear)
        card.lay.addLayout(lut_row)
        self.lut_mode = Segmented([("after", "OCIO 뒤에", "디스플레이 변환 결과에 LUT 적용"),
                                   ("replace", "OCIO 대신", "원본에 LUT만 적용")])
        self.lut_mode.changed.connect(self._lut_mode)
        card.lay.addWidget(stack_row("LUT 적용 순서", self.lut_mode))
        lay.addWidget(card)

        # --- Exposure
        head = QHBoxLayout()
        head.addWidget(SectionTitle("노출 · 감마"))
        head.addStretch(1)
        b_reset = QPushButton("초기화")
        b_reset.setProperty("variant", "ghost")
        b_reset.clicked.connect(self._reset)
        head.addWidget(b_reset)
        lay.addLayout(head)
        card = Card()
        self.exposure = ScrubField("노출", 0.0, -12, 12, 0.02, 2, 0.0, icon="sun", suffix=" st", width=150)
        self.gamma = ScrubField("감마", 1.0, 0.1, 4.0, 0.005, 2, 1.0, icon="gamma", width=150)
        for w in (self.exposure, self.gamma):
            card.lay.addWidget(w)
        lay.addWidget(card)

        # --- Alpha & video levels
        lay.addWidget(SectionTitle("알파 · 비디오 레벨"))
        card = Card()
        self.alpha = Segmented([("none", "무시"), ("straight", "Straight"), ("premult", "Premult")])
        self.alpha.changed.connect(self._edited)
        card.lay.addWidget(stack_row("알파 합성", self.alpha))
        self.unpremult = QCheckBox("색 변환 전에 언프리멀티플라이")
        self.unpremult.toggled.connect(self._edited)
        card.lay.addWidget(self.unpremult)
        self.video = Segmented([("auto", "파일대로"), ("legal", "Legal → Full")])
        self.video.changed.connect(self._edited)
        card.lay.addWidget(stack_row("비디오 레벨", self.video))
        lay.addWidget(card)
        lay.addStretch(1)

        for w in (self.exposure, self.gamma):
            w.valueChanged.connect(self._edited)

    # ---------------------------------------------------------------- sync

    def refresh(self, source=None) -> None:
        """Reload menus and values from the colour manager and DisplaySettings."""
        self._updating = True
        d = self.display
        cm = self.colors
        self.config_label.setText(f"설정: {cm.config_label()}" + ("" if cm.available else "  (OCIO 없음)"))
        if source is not None:
            fill_colorspace_combo(self.cs_combo, cm, source.colorspace)
            self.cs_combo.setEnabled(True)
        else:
            self.cs_combo.clear()
            self.cs_combo.setEnabled(False)
        self.display_combo.clear()
        self.display_combo.addItems(cm.displays())
        self.display_combo.setCurrentText(d.display)
        self.view_combo.clear()
        self.view_combo.addItems(cm.views(d.display))
        self.view_combo.setCurrentText(d.view)
        self.look_combo.clear()
        self.look_combo.addItem("없음", "")
        for look in cm.looks():
            self.look_combo.addItem(look, look)
        i = self.look_combo.findData(d.look)
        self.look_combo.setCurrentIndex(max(0, i))
        self.lut_label.setText(os.path.basename(d.lut) if d.lut else "LUT 없음")
        self.lut_label.setToolTip(d.lut)
        self.b_lut_clear.setVisible(bool(d.lut))
        self.lut_mode.set_value(d.lut_mode)
        self.lut_mode.setEnabled(bool(d.lut))
        self.exposure.setValue(d.exposure)
        self.gamma.setValue(d.gamma)
        self.alpha.set_value(d.alpha_mode)
        self.unpremult.setChecked(d.unpremult)
        self.video.set_value(d.video_levels)
        self._updating = False

    def refresh_values(self) -> None:
        """Only the numbers (after hotkeys changed exposure/gamma)."""
        self._updating = True
        self.exposure.setValue(self.display.exposure)
        self.gamma.setValue(self.display.gamma)
        self._updating = False

    def _edited(self, *_):
        if self._updating:
            return
        d = self.display
        d.exposure = self.exposure.value()
        d.gamma = self.gamma.value()
        d.alpha_mode = self.alpha.value()
        d.unpremult = self.unpremult.isChecked()
        d.video_levels = self.video.value()
        self.changed.emit()

    def _reset(self) -> None:
        self.display.reset_grade()
        self.refresh_values()
        self.changed.emit()

    def _cs_chosen(self, index: int) -> None:
        name = self.cs_combo.itemData(index)
        if name:
            self.colorspaceChosen.emit(name)

    def _display_chosen(self, index: int) -> None:
        d = self.display
        d.display = self.display_combo.itemText(index)
        views = self.colors.views(d.display)
        if d.view not in views:
            d.view = self.colors.default_view(d.display) if views else ""
        self.view_combo.clear()
        self.view_combo.addItems(views)
        self.view_combo.setCurrentText(d.view)
        self.changed.emit()

    def _view_chosen(self, index: int) -> None:
        self.display.view = self.view_combo.itemText(index)
        self.changed.emit()

    def _look_chosen(self, index: int) -> None:
        self.display.look = self.look_combo.itemData(index) or ""
        self.changed.emit()

    def _pick_lut(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "LUT 파일 선택", os.path.dirname(self.display.lut) if self.display.lut else "",
            "LUT (*.cube *.3dl *.csp *.spi1d *.spi3d *.spimtx *.cc *.ccc *.cdl *.clf *.ctf *.lut *.mga *.m3d *.icc *.icm);;모든 파일 (*)")
        if path:
            self.display.lut = path
            self.refresh_lut()
            self.changed.emit()

    def _clear_lut(self) -> None:
        self.display.lut = ""
        self.refresh_lut()
        self.changed.emit()

    def refresh_lut(self) -> None:
        d = self.display
        self.lut_label.setText(os.path.basename(d.lut) if d.lut else "LUT 없음")
        self.lut_label.setToolTip(d.lut)
        self.b_lut_clear.setVisible(bool(d.lut))
        self.lut_mode.setEnabled(bool(d.lut))

    def _lut_mode(self, mode: str) -> None:
        self.display.lut_mode = mode
        self.changed.emit()
