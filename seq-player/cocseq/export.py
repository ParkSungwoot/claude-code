"""Export: image sequences and movies with the viewer's color baked in, stills and PDF review notes.

Everything here runs in the GUI thread because the viewer's OpenGL context lives there; file reads
and encodes are pushed to small worker pools so the GPU pass, decoding and encoding overlap.
The playback reader (``source.reader``) is never used: every export reads through its own clone.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Callable, NamedTuple

import numpy as np
from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetricsF, QImage, QPageLayout,
                           QPageSize, QPainter, QPainterPath, QPdfWriter, QPen, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from cocseq.annotations import render_layer
from cocseq.media.frame import Frame
from cocseq.theme import MONO_FONT, PAL, UI_FONT, mono_font, ui_font
from cocseq.utils import fps_label, frames_to_timecode, human_bytes

log = logging.getLogger(__name__)

APP_NAME = "COC_SEQ Player"


# ====================================================================== formats


class FormatSpec(NamedTuple):
    label: str
    ext: str
    is_movie: bool
    supports_alpha: bool


FORMATS: dict[str, FormatSpec] = {
    "png": FormatSpec("PNG 시퀀스 (8비트)", ".png", False, True),
    "png16": FormatSpec("PNG 시퀀스 (16비트)", ".png", False, True),
    "jpg": FormatSpec("JPEG 시퀀스", ".jpg", False, False),
    "tif8": FormatSpec("TIFF 시퀀스 (8비트)", ".tif", False, True),
    "tif16": FormatSpec("TIFF 시퀀스 (16비트)", ".tif", False, True),
    "exr": FormatSpec("OpenEXR 시퀀스 (half)", ".exr", False, True),
    "dpx10": FormatSpec("DPX 시퀀스 (10비트)", ".dpx", False, False),
    "mp4_h264": FormatSpec("MP4 · H.264", ".mp4", True, False),
    "mp4_h265": FormatSpec("MP4 · H.265 (HEVC)", ".mp4", True, False),
    "mov_prores422hq": FormatSpec("MOV · ProRes 422 HQ", ".mov", True, False),
    "mov_prores4444": FormatSpec("MOV · ProRes 4444", ".mov", True, True),
    "mov_mjpeg": FormatSpec("MOV · Motion JPEG", ".mov", True, False),
}

# fmt -> (kind, minimum, maximum, default). "crf": lower is better; "jpeg": higher is better.
QUALITY: dict[str, tuple[str, int, int, int]] = {
    "jpg": ("jpeg", 1, 100, 95),
    "mov_mjpeg": ("jpeg", 1, 100, 90),
    "mp4_h264": ("crf", 0, 51, 18),
    "mp4_h265": ("crf", 0, 51, 20),
}

SCALES = (1.0, 0.75, 0.5, 0.25)

_PIXEL_TYPES = {"png": "uint8", "png16": "uint16", "jpg": "uint8", "tif8": "uint8", "tif16": "uint16",
                "exr": "half", "dpx10": "uint16"}


@dataclass(frozen=True)
class _MovieCodec:
    codec: str
    pix_fmt: str
    src_format: str             # numpy layout handed to PyAV: rgb24 / rgb48le / rgba64le
    colorspace: str             # RGB -> YUV matrix
    color_range: str            # MPEG (limited) or JPEG (full)
    even: bool                  # chroma subsampling needs even dimensions
    options: tuple = ()
    tag: str = ""


def _movie_codec(fmt: str, alpha: bool, quality: int) -> _MovieCodec:
    if fmt == "mp4_h264":
        return _MovieCodec("libx264", "yuv420p", "rgb24", "ITU709", "MPEG", True,
                           (("crf", str(quality)), ("preset", "medium")))
    if fmt == "mp4_h265":
        return _MovieCodec("libx265", "yuv420p", "rgb24", "ITU709", "MPEG", True,
                           (("crf", str(quality)), ("preset", "medium"), ("x265-params", "log-level=error")),
                           tag="hvc1")
    if fmt == "mov_prores422hq":
        return _MovieCodec("prores_ks", "yuv422p10le", "rgb48le", "ITU709", "MPEG", True,
                           (("profile", "3"), ("vendor", "apl0")))
    if fmt == "mov_prores4444":
        if alpha:
            return _MovieCodec("prores_ks", "yuva444p10le", "rgba64le", "ITU709", "MPEG", False,
                               (("profile", "4"), ("vendor", "apl0"), ("alpha_bits", "16")))
        return _MovieCodec("prores_ks", "yuv444p10le", "rgb48le", "ITU709", "MPEG", False,
                           (("profile", "4"), ("vendor", "apl0")))
    if fmt == "mov_mjpeg":
        # -q:v style constant quantizer: 2 (best) .. 31 (worst), lambda = q * FF_QP2LAMBDA.
        q = int(round(31 - (max(1, min(100, quality)) / 100.0) * 29))
        q = max(2, min(31, q))
        return _MovieCodec("mjpeg", "yuvj422p", "rgb24", "ITU601", "JPEG", True,
                           (("flags", "+qscale"), ("global_quality", str(q * 118)), ("qmin", "1"),
                            ("qmax", str(q))))
    raise ValueError(f"unknown movie format {fmt}")


def default_quality(fmt: str) -> int:
    q = QUALITY.get(fmt)
    return q[3] if q else 0


def format_bits(fmt: str) -> int:
    return {"png16": 16, "tif16": 16, "exr": 16, "dpx10": 10, "mov_prores422hq": 10,
            "mov_prores4444": 10}.get(fmt, 8)


# ====================================================================== settings


@dataclass
class ExportSettings:
    path: str = ""                      # sequences: pattern with #### or %04d; movies: file path
    fmt: str = "png"
    first: int = 1                      # source frame numbers (inclusive)
    last: int = 1
    start_number: int | None = None     # output number of the first frame (sequences); None = first
    scale: float = 1.0
    width: int = 0                      # > 0 overrides scale (height follows the aspect)
    apply_color: bool = True            # bake the viewer's color pipeline (always on except EXR)
    burn_annotations: bool = False
    include_audio: bool = False
    quality: int = 0                    # jpeg 1-100 / crf 0-51; 0 = format default
    fps: float = 0.0                    # 0 = the source rate
    alpha: bool = False

    @property
    def spec(self) -> FormatSpec:
        return FORMATS[self.fmt]

    @property
    def is_movie(self) -> bool:
        return FORMATS[self.fmt].is_movie

    @property
    def frame_count(self) -> int:
        return max(0, self.last - self.first + 1)

    def output_number(self, frame: int) -> int:
        start = self.first if self.start_number is None else self.start_number
        return start + (frame - self.first)

    def output_path(self, frame: int | None = None) -> str:
        """File written for a source frame (the movie path for movies)."""
        if self.is_movie:
            return self.path
        return sequence_path(self.path, self.output_number(self.first if frame is None else frame))


class ExportError(RuntimeError):
    pass


class ExportCancelled(Exception):
    pass


# ====================================================================== helpers

_TOKEN_RE = re.compile(r"#+|%0?(\d*)d")


def has_frame_token(path: str) -> bool:
    return bool(_TOKEN_RE.search(os.path.basename(path)))


def sequence_path(pattern: str, number: int) -> str:
    """Replace the frame token (####, %04d) of a pattern's file name with a frame number."""
    folder, base = os.path.split(pattern)
    matches = list(_TOKEN_RE.finditer(base))
    if not matches:
        stem, ext = os.path.splitext(base)
        base = f"{stem}.####{ext}"
        matches = list(_TOKEN_RE.finditer(base))
    m = matches[-1]
    tok = m.group(0)
    pad = len(tok) if tok.startswith("#") else int(m.group(1) or 0)
    num = f"{number:0{pad}d}" if number >= 0 else "-" + f"{-number:0{pad}d}"
    return os.path.join(folder, base[:m.start()] + num + base[m.end():])


def with_extension(path: str, fmt: str) -> str:
    """Swap the extension (and add/remove the frame token) for a format."""
    spec = FORMATS[fmt]
    folder, base = os.path.split(path)
    stem, ext = os.path.splitext(base)
    if ext.lower() not in {f.ext for f in FORMATS.values()} | {".jpeg", ".tiff", ".mxf", ".mkv", ".avi"}:
        stem, ext = base, ""
    if spec.is_movie:
        stem = _TOKEN_RE.sub("", stem).rstrip("._- ") or "export"
    elif not _TOKEN_RE.search(stem):
        stem = f"{stem}.####"
    return os.path.join(folder, stem + spec.ext)


def clip_basename(source) -> str:
    """A clean name for files derived from a clip (no frame token, no extension)."""
    if source.kind == "movie" or not getattr(source, "seq", None):
        return os.path.splitext(os.path.basename(source.path))[0] or "export"
    seq = source.seq
    if seq.single_file:
        return os.path.splitext(os.path.basename(seq.single_file))[0] or "export"
    return seq.prefix.rstrip("._- ") or "export"


def default_output_path(source, fmt: str) -> str:
    folder = os.path.join(source.directory, "export")
    name = clip_basename(source)
    spec = FORMATS[fmt]
    if spec.is_movie:
        return os.path.join(folder, name + spec.ext)
    return os.path.join(folder, f"{name}.####{spec.ext}")


def fps_fraction(fps: float) -> Fraction:
    """Exact frame rate: 23.976 -> 24000/1001, 29.97 -> 30000/1001, 59.94 -> 60000/1001."""
    fps = float(fps or 24.0)
    if abs(fps - round(fps)) < 1e-3:
        return Fraction(int(round(fps)), 1)
    n = round(fps * 1.001)
    if abs(fps - n / 1.001) < 0.006:
        return Fraction(n * 1000, 1001)
    return Fraction(fps).limit_denominator(1001)


def source_has_alpha(source) -> bool:
    chans = list(getattr(source.layer, "channels", []) or [])
    if len(chans) == 2:
        return True
    return any(c.split(".")[-1].upper() in ("A", "ALPHA") for c in chans)


def has_drawings(source) -> bool:
    store = getattr(source, "annotations", None)
    return bool(store is not None and any(store.frames.values()))


def _source_windows(source) -> tuple[tuple, float]:
    info = source.info
    disp = info.display_window if info.display_window and info.display_window[2] else \
        (0, 0, info.width or 1920, info.height or 1080)
    return tuple(disp), float(info.par or 1.0)


def _scaled_size(disp_w: int, disp_h: int, par: float, scale: float, width: int) -> tuple[int, int]:
    """Output size before the even-dimension crop."""
    w = max(1, int(round(disp_w * par))) if abs(par - 1.0) > 1e-3 else disp_w
    h = max(1, disp_h)
    if width and width > 0:
        return max(1, int(width)), max(1, int(round(h * width / max(1, w))))
    s = scale if scale and scale > 0 else 1.0
    return max(1, int(round(w * s))), max(1, int(round(h * s)))


def output_size(fmt: str, disp_w: int, disp_h: int, par: float = 1.0, scale: float = 1.0,
                width: int = 0, alpha: bool = False) -> tuple[int, int]:
    """Final pixel size of an export (pixel aspect is applied for movies only)."""
    movie = FORMATS[fmt].is_movie
    w, h = _scaled_size(disp_w, disp_h, par if movie else 1.0, scale, width)
    if movie and _movie_codec(fmt, alpha, default_quality(fmt) or 1).even:
        w, h = max(2, w - (w % 2)), max(2, h - (h % 2))
    return w, h


def source_output_size(settings: ExportSettings, source) -> tuple[int, int]:
    disp, par = _source_windows(source)
    return output_size(settings.fmt, disp[2], disp[3], par, settings.scale, settings.width, settings.alpha)


# ---------------------------------------------------------------------- pixels


def _to_rgba(px: np.ndarray) -> np.ndarray:
    """(h, w, c) float -> (h, w, 4) float32 the way the viewer interprets channels."""
    px = px.astype(np.float32, copy=False)
    c = px.shape[2]
    h, w = px.shape[:2]
    out = np.empty((h, w, 4), np.float32)
    if c == 1:
        out[..., :3] = px[..., :1]
        out[..., 3] = 1.0
    elif c == 2:
        out[..., :3] = px[..., :1]
        out[..., 3] = px[..., 1]
    elif c == 3:
        out[..., :3] = px
        out[..., 3] = 1.0
    else:
        out[...] = px[..., :4]
    return out


def _place(img: np.ndarray, data_window, display_window) -> np.ndarray:
    """Put a data window image into a display window canvas (cropping anything outside it)."""
    dx, dy = int(data_window[0]), int(data_window[1])
    h, w = img.shape[:2]
    fx, fy, fw, fh = (int(v) for v in display_window)
    if (dx, dy, w, h) == (fx, fy, fw, fh):
        return img
    canvas = np.zeros((fh, fw, img.shape[2]), img.dtype)
    x0, y0 = max(dx, fx), max(dy, fy)
    x1, y1 = min(dx + w, fx + fw), min(dy + h, fy + fh)
    if x1 > x0 and y1 > y0:
        canvas[y0 - fy:y1 - fy, x0 - fx:x1 - fx] = img[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return canvas


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """High quality float resize (OpenImageIO), with a plain numpy fallback."""
    ih, iw = img.shape[:2]
    if (iw, ih) == (w, h):
        return img
    src = np.ascontiguousarray(img, np.float32)
    try:
        import OpenImageIO as oiio

        buf = oiio.ImageBuf(src)
        out = oiio.ImageBufAlgo.resize(buf, roi=oiio.ROI(0, w, 0, h, 0, 1, 0, src.shape[2]))
        px = out.get_pixels(oiio.FLOAT)
        if px is not None and px.shape[:2] == (h, w):
            return px.reshape(h, w, src.shape[2])
    except Exception as exc:  # pragma: no cover - OIIO missing
        log.debug("oiio resize failed: %s", exc)
    ys = np.minimum(((np.arange(h) + 0.5) * ih / h).astype(np.int64), ih - 1)
    xs = np.minimum(((np.arange(w) + 0.5) * iw / w).astype(np.int64), iw - 1)
    return src[ys][:, xs]


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4)).astype(np.float32)


def _annotation_transform(disp, out_w: int, out_h: int) -> QTransform:
    sx = out_w / max(1, disp[2])
    sy = out_h / max(1, disp[3])
    return QTransform(sx, 0, 0, sy, -disp[0] * sx, -disp[1] * sy)


def _overlay(shapes, disp, out_w: int, out_h: int) -> np.ndarray | None:
    """Annotations drawn at the output size, as premultiplied float RGBA (h, w, 4)."""
    if not shapes:
        return None
    layer = render_layer((out_w, out_h), shapes, _annotation_transform(disp, out_w, out_h))
    layer = layer.convertToFormat(QImage.Format_RGBA8888_Premultiplied)
    h, w, bpl = layer.height(), layer.width(), layer.bytesPerLine()
    raw = np.frombuffer(layer.constBits(), np.uint8, count=bpl * h).reshape(h, bpl)[:, : w * 4]
    arr = raw.reshape(h, w, 4)
    if not arr[..., 3].any():
        return None
    return arr.astype(np.float32) * (1.0 / 255.0)


def _composite(img: np.ndarray, over: np.ndarray, linear: bool = False, ox: int = 0, oy: int = 0) -> None:
    """Premultiplied `over` on top of img[..., :3] (and alpha when img has 4 channels), in place.

    (ox, oy) is where img's top-left pixel sits inside `over`.
    """
    oh, ow = over.shape[:2]
    ih, iw = img.shape[:2]
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(ow, ox + iw), min(oh, oy + ih)
    if x1 <= x0 or y1 <= y0:
        return
    o = over[y0:y1, x0:x1]
    a = o[..., 3:4]
    rgb = o[..., :3]
    if linear:
        straight = np.where(a > 1e-6, rgb / np.maximum(a, 1e-6), 0.0)
        rgb = _srgb_to_linear(straight) * a
    tgt = img[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    nc = min(3, tgt.shape[2])
    base = tgt[..., :nc].astype(np.float32)
    tgt[..., :nc] = (rgb[..., :nc] + base * (1.0 - a)).astype(tgt.dtype)
    if tgt.shape[2] >= 4:
        ta = tgt[..., 3:4].astype(np.float32)
        tgt[..., 3:4] = (a + ta * (1.0 - a)).astype(tgt.dtype)


def _quantize(img: np.ndarray, ptype: str) -> np.ndarray:
    if ptype == "uint8":
        return (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    if ptype == "uint16":
        return (np.clip(img, 0.0, 1.0) * 65535.0 + 0.5).astype(np.uint16)
    if ptype == "half":
        return np.ascontiguousarray(img, np.float32).astype(np.float16)
    return np.ascontiguousarray(img, np.float32)


def write_image(path: str, pixels: np.ndarray, fmt: str, *, channel_names=None, data_window=None,
                display_window=None, fps: float = 0.0, par: float = 1.0, quality: int = 0,
                pixel_type: str | None = None) -> None:
    """Write one image with OpenImageIO. `pixels` is float (converted) unless pixel_type is given."""
    import OpenImageIO as oiio

    if pixels.ndim == 2:
        pixels = pixels[:, :, None]
    h, w, c = pixels.shape
    ptype = pixel_type or _PIXEL_TYPES[fmt]
    spec = oiio.ImageSpec(w, h, c, ptype)
    if channel_names:
        spec.channelnames = tuple(channel_names)
    elif c == 4:
        spec.channelnames = ("R", "G", "B", "A")
    elif c == 3:
        spec.channelnames = ("R", "G", "B")
    if data_window is not None:
        spec.x, spec.y = int(data_window[0]), int(data_window[1])
    if display_window is not None:
        spec.full_x, spec.full_y = int(display_window[0]), int(display_window[1])
        spec.full_width, spec.full_height = int(display_window[2]), int(display_window[3])
    spec.attribute("Software", APP_NAME)
    if fmt == "exr":
        spec.attribute("compression", "zip")
    elif fmt == "jpg":
        q = max(1, min(100, int(quality or 95)))
        spec.attribute("Compression", f"jpeg:{q}")
        if q >= 90:
            spec.attribute("jpeg:subsampling", "4:4:4")    # no chroma bleeding on review stills
    elif fmt in ("tif8", "tif16"):
        spec.attribute("compression", "zip")
    elif fmt in ("png", "png16"):
        spec.attribute("png:compressionLevel", 6)
    elif fmt == "dpx10":
        spec.attribute("oiio:BitsPerSample", 10)
    if fps and fmt in ("exr", "dpx10"):
        fr = fps_fraction(fps)
        spec.attribute("FramesPerSecond", oiio.TypeDesc("rational"), (fr.numerator, fr.denominator))
    if par and abs(par - 1.0) > 1e-4:
        spec.attribute("PixelAspectRatio", float(par))
    data = pixels if pixel_type else _quantize(pixels, ptype)
    data = np.ascontiguousarray(data)
    out = oiio.ImageOutput.create(path)
    if not out:
        raise ExportError(f"이 형식으로 쓸 수 없습니다: {os.path.basename(path)}\n{oiio.geterror()}")
    try:
        if not out.open(path, spec):
            raise ExportError(f"파일을 만들 수 없습니다: {path}\n{out.geterror()}")
        if not out.write_image(data):
            raise ExportError(f"이미지를 쓰지 못했습니다: {path}\n{out.geterror()}")
    finally:
        out.close()


def _qimage_rgb(img: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray((np.clip(img[..., :3], 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


# ====================================================================== audio


class _AudioFeed:
    """Hands out the audio that belongs to each exported frame (sample exact, zero padded)."""

    def __init__(self, track, t0: float, fps: float):
        self.track = track
        self.rate = int(track.rate)
        self.fps = float(fps)
        self.start = int(round(t0 * self.rate))

    def _bound(self, i: int) -> int:
        return self.start + int(round(i * self.rate / self.fps))

    def chunk(self, i: int) -> np.ndarray:
        a, b = self._bound(i), self._bound(i + 1)
        return self.track.slice(a / self.rate, b / self.rate)


def _audio_track(source):
    track = getattr(source, "audio", None)
    if track is not None and getattr(track, "path", "") == source.audio_path:
        return track
    from cocseq.media.audio import decode_audio

    return decode_audio(source.audio_path)


# ====================================================================== sinks


class _SequenceSink:
    parallel = 3

    def __init__(self, settings: ExportSettings, keep_alpha: bool):
        self.s = settings
        self.keep_alpha = keep_alpha
        self.written: list[str] = []
        folder = os.path.dirname(settings.path)
        if folder:
            os.makedirs(folder, exist_ok=True)

    def write(self, item: dict) -> None:
        s = self.s
        path = s.output_path(item["frame"])
        if item.get("raw"):
            write_image(path, item["pixels"], "exr", channel_names=item["names"], data_window=item["data"],
                        display_window=item["disp"], fps=s.fps, par=item["par"], pixel_type=item["ptype"])
        else:
            px = item["pixels"]
            if not (self.keep_alpha and px.shape[2] >= 4):
                px = px[..., :3]
            write_image(path, px, s.fmt, fps=s.fps, par=item["par"], quality=s.quality)
        self.written.append(path)

    def finish(self) -> None:
        pass

    def abort(self) -> None:
        pass


class _MovieSink:
    parallel = 1

    def __init__(self, settings: ExportSettings, size: tuple[int, int], keep_alpha: bool, audio: _AudioFeed | None,
                 title: str = ""):
        import av
        from av.video.reformatter import VideoReformatter

        self.av = av
        self.s = settings
        self.path = settings.path
        self.size = size
        self.cfg = _movie_codec(settings.fmt, keep_alpha, settings.quality)
        self.keep_alpha = keep_alpha
        self.audio = audio
        self.audio_pos = 0
        self.frames = 0
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        try:
            self.container = av.open(self.path, "w", container_options={"movflags": "+faststart"})
        except Exception as exc:
            raise ExportError(f"파일을 만들 수 없습니다: {self.path}\n{exc}") from exc
        try:
            if title:
                self.container.metadata["title"] = title
            self.container.metadata["comment"] = f"Exported with {APP_NAME}"
            vs = self.container.add_stream(self.cfg.codec, rate=fps_fraction(settings.fps))
            vs.width, vs.height = size
            vs.pix_fmt = self.cfg.pix_fmt
            vs.options = dict(self.cfg.options)
            cc = vs.codec_context
            if self.cfg.tag:
                cc.codec_tag = self.cfg.tag
            try:
                if self.cfg.colorspace == "ITU709":
                    cc.color_primaries, cc.color_trc, cc.colorspace = 1, 1, 1
                else:
                    cc.color_primaries, cc.color_trc, cc.colorspace = 1, 1, 5
                cc.color_range = 2 if self.cfg.color_range == "JPEG" else 1
            except Exception:
                log.debug("color tags not supported", exc_info=True)
            self.vstream = vs
            self.astream = None
            if audio is not None:
                codec = "pcm_s16le" if settings.path.lower().endswith(".mov") else "aac"
                a = self.container.add_stream(codec, rate=audio.rate)
                a.layout = "stereo"
                if codec == "aac":
                    a.bit_rate = 192000
                self.astream = a
            self.reformatter = VideoReformatter()
        except Exception:
            self.abort()
            raise

    def _mux(self, packets) -> None:
        for p in packets:
            self.container.mux(p)

    def write(self, item: dict) -> None:
        av = self.av
        cfg = self.cfg
        img = item["pixels"]
        w, h = self.size
        if img.shape[1] != w or img.shape[0] != h:
            img = _resize(img, w, h)
        if cfg.src_format == "rgb24":
            arr = _quantize(img[..., :3], "uint8")
        elif cfg.src_format == "rgb48le":
            arr = _quantize(img[..., :3], "uint16")
        else:
            rgba = img if img.shape[2] >= 4 else _to_rgba(img)
            arr = _quantize(rgba[..., :4], "uint16")
        vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format=cfg.src_format)
        out = self.reformatter.reformat(vf, format=cfg.pix_fmt, src_colorspace=cfg.colorspace,
                                        dst_colorspace=cfg.colorspace, src_color_range="JPEG",
                                        dst_color_range=cfg.color_range, interpolation="BICUBIC")
        out.pts = self.frames
        self._mux(self.vstream.encode(out))
        if self.astream is not None:
            chunk = self.audio.chunk(self.frames)
            if len(chunk):
                af = av.AudioFrame.from_ndarray(np.ascontiguousarray(chunk.T, np.float32), format="fltp",
                                                layout="stereo")
                af.sample_rate = self.audio.rate
                af.pts = self.audio_pos
                af.time_base = Fraction(1, self.audio.rate)
                self.audio_pos += len(chunk)
                self._mux(self.astream.encode(af))
        self.frames += 1

    def finish(self) -> None:
        try:
            self._mux(self.vstream.encode(None))
            if self.astream is not None:
                self._mux(self.astream.encode(None))
        finally:
            self.container.close()
            self.container = None

    def abort(self) -> None:
        c = getattr(self, "container", None)
        self.container = None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


# ====================================================================== exporter


class Exporter:
    """Renders frames through the viewer's color pipeline and writes them to disk."""

    PREFETCH = 3          # decoded frames waiting for the GPU pass
    MAX_PENDING = 3       # rendered frames waiting for the encoder (bounds memory at 4K)

    def __init__(self):
        self.warnings: list[str] = []
        self.missing: list[int] = []
        self.written = 0
        self.output_size: tuple[int, int] = (0, 0)
        self.elapsed = 0.0
        self._cpu_warned = False

    # ------------------------------------------------------------ settings

    @staticmethod
    def prepare(settings: ExportSettings, source) -> ExportSettings:
        """A normalized copy: valid range, forced options, defaults filled in."""
        if settings.fmt not in FORMATS:
            raise ExportError(f"알 수 없는 형식: {settings.fmt}")
        s = replace(settings)
        spec = FORMATS[s.fmt]
        lo, hi = source.first, source.last
        s.first = max(lo, min(int(s.first), hi))
        s.last = max(s.first, min(int(s.last), hi))
        if s.fmt != "exr":
            s.apply_color = True
        s.alpha = bool(s.alpha and spec.supports_alpha and source_has_alpha(source))
        s.burn_annotations = bool(s.burn_annotations and has_drawings(source))
        s.include_audio = bool(s.include_audio and spec.is_movie and source.audio_path)
        if not s.fps or s.fps <= 0:
            s.fps = float(source.fps or 24.0)
        q = QUALITY.get(s.fmt)
        if q:
            s.quality = int(s.quality) if s.quality else q[3]
            s.quality = max(q[1], min(q[2], s.quality))
        if not s.path:
            s.path = default_output_path(source, s.fmt)
        if not spec.is_movie and not has_frame_token(s.path):
            stem, ext = os.path.splitext(s.path)
            s.path = f"{stem}.####{ext or spec.ext}"
        return s

    # ------------------------------------------------------------ frame processing

    def _display_pixels(self, source, viewer, frame: Frame) -> np.ndarray:
        """Display-referred RGBA of the data window."""
        img = viewer.render_to_array(source, frame) if viewer is not None else None
        if img is not None:
            return img
        # No OpenGL: approximate with the OCIO CPU processor (grade controls are not applied).
        if not self._cpu_warned:
            self._cpu_warned = True
            self.warnings.append("OpenGL을 쓸 수 없어 CPU 색 변환으로 내보냈습니다 (노출/감마 조정 제외).")
            log.warning("export: viewer GL unavailable, using CPU color conversion")
        rgba = _to_rgba(frame.normalized())
        cm = getattr(viewer, "colors", None)
        d = getattr(viewer, "display", None)
        if cm is not None and d is not None:
            fn = cm.cpu_function(source.colorspace, d.display, d.view, d.look, d.lut, d.lut_mode)
        else:
            def fn(rgb):
                x = np.clip(rgb, 0, None)
                return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
        rgba[..., :3] = fn(np.ascontiguousarray(rgba[..., :3]))
        return rgba

    def render_display(self, s: ExportSettings, source, viewer, frame: Frame | None, n: int,
                       fixed_size: tuple[int, int] | None = None, last: dict | None = None) -> dict:
        """One output frame (display-referred float RGBA at the output size) with annotations burned."""
        movie = s.is_movie
        if frame is None or frame.missing or frame.pixels is None:
            disp = (last or {}).get("disp") or _source_windows(source)[0]
            par = (last or {}).get("par") or _source_windows(source)[1]
            canvas = np.zeros((int(disp[3]), int(disp[2]), 4), np.float32)
            canvas[..., 3] = 1.0
        else:
            img = self._display_pixels(source, viewer, frame)
            dw = frame.data_window if frame.data_window[2] else (0, 0, img.shape[1], img.shape[0])
            disp = frame.display_window if frame.display_window[2] else dw
            if img.shape[:2] != (dw[3], dw[2]):
                dw = (dw[0], dw[1], img.shape[1], img.shape[0])
            canvas = _place(img, dw, disp)
            par = float(frame.par or 1.0)
        if last is not None:
            last["disp"], last["par"] = tuple(disp), par
        tw, th = _scaled_size(int(disp[2]), int(disp[3]), par if movie else 1.0, s.scale, s.width)
        canvas = _resize(canvas, tw, th)
        if not canvas.flags.writeable or canvas.dtype != np.float32:
            canvas = np.array(canvas, np.float32)
        if s.burn_annotations:
            over = _overlay(source.annotations.visible(n, 0), disp, tw, th)
            if over is not None:
                _composite(canvas, over)
        if fixed_size is not None and (tw, th) != fixed_size:
            fw, fh = fixed_size
            if tw - fw in (0, 1) and th - fh in (0, 1):
                canvas = canvas[:fh, :fw]
            else:
                canvas = _resize(canvas, fw, fh)
        return {"frame": n, "pixels": canvas, "par": 1.0 if movie else par}

    def render_raw(self, s: ExportSettings, source, frame: Frame | None, n: int, last: dict | None = None) -> dict:
        """Raw layer values for EXR: original channels, data and display windows (scaled if asked)."""
        if frame is None or frame.missing or frame.pixels is None:
            if last and "raw" in last:
                prev = last["raw"]
                px = np.zeros_like(prev["pixels"])
                item = dict(prev)
                item.update(frame=n, pixels=px)
                return item
            disp, par = _source_windows(source)
            names = list(source.layer.channels) or ["R", "G", "B"]
            px = np.zeros((int(disp[3]), int(disp[2]), len(names)), np.float16)
            dw = disp
        else:
            px = frame.pixels
            names = list(frame.channel_names) or [f"C{i}" for i in range(px.shape[2])]
            dw = frame.data_window if frame.data_window[2] else (0, 0, px.shape[1], px.shape[0])
            disp = frame.display_window if frame.display_window[2] else dw
            par = float(frame.par or 1.0)
        ptype = "float" if px.dtype == np.float32 else "half"
        if px.dtype == np.uint8:
            px = (px.astype(np.float32) / 255.0).astype(np.float16)
        elif px.dtype == np.uint16:
            px = (px.astype(np.float32) / 65535.0).astype(np.float16)
        tw, th = _scaled_size(int(disp[2]), int(disp[3]), 1.0, s.scale, s.width)
        sx, sy = tw / max(1, disp[2]), th / max(1, disp[3])
        if (tw, th) != (disp[2], disp[3]):
            ndw = (int(round(dw[0] * sx)), int(round(dw[1] * sy)),
                   max(1, int(round(dw[2] * sx))), max(1, int(round(dw[3] * sy))))
            px = _resize(px.astype(np.float32), ndw[2], ndw[3])
            px = px.astype(np.float16) if ptype == "half" else px
            ndisp = (int(round(disp[0] * sx)), int(round(disp[1] * sy)), tw, th)
        else:
            ndw, ndisp = tuple(dw), tuple(disp)
        if s.burn_annotations and px.shape[2] >= 3:
            over = _overlay(source.annotations.visible(n, 0), ndisp, tw, th)
            if over is not None:
                px = np.array(px, copy=True)
                _composite(px, over, linear=True, ox=ndw[0] - ndisp[0], oy=ndw[1] - ndisp[1])
        item = {"frame": n, "raw": True, "pixels": np.ascontiguousarray(px), "names": names, "data": ndw,
                "disp": ndisp, "par": par, "ptype": ptype}
        if last is not None:
            last["raw"] = item
        return item

    # ------------------------------------------------------------ run

    def run(self, settings: ExportSettings, source, viewer, progress: Callable[[int, int], bool] | None = None) -> str:
        """Export and return a short description. Raises ExportCancelled when progress() returns False."""
        t_start = time.monotonic()
        s = self.prepare(settings, source)
        spec = s.spec
        raw = s.fmt == "exr" and not s.apply_color
        keep_alpha = s.alpha
        frames = list(range(s.first, s.last + 1))
        total = len(frames)
        progress = progress or (lambda _d, _t: True)

        reader = source.reader.clone()          # never the playback reader
        layer = source.layer
        sink = None
        fixed = None
        read_pool = write_pool = None
        pending_reads: deque = deque()
        pending_writes: deque = deque()
        try:
            if spec.is_movie:
                disp, par = _source_windows(source)
                fixed = output_size(s.fmt, int(disp[2]), int(disp[3]), par, s.scale, s.width, keep_alpha)
                audio = None
                if s.include_audio:
                    track = _audio_track(source)
                    if track is None:
                        self.warnings.append("오디오를 읽지 못해 영상만 내보냈습니다.")
                    else:
                        fps = float(source.fps or s.fps)
                        t0 = (s.first - source.first) / fps - track.start - source.audio_offset / fps
                        audio = _AudioFeed(track, t0, fps)
                        if abs(fps - s.fps) > 1e-3:
                            self.warnings.append("FPS가 원본과 달라 오디오 길이가 영상과 다를 수 있습니다.")
                sink = _MovieSink(s, fixed, keep_alpha, audio, title=clip_basename(source))
                self.output_size = fixed
            else:
                sink = _SequenceSink(s, keep_alpha)
                disp, _par = _source_windows(source)
                self.output_size = _scaled_size(int(disp[2]), int(disp[3]), 1.0, s.scale, s.width)

            nread = 3 if getattr(reader, "thread_safe", False) else 1
            read_pool = ThreadPoolExecutor(max_workers=nread, thread_name_prefix="export-read")
            write_pool = ThreadPoolExecutor(max_workers=sink.parallel, thread_name_prefix="export-write")
            next_read = 0
            last: dict = {}
            if progress(0, total) is False:
                raise ExportCancelled()
            for i, n in enumerate(frames):
                while next_read < total and len(pending_reads) < self.PREFETCH:
                    pending_reads.append(read_pool.submit(reader.read, frames[next_read], layer))
                    next_read += 1
                frame = pending_reads.popleft().result()
                if frame is None or frame.missing or frame.pixels is None:
                    self.missing.append(n)
                    log.warning("export: frame %d missing (%s), writing black", n,
                                getattr(frame, "error", "") or "no file")
                if raw:
                    item = self.render_raw(s, source, frame, n, last)
                else:
                    item = self.render_display(s, source, viewer, frame, n, fixed, last)
                pending_writes.append(write_pool.submit(sink.write, item))
                while pending_writes and (len(pending_writes) > self.MAX_PENDING or pending_writes[0].done()):
                    pending_writes.popleft().result()
                    self.written += 1
                if progress(i + 1, total) is False:
                    raise ExportCancelled()
            while pending_writes:
                pending_writes.popleft().result()
                self.written += 1
            sink.finish()
        except BaseException:
            for f in pending_reads:
                f.cancel()
            for f in pending_writes:
                try:
                    f.result()
                except BaseException:
                    pass
            if sink is not None:
                sink.abort()
            raise
        finally:
            if read_pool is not None:
                read_pool.shutdown(wait=True, cancel_futures=True)
            if write_pool is not None:
                write_pool.shutdown(wait=True)
            try:
                reader.close()
            except Exception:
                pass
            if viewer is not None:
                try:
                    viewer.release_export()
                except Exception:
                    log.debug("release_export failed", exc_info=True)
        if self.missing:
            self.warnings.append(f"누락된 프레임 {len(self.missing)}개를 검은 화면으로 채웠습니다.")
        self.elapsed = time.monotonic() - t_start
        self.settings = s
        w, h = self.output_size
        if spec.is_movie:
            where = s.path
        else:
            a, b = s.output_number(s.first), s.output_number(s.last)
            where = s.path if a == b else f"{s.path}  ({a}–{b})"
        return f"{spec.label} · {total}프레임 · {w}×{h}\n{where}"


# ====================================================================== GUI helpers


def _dialog_parent(parent):
    return parent.window() if parent is not None and hasattr(parent, "window") else parent


def _badge(icon_name: str, color: str, size: int = 38) -> QLabel:
    badge = QLabel()
    badge.setFixedSize(size, size)
    badge.setAlignment(Qt.AlignCenter)
    badge.setStyleSheet(f"background: {PAL.rgba(color, 0.15)}; border-radius: {size // 2 - 8}px;")
    try:
        from cocseq import icons

        badge.setPixmap(icons.pixmap(icon_name, 20, color))
    except Exception:
        pass
    return badge


class _ProgressDialog(QDialog):
    """Window-modal progress with a thin bar, ETA and a 취소 button (QProgressDialog-like API)."""

    def __init__(self, parent, title: str, subtitle: str, total: int, verb: str, icon_name: str = "export"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModal)
        self.setMinimumWidth(460)
        self._canceled = False
        self.verb = verb
        self.total = max(1, total)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_badge(icon_name, PAL.accent), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title_label = QLabel()
        self.title_label.setTextFormat(Qt.RichText)
        col.addWidget(self.title_label)
        sub = QLabel(QFontMetricsF(ui_font()).elidedText(subtitle, Qt.ElideMiddle, 360))
        sub.setProperty("class", "muted")
        sub.setToolTip(subtitle)
        col.addWidget(sub)
        head.addLayout(col, 1)
        lay.addLayout(head)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, self.total)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background: {PAL.bg4}; border: none; border-radius: 3px; min-height: 6px; }}"
            f"QProgressBar::chunk {{ background: {PAL.accent}; border-radius: 3px; }}")
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.eta = QLabel("")
        self.eta.setProperty("class", "faint")
        row.addWidget(self.eta, 1)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)
        self.set_progress(0, total)

    def cancel(self) -> None:
        self._canceled = True
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("취소하는 중…")

    def reject(self) -> None:          # Esc / window close
        self.cancel()

    def wasCanceled(self) -> bool:
        return self._canceled

    def set_progress(self, done: int, total: int, eta: str = "") -> None:
        total = max(1, total)
        if self.bar.maximum() != total:
            self.bar.setMaximum(total)
        self.bar.setValue(max(0, min(done, total)))
        self.title_label.setText(
            f"<span style='font-size:14px; font-weight:600; color:{PAL.text}'>{self.verb}… "
            f"<span style='color:{PAL.accent}'>{done}</span> / {total}</span>")
        pct = int(round(100.0 * done / total))
        self.eta.setText(f"{pct}%" + (f"  ·  {eta}" if eta else ""))


class _Progress:
    """Runs the progress dialog; update() pumps the event loop and reports cancellation."""

    def __init__(self, parent, title: str, subtitle: str, total: int, verb: str = "내보내는 중",
                 icon_name: str = "export"):
        self.t0 = time.monotonic()
        self.dialog = _ProgressDialog(_dialog_parent(parent), title, subtitle, total, verb, icon_name)
        self.dialog.show()
        QApplication.processEvents()

    def update(self, done: int, total: int) -> bool:
        eta = ""
        el = time.monotonic() - self.t0
        if 0 < done < total and el > 1.0:
            left = el / done * (total - done)
            eta = f"남은 시간 약 {int(left // 60)}:{int(left % 60):02d}"
        self.dialog.set_progress(done, total, eta)
        QApplication.processEvents()
        return not self.dialog.wasCanceled()

    def close(self) -> None:
        self.dialog.hide()
        self.dialog.deleteLater()


class _ResultDialog(QDialog):
    """Small "done" message with the output file and a button that opens its folder."""

    def __init__(self, parent, title: str, summary: str, path: str, detail: str = "", warnings=()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._path = path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(_badge("check", PAL.ok), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        t = QLabel(title)
        t.setProperty("class", "title")
        col.addWidget(t)
        m = QLabel(summary)
        m.setProperty("class", "muted")
        m.setWordWrap(True)
        col.addWidget(m)
        col.addSpacing(4)
        name = QLabel(os.path.basename(path) + (f"   {detail}" if detail else ""))
        name.setStyleSheet(f"font-family: '{MONO_FONT}', Consolas; font-size: 12px; color: {PAL.text};")
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(name)
        folder = os.path.dirname(path)
        fl = QLabel(QFontMetricsF(mono_font(8.5)).elidedText(folder, Qt.ElideMiddle, 380))
        fl.setProperty("class", "mono")
        fl.setToolTip(folder)
        col.addWidget(fl)
        for w in warnings:
            wl = QLabel(f"⚠  {w}")
            wl.setWordWrap(True)
            wl.setStyleSheet(f"color: {PAL.warn}; padding-top: 4px;")
            col.addWidget(wl)
        head.addLayout(col, 1)
        lay.addLayout(head)
        btns = QHBoxLayout()
        btns.addStretch(1)
        open_btn = QPushButton("폴더 열기")
        try:
            from cocseq import icons

            open_btn.setIcon(icons.icon("folder-open", size=16))
        except Exception:
            pass
        open_btn.clicked.connect(self._open_folder)
        close_btn = QPushButton("닫기")
        close_btn.setProperty("variant", "primary")
        close_btn.setDefault(True)
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        btns.addWidget(open_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        self.setMinimumWidth(460)

    def _open_folder(self) -> None:
        folder = self._path if os.path.isdir(self._path) else os.path.dirname(self._path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.accept()


def export_with_progress(parent, settings: ExportSettings, source, viewer) -> bool:
    """Run an export in the GUI thread with a progress dialog. True when it completed."""
    top = _dialog_parent(parent)
    try:
        s = Exporter.prepare(settings, source)
    except ExportError as exc:
        QMessageBox.warning(top, "내보내기", str(exc))
        return False
    prog = _Progress(parent, "내보내기", f"{s.spec.label}  ·  {os.path.basename(s.path)}", s.frame_count)
    exporter = Exporter()
    try:
        exporter.run(s, source, viewer, prog.update)
    except ExportCancelled:
        prog.close()
        return False
    except Exception as exc:
        prog.close()
        log.exception("export failed")
        QMessageBox.critical(top, "내보내기 실패", f"내보내기 중 문제가 생겼습니다.\n\n{exc}")
        return False
    prog.close()
    w, h = exporter.output_size
    summary = f"{s.spec.label}  ·  {s.frame_count}프레임  ·  {w}×{h}  ·  {exporter.elapsed:.1f}초"
    detail = ""
    if not s.is_movie:
        a, b = s.output_number(s.first), s.output_number(s.last)
        detail = f"{a}–{b}" if a != b else ""
    _ResultDialog(top, "내보내기 완료", summary, s.path, detail, exporter.warnings).exec()
    return True


# ====================================================================== still frame


def _read_frame(source, frame_no: int) -> Frame:
    reader = source.reader.clone()
    try:
        return reader.read(frame_no, source.layer)
    finally:
        try:
            reader.close()
        except Exception:
            pass


_STILL_FORMATS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".tif": "tif16", ".tiff": "tif16", ".exr": "exr",
                  ".dpx": "dpx10"}


def write_still(path: str, viewer, source, frame, with_annotations: bool = True, raw: bool | None = None) -> str:
    """Write one frame. PNG/JPEG/TIFF get the display-referred image; EXR gets the raw layer values."""
    ext = os.path.splitext(path)[1].lower()
    fmt = _STILL_FORMATS.get(ext)
    if fmt is None:
        path, fmt = path + ".png", "png"
    if isinstance(frame, Frame):
        fr, n = frame, frame.frame_no
    else:
        n = int(frame)
        fr = _read_frame(source, n)
    if fr is None or fr.missing or fr.pixels is None:
        raise ExportError(f"프레임 {n}을 읽을 수 없습니다.")
    raw = (fmt == "exr") if raw is None else raw
    s = ExportSettings(path=path, fmt=fmt, first=n, last=n, apply_color=not raw,
                       burn_annotations=bool(with_annotations and has_drawings(source)), fps=source.fps,
                       quality=95)
    ex = Exporter()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    try:
        if raw and fmt == "exr":
            item = ex.render_raw(s, source, fr, n)
            write_image(path, item["pixels"], "exr", channel_names=item["names"], data_window=item["data"],
                        display_window=item["disp"], fps=source.fps, par=item["par"], pixel_type=item["ptype"])
        else:
            item = ex.render_display(s, source, viewer, fr, n)
            write_image(path, item["pixels"][..., :3], fmt, par=item["par"], quality=95, fps=source.fps)
    finally:
        if viewer is not None:
            viewer.release_export()
    return path


def save_current_frame(parent, viewer, source, frame, with_annotations: bool = True) -> str | None:
    """Ask for a file name and save the current frame. Returns the path or None."""
    n = frame.frame_no if isinstance(frame, Frame) else int(frame)
    default = os.path.join(source.directory, f"{clip_basename(source)}_{n}.png")
    filters = ["PNG 이미지 (*.png)", "JPEG 이미지 (*.jpg *.jpeg)", "TIFF 16비트 (*.tif *.tiff)",
               "OpenEXR · 원본 값 (*.exr)"]
    path, chosen = QFileDialog.getSaveFileName(_dialog_parent(parent), "현재 프레임 저장", default, ";;".join(filters))
    if not path:
        return None
    if os.path.splitext(path)[1].lower() not in _STILL_FORMATS:
        ext = {0: ".png", 1: ".jpg", 2: ".tif", 3: ".exr"}.get(filters.index(chosen) if chosen in filters else 0)
        path += ext
    try:
        return write_still(path, viewer, source, frame, with_annotations)
    except Exception as exc:
        log.exception("save frame failed")
        QMessageBox.warning(_dialog_parent(parent), "프레임 저장", f"저장하지 못했습니다.\n\n{exc}")
        return None


# ====================================================================== PDF

_MM = 150.0 / 25.4          # device pixels per millimetre at 150 dpi

_INK = "#16181D"
_INK2 = "#565C66"
_INK3 = "#8C929C"
_RULE = "#E4E6EA"
_SOFT = "#F5F6F8"
_PANEL = "#0F1014"

_SHAPE_NAMES = {"pen": "펜", "line": "선", "arrow": "화살표", "rect": "사각형", "ellipse": "원", "text": "텍스트",
                "eraser": "지우개"}


def _pfont(size: float, weight=QFont.Normal, mono: bool = False) -> QFont:
    f = mono_font(size, weight) if mono else ui_font(size, weight)
    if not mono:
        f.setFamilies([UI_FONT, "Pretendard Variable", "Noto Sans CJK KR", "Malgun Gothic", "Apple SD Gothic Neo",
                       "Segoe UI"])
    else:
        f.setFamilies([MONO_FONT, "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"])
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


class _PdfReport:
    def __init__(self, path: str, viewer, source):
        self.path = path
        self.viewer = viewer
        self.source = source
        self.frames = source.annotations.annotated_frames()
        self.now = datetime.datetime.now()
        self.accent = QColor(PAL.accent)

    # -- layout constants (device px)

    def _setup(self, writer: QPdfWriter) -> None:
        self.device = writer
        self.W = writer.width()
        self.H = writer.height()
        self.M = 14 * _MM
        self.footer_h = 10 * _MM

    def _text(self, p: QPainter, rect: QRectF, text: str, font: QFont, color: str,
              flags=Qt.AlignLeft | Qt.AlignVCenter) -> None:
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(rect, int(flags), text)

    def _fm(self, font: QFont) -> QFontMetricsF:
        # Measure at the PDF's resolution, not the screen's.
        return QFontMetricsF(font, self.device)

    def _elide(self, text: str, font: QFont, width: float) -> str:
        return self._fm(font).elidedText(text, Qt.ElideRight, width)

    def _footer(self, p: QPainter, page: int, pages: int) -> None:
        y = self.H - self.M * 0.5 - self.footer_h
        p.setPen(QPen(QColor(_RULE), 1.2))
        p.drawLine(QPointF(self.M, y), QPointF(self.W - self.M, y))
        f = _pfont(7.5)
        left = f"{APP_NAME}  ·  {clip_basename(self.source)}  ·  {self.now:%Y-%m-%d %H:%M}"
        self._text(p, QRectF(self.M, y, self.W * 0.7, self.footer_h), left, f, _INK3)
        self._text(p, QRectF(self.W - self.M - 60 * _MM, y, 60 * _MM, self.footer_h), f"{page} / {pages}",
                   _pfont(7.5, QFont.DemiBold), _INK2, Qt.AlignRight | Qt.AlignVCenter)

    def _brand(self, p: QPainter, x: float, y: float) -> float:
        size = 9 * _MM
        drew = False
        try:
            from cocseq import icons

            pm = icons.logo_pixmap(64, 2.0)
            if not pm.isNull():
                p.drawPixmap(QRectF(x, y, size, size), pm, QRectF(0, 0, pm.width(), pm.height()))
                drew = True
        except Exception:
            pass
        if not drew:
            p.setPen(Qt.NoPen)
            p.setBrush(self.accent)
            p.drawRoundedRect(QRectF(x, y, size, size), size * 0.25, size * 0.25)
        self._text(p, QRectF(x + size + 3 * _MM, y, 120 * _MM, size), APP_NAME, _pfont(11, QFont.Bold), _INK)
        return y + size

    # -- pages

    def _cover_rows_per_page(self, first: bool) -> int:
        top = (84 if first else 40) * _MM
        bottom = self.H - self.M - self.footer_h - 4 * _MM
        return max(1, int((bottom - top - 9 * _MM) // (8.5 * _MM)))

    def _plan(self) -> list[list[int]]:
        pages: list[list[int]] = []
        rest = list(self.frames)
        first = True
        while True:
            n = self._cover_rows_per_page(first)
            pages.append(rest[:n])
            rest = rest[n:]
            first = False
            if not rest:
                break
        return pages

    def _cover(self, p: QPainter, rows: list[int], first: bool, page: int, pages: int) -> None:
        src = self.source
        M, W = self.M, self.W
        p.fillRect(QRectF(0, 0, W, self.H), QColor("#FFFFFF"))
        p.fillRect(QRectF(0, 0, W, 2.2 * _MM), self.accent)
        y = self._brand(p, M, M)
        if first:
            y += 9 * _MM
            self._text(p, QRectF(M, y, W - 2 * M, 6 * _MM), "리뷰 노트", _pfont(9, QFont.Bold), PAL.accent)
            y += 6 * _MM
            title = self._elide(clip_basename(src), _pfont(26, QFont.Bold), W - 2 * M)
            self._text(p, QRectF(M, y, W - 2 * M, 14 * _MM), title, _pfont(26, QFont.Bold), _INK)
            y += 14 * _MM
            self._text(p, QRectF(M, y, W - 2 * M, 6 * _MM),
                       self._elide(src.display_path, _pfont(8, mono=True), W - 2 * M), _pfont(8, mono=True), _INK3)
            y += 11 * _MM
            w_, h_ = src.resolution
            lo, hi = src.first, src.last
            meta = [
                ("생성 일시", f"{self.now:%Y-%m-%d  %H:%M}"),
                ("프레임 범위", f"{lo} – {hi}  ({hi - lo + 1}프레임)"),
                ("해상도 · FPS", f"{w_} × {h_}  ·  {fps_label(src.fps)} fps"),
                ("주석 프레임", f"{len(self.frames)}개"),
            ]
            cw = (W - 2 * M) / len(meta)
            box = QRectF(M, y, W - 2 * M, 17 * _MM)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(_SOFT))
            p.drawRoundedRect(box, 2.5 * _MM, 2.5 * _MM)
            for i, (k, v) in enumerate(meta):
                x = M + i * cw + 6 * _MM
                self._text(p, QRectF(x, y + 3 * _MM, cw - 8 * _MM, 5 * _MM), k, _pfont(7.5, QFont.DemiBold), _INK3)
                self._text(p, QRectF(x, y + 8.5 * _MM, cw - 8 * _MM, 6 * _MM), v, _pfont(10.5, QFont.DemiBold), _INK)
                if i:
                    p.setPen(QPen(QColor(_RULE), 1.2))
                    p.drawLine(QPointF(M + i * cw, y + 3.5 * _MM), QPointF(M + i * cw, y + 13.5 * _MM))
                    p.setPen(Qt.NoPen)
            y = 84 * _MM
        else:
            y = self.M + 12 * _MM
            self._text(p, QRectF(M, y, W - 2 * M, 8 * _MM), "주석 목록 (계속)", _pfont(13, QFont.Bold), _INK)
            y = 40 * _MM
        # table
        cols = [("프레임", 24 * _MM), ("타임코드", 34 * _MM), ("그림", 38 * _MM), ("노트", 0)]
        x = M
        hdr_h = 7 * _MM
        p.setPen(QPen(QColor(_INK), 1.6))
        p.drawLine(QPointF(M, y + hdr_h), QPointF(W - M, y + hdr_h))
        xs = []
        for name, cw in cols:
            xs.append(x)
            self._text(p, QRectF(x, y, (cw or 60 * _MM), hdr_h), name, _pfont(7.5, QFont.Bold), _INK2)
            x += cw
        y += hdr_h
        row_h = 8.5 * _MM
        note_w = W - M - xs[3]
        store = src.annotations
        for f in rows:
            shapes = store.frames.get(f, [])
            note = " · ".join(l.strip() for l in store.notes.get(f, "").splitlines() if l.strip())
            self._text(p, QRectF(xs[0], y, cols[0][1], row_h), str(f), _pfont(9.5, QFont.DemiBold, mono=True), _INK)
            self._text(p, QRectF(xs[1], y, cols[1][1], row_h), frames_to_timecode(f - src.first, src.fps),
                       _pfont(8.5, mono=True), _INK2)
            # colour dots for the drawings
            dx = self._dots(p, xs[2], y + row_h / 2, shapes, 6)
            label = f"{len(shapes)}개" if shapes else "—"
            self._text(p, QRectF(dx + (1 * _MM if shapes else 0), y, 20 * _MM, row_h), label, _pfont(8.5), _INK2)
            nf = _pfont(9.5)
            self._text(p, QRectF(xs[3], y, note_w, row_h), self._elide(note or "—", nf, note_w), nf,
                       _INK if note else _INK3)
            y += row_h
            p.setPen(QPen(QColor(_RULE), 1.0))
            p.drawLine(QPointF(M, y), QPointF(W - M, y))
        self._footer(p, page, pages)

    def _dots(self, p: QPainter, x: float, cy: float, shapes, limit: int) -> float:
        """Colour dots for drawings (outlined so white strokes show on paper). Returns the next x."""
        d = 2.6 * _MM
        for sh in shapes[:limit]:
            p.setPen(QPen(QColor(0, 0, 0, 50), 1.0))
            p.setBrush(QColor(sh.color))
            p.drawEllipse(QRectF(x, cy - d / 2, d, d))
            x += d + 1.0 * _MM
        return x

    def _frame_image(self, reader, f: int, target_w: int, target_h: int) -> QImage | None:
        src = self.source
        frame = reader.read(f, src.layer)
        if frame is None or frame.missing or frame.pixels is None:
            return None
        ex = Exporter()
        img = ex._display_pixels(src, self.viewer, frame)
        dw = frame.data_window if frame.data_window[2] else (0, 0, img.shape[1], img.shape[0])
        disp = frame.display_window if frame.display_window[2] else dw
        canvas = _place(img, (dw[0], dw[1], img.shape[1], img.shape[0]), disp)
        canvas = np.array(_resize(canvas, target_w, target_h), np.float32)
        over = _overlay(src.annotations.visible(f, 0), disp, target_w, target_h)
        if over is not None:
            _composite(canvas, over)
        return _qimage_rgb(canvas)

    def _frame_page(self, p: QPainter, reader, f: int, page: int, pages: int, index: int) -> None:
        src = self.source
        M, W, H = self.M, self.W, self.H
        p.fillRect(QRectF(0, 0, W, H), QColor("#FFFFFF"))
        p.fillRect(QRectF(0, 0, W, 2.2 * _MM), self.accent)
        # header
        y = M
        self._text(p, QRectF(M, y, W * 0.6, 5 * _MM),
                   self._elide(f"{clip_basename(src)}  ·  주석 {index} / {len(self.frames)}", _pfont(8.5), W * 0.6),
                   _pfont(8.5), _INK3)
        y += 5.5 * _MM
        tf = _pfont(20, QFont.Bold)
        title = f"프레임 {f}"
        self._text(p, QRectF(M, y, W * 0.5, 11 * _MM), title, tf, _INK)
        tw = self._fm(tf).horizontalAdvance(title)
        tc = frames_to_timecode(f - src.first, src.fps)
        chip_f = _pfont(9, QFont.DemiBold, mono=True)
        cw = self._fm(chip_f).horizontalAdvance(tc) + 6 * _MM
        chip = QRectF(M + tw + 5 * _MM, y + 2.2 * _MM, cw, 6.6 * _MM)
        p.setPen(Qt.NoPen)
        c = QColor(self.accent)
        c.setAlphaF(0.12)
        p.setBrush(c)
        p.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
        self._text(p, chip, tc, chip_f, PAL.accent, Qt.AlignCenter)
        y += 15 * _MM
        # image panel (left) and notes column (right)
        bottom = H - M * 0.5 - self.footer_h - 5 * _MM
        col_w = 78 * _MM
        gap = 8 * _MM
        pad = 3 * _MM
        avail = QRectF(M, y, W - 2 * M - col_w - gap, bottom - y)
        disp, par = _source_windows(src)
        aspect = (disp[2] * par) / max(1, disp[3])
        inner = avail.adjusted(pad, pad, -pad, -pad)
        if inner.width() / inner.height() > aspect:
            ih = inner.height()
            iw = ih * aspect
        else:
            iw = inner.width()
            ih = iw / aspect
        rect = QRectF(avail.left() + (avail.width() - iw) / 2, avail.top() + pad, iw, ih)
        panel = rect.adjusted(-pad, -pad, pad, pad)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(_PANEL))
        p.drawRoundedRect(panel, 2.5 * _MM, 2.5 * _MM)
        tw_px = int(max(64, min(2400, round(iw * 1.5))))
        th_px = int(max(36, round(tw_px / aspect)))
        img = None
        try:
            img = self._frame_image(reader, f, tw_px, th_px)
        except Exception:
            log.exception("pdf frame %d", f)
        if img is not None:
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(rect, 1.2 * _MM, 1.2 * _MM)
            p.setClipPath(clip)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(rect, img)
            p.restore()
        else:
            p.setPen(QPen(QColor("#3A3F4A"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, 1.2 * _MM, 1.2 * _MM)
            self._text(p, rect, "프레임을 읽을 수 없습니다", _pfont(11, QFont.DemiBold), "#8C929C", Qt.AlignCenter)
        # notes column
        x = panel.right() + gap
        cy = y
        self._text(p, QRectF(x, cy, col_w, 5 * _MM), "노트", _pfont(8, QFont.Bold), PAL.accent)
        cy += 7 * _MM
        note = src.annotations.notes.get(f, "").strip()
        shapes = src.annotations.frames.get(f, [])
        info_h = 36 * _MM
        flags = int(Qt.TextWordWrap | Qt.AlignTop | Qt.AlignLeft)
        # Keep the info block level with the bottom of the picture unless the note needs the room.
        need = self._fm(_pfont(11.0)).boundingRect(QRectF(x, cy, col_w, 10000), flags, note).height() if note \
            else 6 * _MM
        col_bottom = panel.bottom() if cy + need + info_h + 4 * _MM <= panel.bottom() else bottom
        box = QRectF(x, cy, col_w, col_bottom - cy - info_h)
        if note:
            size = 11.0
            while True:
                nf = _pfont(size)
                br = self._fm(nf).boundingRect(box, flags, note)
                if br.height() <= box.height() or size <= 7.0:
                    break
                size -= 0.5
            p.setFont(nf)
            p.setPen(QColor(_INK))
            p.drawText(box, flags, note)
        else:
            self._text(p, QRectF(x, cy, col_w, 6 * _MM), "노트 없음", _pfont(10), _INK3, Qt.AlignLeft | Qt.AlignTop)
        # info block
        iy = col_bottom - info_h
        p.setPen(QPen(QColor(_RULE), 1.2))
        p.drawLine(QPointF(x, iy), QPointF(x + col_w, iy))
        iy += 3 * _MM
        counts: dict[str, int] = {}
        for sh in shapes:
            counts[sh.kind] = counts.get(sh.kind, 0) + 1
        drawn = "  ·  ".join(f"{_SHAPE_NAMES.get(k, k)} {v}" for k, v in counts.items()) or "없음"
        pos = f"{f - src.first + 1} / {src.length}"
        rows = [("그림", drawn), ("타임코드", tc), ("클립 내 위치", pos), ("해상도", f"{disp[2]} × {disp[3]}")]
        kw = 26 * _MM
        for k, v in rows:
            vx = x + kw
            self._text(p, QRectF(x, iy, kw, 7 * _MM), k, _pfont(7.5, QFont.DemiBold), _INK3)
            if k == "그림" and shapes:
                vx = self._dots(p, vx, iy + 3.5 * _MM, shapes, 5) + 1.2 * _MM
            vf = _pfont(8.5, mono=k in ("타임코드", "클립 내 위치", "해상도"))
            self._text(p, QRectF(vx, iy, x + col_w - vx, 7 * _MM), self._elide(v, vf, x + col_w - vx), vf, _INK)
            iy += 7.5 * _MM
        self._footer(p, page, pages)

    def write(self, progress: Callable[[int, int], bool] | None = None) -> str:
        progress = progress or (lambda _d, _t: True)
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        writer = QPdfWriter(self.path)
        writer.setResolution(150)
        writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape, QMarginsF(0, 0, 0, 0)))
        writer.setTitle(f"{clip_basename(self.source)} — 리뷰 노트")
        writer.setCreator(APP_NAME)
        if hasattr(writer, "setAuthor"):
            try:
                writer.setAuthor(APP_NAME)
            except Exception:
                pass
        self._setup(writer)
        cover = self._plan()
        pages = len(cover) + len(self.frames)
        total = len(self.frames)
        p = QPainter()
        if not p.begin(writer):
            raise ExportError(f"PDF 파일을 만들 수 없습니다: {self.path}")
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        reader = self.source.reader.clone()
        page = 0
        cancelled = False
        try:
            if progress(0, total) is False:
                raise ExportCancelled()
            for i, rows in enumerate(cover):
                if page:
                    writer.newPage()
                page += 1
                self._cover(p, rows, i == 0, page, pages)
            for i, f in enumerate(self.frames):
                writer.newPage()
                page += 1
                self._frame_page(p, reader, f, page, pages, i + 1)
                if progress(i + 1, total) is False:
                    raise ExportCancelled()
        except ExportCancelled:
            cancelled = True
            raise
        finally:
            p.end()
            try:
                reader.close()
            except Exception:
                pass
            if self.viewer is not None:
                self.viewer.release_export()
            if cancelled:
                try:
                    os.remove(self.path)
                except OSError:
                    pass
        return self.path


def write_annotations_pdf(path: str, viewer, source, progress: Callable[[int, int], bool] | None = None) -> str:
    """Dialog-free PDF report writer (cover + one page per annotated frame)."""
    return _PdfReport(path, viewer, source).write(progress)


def export_annotations_pdf(parent, viewer, source) -> str | None:
    """Ask for a file name and write a PDF of every annotated frame with its notes."""
    top = _dialog_parent(parent)
    if source is None or not source.annotations.annotated_frames():
        QMessageBox.information(top, "주석 PDF", "주석이나 노트가 있는 프레임이 없습니다.")
        return None
    default = os.path.join(source.directory, f"{clip_basename(source)}_review.pdf")
    path, _ = QFileDialog.getSaveFileName(top, "주석을 PDF로 내보내기", default, "PDF 문서 (*.pdf)")
    if not path:
        return None
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    n = len(source.annotations.annotated_frames())
    prog = _Progress(parent, "주석 PDF", os.path.basename(path), n, verb="PDF 만드는 중", icon_name="pdf")
    try:
        out = write_annotations_pdf(path, viewer, source, prog.update)
    except ExportCancelled:
        prog.close()
        return None
    except Exception as exc:
        prog.close()
        log.exception("pdf export failed")
        QMessageBox.critical(top, "주석 PDF", f"PDF를 만들지 못했습니다.\n\n{exc}")
        return None
    prog.close()
    size = os.path.getsize(out) if os.path.exists(out) else 0
    _ResultDialog(top, "PDF 저장 완료", f"주석 프레임 {n}개  ·  {human_bytes(size)}", out).exec()
    return out
