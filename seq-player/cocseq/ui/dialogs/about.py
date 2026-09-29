"""About dialog: logo, version, library versions and open source credits."""

from __future__ import annotations

import platform

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QRadialGradient
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from cocseq import APP_NAME, __version__
from cocseq.theme import PAL
from cocseq.ui.widgets import Segmented

DESCRIPTION = "이미지 시퀀스·동영상 리뷰 플레이어"

CREDITS = [
    ("Pretendard · JetBrains Mono", "SIL OFL 1.1", "앱에 포함된 글꼴 — UI 글꼴과 숫자·타임코드용 고정폭 글꼴"),
    ("OpenImageIO", "Apache-2.0", "EXR, DPX, TIFF 등 이미지 읽기·쓰기"),
    ("OpenColorIO", "BSD-3-Clause", "OCIO 컬러 관리"),
    ("FFmpeg · PyAV", "LGPL / GPL", "동영상·오디오 디코딩과 인코딩 — libx264를 포함한 빌드는 GPL"),
    ("Qt · PySide6", "LGPLv3", "UI 프레임워크"),
]


def library_versions(gl_info: str = "") -> list[tuple[str, str]]:
    """(name, version) of the libraries the app is built on; missing ones say so."""
    rows: list[tuple[str, str]] = []
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        rows.append(("Qt / PySide6", f"{qVersion()} / {PySide6.__version__}"))
    except Exception:
        rows.append(("Qt / PySide6", "알 수 없음"))
    try:
        import OpenImageIO as oiio

        rows.append(("OpenImageIO", str(getattr(oiio, "__version__", "") or getattr(oiio, "VERSION_STRING", ""))))
    except Exception:
        rows.append(("OpenImageIO", "없음"))
    try:
        import PyOpenColorIO as ocio

        v = getattr(ocio, "__version__", "") or (ocio.GetVersion() if hasattr(ocio, "GetVersion") else "")
        rows.append(("OpenColorIO", str(v)))
    except Exception:
        rows.append(("OpenColorIO", "없음"))
    try:
        import av

        ff = getattr(av, "ffmpeg_version_info", "")
        rows.append(("FFmpeg (PyAV)", f"{ff} · PyAV {av.__version__}" if ff else f"PyAV {av.__version__}"))
    except Exception:
        rows.append(("FFmpeg (PyAV)", "없음"))
    try:
        import numpy

        rows.append(("NumPy", numpy.__version__))
    except Exception:
        rows.append(("NumPy", "없음"))
    rows.append(("Python", platform.python_version()))
    if gl_info:
        rows.append(("OpenGL", gl_info))
    try:
        rows.append(("운영체제", f"{platform.system()} {platform.release()}".strip()))
    except Exception:
        pass
    return rows


def _qss() -> str:
    P = PAL
    return f"""
QLabel#AbName {{ font-size: 21px; font-weight: 700; color: {P.text}; }}
QLabel#AbDesc {{ color: {P.text2}; font-size: 12.5px; }}
QLabel#AbVersion {{
    background: {P.rgba(P.accent, 0.14)};
    color: {P.accent};
    border-radius: 6px;
    padding: 2px 8px;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 11px;
    font-weight: 600;
}}
QFrame#AbCard {{
    background: {P.bg2};
    border: 1px solid {P.line};
    border-radius: 12px;
}}
QFrame#AbSep {{ background: {P.line}; border: none; min-height: 1px; max-height: 1px; }}
QLabel#AbKey {{ color: {P.text2}; font-size: 12px; }}
QLabel#AbVal {{ color: {P.text}; font-family: "JetBrains Mono", "Consolas"; font-size: 11px; }}
QLabel#AbLib {{ color: {P.text}; font-size: 12.5px; font-weight: 600; }}
QLabel#AbLibDesc {{ color: {P.text3}; font-size: 11px; }}
QLabel#AbLicense {{
    background: {P.bg3};
    border: 1px solid {P.line2};
    color: {P.text2};
    border-radius: 6px;
    padding: 1px 7px;
    font-family: "JetBrains Mono", "Consolas";
    font-size: 10px;
}}
QLabel#AbNote {{ color: {P.text3}; font-size: 11px; }}
QWidget#AbFooter {{ background: {P.bg1}; border-top: 1px solid {P.line}; }}
"""


class _Hero(QWidget):
    """Logo, name and version over a soft accent glow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from cocseq import icons

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 8)
        v.setSpacing(0)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(84))
        logo.setFixedSize(84, 84)
        logo.setAlignment(Qt.AlignCenter)
        v.addWidget(logo, 0, Qt.AlignHCenter)
        v.addSpacing(12)
        name = QLabel(APP_NAME)
        name.setObjectName("AbName")
        name.setAlignment(Qt.AlignCenter)
        v.addWidget(name)
        v.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("AbVersion")
        row.addWidget(ver)
        desc = QLabel(DESCRIPTION)
        desc.setObjectName("AbDesc")
        row.addWidget(desc)
        row.addStretch(1)
        v.addLayout(row)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, 64)
        g = QRadialGradient(c, 190)
        acc = QColor(PAL.accent)
        for stop, a in ((0.0, 0.20), (0.45, 0.06), (1.0, 0.0)):
            col = QColor(acc)
            col.setAlphaF(a)
            g.setColorAt(stop, col)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QRectF(c.x() - 190, c.y() - 190, 380, 380))


def _card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("AbCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 6, 16, 6)
    lay.setSpacing(0)
    return card, lay


def _sep() -> QFrame:
    s = QFrame()
    s.setObjectName("AbSep")
    s.setFixedHeight(1)
    return s


class AboutDialog(QDialog):
    def __init__(self, parent=None, gl_info: str = ""):
        super().__init__(parent)
        self._versions = library_versions(gl_info)
        self.setWindowTitle(f"{APP_NAME} 정보")
        self.setModal(True)
        self.resize(520, 560)
        self.setMinimumSize(460, 500)
        self.setStyleSheet(_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(_Hero())

        tabs = Segmented([("versions", "구성 요소"), ("credits", "오픈소스 라이선스")])
        for key in ("versions", "credits"):
            tabs.button(key).setMinimumWidth(110)
        th = QHBoxLayout()
        th.setContentsMargins(24, 6, 24, 10)
        th.addStretch(1)
        th.addWidget(tabs)
        th.addStretch(1)
        root.addLayout(th)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._versions_page())
        self.stack.addWidget(self._credits_page())
        root.addWidget(self.stack, 1)
        tabs.changed.connect(lambda k: self.stack.setCurrentIndex(0 if k == "versions" else 1))
        self.tabs = tabs

        footer = QWidget()
        footer.setObjectName("AbFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 12)
        fl.setSpacing(8)
        from cocseq import icons

        self.btn_copy = QPushButton("정보 복사")
        self.btn_copy.setProperty("variant", "ghost")
        self.btn_copy.setIcon(icons.icon("link", size=16))
        self.btn_copy.setIconSize(QSize(15, 15))
        self.btn_copy.setToolTip("버전 정보를 클립보드에 복사합니다 (버그 제보용)")
        self.btn_copy.setAutoDefault(False)
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self.copy_info)
        fl.addWidget(self.btn_copy)
        fl.addStretch(1)
        close = QPushButton("닫기")
        close.setProperty("variant", "primary")
        close.setMinimumWidth(86)
        close.setDefault(True)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        fl.addWidget(close)
        root.addWidget(footer)

    # ------------------------------------------------------------ pages

    def _versions_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 0, 24, 18)
        v.setSpacing(0)
        card, lay = _card()
        for i, (k, val) in enumerate(self._versions):
            if i:
                lay.addWidget(_sep())
            row = QHBoxLayout()
            row.setContentsMargins(0, 6, 0, 6)
            row.setSpacing(16)
            kl = QLabel(k)
            kl.setObjectName("AbKey")
            vl = QLabel(val)
            vl.setObjectName("AbVal")
            vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setWordWrap(len(val) > 44)
            vl.setToolTip(val)
            row.addWidget(kl, 0, Qt.AlignTop if len(val) > 44 else Qt.AlignVCenter)
            row.addWidget(vl, 1)
            lay.addLayout(row)
        v.addWidget(card)
        v.addStretch(1)
        return self._scroll(page)

    def _credits_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(24, 0, 24, 6)
        v.setSpacing(8)
        card, lay = _card()
        for i, (name, lic, desc) in enumerate(CREDITS):
            if i:
                lay.addWidget(_sep())
            box = QVBoxLayout()
            box.setContentsMargins(0, 6, 0, 6)
            box.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(8)
            n = QLabel(name)
            n.setObjectName("AbLib")
            top.addWidget(n)
            top.addStretch(1)
            badge = QLabel(lic)
            badge.setObjectName("AbLicense")
            top.addWidget(badge)
            box.addLayout(top)
            d = QLabel(desc)
            d.setObjectName("AbLibDesc")
            d.setWordWrap(True)
            box.addWidget(d)
            lay.addLayout(box)
        v.addWidget(card)
        note = QLabel("각 구성 요소는 해당 라이선스를 따릅니다 · 글꼴 라이선스 전문은 assets/fonts에 있습니다")
        note.setObjectName("AbNote")
        note.setWordWrap(True)
        note.setContentsMargins(4, 0, 4, 0)
        v.addWidget(note)
        v.addStretch(1)
        return self._scroll(page)

    @staticmethod
    def _scroll(page: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        return sa

    # ------------------------------------------------------------ actions

    def info_text(self) -> str:
        lines = [f"{APP_NAME} {__version__}"]
        lines += [f"{k}: {v}" for k, v in self._versions]
        return "\n".join(lines)

    def copy_info(self) -> None:
        QGuiApplication.clipboard().setText(self.info_text())
        self.btn_copy.setText("복사됨")
        QTimer.singleShot(1500, self.btn_copy, lambda: self.btn_copy.setText("정보 복사"))
