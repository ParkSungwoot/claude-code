"""Environment map (360° lat-long panorama) viewing panel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QPushButton, QVBoxLayout, QWidget

from cocseq.ui.widgets import Card, ScrubField, SectionTitle, muted


class EnvPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._viewer = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 12)
        lay.setSpacing(10)
        lay.addWidget(SectionTitle("360° 파노라마"))
        card = Card()
        self.enabled = QCheckBox("환경 맵으로 보기 (구면 · Lat-Long)")
        self.enabled.toggled.connect(self._edited)
        card.lay.addWidget(self.enabled)
        self.yaw = ScrubField("좌우 회전", 0.0, -3600, 3600, 0.5, 1, 0.0, suffix="°", width=150)
        self.pitch = ScrubField("상하 회전", 0.0, -89, 89, 0.5, 1, 0.0, suffix="°", width=150)
        self.fov = ScrubField("시야각", 90.0, 10, 160, 0.5, 1, 90.0, suffix="°", width=150)
        for w in (self.yaw, self.pitch, self.fov):
            w.valueChanged.connect(self._edited)
            card.lay.addWidget(w)
        b = QPushButton("시점 초기화")
        b.clicked.connect(self._reset)
        card.lay.addWidget(b)
        lay.addWidget(card)
        lay.addWidget(muted("화면을 드래그해서 둘러보고, 휠로 시야각을 바꿉니다.\n"
                            "가로:세로 2:1 구면(equirectangular) 이미지용입니다.", "faint"))
        lay.addStretch(1)

    def bind(self, viewer) -> None:
        self._viewer = viewer
        self.sync()

    def sync(self) -> None:
        v = self._viewer
        if v is None:
            return
        self._updating = True
        self.enabled.setChecked(v.env_mode)
        self.yaw.setValue(v.env_yaw)
        self.pitch.setValue(v.env_pitch)
        self.fov.setValue(v.env_fov)
        self._updating = False

    def _edited(self, *_):
        if self._updating or self._viewer is None:
            return
        v = self._viewer
        v.env_mode = self.enabled.isChecked()
        v.env_yaw = self.yaw.value()
        v.env_pitch = self.pitch.value()
        v.env_fov = self.fov.value()
        v.update()
        self.changed.emit()

    def _reset(self) -> None:
        if self._viewer is None:
            return
        self._viewer.env_yaw = 0.0
        self._viewer.env_pitch = 0.0
        self._viewer.env_fov = 90.0
        self._viewer.update()
        self.sync()
        self.changed.emit()
