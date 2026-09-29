"""In-memory frame and media description types."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Layer:
    """A group of channels shown together (EXR AOV, or the plain RGBA of any image)."""

    name: str                 # "RGBA" for the main layer, "diffuse", "part.specular", ...
    part: int                 # OIIO subimage (EXR part) index
    channels: list[str]       # channel names in display order (at most 4)
    indices: list[int]        # indices of those channels in the part's channel list

    @property
    def key(self) -> str:
        return f"{self.part}:{self.name}"

    @property
    def label(self) -> str:
        short = [c.split(".")[-1] for c in self.channels]
        chans = "".join(short) if all(len(c) == 1 for c in short) else ",".join(short)
        return self.name if chans == self.name else f"{self.name} · {chans}"


@dataclass
class Frame:
    pixels: np.ndarray | None           # (h, w, c) with c in 1..4; uint8, uint16, float16 or float32
    frame_no: int
    data_window: tuple[int, int, int, int] = (0, 0, 0, 0)     # x, y, w, h (y grows downwards)
    display_window: tuple[int, int, int, int] = (0, 0, 0, 0)
    par: float = 1.0
    channel_names: list[str] = field(default_factory=list)
    missing: bool = False
    error: str = ""

    @property
    def nbytes(self) -> int:
        return int(self.pixels.nbytes) if self.pixels is not None else 64

    @property
    def width(self) -> int:
        return self.data_window[2]

    @property
    def height(self) -> int:
        return self.data_window[3]

    @property
    def nchannels(self) -> int:
        return 0 if self.pixels is None else self.pixels.shape[2]

    @staticmethod
    def missing_frame(frame_no: int, error: str = "") -> "Frame":
        return Frame(None, frame_no, missing=True, error=error)

    def normalized(self) -> np.ndarray:
        """Pixels as float32 in their natural range (integers scaled to 0..1)."""
        px = self.pixels
        if px is None:
            return np.zeros((1, 1, 4), np.float32)
        if px.dtype == np.uint8:
            return px.astype(np.float32) / 255.0
        if px.dtype == np.uint16:
            return px.astype(np.float32) / 65535.0
        return px.astype(np.float32, copy=False)

    def value_at(self, x: int, y: int) -> list[float] | None:
        """Raw values at an image (display window) pixel, or None outside the data window."""
        if self.pixels is None:
            return None
        dx, dy, w, h = self.data_window
        ix, iy = x - dx, y - dy
        if not (0 <= ix < w and 0 <= iy < h):
            return None
        v = self.pixels[iy, ix]
        if self.pixels.dtype == np.uint8:
            return [float(c) / 255.0 for c in v]
        if self.pixels.dtype == np.uint16:
            return [float(c) / 65535.0 for c in v]
        return [float(c) for c in v]

    def region(self, x0: int, y0: int, x1: int, y1: int) -> np.ndarray | None:
        """Float pixels inside an image-space rectangle (clipped to the data window)."""
        if self.pixels is None:
            return None
        dx, dy, w, h = self.data_window
        ax0, ay0 = max(0, x0 - dx), max(0, y0 - dy)
        ax1, ay1 = min(w, x1 - dx), min(h, y1 - dy)
        if ax1 <= ax0 or ay1 <= ay0:
            return None
        sub = self.pixels[ay0:ay1, ax0:ax1]
        if sub.dtype == np.uint8:
            return sub.astype(np.float32) / 255.0
        if sub.dtype == np.uint16:
            return sub.astype(np.float32) / 65535.0
        return sub.astype(np.float32)


@dataclass
class MediaInfo:
    kind: str                                   # "sequence" | "movie"
    path: str
    width: int = 0
    height: int = 0
    data_window: tuple[int, int, int, int] = (0, 0, 0, 0)
    display_window: tuple[int, int, int, int] = (0, 0, 0, 0)
    par: float = 1.0
    fps: float = 0.0                            # 0 = unknown (use default)
    first: int = 1
    last: int = 1
    layers: list[Layer] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    pixel_type: str = ""                        # uint8, uint16, half, float, ...
    bit_depth: int = 8
    is_float: bool = False
    compression: str = ""
    codec: str = ""
    pix_fmt: str = ""
    file_colorspace: str = ""
    timecode: str = ""
    duration_s: float = 0.0
    bitrate: int = 0
    has_audio: bool = False
    audio_desc: str = ""
    file_size: int = 0
    metadata: dict = field(default_factory=dict)
    subimages: int = 1
    error: str = ""

    def bytes_per_frame(self, layer: Layer | None = None) -> int:
        w, h = self.data_window[2] or self.width, self.data_window[3] or self.height
        nch = len(layer.channels) if layer else min(4, max(1, len(self.channels) or 3))
        bpc = {"uint8": 1, "uint16": 2, "half": 2}.get(self.pixel_type, 4)
        return max(1, w * h * nch * bpc)
