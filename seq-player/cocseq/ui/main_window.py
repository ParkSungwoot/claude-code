"""The main window: wires media, cache, playback, viewer, timeline and panels together."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from PySide6.QtCore import QByteArray, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QSizePolicy, QSplitter, QStackedWidget, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from cocseq import APP_NAME, SESSION_EXT, __version__, hotkeys, icons, theme
from cocseq.annotations import Shape
from cocseq.color.ocio_mgr import ColorManager
from cocseq.media.audio import AudioEngine, AudioLoader
from cocseq.media.cache import FrameCache, Prefetcher, ThumbnailService, window_frames
from cocseq.media.frame import Frame
from cocseq.media.seqscan import find_version, is_audio, is_media, scan_directory
from cocseq.media.source import MediaSource
from cocseq.playback import Playback
from cocseq.prefs import PrefsStore
from cocseq.theme import PAL, mono_font, ui_font
from cocseq.ui.panels.annotate import AnnotatePanel, ToolBar
from cocseq.ui.panels.color import ColorPanel, fill_colorspace_combo
from cocseq.ui.panels.compare import ComparePanel
from cocseq.ui.panels.env import EnvPanel
from cocseq.ui.panels.playlist import PlaylistPanel
from cocseq.ui.timeline import ThumbPopup, Timeline
from cocseq.ui.transport import Transport
from cocseq.ui.widgets import IconButton, PanelHeader, ScrubField, Segmented
from cocseq.utils import format_frame, fps_label, frames_to_timecode, human_bytes
from cocseq.viewer.gl_viewer import COMPARE_MODES, SlotInput, ViewerWidget

log = logging.getLogger(__name__)

PANELS = [
    ("playlist", "플레이리스트", "playlist"),
    ("color", "색 보정", "palette"),
    ("compare", "비교", "compare"),
    ("annotate", "주석", "pen"),
    ("info", "미디어 정보", "info"),
    ("scopes", "스코프", "histogram"),
    ("area", "영역 색 정보", "color-area"),
    ("env", "환경 맵", "globe"),
    ("logs", "로그", "terminal"),
]
CHANNEL_KEYS = [("rgb", "RGB"), ("r", "R"), ("g", "G"), ("b", "B"), ("a", "A"), ("luma", "L")]
BACKGROUNDS = [("dark", "어두운 회색"), ("black", "검정"), ("gray", "회색 18%"), ("checker", "체커보드"),
               ("custom", "사용자 색…")]
ASPECTS = [("", "없음"), ("16:9", "16:9"), ("1.85", "1.85:1"), ("2.39", "2.39:1"), ("4:3", "4:3"),
           ("1:1", "1:1"), ("9:16", "9:16 (세로)")]
MEDIA_FILTER = ("미디어 (*.exr *.dpx *.cin *.tif *.tiff *.png *.jpg *.jpeg *.tga *.bmp *.hdr *.psd *.webp *.jp2 "
                "*.sgi *.iff *.pic *.mov *.mp4 *.m4v *.avi *.mkv *.mxf *.webm *.gif *.mpg *.mpeg *.ts "
                f"*{SESSION_EXT});;모든 파일 (*)")


class MainWindow(QMainWindow):
    def __init__(self, store: PrefsStore, software_gl: bool = False):
        super().__init__()
        self.store = store
        self.prefs = store.prefs
        self.software_gl = software_gl
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon() if hasattr(icons, "app_icon") else icons.icon("logo-mark"))
        self.setAcceptDrops(True)
        self.resize(1480, 900)
        self.setMinimumSize(760, 480)

        self.sources: list[MediaSource] = []
        self.a: MediaSource | None = None
        self.compare_slots: list = [None, None, None]
        self.compare_mode = "A"
        self.compare_align = self.prefs.compare_align
        self.compare_offset = 0
        self.session_path = ""
        self.gl_info = ""
        self._last_frames: dict[int, Frame] = {}
        self._presentation = False
        self._pre_presentation_state = None
        self._prefetch_sig = None
        self._scrub_resume = 0
        self._hover_frame = -1

        self._init_services()
        self._build_ui()
        self._build_actions()
        self._build_menus()
        self.apply_prefs(initial=True)
        self._update_all()

        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(250)
        self._cache_timer.timeout.connect(self._on_cache_timer)
        self._cache_timer.start()

    # ================================================================ services

    def _init_services(self) -> None:
        p = self.prefs
        self.colors = ColorManager()
        if not self.colors.load(p.ocio_config, p.ocio_prefer_env):
            log.error("OCIO: %s", self.colors.error)
        self.cache = FrameCache(int(p.cache_gb * 1024 ** 3))
        self.prefetch = Prefetcher(self.cache, p.reader_threads)
        self.prefetch.frameLoaded.connect(self._on_frame_loaded)
        self.thumbs = ThumbnailService(self.cache)
        self.thumbs.ready.connect(self._on_thumb)
        self.audio = AudioEngine()
        self.audio.error.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.audio_loader = AudioLoader()
        self.audio_loader.loaded.connect(self._on_audio_loaded)
        self.playback = Playback(self)
        pb = self.playback
        pb.frameChanged.connect(self._on_frame_changed)
        pb.stateChanged.connect(self._on_play_state)
        pb.measuredFps.connect(lambda f: self.transport.set_actual_fps(f))
        pb.loopModeChanged.connect(self._on_loop_mode)
        pb.fpsChanged.connect(self._on_fps_changed)
        pb.rangeChanged.connect(self._on_range_changed)
        pb.reachedEnd.connect(self._on_reached_end)
        pb.is_ready = self._is_ready
        pb.on_start = self._audio_start
        pb.on_stop = self._audio_stop

    # ================================================================ UI

    def _build_ui(self) -> None:
        self._build_toolbar()
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        body.addWidget(self.splitter, 1)

        # Viewer with floating drawing tools
        self.viewer_box = QWidget()
        vb = QVBoxLayout(self.viewer_box)
        vb.setContentsMargins(0, 0, 0, 0)
        self.viewer = ViewerWidget(self.viewer_box)
        self.viewer.set_color_manager(self.colors)
        vb.addWidget(self.viewer)
        self.draw_bar = ToolBar(self.viewer_box)
        self.draw_bar.toolChosen.connect(self.set_tool)
        self.draw_bar.undo.connect(self.annotation_undo)
        self.draw_bar.redo.connect(self.annotation_redo)
        self.draw_bar.clearFrame.connect(self.annotation_clear_frame)
        self.draw_bar.colorClicked.connect(lambda: self.show_panel("annotate"))
        self.draw_bar.adjustSize()
        self.viewer_box.installEventFilter(self)
        self.splitter.addWidget(self.viewer_box)

        v = self.viewer
        v.pixelProbed.connect(self._on_pixel)
        v.areaSelected.connect(self._on_area)
        v.zoomChanged.connect(self._on_zoom_changed)
        v.shapeFinished.connect(self._on_shape)
        v.filesDropped.connect(self.open_paths)
        v.scrubRequested.connect(lambda n: self.playback.seek(self.playback.frame + n))
        v.contextMenuRequested.connect(self._viewer_menu)
        v.wipeChanged.connect(lambda: self.compare_panel.sync_wipe(self.viewer))
        v.glReady.connect(self._on_gl_ready)
        v.envChanged.connect(lambda: self.env_panel.sync())
        v.displaySample.connect(self._on_display_sample)

        # Side panel
        self.side = QWidget()
        self.side.setObjectName("SidePanel")
        self.side.setAttribute(Qt.WA_StyledBackground, True)
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.side_header = PanelHeader("")
        b_close = IconButton("close", "패널 닫기 (Tab)", size=15)
        b_close.clicked.connect(lambda: self.set_side_visible(False))
        self.side_header.add(b_close)
        sl.addWidget(self.side_header)
        self.stack = QStackedWidget()
        sl.addWidget(self.stack, 1)
        self.side.setMinimumWidth(270)
        self.side.setMaximumWidth(560)
        self.splitter.addWidget(self.side)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self._build_panels()

        # Rail
        self.rail = QFrame()
        self.rail.setProperty("class", "rail")
        self.rail.setFixedWidth(50)
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(6, 8, 6, 8)
        rl.setSpacing(4)
        self.rail_buttons: dict[str, IconButton] = {}
        for key, title, icon_name in PANELS:
            b = IconButton(icon_name, title, checkable=True, size=19, role="rail")
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedSize(38, 38)
            b.clicked.connect(lambda _=False, k=key: self._rail_clicked(k))
            rl.addWidget(b)
            self.rail_buttons[key] = b
        rl.addStretch(1)
        for icon_name, tip, fn in (("keyboard", "단축키 (F1)", self.show_hotkeys),
                                   ("settings", "환경 설정 (Ctrl+,)", self.show_preferences)):
            b = IconButton(icon_name, tip, size=19, role="rail")
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedSize(38, 38)
            b.clicked.connect(fn)
            rl.addWidget(b)
        body.addWidget(self.rail)

        # Bottom: timeline + transport
        self.bottom = QWidget()
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        sep = QFrame()
        sep.setProperty("class", "hline")
        bl.addWidget(sep)
        self.timeline = Timeline()
        self.timeline.frameRequested.connect(self._timeline_seek)
        self.timeline.scrubStarted.connect(self._scrub_start)
        self.timeline.scrubFinished.connect(self._scrub_end)
        self.timeline.hoverFrame.connect(self._timeline_hover)
        bl.addWidget(self.timeline)
        self.transport = Transport()
        self._connect_transport()
        bl.addWidget(self.transport)
        root.addWidget(self.bottom)
        self.thumb_popup = ThumbPopup(self)

        self._build_status()

    def _build_toolbar(self) -> None:
        tb = QToolBar("뷰어")
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(Qt.TopToolBarArea, tb)
        self.toolbar = tb

        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(4, 0, 10, 0)
        bl.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(24))
        bl.addWidget(logo)
        name = QLabel("COC_SEQ")
        name.setStyleSheet(f"font-weight: 800; font-size: 13px; letter-spacing: 0.4px; color: {PAL.text};")
        bl.addWidget(name)
        tb.addWidget(brand)
        tb.addSeparator()

        def btn(icon_name, tip, fn, checkable=False):
            b = IconButton(icon_name, tip, checkable=checkable, size=18)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            tb.addWidget(b)
            return b

        btn("file-plus", "파일 열기 (Ctrl+O)", self.open_dialog)
        btn("folder-open", "폴더 열기 (Ctrl+Shift+O)", self.open_folder_dialog)
        tb.addSeparator()

        self.compare_seg = CompareButton()
        self.compare_seg.changed.connect(self.set_compare_mode)
        tb.addWidget(self.compare_seg)
        tb.addSeparator()

        self.channel_seg = Segmented([(k, t, f"채널: {t}") for k, t in CHANNEL_KEYS])
        self.channel_seg.changed.connect(self.set_channel)
        self._nofocus(self.channel_seg)
        colors = {"r": "#FF6B6B", "g": "#5BE38C", "b": "#5AA9FF"}
        for k, c in colors.items():
            self.channel_seg.button(k).setStyleSheet(f"QToolButton {{ color: {c}; }}")
        tb.addWidget(self.channel_seg)
        self.layer_combo = QComboBox()
        self.layer_combo.setProperty("role", "toolbar")
        self.layer_combo.setToolTip("레이어 (EXR AOV)")
        self.layer_combo.setMinimumWidth(128)
        self.layer_combo.setFocusPolicy(Qt.NoFocus)
        self.layer_combo.activated.connect(lambda i: self.set_layer(self.layer_combo.itemData(i)))
        self.layer_action = tb.addWidget(self.layer_combo)
        tb.addSeparator()

        self.exposure_field = ScrubField("", 0.0, -12, 12, 0.02, 2, 0.0, icon="sun", suffix=" st", width=104)
        self.exposure_field.setToolTip("노출 (스톱) — 드래그 / 더블클릭 입력 / 우클릭 초기화  ·  [ ] 키")
        self.exposure_field.valueChanged.connect(lambda v: self._set_display(exposure=v))
        tb.addWidget(self.exposure_field)
        self.gamma_field = ScrubField("", 1.0, 0.1, 4.0, 0.005, 2, 1.0, icon="gamma", width=88)
        self.gamma_field.setToolTip("감마 — 드래그 / 더블클릭 입력 / 우클릭 초기화")
        self.gamma_field.valueChanged.connect(lambda v: self._set_display(gamma=v))
        tb.addWidget(self.gamma_field)
        tb.addSeparator()

        self.cs_combo = QComboBox()
        self.cs_combo.setToolTip("입력 색공간 (현재 클립)")
        self.cs_combo.setFixedWidth(176)
        self.cs_combo.setMaxVisibleItems(26)
        self.cs_combo.setFocusPolicy(Qt.NoFocus)
        self.cs_combo.activated.connect(lambda i: self.set_colorspace(self.cs_combo.itemData(i)))
        tb.addWidget(self.cs_combo)
        arrow = QLabel("→")
        arrow.setProperty("class", "faint")
        arrow.setContentsMargins(2, 0, 2, 0)
        tb.addWidget(arrow)
        self.display_combo = QComboBox()
        self.display_combo.setToolTip("디스플레이")
        self.display_combo.setFixedWidth(136)
        self.display_combo.setFocusPolicy(Qt.NoFocus)
        self.display_combo.activated.connect(lambda i: self.set_display_view(self.display_combo.itemText(i), None))
        tb.addWidget(self.display_combo)
        self.view_combo = QComboBox()
        self.view_combo.setToolTip("뷰 변환")
        self.view_combo.setFixedWidth(176)
        self.view_combo.setFocusPolicy(Qt.NoFocus)
        self.view_combo.activated.connect(lambda i: self.set_display_view(None, self.view_combo.itemText(i)))
        tb.addWidget(self.view_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setProperty("role", "toolbar")
        self.zoom_combo.setFixedWidth(84)
        self.zoom_combo.setToolTip("확대 비율")
        self.zoom_combo.setFocusPolicy(Qt.ClickFocus)
        for z in ("맞춤", "12%", "25%", "50%", "100%", "200%", "400%", "800%"):
            self.zoom_combo.addItem(z)
        self.zoom_combo.lineEdit().setFont(mono_font(9))
        self.zoom_combo.activated.connect(lambda i: self._zoom_text(self.zoom_combo.itemText(i)))
        self.zoom_combo.lineEdit().editingFinished.connect(lambda: self._zoom_text(self.zoom_combo.currentText()))
        tb.addWidget(self.zoom_combo)
        btn("fit", "화면에 맞추기 (F)", lambda: self.viewer.fit())
        self.b_fullscreen = btn("fullscreen", "전체 화면 (F11)", self.toggle_fullscreen)
        btn("presentation", "프레젠테이션 모드 (F12)", self.toggle_presentation)

    @staticmethod
    def _nofocus(w: QWidget) -> None:
        for child in w.findChildren(QToolButton):
            child.setFocusPolicy(Qt.NoFocus)

    def _build_panels(self) -> None:
        self.panels: dict[str, QWidget] = {}
        self.playlist = PlaylistPanel()
        pl = self.playlist
        pl.activated.connect(self.set_a)
        pl.setB.connect(lambda s: self.set_compare_slot(0, s, auto_mode=True))
        pl.removeRequested.connect(self.close_source)
        pl.reloadRequested.connect(self.reload_source)
        pl.revealRequested.connect(self.reveal_source)
        pl.copyPathRequested.connect(self.copy_path)
        pl.attachAudioRequested.connect(self.open_audio_dialog)
        pl.openRequested.connect(self.open_dialog)
        pl.openFolderRequested.connect(self.open_folder_dialog)
        pl.filesDropped.connect(self.open_paths)
        pl.orderChanged.connect(self._on_order_changed)
        pl.clearRequested.connect(self.close_all)
        self.panels["playlist"] = pl

        self.color_panel = ColorPanel(self.viewer.display, self.colors)
        self.color_panel.changed.connect(self._on_display_changed)
        self.color_panel.colorspaceChosen.connect(self.set_colorspace)
        self.color_panel.configRequested.connect(lambda: self.show_preferences("color"))
        self.panels["color"] = self.color_panel

        self.compare_panel = ComparePanel()
        cp = self.compare_panel
        cp.modeChosen.connect(self.set_compare_mode)
        cp.bChosen.connect(lambda s: self.set_compare_slot(0, s, auto_mode=True))
        cp.extraChosen.connect(lambda i, s: self.set_compare_slot(i - 1, s))
        cp.swapRequested.connect(self.swap_ab)
        cp.alignChanged.connect(self._set_align)
        cp.offsetChanged.connect(self._set_offset)
        self.panels["compare"] = cp

        self.annotate_panel = AnnotatePanel()
        ap = self.annotate_panel
        ap.toolChosen.connect(self.set_tool)
        ap.styleChanged.connect(self._on_draw_style)
        ap.jumpRequested.connect(self.playback.seek)
        ap.undo.connect(self.annotation_undo)
        ap.redo.connect(self.annotation_redo)
        ap.clearFrame.connect(self.annotation_clear_frame)
        ap.clearAll.connect(self.annotation_clear_all)
        ap.exportPdf.connect(self.export_pdf)
        ap.noteEdited.connect(self._on_note)
        ap.visibilityToggled.connect(self._set_annotations_visible)
        self.panels["annotate"] = ap

        self.info_panel = self._optional_panel("cocseq.ui.panels.info", "MediaInfoPanel")
        self.panels["info"] = self.info_panel
        self.scopes_panel = self._optional_panel("cocseq.ui.panels.scopes", "ScopesPanel")
        if hasattr(self.scopes_panel, "activeChanged"):
            self.scopes_panel.activeChanged.connect(self._on_scopes_active)
        self.panels["scopes"] = self.scopes_panel
        self.area_panel = self._optional_panel("cocseq.ui.panels.area", "AreaPanel")
        self.panels["area"] = self.area_panel
        self.env_panel = EnvPanel()
        self.env_panel.bind(self.viewer)
        self.panels["env"] = self.env_panel
        self.log_panel = self._optional_panel("cocseq.ui.panels.logs", "LogPanel")
        self.panels["logs"] = self.log_panel
        from PySide6.QtWidgets import QScrollArea

        self._panel_pages: dict[str, QWidget] = {}
        for key, _t, _i in PANELS:
            w = self.panels[key]
            if key in ("playlist", "color", "logs"):
                page = w          # these scroll by themselves
            else:
                page = QScrollArea()
                page.setWidgetResizable(True)
                page.setFrameShape(QFrame.NoFrame)
                page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                page.setWidget(w)
            self._panel_pages[key] = page
            self.stack.addWidget(page)

    def _optional_panel(self, module: str, cls: str) -> QWidget:
        try:
            mod = __import__(module, fromlist=[cls])
            return getattr(mod, cls)()
        except Exception as exc:
            log.error("panel %s unavailable: %s", cls, exc)
            w = QLabel(f"{cls}를 불러오지 못했습니다.\n{exc}")
            w.setWordWrap(True)
            w.setAlignment(Qt.AlignCenter)
            return w

    def _build_status(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.pixel_swatch = QLabel()
        self.pixel_swatch.setFixedSize(14, 14)
        self.pixel_swatch.setStyleSheet("background: transparent; border-radius: 4px;")
        sb.addWidget(self.pixel_swatch)
        self.pixel_label = QLabel("")
        self.pixel_label.setFont(mono_font(8.5))
        self.pixel_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sb.addWidget(self.pixel_label, 1)
        self.gl_label = QLabel("")
        self.gl_label.setProperty("class", "faint")
        self.gl_label.setFont(ui_font(8.5))
        sb.addPermanentWidget(self.gl_label)
        self.mem_label = QLabel("")
        self.mem_label.setFont(mono_font(8.5))
        self.mem_label.setToolTip("프레임 캐시 메모리 사용량")
        sb.addPermanentWidget(self.mem_label)
        self.mem_bar = QProgressBar()
        self.mem_bar.setTextVisible(False)
        self.mem_bar.setFixedSize(70, 6)
        self.mem_bar.setStyleSheet(f"QProgressBar {{ min-height: 6px; max-height: 6px; border-radius: 3px;"
                                   f" background: {PAL.bg4}; border: none; }}"
                                   f"QProgressBar::chunk {{ background: {PAL.ok}; border-radius: 3px; }}")
        sb.addPermanentWidget(self.mem_bar)

    def _connect_transport(self) -> None:
        t = self.transport
        pb = self.playback
        t.playForward.connect(lambda: pb.play(1))
        t.playBackward.connect(lambda: pb.toggle(-1) if pb.direction != -1 else pb.stop())
        t.stop.connect(pb.stop)
        t.stepRequested.connect(pb.step)
        t.gotoStart.connect(pb.goto_start)
        t.gotoEnd.connect(pb.goto_end)
        t.frameEntered.connect(pb.seek)
        t.setIn.connect(self.set_in)
        t.setOut.connect(self.set_out)
        t.clearIn.connect(lambda: self.set_in(None))
        t.clearOut.connect(lambda: self.set_out(None))
        t.loopClicked.connect(pb.cycle_loop_mode)
        t.fpsChosen.connect(self.set_fps)
        t.timeModeChosen.connect(self.set_time_mode)
        t.volumeChanged.connect(self.set_volume)
        t.muteToggled.connect(self.set_muted)
        for b in t.findChildren(QToolButton):
            b.setFocusPolicy(Qt.NoFocus)

    # ================================================================ actions & menus

    def _build_actions(self) -> None:
        self.actions_by_id: dict[str, QAction] = {}
        pb = self.playback
        v = self.viewer
        h = {
            "file.open": self.open_dialog,
            "file.open_folder": self.open_folder_dialog,
            "file.open_audio": lambda: self.open_audio_dialog(self.a),
            "file.open_session": self.open_session_dialog,
            "file.save_session": self.save_session,
            "file.save_session_as": self.save_session_as,
            "file.save_frame": self.save_frame,
            "file.export": self.export_dialog,
            "file.export_pdf": self.export_pdf,
            "file.reload": lambda: self.reload_source(self.a),
            "file.close": lambda: self.close_source(self.a),
            "file.close_all": self.close_all,
            "file.reveal": lambda: self.reveal_source(self.a),
            "file.copy_path": lambda: self.copy_path(self.a),
            "file.quit": self.close,
            "play.toggle": lambda: pb.toggle(1),
            "play.forward": lambda: pb.play(1),
            "play.backward": lambda: pb.play(-1),
            "play.stop": pb.stop,
            "play.jkl_forward": lambda: pb.play(1),
            "play.jkl_backward": lambda: pb.play(-1),
            "play.next_frame": lambda: pb.step(1),
            "play.prev_frame": lambda: pb.step(-1),
            "play.next_10": lambda: pb.step(10),
            "play.prev_10": lambda: pb.step(-10),
            "play.start": pb.goto_start,
            "play.end": pb.goto_end,
            "play.set_in": self.set_in,
            "play.set_out": self.set_out,
            "play.clear_in": lambda: self.set_in(None),
            "play.clear_out": lambda: self.set_out(None),
            "play.clear_range": self.clear_range,
            "play.loop_cycle": pb.cycle_loop_mode,
            "play.goto": self.goto_dialog,
            "play.faster": lambda: self._fps_step(1),
            "play.slower": lambda: self._fps_step(-1),
            "play.mute": lambda: self.set_muted(not self.prefs.muted),
            "clip.next": lambda: self.next_clip(1),
            "clip.prev": lambda: self.next_clip(-1),
            "clip.next_version": lambda: self.version_step(1),
            "clip.prev_version": lambda: self.version_step(-1),
            "clip.set_b": lambda: self.set_compare_slot(0, self.a, auto_mode=True) if self.a else None,
            "compare.swap": self.swap_ab,
            "view.fit": v.fit,
            "view.zoom_1": lambda: v.set_zoom(1.0),
            "view.zoom_2": lambda: v.set_zoom(2.0),
            "view.zoom_half": lambda: v.set_zoom(0.5),
            "view.zoom_in": lambda: v.zoom_by(1.25),
            "view.zoom_out": lambda: v.zoom_by(0.8),
            "view.center": v.center_image,
            "view.mirror_x": lambda: self._toggle_view("mirror_x"),
            "view.mirror_y": lambda: self._toggle_view("mirror_y"),
            "view.rotate_cw": lambda: v.set_rotation(v.rotation + 90),
            "view.rotate_ccw": lambda: v.set_rotation(v.rotation - 90),
            "view.fullscreen": self.toggle_fullscreen,
            "view.presentation": self.toggle_presentation,
            "view.on_top": self.toggle_on_top,
            "view.hud": lambda: self._toggle_view("hud_enabled"),
            "view.safe_areas": lambda: self._toggle_view("show_safe_areas"),
            "view.display_window": lambda: self._toggle_view("show_display_window"),
            "view.data_window": lambda: self._toggle_view("show_data_window"),
            "view.filter": lambda: self._toggle_view("filter_linear"),
            "view.env_map": self.toggle_env,
            "view.side_panel": lambda: self.set_side_visible(not self.side.isVisible()),
            "view.timeline": lambda: self.bottom.setVisible(not self.bottom.isVisible()),
            "ch.next_layer": lambda: self._layer_step(1),
            "ch.prev_layer": lambda: self._layer_step(-1),
            "color.exposure_up": lambda: self._set_display(exposure=round(v.display.exposure + 0.5, 2)),
            "color.exposure_down": lambda: self._set_display(exposure=round(v.display.exposure - 0.5, 2)),
            "color.exposure_reset": lambda: self._set_display(exposure=0.0),
            "color.gamma_up": lambda: self._set_display(gamma=round(min(4.0, v.display.gamma + 0.1), 2)),
            "color.gamma_down": lambda: self._set_display(gamma=round(max(0.1, v.display.gamma - 0.1), 2)),
            "color.reset": self.reset_color,
            "draw.undo": self.annotation_undo,
            "draw.redo": self.annotation_redo,
            "draw.clear_frame": self.annotation_clear_frame,
            "draw.next": lambda: self.annotation_jump(1),
            "draw.prev": lambda: self.annotation_jump(-1),
            "draw.toggle": lambda: self._set_annotations_visible(not self.viewer.show_annotations),
            "app.preferences": self.show_preferences,
            "app.hotkeys": self.show_hotkeys,
            "app.about": self.show_about,
        }
        for mode in COMPARE_MODES:
            h[f"compare.{mode}"] = (lambda m=mode: self.set_compare_mode(m))
        for key, _ in CHANNEL_KEYS:
            h[f"ch.{key}"] = (lambda k=key: self.set_channel(k))
        for key, tool in (("none", ""), ("pen", "pen"), ("eraser", "eraser"), ("line", "line"), ("arrow", "arrow"),
                          ("rect", "rect"), ("ellipse", "ellipse"), ("text", "text"), ("area", "area")):
            h[f"draw.{key}"] = (lambda t=tool: self.set_tool(t))
        for key, _t, _i in PANELS:
            h[f"panel.{key}"] = (lambda k=key: self.show_panel(k, toggle=True))

        overrides = self.prefs.hotkeys
        for adef in hotkeys.ACTIONS:
            act = QAction(adef.label, self)
            if adef.icon:
                act.setIcon(icons.icon(adef.icon, size=16))
            act.setCheckable(adef.checkable)
            seq = hotkeys.shortcut_for(adef.id, overrides)
            if seq:
                act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(Qt.WindowShortcut)
            fn = h.get(adef.id)
            if fn is not None:
                act.triggered.connect(lambda _=False, f=fn: f())
            self.addAction(act)
            self.actions_by_id[adef.id] = act

    def apply_hotkeys(self) -> None:
        overrides = self.prefs.hotkeys
        for adef in hotkeys.ACTIONS:
            act = self.actions_by_id.get(adef.id)
            if act is not None:
                seq = hotkeys.shortcut_for(adef.id, overrides)
                act.setShortcut(QKeySequence(seq) if seq else QKeySequence())

    def _act(self, action_id: str) -> QAction:
        return self.actions_by_id[action_id]

    def _build_menus(self) -> None:
        mb = self.menuBar()
        A = self._act

        m = mb.addMenu("파일")
        for aid in ("file.open", "file.open_folder", "file.open_audio"):
            m.addAction(A(aid))
        self.recent_menu = m.addMenu("최근 파일")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for aid in ("file.open_session", "file.save_session", "file.save_session_as"):
            m.addAction(A(aid))
        self.recent_session_menu = m.addMenu("최근 세션")
        self.recent_session_menu.aboutToShow.connect(self._fill_recent_sessions)
        m.addSeparator()
        for aid in ("file.save_frame", "file.export", "file.export_pdf"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("file.reload", "file.reveal", "file.copy_path"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("file.close", "file.close_all"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("file.quit"))

        m = mb.addMenu("보기")
        for aid in ("view.fit", "view.zoom_1", "view.zoom_2", "view.zoom_half", "view.zoom_in", "view.zoom_out",
                    "view.center"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("view.mirror_x", "view.mirror_y", "view.rotate_cw", "view.rotate_ccw"):
            m.addAction(A(aid))
        m.addSeparator()
        bg = m.addMenu("배경")
        self.bg_group = QActionGroup(self)
        self.bg_actions = {}
        for key, label in BACKGROUNDS:
            a = bg.addAction(label)
            a.setCheckable(True)
            self.bg_group.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.set_background(k))
            self.bg_actions[key] = a
        m.addAction(A("view.filter"))
        m.addSeparator()
        for aid in ("view.hud", "view.safe_areas"):
            m.addAction(A(aid))
        asp = m.addMenu("화면비 가이드")
        self.aspect_group = QActionGroup(self)
        self.aspect_actions = {}
        for key, label in ASPECTS:
            a = asp.addAction(label)
            a.setCheckable(True)
            self.aspect_group.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.set_aspect_guide(k))
            self.aspect_actions[key] = a
        for aid in ("view.display_window", "view.data_window"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("view.env_map"))
        m.addSeparator()
        for aid in ("view.fullscreen", "view.presentation", "view.on_top"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("view.side_panel", "view.timeline"):
            m.addAction(A(aid))

        m = mb.addMenu("재생")
        for aid in ("play.toggle", "play.forward", "play.backward", "play.stop"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("play.next_frame", "play.prev_frame", "play.next_10", "play.prev_10", "play.start", "play.end",
                    "play.goto"):
            m.addAction(A(aid))
        m.addSeparator()
        for aid in ("play.set_in", "play.set_out", "play.clear_in", "play.clear_out", "play.clear_range"):
            m.addAction(A(aid))
        m.addSeparator()
        loop = m.addMenu("반복 방식")
        self.loop_group = QActionGroup(self)
        self.loop_actions = {}
        for key, label in (("loop", "반복"), ("once", "한 번"), ("pingpong", "왕복")):
            a = loop.addAction(label)
            a.setCheckable(True)
            self.loop_group.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.playback.set_loop_mode(k))
            self.loop_actions[key] = a
        loop.addSeparator()
        loop.addAction(A("play.loop_cycle"))
        mode = m.addMenu("재생 방식")
        self.play_mode_group = QActionGroup(self)
        self.act_play_all = mode.addAction("모든 프레임 재생")
        self.act_realtime = mode.addAction("실시간 유지 (프레임 건너뜀)")
        for a, val in ((self.act_play_all, True), (self.act_realtime, False)):
            a.setCheckable(True)
            self.play_mode_group.addAction(a)
            a.triggered.connect(lambda _=False, x=val: self._set_play_all(x))
        self.act_continuous = m.addAction("플레이리스트 이어서 재생")
        self.act_continuous.setCheckable(True)
        self.act_continuous.toggled.connect(self._set_continuous)
        for aid in ("play.faster", "play.slower"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("play.mute"))

        m = mb.addMenu("클립")
        for aid in ("clip.next", "clip.prev", "clip.next_version", "clip.prev_version"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("clip.set_b"))
        self.layer_menu = m.addMenu("레이어")
        self.layer_menu.aboutToShow.connect(self._fill_layer_menu)
        m.addSeparator()
        m.addAction(A("file.open_audio"))

        m = mb.addMenu("비교")
        for mode_key in COMPARE_MODES:
            m.addAction(A(f"compare.{mode_key}"))
        m.addSeparator()
        m.addAction(A("compare.swap"))

        m = mb.addMenu("색")
        for key, _ in CHANNEL_KEYS:
            m.addAction(A(f"ch.{key}"))
        m.addAction(A("ch.next_layer"))
        m.addAction(A("ch.prev_layer"))
        m.addSeparator()
        for aid in ("color.exposure_up", "color.exposure_down", "color.exposure_reset", "color.gamma_up",
                    "color.gamma_down", "color.reset"):
            m.addAction(A(aid))
        m.addSeparator()
        self.display_menu = m.addMenu("디스플레이 / 뷰")
        self.display_menu.aboutToShow.connect(self._fill_display_menu)
        alpha = m.addMenu("알파 합성")
        self.alpha_group = QActionGroup(self)
        self.alpha_actions = {}
        for key, label in (("none", "무시"), ("straight", "Straight"), ("premult", "Premultiplied")):
            a = alpha.addAction(label)
            a.setCheckable(True)
            self.alpha_group.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self._set_display(alpha_mode=k))
            self.alpha_actions[key] = a

        m = mb.addMenu("주석")
        for key in ("none", "pen", "eraser", "line", "arrow", "rect", "ellipse", "text", "area"):
            m.addAction(A(f"draw.{key}"))
        m.addSeparator()
        for aid in ("draw.undo", "draw.redo", "draw.clear_frame", "draw.next", "draw.prev", "draw.toggle"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("file.export_pdf"))

        m = mb.addMenu("패널")
        for key, _t, _i in PANELS:
            m.addAction(A(f"panel.{key}"))

        m = mb.addMenu("도움말")
        for aid in ("app.hotkeys", "app.preferences", "app.about"):
            m.addAction(A(aid))

    # ================================================================ prefs

    def apply_prefs(self, initial: bool = False) -> None:
        p = self.prefs
        theme.set_accent(p.accent)
        if not initial:
            icons.clear_cache()
            theme.apply_theme(QApplication.instance())
        self.cache.set_budget(int(p.cache_gb * 1024 ** 3))
        self.prefetch.set_threads(p.reader_threads)
        self.playback.play_all_frames = p.play_all_frames
        self.playback.set_loop_mode(p.loop_mode)
        self.transport.set_time_mode(p.time_display)
        self.timeline.set_time_mode(p.time_display)
        self.transport.set_loop_mode(self.playback.loop_mode)
        self.transport.set_volume(p.volume, p.muted)
        self.audio.set_volume(p.volume)
        self.audio.set_muted(p.muted)
        self.audio.set_device(p.audio_device)
        v = self.viewer
        v.background = p.background
        v.background_color = QColor(p.background_color)
        v.checker_size = p.checker_size
        v.filter_linear = p.filter_linear
        v.pen_color = p.pen_color
        v.pen_size = p.pen_size
        v.ghost_frames = p.ghost_frames
        v.hud_enabled = p.hud
        v.aspect_guide = p.safe_area_ratio if p.safe_area_ratio in dict(ASPECTS) else ""
        if initial:
            d = v.display
            d.display, d.view = self.colors.resolve_display_view(p.display, p.view)
        self.annotate_panel.set_style(v.pen_color, v.pen_size, v.pen_fill, v.pen_hold, v.ghost_frames)
        self.draw_bar.set_color(v.pen_color)
        self.act_play_all.setChecked(p.play_all_frames)
        self.act_realtime.setChecked(not p.play_all_frames)
        self.act_continuous.setChecked(p.playlist_continuous)
        self.compare_align = p.compare_align if initial else self.compare_align
        self._sync_view_actions()
        if initial:
            self.set_side_visible(p.panel_visible)
            self.show_panel(p.panel if p.panel in self.panels else "playlist")
            geo = self.store.value("window_geometry")
            if geo:
                self.restoreGeometry(QByteArray(geo))
            sizes = self.store.value("splitter_sizes")
            if sizes:
                try:
                    self.splitter.setSizes([int(s) for s in sizes])
                except (TypeError, ValueError):
                    pass
        self.apply_hotkeys()
        self._refresh_view()
        self.update()

    def _save_state(self) -> None:
        p = self.prefs
        p.panel_visible = self.side.isVisible()
        p.volume = self.audio.volume
        p.muted = self.audio.muted
        p.pen_color, p.pen_size = self.viewer.pen_color, self.viewer.pen_size
        p.ghost_frames = self.viewer.ghost_frames
        p.loop_mode = self.playback.loop_mode
        p.hud = self.viewer.hud_enabled
        p.safe_area_ratio = self.viewer.aspect_guide
        p.display, p.view = self.viewer.display.display, self.viewer.display.view
        p.background = self.viewer.background
        p.filter_linear = self.viewer.filter_linear
        self.store.set_value("window_geometry", self.saveGeometry())
        self.store.set_value("splitter_sizes", self.splitter.sizes())
        self.store.save()

    # ================================================================ opening media

    def _start_dir(self) -> str:
        if self.a is not None:
            return self.a.directory
        return self.prefs.last_dir or os.path.expanduser("~")

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "파일 열기", self._start_dir(), MEDIA_FILTER)
        if paths:
            self.open_paths(paths)

    def open_folder_dialog(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "폴더 열기", self._start_dir())
        if d:
            self.open_paths([d])

    def open_audio_dialog(self, src=None) -> None:
        src = src or self.a
        if src is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "오디오 파일 연결", src.directory,
                                              "오디오 (*.wav *.mp3 *.aac *.m4a *.flac *.ogg *.aif *.aiff *.mov *.mp4);;모든 파일 (*)")
        if path:
            self.attach_audio(src, path)

    def attach_audio(self, src, path: str) -> None:
        src.audio_path = path
        src.audio = None
        self.audio_loader.load(src.id, path)
        self.statusBar().showMessage(f"오디오 연결: {os.path.basename(path)}", 4000)

    def open_paths(self, paths: list[str]) -> None:
        paths = [p for p in paths if p]
        if not paths:
            return
        opened: list[MediaSource] = []
        audio_files = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            seen_seq = set()
            for path in paths:
                if os.path.isdir(path):
                    items = scan_directory(path)
                    for it in items:
                        if it.kind == "audio":
                            audio_files.append(it.path)
                        else:
                            src = self.add_source_path(it.path, activate=False, detect=False if it.kind == "movie"
                                                       else True)
                            if src:
                                opened.append(src)
                    if not items:
                        self.statusBar().showMessage(f"'{os.path.basename(path)}' 폴더에 열 수 있는 미디어가 없습니다.", 5000)
                    continue
                low = path.lower()
                if low.endswith(SESSION_EXT):
                    self.open_session(path)
                    return
                if is_audio(path):
                    audio_files.append(path)
                    continue
                if not is_media(path):
                    self.statusBar().showMessage(f"지원하지 않는 파일: {os.path.basename(path)}", 5000)
                    continue
                src = self.add_source_path(path, activate=False)
                if src is None:
                    continue
                key = src.display_path
                if key in seen_seq:
                    self._remove_source_silently(src)
                    continue
                seen_seq.add(key)
                opened.append(src)
        finally:
            QApplication.restoreOverrideCursor()
        if opened:
            self.prefs.last_dir = opened[-1].directory
            self.set_a(opened[0])
            if self.prefs.autoplay_on_open:
                self.playback.play(1)
        target = opened[0] if opened else self.a
        if audio_files and target is not None:
            self.attach_audio(target, audio_files[0])
        self.store.save()

    def add_source_path(self, path: str, activate: bool = True, restore: dict | None = None,
                        detect: bool | None = None) -> MediaSource | None:
        p = self.prefs
        try:
            src = MediaSource.open(path, p.auto_detect_sequence if detect is None else detect,
                                   p.movie_start_frame, p.default_fps)
        except Exception as exc:
            log.exception("open %s", path)
            QMessageBox.warning(self, APP_NAME, f"파일을 열 수 없습니다.\n{path}\n\n{exc}")
            return None
        if src.error and not src.info.width:
            log.error("%s: %s", path, src.error)
            self.statusBar().showMessage(f"열기 실패: {src.error}", 8000)
        # The same sequence already open? Use that one.
        for s in self.sources:
            if s.display_path == src.display_path and s.kind == src.kind and restore is None:
                src.close()
                if activate:
                    self.set_a(s)
                return s
        src.colorspace = self.colors.default_colorspace(src, p)
        if restore:
            src.apply_dict(restore)
            if not src.colorspace:
                src.colorspace = self.colors.default_colorspace(src, p)
            else:
                src.colorspace = self.colors.resolve_colorspace(src.colorspace)
        self.sources.append(src)
        self.playlist.add_source(src)
        self._update_thumb_fn(src)
        self.thumbs.request(src, src.first, self._thumb_w())
        if src.audio_path:
            self.audio_loader.load(src.id, src.audio_path)
        p.add_recent(src.display_path if src.kind == "movie" else src.frame_path(src.first))
        log.info("열기: %s (%s)", src.display_path, src.kind)
        if activate:
            self.set_a(src)
        return src

    def _thumb_w(self) -> int:
        return int(88 * max(1.0, self.devicePixelRatioF()))

    def _update_thumb_fn(self, src) -> None:
        d = self.viewer.display
        fn = self.colors.cpu_function(src.colorspace, d.display, d.view, d.look, d.lut, d.lut_mode)
        self.thumbs.set_display_fn(src.id, fn)

    def _remove_source_silently(self, src) -> None:
        if src in self.sources:
            self.sources.remove(src)
        self.playlist.remove_source(src)
        self.cache.drop_source(src.id)
        self.thumbs.forget(src.id)
        src.close()

    def close_source(self, src) -> None:
        if src is None:
            return
        idx = self.sources.index(src) if src in self.sources else -1
        was_a = src is self.a
        self.compare_slots = [None if s is src else s for s in self.compare_slots]
        self._remove_source_silently(src)
        self._last_frames.clear()
        if was_a:
            self.a = None
            if self.sources:
                self.set_a(self.sources[min(max(idx, 0), len(self.sources) - 1)])
            else:
                self.playback.stop()
                self._update_all()
        else:
            self._update_all()

    def close_all(self, confirm: bool = True) -> None:
        if not self.sources:
            return
        if confirm and any(not s.annotations.is_empty() for s in self.sources):
            r = QMessageBox.question(self, APP_NAME, "주석이 있는 클립이 있습니다. 모두 닫을까요?\n(세션으로 저장하지 않은 주석은 사라집니다)")
            if r != QMessageBox.Yes:
                return
        self.playback.stop()
        for s in list(self.sources):
            self._remove_source_silently(s)
        self.a = None
        self.compare_slots = [None, None, None]
        self.compare_mode = "A"
        self._last_frames.clear()
        self.cache.clear()
        self._update_all()

    def reload_source(self, src) -> None:
        if src is None:
            return
        self.cache.drop_source(src.id)
        self.thumbs.forget(src.id)
        src.reload()
        self._update_thumb_fn(src)
        self.thumbs.request(src, src.first, self._thumb_w())
        self._last_frames.clear()
        if src is self.a:
            self.playback.set_clip(src.first, src.last, self.playback.frame, src.in_point, src.out_point, src.fps)
            self._update_clip_widgets()
        self._prefetch_sig = None
        self._refresh_view()
        self.statusBar().showMessage(f"다시 불러옴: {src.name} ({src.first}–{src.last})", 4000)

    def reveal_source(self, src) -> None:
        if src is None:
            return
        path = src.frame_path(src.current)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def copy_path(self, src) -> None:
        if src is None:
            return
        QApplication.clipboard().setText(src.display_path)
        self.statusBar().showMessage("경로를 복사했습니다.", 2500)

    def _on_order_changed(self, order: list) -> None:
        self.sources = [s for s in order if s is not None]

    # ================================================================ current clip

    def set_a(self, src) -> None:
        if src is None:
            return
        if self.a is not None and self.a is not src:
            self.a.current = self.playback.frame
        if src is self.compare_slots[0]:
            self.compare_slots[0] = self.a if self.a is not src else None
        playing = self.playback.direction
        self.a = src
        self.playback.stop()
        self.playback.set_clip(src.first, src.last, src.current, src.in_point, src.out_point, src.fps)
        self._last_frames.clear()
        self._prefetch_sig = None
        self._update_clip_widgets()
        self._update_all()
        if self.prefs.zoom_to_fit_on_open:
            self.viewer._auto_fit = True
            self.viewer._pending_fit = True
        if playing:
            self.playback.play(playing)

    def _update_clip_widgets(self) -> None:
        src = self.a
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        if src is not None:
            for l in src.layers:
                self.layer_combo.addItem(l.label, l.name)
            self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(src.layer.name)))
        self.layer_combo.setEnabled(src is not None and len(src.layers) > 1)
        self.layer_action.setVisible(src is not None and len(src.layers) > 1)
        self.layer_combo.blockSignals(False)
        if src is not None:
            fill_colorspace_combo(self.cs_combo, self.colors, src.colorspace)
        else:
            self.cs_combo.clear()
        self.cs_combo.setEnabled(src is not None)
        self.timeline.clip_name = src.name if src else ""
        if src is not None:
            self.timeline.set_range(src.first, src.last)
            self.timeline.set_missing(src.missing)
            self.timeline.set_fps(src.fps)
            self._update_timeline_audio()
        else:
            self.timeline.set_range(1, 100)
            self.timeline.set_missing([])
            self.timeline.set_audio(None)
            self.timeline.set_cached(set())
        self.viewer.annotation_store = src.annotations if src else None
        if hasattr(self.info_panel, "set_source"):
            self.info_panel.set_source(src, None)
        self.color_panel.refresh(src)
        self._update_title()

    def _update_title(self) -> None:
        parts = [APP_NAME]
        if self.a is not None:
            parts.insert(0, self.a.name)
        if self.session_path:
            parts.insert(1 if self.a else 0, os.path.basename(self.session_path))
        self.setWindowTitle("  —  ".join(parts))

    def next_clip(self, step: int) -> None:
        if not self.sources or self.a is None:
            return
        i = self.sources.index(self.a) if self.a in self.sources else 0
        self.set_a(self.sources[(i + step) % len(self.sources)])

    def version_step(self, step: int) -> None:
        src = self.a
        if src is None:
            return
        path = src.frame_path(src.first) if src.kind == "sequence" else src.path
        found = find_version(path, step, src.kind == "sequence")
        if not found:
            self.statusBar().showMessage("다른 버전을 찾지 못했습니다 (파일 경로에 v001 같은 버전 표시가 필요합니다).", 5000)
            return
        frame = self.playback.frame
        new = self.add_source_path(found, activate=False)
        if new is None:
            return
        new.colorspace = src.colorspace
        new.set_layer(src.layer.name)
        new.current = max(new.first, min(new.last, new.first + (frame - src.first)))
        self.set_a(new)
        self.statusBar().showMessage(f"버전 전환: {new.name}", 4000)

    def set_layer(self, name: str) -> None:
        if self.a is None or not name:
            return
        if self.a.set_layer(name):
            self._last_frames.pop(0, None)
            self._prefetch_sig = None
            self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(name)))
            self._refresh_view()

    def _layer_step(self, step: int) -> None:
        if self.a is None or len(self.a.layers) < 2:
            return
        names = [l.name for l in self.a.layers]
        i = names.index(self.a.layer.name) if self.a.layer.name in names else 0
        self.set_layer(names[(i + step) % len(names)])
        self.statusBar().showMessage(f"레이어: {self.a.layer.label}", 2500)

    def _fill_layer_menu(self) -> None:
        m = self.layer_menu
        m.clear()
        if self.a is None:
            m.addAction("클립 없음").setEnabled(False)
            return
        g = QActionGroup(m)
        for l in self.a.layers:
            a = m.addAction(l.label)
            a.setCheckable(True)
            a.setChecked(l.name == self.a.layer.name)
            g.addAction(a)
            a.triggered.connect(lambda _=False, n=l.name: self.set_layer(n))

    def set_colorspace(self, name: str) -> None:
        if self.a is None or not name:
            return
        self.a.colorspace = name
        self._update_thumb_fn(self.a)
        self.thumbs.forget(self.a.id)
        self._update_thumb_fn(self.a)
        self.thumbs.request(self.a, self.a.first, self._thumb_w())
        fill_colorspace_combo(self.cs_combo, self.colors, name)
        self.color_panel.refresh(self.a)
        self._refresh_view()

    # ================================================================ frames

    def _map_frame(self, src, frame: int) -> int:
        a = self.a
        if a is None:
            return frame
        if self.compare_align == "absolute":
            f = frame + self.compare_offset
        else:
            f = src.first + (frame - a.first) + self.compare_offset
        return max(src.first, min(src.last, f))

    def _visible_compare(self) -> list:
        mode = self.compare_mode
        if mode == "A":
            return []
        if mode == "tile":
            return [s for s in self.compare_slots if s is not None]
        return [self.compare_slots[0]] if self.compare_slots[0] is not None else []

    def _frame_for(self, slot: int, src, frame_no: int) -> tuple[Frame | None, bool]:
        """Frame to show for a slot and whether it is the exact frame (False while loading)."""
        key = Prefetcher.key_for(src, src.layer, frame_no)
        f = self.cache.get(key)
        if f is not None:
            if f.missing and self.prefs.missing_frame == "hold":
                last = self._last_frames.get(slot)
                if last is not None and not last.missing:
                    return last, True
            self._last_frames[slot] = f
            return f, True
        last = self._last_frames.get(slot)
        return last, False

    def _is_ready(self, frame: int) -> bool:
        a = self.a
        if a is None:
            return True
        if not self.cache.contains(Prefetcher.key_for(a, a.layer, frame)):
            return False
        for s in self._visible_compare():
            if not self.cache.contains(Prefetcher.key_for(s, s.layer, self._map_frame(s, frame))):
                return False
        return True

    def _on_frame_changed(self, frame: int) -> None:
        if self.a is not None:
            self.a.current = frame
        self._refresh_view()
        if (not self.playback.playing and self.prefs.audio_scrub and self.a is not None
                and self.a.audio is not None):
            t = self._track_time(self.a, frame)
            self.audio.scrub(self.a.audio, t, 1.0 / max(1.0, self.playback.fps))

    def _refresh_view(self) -> None:
        a = self.a
        v = self.viewer
        if a is None:
            v.set_slots([])
            v.set_loading(False)
            v.hud = {}
            self._update_prefetch()
            return
        frame = self.playback.frame
        slots = []
        loading = False
        fa, ok = self._frame_for(0, a, frame)
        loading |= not ok
        if fa is not None and fa.frame_no != frame and ok:
            fa = fa  # held missing frame
        slots.append(SlotInput(a, fa if (fa is None or self._same_source(fa, a)) else None))
        for i, s in enumerate(self._visible_compare()):
            fb, ok = self._frame_for(i + 1, s, self._map_frame(s, frame))
            loading |= not ok
            slots.append(SlotInput(s, fb))
        v.set_slots(slots)
        v.set_loading(loading)
        v.annotation_frame = frame
        self.timeline.set_frame(frame)
        self.transport.set_frame(frame)
        self._update_hud()
        self._update_prefetch()
        if not self.playback.playing:
            self.annotate_panel.set_note(frame, a.annotations.notes.get(frame, ""))

    def _same_source(self, frame: Frame, src) -> bool:
        return True

    def _update_prefetch(self) -> None:
        a = self.a
        if a is None:
            self.prefetch.set_wanted([])
            return
        pb = self.playback
        lo, hi = pb.range()
        comp = self._visible_compare()
        sig = (a.id, a.layer.key, pb.frame, pb.direction, lo, hi, pb.loop_mode, tuple(s.id for s in comp),
               self.cache.budget, self.compare_align, self.compare_offset,
               tuple(s.layer.key for s in comp))
        if sig == self._prefetch_sig:
            return
        self._prefetch_sig = sig
        budget = self.cache.budget * 0.92
        members = [a] + comp
        share = budget / len(members)
        count = max(1, int(share // max(1, a.bytes_per_frame())))
        frames = window_frames(pb.frame, lo, hi, pb.direction or 1, pb.loop_mode, count,
                               self.prefs.cache_behind_ratio)
        items = []
        comp_lists = []
        for s in comp:
            n = max(1, int(share // max(1, s.bytes_per_frame())))
            seen = set()
            lst = []
            for f in frames[:n]:
                g = self._map_frame(s, f)
                if g not in seen:
                    seen.add(g)
                    lst.append(g)
            comp_lists.append((s, lst))
        for i, f in enumerate(frames):
            items.append((a, a.layer, f))
            for s, lst in comp_lists:
                if i < len(lst):
                    items.append((s, s.layer, lst[i]))
        self.prefetch.set_wanted(items)

    def _on_frame_loaded(self, sid: int, lkey: str, fno: int) -> None:
        a = self.a
        if a is None:
            return
        frame = self.playback.frame
        if sid == a.id and fno == frame:
            self._refresh_view()
            return
        for s in self._visible_compare():
            if s.id == sid and fno == self._map_frame(s, frame):
                self._refresh_view()
                return

    def _on_cache_timer(self) -> None:
        a = self.a
        if a is not None:
            self.timeline.set_cached(self.cache.frames_for(a.id, "movie" if a.kind == "movie" else a.layer.key))
        used, budget = self.cache.used, self.cache.budget
        self.mem_label.setText(f"{human_bytes(used)} / {human_bytes(budget)}")
        self.mem_bar.setValue(int(100 * used / max(1, budget)))
        self.mem_bar.setMaximum(100)

    # ================================================================ playback glue

    def _on_play_state(self, direction: int) -> None:
        self.transport.set_playing(direction)
        self._prefetch_sig = None
        self._update_prefetch()
        if direction == 0 and self.a is not None:
            self.annotate_panel.set_note(self.playback.frame, self.a.annotations.notes.get(self.playback.frame, ""))
            self._update_hud()

    def _on_loop_mode(self, mode: str) -> None:
        self.transport.set_loop_mode(mode)
        a = self.loop_actions.get(mode)
        if a:
            a.setChecked(True)
        self._prefetch_sig = None
        self._update_prefetch()

    def _on_fps_changed(self, fps: float) -> None:
        self.transport.set_fps(fps)
        self.timeline.set_fps(fps)

    def _on_range_changed(self) -> None:
        pb = self.playback
        if self.a is not None:
            self.a.in_point, self.a.out_point = pb.in_point, pb.out_point
            self.transport.set_clip_info(self.a.first, self.a.last, pb.fps, pb.in_point, pb.out_point)
        self.timeline.set_inout(pb.in_point, pb.out_point)
        self._prefetch_sig = None
        self._update_prefetch()

    def _on_reached_end(self, _d: int) -> None:
        if self.prefs.playlist_continuous and len(self.sources) > 1 and self.a in self.sources:
            i = self.sources.index(self.a)
            if i + 1 < len(self.sources) or self.playback.loop_mode == "loop":
                nxt = self.sources[(i + 1) % len(self.sources)]
                nxt.current = nxt.range[0]
                self.set_a(nxt)
                self.playback.play(1)

    def set_in(self, frame=False) -> None:
        if self.a is None:
            return
        self.playback.set_in(self.playback.frame if frame is False else frame)

    def set_out(self, frame=False) -> None:
        if self.a is None:
            return
        self.playback.set_out(self.playback.frame if frame is False else frame)

    def clear_range(self) -> None:
        self.playback.set_in(None)
        self.playback.set_out(None)

    def set_fps(self, fps: float) -> None:
        if self.a is None:
            return
        self.a.fps_override = fps if abs(fps - (self.a.info.fps or self.a.default_fps)) > 1e-6 else 0.0
        self.playback.set_fps(fps)
        self._update_hud()

    def _fps_step(self, step: int) -> None:
        from cocseq.ui.transport import FPS_PRESETS

        cur = self.playback.fps
        if step > 0:
            nxt = next((f for f in FPS_PRESETS if f > cur + 1e-3), FPS_PRESETS[-1])
        else:
            nxt = next((f for f in reversed(FPS_PRESETS) if f < cur - 1e-3), FPS_PRESETS[0])
        self.set_fps(nxt)
        self.statusBar().showMessage(f"FPS {fps_label(nxt)}", 2000)

    def _set_play_all(self, value: bool) -> None:
        self.prefs.play_all_frames = value
        self.playback.play_all_frames = value

    def _set_continuous(self, on: bool) -> None:
        self.prefs.playlist_continuous = on

    def set_time_mode(self, mode: str) -> None:
        self.prefs.time_display = mode
        self.transport.set_time_mode(mode)
        self.timeline.set_time_mode(mode)
        if self.a is not None:
            pb = self.playback
            self.transport.set_clip_info(self.a.first, self.a.last, pb.fps, pb.in_point, pb.out_point)
        self.transport.set_frame(self.playback.frame)

    def goto_dialog(self) -> None:
        if self.a is None:
            return
        f, ok = QInputDialog.getInt(self, "프레임으로 이동", "프레임 번호", self.playback.frame, self.a.first, self.a.last)
        if ok:
            self.playback.seek(f)

    def _timeline_seek(self, frame: int) -> None:
        self.playback.seek(frame)

    def _scrub_start(self) -> None:
        self._scrub_resume = self.playback.direction
        if self._scrub_resume:
            self.playback.stop()

    def _scrub_end(self) -> None:
        if self._scrub_resume:
            self.playback.play(self._scrub_resume)
        self._scrub_resume = 0

    def _timeline_hover(self, frame: int, gx: int) -> None:
        self._hover_frame = frame
        if frame < 0 or self.a is None:
            self.thumb_popup.hide()
            return
        img = self.thumbs.request(self.a, frame, 176)
        label = format_frame(frame, self.prefs.time_display, self.playback.fps, self.a.first)
        if self.prefs.time_display != "frames":
            label += f"  ·  {frame}"
        top = self.timeline.mapToGlobal(QPoint(0, 0)).y()
        self.thumb_popup.show_at(gx, top, label, img)

    def _on_thumb(self, sid: int, frame: int, width: int, img) -> None:
        if width == self._thumb_w():
            src = next((s for s in self.sources if s.id == sid), None)
            if src is not None and frame == src.first:
                self.playlist.set_thumbnail(sid, img)
        if width == 176 and self.a is not None and sid == self.a.id and frame == self._hover_frame:
            if self.thumb_popup.isVisible():
                self.thumb_popup.set_image(img)

    # ================================================================ audio

    def _track_time(self, src, frame: int) -> float:
        tr = src.audio
        fps = src.info.fps or src.fps
        return (frame - src.first) / fps - (tr.start if tr else 0.0) - src.audio_offset / fps

    def _audio_start(self, frame: int, direction: int) -> None:
        a = self.a
        self.playback.audio_elapsed = None
        if a is None or a.audio is None or direction <= 0 or self.audio.muted:
            self.audio.stop()
            return
        native = a.info.fps or a.fps
        if abs(self.playback.fps - native) > 0.01:
            self.audio.stop()
            return
        t0 = self._track_time(a, frame)
        if not self.audio.play(a.audio, t0):
            return

        def elapsed(t0=t0):
            pos = self.audio.position()
            return None if pos is None else pos - t0

        self.playback.audio_elapsed = elapsed

    def _audio_stop(self) -> None:
        self.audio.stop()
        self.playback.audio_elapsed = None

    def _on_audio_loaded(self, sid: int, track) -> None:
        src = next((s for s in self.sources if s.id == sid), None)
        if src is None:
            return
        src.audio = track
        if track is None:
            log.warning("오디오를 읽지 못했습니다: %s", src.audio_path)
            return
        log.info("오디오 준비됨: %s (%.1f초)", os.path.basename(track.path), track.duration)
        if src is self.a:
            self._update_timeline_audio()
            if self.playback.playing:
                self.playback.play(self.playback.direction)

    def _update_timeline_audio(self) -> None:
        a = self.a
        if a is None or a.audio is None:
            self.timeline.set_audio(None)
            return
        tr = a.audio
        fps = a.info.fps or a.fps
        self.timeline.set_audio(tr.peaks(1600), -(tr.start * fps + a.audio_offset), tr.duration * fps)

    def set_volume(self, v: float) -> None:
        self.prefs.volume = v
        self.audio.set_volume(v)

    def set_muted(self, muted: bool) -> None:
        self.prefs.muted = muted
        self.audio.set_muted(muted)
        self.transport.set_volume(self.audio.volume, muted)
        if self.playback.playing:
            self.playback.play(self.playback.direction)

    # ================================================================ compare

    def set_compare_mode(self, mode: str) -> None:
        if mode not in COMPARE_MODES:
            return
        if mode != "A" and self.compare_slots[0] is None:
            others = [s for s in self.sources if s is not self.a]
            if others:
                self.compare_slots[0] = others[0]
            else:
                self.statusBar().showMessage("비교하려면 클립을 두 개 이상 여세요.", 4000)
                mode = "A"
        if mode == "tile":
            others = [s for s in self.sources if s is not self.a and s not in self.compare_slots]
            for i in (1, 2):
                if self.compare_slots[i] is None and others:
                    self.compare_slots[i] = others.pop(0)
        self.compare_mode = mode
        self.viewer.compare_mode = mode
        self.compare_seg.set_value(mode)
        self._prefetch_sig = None
        self.viewer._auto_fit = True
        self.viewer._pending_fit = True
        self._last_frames = {k: v for k, v in self._last_frames.items() if k == 0}
        self._update_compare_panel()
        self._refresh_view()
        self.viewer._update_cursor()

    def set_compare_slot(self, index: int, src, auto_mode: bool = False) -> None:
        if src is self.a and src is not None:
            return
        self.compare_slots[index] = src
        self._last_frames.pop(index + 1, None)
        if auto_mode:
            if src is None:
                self.set_compare_mode("A")
                return
            if self.compare_mode == "A":
                self.set_compare_mode("wipe")
                return
        self._prefetch_sig = None
        self._update_compare_panel()
        self._refresh_view()

    def swap_ab(self) -> None:
        b = self.compare_slots[0]
        if b is None or self.a is None:
            return
        a = self.a
        self.compare_slots[0] = a
        self.a = None
        self.set_a(b)
        self.compare_slots[0] = a
        self._update_compare_panel()
        self._refresh_view()

    def _set_align(self, mode: str) -> None:
        self.compare_align = mode
        self._prefetch_sig = None
        self._refresh_view()

    def _set_offset(self, n: int) -> None:
        self.compare_offset = n
        self._prefetch_sig = None
        self._refresh_view()

    def _update_compare_panel(self) -> None:
        self.compare_panel.set_state(self.sources, self.a, self.compare_slots, self.compare_mode, self.viewer,
                                     self.compare_align, self.compare_offset)
        self.playlist.set_current(self.a, self._visible_compare())

    # ================================================================ color

    def _set_display(self, **kw) -> None:
        d = self.viewer.display
        for k, val in kw.items():
            setattr(d, k, val)
        self._on_display_changed()
        self.color_panel.refresh_values()
        if "alpha_mode" in kw:
            self.color_panel.refresh(self.a)

    def _on_display_changed(self) -> None:
        d = self.viewer.display
        self.exposure_field.setValue(d.exposure)
        self.gamma_field.setValue(d.gamma)
        self.channel_seg.set_value(d.channel)
        self._fill_display_combos()
        a = self.alpha_actions.get(d.alpha_mode)
        if a:
            a.setChecked(True)
        for s in self.sources:
            self._update_thumb_fn(s)
        self.viewer.display_changed()
        self._update_hud()

    def _fill_display_combos(self, force: bool = False) -> None:
        d = self.viewer.display
        key = (self.colors.uri, d.display, d.view)
        if not force and key == getattr(self, "_display_combo_key", None):
            return
        self._display_combo_key = key
        self.display_combo.blockSignals(True)
        self.display_combo.clear()
        self.display_combo.addItems(self.colors.displays())
        self.display_combo.setCurrentText(d.display)
        self.display_combo.blockSignals(False)
        self.view_combo.blockSignals(True)
        self.view_combo.clear()
        self.view_combo.addItems(self.colors.views(d.display))
        self.view_combo.setCurrentText(d.view)
        self.view_combo.blockSignals(False)

    def set_display_view(self, display: str | None, view: str | None) -> None:
        d = self.viewer.display
        if display:
            d.display = display
            views = self.colors.views(display)
            if d.view not in views:
                d.view = self.colors.default_view(display)
        if view:
            d.view = view
        self.color_panel.refresh(self.a)
        self._on_display_changed()

    def _fill_display_menu(self) -> None:
        m = self.display_menu
        m.clear()
        d = self.viewer.display
        for disp in self.colors.displays():
            sub = m.addMenu(disp)
            g = QActionGroup(sub)
            for view in self.colors.views(disp):
                a = sub.addAction(view)
                a.setCheckable(True)
                a.setChecked(disp == d.display and view == d.view)
                g.addAction(a)
                a.triggered.connect(lambda _=False, x=disp, y=view: self.set_display_view(x, y))

    def set_channel(self, ch: str) -> None:
        d = self.viewer.display
        d.channel = "rgb" if (d.channel == ch and ch != "rgb") else ch
        self._on_display_changed()
        self.statusBar().showMessage(f"채널: {dict(CHANNEL_KEYS)[d.channel]}", 1500)

    def reset_color(self) -> None:
        d = self.viewer.display
        d.reset_grade()
        d.channel = "rgb"
        self.color_panel.refresh(self.a)
        self._on_display_changed()

    # ================================================================ view

    def _toggle_view(self, attr: str) -> None:
        v = self.viewer
        setattr(v, attr, not getattr(v, attr))
        v.update()
        self._sync_view_actions()

    def _sync_view_actions(self) -> None:
        v = self.viewer
        for aid, attr in (("view.mirror_x", "mirror_x"), ("view.mirror_y", "mirror_y"), ("view.hud", "hud_enabled"),
                          ("view.safe_areas", "show_safe_areas"), ("view.display_window", "show_display_window"),
                          ("view.data_window", "show_data_window"), ("view.filter", "filter_linear"),
                          ("view.env_map", "env_mode"), ("draw.toggle", "show_annotations")):
            act = self.actions_by_id.get(aid)
            if act is not None:
                act.blockSignals(True)
                act.setChecked(bool(getattr(v, attr)))
                act.blockSignals(False)
        a = self.bg_actions.get(v.background) if hasattr(self, "bg_actions") else None
        if a:
            a.setChecked(True)
        a = self.aspect_actions.get(v.aspect_guide) if hasattr(self, "aspect_actions") else None
        if a:
            a.setChecked(True)
        act = self.actions_by_id.get("view.side_panel")
        if act:
            act.setChecked(self.side.isVisible())

    def set_background(self, key: str) -> None:
        v = self.viewer
        if key == "custom":
            c = QColorDialog.getColor(v.background_color, self, "배경색")
            if not c.isValid():
                self._sync_view_actions()
                return
            v.background_color = c
            self.prefs.background_color = c.name()
        v.background = key
        v.update()
        self._sync_view_actions()

    def set_aspect_guide(self, key: str) -> None:
        self.viewer.aspect_guide = key
        self.prefs.safe_area_ratio = key
        self.viewer.update()

    def toggle_env(self) -> None:
        v = self.viewer
        v.env_mode = not v.env_mode
        v.update()
        self.env_panel.sync()
        self._sync_view_actions()
        if v.env_mode:
            self.statusBar().showMessage("360° 보기: 드래그로 둘러보기 · 휠로 시야각", 4000)

    def _zoom_text(self, text: str) -> None:
        t = text.strip().replace("%", "")
        if t in ("맞춤", "fit", ""):
            self.viewer.fit()
            return
        try:
            self.viewer.set_zoom(float(t) / 100.0)
        except ValueError:
            pass

    def _on_zoom_changed(self, z: float) -> None:
        if not self.zoom_combo.lineEdit().hasFocus():
            self.zoom_combo.setEditText(f"{z * 100:.0f}%")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            if self._presentation:
                self.toggle_presentation()
                return
            self.showNormal()
            if getattr(self, "_was_maximized", False):
                self.showMaximized()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        self._act("view.fullscreen").setChecked(self.isFullScreen())

    def toggle_presentation(self) -> None:
        if not self._presentation:
            self._pre_presentation_state = (self.side.isVisible(), self.bottom.isVisible(), self.isFullScreen(),
                                            self.isMaximized())
            self._presentation = True
            for w in (self.side, self.rail, self.bottom, self.toolbar, self.menuBar(), self.statusBar(),
                      self.draw_bar):
                w.hide()
            if not self.isFullScreen():
                self.showFullScreen()
        else:
            self._presentation = False
            side, bottom, full, maxed = self._pre_presentation_state or (True, True, False, False)
            for w in (self.rail, self.toolbar, self.menuBar(), self.statusBar(), self.draw_bar):
                w.show()
            self.side.setVisible(side)
            self.bottom.setVisible(bottom)
            if not full:
                self.showNormal()
                if maxed:
                    self.showMaximized()
        self._act("view.presentation").setChecked(self._presentation)
        self._act("view.fullscreen").setChecked(self.isFullScreen())
        self.viewer.setFocus()

    def toggle_on_top(self) -> None:
        on = not bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self._act("view.on_top").setChecked(on)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            if self._presentation:
                self.toggle_presentation()
                return
            if self.isFullScreen():
                self.toggle_fullscreen()
                return
            if self.viewer.tool:
                self.set_tool("")
                return
        super().keyPressEvent(ev)

    # ---------------------------------------------------------------- side panel

    def show_panel(self, key: str, toggle: bool = False) -> None:
        if key not in self.panels:
            return
        if toggle and self.side.isVisible() and self.prefs.panel == key:
            self.set_side_visible(False)
            return
        self.prefs.panel = key
        self.stack.setCurrentWidget(self._panel_pages[key])
        title = next(t for k, t, _i in PANELS if k == key)
        self.side_header.title.setText(title)
        for k, b in self.rail_buttons.items():
            b.setChecked(k == key and True)
        self.set_side_visible(True)
        if key == "annotate" and self.a is not None:
            self.annotate_panel.set_frames(self.a.annotations, self.playback.frame)
        if key == "compare":
            self._update_compare_panel()
        if key == "info" and hasattr(self.info_panel, "set_source"):
            self.info_panel.set_source(self.a, None)
        if key == "scopes":
            self.viewer.request_sample()

    def _rail_clicked(self, key: str) -> None:
        if self.side.isVisible() and self.prefs.panel == key:
            self.set_side_visible(False)
        else:
            self.show_panel(key)

    def set_side_visible(self, visible: bool) -> None:
        self.side.setVisible(visible)
        for k, b in self.rail_buttons.items():
            b.setChecked(visible and k == self.prefs.panel)
        act = self.actions_by_id.get("view.side_panel") if hasattr(self, "actions_by_id") else None
        if act:
            act.setChecked(visible)
        self._on_scopes_active(visible and self.prefs.panel == "scopes")

    def _on_scopes_active(self, active: bool) -> None:
        active = active and self.side.isVisible() and self.prefs.panel == "scopes"
        self.viewer.scopes_enabled = active
        if active:
            self.viewer.request_sample()

    def _on_display_sample(self, img) -> None:
        if hasattr(self.scopes_panel, "set_image"):
            self.scopes_panel.set_image(img)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.viewer_box and ev.type() == ev.Type.Resize:
            self._place_draw_bar()
        return super().eventFilter(obj, ev)

    def _place_draw_bar(self) -> None:
        bar = self.draw_bar
        bar.adjustSize()
        h = self.viewer_box.height()
        bar.move(12, max(8, (h - bar.height()) // 2))
        bar.raise_()

    # ================================================================ annotations

    def set_tool(self, tool: str) -> None:
        self.viewer.set_tool(tool)
        self.draw_bar.set_tool(tool)
        self.annotate_panel.set_tool(tool)
        if tool == "area":
            self.show_panel("area")
        elif tool and self.prefs.panel not in ("annotate",) and self.side.isVisible() and self.prefs.panel == "area":
            pass

    def _on_draw_style(self) -> None:
        color, size, fill, hold, ghost = self.annotate_panel.style()
        v = self.viewer
        v.pen_color, v.pen_size, v.pen_fill, v.pen_hold, v.ghost_frames = color, size, fill, hold, ghost
        self.prefs.pen_color, self.prefs.pen_size, self.prefs.ghost_frames = color, size, ghost
        self.draw_bar.set_color(color)
        v.update()

    def _on_shape(self, shape: Shape) -> None:
        if self.a is None:
            return
        self.a.annotations.add(self.playback.frame, shape)
        self._annotations_changed()

    def _annotations_changed(self) -> None:
        a = self.a
        if a is None:
            return
        self.timeline.set_marks(a.annotations.annotated_frames())
        if self.prefs.panel == "annotate":
            self.annotate_panel.set_frames(a.annotations, self.playback.frame)
        self.viewer.update()

    def annotation_undo(self) -> None:
        if self.a is None:
            return
        f = self.a.annotations.undo()
        if f is not None and f != self.playback.frame:
            self.playback.seek(f)
        self._annotations_changed()

    def annotation_redo(self) -> None:
        if self.a is None:
            return
        f = self.a.annotations.redo()
        if f is not None and f != self.playback.frame:
            self.playback.seek(f)
        self._annotations_changed()

    def annotation_clear_frame(self) -> None:
        if self.a is None:
            return
        self.a.annotations.clear_frame(self.playback.frame)
        self._annotations_changed()

    def annotation_clear_all(self) -> None:
        if self.a is None or self.a.annotations.is_empty():
            return
        r = QMessageBox.question(self, APP_NAME, "이 클립의 주석과 노트를 모두 지울까요? 되돌릴 수 없습니다.")
        if r == QMessageBox.Yes:
            self.a.annotations.clear_all()
            self._annotations_changed()

    def annotation_jump(self, step: int) -> None:
        if self.a is None:
            return
        f = self.a.annotations.next_frame(self.playback.frame, step)
        if f is None:
            self.statusBar().showMessage("더 이상 주석이 있는 프레임이 없습니다.", 2000)
            return
        self.playback.seek(f)

    def _on_note(self, text: str) -> None:
        if self.a is None:
            return
        self.a.annotations.set_note(self.playback.frame, text)
        self._annotations_changed()

    def _set_annotations_visible(self, on: bool) -> None:
        self.viewer.show_annotations = on
        self.annotate_panel.visible.blockSignals(True)
        self.annotate_panel.visible.setChecked(on)
        self.annotate_panel.visible.blockSignals(False)
        self._sync_view_actions()
        self.viewer.update()

    # ================================================================ pixel info

    def _on_pixel(self, info: dict) -> None:
        if hasattr(self.area_panel, "set_pixel"):
            self.area_panel.set_pixel(info)
        if not info or info.get("raw") is None:
            self.pixel_label.setText("")
            self.pixel_swatch.setStyleSheet("background: transparent;")
            return
        names = info.get("names") or []
        raw = info["raw"]
        short = [n.split(".")[-1] for n in names] or ["R", "G", "B", "A"][: len(raw)]
        vals = "  ".join(f"{n} {v:.4f}" for n, v in zip(short, raw))
        slot = "AB CD"[info.get("slot", 0)] if len(self.viewer.slots) > 1 else ""
        text = f"{slot + ' ' if slot.strip() else ''}x {info['x']:>5}  y {info['y']:>5}   {vals}"
        disp = info.get("display")
        if disp:
            r, g, b = (max(0, min(255, int(round(c * 255)))) for c in disp[:3])
            self.pixel_swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border-radius: 4px;"
                                            f" border: 1px solid {PAL.line2};")
            text += f"    화면 {r} {g} {b}"
        self.pixel_label.setText(text)

    def _on_area(self, rect) -> None:
        if not hasattr(self.area_panel, "set_area"):
            return
        vis = self.viewer.slots
        if rect is None or not vis or vis[0].frame is None:
            self.area_panel.set_area(None, None, None, [])
            return
        f = vis[0].frame
        x0, y0, x1, y1 = rect
        raw = f.region(x0, y0, x1, y1)
        disp = self.viewer.display_region(0, x0, y0, x1, y1)
        self.area_panel.set_area(rect, raw, disp, list(f.channel_names))

    # ================================================================ HUD

    def _update_hud(self) -> None:
        v = self.viewer
        a = self.a
        if a is None or not v.hud_enabled:
            v.hud = {}
            v.update()
            return
        items = set(self.prefs.hud_items)
        pb = self.playback
        f = pb.frame
        tl, tr, bl, br = [], [], [], []
        if "name" in items:
            tl.append(a.seq.pattern if a.seq and a.kind == "sequence" else a.name)
        if "directory" in items:
            tl.append(a.directory)
        if "frame" in items:
            lo, hi = pb.range()
            tl.append(f"{f}   [{lo}–{hi}]")
        if "timecode" in items:
            tl.append(frames_to_timecode(f - a.first, pb.fps))
        if "resolution" in items:
            w, h = a.resolution
            par = f"  ·  PAR {a.info.par:.3g}" if abs(a.info.par - 1) > 1e-3 else ""
            tr.append(f"{w}×{h}{par}")
        if "fps" in items:
            tr.append(f"{fps_label(pb.fps)} fps")
        if "layer" in items and len(a.layers) > 1:
            bl.append(f"레이어  {a.layer.name}")
        ch = v.display.channel
        if ch != "rgb":
            bl.append(f"채널  {dict(CHANNEL_KEYS)[ch]}")
        if "colorspace" in items:
            bl.append(f"{a.colorspace}  →  {v.display.view}")
        if "exposure" in items:
            d = v.display
            if d.exposure or d.gamma != 1.0:
                br.append(f"노출 {d.exposure:+.2f}  ·  감마 {d.gamma:.2f}")
        if "memory" in items:
            br.append(f"캐시 {human_bytes(self.cache.used)}")
        if self.compare_mode != "A" and self._visible_compare():
            names = " · ".join(s.name for s in self._visible_compare())
            br.append(f"{COMPARE_LABELS[self.compare_mode][2]}  ·  {names}")
        v.hud = {"tl": tl, "tr": tr, "bl": bl, "br": br}
        v.update()

    # ================================================================ session

    def _fill_recent(self) -> None:
        m = self.recent_menu
        m.clear()
        items = [p for p in self.prefs.recent_files if p]
        if not items:
            m.addAction("없음").setEnabled(False)
            return
        for p in items:
            a = m.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, x=p: self.open_paths([x]))
        m.addSeparator()
        m.addAction("목록 지우기", lambda: (self.prefs.recent_files.clear(), self.store.save()))

    def _fill_recent_sessions(self) -> None:
        m = self.recent_session_menu
        m.clear()
        items = [p for p in self.prefs.recent_sessions if p]
        if not items:
            m.addAction("없음").setEnabled(False)
            return
        for p in items:
            a = m.addAction(os.path.basename(p))
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, x=p: self.open_session(x))

    def open_session_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "세션 열기", self._start_dir(),
                                              f"COC_SEQ 세션 (*{SESSION_EXT});;모든 파일 (*)")
        if path:
            self.open_session(path)

    def open_session(self, path: str) -> None:
        from cocseq.session import load_session

        try:
            missing = load_session(self, path)
        except Exception as exc:
            log.exception("session load")
            QMessageBox.warning(self, APP_NAME, f"세션을 열 수 없습니다.\n{exc}")
            return
        self.session_path = path
        self.prefs.add_recent(path, session=True)
        self.store.save()
        self._update_title()
        if missing:
            QMessageBox.information(self, APP_NAME, "다음 파일을 찾지 못했습니다:\n\n" + "\n".join(missing[:20]))
        self.statusBar().showMessage(f"세션 열림: {os.path.basename(path)}", 4000)

    def after_session_load(self) -> None:
        self.color_panel.refresh(self.a)
        self._on_display_changed()
        self._sync_view_actions()
        self.env_panel.sync()
        self._update_compare_panel()
        if self.a is not None:
            self._annotations_changed()

    def save_session(self) -> None:
        if not self.session_path:
            self.save_session_as()
            return
        from cocseq.session import save_session

        try:
            save_session(self, self.session_path)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"세션을 저장하지 못했습니다.\n{exc}")
            return
        self.prefs.add_recent(self.session_path, session=True)
        self.store.save()
        self.statusBar().showMessage(f"세션 저장: {os.path.basename(self.session_path)}", 4000)
        self._update_title()

    def save_session_as(self) -> None:
        start = self.session_path or os.path.join(self._start_dir(), (self.a.name if self.a else "review") + SESSION_EXT)
        path, _ = QFileDialog.getSaveFileName(self, "세션 저장", start, f"COC_SEQ 세션 (*{SESSION_EXT})")
        if not path:
            return
        if not path.lower().endswith(SESSION_EXT):
            path += SESSION_EXT
        self.session_path = path
        self.save_session()

    # ================================================================ dialogs

    def show_preferences(self, page: str = "") -> None:
        try:
            from cocseq.ui.dialogs.prefs_dialog import PreferencesDialog
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"환경 설정 창을 열 수 없습니다: {exc}")
            return
        dlg = PreferencesDialog(self.prefs, self)
        if page and hasattr(dlg, "set_page"):
            dlg.set_page(page)
        if dlg.exec():
            restart = dlg.restart_required() if hasattr(dlg, "restart_required") else False
            old = self.prefs
            new = dlg.result_prefs()
            color_changed = (old.ocio_config, old.ocio_prefer_env) != (new.ocio_config, new.ocio_prefer_env)
            self.store.apply(new)
            self.prefs = self.store.prefs
            if color_changed:
                self.colors.load(new.ocio_config, new.ocio_prefer_env)
                d = self.viewer.display
                d.display, d.view = self.colors.resolve_display_view(new.display, new.view)
                for s in self.sources:
                    s.colorspace = self.colors.resolve_colorspace(s.colorspace) or self.colors.default_colorspace(s, new)
                self.viewer.invalidate_color()
                self._update_clip_widgets()
            self.apply_prefs()
            self._on_display_changed()
            self._prefetch_sig = None
            self._update_prefetch()
            if restart:
                QMessageBox.information(self, APP_NAME, "일부 설정은 프로그램을 다시 시작하면 적용됩니다.")

    def show_hotkeys(self) -> None:
        try:
            from cocseq.ui.dialogs.hotkeys_dialog import HotkeysDialog
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"단축키 창을 열 수 없습니다: {exc}")
            return
        dlg = HotkeysDialog(dict(self.prefs.hotkeys), self)
        if dlg.exec():
            self.prefs.hotkeys = dlg.result_overrides()
            self.store.save()
            self.apply_hotkeys()

    def show_about(self) -> None:
        try:
            from cocseq.ui.dialogs.about import AboutDialog
        except Exception as exc:
            QMessageBox.about(self, APP_NAME, f"{APP_NAME} {__version__}\n{exc}")
            return
        AboutDialog(gl_info=self.gl_info, parent=self).exec()

    def export_dialog(self) -> None:
        if self.a is None:
            return
        self.playback.stop()
        try:
            from cocseq.export import export_with_progress
            from cocseq.ui.dialogs.export_dialog import ExportDialog
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"내보내기를 사용할 수 없습니다: {exc}")
            return
        dlg = ExportDialog(self.a, self.viewer, self.playback.frame, self)
        if dlg.exec():
            export_with_progress(self, dlg.settings(), self.a, self.viewer)

    def save_frame(self) -> None:
        if self.a is None or not self.viewer.slots or self.viewer.slots[0].frame is None:
            return
        try:
            from cocseq.export import save_current_frame
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"프레임 저장을 사용할 수 없습니다: {exc}")
            return
        path = save_current_frame(self, self.viewer, self.a, self.viewer.slots[0].frame,
                                  with_annotations=self.viewer.show_annotations)
        if path:
            self.statusBar().showMessage(f"저장: {path}", 5000)

    def export_pdf(self) -> None:
        if self.a is None:
            return
        if self.a.annotations.is_empty():
            QMessageBox.information(self, APP_NAME, "이 클립에는 주석이 없습니다.")
            return
        try:
            from cocseq.export import export_annotations_pdf
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"PDF 내보내기를 사용할 수 없습니다: {exc}")
            return
        path = export_annotations_pdf(self, self.viewer, self.a)
        if path:
            self.statusBar().showMessage(f"PDF 저장: {path}", 5000)

    # ================================================================ misc

    def _viewer_menu(self, pos: QPoint) -> None:
        m = QMenu(self)
        A = self._act
        if self.a is None:
            m.addAction(A("file.open"))
            m.addAction(A("file.open_folder"))
            m.exec(pos)
            return
        for aid in ("play.toggle", "view.fit", "view.zoom_1"):
            m.addAction(A(aid))
        m.addSeparator()
        ch = m.addMenu("채널")
        for key, _ in CHANNEL_KEYS:
            ch.addAction(A(f"ch.{key}"))
        if len(self.a.layers) > 1:
            lm = m.addMenu("레이어")
            for l in self.a.layers:
                act = lm.addAction(l.label)
                act.setCheckable(True)
                act.setChecked(l.name == self.a.layer.name)
                act.triggered.connect(lambda _=False, n=l.name: self.set_layer(n))
        cm = m.addMenu("비교")
        for mode in COMPARE_MODES:
            cm.addAction(A(f"compare.{mode}"))
        m.addSeparator()
        for aid in ("view.mirror_x", "view.mirror_y", "view.safe_areas", "view.hud"):
            m.addAction(A(aid))
        bg = m.addMenu("배경")
        for key, label in BACKGROUNDS:
            bg.addAction(self.bg_actions[key])
        m.addSeparator()
        for aid in ("file.save_frame", "file.export", "file.reveal", "file.copy_path"):
            m.addAction(A(aid))
        m.addSeparator()
        m.addAction(A("view.presentation"))
        m.exec(pos)

    def _on_gl_ready(self, info: str) -> None:
        self.gl_info = info
        short = info.split(" / ")[0] if " / " in info else info
        self.gl_label.setText(short[:48])
        self.gl_label.setToolTip(info)
        if "실패" in info and not os.environ.get("COCSEQ_TESTING"):
            r = QMessageBox.question(
                self, APP_NAME,
                f"{info}\n\n그래픽 드라이버가 OpenGL 3.3을 지원하지 않거나 원격 데스크톱 환경일 수 있습니다.\n"
                "소프트웨어 렌더링으로 다시 시작할까요? (느리지만 대부분의 환경에서 동작합니다)")
            if r == QMessageBox.Yes:
                args = [a for a in sys.argv[1:] if a != "--software-gl"] + ["--software-gl"]
                exe = sys.executable
                cmd = [exe] + (args if getattr(sys, "frozen", False) else [sys.argv[0]] + args)
                subprocess.Popen(cmd)
                QTimer.singleShot(0, self.close)

    def _update_all(self) -> None:
        a = self.a
        pb = self.playback
        if a is not None:
            self.transport.set_clip_info(a.first, a.last, pb.fps, pb.in_point, pb.out_point)
            self.timeline.set_inout(pb.in_point, pb.out_point)
            self.timeline.set_marks(a.annotations.annotated_frames())
        else:
            self.transport.set_clip_info(1, 1, pb.fps, None, None)
            self.transport.range_label.setText("")
            self.timeline.set_marks([])
            self.color_panel.refresh(None)
            if hasattr(self.info_panel, "set_source"):
                self.info_panel.set_source(None, None)
        self._fill_display_combos()
        self._on_display_changed()
        self._update_compare_panel()
        self.playlist.refresh()
        self._update_title()
        self._refresh_view()
        for w in (self.exposure_field, self.gamma_field, self.compare_seg, self.channel_seg):
            w.setEnabled(True)

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.open_paths(paths)

    def closeEvent(self, ev) -> None:
        self.playback.stop()
        try:
            self._save_state()
        except Exception:
            log.exception("saving state")
        self.prefetch.shutdown()
        self.thumbs.shutdown()
        self.audio.shutdown()
        for s in self.sources:
            s.close()
        super().closeEvent(ev)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        QTimer.singleShot(0, self._place_draw_bar)
        if sys.platform == "win32":
            _dark_title_bar(self)


COMPARE_LABELS = {
    "A": ("a-letter", "A", "A만 보기"), "B": ("b-letter", "B", "B만 보기"), "wipe": ("wipe", "와이프", "와이프 (W)"),
    "overlay": ("overlay", "오버레이", "오버레이"), "difference": ("difference", "차이", "차이"),
    "horizontal": ("side-by-side", "좌우", "좌우 나란히"), "vertical": ("top-bottom", "위아래", "위아래 나란히"),
    "tile": ("tile", "타일", "타일"),
}


class CompareButton(QToolButton):
    """Compact compare-mode picker for the top bar."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "text")
        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(16, 16))
        self.setToolTip("비교 방식")
        menu = QMenu(self)
        group = QActionGroup(menu)
        self._acts = {}
        for key in COMPARE_MODES:
            icon_name, _short, label = COMPARE_LABELS[key]
            a = menu.addAction(icons.icon(icon_name, size=16), label)
            a.setCheckable(True)
            group.addAction(a)
            a.triggered.connect(lambda _=False, k=key: self.changed.emit(k))
            self._acts[key] = a
        self.setMenu(menu)
        self.setMinimumWidth(96)
        self.set_value("A")

    def set_value(self, key: str) -> None:
        icon_name, short, label = COMPARE_LABELS.get(key, COMPARE_LABELS["A"])
        self.setIcon(icons.icon(icon_name, size=16))
        self.setText(f"비교 · {short}" if key != "A" else "비교 끔")
        if key in self._acts:
            self._acts[key].setChecked(True)


def _dark_title_bar(win: QWidget) -> None:
    """Ask Windows 10/11 for a dark title bar so the frame matches the app."""
    try:
        import ctypes

        hwnd = int(win.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        color = ctypes.c_int(0x00181311)  # COLORREF 0x00BBGGRR of #111318
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass
