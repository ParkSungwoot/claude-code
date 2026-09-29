"""Color Area panel: the pixel under the cursor and min / max / mean of a selected region."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from cocseq.theme import MONO_FONT, PAL
from cocseq.ui.widgets import Card, SectionTitle

__all__ = ["AreaPanel"]

LUMA709 = (0.2126, 0.7152, 0.0722)
_CH_COLORS = {"R": "#FF6B6B", "G": "#4FD98A", "B": "#5AA2FF", "A": "#A2A8B3"}
DASH = "—"


def _short(name: str) -> str:
    return name.split(".")[-1] if name else "?"


def _ch_color(name: str) -> str:
    return _CH_COLORS.get(_short(name).upper()[:1] if len(_short(name)) == 1 else _short(name).upper(), PAL.text2)


def fmt(v, decimals: int = 4) -> str:
    """Float with 4 decimals, shortened for big magnitudes so columns stay narrow."""
    if v is None:
        return DASH
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DASH
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "+inf" if v > 0 else "-inf"
    a = abs(v)
    if a >= 1e5:
        return f"{v:.2e}"
    if a >= 1000:
        return f"{v:.1f}"
    if a >= 100:
        return f"{v:.2f}"
    return f"{v:.{decimals}f}"


def rgb_to_hsv(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Hue in degrees, saturation 0..1, value (unclamped max)."""
    mx, mn = max(r, g, b), min(r, g, b)
    v = mx
    d = mx - mn
    s = 0.0 if mx <= 1e-12 else max(0.0, min(1.0, d / mx))
    if d <= 1e-12:
        h = 0.0
    elif mx == r:
        h = 60.0 * (((g - b) / d) % 6.0)
    elif mx == g:
        h = 60.0 * ((b - r) / d + 2.0)
    else:
        h = 60.0 * ((r - g) / d + 4.0)
    return h, s, v


def luminance(values) -> float | None:
    if values is None or len(values) < 3:
        return None
    return LUMA709[0] * values[0] + LUMA709[1] * values[1] + LUMA709[2] * values[2]


def _to_qcolor(disp) -> QColor | None:
    if not disp:
        return None
    vals = [0.0 if not math.isfinite(float(c)) else min(1.0, max(0.0, float(c))) for c in disp]
    while len(vals) < 3:
        vals.append(vals[0] if vals else 0.0)
    a = vals[3] if len(vals) > 3 else 1.0
    return QColor.fromRgbF(vals[0], vals[1], vals[2], a)


# ------------------------------------------------------------------ widgets


class _Swatch(QWidget):
    """Rounded colour chip over a checkerboard (so alpha shows)."""

    def __init__(self, size: int = 40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color: QColor | None = None

    def set_color(self, c: QColor | None) -> None:
        if c != self._color:
            self._color = c
            self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 9, 9)
        if self._color is None:
            pen = QPen(PAL.qcolor("line2"), 1, Qt.DashLine)
            pen.setDashPattern([3, 3])
            p.setPen(pen)
            p.setBrush(PAL.qcolor("bg2"))
            p.drawPath(path)
            return
        p.save()
        p.setClipPath(path)
        if self._color.alphaF() < 0.999:
            s = 6
            light, dark = QColor("#3A3F49"), QColor("#2A2E36")
            for yy in range(0, self.height(), s):
                for xx in range(0, self.width(), s):
                    p.fillRect(xx, yy, s, s, light if (xx // s + yy // s) % 2 == 0 else dark)
        p.fillRect(self.rect(), self._color)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 38), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _label(text: str = "", role: str = "val", align=Qt.AlignRight | Qt.AlignVCenter) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("area", role)
    lab.setAlignment(align)
    if role in ("val", "big"):
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lab.setMinimumWidth(20)
    return lab


def _set_color(lab: QLabel, color: str | None) -> None:
    ss = f"color: {color};" if color else ""
    if lab.styleSheet() != ss:
        lab.setStyleSheet(ss)


class _ValueGrid(QWidget):
    """Header row of column names plus labelled rows of values (4 value columns)."""

    def __init__(self, columns: int = 4, label_width: int = 40, parent=None):
        super().__init__(parent)
        self.ncols = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnMinimumWidth(0, label_width)
        for c in range(1, columns + 1):
            self.grid.setColumnStretch(c, 1)
        self.headers: list[QLabel] = []
        for c in range(columns):
            h = _label("", "head")
            self.grid.addWidget(h, 0, c + 1)
            self.headers.append(h)
        self.rows: dict[str, tuple[QLabel, list[QLabel]]] = {}

    def add_row(self, key: str, title: str) -> None:
        r = len(self.rows) + 1
        t = _label(title, "rowkey", Qt.AlignLeft | Qt.AlignVCenter)
        self.grid.addWidget(t, r, 0)
        vals = []
        for c in range(self.ncols):
            v = _label(DASH, "val")
            self.grid.addWidget(v, r, c + 1)
            vals.append(v)
        self.rows[key] = (t, vals)

    def set_headers(self, names: list[str], colors: list[str | None] | None = None) -> None:
        for i, h in enumerate(self.headers):
            text = names[i] if i < len(names) else ""
            h.setText(text)
            _set_color(h, colors[i] if colors and i < len(colors) else None)

    def set_row(self, key: str, values: list[str], colors: list[str | None] | None = None) -> None:
        _t, labs = self.rows[key]
        for i, lab in enumerate(labs):
            text = values[i] if i < len(values) else ""
            if lab.text() != text:
                lab.setText(text)
            _set_color(lab, colors[i] if colors and i < len(colors) else None)

    def set_row_title(self, key: str, title: str, color: str | None = None) -> None:
        t, _labs = self.rows[key]
        t.setText(title)
        _set_color(t, color)


class _StatTable(QWidget):
    """Rows = channels (+ luminance); columns = min / max / mean."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnMinimumWidth(0, 40)
        for c, title in enumerate(("최소", "최대", "평균")):
            self.grid.addWidget(_label(title, "head"), 0, c + 1)
            self.grid.setColumnStretch(c + 1, 1)
        self._rows: list[tuple[QLabel, list[QLabel]]] = []

    def set_data(self, names: list[str], mins, maxs, means, lum: tuple | None = None) -> None:
        entries = [(_short(n), _ch_color(n), mins[i], maxs[i], means[i]) for i, n in enumerate(names)]
        if lum is not None:
            entries.append(("휘도", PAL.text2, lum[0], lum[1], lum[2]))
        if len(entries) != len(self._rows):
            # rebuild the rows so the grid never keeps space for rows that are gone
            for t, vals in self._rows:
                for w in (t, *vals):
                    self.grid.removeWidget(w)
                    w.hide()
                    w.deleteLater()
            self._rows = []
            for r in range(1, len(entries) + 1):
                t = _label("", "rowkey", Qt.AlignLeft | Qt.AlignVCenter)
                self.grid.addWidget(t, r, 0)
                vals = [_label("", "val") for _ in range(3)]
                for c, v in enumerate(vals):
                    self.grid.addWidget(v, r, c + 1)
                self._rows.append((t, vals))
        for (t, vals), (name, color, mn, mx, mean) in zip(self._rows, entries):
            t.setText(name)
            _set_color(t, color)
            for v, x in zip(vals, (mn, mx, mean)):
                v.setText(fmt(x))


def _channel_stats(arr: np.ndarray):
    """(min, max, mean) per channel, ignoring NaN / inf when present."""
    flat = arr.reshape(-1, arr.shape[-1]) if arr.ndim == 3 else arr.reshape(-1, 1)
    if flat.shape[0] == 0:
        n = flat.shape[1]
        return [float("nan")] * n, [float("nan")] * n, [float("nan")] * n
    mins = flat.min(axis=0)
    maxs = flat.max(axis=0)
    means = flat.mean(axis=0, dtype=np.float64)
    if not (np.isfinite(mins).all() and np.isfinite(maxs).all()):
        finite = np.where(np.isfinite(flat), flat, np.nan)
        with np.errstate(all="ignore"):
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                mins = np.nanmin(finite, axis=0)
                maxs = np.nanmax(finite, axis=0)
                means = np.nanmean(finite, axis=0, dtype=np.float64)
    return [float(x) for x in mins], [float(x) for x in maxs], [float(x) for x in means]


def _luma_stats(arr: np.ndarray):
    if arr is None or arr.ndim != 3 or arr.shape[-1] < 3 or arr.size == 0:
        return None
    y = arr[..., 0] * LUMA709[0] + arr[..., 1] * LUMA709[1] + arr[..., 2] * LUMA709[2]
    if not np.isfinite(y).all():
        y = y[np.isfinite(y)]
        if y.size == 0:
            return None
    return float(y.min()), float(y.max()), float(y.mean(dtype=np.float64))


# ------------------------------------------------------------------ panel


class AreaPanel(QWidget):
    """Live pixel readout under the cursor and statistics of a selected rectangle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AreaPanel")
        self._raw_names: list[str] | None = None
        self._merged: bool | None = None
        self.setStyleSheet(self._style())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(0)

        # ------------------------------------------------ pixel
        lay.addWidget(SectionTitle("픽셀"))
        lay.addSpacing(4)
        card = Card(margins=(12, 12, 12, 12), spacing=10)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        self.px_swatch = _Swatch(42)
        head.addWidget(self.px_swatch)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        coords = QHBoxLayout()
        coords.setSpacing(12)
        self.px_x = self._coord("X")
        self.px_y = self._coord("Y")
        coords.addLayout(self.px_x[0])
        coords.addLayout(self.px_y[0])
        coords.addStretch(1)
        col.addLayout(coords)
        self.px_note = _label("이미지 위에 커서를 올리면 값을 보여 줍니다", "note", Qt.AlignLeft | Qt.AlignVCenter)
        self.px_note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.px_note)
        head.addLayout(col, 1)
        card.lay.addLayout(head)
        card.lay.addWidget(self._hline())

        # raw values (own header when the channels are not plain RGBA)
        self.raw_grid = _ValueGrid()
        self.raw_grid.add_row("raw", "원본")
        card.lay.addWidget(self.raw_grid)
        self.disp_grid = _ValueGrid()
        self.disp_grid.add_row("raw", "원본")
        self.disp_grid.add_row("disp", "표시")
        self.disp_grid.add_row("8bit", "8비트")
        self.disp_grid.set_headers(["R", "G", "B", "A"], [_CH_COLORS[c] for c in "RGBA"])
        card.lay.addWidget(self.disp_grid)
        card.lay.addWidget(self._hline())

        extra = QGridLayout()
        extra.setContentsMargins(0, 0, 0, 0)
        extra.setHorizontalSpacing(6)
        extra.setVerticalSpacing(4)
        extra.setColumnMinimumWidth(0, 40)
        for c in range(1, 5):
            extra.setColumnStretch(c, 1)
        for c, t in enumerate(("H", "S", "V")):
            extra.addWidget(_label(t, "head"), 0, c + 1)
        extra.addWidget(_label("HSV", "rowkey", Qt.AlignLeft | Qt.AlignVCenter), 1, 0)
        self.hsv = [_label(DASH, "val") for _ in range(3)]
        for c, v in enumerate(self.hsv):
            extra.addWidget(v, 1, c + 1)
        extra.addWidget(_label("휘도", "rowkey", Qt.AlignLeft | Qt.AlignVCenter), 2, 0)
        self.lum = _label(DASH, "val")
        self.lum.setToolTip("원본 값의 Rec.709 휘도 (0.2126 R + 0.7152 G + 0.0722 B)")
        extra.addWidget(self.lum, 2, 1)
        lum_note = _label("Rec.709 · 원본", "note", Qt.AlignLeft | Qt.AlignVCenter)
        extra.addWidget(lum_note, 2, 2, 1, 3)
        card.lay.addLayout(extra)
        lay.addWidget(card)

        # ------------------------------------------------ area
        lay.addSpacing(16)
        lay.addWidget(SectionTitle("영역"))
        lay.addSpacing(4)
        self.hint_card = Card(margins=(14, 14, 14, 14), spacing=10)
        hl = QHBoxLayout()
        hl.setSpacing(12)
        from cocseq import icons

        ic = QLabel()
        ic.setPixmap(icons.pixmap("color-area", 22, PAL.text3, 2.0))
        ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        ic.setFixedWidth(24)
        hl.addWidget(ic, 0, Qt.AlignTop)
        hint = QLabel("영역 선택 도구(Shift+M)로 화면을 드래그하면 영역의 최소·최대·평균 값을 보여 줍니다.")
        hint.setWordWrap(True)
        hint.setProperty("area", "hint")
        hl.addWidget(hint, 1)
        self.hint_card.lay.addLayout(hl)
        lay.addWidget(self.hint_card)

        self.area_card = Card(margins=(12, 12, 12, 12), spacing=10)
        ah = QHBoxLayout()
        ah.setSpacing(12)
        self.area_swatch = _Swatch(42)
        self.area_swatch.setToolTip("영역 평균 (표시 값)")
        ah.addWidget(self.area_swatch)
        acol = QVBoxLayout()
        acol.setSpacing(2)
        self.area_pos = _label("", "big", Qt.AlignLeft | Qt.AlignVCenter)
        self.area_size = _label("", "note", Qt.AlignLeft | Qt.AlignVCenter)
        self.area_size.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        acol.addWidget(self.area_pos)
        acol.addWidget(self.area_size)
        ah.addLayout(acol, 1)
        self.area_card.lay.addLayout(ah)
        self.area_card.lay.addWidget(self._hline())
        self.raw_caption = _label("원본", "caption", Qt.AlignLeft | Qt.AlignVCenter)
        self.area_card.lay.addWidget(self.raw_caption)
        self.raw_table = _StatTable()
        self.area_card.lay.addWidget(self.raw_table)
        self.disp_caption = _label("표시", "caption", Qt.AlignLeft | Qt.AlignVCenter)
        self.area_card.lay.addSpacing(2)
        self.area_card.lay.addWidget(self.disp_caption)
        self.disp_table = _StatTable()
        self.area_card.lay.addWidget(self.disp_table)
        lay.addWidget(self.area_card)
        lay.addStretch(1)

        self.set_pixel({})
        self.set_area(None, None, None, [])

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _style() -> str:
        P = PAL
        return f"""
QLabel[area="val"] {{ color: {P.text}; font-family: "{MONO_FONT}"; font-size: 11px; }}
QLabel[area="big"] {{ color: {P.text}; font-family: "{MONO_FONT}"; font-size: 12px; }}
QLabel[area="coord"] {{ color: {P.text}; font-family: "{MONO_FONT}"; font-size: 14px; font-weight: 500; }}
QLabel[area="axis"] {{ color: {P.text3}; font-size: 11px; font-weight: 700; }}
QLabel[area="head"] {{ color: {P.text3}; font-size: 10.5px; font-weight: 700; }}
QLabel[area="rowkey"] {{ color: {P.text2}; font-size: 11px; }}
QLabel[area="note"] {{ color: {P.text3}; font-size: 11px; }}
QLabel[area="caption"] {{ color: {P.text3}; font-size: 10.5px; font-weight: 700; letter-spacing: 0.4px; }}
QLabel[area="hint"] {{ color: {P.text2}; font-size: 12px; }}
QWidget#AreaPanel[compact="true"] QLabel[area="val"] {{ font-size: 10px; }}
QWidget#AreaPanel[compact="true"] QLabel[area="rowkey"] {{ font-size: 10.5px; }}
"""

    def _coord(self, axis: str):
        box = QHBoxLayout()
        box.setSpacing(5)
        a = QLabel(axis)
        a.setProperty("area", "axis")
        v = QLabel(DASH)
        v.setProperty("area", "coord")
        v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(a, 0, Qt.AlignBaseline)
        box.addWidget(v, 0, Qt.AlignBaseline)
        return box, v

    @staticmethod
    def _hline() -> QFrame:
        f = QFrame()
        f.setProperty("class", "hline")
        f.setFixedHeight(1)
        return f

    def sizeHint(self) -> QSize:
        return QSize(330, 640)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        compact = self.width() < 310
        if self.property("compact") != compact:
            self.setProperty("compact", compact)
            gap = 4 if compact else 6
            for grid in self.findChildren(QGridLayout):
                grid.setHorizontalSpacing(gap)
                grid.setColumnMinimumWidth(0, 34 if compact else 40)
            for lab in self.findChildren(QLabel):
                if lab.property("area") in ("val", "rowkey"):
                    lab.style().unpolish(lab)
                    lab.style().polish(lab)

    # ------------------------------------------------------------ public API

    def set_pixel(self, info: dict) -> None:
        """Pixel under the cursor; {} when the cursor left the image (see module docs for keys)."""
        info = info or {}
        raw = info.get("raw")
        disp = info.get("display")
        names = list(info.get("names") or [])
        has = "x" in info and "y" in info
        self.px_x[1].setText(str(int(info["x"])) if has else DASH)
        self.px_y[1].setText(str(int(info["y"])) if has else DASH)

        if not has:
            note = "이미지 위에 커서를 올리면 값을 보여 줍니다"
        elif raw is None:
            note = "데이터 윈도우 밖"
        else:
            src = info.get("source")
            layer = getattr(getattr(src, "layer", None), "name", "")
            note = f"레이어 {layer}" if layer else f"{len(raw)}채널"
        self.px_note.setText(note)
        self.px_swatch.set_color(_to_qcolor(disp) if has else None)

        # raw values: merge into the RGBA grid when the channels are R, G, B(, A)
        if raw is not None and not names:
            names = ["R", "G", "B", "A"][:len(raw)] if len(raw) <= 4 else [f"C{i}" for i in range(len(raw))]
        shorts = [_short(n).upper() for n in names]
        merged = shorts == ["R", "G", "B", "A"][:len(shorts)] and len(shorts) >= 3 or not names
        if merged != self._merged or names != self._raw_names:
            self._merged = merged
            self._raw_names = names
            self.raw_grid.setVisible(not merged)
            self.disp_grid.rows["raw"][0].setVisible(merged)
            for lab in self.disp_grid.rows["raw"][1]:
                lab.setVisible(merged)
            if not merged:
                self.raw_grid.set_headers([_short(n) for n in names[:4]], [_ch_color(n) for n in names[:4]])
        raw_vals = [fmt(v) for v in (raw or [])[:4]] if raw is not None else ([DASH] * max(1, len(names[:4])))
        if merged:
            self.disp_grid.set_row("raw", raw_vals + [""] * (4 - len(raw_vals)) if raw is not None else [DASH] * 4)
        else:
            self.raw_grid.set_row("raw", raw_vals)

        if disp is not None and has:
            d = [float(c) for c in disp[:4]]
            while len(d) < 4:
                d.append(1.0)
            self.disp_grid.set_row("disp", [fmt(c) for c in d])
            eight = []
            for c in d:
                eight.append(str(int(round(min(1.0, max(0.0, c)) * 255))) if math.isfinite(c) else DASH)
            over = [PAL.warn if (math.isfinite(c) and (c > 1.0 or c < 0.0)) else None for c in d]
            self.disp_grid.set_row("8bit", eight, over)
            h, s, v = rgb_to_hsv(d[0], d[1], d[2]) if all(math.isfinite(c) for c in d[:3]) else (0.0, 0.0, 0.0)
            self.hsv[0].setText(f"{h:.1f}°")
            self.hsv[1].setText(fmt(s))
            self.hsv[2].setText(fmt(v))
        else:
            self.disp_grid.set_row("disp", [DASH] * 4)
            self.disp_grid.set_row("8bit", [DASH] * 4)
            for lab in self.hsv:
                lab.setText(DASH)
        y = luminance(raw) if raw is not None else None
        self.lum.setText(fmt(y) if y is not None else DASH)

    def set_area(self, rect: tuple | None, raw: np.ndarray | None, display: np.ndarray | None,
                 names: list[str]) -> None:
        """Statistics of an image-space rectangle (x0, y0, x1, y1); None shows the how-to hint."""
        if rect is None:
            self.hint_card.setVisible(True)
            self.area_card.setVisible(False)
            return
        self.hint_card.setVisible(False)
        self.area_card.setVisible(True)
        x0, y0, x1, y1 = (int(v) for v in rect)
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        w, h = x1 - x0, y1 - y0
        self.area_pos.setText(f"{x0}, {y0}  →  {x1}, {y1}")
        self.area_size.setText(f"{w} × {h}  ·  {w * h:,} 픽셀")

        names = list(names or [])
        if raw is not None and raw.size:
            arr = np.asarray(raw, np.float32)
            if arr.ndim == 2:
                arr = arr[..., None]
            nch = arr.shape[-1]
            if len(names) < nch:
                names = names + [f"C{i}" for i in range(len(names), nch)]
            mins, maxs, means = _channel_stats(arr)
            self.raw_table.set_data(names[:nch], mins, maxs, means, _luma_stats(arr))
            self.raw_caption.setVisible(True)
            self.raw_table.setVisible(True)
        else:
            self.raw_caption.setVisible(False)
            self.raw_table.setVisible(False)

        if display is not None and display.size:
            darr = np.asarray(display, np.float32)
            if darr.ndim == 2:
                darr = darr[..., None]
            dn = ["R", "G", "B", "A"][:darr.shape[-1]]
            mins, maxs, means = _channel_stats(darr)
            self.disp_table.set_data(dn, mins, maxs, means, _luma_stats(darr))
            self.disp_caption.setVisible(True)
            self.disp_table.setVisible(True)
            self.area_swatch.set_color(_to_qcolor(means))
        else:
            self.disp_caption.setVisible(False)
            self.disp_table.setVisible(False)
            self.area_swatch.set_color(None)
