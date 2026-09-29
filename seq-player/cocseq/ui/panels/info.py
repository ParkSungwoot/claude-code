"""Media information: file, image, playback and codec details plus searchable metadata."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
                               QScrollArea, QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from cocseq.theme import MONO_FONT, PAL, mono_font
from cocseq.ui.widgets import Card, SectionTitle
from cocseq.utils import fps_label, frames_to_timecode, human_bytes

__all__ = ["MediaInfoPanel"]

KEY_WIDTH = 78


def _icon(name: str, size: int = 16, color: str | None = None):
    from cocseq import icons

    return icons.icon(name, color=color, size=size)


def _frame_ranges(frames: list[int], limit: int = 6) -> str:
    """[1, 2, 3, 7, 9, 10] -> '1–3, 7, 9–10'."""
    if not frames:
        return ""
    runs: list[tuple[int, int]] = []
    start = prev = frames[0]
    for f in frames[1:]:
        if f == prev + 1:
            prev = f
            continue
        runs.append((start, prev))
        start = prev = f
    runs.append((start, prev))
    parts = [str(a) if a == b else f"{a}–{b}" for a, b in runs[:limit]]
    text = ", ".join(parts)
    if len(runs) > limit:
        text += f" 외 {len(runs) - limit}구간"
    return text


def _bitrate(bps: int) -> str:
    if bps <= 0:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{bps / 1000:.0f} kbps"


def _ratio(w: int, h: int) -> str:
    if not w or not h:
        return ""
    return f"{w / h:.2f}:1"


def _pixel_type(info) -> str:
    t = info.pixel_type or "—"
    kind = "부동소수" if info.is_float else "정수"
    if info.bit_depth:
        return f"{t} · {info.bit_depth}비트 {kind}"
    return t


def _window(win) -> str:
    x, y, w, h = win
    return f"{w} × {h}  @ {x}, {y}"


# ------------------------------------------------------------------ small widgets


class _ElideLabel(QLabel):
    """Single-line label that elides to its width; the full text is in the tooltip."""

    def __init__(self, text: str = "", mode=Qt.ElideMiddle, parent=None):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(30)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._elide()

    def _elide(self) -> None:
        w = self.width() - 2
        text = self.fontMetrics().elidedText(self._full, self._mode, max(10, w)) if w > 10 else self._full
        if text != self.text():
            super().setText(text)


class _MetaTree(QTreeWidget):
    """Two-column key/value list sized to its rows; wheel events scroll the page instead."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MetaTree")
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIndentation(0)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.setTextElideMode(Qt.ElideRight)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        hdr = self.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setMinimumSectionSize(40)
        self._key_width = 100

    def set_key_width(self, w: int) -> None:
        self._key_width = w
        self._fit_columns()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._fit_columns()

    def _fit_columns(self) -> None:
        avail = max(80, self.viewport().width())
        self.setColumnWidth(0, int(min(self._key_width, avail * 0.46)))

    def wheelEvent(self, ev) -> None:
        ev.ignore()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        QTimer.singleShot(0, self.fit_height)

    def fit_height(self) -> None:
        n = sum(1 for i in range(self.topLevelItemCount()) if not self.topLevelItem(i).isHidden())
        rh = self.sizeHintForRow(0) if self.topLevelItemCount() else 22
        rh = max(rh, 18)
        # viewport height = rows; the frame adds the style sheet border + padding around it
        chrome = self.height() - self.viewport().height() if self.isVisible() else 2 * self.frameWidth() + 8
        self.setFixedHeight(max(1, n) * rh + max(chrome, 2))

    def selected_text(self, with_keys: bool = True) -> str:
        items = self.selectedItems() or ([self.currentItem()] if self.currentItem() else [])
        lines = []
        for it in items:
            key, value = it.text(0), it.data(1, Qt.UserRole) or it.text(1)
            lines.append(f"{key}: {value}" if with_keys else str(value))
        return "\n".join(lines)

    def keyPressEvent(self, ev) -> None:
        if ev.matches(QKeySequence.Copy):
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            return
        super().keyPressEvent(ev)

    def _menu(self, pos) -> None:
        it = self.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.setCurrentItem(it)
        m = QMenu(self)
        a_val = m.addAction("값 복사")
        a_both = m.addAction("키와 값 복사")
        chosen = m.exec(self.viewport().mapToGlobal(pos))
        if chosen is a_val:
            QGuiApplication.clipboard().setText(self.selected_text(with_keys=False))
        elif chosen is a_both:
            QGuiApplication.clipboard().setText(self.selected_text())


# ------------------------------------------------------------------ panel


class MediaInfoPanel(QWidget):
    """Details of the current clip: file, image, playback, codec, layers and metadata."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MediaInfoPanel")
        self._source = None
        self._sig: tuple = ()
        self._info = None
        self._frame = None
        self._sections: list[tuple[str, list[tuple[str, str]]]] = []
        self._frame_labels: dict[str, QLabel] = {}
        self._meta_items: list[QTreeWidgetItem] = []
        self._filter = ""
        self.setStyleSheet(self._style())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        self._content: QWidget | None = None
        self.set_source(None)

    # ------------------------------------------------------------ style

    @staticmethod
    def _style() -> str:
        P = PAL
        return f"""
QLabel[info="key"] {{ color: {P.text2}; }}
QLabel[info="value"] {{ color: {P.text}; }}
QLabel[info="mono"] {{ color: {P.text}; font-family: "{MONO_FONT}"; font-size: 11px; }}
QLabel[info="sub"] {{ color: {P.text3}; font-size: 11px; }}
QLabel[info="warn"] {{ color: {P.warn}; }}
QLabel[info="ok"] {{ color: {P.text3}; }}
QLabel[info="name"] {{ color: {P.text}; font-size: 13px; font-weight: 600; }}
QLabel[info="kind"] {{ color: {P.text2}; font-size: 11px; }}
QLabel[info="chip"] {{
    color: {P.text2}; background: {P.bg4}; border: 1px solid {P.line2}; border-radius: 5px;
    padding: 0 5px; font-family: "{MONO_FONT}"; font-size: 10px;
}}
QLabel[info="current"] {{
    color: {P.accent}; background: {P.rgba(P.accent, 0.14)}; border-radius: 5px;
    padding: 0 6px; font-size: 10px; font-weight: 700;
}}
QLabel[info="count"] {{ color: {P.text3}; font-size: 11px; font-weight: 600; padding-top: 4px; }}
QLabel[info="empty"] {{ color: {P.text2}; font-size: 12px; }}
QLabel[info="none"] {{ color: {P.text3}; font-size: 11px; padding: 6px 2px; }}
QFrame#InfoIconTile {{ background: {P.bg4}; border: 1px solid {P.line2}; border-radius: 9px; }}
QFrame#InfoError {{ background: {P.rgba(P.err, 0.10)}; border: 1px solid {P.rgba(P.err, 0.45)}; border-radius: 10px; }}
QLabel[info="error"] {{ color: {P.err}; }}
QTreeWidget#MetaTree {{
    background: {P.bg3}; border: 1px solid {P.line}; border-radius: 10px; padding: 4px;
}}
QTreeWidget#MetaTree::item {{ padding: 2px 4px; border-radius: 0; }}
QTreeWidget#MetaTree::item:hover {{ background: {P.bg4}; }}
QTreeWidget#MetaTree::item:selected {{ background: {P.rgba(P.accent, 0.16)}; color: {P.text}; }}
"""

    # ------------------------------------------------------------ public API

    def set_source(self, source, frame=None) -> None:
        """Show ``source`` (a MediaSource, or None for the empty state); ``frame`` adds per-frame details."""
        sig = self._signature(source)
        if source is not None and sig == self._sig and self._content is not None:
            # same clip and settings: only the per-frame rows change (cheap enough for playback)
            self._frame = frame
            self._update_frame_rows()
            return
        same_clip = source is not None and source is self._source
        self._source = source
        self._sig = sig
        self._info = getattr(source, "info", None) if source is not None else None
        self._frame = frame
        self._rebuild(keep_scroll=same_clip)

    @staticmethod
    def _signature(source) -> tuple:
        if source is None:
            return ()
        layer = getattr(source, "layer", None)
        return (id(source), id(getattr(source, "info", None)), getattr(layer, "key", ""),
                getattr(source, "fps_override", 0.0), getattr(source, "in_point", None),
                getattr(source, "out_point", None), getattr(source, "error", ""))

    def text(self) -> str:
        """Everything shown in the panel as plain text (what the copy button puts on the clipboard)."""
        lines: list[str] = []
        for title, rows in self._sections:
            lines.append(f"[{title}]")
            lines.extend(f"{k}: {v}" for k, v in rows)
            if title == "재생" and self._frame is not None and "cur" in self._frame_labels:
                cur = self._frame_labels["cur"]
                sub = cur.sub_label.text() if cur.sub_label is not None else ""
                lines.append(f"현재 프레임: {cur.text()}" + (f" ({sub})" if sub else ""))
            lines.append("")
        meta = self._info.metadata if self._info is not None else {}
        if meta:
            lines.append("[메타데이터]")
            lines.extend(f"{k}: {v}" for k, v in sorted(meta.items(), key=lambda kv: kv[0].lower()))
        return "\n".join(lines).strip() + "\n"

    # ------------------------------------------------------------ build

    def _rebuild(self, keep_scroll: bool = False) -> None:
        bar = self.scroll.verticalScrollBar()
        keep = bar.value() if keep_scroll else 0
        self._sections = []
        self._frame_labels = {}
        self._meta_items = []
        content = QWidget()
        content.setObjectName("InfoContent")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(12, 12, 12, 16)
        lay.setSpacing(0)
        self._lay = lay
        if self._source is None:
            self._build_empty(lay)
        else:
            self._build(lay)
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(content)
        self._content = content

        def restore_scroll():
            try:
                bar.setValue(keep)
            except RuntimeError:     # panel already destroyed
                pass

        QTimer.singleShot(0, restore_scroll)

    def _build_empty(self, lay: QVBoxLayout) -> None:
        from cocseq import icons

        lay.addStretch(1)
        ic = QLabel()
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(icons.pixmap("info", 30, PAL.text3, self.devicePixelRatioF() or 2.0))
        lay.addWidget(ic)
        lay.addSpacing(10)
        t = QLabel("미디어를 열면 정보가 표시됩니다")
        t.setProperty("info", "empty")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        lay.addStretch(2)

    def _section(self, lay: QVBoxLayout, title: str, first: bool = False, extra: QWidget | None = None) -> Card:
        if not first:
            lay.addSpacing(14)
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(6)
        row.addWidget(SectionTitle(title))
        row.addStretch(1)
        if extra is not None:
            row.addWidget(extra)
        lay.addLayout(row)
        lay.addSpacing(4)
        card = Card(margins=(12, 10, 12, 10), spacing=7)
        lay.addWidget(card)
        self._sections.append((title, []))
        return card

    def _row(self, card: Card, key: str, value: str, mono: bool = False, elide: bool = False,
             state: str = "", tooltip: str = "", sub: str = "", wrap: bool = False, record: bool = True) -> QLabel:
        w = QWidget(card)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        k = QLabel(key, w)
        k.setProperty("info", "key")
        k.setFixedWidth(KEY_WIDTH)
        k.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        h.addWidget(k, 0, Qt.AlignTop)
        if elide:
            v = _ElideLabel(value, Qt.ElideMiddle, w)
        else:
            v = QLabel(value, w)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.setWordWrap(wrap)
            if wrap:
                v.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.setProperty("info", state or ("mono" if mono else "value"))
        if tooltip:
            v.setToolTip(tooltip)
        v.sub_label = None
        if sub:
            box = QHBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(6)
            box.addWidget(v)
            s = QLabel(sub.strip(), w)
            s.setProperty("info", "sub")
            box.addWidget(s)
            v.sub_label = s
            box.addStretch(1)
            h.addLayout(box, 1)
        else:
            h.addWidget(v, 1)
        card.lay.addWidget(w)
        if record:
            self._sections[-1][1].append((key, value + (f" ({sub})" if sub else "")))
        return v

    def _build(self, lay: QVBoxLayout) -> None:
        src, info = self._source, self._info
        movie = src.kind == "movie"
        single = bool(getattr(src.seq, "single_file", "")) if src.seq is not None else False
        ext = os.path.splitext(src.path)[1].lstrip(".").upper() or "?"
        kind = "동영상" if movie else ("단일 이미지" if single else "이미지 시퀀스")

        if src.error:
            err = QFrame()
            err.setObjectName("InfoError")
            el = QHBoxLayout(err)
            el.setContentsMargins(12, 9, 12, 9)
            t = QLabel(src.error)
            t.setWordWrap(True)
            t.setProperty("info", "error")
            el.addWidget(t)
            lay.addWidget(err)
            lay.addSpacing(12)

        # ---- file
        card = self._section(lay, "파일", first=True)
        hero = QWidget(card)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(0, 0, 0, 2)
        hl.setSpacing(10)
        tile = QFrame(hero)
        tile.setObjectName("InfoIconTile")
        tile.setFixedSize(36, 36)
        tl = QVBoxLayout(tile)
        tl.setContentsMargins(0, 0, 0, 0)
        ic = QLabel(tile)
        ic.setAlignment(Qt.AlignCenter)
        from cocseq import icons

        ic.setPixmap(icons.pixmap("movie" if movie else ("image" if single else "sequence"), 18, PAL.accent,
                                  self.devicePixelRatioF() or 2.0))
        tl.addWidget(ic)
        hl.addWidget(tile)
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(1)
        name = _ElideLabel(src.name, Qt.ElideRight, hero)
        name.setProperty("info", "name")
        names.addWidget(name)
        kl = QLabel(f"{kind} · {ext}", hero)
        kl.setProperty("info", "kind")
        names.addWidget(kl)
        hl.addLayout(names, 1)
        card.lay.addWidget(hero)
        self._sections[-1][1].append(("이름", src.name))
        self._sections[-1][1].append(("종류", f"{kind} ({ext})"))
        sep = QFrame(card)
        sep.setProperty("class", "hline")
        sep.setFixedHeight(1)
        card.lay.addWidget(sep)

        self._row(card, "경로", src.display_path, elide=True)
        if info.file_size:
            if movie or single:
                self._row(card, "크기", human_bytes(info.file_size), mono=True)
            else:
                est = human_bytes(info.file_size * max(1, len(src.seq.frames) if src.seq else 1))
                self._row(card, "크기", human_bytes(info.file_size), mono=True, sub=f"프레임당 · 전체 약 {est}")
        if not single:
            self._row(card, "프레임 범위", f"{src.first} – {src.last}", mono=True)
            count = len(src.seq.frames) if (src.seq is not None and not movie) else src.length
            self._row(card, "프레임 수", f"{count:,}", mono=True)
        if not movie and not single:
            missing = src.missing
            if missing:
                self._row(card, "누락 프레임", f"{len(missing)}개 · {_frame_ranges(missing)}", state="warn",
                          wrap=True, tooltip=", ".join(str(f) for f in missing[:400]))
            else:
                self._row(card, "누락 프레임", "없음", state="ok")

        # ---- image
        card = self._section(lay, "이미지")
        w, h = info.width, info.height
        self._row(card, "해상도", f"{w} × {h}", mono=True, sub=_ratio(w, h))
        dw, dispw = info.data_window, info.display_window
        if dw and dispw and tuple(dw) != tuple(dispw) and any(dw):
            self._row(card, "디스플레이", _window(dispw), mono=True)
            self._row(card, "데이터 윈도우", _window(dw), mono=True)
        self._frame_labels["dw"] = self._row(card, "현재 데이터", "—", mono=True, record=False)
        self._frame_labels["dw"].parentWidget().setVisible(False)
        self._row(card, "픽셀 비율", f"{info.par:.3f}", mono=True, sub="아나모픽" if abs(info.par - 1.0) > 1e-3 else "")
        chans = info.channels or list(src.layer.channels)
        self._row(card, "채널", f"{len(chans)}개 · " + ", ".join(chans), wrap=True)
        self._row(card, "레이어", f"{len(src.layers)}개", mono=False)
        self._row(card, "픽셀 형식", _pixel_type(info))
        if info.compression:
            self._row(card, "압축", info.compression)
        if info.pix_fmt:
            self._row(card, "픽셀 포맷", info.pix_fmt, mono=True)
        self._row(card, "파일 색 공간", info.file_colorspace or "—")
        if info.subimages > 1:
            self._row(card, "파트", f"{info.subimages}개", mono=False)

        # ---- playback
        card = self._section(lay, "재생")
        fps = src.fps
        note = ""
        if src.fps_override:
            note = f"재정의 · 원본 {fps_label(info.fps)}" if info.fps else "재정의"
        elif not info.fps:
            note = "기본값"
        self._row(card, "프레임 속도", f"{fps_label(fps)} fps", mono=True, sub=note)
        length = src.length
        seconds = length / fps if fps else 0.0
        self._row(card, "길이", frames_to_timecode(length, fps), mono=True, sub=f"{seconds:.2f}초 · {length} 프레임")
        if info.timecode:
            self._row(card, "시작 타임코드", info.timecode, mono=True)
        lo, hi = src.range
        if src.in_point is not None or src.out_point is not None:
            self._row(card, "재생 구간", f"{lo} – {hi}", mono=True, sub=f"{hi - lo + 1} 프레임")
        self._frame_labels["cur"] = self._row(card, "현재 프레임", "—", mono=True, record=False, sub=" ")
        self._frame_labels["cur"].parentWidget().setVisible(False)

        # ---- codec
        if movie:
            card = self._section(lay, "코덱")
            self._row(card, "비디오", info.codec or "—", wrap=True)
            self._row(card, "픽셀 포맷", info.pix_fmt or "—", mono=True)
            self._row(card, "비트레이트", _bitrate(info.bitrate), mono=True)
            self._row(card, "오디오", info.audio_desc if info.has_audio else "없음",
                      mono=False, state="" if info.has_audio else "ok")

        # ---- layers
        count = QLabel(str(len(src.layers)))
        count.setProperty("info", "count")
        card = self._section(lay, "레이어", extra=count)
        card.lay.setSpacing(4)
        for layer in src.layers:
            self._layer_row(card, layer, layer is src.layer or layer.key == src.layer.key)

        # ---- metadata
        self._build_metadata(lay)
        self._update_frame_rows()
        lay.addStretch(1)

    def _layer_row(self, card: Card, layer, current: bool) -> None:
        w = QWidget(card)
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(8)
        dot = QLabel("●" if current else "○", w)
        dot.setStyleSheet(f"color: {PAL.accent if current else PAL.text3}; font-size: 9px;")
        dot.setFixedWidth(10)
        h.addWidget(dot)
        name = _ElideLabel(layer.name, Qt.ElideMiddle, w)
        name.setProperty("info", "value")
        h.addWidget(name, 1)
        short = [c.split(".")[-1] for c in layer.channels]
        chans = "".join(short) if all(len(c) == 1 for c in short) else ",".join(short)
        chip = QLabel(chans, w)
        chip.setProperty("info", "chip")
        chip.setToolTip(", ".join(layer.channels))
        h.addWidget(chip)
        if current:
            cur = QLabel("표시 중", w)
            cur.setProperty("info", "current")
            h.addWidget(cur)
        w.setToolTip(layer.label)
        card.lay.addWidget(w)
        self._sections[-1][1].append((layer.name, layer.label + ("  [표시 중]" if current else "")))

    def _build_metadata(self, lay: QVBoxLayout) -> None:
        meta = self._info.metadata or {}
        lay.addSpacing(14)
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 2, 0)
        row.addWidget(SectionTitle("메타데이터"))
        row.addStretch(1)
        count = QLabel(str(len(meta)))
        count.setProperty("info", "count")
        row.addWidget(count)
        self._meta_count = count
        lay.addLayout(row)
        lay.addSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        search = QLineEdit()
        search.setObjectName("MetaSearch")
        search.setPlaceholderText("메타데이터 검색")
        search.setClearButtonEnabled(True)
        search.addAction(_icon("search", 16, PAL.text3), QLineEdit.LeadingPosition)
        search.setText(self._filter)
        search.textChanged.connect(self._apply_filter)
        bar.addWidget(search, 1)
        copy = QPushButton("복사")
        copy.setIcon(_icon("notes", 16))
        copy.setIconSize(QSize(16, 16))
        copy.setCursor(Qt.PointingHandCursor)
        copy.setToolTip("패널의 모든 정보와 메타데이터를 텍스트로 클립보드에 복사")
        copy.clicked.connect(lambda: self._copy_all(copy))
        bar.addWidget(copy)
        lay.addLayout(bar)
        lay.addSpacing(8)

        tree = _MetaTree()
        key_font_w = 0
        fm_key = self.fontMetrics()
        mono = mono_font(8.5)
        for k in sorted(meta, key=lambda s: s.lower()):
            v = str(meta[k])
            one_line = " ".join(v.split())
            it = QTreeWidgetItem([k, one_line])
            it.setForeground(0, QColor(PAL.text2))
            it.setForeground(1, QColor(PAL.text))
            it.setFont(1, mono)
            it.setData(1, Qt.UserRole, v)
            it.setToolTip(0, k)
            it.setToolTip(1, v if len(v) < 2000 else v[:2000] + "…")
            tree.addTopLevelItem(it)
            self._meta_items.append(it)
            key_font_w = max(key_font_w, fm_key.horizontalAdvance(k))
        tree.set_key_width(key_font_w + 20)
        self._tree = tree
        lay.addWidget(tree)
        self._no_match = QLabel("일치하는 항목이 없습니다" if meta else "메타데이터가 없습니다")
        self._no_match.setProperty("info", "none")
        self._no_match.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._no_match)
        self._apply_filter(self._filter)

    # ------------------------------------------------------------ behaviour

    def _apply_filter(self, text: str) -> None:
        self._filter = text
        needle = text.strip().lower()
        shown = 0
        for it in self._meta_items:
            hit = not needle or needle in it.text(0).lower() or needle in str(it.data(1, Qt.UserRole)).lower()
            it.setHidden(not hit)
            shown += hit
        total = len(self._meta_items)
        self._tree.setVisible(shown > 0)
        self._no_match.setVisible(shown == 0)
        self._no_match.setText("일치하는 항목이 없습니다" if total else "메타데이터가 없습니다")
        self._meta_count.setText(f"{shown} / {total}" if needle else str(total))
        if shown:
            self._tree.fit_height()

    def _copy_all(self, button: QPushButton) -> None:
        QGuiApplication.clipboard().setText(self.text())
        button.setText("복사됨")
        button.setIcon(_icon("check", 16, PAL.ok))

        def restore():
            try:
                button.setText("복사")
                button.setIcon(_icon("notes", 16))
            except RuntimeError:
                pass

        QTimer.singleShot(1400, restore)

    def _update_frame_rows(self) -> None:
        fr = self._frame
        cur = self._frame_labels.get("cur")
        dw = self._frame_labels.get("dw")
        if cur is None or dw is None:
            return
        if fr is None:
            cur.parentWidget().setVisible(False)
            dw.parentWidget().setVisible(False)
            return
        src = self._source
        tc = frames_to_timecode(fr.frame_no - src.first, src.fps)
        cur.setText(str(fr.frame_no))
        missing = bool(getattr(fr, "missing", False))
        if cur.sub_label is not None:
            cur.sub_label.setText("누락된 프레임" if missing else tc)
            cur.sub_label.setProperty("info", "warn" if missing else "sub")
            cur.sub_label.style().unpolish(cur.sub_label)
            cur.sub_label.style().polish(cur.sub_label)
        cur.parentWidget().setVisible(True)
        info = self._info
        fdw = tuple(getattr(fr, "data_window", ()) or ())
        show_dw = bool(fdw) and any(fdw) and fdw != tuple(info.data_window) and not getattr(fr, "missing", False)
        if show_dw:
            dw.setText(_window(fdw))
        dw.parentWidget().setVisible(show_dw)
