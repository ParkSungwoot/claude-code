"""The export dialog: format tiles, range, output path, size, quality and options."""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from cocseq import export as E
from cocseq.theme import PAL, mono_font, ui_font
from cocseq.ui.widgets import Card, ScrubField, SectionTitle, Segmented, hline, muted
from cocseq.utils import fps_label, frames_to_timecode

# key -> (title, detail) for the tiles
_TILES = {
    "png": ("PNG", "8비트"),
    "png16": ("PNG", "16비트"),
    "jpg": ("JPEG", "8비트 · 손실"),
    "tif8": ("TIFF", "8비트"),
    "tif16": ("TIFF", "16비트"),
    "exr": ("OpenEXR", "half"),
    "dpx10": ("DPX", "10비트"),
    "mp4_h264": ("H.264", "MP4"),
    "mp4_h265": ("H.265 · HEVC", "MP4"),
    "mov_prores422hq": ("ProRes 422 HQ", "MOV"),
    "mov_prores4444": ("ProRes 4444", "MOV · 알파"),
    "mov_mjpeg": ("Motion JPEG", "MOV"),
}

_CODECS = {"mp4_h264": "libx264", "mp4_h265": "libx265", "mov_prores422hq": "prores_ks",
           "mov_prores4444": "prores_ks", "mov_mjpeg": "mjpeg"}

_FPS_PRESETS = ["23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60"]

# Remembered for the session so the next export starts where the last one ended.
_LAST: dict = {}


def _icon_pixmap(name: str, size: int, color: str):
    try:
        from cocseq import icons

        return icons.pixmap(name, size, color)
    except Exception:
        return None


def _icon(name: str, size: int = 16, color: str | None = None):
    try:
        from cocseq import icons

        return icons.icon(name, color=color, size=size)
    except Exception:
        from PySide6.QtGui import QIcon

        return QIcon()


def _available_codecs() -> set[str]:
    try:
        import av

        return set(av.codecs_available)
    except Exception:
        return set()


class FormatTile(QAbstractButton):
    """One selectable format in the list: icon, name and a faint detail on the right."""

    def __init__(self, key: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.icon_name = icon_name
        self.title, self.detail = _TILES[key]
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(E.FORMATS[key].label)
        self.setAttribute(Qt.WA_Hover, True)

    def sizeHint(self) -> QSize:
        return QSize(200, 34)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        sel = self.isChecked()
        hover = self.underMouse() and self.isEnabled()
        if sel:
            p.setPen(QPen(PAL.qcolor("accent", 0.55), 1))
            p.setBrush(PAL.qcolor("accent", 0.13))
        elif hover:
            p.setPen(Qt.NoPen)
            p.setBrush(PAL.qcolor("bg4"))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        enabled = self.isEnabled()
        icol = PAL.accent if sel else (PAL.text2 if enabled else PAL.text3)
        pm = _icon_pixmap(self.icon_name, 16, icol)
        x = r.left() + 10
        if pm is not None:
            p.drawPixmap(int(x), int(r.center().y() - 8), pm)
        x += 26
        p.setFont(ui_font(9.5, QFont.DemiBold if sel else QFont.Medium))
        p.setPen(PAL.qcolor("text") if enabled else PAL.qcolor("text3"))
        tr = QRectF(x, r.top(), r.width() - x - 8, r.height())
        p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft, self.title)
        p.setFont(ui_font(8.0, QFont.Medium))
        p.setPen(PAL.qcolor("accent", 0.9) if sel else PAL.qcolor("text3"))
        p.drawText(QRectF(x, r.top(), r.right() - x - 10, r.height()), Qt.AlignVCenter | Qt.AlignRight, self.detail)


class _Header(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 14)
        lay.setSpacing(12)
        badge = QLabel()
        badge.setFixedSize(38, 38)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background: {PAL.rgba(PAL.accent, 0.15)}; border-radius: 11px;")
        pm = _icon_pixmap("export", 20, PAL.accent)
        if pm is not None:
            badge.setPixmap(pm)
        lay.addWidget(badge)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {PAL.text};")
        col.addWidget(t)
        s = QLabel(subtitle)
        s.setProperty("class", "muted")
        col.addWidget(s)
        self.subtitle = s
        lay.addLayout(col, 1)


def _row(label: str, *widgets, stretch_last: bool = False, label_width: int = 56) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    l = QLabel(label)
    l.setProperty("class", "muted")
    l.setFixedWidth(label_width)
    lay.addWidget(l)
    for i, x in enumerate(widgets):
        if x is None:
            lay.addStretch(1)
        elif isinstance(x, int):
            lay.addSpacing(x)
        else:
            lay.addWidget(x, 1 if (stretch_last and i == len(widgets) - 1) else 0)
    return w


class ExportDialog(QDialog):
    """ExportDialog(source, viewer, current_frame).exec(); then settings() -> ExportSettings."""

    formatChanged = Signal(str)

    def __init__(self, source, viewer, current_frame: int, parent=None):
        super().__init__(parent)
        self.source = source
        self.viewer = viewer
        self.current_frame = int(current_frame)
        self.setWindowTitle("내보내기")
        self.setModal(True)
        self.setMinimumSize(640, 600)
        self.resize(664, 640)
        self._ready = False
        self._fmt = "png"
        self._auto_path = ""
        self._start_touched = False
        self._alpha_touched = False
        self._codecs = _available_codecs()
        self._disp, self._par = E._source_windows(source)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        w, h = source.resolution
        sub = f"{source.name}  ·  {w} × {h}  ·  {fps_label(source.fps)} fps  ·  {source.first}–{source.last}"
        root.addWidget(_Header("내보내기", sub))
        root.addWidget(hline())

        body = QHBoxLayout()
        body.setContentsMargins(16, 14, 20, 12)
        body.setSpacing(16)
        root.addLayout(body, 1)

        body.addWidget(self._build_formats())
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_range())
        right.addWidget(self._build_output())
        right.addWidget(self._build_options())
        right.addStretch(1)
        body.addLayout(right, 1)

        root.addWidget(hline())
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 12, 20, 14)
        foot.setSpacing(8)
        self.summary = QLabel()
        self.summary.setProperty("class", "muted")
        foot.addWidget(self.summary, 1)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        self.export_btn = QPushButton("내보내기")
        self.export_btn.setProperty("variant", "primary")
        self.export_btn.setIcon(_icon("export", 16, "#FFFFFF"))
        self.export_btn.setDefault(True)
        self.export_btn.setMinimumWidth(116)
        self.export_btn.clicked.connect(self._on_accept)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.export_btn)
        root.addLayout(foot)

        # Checked-but-locked options read as "on, not changeable" instead of fully active.
        self.setStyleSheet(
            f"QCheckBox::indicator:checked:disabled {{ background: {PAL.rgba(PAL.accent, 0.32)};"
            f" border-color: {PAL.rgba(PAL.accent, 0.0)}; }}"
            f"QCheckBox:disabled {{ color: {PAL.text3}; }}")
        self._restore()
        self._ready = True
        self._refresh()

    # ------------------------------------------------------------------ building

    def _build_formats(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("class", "card")
        panel.setFixedWidth(214)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._tiles: dict[str, FormatTile] = {}
        for title, icon_name, keys in (
            ("이미지 시퀀스", "image", [k for k, f in E.FORMATS.items() if not f.is_movie]),
            ("동영상", "film", [k for k, f in E.FORMATS.items() if f.is_movie]),
        ):
            head = SectionTitle(title)
            head.setContentsMargins(8, 4 if not self._tiles else 10, 0, 2)
            lay.addWidget(head)
            for k in keys:
                t = FormatTile(k, icon_name)
                codec = _CODECS.get(k)
                if codec and self._codecs and codec not in self._codecs:
                    t.setEnabled(False)
                    t.setToolTip(f"{E.FORMATS[k].label}\n이 시스템의 FFmpeg에 {codec} 인코더가 없습니다.")
                t.toggled.connect(lambda on, key=k: on and self._on_format(key))
                self._group.addButton(t)
                self._tiles[k] = t
                lay.addWidget(t)
        lay.addStretch(1)
        return panel

    def _card(self, title: str) -> Card:
        c = Card(margins=(14, 10, 14, 12), spacing=8)
        c.lay.addWidget(SectionTitle(title))
        return c

    def _build_range(self) -> QWidget:
        c = self._card("범위")
        self.range_seg = Segmented([
            ("inout", "In–Out 구간", "In/Out 점 사이 (설정하지 않았으면 전체)"),
            ("all", "전체", "클립 전체"),
            ("current", "현재 프레임", "지금 보고 있는 프레임 하나"),
            ("custom", "직접 입력", "프레임 번호를 직접 입력"),
        ])
        self.range_seg.changed.connect(lambda _k: self._on_range_mode())
        c.lay.addWidget(self.range_seg)
        lo, hi = self.source.first, self.source.last
        self.first_spin = QSpinBox()
        self.last_spin = QSpinBox()
        for sp in (self.first_spin, self.last_spin):
            sp.setRange(lo, hi)
            sp.setFixedWidth(84)
            sp.setAlignment(Qt.AlignCenter)
            sp.setFont(mono_font(9.5))
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(lambda _v: self._on_custom_range())
        arrow = QLabel("→")
        arrow.setProperty("class", "faint")
        self.range_info = QLabel()
        self.range_info.setProperty("class", "muted")
        self.range_info.setTextFormat(Qt.RichText)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.first_spin)
        row.addWidget(arrow)
        row.addWidget(self.last_spin)
        row.addSpacing(6)
        row.addWidget(self.range_info, 1)
        c.lay.addLayout(row)
        return c

    def _build_output(self) -> QWidget:
        c = self._card("출력")
        self.path_edit = QLineEdit()
        self.path_edit.setFont(mono_font(9))
        self.path_edit.setPlaceholderText("D:/out/shot.####.png")
        self.path_edit.textEdited.connect(lambda _t: self._refresh())
        self.path_edit.textChanged.connect(self.path_edit.setToolTip)
        browse = QPushButton("찾아보기…")
        browse.setIcon(_icon("folder-open", 16))
        browse.clicked.connect(self._browse)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(self.path_edit, 1)
        prow.addWidget(browse)
        c.lay.addLayout(prow)
        self.path_hint = QLabel()
        self.path_hint.setProperty("class", "mono")
        self.path_hint.setWordWrap(False)
        self.path_hint.setMinimumWidth(10)
        self.path_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        c.lay.addWidget(self.path_hint)
        c.lay.addSpacing(2)

        self.size_seg = Segmented([(str(s), f"{int(s * 100)}%", "") for s in E.SCALES])
        self.size_seg.changed.connect(lambda _k: self._refresh())
        self.size_label = QLabel()
        self.size_label.setProperty("class", "mono")
        c.lay.addWidget(_row("크기", self.size_seg, 6, self.size_label, None))

        self.quality = ScrubField("", 18, 0, 51, step=0.2, decimals=0, bar=True, width=150)
        self.quality.setFixedWidth(150)
        self.quality.valueChanged.connect(lambda _v: self._refresh())
        self.quality_hint = muted("", "faint")
        self.quality_row = _row("품질", self.quality, 4, self.quality_hint, None)
        c.lay.addWidget(self.quality_row)

        self.fps_combo = QComboBox()
        self.fps_combo.setEditable(True)
        self.fps_combo.addItems(_FPS_PRESETS)
        self.fps_combo.setFixedWidth(92)
        self.fps_combo.lineEdit().setValidator(QDoubleValidator(1.0, 240.0, 3, self))
        self.fps_combo.lineEdit().setFont(mono_font(9.5))
        self.fps_combo.setCurrentText(fps_label(self.source.fps))
        self.fps_combo.currentTextChanged.connect(lambda _t: self._refresh())
        self.start_spin = QSpinBox()
        self.start_spin.setRange(-1_000_000, 10_000_000)
        self.start_spin.setFixedWidth(84)
        self.start_spin.setAlignment(Qt.AlignCenter)
        self.start_spin.setFont(mono_font(9.5))
        self.start_spin.valueChanged.connect(self._on_start_edited)
        self.start_label = QLabel("시작 번호")
        self.start_label.setProperty("class", "muted")
        c.lay.addWidget(_row("FPS", self.fps_combo, 18, self.start_label, self.start_spin, None))
        return c

    def _build_options(self) -> QWidget:
        c = self._card("옵션")
        self.color_chk = QCheckBox("뷰어 색 보정 적용")
        self.color_chk.setChecked(True)
        self.burn_chk = QCheckBox("주석 포함")
        self.audio_chk = QCheckBox("오디오 포함")
        self.alpha_chk = QCheckBox("알파 유지")
        self.color_chk.toggled.connect(lambda _v: self._refresh())
        self.burn_chk.toggled.connect(lambda _v: self._refresh())
        self.audio_chk.toggled.connect(lambda _v: self._refresh())
        self.alpha_chk.clicked.connect(self._on_alpha_clicked)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.addWidget(self.color_chk, 0, 0)
        grid.addWidget(self.burn_chk, 0, 1)
        grid.addWidget(self.audio_chk, 1, 0)
        grid.addWidget(self.alpha_chk, 1, 1)
        grid.setColumnStretch(2, 1)
        c.lay.addLayout(grid)
        self.option_hint = muted("", "faint")
        self.option_hint.setWordWrap(True)
        c.lay.addWidget(self.option_hint)
        if E.has_drawings(self.source):
            self.burn_chk.setChecked(True)
        else:
            self.burn_chk.setEnabled(False)
            self.burn_chk.setToolTip("이 클립에는 그린 주석이 없습니다.")
        self.audio_chk.setChecked(bool(self.source.audio_path))
        return c

    # ------------------------------------------------------------------ state

    def _restore(self) -> None:
        fmt = _LAST.get("fmt", "mp4_h264" if self.source.kind == "movie" else "png")
        if fmt not in self._tiles or not self._tiles[fmt].isEnabled():
            fmt = "png"
        self._fmt = fmt
        self.size_seg.set_value(str(_LAST.get("scale", 1.0)))
        has_range = self.source.in_point is not None or self.source.out_point is not None
        self.range_seg.set_value("inout" if has_range else "all")
        self._on_range_mode(refresh=False)
        self.path_edit.setText(E.default_output_path(self.source, fmt))
        self._auto_path = self.path_edit.text()
        self._tiles[fmt].setChecked(True)
        self._apply_format_defaults(fmt)

    def fmt(self) -> str:
        return self._fmt

    def _on_format(self, key: str) -> None:
        if key == getattr(self, "_fmt", None) and self.path_edit.text():
            return
        self._fmt = key
        path = self.path_edit.text().strip()
        was_auto = not path or path == self._auto_path
        new = E.default_output_path(self.source, key) if was_auto else E.with_extension(path, key)
        self.path_edit.setText(new)
        if was_auto:
            self._auto_path = new
        self._apply_format_defaults(key)
        self.formatChanged.emit(key)
        self._refresh()

    def _apply_format_defaults(self, key: str) -> None:
        q = E.QUALITY.get(key)
        if q:
            kind, lo, hi, default = q
            self.quality.minimum, self.quality.maximum = float(lo), float(hi)
            self.quality.default = float(default)
            remembered = _LAST.get(f"quality_{key}")
            self.quality.label = "CRF" if kind == "crf" else "Q"
            self.quality.setValue(float(remembered if remembered is not None else default))
            self.quality.update()
        if not self._alpha_touched:
            self.alpha_chk.setChecked(key in ("exr", "mov_prores4444"))

    def _on_alpha_clicked(self, _checked: bool) -> None:
        self._alpha_touched = True
        self._refresh()

    def _on_start_edited(self, _v: int) -> None:
        if getattr(self, "_setting_start", False):
            return
        self._start_touched = True
        self._refresh()

    def _range_values(self) -> tuple[int, int]:
        mode = self.range_seg.value()
        src = self.source
        if mode == "inout":
            return src.range
        if mode == "all":
            return src.first, src.last
        if mode == "current":
            f = max(src.first, min(self.current_frame, src.last))
            return f, f
        return self.first_spin.value(), self.last_spin.value()

    def _on_range_mode(self, refresh: bool = True) -> None:
        custom = self.range_seg.value() == "custom"
        if not custom:
            lo, hi = self._range_values()
            for sp, v in ((self.first_spin, lo), (self.last_spin, hi)):
                sp.blockSignals(True)
                sp.setValue(v)
                sp.blockSignals(False)
        self.first_spin.setEnabled(custom)
        self.last_spin.setEnabled(custom)
        if refresh:
            self._refresh()

    def _on_custom_range(self) -> None:
        if self.range_seg.value() == "custom":
            self._refresh()

    def _fps(self) -> float:
        try:
            v = float(self.fps_combo.currentText().replace(",", "."))
            return v if v > 0 else self.source.fps
        except ValueError:
            return self.source.fps

    def _scale(self) -> float:
        try:
            return float(self.size_seg.value())
        except ValueError:
            return 1.0

    # ------------------------------------------------------------------ refresh

    def _refresh(self) -> None:
        if not self._ready:
            return
        key = self._fmt
        spec = E.FORMATS[key]
        movie = spec.is_movie
        is_exr = key == "exr"
        src = self.source

        # options
        self.color_chk.setEnabled(is_exr)
        if not is_exr:
            self.color_chk.blockSignals(True)
            self.color_chk.setChecked(True)
            self.color_chk.blockSignals(False)
            self.color_chk.setToolTip("8/16비트와 동영상 형식은 항상 뷰어 색 보정을 적용합니다.")
        else:
            self.color_chk.setToolTip("끄면 레이어의 원본 값(채널 이름, 데이터 윈도우 포함)을 그대로 씁니다.")
        raw = is_exr and not self.color_chk.isChecked()
        has_audio = bool(src.audio_path)
        self.audio_chk.setEnabled(movie and has_audio)
        self.audio_chk.setToolTip("" if (movie and has_audio) else
                                  ("동영상 형식에서만 오디오를 넣을 수 있습니다." if has_audio else "이 클립에는 오디오가 없습니다."))
        alpha_ok = spec.supports_alpha and E.source_has_alpha(src) and not raw
        self.alpha_chk.setEnabled(alpha_ok)
        if not spec.supports_alpha:
            self.alpha_chk.setToolTip("이 형식은 알파 채널을 지원하지 않습니다.")
        elif not E.source_has_alpha(src):
            self.alpha_chk.setToolTip("현재 레이어에 알파 채널이 없습니다.")
        elif raw:
            self.alpha_chk.setToolTip("원본 값 EXR은 레이어의 모든 채널을 그대로 씁니다.")
        else:
            self.alpha_chk.setToolTip("")
        hints = []
        if raw:
            hints.append("원본 값: 색 변환 없이 레이어 채널을 half/float 그대로 씁니다.")
        elif not is_exr:
            hints.append("색 보정은 EXR에서만 끌 수 있습니다.")
        if movie and has_audio and self.audio_chk.isChecked() and abs(self._fps() - src.fps) > 1e-3:
            hints.append("FPS가 원본과 달라 오디오 싱크가 어긋날 수 있습니다.")
        self.option_hint.setText("  ·  ".join(hints))
        self.option_hint.setVisible(bool(hints))

        # quality / fps / start number
        q = E.QUALITY.get(key)
        self.quality_row.setVisible(bool(q))
        if q:
            v = int(self.quality.value())
            if q[0] == "crf":
                self.quality_hint.setText(f"낮을수록 고화질 · 권장 {q[3]}")
            else:
                self.quality_hint.setText(f"높을수록 고화질 · 권장 {q[3]}")
            _LAST[f"quality_{key}"] = v
        self.start_label.setVisible(not movie)
        self.start_spin.setVisible(not movie)
        lo, hi = self._range_values()
        if not self._start_touched and self.start_spin.value() != lo:
            self._setting_start = True
            self.start_spin.setValue(lo)
            self._setting_start = False

        # range info
        n = hi - lo + 1
        fps = self._fps()
        dur = frames_to_timecode(n, fps)
        self.range_info.setText(f"<span style='color:{PAL.text}; font-weight:600'>{n}</span>프레임"
                                f"<span style='color:{PAL.text3}'>&nbsp;&nbsp;·&nbsp;&nbsp;</span>"
                                f"<span style='font-family:\"JetBrains Mono\"; font-size:11px'>{dur}</span>")

        # size
        s = self.settings()
        ow, oh = E.source_output_size(s, src)
        par_note = "  (픽셀 비율 보정)" if movie and abs(self._par - 1.0) > 1e-3 else ""
        self.size_label.setText(f"{ow} × {oh}{par_note}")

        # path validation
        err = self._validate(s)
        if err:
            self.path_hint.setText(f"⚠  {err}")
            self.path_hint.setStyleSheet(f"color: {PAL.err}; font-family: \"Pretendard\", \"Malgun Gothic\";"
                                         " font-size: 11px;")
        else:
            if movie:
                text = f"→ {os.path.basename(s.path)}"
            else:
                a, b = os.path.basename(s.output_path(lo)), os.path.basename(s.output_path(hi))
                text = f"→ {a}" if lo == hi else f"→ {a}  …  {b}"
            self.path_hint.setText(text)
            self.path_hint.setStyleSheet("")
        self.export_btn.setEnabled(not err)

        # footer summary
        parts = [spec.label]
        if movie:
            parts.append(f"{n / max(fps, 1e-6):.1f}초")
            if self.audio_chk.isEnabled() and self.audio_chk.isChecked():
                parts.append("오디오")
        else:
            parts.append(f"파일 {n}개")
        parts.append(f"{ow} × {oh}")
        self.summary.setText("  ·  ".join(parts))

    # ------------------------------------------------------------------ validation

    def _validate(self, s: E.ExportSettings) -> str:
        path = s.path.strip()
        src = self.source
        if not path:
            return "출력 경로를 입력하세요."
        if s.first > s.last:
            return "시작 프레임이 끝 프레임보다 큽니다."
        if s.first < src.first or s.last > src.last:
            return f"범위는 {src.first}–{src.last} 안이어야 합니다."
        spec = E.FORMATS[s.fmt]
        ext = os.path.splitext(path)[1].lower()
        allowed = {spec.ext} | ({".jpeg"} if spec.ext == ".jpg" else set()) | ({".tiff"} if spec.ext == ".tif" else set())
        if ext not in allowed:
            return f"확장자가 {spec.ext} 이어야 합니다."
        if not spec.is_movie and not E.has_frame_token(path):
            return "시퀀스 경로에는 프레임 번호 자리(#### 또는 %04d)가 필요합니다."
        if spec.is_movie and E.has_frame_token(path):
            return "동영상 경로에는 ####를 쓰지 않습니다."
        folder = os.path.dirname(os.path.abspath(path))
        probe = folder
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not probe or not os.path.isdir(probe) or not os.access(probe, os.W_OK):
            return "이 폴더에 쓸 수 없습니다."
        src_paths = {os.path.abspath(src.frame_path(f)) for f in (s.first, s.last)}
        if os.path.abspath(s.output_path(s.first)) in src_paths:
            return "원본 파일을 덮어쓰게 됩니다. 다른 경로를 고르세요."
        return ""

    # ------------------------------------------------------------------ actions

    def _browse(self) -> None:
        key = self._fmt
        spec = E.FORMATS[key]
        cur = self.path_edit.text().strip() or E.default_output_path(self.source, key)
        start = cur
        if not spec.is_movie:
            start = E.sequence_path(cur, self.start_spin.value()) if E.has_frame_token(cur) else cur
        folder = os.path.dirname(start)
        if folder and not os.path.isdir(folder):
            parent = folder
            while parent and not os.path.isdir(parent) and os.path.dirname(parent) != parent:
                parent = os.path.dirname(parent)
            start = os.path.join(parent, os.path.basename(start))
        filt = f"{spec.label} (*{spec.ext})"
        path, _ = QFileDialog.getSaveFileName(self, "내보낼 위치", start, filt,
                                              options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if os.path.splitext(path)[1].lower() != spec.ext:
            path = os.path.splitext(path)[0] + spec.ext
        if not spec.is_movie and not E.has_frame_token(path):
            stem, ext = os.path.splitext(path)
            # "shot.1001.png" picked from the dialog: turn its number into the token
            import re

            m = re.search(r"(\d+)$", stem)
            stem = stem[: m.start()] + "#" * max(4, len(m.group(1))) if m else f"{stem}.####"
            path = stem + ext
        self.path_edit.setText(path)
        self._refresh()

    def _on_accept(self) -> None:
        s = self.settings()
        err = self._validate(s)
        if err:
            QMessageBox.warning(self, "내보내기", err)
            return
        first = s.output_path(s.first)
        if os.path.exists(first):
            what = "파일이" if s.is_movie else "시퀀스 파일이"
            box = QMessageBox(QMessageBox.Warning, "덮어쓰기 확인",
                              f"{what} 이미 있습니다.\n{first}\n\n덮어쓸까요?", QMessageBox.NoButton, self)
            yes = box.addButton("덮어쓰기", QMessageBox.AcceptRole)
            box.addButton("취소", QMessageBox.RejectRole)
            box.setDefaultButton(yes)
            box.exec()
            if box.clickedButton() is not yes:
                return
        _LAST["fmt"] = s.fmt
        _LAST["scale"] = s.scale
        self.accept()

    # ------------------------------------------------------------------ result

    def settings(self) -> E.ExportSettings:
        key = self._fmt
        lo, hi = self._range_values()
        movie = E.FORMATS[key].is_movie
        q = E.QUALITY.get(key)
        return E.ExportSettings(
            path=self.path_edit.text().strip(),
            fmt=key,
            first=lo,
            last=hi,
            start_number=None if movie else self.start_spin.value(),
            scale=self._scale(),
            apply_color=self.color_chk.isChecked() if key == "exr" else True,
            burn_annotations=self.burn_chk.isEnabled() and self.burn_chk.isChecked(),
            include_audio=self.audio_chk.isEnabled() and self.audio_chk.isChecked(),
            quality=int(self.quality.value()) if q else 0,
            fps=self._fps(),
            alpha=self.alpha_chk.isEnabled() and self.alpha_chk.isChecked(),
        )
