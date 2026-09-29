"""Timeline: ruler, cached frames, in/out range, annotation marks, audio waveform and playhead."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from cocseq.theme import PAL, mono_font, ui_font
from cocseq.utils import format_frame, nice_step


class Timeline(QWidget):
    frameRequested = Signal(int)
    scrubStarted = Signal()
    scrubFinished = Signal()
    hoverFrame = Signal(int, int)       # frame, global x   (-1 when leaving)

    RULER_H = 20
    TRACK_H = 24
    WAVE_H = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(self.RULER_H + self.TRACK_H + 14)
        self.first = 1
        self.last = 100
        self.frame = 1
        self.in_point: int | None = None
        self.out_point: int | None = None
        self.fps = 24.0
        self.time_mode = "frames"
        self.cached: set[int] = set()
        self.marks: list[int] = []
        self.missing: set[int] = set()
        self.clip_name = ""
        self.peaks: np.ndarray | None = None
        self.peaks_offset = 0.0         # frames of audio before the first frame
        self.peaks_frames = 0.0         # audio length in frames
        self._v0 = None                 # visible range when zoomed (floats)
        self._v1 = None
        self._scrubbing = False
        self._panning = None
        self._hover_x = -1.0
        self._cache_img: QImage | None = None
        self._cache_key = None
        self._update_height()

    # ---------------------------------------------------------------- data

    def _update_height(self) -> None:
        h = self.RULER_H + self.TRACK_H + 14 + (self.WAVE_H + 2 if self.peaks is not None else 0)
        self.setFixedHeight(h)

    def set_range(self, first: int, last: int) -> None:
        if (first, last) != (self.first, self.last):
            self.first, self.last = int(first), int(max(first, last))
            self._v0 = self._v1 = None
            self._cache_key = None
            self.update()

    def set_frame(self, f: int) -> None:
        if f != self.frame:
            self.frame = f
            if self._v0 is not None and not (self._v0 <= f <= self._v1):
                span = self._v1 - self._v0
                self._v0 = max(self.first - 0.5, f - span * 0.1)
                self._v1 = self._v0 + span
            self.update()

    def set_inout(self, lo: int | None, hi: int | None) -> None:
        self.in_point, self.out_point = lo, hi
        self.update()

    def set_cached(self, frames: set[int]) -> None:
        if frames != self.cached:
            self.cached = frames
            self._cache_key = None
            self.update()

    def set_marks(self, marks: list[int]) -> None:
        self.marks = list(marks)
        self.update()

    def set_missing(self, missing) -> None:
        self.missing = set(missing)
        self._cache_key = None
        self.update()

    def set_fps(self, fps: float) -> None:
        self.fps = fps
        self.update()

    def set_time_mode(self, mode: str) -> None:
        self.time_mode = mode
        self.update()

    def set_audio(self, peaks: np.ndarray | None, offset_frames: float = 0.0, length_frames: float = 0.0) -> None:
        self.peaks = peaks
        self.peaks_offset = offset_frames
        self.peaks_frames = length_frames
        self._update_height()
        self.update()

    # ---------------------------------------------------------------- geometry

    def _visible(self) -> tuple[float, float]:
        if self._v0 is None:
            return self.first - 0.5, self.last + 0.5
        return self._v0, self._v1

    def _area(self) -> QRectF:
        return QRectF(12, 0, max(10, self.width() - 24), self.height())

    def x_of(self, f: float) -> float:
        a = self._area()
        v0, v1 = self._visible()
        return a.left() + (f - v0) / max(1e-9, v1 - v0) * a.width()

    def frame_at(self, x: float) -> int:
        a = self._area()
        v0, v1 = self._visible()
        f = v0 + (x - a.left()) / max(1e-9, a.width()) * (v1 - v0)
        return int(max(self.first, min(self.last, math.floor(f + 0.5))))

    # ---------------------------------------------------------------- paint

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), PAL.qcolor("bg2"))
        a = self._area()
        v0, v1 = self._visible()
        ppf = a.width() / max(1e-9, v1 - v0)      # pixels per frame
        top = self.RULER_H
        track = QRectF(a.left(), top + 2, a.width(), self.TRACK_H)

        # Clip bar
        x0 = max(a.left(), self.x_of(self.first - 0.5))
        x1 = min(a.right(), self.x_of(self.last + 0.5))
        clip = QRectF(x0, track.top(), max(2, x1 - x0), track.height())
        path = QPainterPath()
        path.addRoundedRect(clip, 6, 6)
        g = QLinearGradient(clip.topLeft(), clip.bottomLeft())
        g.setColorAt(0, PAL.qcolor("bg4"))
        g.setColorAt(1, PAL.qcolor("bg3"))
        p.fillPath(path, g)
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        p.drawPath(path)

        # In / out region
        lo = self.in_point if self.in_point is not None else self.first
        hi = self.out_point if self.out_point is not None else self.last
        if self.in_point is not None or self.out_point is not None:
            rx0, rx1 = self.x_of(lo - 0.5), self.x_of(hi + 0.5)
            p.save()
            p.setClipPath(path)
            dim = QColor(0, 0, 0, 120)
            p.fillRect(QRectF(clip.left(), clip.top(), rx0 - clip.left(), clip.height()), dim)
            p.fillRect(QRectF(rx1, clip.top(), clip.right() - rx1, clip.height()), dim)
            p.fillRect(QRectF(rx0, clip.top(), rx1 - rx0, clip.height()), PAL.qcolor("accent", 0.10))
            p.restore()
            p.setPen(QPen(PAL.qcolor("accent"), 2))
            for x, is_in in ((rx0, True), (rx1, False)):
                p.drawLine(QPointF(x, clip.top() - 2), QPointF(x, clip.bottom() + 2))
                br = QPainterPath()
                d = 5 if is_in else -5
                br.moveTo(x, clip.top() - 2)
                br.lineTo(x + d, clip.top() - 2)
                br.moveTo(x, clip.bottom() + 2)
                br.lineTo(x + d, clip.bottom() + 2)
                p.drawPath(br)

        # Clip name
        if self.clip_name and clip.width() > 80:
            p.setFont(ui_font(8.5, QFont.DemiBold))
            p.setPen(PAL.qcolor("text3"))
            p.drawText(clip.adjusted(10, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, self.clip_name)

        # Cache bar and missing frames
        self._paint_cache(p, clip, ppf)

        # Annotation marks
        if self.marks:
            p.setPen(Qt.NoPen)
            p.setBrush(PAL.qcolor("warn"))
            for f in self.marks:
                if v0 <= f <= v1:
                    x = self.x_of(f)
                    y = clip.top() + 5
                    diamond = [QPointF(x, y - 3.5), QPointF(x + 3.5, y), QPointF(x, y + 3.5), QPointF(x - 3.5, y)]
                    p.drawPolygon(diamond)

        # Audio waveform
        if self.peaks is not None and len(self.peaks):
            wr = QRectF(a.left(), clip.bottom() + 6, a.width(), self.WAVE_H)
            self._paint_wave(p, wr)

        # Ruler (labels hidden under the playhead label)
        avoid = None
        if self.first <= self.frame <= self.last:
            label = format_frame(self.frame, self.time_mode, self.fps, self.first)
            lw = QFontMetricsF(mono_font(8, QFont.DemiBold)).horizontalAdvance(label) + 12
            xph = self.x_of(self.frame)
            avoid = (xph - lw / 2 - 4, xph + lw / 2 + 4)
        self._paint_ruler(p, a, v0, v1, ppf, avoid)

        # Hover line
        if self._hover_x >= 0 and not self._scrubbing:
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.drawLine(QPointF(self._hover_x, top), QPointF(self._hover_x, h))

        # Playhead
        if self.first <= self.frame <= self.last:
            x = self.x_of(self.frame)
            if a.left() - 1 <= x <= a.right() + 1:
                acc = PAL.qcolor("accent")
                if ppf > 3:
                    p.fillRect(QRectF(x - ppf / 2, clip.top(), ppf, clip.height()), PAL.qcolor("accent", 0.25))
                p.setPen(QPen(acc, 2))
                p.drawLine(QPointF(x, top - 1), QPointF(x, h - 3))
                label = format_frame(self.frame, self.time_mode, self.fps, self.first)
                p.setFont(mono_font(8, QFont.DemiBold))
                fm = QFontMetricsF(p.font())
                lw = fm.horizontalAdvance(label) + 12
                lr = QRectF(x - lw / 2, 1, lw, 17)
                if lr.left() < 0:
                    lr.moveLeft(0)
                if lr.right() > w:
                    lr.moveRight(w)
                p.setPen(Qt.NoPen)
                p.setBrush(acc)
                p.drawRoundedRect(lr, 5, 5)
                p.setPen(QColor("white"))
                p.drawText(lr, Qt.AlignCenter, label)

    def _paint_cache(self, p: QPainter, clip: QRectF, ppf: float) -> None:
        y = clip.bottom() - 4
        if not self.cached and not self.missing:
            return
        v0, v1 = self._visible()
        lo, hi = int(math.floor(v0)), int(math.ceil(v1))
        # Collapse consecutive frames into runs so wide ranges draw quickly.
        frames = sorted(f for f in self.cached if lo <= f <= hi)
        runs = []
        for f in frames:
            if runs and f == runs[-1][1] + 1:
                runs[-1][1] = f
            else:
                runs.append([f, f])
        p.setPen(Qt.NoPen)
        p.setBrush(PAL.qcolor("ok", 0.85))
        for a, b in runs:
            xa, xb = self.x_of(a - 0.5), self.x_of(b + 0.5)
            r = QRectF(max(xa, clip.left() + 3), y, min(xb, clip.right() - 3) - max(xa, clip.left() + 3), 2.5)
            if r.width() > 0:
                p.drawRect(r)
        if self.missing:
            p.setBrush(PAL.qcolor("err"))
            for f in self.missing:
                if lo <= f <= hi:
                    x = self.x_of(f)
                    p.drawRect(QRectF(x - max(1.0, ppf / 2), clip.top() + 3, max(2.0, ppf), clip.height() - 6))

    def _paint_wave(self, p: QPainter, r: QRectF) -> None:
        peaks = self.peaks
        n = len(peaks)
        if n == 0 or self.peaks_frames <= 0:
            return
        start = self.first - self.peaks_offset
        p.save()
        p.setClipRect(r)
        p.setPen(Qt.NoPen)
        p.setBrush(PAL.qcolor("b", 0.55))
        cols = int(r.width())
        mid = r.center().y()
        v0, v1 = self._visible()
        path = QPainterPath()
        path.moveTo(r.left(), mid)
        tops = []
        for i in range(0, cols, 2):
            f = v0 + (i / max(1, r.width())) * (v1 - v0)
            k = (f - start) / self.peaks_frames
            if 0 <= k < 1:
                amp = float(peaks[min(n - 1, int(k * n))])
            else:
                amp = 0.0
            tops.append((r.left() + i, amp))
        for x, amp in tops:
            path.lineTo(x, mid - amp * r.height() / 2)
        for x, amp in reversed(tops):
            path.lineTo(x, mid + amp * r.height() / 2)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()

    def _paint_ruler(self, p: QPainter, a: QRectF, v0: float, v1: float, ppf: float, avoid=None) -> None:
        span = v1 - v0
        p.setFont(mono_font(7.5))
        fm = QFontMetricsF(p.font())
        sample = format_frame(int(self.last), self.time_mode, self.fps, self.first)
        label_w = fm.horizontalAdvance(sample) + 24
        max_labels = max(2, int(a.width() / label_w))
        if self.time_mode in ("timecode", "seconds") and self.fps >= 1:
            fps_i = max(1, int(round(self.fps)))
            candidates = [1, 2, 5, 10, fps_i // 2 or 1, fps_i, fps_i * 2, fps_i * 5, fps_i * 10, fps_i * 30,
                          fps_i * 60, fps_i * 300, fps_i * 600]
            candidates = sorted(set(c for c in candidates if c > 0))
            step = next((c for c in candidates if span / c <= max_labels), candidates[-1])
        else:
            step = max(1, int(nice_step(span, max_labels)))
        minor = step / 5 if step >= 5 else (1 if step > 1 else 0)
        base = self.first
        first_tick = base + math.ceil((v0 - base) / step) * step
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        if minor and minor * ppf >= 4:
            t = base + math.ceil((v0 - base) / minor) * minor
            while t <= v1:
                x = self.x_of(t)
                p.drawLine(QPointF(x, self.RULER_H - 4), QPointF(x, self.RULER_H - 1))
                t += minor
        t = first_tick
        while t <= v1 + 1e-6:
            x = self.x_of(t)
            if a.left() - 1 <= x <= a.right() + 1:
                p.setPen(QPen(PAL.qcolor("text3"), 1))
                p.drawLine(QPointF(x, self.RULER_H - 7), QPointF(x, self.RULER_H - 1))
                label = format_frame(int(round(t)), self.time_mode, self.fps, self.first)
                lx1 = x + 3 + fm.horizontalAdvance(label)
                if avoid is None or lx1 < avoid[0] or x + 3 > avoid[1]:
                    p.setPen(PAL.qcolor("text3"))
                    p.drawText(QPointF(x + 3, self.RULER_H - 8), label)
            t += step

    # ---------------------------------------------------------------- mouse

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._scrubbing = True
            self.scrubStarted.emit()
            self.frameRequested.emit(self.frame_at(ev.position().x()))
        elif ev.button() == Qt.MiddleButton:
            self._panning = (ev.position().x(), self._visible())

    def mouseMoveEvent(self, ev) -> None:
        x = ev.position().x()
        self._hover_x = x
        if self._scrubbing:
            self.frameRequested.emit(self.frame_at(x))
        elif self._panning is not None:
            x0, (v0, v1) = self._panning
            df = (x - x0) / max(1e-9, self._area().width()) * (v1 - v0)
            self._set_view(v0 - df, v1 - df)
        f = self.frame_at(x)
        self.hoverFrame.emit(f, int(self.mapToGlobal(QPointF(x, 0).toPoint()).x()))
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if self._scrubbing and ev.button() == Qt.LeftButton:
            self._scrubbing = False
            self.scrubFinished.emit()
        self._panning = None

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.MiddleButton or ev.modifiers() & Qt.ControlModifier:
            self._v0 = self._v1 = None
            self.update()

    def leaveEvent(self, ev) -> None:
        self._hover_x = -1
        self.hoverFrame.emit(-1, 0)
        self.update()

    def wheelEvent(self, ev) -> None:
        d = ev.angleDelta().y() or ev.pixelDelta().y()
        if not d:
            return
        if ev.modifiers() & Qt.ControlModifier:
            v0, v1 = self._visible()
            f = v0 + (ev.position().x() - self._area().left()) / max(1, self._area().width()) * (v1 - v0)
            k = 0.8 if d > 0 else 1.25
            self._set_view(f - (f - v0) * k, f + (v1 - f) * k)
        elif ev.modifiers() & Qt.ShiftModifier:
            v0, v1 = self._visible()
            df = (v1 - v0) * (-0.1 if d > 0 else 0.1)
            self._set_view(v0 + df, v1 + df)
        else:
            self.frameRequested.emit(max(self.first, min(self.last, self.frame + (-1 if d > 0 else 1))))

    def _set_view(self, v0: float, v1: float) -> None:
        full0, full1 = self.first - 0.5, self.last + 0.5
        span = min(full1 - full0, max(8.0, v1 - v0))
        v0 = max(full0, min(v0, full1 - span))
        v1 = v0 + span
        if abs(span - (full1 - full0)) < 1e-6:
            self._v0 = self._v1 = None
        else:
            self._v0, self._v1 = v0, v1
        self.update()


class ThumbPopup(QWidget):
    """Frame preview shown above the timeline while hovering."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._img: QImage | None = None
        self._label = ""
        self.resize(196, 130)

    def show_at(self, global_x: int, global_bottom: int, label: str, img: QImage | None) -> None:
        self._label = label
        self._img = img
        iw, ih = (img.width(), img.height()) if img is not None else (180, 101)
        w, h = iw + 12, ih + 34
        self.resize(w, h)
        self.move(int(global_x - w / 2), int(global_bottom - h - 6))
        self.update()
        if not self.isVisible():
            self.show()

    def set_image(self, img: QImage) -> None:
        self._img = img
        self.resize(img.width() + 12, img.height() + 34)
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        p.setBrush(PAL.qcolor("bg3"))
        p.drawRoundedRect(r, 9, 9)
        ir = QRectF(6, 6, r.width() - 12, r.height() - 34)
        if self._img is not None:
            p.drawImage(ir, self._img)
        else:
            p.fillRect(ir, PAL.qcolor("bg1"))
            p.setPen(PAL.qcolor("text3"))
            p.setFont(ui_font(8.5))
            p.drawText(ir, Qt.AlignCenter, "불러오는 중…")
        p.setPen(PAL.qcolor("text"))
        p.setFont(mono_font(8.5, QFont.DemiBold))
        p.drawText(QRectF(0, r.height() - 27, r.width(), 22), Qt.AlignCenter, self._label)
