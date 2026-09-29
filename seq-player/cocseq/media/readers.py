"""Frame readers: OpenImageIO for still images and sequences, PyAV (FFmpeg) for movies."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from fractions import Fraction

import numpy as np

from cocseq.media.frame import Frame, Layer, MediaInfo
from cocseq.media.seqscan import Sequence

log = logging.getLogger(__name__)

try:
    import OpenImageIO as oiio
except Exception as exc:  # pragma: no cover - reported in the UI
    oiio = None
    log.error("OpenImageIO unavailable: %s", exc)

try:
    import av
except Exception as exc:  # pragma: no cover
    av = None
    log.error("PyAV unavailable: %s", exc)


# ------------------------------------------------------------------ layers

_RGBA_ALIASES = {
    "R": "R", "RED": "R", "G": "G", "GREEN": "G", "B": "B", "BLUE": "B", "A": "A", "ALPHA": "A",
}


def _order_channels(chans: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    """Pick up to four channels of a group in display order."""
    by_upper = {}
    for item in chans:
        by_upper.setdefault(item[0].upper(), item)
    for keys in (("R", "G", "B", "A"), ("RED", "GREEN", "BLUE", "ALPHA"), ("X", "Y", "Z", "W"), ("U", "V", "W")):
        picked = [by_upper[k] for k in keys if k in by_upper]
        if len(picked) >= 2 or (len(picked) == 1 and len(chans) == 1):
            if keys[0] in ("R", "RED") and len(picked) < 3 and len(chans) > len(picked):
                continue
            return picked
    return chans[:4]


def detect_layers(parts: list[tuple[str, list[str]]]) -> list[Layer]:
    """parts: [(part_name, channel_names)] for every subimage."""
    layers: list[Layer] = []
    multi = len(parts) > 1
    for part_idx, (part_name, names) in enumerate(parts):
        groups: "OrderedDict[str, list[tuple[str, int, str]]]" = OrderedDict()
        for i, ch in enumerate(names):
            layer, short = ch.rsplit(".", 1) if "." in ch else ("", ch)
            groups.setdefault(layer, []).append((short, i, ch))
        for lname, chans in groups.items():
            if lname == "":
                rgba = [c for c in chans if c[0].upper() in _RGBA_ALIASES]
                rest = [c for c in chans if c[0].upper() not in _RGBA_ALIASES]
                subgroups = []
                if rgba:
                    subgroups.append(("RGBA" if len(rgba) > 1 or rgba[0][0].upper() != "A" else "A", rgba))
                for c in rest:
                    subgroups.append((c[0], [c]))
            else:
                subgroups = [(lname, chans)]
            for name, group in subgroups:
                ordered = _order_channels(group)
                if multi:
                    pname = part_name or f"part{part_idx}"
                    if name in ("RGBA",) and pname.lower() not in ("rgba", "rgb"):
                        name = pname
                    elif name != pname and not name.startswith(pname + "."):
                        name = f"{pname}.{name}" if name != "RGBA" else pname
                layers.append(Layer(name, part_idx, [c[2] for c in ordered], [c[1] for c in ordered]))
    # Put the main RGBA layer first.
    layers.sort(key=lambda l: (0 if l.name == "RGBA" else 1))
    return layers or [Layer("RGBA", 0, ["R", "G", "B"], [0, 1, 2])]


# ------------------------------------------------------------------ images

_READ_FORMATS = {"uint8": "uint8", "int8": "uint8", "uint16": "uint16", "int16": "uint16", "half": "half"}


def _attr(spec, name, default=None):
    try:
        v = spec.getattribute(name)
    except Exception:
        return default
    return default if v is None else v


def _fps_from_spec(spec) -> float:
    v = _attr(spec, "FramesPerSecond")
    try:
        if isinstance(v, (tuple, list)) and len(v) == 2 and v[1]:
            return float(v[0]) / float(v[1])
        if isinstance(v, (int, float)):
            return float(v)
    except Exception:
        pass
    return 0.0


def _meta_from_spec(spec) -> dict:
    meta = {}
    for a in spec.extra_attribs:
        try:
            value = a.value
            if isinstance(value, (bytes, bytearray)):
                value = f"<{len(value)} bytes>"
            text = str(value)
        except Exception:
            text = "?"
        meta[a.name] = text[:600]
    return meta


class SequenceReader:
    """Reads frames of an image sequence (or a single image). Safe to use from many threads."""

    kind = "sequence"
    thread_safe = True

    def __init__(self, seq: Sequence):
        self.seq = seq

    def clone(self) -> "SequenceReader":
        return SequenceReader(self.seq)

    def close(self) -> None:
        pass

    def probe(self) -> MediaInfo:
        info = MediaInfo("sequence", self.seq.pattern_path, first=self.seq.first, last=self.seq.last)
        if oiio is None:
            info.error = "OpenImageIO를 불러오지 못했습니다."
            return info
        path = next((self.seq.path_for(f) for f in self.seq.frames if os.path.exists(self.seq.path_for(f))), None)
        if path is None:
            info.error = "파일을 찾을 수 없습니다."
            return info
        inp = oiio.ImageInput.open(path)
        if not inp:
            info.error = oiio.geterror() or "이미지를 열 수 없습니다."
            return info
        try:
            parts = []
            specs = []
            idx = 0
            while True:
                spec = inp.spec()
                specs.append(spec)
                parts.append((spec.get_string_attribute("name", ""), list(spec.channelnames)))
                idx += 1
                if idx > 256 or not inp.seek_subimage(idx, 0):
                    break
            spec = specs[0]
            info.subimages = len(specs)
            info.width, info.height = spec.full_width or spec.width, spec.full_height or spec.height
            info.data_window = (spec.x, spec.y, spec.width, spec.height)
            info.display_window = (spec.full_x, spec.full_y, info.width, info.height)
            info.par = float(_attr(spec, "PixelAspectRatio", 1.0) or 1.0)
            info.fps = _fps_from_spec(spec)
            info.channels = [c for _n, names in parts for c in names]
            info.layers = detect_layers(parts)
            fmt = str(spec.format)
            info.pixel_type = fmt
            info.is_float = fmt in ("half", "float", "double")
            bits = int(_attr(spec, "oiio:BitsPerSample", 0) or 0)
            info.bit_depth = bits or {"uint8": 8, "uint16": 16, "half": 16, "float": 32}.get(fmt, 32)
            info.compression = spec.get_string_attribute("compression", "")
            info.file_colorspace = spec.get_string_attribute("oiio:ColorSpace", "")
            info.timecode = spec.get_string_attribute("smpte:TimeCode", "")
            info.metadata = _meta_from_spec(spec)
            info.metadata["format"] = inp.format_name()
            if spec.deep:
                info.error = "딥(deep) 이미지는 지원하지 않습니다."
            try:
                info.file_size = os.path.getsize(path)
            except OSError:
                pass
        finally:
            inp.close()
        return info

    def read(self, frame_no: int, layer: Layer) -> Frame:
        if oiio is None:
            return Frame.missing_frame(frame_no, "OpenImageIO unavailable")
        path = self.seq.path_for(frame_no)
        if not os.path.exists(path):
            return Frame.missing_frame(frame_no)
        inp = oiio.ImageInput.open(path)
        if not inp:
            return Frame.missing_frame(frame_no, oiio.geterror() or "open failed")
        try:
            part = layer.part
            if part and not inp.seek_subimage(part, 0):
                return Frame.missing_frame(frame_no, f"no subimage {part}")
            spec = inp.spec()
            nch = spec.nchannels
            indices = [i for i in layer.indices if i < nch] or list(range(min(nch, 4)))
            lo, hi = min(indices), max(indices) + 1
            chfmts = [str(t) for t in spec.channelformats] if len(spec.channelformats) else []
            if chfmts:
                sel = {chfmts[i] for i in indices if i < len(chfmts)}
                fmt = "half" if sel == {"half"} else ("float" if sel - {"uint8", "uint16"} else "uint16")
            else:
                fmt = _READ_FORMATS.get(str(spec.format), "float")
            data = inp.read_image(part, 0, lo, hi, fmt)
            if data is None:
                return Frame.missing_frame(frame_no, oiio.geterror() or "read failed")
            if data.ndim == 2:
                data = data[:, :, None]
            local = [i - lo for i in indices]
            if local != list(range(hi - lo)):
                data = data[:, :, local]
            data = np.ascontiguousarray(data)
            w, h = spec.width, spec.height
            dw = (spec.x, spec.y, w, h)
            disp = (spec.full_x, spec.full_y, spec.full_width or w, spec.full_height or h)
            par = float(_attr(spec, "PixelAspectRatio", 1.0) or 1.0)
            names = [spec.channelnames[i] for i in indices]
            return Frame(data, frame_no, dw, disp, par, names)
        except Exception as exc:
            log.warning("read %s: %s", path, exc)
            return Frame.missing_frame(frame_no, str(exc))
        finally:
            inp.close()


def read_image_file(path: str, layer: Layer | None = None) -> Frame:
    """Convenience for reading one image outside of a sequence."""
    seq = Sequence(os.path.dirname(path), "", os.path.splitext(path)[1], 0, [1], single_file=path)
    reader = SequenceReader(seq)
    if layer is None:
        info = reader.probe()
        layer = info.layers[0] if info.layers else Layer("RGBA", 0, ["R", "G", "B", "A"], [0, 1, 2, 3])
    return reader.read(1, layer)


# ------------------------------------------------------------------ movies

MOVIE_LAYER = Layer("RGBA", 0, ["R", "G", "B"], [0, 1, 2])

_ALPHA_FORMATS = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16", "pal8", "rgb32", "bgr32")


def _colorspace_name(frame, height: int) -> str:
    cs = int(getattr(frame, "colorspace", 2) or 2)
    if cs == 1:
        return "ITU709"
    if cs in (5, 6):
        return "ITU601"
    if cs in (9, 10):
        return "BT2020"
    if cs == 7:
        return "SMPTE240M"
    return "ITU709" if height >= 720 else "ITU601"


class MovieReader:
    """Decodes a movie file. Not thread safe: callers hold `lock` while reading."""

    kind = "movie"
    thread_safe = False
    MAX_COLLECT = 48

    def __init__(self, path: str, start_frame: int = 1):
        self.path = path
        self.start_frame = start_frame
        self.lock = threading.Lock()
        self._container = None
        self._stream = None
        self._iter = None
        self._last_index: int | None = None
        self._first_index = 0
        self._fps = 24.0
        self._time_base = Fraction(1, 24)
        self._start_pts = 0
        self._out_format = "rgb24"
        self._is_yuv = True
        self._nframes = 0
        self._height = 0
        self._layer = MOVIE_LAYER

    def clone(self) -> "MovieReader":
        return MovieReader(self.path, self.start_frame)

    # -- open / probe

    def _open(self) -> None:
        if self._container is not None:
            return
        if av is None:
            raise RuntimeError("PyAV unavailable")
        self._container = av.open(self.path, metadata_errors="ignore")
        if not self._container.streams.video:
            raise RuntimeError("비디오 스트림이 없습니다.")
        vs = self._container.streams.video[0]
        vs.thread_type = "AUTO"
        self._stream = vs
        rate = vs.average_rate or vs.guessed_rate or vs.base_rate or Fraction(24, 1)
        self._fps = float(rate) if rate else 24.0
        self._time_base = vs.time_base or Fraction(1, 90000)
        self._start_pts = vs.start_time if vs.start_time is not None else 0
        pix = vs.codec_context.pix_fmt or "yuv420p"
        self._height = vs.codec_context.height
        bits = 8
        try:
            fmt = av.VideoFormat(pix)
            bits = max((c.bits for c in fmt.components), default=8)
            self._is_yuv = not fmt.is_rgb and not pix.startswith(("gray", "pal", "ya"))
        except Exception:
            self._is_yuv = pix.startswith("yuv")
        alpha = pix.startswith(_ALPHA_FORMATS)
        if pix.startswith("gray"):
            self._out_format = "gray16le" if bits > 8 else "gray"
            self._layer = Layer("Y", 0, ["Y"], [0])
        elif alpha:
            self._out_format = "rgba64le" if bits > 8 else "rgba"
            self._layer = Layer("RGBA", 0, ["R", "G", "B", "A"], [0, 1, 2, 3])
        else:
            self._out_format = "rgb48le" if bits > 8 else "rgb24"
            self._layer = MOVIE_LAYER
        self._bits = bits
        n = vs.frames or 0
        if n <= 0:
            dur = None
            if vs.duration is not None:
                dur = float(vs.duration * self._time_base)
            elif self._container.duration:
                dur = self._container.duration / 1_000_000
            n = int(round(dur * self._fps)) if dur else 1
        self._nframes = max(1, n)
        # The index of the first decoded frame becomes 0.
        try:
            first = next(self._container.decode(vs))
            self._first_index = self._raw_index(first)
        except Exception:
            self._first_index = 0
        self._container.seek(self._start_pts, stream=vs, backward=True, any_frame=False)
        self._iter = None
        self._last_index = None

    def probe(self) -> MediaInfo:
        info = MediaInfo("movie", self.path)
        try:
            with self.lock:
                self._open()
        except Exception as exc:
            info.error = f"동영상을 열 수 없습니다: {exc}"
            return info
        c, vs = self._container, self._stream
        cc = vs.codec_context
        info.width, info.height = cc.width, cc.height
        info.data_window = (0, 0, cc.width, cc.height)
        info.display_window = (0, 0, cc.width, cc.height)
        sar = vs.sample_aspect_ratio
        info.par = float(sar) if sar and float(sar) > 0 else 1.0
        info.fps = self._fps
        info.first = self.start_frame
        info.last = self.start_frame + self._nframes - 1
        info.layers = [self._layer]
        info.channels = list(self._layer.channels)
        info.pixel_type = "uint16" if self._bits > 8 else "uint8"
        info.bit_depth = self._bits
        info.codec = f"{cc.codec.long_name or cc.name}" + (f" ({vs.profile})" if vs.profile else "")
        info.pix_fmt = cc.pix_fmt or ""
        info.duration_s = self._nframes / self._fps if self._fps else 0.0
        info.bitrate = int(c.bit_rate or 0)
        meta = {}
        for k, v in list(c.metadata.items()) + list(vs.metadata.items()):
            meta[k] = str(v)[:600]
        info.metadata = meta
        info.timecode = vs.metadata.get("timecode") or c.metadata.get("timecode") or ""
        if c.streams.audio:
            a = c.streams.audio[0]
            info.has_audio = True
            layout = getattr(a.layout, "name", "") if getattr(a, "layout", None) else ""
            info.audio_desc = f"{a.codec_context.name} {a.rate} Hz {layout}".strip()
        try:
            info.file_size = os.path.getsize(self.path)
        except OSError:
            pass
        return info

    def close(self) -> None:
        with self.lock:
            if self._container is not None:
                try:
                    self._container.close()
                except Exception:
                    pass
            self._container = None
            self._iter = None

    # -- decode

    def _raw_index(self, vframe) -> int:
        pts = vframe.pts if vframe.pts is not None else vframe.dts
        if pts is None:
            return (self._last_index or -1) + 1 + self._first_index
        t = (pts - self._start_pts) * self._time_base
        return int(round(float(t) * self._fps))

    def _convert(self, vframe) -> np.ndarray:
        kwargs = {}
        if self._is_yuv:
            kwargs["src_colorspace"] = _colorspace_name(vframe, self._height)
            rng = int(getattr(vframe, "color_range", 0) or 0)
            kwargs["src_color_range"] = "JPEG" if rng == 2 else "MPEG"
            kwargs["dst_color_range"] = "JPEG"
        try:
            arr = vframe.to_ndarray(format=self._out_format, **kwargs)
        except TypeError:
            arr = vframe.reformat(format=self._out_format, **kwargs).to_ndarray()
        if arr.ndim == 2:
            arr = arr[:, :, None]
        return np.ascontiguousarray(arr)

    def _make_frame(self, arr: np.ndarray, index: int) -> Frame:
        h, w = arr.shape[:2]
        par = 1.0
        if self._stream is not None and self._stream.sample_aspect_ratio:
            par = float(self._stream.sample_aspect_ratio) or 1.0
        return Frame(arr, self.start_frame + index, (0, 0, w, h), (0, 0, w, h), par, list(self._layer.channels))

    def read_many(self, frame_no: int) -> dict[int, Frame]:
        """Decode `frame_no` and return it with any neighbours decoded on the way.

        The caller must hold `self.lock`.
        """
        self._open()
        index = frame_no - self.start_frame
        out: dict[int, Frame] = {}
        if index < 0 or index >= self._nframes:
            return {frame_no: Frame.missing_frame(frame_no)}
        vs = self._stream
        need_seek = self._iter is None or self._last_index is None or not (0 < index - self._last_index <= 16)
        if need_seek:
            t = Fraction(index + self._first_index, 1) / Fraction(self._fps).limit_denominator(100000)
            ts = self._start_pts + int(t / self._time_base)
            try:
                self._container.seek(ts, stream=vs, backward=True, any_frame=False)
            except Exception:
                self._container.seek(self._start_pts, stream=vs, backward=True, any_frame=False)
            self._iter = self._container.decode(vs)
            self._last_index = None
        got_target = False
        try:
            for vf in self._iter:
                i = self._raw_index(vf) - self._first_index
                self._last_index = i
                if i < index - self.MAX_COLLECT:
                    continue
                if i > index and not got_target and not out:
                    # Seek landed past the target (bad index); show what we have.
                    out[frame_no] = self._make_frame(self._convert(vf), index)
                    got_target = True
                    break
                out[self.start_frame + i] = self._make_frame(self._convert(vf), i)
                if i >= index:
                    got_target = True
                    break
        except (StopIteration, EOFError):
            pass
        except Exception as exc:
            if av is not None and isinstance(exc, av.error.FFmpegError):
                log.warning("decode %s frame %d: %s", self.path, frame_no, exc)
            else:
                raise
        if not got_target:
            self._iter = None
            self._last_index = None
            if frame_no not in out:
                # Past the real end of the stream: hold the last decoded frame if any.
                if out:
                    last = max(out)
                    f = out[last]
                    out[frame_no] = Frame(f.pixels, frame_no, f.data_window, f.display_window, f.par, f.channel_names)
                else:
                    out[frame_no] = Frame.missing_frame(frame_no)
        return out

    def read(self, frame_no: int, layer: Layer | None = None) -> Frame:
        with self.lock:
            return self.read_many(frame_no)[frame_no]


def make_reader(kind: str, target, start_frame: int = 1):
    if kind == "movie":
        return MovieReader(target, start_frame)
    return SequenceReader(target)
