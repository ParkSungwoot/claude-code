"""Image scopes: histogram, waveform (luma / RGB parade) and a Rec.709 vectorscope.

The host feeds a small display-referred float image (``set_image``) while the
panel is visible (``activeChanged``). All analysis is vectorised numpy; the
density plots are turned into QImages and drawn with a light graticule.
"""

from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget,
                               QVBoxLayout, QWidget)

from cocseq.theme import MONO_FONT, PAL, mono_font, ui_font
from cocseq.ui.widgets import Card, SectionTitle, Segmented

__all__ = ["ScopesPanel", "prepare", "luma", "histogram_bins", "waveform_counts", "vectorscope_counts"]

LUMA709 = (0.2126, 0.7152, 0.0722)
KB, KR = 1.8556, 1.5748          # Rec.709 Cb / Cr scale factors
VS_RANGE = 0.6                   # CbCr magnitude at the graticule's outer circle (1x zoom)
SKIN_DEG = 123.0                 # skin tone (I) line, degrees from +Cb counter-clockwise
MAX_SAMPLES = 260_000            # bigger images are subsampled before analysis

CH_COLORS = ("#FF5B5B", "#46D980", "#4C9BFF")
LUMA_WAVE = (0.80, 0.95, 0.87)   # soft phosphor white for the luma waveform

_TARGETS = (                     # label, RGB of the 100 % colour
    ("R", (1.0, 0.0, 0.0)), ("Mg", (1.0, 0.0, 1.0)), ("B", (0.0, 0.0, 1.0)),
    ("Cy", (0.0, 1.0, 1.0)), ("G", (0.0, 1.0, 0.0)), ("Yl", (1.0, 1.0, 0.0)),
)


# ============================================================== analysis (pure numpy)


def prepare(img) -> np.ndarray | None:
    """RGB float32 (h, w, 3), finite, subsampled to at most MAX_SAMPLES pixels."""
    if img is None:
        return None
    a = np.asarray(img)
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3 or a.shape[0] == 0 or a.shape[1] == 0 or a.shape[2] == 0:
        return None
    h, w = a.shape[:2]
    if h * w > MAX_SAMPLES:
        step = int(math.ceil(math.sqrt(h * w / MAX_SAMPLES)))
        a = a[::step, ::step]
    rgb = a[..., :3] if a.shape[2] >= 3 else np.repeat(a[..., :1], 3, axis=2)
    rgb = np.asarray(rgb, dtype=np.float32)          # a view when the input is already float32
    if not math.isfinite(float(rgb.sum(dtype=np.float64))):   # cheap NaN / inf probe
        rgb = np.nan_to_num(rgb, nan=0.0, posinf=1e4, neginf=-1e4)
    return rgb


def luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * LUMA709[0] + rgb[..., 1] * LUMA709[1] + rgb[..., 2] * LUMA709[2]


def histogram_bins(rgb: np.ndarray, y: np.ndarray, bins: int = 256) -> np.ndarray:
    """(4, bins) counts for R, G, B and luma over 0..1 (out-of-range values land in the end bins)."""
    out = np.empty((4, bins), np.float64)
    tmp = np.empty(y.shape, np.float32)
    for i, ch in enumerate((rgb[..., 0], rgb[..., 1], rgb[..., 2], y)):
        np.multiply(ch, np.float32(bins - 1), out=tmp)
        tmp += np.float32(0.5)
        np.clip(tmp, 0.0, bins - 1, out=tmp)
        out[i] = np.bincount(tmp.astype(np.int32).ravel(), minlength=bins)
    return out


def waveform_counts(values: np.ndarray, cols: int, rows: int) -> tuple[np.ndarray, float]:
    """Density (rows, bins) of value per image column; row 0 is value 1.0. Returns (counts, samples per bin).

    ``cols`` is the target plot width in pixels. Every bin gets the same number of image
    columns (1 when the image is at most twice as wide as the plot, else an integer k),
    so the trace has no brightness striping; the caller scales the result to the plot.
    """
    h, w = values.shape
    k = max(1, w // max(1, int(cols)))
    bins = max(1, w // k)
    used = bins * k
    rows = max(2, int(rows))
    if used != w:
        values = values[:, :used]
    colmap = np.arange(used, dtype=np.intp) // k
    r = ((1.0 - np.clip(values, 0.0, 1.0)) * (rows - 1) + 0.5).astype(np.intp)
    flat = r * bins + colmap[None, :]
    counts = np.bincount(flat.ravel(), minlength=rows * bins).reshape(rows, bins)
    return counts, float(h * k)


def soften_rows(counts: np.ndarray) -> np.ndarray:
    """Integer 1-2-1 blur along the value axis (a little phosphor glow); result is 4x the counts."""
    out = counts * 2
    out[1:] += counts[:-1]
    out[:-1] += counts[1:]
    out[0] += counts[0]
    out[-1] += counts[-1]
    return out


def cbcr(rgb: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (rgb[..., 2] - y) / KB, (rgb[..., 0] - y) / KR


def vectorscope_counts(cb: np.ndarray, cr: np.ndarray, n: int, zoom: float) -> np.ndarray:
    """(n, n) density of CbCr; the square spans +-VS_RANGE / zoom, +Cr up."""
    s = zoom / VS_RANGE
    half = (n - 1) * 0.5
    fx = cb * (s * half) + (half + 0.5)
    fy = (half + 0.5) - cr * (s * half)
    m = (fx >= 0) & (fx < n) & (fy >= 0) & (fy < n)
    ix = fx[m].astype(np.intp)
    iy = fy[m].astype(np.intp)
    return np.bincount(iy * n + ix, minlength=n * n).reshape(n, n)


_vs_colormaps: dict[tuple[int, float], np.ndarray] = {}


def vectorscope_colormap(n: int, zoom: float) -> np.ndarray:
    """(n, n, 3) float colours: every CbCr position tinted with its own hue."""
    key = (n, zoom)
    cm = _vs_colormaps.get(key)
    if cm is not None:
        return cm
    half = (n - 1) * 0.5
    u = (np.arange(n, dtype=np.float32) - half) / half * (VS_RANGE / zoom)
    cb = u[None, :]
    cr = -u[:, None]
    y = 0.5
    r = y + KR * cr
    b = y + KB * cb
    g = (y - LUMA709[0] * r - LUMA709[2] * b) / LUMA709[1]
    rgb = np.stack(np.broadcast_arrays(r, g, b), axis=-1).astype(np.float32)
    rgb = np.clip(rgb, 0.0, None)
    rgb /= np.maximum(rgb.max(axis=-1, keepdims=True), 1e-6)
    cm = 0.42 + 0.58 * rgb
    if len(_vs_colormaps) > 8:
        _vs_colormaps.clear()
    _vs_colormaps[key] = cm
    return cm


def density_to_image(counts: np.ndarray, norm: float, color, gamma: float = 0.5,
                     floor: float = 0.16) -> QImage:
    """Counts -> premultiplied RGBA QImage; brightness = (counts / norm) ** gamma, hits never below floor.

    ``color`` is one RGB triple (0..1) or an (h, w, 3) float array. The brightness curve is
    evaluated once per distinct count through a lookup table.
    """
    h, w = counts.shape
    norm = max(float(norm), 1e-9)
    cmax = int(counts.max()) if counts.size else 0
    top = int(min(cmax, math.ceil(norm)))
    lut = np.minimum(np.arange(top + 1, dtype=np.float32) * np.float32(1.0 / norm), 1.0)
    lut = np.sqrt(lut) if gamma == 0.5 else lut ** np.float32(gamma)
    lut = np.maximum(lut, np.float32(floor))
    lut[0] = 0.0
    idx = np.minimum(counts, top) if top < cmax else counts
    col = np.asarray(color, np.float32)
    if col.ndim == 1:
        lut4 = np.empty((top + 1, 4), np.float32)
        lut4[:, :3] = lut[:, None] * col[None, :3]
        lut4[:, 3] = lut
        out = (lut4 * 255.0 + 0.5).astype(np.uint8)[idx]
    else:
        # per-bin colours: shade only the occupied bins (a vectorscope trace is usually sparse)
        flat = idx.ravel()
        nz = np.flatnonzero(flat)
        v255 = lut[flat[nz]] * np.float32(255.0)
        out = np.zeros((h * w, 4), np.uint8)
        out[nz, :3] = col.reshape(-1, 3)[nz] * v255[:, None]
        out[nz, 3] = v255
    out = np.ascontiguousarray(out)
    img = QImage(out.data, w, h, 4 * w, QImage.Format_RGBA8888_Premultiplied)
    return img.copy()


def histogram_fill_image(heights: np.ndarray, width: int, height: int, alpha: float = 0.30) -> QImage:
    """Additive R/G/B area fills. heights: (3, bins) in 0..1 of the plot height."""
    nb = heights.shape[1]
    xc = (np.arange(width, dtype=np.float32) + 0.5) / width * nb - 0.5
    rows = np.arange(height, dtype=np.float32)[:, None]
    acc = np.zeros((height, width, 4), np.float32)
    for ch in range(3):
        hcol = np.interp(xc, np.arange(nb, dtype=np.float32), heights[ch]).astype(np.float32) * height
        top = height - hcol                                   # first covered row (fractional)
        cov = np.clip(rows + 1.0 - top[None, :], 0.0, 1.0) * np.float32(alpha)
        c = QColor(CH_COLORS[ch])
        acc[..., 0] += cov * c.redF()
        acc[..., 1] += cov * c.greenF()
        acc[..., 2] += cov * c.blueF()
        acc[..., 3] += cov
    np.minimum(acc, 1.0, out=acc)
    out = np.ascontiguousarray((acc * 255.0 + 0.5).astype(np.uint8))
    img = QImage(out.data, width, height, 4 * width, QImage.Format_RGBA8888_Premultiplied)
    return img.copy()


def _target_cbcr(rgb, scale: float = 0.75) -> tuple[float, float]:
    r, g, b = (c * scale for c in rgb)
    y = LUMA709[0] * r + LUMA709[1] * g + LUMA709[2] * b
    return (b - y) / KB, (r - y) / KR


# ============================================================== small widgets


def _fmt(v: float, digits: int = 3) -> str:
    if not math.isfinite(v):
        return "—"
    if abs(v) >= 1000:
        return f"{v:.0f}"
    return f"{v:.{digits}f}"


def _pct(v: float) -> str:
    if v <= 0:
        return "0 %"
    if v < 0.01:
        return "<0.01 %"
    if v < 10:
        return f"{v:.2f} %"
    return f"{v:.1f} %"


class _Legend(QWidget):
    """Tiny coloured dot + letter entries."""

    def __init__(self, entries: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.entries = entries
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._font = ui_font(8.5, QFont.DemiBold)
        fm = QFontMetricsF(self._font)
        self._w = [10 + fm.horizontalAdvance(t) for t, _c in entries]
        self.setFixedWidth(int(sum(self._w) + 10 * (len(entries) - 1)) + 2)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font)
        x = 1.0
        cy = self.height() / 2
        for (text, color), w in zip(self.entries, self._w):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(x + 3, cy), 3, 3)
            p.setPen(PAL.qcolor("text3"))
            p.drawText(QRectF(x + 10, 0, w, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += w + 10


class _StatGrid(Card):
    """3-column grid of label / value cells."""

    COLS = 3

    def __init__(self, parent=None):
        super().__init__(parent, margins=(12, 10, 12, 10), spacing=0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(8)
        self.lay.addLayout(self.grid)
        self._cells: list[tuple[QLabel, QLabel]] = []
        for i in range(6):
            cell = QWidget(self)
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(1)
            lab = QLabel("", cell)
            lab.setProperty("scope", "statlabel")
            val = QLabel("—", cell)
            val.setProperty("scope", "statvalue")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(lab)
            v.addWidget(val)
            self.grid.addWidget(cell, i // self.COLS, i % self.COLS)
            self._cells.append((lab, val))
        for c in range(self.COLS):
            self.grid.setColumnStretch(c, 1)

    def set_cells(self, cells: list[tuple]) -> None:
        """cells: [(label, value, value_color_or_None, label_color_or_None)]"""
        for i, (lab, val) in enumerate(self._cells):
            if i < len(cells):
                item = tuple(cells[i]) + (None, None)
                text, value, vcol, lcol = item[0], item[1], item[2], item[3]
                lab.setText(text)
                val.setText(value)
                vss = f"color: {vcol};" if vcol else ""
                lss = f"color: {lcol};" if lcol else ""
                if val.styleSheet() != vss:
                    val.setStyleSheet(vss)
                if lab.styleSheet() != lss:
                    lab.setStyleSheet(lss)
                lab.parentWidget().setVisible(True)
            else:
                lab.parentWidget().setVisible(False)


# ============================================================== plot


class _ScopeView(QWidget):
    def __init__(self, panel: "ScopesPanel"):
        super().__init__(panel)
        self.panel = panel
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.setMinimumSize(180, 120)
        self._cache_key = None
        self._cache: list[QImage] = []

    # -- geometry

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        mode = self.panel.mode
        if mode == "vector":
            return int(w)
        if mode == "wave":
            return int(round(w * 0.68))
        return int(round(w * 0.62))

    def sizeHint(self) -> QSize:
        return QSize(306, self.heightForWidth(306))

    def invalidate(self) -> None:
        self._cache_key = None
        self.update()

    # -- rects

    def _frame(self) -> QRectF:
        return QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

    def _hist_plot(self) -> QRectF:
        return self._frame().adjusted(12, 14, -12, -24)

    def _wave_plot(self) -> QRectF:
        return self._frame().adjusted(34, 14, -12, -14)

    def _vector_square(self) -> QRectF:
        f = self._frame()
        side = min(f.width(), f.height()) - 28
        return QRectF(f.center().x() - side / 2, f.center().y() - side / 2, side, side)

    # -- paint

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = self._frame()
        p.setPen(QPen(PAL.qcolor("line"), 1))
        p.setBrush(PAL.qcolor("bg1"))
        p.drawRoundedRect(f, 10, 10)
        panel = self.panel
        if panel._rgb is None:
            self._paint_empty(p, f)
            return
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(f.adjusted(1, 1, -1, -1), 9, 9)
        p.setClipPath(clip)
        if panel.mode == "hist":
            self._paint_hist(p)
        elif panel.mode == "wave":
            self._paint_wave(p)
        else:
            self._paint_vector(p)
        p.restore()

    def _label_font(self) -> QFont:
        return mono_font(7.5)

    def _paint_empty(self, p: QPainter, f: QRectF) -> None:
        from cocseq import icons

        icon_name = {"hist": "histogram", "wave": "waveform", "vector": "vectorscope"}[self.panel.mode]
        pm = icons.pixmap(icon_name, 30, PAL.text3, self.devicePixelRatioF())
        c = f.center()
        p.drawPixmap(QPointF(c.x() - 15, c.y() - 30), pm)
        p.setFont(ui_font(9.5))
        p.setPen(PAL.qcolor("text2"))
        p.drawText(QRectF(f.left() + 12, c.y() + 8, f.width() - 24, 22), Qt.AlignCenter,
                   "이미지를 열면 스코프가 표시됩니다")

    # histogram ------------------------------------------------------

    def _paint_hist(self, p: QPainter) -> None:
        panel = self.panel
        plot = self._hist_plot()
        bins = panel._data("hist")
        if bins is None:
            return
        # grid
        p.setFont(self._label_font())
        for i, t in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
            x = plot.left() + t * plot.width()
            p.setPen(QPen(PAL.qcolor("line2") if i in (0, 4) else PAL.qcolor("line"), 1))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(PAL.qcolor("text3"))
            text = ("0", ".25", ".5", ".75", "1")[i]
            align = Qt.AlignLeft if i == 0 else (Qt.AlignRight if i == 4 else Qt.AlignHCenter)
            box = QRectF(x - 20, plot.bottom() + 5, 40, 14)
            if i == 0:
                box.moveLeft(x)
            elif i == 4:
                box.moveRight(x)
            p.drawText(box, align | Qt.AlignTop, text)
        dash = QPen(PAL.qcolor("line"), 1, Qt.DashLine)
        dash.setDashPattern([2, 3])
        p.setPen(dash)
        for t in (0.25, 0.5, 0.75):
            y = plot.bottom() - t * plot.height()
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        n = bins.shape[1]
        if panel.log_scale:
            vals = np.log1p(bins)
            top = max(float(vals.max()), 1e-6)
        else:
            vals = bins
            inner = bins[:, 1:-1]
            top = max(float(inner.max()) if inner.size else 0.0, 1.0)
        norm = np.clip(vals / top, 0.0, 1.0) * 0.96

        # additive translucent fills, rasterised with numpy (fast for any shape)
        dpr = self.devicePixelRatioF()
        W = max(2, min(n, int(round(plot.width() * dpr))))       # one column per bin is plenty
        H = max(2, min(720, int(round(plot.height() * dpr))))
        key = ("hist", panel._gen, panel.log_scale, W, H)
        if key != self._cache_key:
            self._cache = [histogram_fill_image(norm[:3], W, H)]
            self._cache_key = key
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(plot, self._cache[0])
        p.restore()

        # outlines: cosmetic pens are an order of magnitude faster than wide antialiased strokes
        xs = plot.left() + (np.arange(n) + 0.5) / n * plot.width()
        ys = plot.bottom() - norm * plot.height()
        p.setBrush(Qt.NoBrush)
        for ch in range(4):
            poly = QPolygonF([QPointF(x, y) for x, y in zip(xs.tolist(), ys[ch].tolist())])
            if ch < 3:
                c = QColor(CH_COLORS[ch])
                c.setAlphaF(0.95)
            else:
                c = PAL.qcolor("text", 0.92)
            pen = QPen(c, 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPolyline(poly)

    # waveform -------------------------------------------------------

    def _paint_wave(self, p: QPainter) -> None:
        panel = self.panel
        plot = self._wave_plot()
        # grid: every 10 IRE, labels every 20
        p.setFont(self._label_font())
        for ire in range(0, 101, 10):
            y = plot.bottom() - ire / 100.0 * plot.height()
            major = ire in (0, 50, 100)
            if major:
                p.setPen(QPen(PAL.qcolor("line2"), 1))
            else:
                pen = QPen(PAL.qcolor("line"), 1, Qt.DashLine)
                pen.setDashPattern([2, 3])
                p.setPen(pen)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if ire % 20 == 0:
                p.setPen(PAL.qcolor("text3"))
                p.drawText(QRectF(plot.left() - 34, y - 7, 28, 14), Qt.AlignRight | Qt.AlignVCenter, str(ire))

        dpr = self.devicePixelRatioF()
        parade = panel.wave_mode == "parade"
        gap = 6.0
        if parade:
            sub_w = (plot.width() - 2 * gap) / 3
            rects = [QRectF(plot.left() + i * (sub_w + gap), plot.top(), sub_w, plot.height()) for i in range(3)]
        else:
            rects = [QRectF(plot)]
        cols = max(8, int(rects[0].width() * dpr))
        rows = max(16, min(720, int(plot.height() * dpr)))
        key = ("wave", panel._gen, parade, cols, rows)
        if key != self._cache_key:
            rgb = panel._rgb
            if parade:
                self._cache = []
                for ch in range(3):
                    counts, spc = waveform_counts(rgb[..., ch], cols, rows)
                    color = QColor(CH_COLORS[ch])
                    tint = (color.redF() * 0.85 + 0.15, color.greenF() * 0.85 + 0.15, color.blueF() * 0.85 + 0.15)
                    self._cache.append(density_to_image(soften_rows(counts), spc * 64.0 / rows, tint, gamma=0.55))
            else:
                counts, spc = waveform_counts(panel._y, cols, rows)
                self._cache = [density_to_image(soften_rows(counts), spc * 64.0 / rows, LUMA_WAVE, gamma=0.55)]
            self._cache_key = key
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for img, r in zip(self._cache, rects):
            p.drawImage(r, img)
        if parade:
            p.setFont(ui_font(8, QFont.Bold))
            for ch, r in enumerate(rects):
                c = QColor(CH_COLORS[ch])
                c.setAlphaF(0.85)
                p.setPen(c)
                p.drawText(r.adjusted(5, 3, -4, 0), Qt.AlignLeft | Qt.AlignTop, "RGB"[ch])
                if ch:
                    p.setPen(QPen(PAL.qcolor("line"), 1))
                    x = r.left() - gap / 2
                    p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

    # vectorscope ----------------------------------------------------

    def _paint_vector(self, p: QPainter) -> None:
        panel = self.panel
        sq = self._vector_square()
        c = sq.center()
        R = sq.width() / 2
        zoom = panel.zoom
        s = zoom / VS_RANGE

        # graticule under the trace
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(PAL.qcolor("line"), 1))
        p.drawLine(QPointF(c.x() - R, c.y()), QPointF(c.x() + R, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - R), QPointF(c.x(), c.y() + R))
        dash = QPen(PAL.qcolor("line"), 1, Qt.DashLine)
        dash.setDashPattern([2, 3])
        p.setPen(dash)
        p.drawEllipse(c, R * 0.5, R * 0.5)
        p.setPen(QPen(PAL.qcolor("line2"), 1.2))
        p.drawEllipse(c, R, R)
        p.setPen(QPen(PAL.qcolor("line2"), 1))
        for deg in range(0, 360, 10):
            a = math.radians(deg)
            ln = 7 if deg % 30 == 0 else 3.5
            ca, sa = math.cos(a), -math.sin(a)
            p.drawLine(QPointF(c.x() + ca * R, c.y() + sa * R),
                       QPointF(c.x() + ca * (R - ln), c.y() + sa * (R - ln)))

        # trace
        dpr = self.devicePixelRatioF()
        n = max(64, min(512, int(sq.width() * dpr)))
        key = ("vector", panel._gen, n, zoom)
        if key != self._cache_key:
            cb, cr = panel._data("cbcr")
            counts = vectorscope_counts(cb, cr, n, zoom)
            total = max(1, cb.size)
            cm = vectorscope_colormap(n, zoom)
            self._cache = [density_to_image(counts, total * 0.0025, cm, gamma=0.45, floor=0.2)]
            self._cache_key = key
        p.save()
        disc = QPainterPath()
        disc.addEllipse(c, R + 1.5, R + 1.5)
        p.setClipPath(disc, Qt.IntersectClip)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(sq, self._cache[0])
        p.restore()

        # skin tone line
        if panel.skin_line:
            a = math.radians(SKIN_DEG)
            sc = QColor(PAL.warn)
            sc.setAlphaF(0.55)
            pen = QPen(sc, 1, Qt.DashLine)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawLine(c, QPointF(c.x() + math.cos(a) * R, c.y() - math.sin(a) * R))

        # 75 % targets (boxes) and 100 % targets (dots)
        p.setFont(mono_font(7.5, QFont.Medium))
        for label, rgb in _TARGETS:
            cb75, cr75 = _target_cbcr(rgb, 0.75)
            cb100, cr100 = _target_cbcr(rgb, 1.0)
            ang = math.atan2(cr75, cb75)
            ux, uy = math.cos(ang), -math.sin(ang)
            tcol = QColor(*(int(v * 255) for v in rgb))
            tcol = QColor.fromHsvF(tcol.hsvHueF(), 0.55, 1.0, 0.8)
            r75 = math.hypot(cb75, cr75) * s * R
            r100 = math.hypot(cb100, cr100) * s * R
            if r75 <= R - 6:
                pt = QPointF(c.x() + ux * r75, c.y() + uy * r75)
                p.setPen(QPen(tcol, 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(pt.x() - 4.5, pt.y() - 4.5, 9, 9))
                if r100 <= R - 3:
                    q = QPointF(c.x() + ux * r100, c.y() + uy * r100)
                    dot = QColor(tcol)
                    dot.setAlphaF(0.55)
                    p.setPen(Qt.NoPen)
                    p.setBrush(dot)
                    p.drawEllipse(q, 1.8, 1.8)
                    p.setBrush(Qt.NoBrush)
                lr = r75 - 15
                lpt = QPointF(c.x() + ux * lr, c.y() + uy * lr)
            else:
                # zoomed in: show the direction on the rim
                lr = R - 14
                lpt = QPointF(c.x() + ux * lr, c.y() + uy * lr)
            p.setPen(tcol)
            p.drawText(QRectF(lpt.x() - 12, lpt.y() - 7, 24, 14), Qt.AlignCenter, label)

        # zoom badge
        if zoom != 1:
            f = self._frame()
            p.setFont(mono_font(7.5, QFont.Medium))
            p.setPen(PAL.qcolor("text3"))
            p.drawText(QRectF(f.left() + 10, f.top() + 8, 60, 14), Qt.AlignLeft | Qt.AlignTop, f"{zoom:g}x")


# ============================================================== panel


class ScopesPanel(QWidget):
    """Histogram / waveform / vectorscope of the displayed image."""

    activeChanged = Signal(bool)

    MODES = ("hist", "wave", "vector")
    STATS_INTERVAL = 0.12      # seconds between stats-row refreshes while frames stream in

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ScopesPanel")
        self.mode = "hist"
        self.wave_mode = "luma"
        self.zoom = 1.0
        self.log_scale = False
        self.skin_line = True
        self._active = False
        self._gen = 0
        self._pending = None
        self._dirty = False
        self._rgb: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._derived: dict = {}
        self._stats_at = 0.0
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.timeout.connect(self._refresh_stats)

        self.setStyleSheet(
            f'QLabel[scope="statlabel"] {{ color: {PAL.text3}; font-size: 11px; }}'
            f'QLabel[scope="statvalue"] {{ color: {PAL.text}; font-family: "{MONO_FONT}"; font-size: 12px; }}'
            f'QLabel[scope="hint"] {{ color: {PAL.text3}; font-size: 11px; }}'
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.seg = Segmented([
            ("hist", "히스토그램", "히스토그램 (RGB + 휘도)", "histogram"),
            ("wave", "웨이브폼", "웨이브폼 (열별 값 분포)", "waveform"),
            ("vector", "벡터스코프", "벡터스코프 (Rec.709 CbCr)", "vectorscope"),
        ], icon_size=15)
        for k in self.MODES:
            b = self.seg.button(k)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumWidth(30)
        self.seg.changed.connect(self.set_mode)
        lay.addWidget(self.seg)

        # per-mode options
        self.options = QStackedWidget(self)
        self.options.setFixedHeight(26)
        # histogram
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(_Legend([("R", CH_COLORS[0]), ("G", CH_COLORS[1]), ("B", CH_COLORS[2]), ("휘도", PAL.text)]))
        h.addStretch(1)
        self.log_check = QCheckBox("로그 스케일")
        self.log_check.setCursor(Qt.PointingHandCursor)
        self.log_check.toggled.connect(self.set_log_scale)
        h.addWidget(self.log_check)
        self.options.addWidget(w)
        # waveform
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.wave_seg = Segmented([("luma", "휘도", "Rec.709 휘도 웨이브폼"),
                                   ("parade", "RGB 퍼레이드", "R, G, B 채널을 나란히 표시")])
        self.wave_seg.changed.connect(self.set_wave_mode)
        h.addWidget(self.wave_seg)
        h.addStretch(1)
        self._wave_hint = QLabel("0–100 = 0.0–1.0")
        self._wave_hint.setProperty("scope", "hint")
        self._wave_hint.setToolTip("세로축 0–100은 표시 값 0.0–1.0입니다. 1.0을 넘는 값은 맨 위 선에 모입니다.")
        h.addWidget(self._wave_hint)
        self.options.addWidget(w)
        # vectorscope
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.zoom_seg = Segmented([("1", "1x", "전체 범위"), ("2", "2x", "중심부 2배 확대 (저채도 확인)")])
        self.zoom_seg.changed.connect(lambda k: self.set_zoom(float(k)))
        h.addWidget(self.zoom_seg)
        h.addStretch(1)
        self.skin_check = QCheckBox("피부톤 선")
        self.skin_check.setChecked(True)
        self.skin_check.setCursor(Qt.PointingHandCursor)
        self.skin_check.toggled.connect(self._set_skin)
        h.addWidget(self.skin_check)
        self.options.addWidget(w)
        lay.addWidget(self.options)

        self.view = _ScopeView(self)
        lay.addWidget(self.view)

        self.stats_title = SectionTitle("통계")
        lay.addWidget(self.stats_title)
        self.stats = _StatGrid(self)
        lay.addWidget(self.stats)
        lay.addStretch(1)
        self._refresh_stats()

    # ------------------------------------------------------------ public API

    @property
    def active(self) -> bool:
        """True while the panel is shown (the host should keep feeding images)."""
        return self._active

    def set_image(self, img: np.ndarray | None) -> None:
        """Display-referred float image (h, w, 4), top row first. None clears the scopes."""
        if not self._active and img is not None:
            # Keep the latest frame; analyse it once the panel is shown.
            self._pending = img
            self._dirty = True
            return
        self._pending = None
        self._dirty = False
        self._analyse(img)

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            return
        self.mode = mode
        self.seg.set_value(mode)
        self.options.setCurrentIndex(self.MODES.index(mode))
        self.view.invalidate()
        self.view.updateGeometry()
        self._refresh_stats()

    def set_log_scale(self, on: bool) -> None:
        self.log_scale = bool(on)
        if self.log_check.isChecked() != self.log_scale:
            self.log_check.setChecked(self.log_scale)
        self.view.update()

    def set_wave_mode(self, mode: str) -> None:
        if mode not in ("luma", "parade"):
            return
        self.wave_mode = mode
        self.wave_seg.set_value(mode)
        self.view.invalidate()
        self._refresh_stats()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = 2.0 if zoom >= 2 else 1.0
        self.zoom_seg.set_value(str(int(self.zoom)))
        self.view.invalidate()

    # ------------------------------------------------------------ internals

    def _set_skin(self, on: bool) -> None:
        self.skin_line = bool(on)
        self.view.update()

    def _analyse(self, img) -> None:
        rgb = prepare(img)
        self._gen += 1
        self._rgb = rgb
        self._y = luma(rgb) if rgb is not None else None
        self._derived = {}
        self.view.invalidate()
        # During playback the numbers would flicker unreadably: refresh them at most ~8x a second.
        now = time.monotonic()
        wait = self.STATS_INTERVAL - (now - self._stats_at)
        if rgb is None or wait <= 0:
            self._stats_timer.stop()
            self._refresh_stats()
        elif not self._stats_timer.isActive():
            self._stats_timer.start(max(1, int(wait * 1000)))

    def _data(self, what: str):
        """Derived data of the current image, computed on first use: 'hist', 'cbcr' or a stats kind."""
        if self._rgb is None:
            return None
        got = self._derived.get(what)
        if got is not None:
            return got
        rgb, y = self._rgb, self._y
        if what == "hist":
            got = histogram_bins(rgb, y)
        elif what == "cbcr":
            got = cbcr(rgb, y)
        elif what == "luma":
            got = self._luma_stats(rgb, y)
        elif what == "channels":
            flat = (rgb[..., 0], rgb[..., 1], rgb[..., 2])
            got = {"mean": [float(c.mean(dtype=np.float64)) for c in flat],
                   "max": [float(c.max()) for c in flat]}
        elif what == "color":
            got = self._color_stats(rgb)
        self._derived[what] = got
        return got

    def _luma_stats(self, rgb: np.ndarray, y: np.ndarray) -> dict:
        n = max(1, y.size)
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        st = {
            "min": float(y.min()), "max": float(y.max()), "mean": float(y.mean(dtype=np.float64)),
            "over": np.count_nonzero(np.maximum(np.maximum(r, g), b) > 1.0) * 100.0 / n,
            "under": np.count_nonzero(np.minimum(np.minimum(r, g), b) < 0.0) * 100.0 / n,
        }
        # median from the luma histogram (exact to 1/255, no sort)
        hist = self._data("hist")[3]
        cum = np.cumsum(hist)
        st["median"] = float(np.searchsorted(cum, cum[-1] / 2.0)) / (hist.size - 1) if cum[-1] > 0 else float("nan")
        return st

    def _color_stats(self, rgb: np.ndarray) -> dict:
        n = max(1, rgb.shape[0] * rgb.shape[1])
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        out_of_range = np.count_nonzero((mx > 1.0) | (mn < 0.0)) * 100.0 / n
        # HSV-style saturation of the (non-negative) display values
        np.maximum(mx, 0.0, out=mx)
        np.maximum(mn, 0.0, out=mn)
        sat = (mx - mn) / np.maximum(mx, 1e-6)
        cb, cr = self._data("cbcr")
        mcb, mcr = float(cb.mean(dtype=np.float64)), float(cr.mean(dtype=np.float64))
        hue = (math.degrees(math.atan2(mcr, mcb)) % 360.0) if math.hypot(mcb, mcr) > 1e-4 else float("nan")
        return {"sat_mean": float(sat.mean(dtype=np.float64)) * 100.0, "sat_max": float(sat.max()) * 100.0,
                "cb": mcb, "cr": mcr, "hue": hue, "out": out_of_range}

    def _refresh_stats(self) -> None:
        self._stats_at = time.monotonic()
        has = self._rgb is not None
        self.stats_title.setVisible(has)
        self.stats.setVisible(has)
        if not has:
            return
        warn = PAL.warn
        if self.mode == "vector":
            st = self._data("color")
            self.stats_title.setText("통계 · 색")
            hue = st["hue"]
            hue_text = "—" if not math.isfinite(hue) else f"{hue:.0f}° {self._hue_name(hue)}"
            cells = [
                ("평균 채도", f"{st['sat_mean']:.1f} %"),
                ("최대 채도", f"{st['sat_max']:.1f} %"),
                ("평균 색상", hue_text),
                ("평균 Cb", f"{st['cb']:+.4f}"),
                ("평균 Cr", f"{st['cr']:+.4f}"),
                ("범위 밖", _pct(st["out"]), warn if st["out"] > 0 else None),
            ]
        elif self.mode == "wave" and self.wave_mode == "parade":
            st = self._data("channels")
            self.stats_title.setText("통계 · 채널")
            cells = []
            for i, ch in enumerate("RGB"):
                cells.append((f"{ch} 평균", _fmt(st["mean"][i], 4), None, CH_COLORS[i]))
            for i, ch in enumerate("RGB"):
                v = st["max"][i]
                cells.append((f"{ch} 최대", _fmt(v, 4), warn if v > 1.0 else None, CH_COLORS[i]))
        else:
            st = self._data("luma")
            self.stats_title.setText("통계 · 휘도")
            cells = [
                ("최소", _fmt(st["min"], 4), warn if st["min"] < 0 else None),
                ("평균", _fmt(st["mean"], 4)),
                ("최대", _fmt(st["max"], 4), warn if st["max"] > 1.0 else None),
                ("중간값", _fmt(st["median"], 4)),
                ("1.0 초과", _pct(st["over"]), warn if st["over"] > 0 else None),
                ("0.0 미만", _pct(st["under"]), warn if st["under"] > 0 else None),
            ]
        self.stats.set_cells(cells)

    @staticmethod
    def _hue_name(deg: float) -> str:
        best, best_d = "", 999.0
        for label, rgb in _TARGETS:
            cb, cr = _target_cbcr(rgb, 1.0)
            a = math.degrees(math.atan2(cr, cb)) % 360.0
            d = abs((deg - a + 180.0) % 360.0 - 180.0)
            if d < best_d:
                best, best_d = label, d
        return best

    # ------------------------------------------------------------ Qt events

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if not self._active:
            self._active = True
            if self._dirty:
                img, self._pending, self._dirty = self._pending, None, False
                self._analyse(img)
            self.activeChanged.emit(True)

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)
        if self._active and not self.isVisible():
            self._active = False
            self.activeChanged.emit(False)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        compact = self.width() < 300
        self._wave_hint.setVisible(self.width() >= 320)
        style = Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon
        for k in self.MODES:
            b = self.seg.button(k)
            if b.toolButtonStyle() != style:
                b.setToolButtonStyle(style)
