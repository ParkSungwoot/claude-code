"""Transport bar under the timeline: frame field, play controls, in/out, loop, fps and volume."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QSlider, QToolButton, QWidget

from cocseq.theme import PAL, mono_font
from cocseq.ui.widgets import IconButton, vline
from cocseq.utils import format_frame, fps_label, timecode_to_frames

FPS_PRESETS = [8, 12, 15, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 120]
LOOP_ICONS = {"loop": ("loop", "반복"), "once": ("loop-once", "한 번 재생"), "pingpong": ("pingpong", "왕복")}
TIME_MODES = [("frames", "프레임"), ("timecode", "타임코드"), ("seconds", "초")]


class FrameField(QLineEdit):
    submitted = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "frame")
        self.setFixedWidth(110)
        self.setAlignment(Qt.AlignCenter)
        self.setToolTip("현재 프레임 — 숫자나 타임코드를 입력하고 Enter")
        self.mode = "frames"
        self.fps = 24.0
        self.first = 1
        self.returnPressed.connect(self._submit)

    def show_frame(self, f: int) -> None:
        if not self.hasFocus():
            self.setText(format_frame(f, self.mode, self.fps, self.first))

    def _submit(self) -> None:
        t = self.text().strip()
        f = None
        if ":" in t:
            n = timecode_to_frames(t, self.fps)
            f = None if n is None else n + self.first
        else:
            try:
                if t.endswith("s") and self.mode == "seconds":
                    f = int(round(float(t[:-1]) * self.fps)) + self.first
                else:
                    f = int(float(t))
            except ValueError:
                f = None
        if f is not None:
            self.submitted.emit(f)
        self.clearFocus()


class Transport(QWidget):
    playForward = Signal()
    playBackward = Signal()
    stop = Signal()
    stepRequested = Signal(int)
    gotoStart = Signal()
    gotoEnd = Signal()
    frameEntered = Signal(int)
    setIn = Signal()
    setOut = Signal()
    clearIn = Signal()
    clearOut = Signal()
    loopClicked = Signal()
    fpsChosen = Signal(float)
    timeModeChosen = Signal(str)
    volumeChanged = Signal(float)
    muteToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Transport")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(50)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 8)
        lay.setSpacing(6)

        # Left: current frame and range
        self.frame_field = FrameField()
        self.frame_field.submitted.connect(self.frameEntered)
        lay.addWidget(self.frame_field)
        self.range_label = QLabel("")
        self.range_label.setProperty("class", "mono")
        self.range_label.setMinimumWidth(120)
        lay.addWidget(self.range_label)
        lay.addStretch(1)

        # Center: transport buttons
        def tb(icon, tip, sig, size=17):
            b = IconButton(icon, tip, size=size, role="transport")
            b.clicked.connect(sig)
            lay.addWidget(b)
            return b

        self.b_start = tb("skip-start", "처음으로 (Home)", self.gotoStart.emit)
        self.b_prev = tb("step-back", "이전 프레임 (←)", lambda: self.stepRequested.emit(-1))
        self.b_back = tb("play-reverse", "거꾸로 재생 (↓)", self.playBackward.emit)
        self.b_play = QToolButton()
        self.b_play.setProperty("role", "play")
        self.b_play.setCursor(Qt.PointingHandCursor)
        self.b_play.setIconSize(QSize(18, 18))
        self.b_play.setFixedSize(36, 36)
        self.b_play.clicked.connect(self._play_clicked)
        lay.addWidget(self.b_play)
        self.b_next = tb("step-forward", "다음 프레임 (→)", lambda: self.stepRequested.emit(1))
        self.b_end = tb("skip-end", "끝으로 (End)", self.gotoEnd.emit)
        self._playing = 0
        self._update_play_icon()

        lay.addStretch(1)

        # Right: in/out, loop, fps, time mode, volume
        self.b_in = self._range_button("in-point", "In", "시작점 지정 (I) · 우클릭: 지우기", self.setIn, self.clearIn)
        lay.addWidget(self.b_in)
        self.b_out = self._range_button("out-point", "Out", "끝점 지정 (O) · 우클릭: 지우기", self.setOut,
                                        self.clearOut)
        lay.addWidget(self.b_out)
        lay.addWidget(vline())

        self.b_loop = IconButton("loop", "반복 방식 (Ctrl+L)", size=17, role="transport")
        self.b_loop.clicked.connect(self.loopClicked)
        lay.addWidget(self.b_loop)

        self.fps_combo = QComboBox()
        self.fps_combo.setEditable(True)
        self.fps_combo.setProperty("role", "toolbar")
        self.fps_combo.setFixedWidth(84)
        self.fps_combo.setToolTip("재생 FPS")
        for f in FPS_PRESETS:
            self.fps_combo.addItem(fps_label(f), f)
        self.fps_combo.lineEdit().setAlignment(Qt.AlignRight)
        self.fps_combo.lineEdit().setFont(mono_font(9))
        self.fps_combo.activated.connect(self._fps_activated)
        self.fps_combo.lineEdit().editingFinished.connect(self._fps_edited)
        lay.addWidget(self.fps_combo)
        fps_unit = QLabel("fps")
        fps_unit.setProperty("class", "faint")
        lay.addWidget(fps_unit)
        self.actual = QLabel("")
        self.actual.setProperty("class", "mono")
        self.actual.setFixedWidth(62)
        self.actual.setToolTip("실제 재생 속도")
        lay.addWidget(self.actual)

        self.b_time = QToolButton()
        self.b_time.setProperty("role", "text")
        self.b_time.setPopupMode(QToolButton.InstantPopup)
        self.b_time.setToolTip("시간 표시 방식")
        menu = QMenu(self.b_time)
        for key, label in TIME_MODES:
            a = menu.addAction(label)
            a.triggered.connect(lambda _=False, k=key: self.timeModeChosen.emit(k))
        self.b_time.setMenu(menu)
        lay.addWidget(self.b_time)
        lay.addWidget(vline())

        self.b_mute = IconButton("volume", "소리 (Ctrl+M)", size=17, role="transport", checkable=True)
        self.b_mute.toggled.connect(self._mute_toggled)
        lay.addWidget(self.b_mute)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(84)
        self.volume.setToolTip("음량")
        self.volume.valueChanged.connect(lambda v: self.volumeChanged.emit(v / 100.0))
        lay.addWidget(self.volume)
        self.set_time_mode("frames")

    def _range_button(self, icon: str, text: str, tip: str, set_sig, clear_sig) -> QToolButton:
        b = QToolButton()
        b.setProperty("role", "text")
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        from cocseq import icons

        b.setIcon(icons.icon(icon, size=15))
        b.setIconSize(QSize(15, 15))
        b.setText(text)
        b.setFont(mono_font(8.5))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        b.clicked.connect(set_sig)
        b.customContextMenuRequested.connect(lambda _p: clear_sig.emit())
        b.setMinimumWidth(78)
        return b

    # ---------------------------------------------------------------- state

    def _play_clicked(self) -> None:
        if self._playing:
            self.stop.emit()
        else:
            self.playForward.emit()

    def _update_play_icon(self) -> None:
        from cocseq import icons

        name = "pause" if self._playing else "play"
        self.b_play.setIcon(icons.icon(name, color="#FFFFFF", size=18))
        self.b_play.setToolTip("정지 (Space)" if self._playing else "재생 (Space)")
        self.b_back.setChecked(False)

    def set_playing(self, direction: int) -> None:
        self._playing = direction
        self._update_play_icon()

    def set_frame(self, f: int) -> None:
        self.frame_field.show_frame(f)

    def set_clip_info(self, first: int, last: int, fps: float, lo: int | None, hi: int | None) -> None:
        mode = self.frame_field.mode
        self.frame_field.fps = fps
        self.frame_field.first = first
        n = last - first + 1
        a = format_frame(first, mode, fps, first)
        b = format_frame(last, mode, fps, first)
        self.range_label.setText(f"{a} – {b}  ·  {n}f")
        self.b_in.setText(f"In {format_frame(lo, mode, fps, first)}" if lo is not None else "In")
        self.b_out.setText(f"Out {format_frame(hi, mode, fps, first)}" if hi is not None else "Out")
        for b, active in ((self.b_in, lo is not None), (self.b_out, hi is not None)):
            b.setStyleSheet(f"QToolButton {{ color: {PAL.accent}; border-color: {PAL.rgba(PAL.accent, 0.45)}; }}"
                            if active else "")
        self.set_fps(fps)

    def set_fps(self, fps: float) -> None:
        self.fps_combo.blockSignals(True)
        self.fps_combo.setEditText(fps_label(fps))
        self.fps_combo.blockSignals(False)

    def set_actual_fps(self, fps: float) -> None:
        self.actual.setText(f"{fps:5.1f}" if fps > 0 else "")
        try:
            target = float(self.fps_combo.currentText())
        except ValueError:
            target = 0
        slow = fps > 0 and target > 0 and fps < target * 0.93
        self.actual.setStyleSheet(f"color: {PAL.warn};" if slow else "")

    def set_loop_mode(self, mode: str) -> None:
        icon, tip = LOOP_ICONS.get(mode, LOOP_ICONS["loop"])
        self.b_loop.set_icon_name(icon)
        self.b_loop.setToolTip(f"반복 방식: {tip} (Ctrl+L)")

    def set_time_mode(self, mode: str) -> None:
        self.frame_field.mode = mode
        self.b_time.setText({"frames": "F", "timecode": "TC", "seconds": "S"}.get(mode, "F"))
        self.b_time.setFont(mono_font(8.5, QFont.DemiBold))

    def set_volume(self, v: float, muted: bool) -> None:
        self.volume.blockSignals(True)
        self.volume.setValue(int(round(v * 100)))
        self.volume.blockSignals(False)
        self.b_mute.blockSignals(True)
        self.b_mute.setChecked(muted)
        self.b_mute.blockSignals(False)
        self.b_mute.set_icon_name("volume-mute" if muted else "volume")

    def _mute_toggled(self, on: bool) -> None:
        self.b_mute.set_icon_name("volume-mute" if on else "volume")
        self.muteToggled.emit(on)

    def _fps_activated(self, index: int) -> None:
        v = self.fps_combo.itemData(index)
        if v:
            self.fpsChosen.emit(float(v))

    def _fps_edited(self) -> None:
        try:
            v = float(self.fps_combo.currentText().replace(",", "."))
        except ValueError:
            return
        if v > 0:
            self.fpsChosen.emit(v)
