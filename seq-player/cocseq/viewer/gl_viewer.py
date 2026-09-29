"""The OpenGL image viewer: color pipeline, zoom/pan, compare modes and overlays."""

from __future__ import annotations

import ctypes
import logging
import math
import time
from dataclasses import dataclass, field, fields

import numpy as np
from OpenGL import GL
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QKeyEvent, QPainter, QPainterPath, QPen,
                           QPolygonF, QTransform)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLineEdit

from cocseq.annotations import Shape, render_layer
from cocseq.color.ocio_mgr import ColorManager, ColorPipeline
from cocseq.media.frame import Frame
from cocseq.theme import PAL, mono_font, ui_font
from cocseq.viewer.shaders import COMPOSITE_FRAGMENT, VERTEX, adapt, color_program_source, current_glsl_version

log = logging.getLogger(__name__)

COMPARE_MODES = ["A", "B", "wipe", "overlay", "difference", "horizontal", "vertical", "tile"]
CHANNELS = ["rgb", "r", "g", "b", "a", "luma"]
_CHANNEL_INDEX = {n: i for i, n in enumerate(CHANNELS)}
_MODE_INDEX = {"A": 0, "B": 0, "wipe": 1, "overlay": 2, "difference": 3, "horizontal": 4, "vertical": 4, "tile": 4}

_GL_FORMATS = {1: GL.GL_RED, 2: GL.GL_RG, 3: GL.GL_RGB, 4: GL.GL_RGBA}
_GL_INTERNAL = {
    np.dtype(np.uint8): ({1: GL.GL_R8, 2: GL.GL_RG8, 3: GL.GL_RGB8, 4: GL.GL_RGBA8}, GL.GL_UNSIGNED_BYTE),
    np.dtype(np.uint16): ({1: GL.GL_R16, 2: GL.GL_RG16, 3: GL.GL_RGB16, 4: GL.GL_RGBA16}, GL.GL_UNSIGNED_SHORT),
    np.dtype(np.float16): ({1: GL.GL_R16F, 2: GL.GL_RG16F, 3: GL.GL_RGB16F, 4: GL.GL_RGBA16F}, GL.GL_HALF_FLOAT),
    np.dtype(np.float32): ({1: GL.GL_R32F, 2: GL.GL_RG32F, 3: GL.GL_RGB32F, 4: GL.GL_RGBA32F}, GL.GL_FLOAT),
}


@dataclass
class DisplaySettings:
    """Viewer color settings shared by every clip on screen."""

    exposure: float = 0.0
    gamma: float = 1.0
    offset: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    hue: float = 0.0
    softclip: float = 0.0
    invert: bool = False
    levels: bool = False
    in_lo: float = 0.0
    in_hi: float = 1.0
    lv_gamma: float = 1.0
    out_lo: float = 0.0
    out_hi: float = 1.0
    channel: str = "rgb"
    video_levels: str = "auto"      # auto | legal
    unpremult: bool = False
    display: str = ""
    view: str = ""
    look: str = ""
    lut: str = ""
    lut_mode: str = "after"         # after | replace
    alpha_mode: str = "none"        # none | straight | premult

    def signature(self) -> tuple:
        return tuple(getattr(self, f.name) for f in fields(self))

    def reset_grade(self) -> None:
        for f in ("exposure", "gamma", "offset", "contrast", "saturation", "hue", "softclip", "invert",
                  "levels", "in_lo", "in_hi", "lv_gamma", "out_lo", "out_hi"):
            setattr(self, f, DisplaySettings.__dataclass_fields__[f].default)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def apply_dict(self, d: dict) -> None:
        for f in fields(self):
            if f.name in d:
                try:
                    setattr(self, f.name, type(getattr(self, f.name))(d[f.name]))
                except (TypeError, ValueError):
                    pass


@dataclass
class SlotInput:
    source: object              # MediaSource
    frame: Frame | None


@dataclass
class _SlotLayout:
    disp: QRectF                # display window in canvas coordinates
    data: QRectF                # data window in canvas coordinates
    sx: float
    sy: float
    ox: float                   # display window origin in image pixels
    oy: float


@dataclass
class _GLSlot:
    tex: int = 0
    tex_shape: tuple = ()
    fbo: int = 0
    fbo_tex: int = 0
    fbo_size: tuple = (0, 0)
    sig: tuple = ()
    frame_ref: object = None


@dataclass
class _Program:
    pid: int
    uniforms: dict = field(default_factory=dict)
    textures: list = field(default_factory=list)   # (unit, target, tex_id, sampler)
    error: str = ""


def _hue_matrix(degrees: float) -> np.ndarray:
    """Rotation of colors around the grey axis."""
    if abs(degrees) < 1e-6:
        return np.eye(3, dtype=np.float32)
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    k = 1.0 / 3.0
    sq = math.sqrt(k)
    m = np.array([
        [c + (1 - c) * k, k * (1 - c) - sq * s, k * (1 - c) + sq * s],
        [k * (1 - c) + sq * s, c + k * (1 - c), k * (1 - c) - sq * s],
        [k * (1 - c) - sq * s, k * (1 - c) + sq * s, c + k * (1 - c)],
    ], dtype=np.float32)
    return m


def _compile(kind, src: str) -> int:
    sh = GL.glCreateShader(kind)
    GL.glShaderSource(sh, src)
    GL.glCompileShader(sh)
    if not GL.glGetShaderiv(sh, GL.GL_COMPILE_STATUS):
        msg = GL.glGetShaderInfoLog(sh)
        msg = msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg)
        GL.glDeleteShader(sh)
        raise RuntimeError(msg)
    return sh


def _link(vs_src: str, fs_src: str, glsl: int | None = None) -> int:
    if glsl is None:
        glsl = current_glsl_version()
    vs = _compile(GL.GL_VERTEX_SHADER, adapt(vs_src, glsl))
    fs = _compile(GL.GL_FRAGMENT_SHADER, adapt(fs_src, glsl))
    pid = GL.glCreateProgram()
    GL.glAttachShader(pid, vs)
    GL.glAttachShader(pid, fs)
    GL.glBindAttribLocation(pid, 0, "a_pos")
    if glsl < 330:
        GL.glBindFragDataLocation(pid, 0, "fragColor")
    GL.glLinkProgram(pid)
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    if not GL.glGetProgramiv(pid, GL.GL_LINK_STATUS):
        msg = GL.glGetProgramInfoLog(pid)
        msg = msg.decode(errors="replace") if isinstance(msg, bytes) else str(msg)
        GL.glDeleteProgram(pid)
        raise RuntimeError(msg)
    return pid


class ViewerWidget(QOpenGLWidget):
    pixelProbed = Signal(dict)
    areaSelected = Signal(object)          # (x0, y0, x1, y1) image pixels of clip A, or None
    zoomChanged = Signal(float)
    shapeFinished = Signal(object)         # annotations.Shape
    filesDropped = Signal(list)
    scrubRequested = Signal(int)           # frames to move
    contextMenuRequested = Signal(QPoint)
    displaySample = Signal(object)         # float32 (h, w, 4) display-referred pixels of clip A
    wipeChanged = Signal()
    glReady = Signal(str)
    envChanged = Signal()

    MAX_SLOTS = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(200, 150)

        self.colors: ColorManager | None = None
        self.display = DisplaySettings()
        self.slots: list[SlotInput] = []
        self.compare_mode = "A"
        self.wipe_pos = QPointF(0.5, 0.5)      # relative to clip A display window
        self.wipe_angle = 0.0                   # degrees, 0 = vertical line
        self.overlay_opacity = 0.5
        self.diff_gain = 1.0

        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.rotation = 0
        self.mirror_x = False
        self.mirror_y = False
        self.filter_linear = True
        self.background = "dark"
        self.background_color = QColor("#202020")
        self.checker_size = 16
        self._auto_fit = True

        self.env_mode = False
        self.env_yaw = 0.0
        self.env_pitch = 0.0
        self.env_fov = 90.0

        self.show_safe_areas = False
        self.aspect_guide = ""
        self.show_display_window = False
        self.show_data_window = False
        self.hud_enabled = True
        self.hud: dict[str, list[str]] = {}
        self.loading = False
        self.empty_hint = True

        self.tool = ""                          # "", pen, eraser, line, arrow, rect, ellipse, text, area
        self.pen_color = "#FF4D5E"
        self.pen_size = 4.0
        self.pen_fill = False
        self.pen_hold = 1
        self.annotation_store = None
        self.annotation_frame = 0
        self.ghost_frames = 0
        self.show_annotations = True
        self.area: tuple | None = None
        self.scopes_enabled = False

        self._drawing: Shape | None = None
        self._drag_mode = ""
        self._drag_start = QPointF()
        self._drag_pan = QPointF()
        self._drag_value = None
        self._space_down = False
        self._last_mouse = QPointF(-1, -1)
        self._text_edit: QLineEdit | None = None
        self._text_anchor = (0.0, 0.0)

        self._gl_ok = False
        self._gl_error = ""
        self._vao = 0
        self._vbo = 0
        self._composite: _Program | None = None
        self._programs: dict[tuple, _Program] = {}
        self._glslots: list[_GLSlot] = []
        self._export_slot: _GLSlot | None = None
        self._scratch_fbo = 0
        self._scratch_tex = 0
        self._scratch_size = (0, 0)
        self._pipe_errors: set[str] = set()
        self._sample_timer = QTimer(self)
        self._sample_timer.setSingleShot(True)
        self._sample_timer.setInterval(120)
        self._sample_timer.timeout.connect(self._emit_sample)
        self._sample_dirty = False
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(80)
        self._spin_timer.timeout.connect(self.update)
        self._layouts: list[_SlotLayout] = []
        self._pending_fit = False

    # ================================================================ public API

    def set_color_manager(self, cm: ColorManager) -> None:
        self.colors = cm
        self.invalidate_color()

    def invalidate_color(self) -> None:
        """Color config or pipelines changed: rebuild programs on the next paint."""
        self._pipe_errors.clear()
        if self._gl_ok:
            self.makeCurrent()
            for prog in self._programs.values():
                self._delete_program(prog)
            self._programs.clear()
            for s in self._glslots:
                s.sig = ()
            self.doneCurrent()
        self.update()

    def set_slots(self, slots: list[SlotInput]) -> None:
        prev_a = self.slots[0].source if self.slots else None
        self.slots = [s for s in slots[: self.MAX_SLOTS]]
        new_a = self.slots[0].source if self.slots else None
        if new_a is not prev_a and self._auto_fit:
            self._pending_fit = True
        self.update()

    def display_changed(self) -> None:
        self.update()

    def set_loading(self, loading: bool) -> None:
        if loading != self.loading:
            self.loading = loading
            if loading:
                self._spin_timer.start()
            else:
                self._spin_timer.stop()
            self.update()

    # ---------------------------------------------------------------- view

    @property
    def dpr(self) -> float:
        return self.devicePixelRatioF()

    def _fb_size(self) -> tuple[int, int]:
        d = self.dpr
        return max(1, int(round(self.width() * d))), max(1, int(round(self.height() * d)))

    def canvas_bounds(self) -> QRectF:
        lays = self._compute_layouts()
        if not lays:
            return QRectF()
        if self.compare_mode in ("horizontal", "vertical", "tile"):
            r = QRectF(lays[0].disp)
            for l in lays[1:]:
                r = r.united(l.disp)
            return r
        return QRectF(lays[0].disp)

    def fit(self) -> None:
        self._auto_fit = True
        self._pending_fit = False
        b = self.canvas_bounds()
        if b.isEmpty():
            return
        fw, fh = self._fb_size()
        bw, bh = (b.height(), b.width()) if self.rotation % 180 else (b.width(), b.height())
        self.zoom = max(1e-4, min(fw / bw, fh / bh))
        self.pan = b.center()
        self.zoomChanged.emit(self.zoom)
        self.update()

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = max(0.01, min(zoom, 256.0))
        fw, fh = self._fb_size()
        if anchor is None:
            anchor = QPointF(fw / 2, fh / 2)
        inv, _ok = self._canvas_to_device().inverted()
        before = inv.map(anchor)
        self.zoom = zoom
        inv2, _ok = self._canvas_to_device().inverted()
        after = inv2.map(anchor)
        self.pan += before - after
        self._auto_fit = False
        self.zoomChanged.emit(self.zoom)
        self.update()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        self.set_zoom(self.zoom * factor, anchor)

    def center_image(self) -> None:
        b = self.canvas_bounds()
        if not b.isEmpty():
            self.pan = b.center()
            self.update()

    def set_rotation(self, degrees: int) -> None:
        self.rotation = int(degrees) % 360
        if self._auto_fit:
            self.fit()
        self.update()

    def _canvas_to_device(self) -> QTransform:
        fw, fh = self._fb_size()
        t = QTransform()
        t.translate(fw / 2.0, fh / 2.0)
        t.rotate(self.rotation)
        t.scale(self.zoom, self.zoom)
        t.translate(-self.pan.x(), -self.pan.y())
        return t

    def canvas_to_widget(self) -> QTransform:
        d = self.dpr
        return self._canvas_to_device() * QTransform.fromScale(1.0 / d, 1.0 / d)

    def image_to_canvas(self, slot: int = 0) -> QTransform:
        lays = self._layouts or self._compute_layouts()
        if slot >= len(lays):
            return QTransform()
        l = lays[slot]
        t = QTransform()
        if self.mirror_x or self.mirror_y:
            # Mirror inside the display window.
            cx = l.disp.left() + l.disp.right()
            cy = l.disp.top() + l.disp.bottom()
            t = QTransform(-1 if self.mirror_x else 1, 0, 0, -1 if self.mirror_y else 1,
                           cx if self.mirror_x else 0, cy if self.mirror_y else 0)
        m = QTransform(l.sx, 0, 0, l.sy, l.disp.left() - l.ox * l.sx, l.disp.top() - l.oy * l.sy)
        return m * t

    def image_to_widget(self, slot: int = 0) -> QTransform:
        return self.image_to_canvas(slot) * self.canvas_to_widget()

    def widget_to_image(self, pos: QPointF, slot: int = 0) -> QPointF:
        inv, ok = self.image_to_widget(slot).inverted()
        return inv.map(QPointF(pos)) if ok else QPointF()

    def slot_at(self, pos: QPointF) -> int:
        """Which clip is under a widget position (for side by side and wipe)."""
        if not self.slots:
            return -1
        c, _ok = self.canvas_to_widget().inverted()
        p = c.map(QPointF(pos))
        lays = self._layouts or self._compute_layouts()
        mode = self.compare_mode
        if mode == "B":
            return 1 if len(self.slots) > 1 else 0
        if mode == "wipe" and len(lays) > 1:
            n, o = self._wipe_line()
            s = (p.x() - o.x()) * n[0] + (p.y() - o.y()) * n[1]
            return 0 if s < 0 else 1
        if mode in ("horizontal", "vertical", "tile"):
            for i, l in enumerate(lays):
                if l.disp.contains(p):
                    return i
            return -1
        return 0

    # ---------------------------------------------------------------- layout

    def _slot_windows(self, s: SlotInput):
        info = s.source.info
        f = s.frame
        if f is not None and not f.missing and f.pixels is not None:
            return f.display_window, f.data_window, f.par or 1.0
        disp = info.display_window if info.display_window[2] else (0, 0, info.width or 1920, info.height or 1080)
        data = info.data_window if info.data_window[2] else disp
        return disp, data, info.par or 1.0

    def _visible_slots(self) -> list[SlotInput]:
        if not self.slots:
            return []
        if self.compare_mode == "A" or len(self.slots) == 1:
            return self.slots[:1]
        if self.compare_mode == "B":
            return [self.slots[1]]
        if self.compare_mode in ("wipe", "overlay", "difference"):
            return self.slots[:2]
        if self.compare_mode in ("horizontal", "vertical"):
            return self.slots[:2]
        return self.slots[: self.MAX_SLOTS]

    def _compute_layouts(self) -> list[_SlotLayout]:
        vis = self._visible_slots()
        out: list[_SlotLayout] = []
        if not vis:
            self._layouts = out
            return out
        disp0, _data0, par0 = self._slot_windows(vis[0])
        W0 = max(1.0, disp0[2] * par0)
        H0 = max(1.0, disp0[3])
        base = QRectF(0, 0, W0, H0)
        mode = self.compare_mode if len(vis) > 1 else "A"
        for i, s in enumerate(vis):
            disp, data, par = self._slot_windows(s)
            w = max(1.0, disp[2] * par)
            h = max(1.0, float(disp[3]))
            if i == 0:
                rect = QRectF(base)
            elif mode in ("wipe", "overlay", "difference"):
                k = min(W0 / w, H0 / h)
                rect = QRectF(0, 0, w * k, h * k)
                rect.moveCenter(base.center())
            elif mode == "horizontal":
                k = H0 / h
                rect = QRectF(W0, 0, w * k, H0)
            elif mode == "vertical":
                k = W0 / w
                rect = QRectF(0, H0, W0, h * k)
            else:  # tile, two columns
                col, row = i % 2, i // 2
                cell = QRectF(col * W0, row * H0, W0, H0)
                k = min(W0 / w, H0 / h)
                rect = QRectF(0, 0, w * k, h * k)
                rect.moveCenter(cell.center())
            sx = rect.width() / max(1, disp[2])
            sy = rect.height() / max(1, disp[3])
            data_rect = QRectF(rect.left() + (data[0] - disp[0]) * sx, rect.top() + (data[1] - disp[1]) * sy,
                               data[2] * sx, data[3] * sy)
            out.append(_SlotLayout(rect, data_rect, sx, sy, float(disp[0]), float(disp[1])))
        self._layouts = out
        return out

    def _wipe_line(self):
        l = self._layouts[0] if self._layouts else None
        if l is None:
            return (1.0, 0.0), QPointF()
        o = QPointF(l.disp.left() + self.wipe_pos.x() * l.disp.width(),
                    l.disp.top() + self.wipe_pos.y() * l.disp.height())
        a = math.radians(self.wipe_angle)
        return (math.cos(a), math.sin(a)), o

    # ================================================================ GL lifecycle

    def initializeGL(self) -> None:
        self._programs.clear()
        self._glslots = []
        self._export_slot = None
        self._scratch_fbo = 0
        try:
            ver = GL.glGetString(GL.GL_VERSION)
            ren = GL.glGetString(GL.GL_RENDERER)
            info = f"{(ren or b'').decode(errors='replace')} / OpenGL {(ver or b'').decode(errors='replace')}"
            self._glsl = current_glsl_version()
            self._composite = self._make_program(COMPOSITE_FRAGMENT)
            quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)
            self._vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(self._vao)
            self._vbo = GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)
            GL.glBindVertexArray(0)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            self._gl_ok = True
            self._gl_error = ""
            log.info("OpenGL: %s", info)
            self.glReady.emit(info)
        except Exception as exc:
            self._gl_ok = False
            self._gl_error = str(exc)
            log.exception("OpenGL init failed")
            self.glReady.emit(f"OpenGL 초기화 실패: {exc}")
        ctx = self.context()
        if ctx is not None:
            ctx.aboutToBeDestroyed.connect(self._on_context_destroyed)

    def _on_context_destroyed(self) -> None:
        self._gl_ok = False
        self._programs.clear()
        self._glslots = []
        self._export_slot = None

    def _make_program(self, fragment: str) -> _Program:
        pid = _link(VERTEX, fragment, getattr(self, "_glsl", None))
        return _Program(pid)

    def _loc(self, prog: _Program, name: str) -> int:
        loc = prog.uniforms.get(name)
        if loc is None:
            loc = GL.glGetUniformLocation(prog.pid, name)
            prog.uniforms[name] = loc
        return loc

    def _delete_program(self, prog: _Program) -> None:
        try:
            GL.glDeleteProgram(prog.pid)
            for _unit, _target, tid, _s in prog.textures:
                GL.glDeleteTextures([tid])
        except Exception:
            pass

    # ---------------------------------------------------------------- color programs

    def _pipeline_for(self, source) -> ColorPipeline | None:
        if self.colors is None:
            return None
        d = self.display
        return self.colors.pipeline(source.colorspace, d.display, d.view, d.look, d.lut, d.lut_mode)

    def _color_program(self, pipe: ColorPipeline) -> _Program:
        prog = self._programs.get(pipe.key)
        if prog is not None:
            return prog
        src = color_program_source(pipe.to_lin.text, pipe.to_disp.text)
        try:
            prog = self._make_program(src)
        except RuntimeError as exc:
            log.error("color shader failed to compile, using fallback: %s", exc)
            fallback = self.colors._fallback(pipe.key, pipe.key[1], str(exc))
            prog = self._make_program(color_program_source(fallback.to_lin.text, fallback.to_disp.text))
            prog.error = str(exc)
            self._programs[pipe.key] = prog
            return prog
        GL.glUseProgram(prog.pid)
        unit = 1
        for fn in (pipe.to_lin, pipe.to_disp):
            for tex in fn.textures:
                tid = GL.glGenTextures(1)
                interp = GL.GL_LINEAR if tex.linear else GL.GL_NEAREST
                fmt = GL.GL_RED if tex.channels == 1 else GL.GL_RGB
                ifmt = GL.GL_R32F if tex.channels == 1 else GL.GL_RGB32F
                ptr = tex.values.ctypes.data_as(ctypes.c_void_p)
                GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
                if tex.kind == "3d":
                    target = GL.GL_TEXTURE_3D
                    GL.glBindTexture(target, tid)
                    GL.glTexImage3D(target, 0, GL.GL_RGB32F, tex.width, tex.width, tex.width, 0,
                                    GL.GL_RGB, GL.GL_FLOAT, ptr)
                    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_R, GL.GL_CLAMP_TO_EDGE)
                elif tex.kind == "1d":
                    target = GL.GL_TEXTURE_1D
                    GL.glBindTexture(target, tid)
                    GL.glTexImage1D(target, 0, ifmt, tex.width, 0, fmt, GL.GL_FLOAT, ptr)
                else:
                    target = GL.GL_TEXTURE_2D
                    GL.glBindTexture(target, tid)
                    GL.glTexImage2D(target, 0, ifmt, tex.width, tex.height, 0, fmt, GL.GL_FLOAT, ptr)
                    GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
                GL.glTexParameteri(target, GL.GL_TEXTURE_MIN_FILTER, interp)
                GL.glTexParameteri(target, GL.GL_TEXTURE_MAG_FILTER, interp)
                GL.glTexParameteri(target, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
                GL.glBindTexture(target, 0)
                loc = self._loc(prog, tex.sampler)
                if loc >= 0:
                    GL.glUniform1i(loc, unit)
                prog.textures.append((unit, target, tid, tex.sampler))
                unit += 1
            for name, typ, val in fn.uniforms:
                loc = self._loc(prog, name)
                if loc < 0:
                    continue
                if typ == "UNIFORM_DOUBLE":
                    GL.glUniform1f(loc, float(val))
                elif typ == "UNIFORM_BOOL":
                    GL.glUniform1i(loc, int(bool(val)))
                elif typ == "UNIFORM_FLOAT3":
                    GL.glUniform3f(loc, *[float(v) for v in val])
                elif typ == "UNIFORM_VECTOR_FLOAT":
                    GL.glUniform1fv(loc, len(val), np.array(val, np.float32))
                elif typ == "UNIFORM_VECTOR_INT":
                    GL.glUniform1iv(loc, len(val), np.array(val, np.int32))
        GL.glUniform1i(self._loc(prog, "u_src"), 0)
        GL.glUseProgram(0)
        self._programs[pipe.key] = prog
        if pipe.error and pipe.error not in self._pipe_errors:
            self._pipe_errors.add(pipe.error)
            log.warning("color pipeline fallback: %s", pipe.error)
        return prog

    # ---------------------------------------------------------------- textures

    def _upload(self, gs: _GLSlot, frame: Frame) -> None:
        px = frame.pixels
        if px.dtype not in _GL_INTERNAL:
            px = px.astype(np.float32)
        if not px.flags["C_CONTIGUOUS"]:
            px = np.ascontiguousarray(px)
        h, w, c = px.shape
        internal_map, gltype = _GL_INTERNAL[px.dtype]
        shape = (w, h, c, px.dtype.str)
        if not gs.tex:
            gs.tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, gs.tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        ptr = px.ctypes.data_as(ctypes.c_void_p)
        if gs.tex_shape != shape:
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, internal_map[c], w, h, 0, _GL_FORMATS[c], gltype, ptr)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            gs.tex_shape = shape
        else:
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, _GL_FORMATS[c], gltype, ptr)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def _ensure_fbo(self, gs: _GLSlot, w: int, h: int) -> None:
        if gs.fbo and gs.fbo_size == (w, h):
            return
        if not gs.fbo:
            gs.fbo = GL.glGenFramebuffers(1)
            gs.fbo_tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, gs.fbo_tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA16F, w, h, 0, GL.GL_RGBA, GL.GL_HALF_FLOAT, None)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, gs.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, gs.fbo_tex, 0)
        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:
            log.error("framebuffer incomplete: %s", status)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        gs.fbo_size = (w, h)

    def _set_color_uniforms(self, prog: _Program, nch: int) -> None:
        d = self.display
        u = lambda n: self._loc(prog, n)  # noqa: E731
        GL.glUniform1i(u("u_nch"), nch)
        GL.glUniform1i(u("u_channel"), _CHANNEL_INDEX.get(d.channel, 0))
        GL.glUniform1i(u("u_video_levels"), 1 if d.video_levels == "legal" else 0)
        GL.glUniform1i(u("u_unpremult"), 1 if d.unpremult else 0)
        GL.glUniform1f(u("u_gain"), 2.0 ** d.exposure)
        GL.glUniform1f(u("u_offset"), d.offset)
        GL.glUniform1f(u("u_contrast"), d.contrast)
        GL.glUniform1f(u("u_saturation"), d.saturation)
        GL.glUniformMatrix3fv(u("u_hue"), 1, GL.GL_TRUE, _hue_matrix(d.hue))
        GL.glUniform1f(u("u_softclip"), max(0.0, min(0.99, d.softclip)))
        GL.glUniform1f(u("u_gamma"), max(0.01, d.gamma))
        GL.glUniform1i(u("u_levels"), 1 if d.levels else 0)
        GL.glUniform1f(u("u_in_lo"), d.in_lo)
        GL.glUniform1f(u("u_in_hi"), d.in_hi)
        GL.glUniform1f(u("u_lv_gamma"), d.lv_gamma)
        GL.glUniform1f(u("u_out_lo"), d.out_lo)
        GL.glUniform1f(u("u_out_hi"), d.out_hi)
        GL.glUniform1i(u("u_invert"), 1 if d.invert else 0)

    def _render_color(self, gs: _GLSlot, source, frame: Frame, force: bool = False) -> bool:
        """Pass 1 for one clip. Returns True when the slot texture holds a valid image."""
        if frame is None or frame.missing or frame.pixels is None:
            gs.sig = ()
            gs.frame_ref = None
            return False
        pipe = self._pipeline_for(source)
        key = pipe.key if pipe else None
        sig = (id(frame.pixels), frame.frame_no, key, self.display.signature())
        if not force and gs.sig == sig and gs.fbo:
            return True
        if gs.frame_ref is not frame.pixels or gs.tex_shape == ():
            self._upload(gs, frame)
            gs.frame_ref = frame.pixels
        h, w = frame.pixels.shape[:2]
        self._ensure_fbo(gs, w, h)
        if pipe is None:
            from cocseq.color.ocio_mgr import ColorManager as _CM

            pipe = _CM()._fallback(("none",), source.colorspace or "srgb", "no color manager")
        prog = self._color_program(pipe)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, gs.fbo)
        GL.glViewport(0, 0, w, h)
        GL.glDisable(GL.GL_BLEND)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glUseProgram(prog.pid)
        self._set_color_uniforms(prog, frame.pixels.shape[2])
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, gs.tex)
        for unit, target, tid, _s in prog.textures:
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(target, tid)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        for unit, target, _tid, _s in prog.textures:
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(target, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, gs.fbo_tex)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glUseProgram(0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        gs.sig = sig
        return True

    # ---------------------------------------------------------------- paint

    def paintGL(self) -> None:
        if self._pending_fit:
            self._pending_fit = False
            self.fit()
        fw, fh = self._fb_size()
        if not self._gl_ok:
            GL.glClearColor(0.05, 0.05, 0.06, 1)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            self._paint_overlays()
            return
        vis = self._visible_slots()
        lays = self._compute_layouts()
        while len(self._glslots) < self.MAX_SLOTS:
            self._glslots.append(_GLSlot())
        valid = []
        a_changed = False
        for i, s in enumerate(vis):
            gs = self._glslots[i]
            old = gs.sig
            try:
                ok = self._render_color(gs, s.source, s.frame)
            except Exception:
                log.exception("color pass failed")
                ok = False
            valid.append(1 if ok else 0)
            if i == 0 and gs.sig != old:
                a_changed = True
        if a_changed and self.scopes_enabled:
            self._sample_dirty = True
            if not self._sample_timer.isActive():
                self._sample_timer.start()

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        GL.glViewport(0, 0, fw, fh)
        surround = PAL.qcolor("bg0")
        GL.glClearColor(surround.redF(), surround.greenF(), surround.blueF(), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if vis:
            self._composite_pass(vis, lays, valid, fw, fh)
        self._paint_overlays()

    def _bg_colors(self):
        if self.background == "checker":
            return (0.24, 0.24, 0.24), (0.16, 0.16, 0.16), 1
        if self.background == "gray":
            return (0.18, 0.18, 0.18), (0, 0, 0), 0
        if self.background == "custom":
            c = self.background_color
            return (c.redF(), c.greenF(), c.blueF()), (0, 0, 0), 0
        if self.background == "black":
            return (0.0, 0.0, 0.0), (0, 0, 0), 0
        return (0.075, 0.078, 0.09), (0, 0, 0), 0

    def _composite_pass(self, vis, lays, valid, fw, fh) -> None:
        prog = self._composite
        GL.glUseProgram(prog.pid)
        u = lambda n: self._loc(prog, n)  # noqa: E731
        n = len(vis)
        rects = np.zeros((4, 4), np.float32)
        disps = np.zeros((4, 4), np.float32)
        valids = np.zeros(4, np.int32)
        for i, l in enumerate(lays[:4]):
            rects[i] = (l.data.left(), l.data.top(), l.data.right(), l.data.bottom())
            disps[i] = (l.disp.left(), l.disp.top(), l.disp.right(), l.disp.bottom())
            valids[i] = valid[i] if i < len(valid) else 0
        inv, _ok = self._canvas_to_device().inverted()
        m = np.array([inv.m11(), inv.m12(), inv.m13(), inv.m21(), inv.m22(), inv.m23(),
                      inv.m31(), inv.m32(), inv.m33()], np.float32)
        GL.glUniformMatrix3fv(u("u_inv"), 1, GL.GL_FALSE, m)
        GL.glUniform4fv(u("u_rect"), 4, rects)
        GL.glUniform4fv(u("u_disp"), 4, disps)
        GL.glUniform1iv(u("u_valid"), 4, valids)
        GL.glUniform1i(u("u_count"), n)
        GL.glUniform1f(u("u_fbh"), float(fh))
        GL.glUniform1f(u("u_dpr"), float(self.dpr))
        mode = _MODE_INDEX.get(self.compare_mode, 0) if n > 1 else 0
        GL.glUniform1i(u("u_mode"), mode)
        nvec, o = self._wipe_line()
        GL.glUniform2f(u("u_wipe_p"), o.x(), o.y())
        GL.glUniform2f(u("u_wipe_n"), nvec[0], nvec[1])
        GL.glUniform1f(u("u_overlay"), self.overlay_opacity)
        GL.glUniform1f(u("u_diff_gain"), self.diff_gain)
        GL.glUniform1i(u("u_alpha_mode"), {"none": 0, "straight": 1, "premult": 2}.get(self.display.alpha_mode, 0))
        a, b, checker = self._bg_colors()
        GL.glUniform1i(u("u_bg"), checker)
        GL.glUniform3f(u("u_bg_a"), *a)
        GL.glUniform3f(u("u_bg_b"), *b)
        GL.glUniform1f(u("u_checker"), float(self.checker_size))
        sur = PAL.qcolor("bg0")
        GL.glUniform3f(u("u_surround"), sur.redF(), sur.greenF(), sur.blueF())
        GL.glUniform1i(u("u_mirror_x"), 1 if self.mirror_x else 0)
        GL.glUniform1i(u("u_mirror_y"), 1 if self.mirror_y else 0)
        GL.glUniform1i(u("u_env"), 1 if self.env_mode else 0)
        GL.glUniformMatrix3fv(u("u_env_rot"), 1, GL.GL_TRUE, self._env_matrix())
        GL.glUniform1f(u("u_env_tan"), math.tan(math.radians(max(5.0, min(170.0, self.env_fov))) / 2))
        GL.glUniform2f(u("u_view"), float(fw), float(fh))
        GL.glUniform1i(u("u_nearest"), 0 if self.filter_linear else 1)
        for i in range(4):
            GL.glUniform1i(u(f"u_img{i}"), i)
            GL.glActiveTexture(GL.GL_TEXTURE0 + i)
            gs = self._glslots[i] if i < len(self._glslots) else None
            tid = gs.fbo_tex if (gs is not None and i < n and valids[i]) else 0
            GL.glBindTexture(GL.GL_TEXTURE_2D, tid)
            if tid:
                if self.filter_linear:
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                else:
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_NEAREST_MIPMAP_NEAREST)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_NEAREST)
                wrap = GL.GL_REPEAT if self.env_mode and i == 0 else GL.GL_CLAMP_TO_EDGE
                GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, wrap)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        for i in range(4):
            GL.glActiveTexture(GL.GL_TEXTURE0 + i)
            GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glUseProgram(0)

    def _env_matrix(self) -> np.ndarray:
        y = math.radians(self.env_yaw)
        p = math.radians(self.env_pitch)
        ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]], np.float32)
        rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]], np.float32)
        return (ry @ rx).astype(np.float32)

    # ---------------------------------------------------------------- read back

    def _read_fbo(self, gs: _GLSlot, x: int, y: int, w: int, h: int) -> np.ndarray:
        buf = np.empty((h, w, 4), np.float32)
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, gs.fbo)
        GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
        GL.glReadPixels(x, y, w, h, GL.GL_RGBA, GL.GL_FLOAT, buf)
        GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self.defaultFramebufferObject())
        return buf

    def display_value(self, slot: int, x: int, y: int) -> list[float] | None:
        """Displayed (after color pipeline) RGBA at an image pixel of a clip."""
        if not self._gl_ok or slot >= len(self._glslots) or slot >= len(self.slots):
            return None
        gs = self._glslots[slot]
        f = self._visible_slots()[slot].frame if slot < len(self._visible_slots()) else None
        if not gs.fbo or not gs.sig or f is None or f.pixels is None:
            return None
        dx, dy, w, h = f.data_window
        ix, iy = x - dx, y - dy
        if not (0 <= ix < w and 0 <= iy < h) or (w, h) != gs.fbo_size:
            return None
        self.makeCurrent()
        try:
            v = self._read_fbo(gs, ix, iy, 1, 1)[0, 0]
        finally:
            self.doneCurrent()
        return [float(c) for c in v]

    def display_region(self, slot: int, x0: int, y0: int, x1: int, y1: int) -> np.ndarray | None:
        if not self._gl_ok or slot >= len(self._glslots):
            return None
        vis = self._visible_slots()
        if slot >= len(vis):
            return None
        gs = self._glslots[slot]
        f = vis[slot].frame
        if not gs.fbo or not gs.sig or f is None or f.pixels is None:
            return None
        dx, dy, w, h = f.data_window
        ax0, ay0 = max(0, x0 - dx), max(0, y0 - dy)
        ax1, ay1 = min(w, x1 - dx), min(h, y1 - dy)
        if ax1 <= ax0 or ay1 <= ay0:
            return None
        self.makeCurrent()
        try:
            return self._read_fbo(gs, ax0, ay0, ax1 - ax0, ay1 - ay0)
        finally:
            self.doneCurrent()

    def _emit_sample(self) -> None:
        if not self.scopes_enabled or not self._sample_dirty:
            return
        self._sample_dirty = False
        img = self.grab_sample(420)
        if img is not None:
            self.displaySample.emit(img)

    def request_sample(self) -> None:
        self._sample_dirty = True
        self._sample_timer.start()

    def grab_sample(self, max_w: int = 420) -> np.ndarray | None:
        """Downscaled display-referred copy of clip A for the scopes."""
        if not self._gl_ok or not self._glslots or not self._glslots[0].sig:
            return None
        gs = self._glslots[0]
        w, h = gs.fbo_size
        if w <= 0 or h <= 0:
            return None
        sw = min(max_w, w)
        sh = max(1, int(round(h * sw / w)))
        self.makeCurrent()
        try:
            if not self._scratch_fbo:
                self._scratch_fbo = GL.glGenFramebuffers(1)
                self._scratch_tex = GL.glGenTextures(1)
            if self._scratch_size != (sw, sh):
                GL.glBindTexture(GL.GL_TEXTURE_2D, self._scratch_tex)
                GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA32F, sw, sh, 0, GL.GL_RGBA, GL.GL_FLOAT, None)
                GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self._scratch_fbo)
                GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D,
                                          self._scratch_tex, 0)
                self._scratch_size = (sw, sh)
            GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, gs.fbo)
            GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, self._scratch_fbo)
            GL.glBlitFramebuffer(0, 0, w, h, 0, 0, sw, sh, GL.GL_COLOR_BUFFER_BIT, GL.GL_LINEAR)
            buf = np.empty((sh, sw, 4), np.float32)
            GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self._scratch_fbo)
            GL.glPixelStorei(GL.GL_PACK_ALIGNMENT, 1)
            GL.glReadPixels(0, 0, sw, sh, GL.GL_RGBA, GL.GL_FLOAT, buf)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            return buf
        except Exception:
            log.debug("scope sample failed", exc_info=True)
            return None
        finally:
            self.doneCurrent()

    def render_to_array(self, source, frame: Frame) -> np.ndarray | None:
        """Full resolution display-referred RGBA float32 of one frame (top row first)."""
        if not self._gl_ok or frame is None or frame.pixels is None:
            return None
        self.makeCurrent()
        try:
            if self._export_slot is None:
                self._export_slot = _GLSlot()
            gs = self._export_slot
            gs.frame_ref = None
            self._render_color(gs, source, frame, force=True)
            w, h = gs.fbo_size
            return self._read_fbo(gs, 0, 0, w, h)
        finally:
            self.doneCurrent()

    def release_export(self) -> None:
        if self._export_slot is None or not self._gl_ok:
            return
        self.makeCurrent()
        try:
            gs = self._export_slot
            if gs.tex:
                GL.glDeleteTextures([gs.tex])
            if gs.fbo_tex:
                GL.glDeleteTextures([gs.fbo_tex])
            if gs.fbo:
                GL.glDeleteFramebuffers(1, [gs.fbo])
        finally:
            self._export_slot = None
            self.doneCurrent()

    # ================================================================ overlays

    def _paint_overlays(self) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        try:
            if not self.slots:
                self._paint_empty(p)
            else:
                if not self.env_mode:
                    self._paint_missing(p)
                    self._paint_guides(p)
                    if self.show_annotations:
                        self._paint_annotations(p)
                    self._paint_compare_marks(p)
                    self._paint_area(p)
                self._paint_hud(p)
                if self.loading:
                    self._paint_spinner(p)
            if not self._gl_ok and self._gl_error:
                p.setPen(PAL.qcolor("err"))
                p.setFont(ui_font(10))
                p.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignBottom | Qt.AlignLeft | Qt.TextWordWrap,
                           f"OpenGL 3.3을 사용할 수 없습니다: {self._gl_error}")
        finally:
            p.end()

    def _paint_empty(self, p: QPainter) -> None:
        r = QRectF(self.rect())
        c = r.center()
        try:
            from cocseq.icons import logo_pixmap

            pm = logo_pixmap(72)
            p.setOpacity(0.95)
            p.drawPixmap(QPointF(c.x() - 36, c.y() - 110), pm)
            p.setOpacity(1.0)
        except Exception:
            pass
        p.setPen(PAL.qcolor("text"))
        f = ui_font(15, QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(r.left(), c.y() - 24, r.width(), 30), Qt.AlignCenter, "시퀀스나 동영상을 끌어다 놓으세요")
        p.setPen(PAL.qcolor("text3"))
        p.setFont(ui_font(10))
        p.drawText(QRectF(r.left(), c.y() + 10, r.width(), 22), Qt.AlignCenter,
                   "EXR · DPX · TIFF · PNG · JPG · MOV · MP4 · 폴더째로도 열 수 있습니다")
        # Dashed drop zone
        zone = QRectF(0, 0, min(520, r.width() - 60), 250)
        zone.moveCenter(QPointF(c.x(), c.y() - 30))
        pen = QPen(PAL.qcolor("line2"), 1.4, Qt.DashLine)
        pen.setDashPattern([5, 5])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(zone, 18, 18)
        keys = [("Ctrl+O", "파일 열기"), ("Ctrl+Shift+O", "폴더 열기"), ("Space", "재생")]
        p.setFont(ui_font(9))
        total = sum(QFontMetricsF(p.font()).horizontalAdvance(k + d) + 58 for k, d in keys)
        x = c.x() - total / 2
        y = zone.bottom() + 26
        for k, d in keys:
            fm = QFontMetricsF(mono_font(8.5))
            kw = fm.horizontalAdvance(k) + 14
            box = QRectF(x, y, kw, 20)
            p.setPen(QPen(PAL.qcolor("line2"), 1))
            p.setBrush(PAL.qcolor("bg3"))
            p.drawRoundedRect(box, 5, 5)
            p.setFont(mono_font(8.5))
            p.setPen(PAL.qcolor("text2"))
            p.drawText(box, Qt.AlignCenter, k)
            p.setFont(ui_font(9))
            p.setPen(PAL.qcolor("text3"))
            dw = QFontMetricsF(p.font()).horizontalAdvance(d)
            p.drawText(QRectF(box.right() + 6, y, dw + 4, 20), Qt.AlignVCenter | Qt.AlignLeft, d)
            x = box.right() + dw + 30

    def _paint_missing(self, p: QPainter) -> None:
        lays = self._layouts
        vis = self._visible_slots()
        for i, s in enumerate(vis):
            if i >= len(lays):
                break
            f = s.frame
            if f is not None and not f.missing:
                continue
            rect = self.canvas_to_widget().mapRect(lays[i].disp)
            p.save()
            p.setClipRect(rect)
            p.fillRect(rect, QColor(18, 12, 14))
            pen = QPen(QColor(PAL.err), 1.5)
            p.setPen(pen)
            p.drawLine(rect.topLeft(), rect.bottomRight())
            p.drawLine(rect.topRight(), rect.bottomLeft())
            label = "프레임을 불러오는 중…" if f is None else (
                f"누락된 프레임 {f.frame_no}" + (f"\n{f.error}" if f.error else ""))
            p.setFont(ui_font(12, QFont.DemiBold))
            box = QRectF(0, 0, min(rect.width() - 20, 360), 64)
            box.moveCenter(rect.center())
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(PAL.qcolor("err") if f is not None else PAL.qcolor("text2"))
            p.drawText(box, Qt.AlignCenter | Qt.TextWordWrap, label)
            p.restore()

    def _paint_guides(self, p: QPainter) -> None:
        if not self._layouts:
            return
        l0 = self._layouts[0]
        t = self.canvas_to_widget()
        if self.show_display_window:
            pen = QPen(PAL.qcolor("text2", 0.9), 1, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(t.map(QPolygonF(l0.disp)))
        if self.show_data_window:
            pen = QPen(PAL.qcolor("warn", 0.95), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawPolygon(t.map(QPolygonF(l0.data)))
            f = self._visible_slots()[0].frame
            if f is not None and f.pixels is not None:
                dw = f.data_window
                p.setFont(mono_font(8))
                pt = t.map(l0.data.topLeft())
                p.drawText(pt + QPointF(4, -4), f"data {dw[0]},{dw[1]} {dw[2]}x{dw[3]}")
        disp = l0.disp
        if self.aspect_guide:
            try:
                if ":" in self.aspect_guide:
                    a, b = self.aspect_guide.split(":")
                    ratio = float(a) / float(b)
                else:
                    ratio = float(self.aspect_guide)
            except ValueError:
                ratio = 0
            if ratio > 0:
                w, h = disp.width(), disp.height()
                if w / h > ratio:
                    gw, gh = h * ratio, h
                else:
                    gw, gh = w, w / ratio
                g = QRectF(0, 0, gw, gh)
                g.moveCenter(disp.center())
                poly = t.map(QPolygonF(g))
                outer = QPainterPath()
                outer.addPolygon(t.map(QPolygonF(disp)))
                inner = QPainterPath()
                inner.addPolygon(poly)
                p.fillPath(outer.subtracted(inner), QColor(0, 0, 0, 150))
                p.setPen(QPen(PAL.qcolor("accent", 0.9), 1))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(poly)
                p.setFont(mono_font(8))
                p.drawText(poly.boundingRect().topLeft() + QPointF(5, 13), self.aspect_guide)
        if self.show_safe_areas:
            for pct, name in ((0.93, "action 93%"), (0.90, "title 90%")):
                g = QRectF(0, 0, disp.width() * pct, disp.height() * pct)
                g.moveCenter(disp.center())
                pen = QPen(QColor(255, 255, 255, 110), 1, Qt.DashLine if pct < 0.92 else Qt.SolidLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                poly = t.map(QPolygonF(g))
                p.drawPolygon(poly)
                p.setFont(mono_font(7.5))
                p.setPen(QColor(255, 255, 255, 130))
                br = poly.boundingRect()
                p.drawText(QPointF(br.left() + 4, br.bottom() - 4), name)
            # Center cross
            c = t.map(disp.center())
            p.setPen(QPen(QColor(255, 255, 255, 110), 1))
            p.drawLine(c + QPointF(-8, 0), c + QPointF(8, 0))
            p.drawLine(c + QPointF(0, -8), c + QPointF(0, 8))

    def _paint_annotations(self, p: QPainter) -> None:
        store = self.annotation_store
        shapes = store.visible(self.annotation_frame, self.ghost_frames) if store is not None else []
        if not shapes and self._drawing is None:
            return
        d = self.dpr
        fw, fh = self._fb_size()
        t = self.image_to_canvas(0) * self._canvas_to_device()
        layer = render_layer((fw, fh), shapes, t, self._drawing)
        layer.setDevicePixelRatio(d)
        p.drawImage(QPointF(0, 0), layer)

    def _paint_compare_marks(self, p: QPainter) -> None:
        vis = self._visible_slots()
        if len(vis) < 2 or self.compare_mode in ("A", "B"):
            return
        t = self.canvas_to_widget()
        lays = self._layouts
        if self.compare_mode == "wipe":
            nvec, o = self._wipe_line()
            d = QPointF(-nvec[1], nvec[0])
            big = 1e5
            a = t.map(o - d * big)
            b = t.map(o + d * big)
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            p.drawLine(a, b)
            c = t.map(o)
            p.setBrush(PAL.qcolor("accent"))
            p.setPen(QPen(QColor("white"), 2))
            p.drawEllipse(c, 7, 7)
            n_scr = t.map(o + QPointF(*nvec) * 10) - c
            ln = math.hypot(n_scr.x(), n_scr.y()) or 1
            n_scr /= ln
            self._chip(p, c - n_scr * 34 + QPointF(-10, -10), "A", PAL.accent)
            self._chip(p, c + n_scr * 34 + QPointF(-10, -10), "B", PAL.b)
            return
        labels = "ABCD"
        colors = [PAL.accent, PAL.b, "#B38CFF", "#3DD68C"]
        for i, l in enumerate(lays[: len(vis)]):
            r = t.mapRect(l.disp)
            if self.compare_mode in ("horizontal", "vertical", "tile"):
                self._chip(p, r.topLeft() + QPointF(10, 10), labels[i], colors[i])
                name = vis[i].source.name
                p.setFont(ui_font(9, QFont.DemiBold))
                p.setPen(QColor(255, 255, 255, 220))
                p.drawText(r.topLeft() + QPointF(38, 25), name)
            elif i == 1:
                self._chip(p, r.topRight() + QPointF(-30, 10), "B", colors[1])
            else:
                self._chip(p, r.topLeft() + QPointF(10, 10), "A", colors[0])

    def _chip(self, p: QPainter, pos: QPointF, text: str, color: str) -> None:
        r = QRectF(pos.x(), pos.y(), 20, 20)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("white"))
        p.setFont(ui_font(9, QFont.Bold))
        p.drawText(r, Qt.AlignCenter, text)

    def _paint_area(self, p: QPainter) -> None:
        if not self.area:
            return
        x0, y0, x1, y1 = self.area
        t = self.image_to_widget(0)
        poly = t.map(QPolygonF(QRectF(QPointF(x0, y0), QPointF(x1, y1))))
        pen = QPen(PAL.qcolor("accent"), 1.4, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(PAL.qcolor("accent", 0.08))
        p.drawPolygon(poly)
        p.setFont(mono_font(8))
        br = poly.boundingRect()
        label = f"{abs(x1 - x0)}×{abs(y1 - y0)}"
        p.setPen(PAL.qcolor("accent"))
        p.drawText(QPointF(br.left(), br.top() - 5), label)

    def _paint_hud(self, p: QPainter) -> None:
        if not self.hud_enabled or not self.hud:
            return
        m = 12
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        f = mono_font(8.5)
        p.setFont(f)
        fm = QFontMetricsF(f)
        lh = fm.height() + 2
        for corner, lines in self.hud.items():
            if not lines:
                continue
            for i, text in enumerate(lines):
                w = fm.horizontalAdvance(text)
                if corner in ("tl", "bl"):
                    x = r.left()
                else:
                    x = r.right() - w
                if corner in ("tl", "tr"):
                    y = r.top() + fm.ascent() + i * lh
                else:
                    y = r.bottom() - (len(lines) - 1 - i) * lh - fm.descent()
                p.setPen(QColor(0, 0, 0, 160))
                p.drawText(QPointF(x + 1, y + 1), text)
                p.setPen(QColor(236, 238, 242, 225) if i else QColor(255, 255, 255, 240))
                p.drawText(QPointF(x, y), text)

    def _paint_spinner(self, p: QPainter) -> None:
        c = QPointF(self.width() - 24, 24 + (18 if self.hud.get("tr") else 0))
        t = time.monotonic() * 360 % 360
        pen = QPen(PAL.qcolor("accent"), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(c.x() - 8, c.y() - 8, 16, 16), int(-t * 16), 270 * 16)

    # ================================================================ interaction

    def _dev(self, pos: QPointF) -> QPointF:
        return QPointF(pos.x() * self.dpr, pos.y() * self.dpr)

    def _probe(self, pos: QPointF) -> None:
        if not self.slots:
            return
        slot = max(0, self.slot_at(pos))
        vis = self._visible_slots()
        if slot >= len(vis):
            return
        pt = self.widget_to_image(pos, slot)
        x, y = int(math.floor(pt.x())), int(math.floor(pt.y()))
        f = vis[slot].frame
        raw = f.value_at(x, y) if f is not None else None
        info = {"slot": slot, "x": x, "y": y, "raw": raw,
                "names": list(f.channel_names) if f is not None else [],
                "display": self.display_value(slot, x, y) if raw is not None else None,
                "source": vis[slot].source}
        self.pixelProbed.emit(info)

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        self._drag_start = pos
        self._drag_pan = QPointF(self.pan)
        self.setFocus()
        btn = ev.button()
        mods = ev.modifiers()
        if btn == Qt.RightButton:
            self._drag_mode = "right"
            return
        if btn == Qt.MiddleButton or (btn == Qt.LeftButton and (self._space_down or mods & Qt.AltModifier)):
            self._drag_mode = "pan"
            self.setCursor(Qt.ClosedHandCursor)
            return
        if btn != Qt.LeftButton:
            return
        if self.env_mode:
            self._drag_mode = "env"
            self._drag_value = (self.env_yaw, self.env_pitch)
            return
        if mods & Qt.ControlModifier:
            self._drag_mode = "scrub"
            self._drag_value = 0
            return
        if self.tool in ("pen", "eraser", "line", "arrow", "rect", "ellipse") and self.slots:
            ip = self.widget_to_image(pos, 0)
            self._drawing = Shape(self.tool, [(ip.x(), ip.y())], self.pen_color, self.pen_size / self._image_scale(),
                                  1.0, "", self.pen_fill, self.pen_hold)
            if self.tool in ("line", "arrow", "rect", "ellipse"):
                self._drawing.points.append((ip.x(), ip.y()))
            self._drag_mode = "draw"
            self.update()
            return
        if self.tool == "text" and self.slots:
            self._start_text(pos)
            return
        if self.tool == "area" and self.slots:
            ip = self.widget_to_image(pos, 0)
            self._drag_mode = "area"
            self._drag_value = (int(ip.x()), int(ip.y()))
            self.area = None
            return
        if self.compare_mode == "wipe" and len(self.slots) > 1:
            self._drag_mode = "wipe_rotate" if mods & Qt.ShiftModifier else "wipe"
            self._move_wipe(pos, rotate=bool(mods & Qt.ShiftModifier))
            return
        self._drag_mode = "pan"
        self.setCursor(Qt.ClosedHandCursor)

    def _image_scale(self) -> float:
        """Widget pixels per image pixel for clip A (keeps brush size constant on screen)."""
        t = self.image_to_widget(0)
        return max(1e-6, math.hypot(t.m11(), t.m12()))

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        self._last_mouse = pos
        mode = self._drag_mode
        if mode == "pan":
            d = self._dev(pos) - self._dev(self._drag_start)
            inv = QTransform().rotate(-self.rotation)
            dc = inv.map(QPointF(d.x() / self.zoom, d.y() / self.zoom))
            self.pan = self._drag_pan - dc
            self._auto_fit = False
            self.update()
        elif mode == "env":
            d = pos - self._drag_start
            k = self.env_fov / max(1, self.height())
            y0, p0 = self._drag_value
            self.env_yaw = y0 - d.x() * k
            self.env_pitch = max(-89.0, min(89.0, p0 + d.y() * k))
            self.envChanged.emit()
            self.update()
        elif mode == "scrub":
            step = int((pos.x() - self._drag_start.x()) / 8)
            if step != self._drag_value:
                self.scrubRequested.emit(step - self._drag_value)
                self._drag_value = step
        elif mode == "draw" and self._drawing is not None:
            ip = self.widget_to_image(pos, 0)
            if self._drawing.kind in ("pen", "eraser"):
                last = self._drawing.points[-1]
                if math.hypot(ip.x() - last[0], ip.y() - last[1]) * self._image_scale() >= 1.5:
                    self._drawing.points.append((ip.x(), ip.y()))
            else:
                a = self._drawing.points[0]
                b = (ip.x(), ip.y())
                if ev.modifiers() & Qt.ShiftModifier:
                    b = self._constrain(a, b, self._drawing.kind)
                self._drawing.points[-1] = b
            self.update()
        elif mode == "area":
            ip = self.widget_to_image(pos, 0)
            x0, y0 = self._drag_value
            x1, y1 = int(math.ceil(ip.x())), int(math.ceil(ip.y()))
            self.area = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            self.update()
        elif mode in ("wipe", "wipe_rotate"):
            self._move_wipe(pos, rotate=mode == "wipe_rotate")
        self._probe(pos)
        if not mode:
            self._update_cursor()

    @staticmethod
    def _constrain(a, b, kind):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if kind in ("rect", "ellipse"):
            s = max(abs(dx), abs(dy))
            return (a[0] + math.copysign(s, dx or 1), a[1] + math.copysign(s, dy or 1))
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        ln = math.hypot(dx, dy)
        return (a[0] + ln * math.cos(ang), a[1] + ln * math.sin(ang))

    def _move_wipe(self, pos: QPointF, rotate: bool) -> None:
        if not self._layouts:
            return
        inv, _ok = self.canvas_to_widget().inverted()
        c = inv.map(QPointF(pos))
        l0 = self._layouts[0].disp
        if rotate:
            _n, o = self._wipe_line()
            self.wipe_angle = math.degrees(math.atan2(c.y() - o.y(), c.x() - o.x()))
        else:
            self.wipe_pos = QPointF((c.x() - l0.left()) / max(1e-6, l0.width()),
                                    (c.y() - l0.top()) / max(1e-6, l0.height()))
        self.wipeChanged.emit()
        self.update()

    def mouseReleaseEvent(self, ev) -> None:
        mode = self._drag_mode
        self._drag_mode = ""
        if mode == "right":
            if (ev.position() - self._drag_start).manhattanLength() < 5:
                self.contextMenuRequested.emit(ev.globalPosition().toPoint())
        elif mode == "draw" and self._drawing is not None:
            shape = self._drawing
            self._drawing = None
            if len(shape.points) >= 1:
                self.shapeFinished.emit(shape)
            self.update()
        elif mode == "area":
            self.areaSelected.emit(self.area)
        self._update_cursor()

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and not self.tool and not self.env_mode:
            self.fit()

    def wheelEvent(self, ev) -> None:
        delta = ev.angleDelta().y() or ev.pixelDelta().y()
        if not delta:
            return
        if self.env_mode:
            self.env_fov = max(10.0, min(160.0, self.env_fov * (0.9 if delta > 0 else 1.1)))
            self.envChanged.emit()
            self.update()
            return
        factor = 1.0015 ** delta
        self.zoom_by(factor, self._dev(ev.position()))

    def leaveEvent(self, ev) -> None:
        self.pixelProbed.emit({})
        super().leaveEvent(ev)

    def keyPressEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space_down = True
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev: QKeyEvent) -> None:
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space_down = False
        super().keyReleaseEvent(ev)

    def _update_cursor(self) -> None:
        if self.tool in ("pen", "line", "arrow", "rect", "ellipse", "area"):
            self.setCursor(Qt.CrossCursor)
        elif self.tool == "eraser":
            self.setCursor(Qt.PointingHandCursor)
        elif self.tool == "text":
            self.setCursor(Qt.IBeamCursor)
        elif self.compare_mode == "wipe" and len(self.slots) > 1:
            self.setCursor(Qt.SplitHCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def set_tool(self, tool: str) -> None:
        self.tool = tool or ""
        self._commit_text()
        self._update_cursor()

    # ---------------------------------------------------------------- text tool

    def _start_text(self, pos: QPointF) -> None:
        self._commit_text()
        ip = self.widget_to_image(pos, 0)
        self._text_anchor = (ip.x(), ip.y())
        edit = QLineEdit(self)
        edit.setPlaceholderText("텍스트 입력 후 Enter")
        edit.setStyleSheet(
            f"QLineEdit {{ background: rgba(10,10,12,200); color: {self.pen_color}; border: 1px solid {self.pen_color};"
            f" border-radius: 6px; padding: 4px 8px; font-size: 14px; font-weight: 600; }}")
        edit.resize(260, 32)
        edit.move(int(pos.x()), int(pos.y()) - 24)
        edit.returnPressed.connect(self._commit_text)
        edit.editingFinished.connect(self._commit_text)
        edit.show()
        edit.setFocus()
        self._text_edit = edit

    def _commit_text(self) -> None:
        edit = self._text_edit
        if edit is None:
            return
        self._text_edit = None
        text = edit.text().strip()
        edit.hide()
        edit.deleteLater()
        if text:
            size = self.pen_size / self._image_scale()
            shape = Shape("text", [self._text_anchor], self.pen_color, max(size, 1.0), 1.0, text, False, self.pen_hold)
            self.shapeFinished.emit(shape)
        self.setFocus()

    # ---------------------------------------------------------------- drag and drop

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            ev.acceptProposedAction()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._auto_fit:
            self._pending_fit = True
