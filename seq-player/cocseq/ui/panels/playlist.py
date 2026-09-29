"""Playlist of open clips with thumbnails."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                               QMenu, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from cocseq.theme import PAL, mono_font, ui_font
from cocseq.ui.widgets import IconButton, muted
from cocseq.utils import fps_label

ROLE_SOURCE = Qt.UserRole + 1
THUMB_W = 88
THUMB_H = 50


class _Delegate(QStyledItemDelegate):
    def __init__(self, panel: "PlaylistPanel"):
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, THUMB_H + 16)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        src = index.data(ROLE_SOURCE)
        if src is None:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        is_a = src is self.panel.current_a
        is_b = src in self.panel.current_b
        bg = PAL.qcolor("accent", 0.13) if is_a else (PAL.qcolor("bg4") if hover or selected else QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 9, 9)
        if is_a:
            p.setBrush(PAL.qcolor("accent"))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3, r.height() - 20), 1.5, 1.5)

        # Thumbnail
        tr = QRectF(r.left() + 10, r.top() + (r.height() - THUMB_H) / 2, THUMB_W, THUMB_H)
        path = QPainterPath()
        path.addRoundedRect(tr, 6, 6)
        p.setClipPath(path)
        p.fillRect(tr, PAL.qcolor("bg0"))
        img: QImage | None = self.panel.thumbs.get(src.id)
        if img is not None and not img.isNull():
            k = min(tr.width() / img.width(), tr.height() / img.height())
            iw, ih = img.width() * k, img.height() * k
            p.drawImage(QRectF(tr.center().x() - iw / 2, tr.center().y() - ih / 2, iw, ih), img)
        else:
            from cocseq import icons

            pm = icons.pixmap("movie" if src.kind == "movie" else "sequence", 20, PAL.text3)
            p.drawPixmap(QPointF(tr.center().x() - 10, tr.center().y() - 10), pm)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(tr, 6, 6)

        # Badges on the thumbnail
        bx = tr.left() + 4
        for label, color, on in (("A", PAL.accent, is_a), ("B", PAL.b, is_b)):
            if on:
                br = QRectF(bx, tr.top() + 4, 16, 16)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
                p.drawRoundedRect(br, 4, 4)
                p.setPen(QColor("white"))
                p.setFont(ui_font(7.5, QFont.Bold))
                p.drawText(br, Qt.AlignCenter, label)
                bx += 19

        # Text
        x = tr.right() + 12
        tw = r.right() - x - 8
        p.setFont(ui_font(9.5, QFont.DemiBold))
        fm = QFontMetricsF(p.font())
        p.setPen(PAL.qcolor("text"))
        name = fm.elidedText(src.name, Qt.ElideMiddle, tw)
        p.drawText(QRectF(x, r.top() + 9, tw, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
        p.setFont(mono_font(7.8))
        fm2 = QFontMetricsF(p.font())
        w, h = src.resolution
        line1 = f"{src.first}–{src.last}  ·  {src.length}f  ·  {fps_label(src.fps)}fps"
        line2 = f"{w}×{h}  ·  {src.layer.name if len(src.layers) > 1 else src.info.pixel_type}"
        if src.kind == "movie":
            line2 = f"{w}×{h}  ·  {src.info.codec.split(' ')[0] if src.info.codec else 'movie'}"
        p.setPen(PAL.qcolor("text3"))
        p.drawText(QRectF(x, r.top() + 29, tw, 14), Qt.AlignLeft | Qt.AlignVCenter, fm2.elidedText(line1, Qt.ElideRight, tw))
        p.drawText(QRectF(x, r.top() + 44, tw, 14), Qt.AlignLeft | Qt.AlignVCenter, fm2.elidedText(line2, Qt.ElideRight, tw))
        warn = ""
        if src.error:
            warn = "!"
        elif src.missing:
            warn = f"누락 {len(src.missing)}"
        if warn:
            p.setFont(ui_font(7.5, QFont.Bold))
            ww = QFontMetricsF(p.font()).horizontalAdvance(warn) + 10
            wr = QRectF(r.right() - ww - 8, r.top() + 10, ww, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(PAL.qcolor("err", 0.2))
            p.drawRoundedRect(wr, 5, 5)
            p.setPen(PAL.qcolor("err"))
            p.drawText(wr, Qt.AlignCenter, warn)
        p.restore()


class PlaylistPanel(QWidget):
    activated = Signal(object)             # source to show as A
    setB = Signal(object)                  # source to compare as B (None clears)
    removeRequested = Signal(object)
    reloadRequested = Signal(object)
    revealRequested = Signal(object)
    copyPathRequested = Signal(object)
    attachAudioRequested = Signal(object)
    openRequested = Signal()
    openFolderRequested = Signal()
    filesDropped = Signal(list)
    orderChanged = Signal(list)            # sources in new order
    clearRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_a = None
        self.current_b: list = []
        self.thumbs: dict[int, QImage] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("클립 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        b_open = IconButton("file-plus", "파일 열기 (Ctrl+O)", size=17)
        b_open.clicked.connect(self.openRequested)
        b_folder = IconButton("folder-open", "폴더 열기 (Ctrl+Shift+O)", size=17)
        b_folder.clicked.connect(self.openFolderRequested)
        top.addWidget(b_open)
        top.addWidget(b_folder)
        lay.addLayout(top)

        self.list = QListWidget()
        self.list.setItemDelegate(_Delegate(self))
        self.list.setMouseTracking(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; }"
                                "QListWidget::item { background: transparent; }")
        self.list.itemClicked.connect(self._clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.model().rowsMoved.connect(lambda *a: self.orderChanged.emit(self.sources()))
        lay.addWidget(self.list, 1)

        self.empty = muted("열린 클립이 없습니다.\n파일이나 폴더를 창에 끌어다 놓으세요.", "faint")
        self.empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.empty)
        self.hint = muted("클릭: 보기 · Alt+클릭: B로 비교 · 끌어서 순서 변경", "faint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.setAcceptDrops(True)
        self._refresh_empty()

    # ---------------------------------------------------------------- items

    def sources(self) -> list:
        return [self.list.item(i).data(ROLE_SOURCE) for i in range(self.list.count())]

    def add_source(self, src) -> None:
        item = QListWidgetItem()
        item.setData(ROLE_SOURCE, src)
        item.setToolTip(src.display_path)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        self.list.addItem(item)
        self._refresh_empty()

    def remove_source(self, src) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_SOURCE) is src:
                self.list.takeItem(i)
                break
        self.thumbs.pop(src.id, None)
        self._refresh_empty()

    def clear(self) -> None:
        self.list.clear()
        self.thumbs.clear()
        self._refresh_empty()

    def set_thumbnail(self, source_id: int, img: QImage) -> None:
        self.thumbs[source_id] = img
        self.list.viewport().update()

    def set_current(self, a, b_list: list) -> None:
        self.current_a = a
        self.current_b = [b for b in b_list if b is not None]
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_SOURCE) is a:
                self.list.setCurrentRow(i)
                break
        self.list.viewport().update()

    def refresh(self) -> None:
        self.list.viewport().update()

    def _refresh_empty(self) -> None:
        has = self.list.count() > 0
        self.empty.setVisible(not has)
        self.hint.setVisible(has)
        self.list.setVisible(has)

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            src = it.data(ROLE_SOURCE)
            it.setHidden(bool(text) and text not in src.name.lower() and text not in src.display_path.lower())

    # ---------------------------------------------------------------- interaction

    def _clicked(self, item: QListWidgetItem) -> None:
        from PySide6.QtWidgets import QApplication

        src = item.data(ROLE_SOURCE)
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            self.setB.emit(None if src in self.current_b else src)
        else:
            self.activated.emit(src)

    def _menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        src = item.data(ROLE_SOURCE)
        from cocseq import icons

        m = QMenu(self)
        m.addAction(icons.icon("play", size=16), "보기 (A)", lambda: self.activated.emit(src))
        if src in self.current_b:
            m.addAction(icons.icon("b-letter", size=16), "B 비교 해제", lambda: self.setB.emit(None))
        else:
            m.addAction(icons.icon("b-letter", size=16), "B로 비교", lambda: self.setB.emit(src))
        m.addSeparator()
        m.addAction(icons.icon("refresh", size=16), "다시 불러오기", lambda: self.reloadRequested.emit(src))
        m.addAction(icons.icon("audio", size=16), "오디오 파일 연결…", lambda: self.attachAudioRequested.emit(src))
        m.addAction(icons.icon("folder-open", size=16), "탐색기에서 폴더 열기", lambda: self.revealRequested.emit(src))
        m.addAction(icons.icon("link", size=16), "경로 복사", lambda: self.copyPathRequested.emit(src))
        m.addSeparator()
        m.addAction(icons.icon("close", size=16), "닫기", lambda: self.removeRequested.emit(src))
        m.addAction(icons.icon("trash", size=16), "모두 닫기", self.clearRequested.emit)
        m.exec(self.list.viewport().mapToGlobal(pos))

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
