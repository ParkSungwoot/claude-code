"""Application log: a buffering logging handler and a panel that shows it.

``install_log_handler()`` hooks the root logger once. Records can come from any
thread; they are buffered (last 2000) and forwarded to the GUI thread through a
Qt signal on a module-level bridge object, so every LogPanel (including ones
created later, which replay the buffer) shows them.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from cocseq.theme import MONO_FONT, PAL, mono_font

__all__ = ["LogPanel", "install_log_handler", "LogEntry", "MAX_RECORDS"]

MAX_RECORDS = 2000
_WARN_PATH = re.compile(r"^(.*[\\/])([^\\/]+:\d+:)")

LEVELS = (  # combo label, minimum level
    ("전체", logging.NOTSET),
    ("정보", logging.INFO),
    ("경고", logging.WARNING),
    ("오류", logging.ERROR),
)


@dataclass(frozen=True)
class LogEntry:
    seq: int
    created: float
    levelno: int
    levelname: str
    logger: str
    message: str

    def line(self) -> str:
        return f"{time.strftime('%H:%M:%S', time.localtime(self.created))}  {_level_tag(self.levelno)}  {self.logger}: {self.message}"


def _level_tag(levelno: int) -> str:
    if levelno >= logging.CRITICAL:
        name = "CRIT"
    elif levelno >= logging.ERROR:
        name = "ERROR"
    elif levelno >= logging.WARNING:
        name = "WARN"
    elif levelno >= logging.INFO:
        name = "INFO"
    else:
        name = "DEBUG"
    return f"{name:<5}"


def _level_color(levelno: int) -> str:
    if levelno >= logging.ERROR:
        return PAL.err
    if levelno >= logging.WARNING:
        return PAL.warn
    if levelno >= logging.INFO:
        return PAL.text2
    return PAL.text3


# ------------------------------------------------------------------ handler + bridge


class _Bridge(QObject):
    record = Signal(object)      # LogEntry
    cleared = Signal()


_lock = threading.Lock()
_buffer: deque[LogEntry] = deque(maxlen=MAX_RECORDS)
_bridge: _Bridge | None = None
_handler: "_BufferHandler | None" = None
_seq = 0


class _BufferHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.NOTSET)
        self._fmt = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        global _seq
        try:
            msg = record.getMessage()
            if record.exc_info:
                msg = f"{msg}\n{self._fmt.formatException(record.exc_info)}"
            elif record.stack_info:
                msg = f"{msg}\n{record.stack_info}"
            name = record.name
            if name == "py.warnings":
                # "/long/path/file.py:12: Category: text\n  source line" -> "file.py:12: Category: text"
                first = msg.strip().splitlines()[0] if msg.strip() else msg
                msg = _WARN_PATH.sub(r"\2", first)
            with _lock:
                _seq += 1
                entry = LogEntry(_seq, record.created, record.levelno, record.levelname, name, msg.rstrip())
                _buffer.append(entry)
            bridge = _bridge
            if bridge is not None:
                bridge.record.emit(entry)          # queued to the GUI thread when emitted elsewhere
        except RuntimeError:
            pass                                    # bridge already destroyed (shutdown)
        except Exception:
            self.handleError(record)


def install_log_handler() -> None:
    """Attach the buffering handler to the root logger (idempotent) and capture warnings."""
    global _bridge, _handler
    with _lock:
        if _bridge is None:
            _bridge = _Bridge()
            app = QGuiApplication.instance()
            if app is not None and _bridge.thread() is not app.thread():
                _bridge.moveToThread(app.thread())
        if _handler is None:
            _handler = _BufferHandler()
    root = logging.getLogger()
    if _handler not in root.handlers:
        root.addHandler(_handler)
        # Only on first install, so a level chosen later by the app (e.g. DEBUG) is kept.
        root.setLevel(logging.INFO)
    logging.captureWarnings(True)


def buffered_entries() -> list[LogEntry]:
    with _lock:
        return list(_buffer)


def clear_buffer() -> None:
    with _lock:
        _buffer.clear()
    if _bridge is not None:
        _bridge.cleared.emit()


# ------------------------------------------------------------------ panel


class LogPanel(QWidget):
    """Read-only, colour-coded view of the application log with a level filter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogPanel")
        install_log_handler()
        self._min_level = logging.NOTSET
        self._shown = 0
        self._pending: list[LogEntry] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(40)
        self._flush_timer.timeout.connect(self._flush)
        self.setStyleSheet(
            f"""
QPlainTextEdit#LogView {{
    background: {PAL.bg1}; border: 1px solid {PAL.line}; border-radius: 10px;
    padding: 6px 4px 6px 8px; font-family: "{MONO_FONT}"; font-size: 11px; color: {PAL.text2};
    selection-background-color: {PAL.rgba(PAL.accent, 0.35)}; selection-color: {PAL.text};
}}
QPlainTextEdit#LogView:focus {{ border-color: {PAL.line2}; background: {PAL.bg1}; }}
QLabel#LogCount {{ color: {PAL.text3}; font-size: 11px; }}
"""
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        self.level = QComboBox()
        for label, lv in LEVELS:
            self.level.addItem(label, lv)
        self.level.setToolTip("표시할 최소 수준")
        self.level.setCursor(Qt.PointingHandCursor)
        self.level.setMinimumWidth(84)
        self.level.currentIndexChanged.connect(self._level_changed)
        bar.addWidget(self.level)
        self.count = QLabel("")
        self.count.setObjectName("LogCount")
        bar.addWidget(self.count)
        bar.addStretch(1)
        self.copy_btn = self._button("복사", "notes", "보이는 로그를 클립보드에 복사")
        self.copy_btn.clicked.connect(self._copy)
        bar.addWidget(self.copy_btn)
        self.clear_btn = self._button("지우기", "trash", "로그 지우기")
        self.clear_btn.clicked.connect(clear_buffer)
        bar.addWidget(self.clear_btn)
        lay.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.view.setMaximumBlockCount(MAX_RECORDS)
        self.view.setPlaceholderText("아직 기록된 로그가 없습니다")
        self.view.setFont(mono_font(8.5))
        self.view.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        lay.addWidget(self.view, 1)

        self._formats = {}
        _bridge.record.connect(self._on_record)
        _bridge.cleared.connect(self._on_cleared)
        self._rerender()

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _button(text: str, icon_name: str, tip: str) -> QPushButton:
        from cocseq import icons

        b = QPushButton(text)
        b.setProperty("variant", "ghost")
        b.setIcon(icons.icon(icon_name, size=16))
        b.setIconSize(QSize(16, 16))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _fmt(self, color: str, bold: bool = False) -> QTextCharFormat:
        key = (color, bold)
        f = self._formats.get(key)
        if f is None:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(600)
            self._formats[key] = f
        return f

    def _visible(self, e: LogEntry) -> bool:
        return e.levelno >= self._min_level

    def _append(self, entries: list[LogEntry]) -> None:
        if not entries:
            return
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cur = QTextCursor(self.view.document())
        cur.movePosition(QTextCursor.End)
        cur.beginEditBlock()
        faint = self._fmt(PAL.text3)
        name_fmt = self._fmt(PAL.text3)
        first = self.view.document().isEmpty()
        for e in entries:
            if first:
                first = False
            else:
                cur.insertBlock()
            col = _level_color(e.levelno)
            cur.insertText(time.strftime("%H:%M:%S", time.localtime(e.created)) + "  ", faint)
            cur.insertText(_level_tag(e.levelno) + "  ", self._fmt(col, bold=e.levelno >= logging.WARNING))
            name = e.logger[7:] if e.logger.startswith("cocseq.") else e.logger
            cur.insertText(name + ": ", name_fmt)
            # a traceback stays inside this block (line separators, not new blocks)
            cur.insertText(e.message.replace("\n", "\u2028"), self._fmt(col))
        cur.endEditBlock()
        self._shown += len(entries)
        self._update_count()
        if at_bottom:
            bar.setValue(bar.maximum())

    def _rerender(self) -> None:
        self.view.clear()
        self._shown = 0
        self._pending.clear()
        self._append([e for e in buffered_entries() if self._visible(e)])
        self._update_count()
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _update_count(self) -> None:
        total = len(_buffer)
        shown = min(self._shown, total)
        self.count.setText(f"{shown:,}줄" if shown == total else f"{shown:,} / {total:,}줄")

    # ------------------------------------------------------------ slots

    def _on_record(self, entry: LogEntry) -> None:
        if self._visible(entry):
            self._pending.append(entry)
            if not self._flush_timer.isActive():
                self._flush_timer.start()
        else:
            self._update_count()

    def _flush(self) -> None:
        batch, self._pending = self._pending, []
        batch.sort(key=lambda e: e.seq)       # records from other threads arrive queued
        self._append(batch)

    def _on_cleared(self) -> None:
        self.view.clear()
        self._shown = 0
        self._pending.clear()
        self._update_count()

    def _level_changed(self, _index: int) -> None:
        self._min_level = int(self.level.currentData() or 0)
        self._rerender()

    def _copy(self) -> None:
        text = "\n".join(e.line() for e in buffered_entries() if self._visible(e))
        QGuiApplication.clipboard().setText(text)
        self.copy_btn.setText("복사됨")

        def restore():
            try:
                self.copy_btn.setText("복사")
            except RuntimeError:
                pass

        QTimer.singleShot(1400, restore)

    # ------------------------------------------------------------ public

    def set_level(self, levelno: int) -> None:
        """Show records at or above ``levelno`` (logging.NOTSET shows everything)."""
        for i in range(self.level.count()):
            if int(self.level.itemData(i)) == levelno:
                self.level.setCurrentIndex(i)
                return

    def plain_text(self) -> str:
        return "\n".join(e.line() for e in buffered_entries() if self._visible(e))

