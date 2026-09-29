"""A clip in the playlist: its reader, frame range, layer, color space and annotations."""

from __future__ import annotations

import itertools
import os

from cocseq.media.frame import Layer, MediaInfo
from cocseq.media.readers import MovieReader, SequenceReader
from cocseq.media.seqscan import Sequence, is_movie, scan_from_file

_ids = itertools.count(1)


class MediaSource:
    def __init__(self, kind: str, path: str, seq: Sequence | None = None, movie_start: int = 1,
                 default_fps: float = 24.0):
        self.id = next(_ids)
        self.kind = kind
        self.path = path
        self.seq = seq
        self.movie_start = movie_start
        self.default_fps = default_fps
        if kind == "movie":
            self.reader = MovieReader(path, movie_start)
        else:
            self.reader = SequenceReader(seq)
        self.info: MediaInfo = self.reader.probe()
        self.layers: list[Layer] = self.info.layers or [Layer("RGBA", 0, ["R", "G", "B"], [0, 1, 2])]
        self.layer: Layer = self.layers[0]
        self.fps_override: float = 0.0
        self.in_point: int | None = None
        self.out_point: int | None = None
        self.current: int = self.first
        self.colorspace: str = ""
        self.audio_path: str = path if (kind == "movie" and self.info.has_audio) else ""
        self.audio_offset: int = 0            # frames; positive delays the audio
        self.audio = None                     # AudioTrack once decoded
        from cocseq.annotations import AnnotationStore

        self.annotations = AnnotationStore()
        self.error = self.info.error

    # ---------------------------------------------------------------- open

    @classmethod
    def open(cls, path: str, detect_sequence: bool = True, movie_start: int = 1,
             default_fps: float = 24.0) -> "MediaSource":
        if is_movie(path):
            return cls("movie", os.path.abspath(path), movie_start=movie_start, default_fps=default_fps)
        seq = scan_from_file(path, detect=detect_sequence)
        return cls("sequence", seq.path_for(seq.first), seq, default_fps=default_fps)

    def reload(self) -> None:
        """Rescan the sequence on disk (new frames from a render) and reprobe."""
        if self.kind == "sequence" and self.seq and not self.seq.single_file:
            fresh = scan_from_file(self.seq.path_for(self.seq.first) if os.path.exists(
                self.seq.path_for(self.seq.first)) else self.path)
            self.seq.frames = fresh.frames
            self.reader = SequenceReader(self.seq)
        elif self.kind == "movie":
            self.reader.close()
            self.reader = MovieReader(self.path, self.movie_start)
        layer_name = self.layer.name
        self.info = self.reader.probe()
        self.layers = self.info.layers or self.layers
        self.layer = next((l for l in self.layers if l.name == layer_name), self.layers[0])
        self.error = self.info.error

    # ---------------------------------------------------------------- range

    @property
    def first(self) -> int:
        return self.info.first

    @property
    def last(self) -> int:
        return max(self.info.first, self.info.last)

    @property
    def fps(self) -> float:
        return self.fps_override or self.info.fps or self.default_fps

    @property
    def range(self) -> tuple[int, int]:
        lo = self.in_point if self.in_point is not None else self.first
        hi = self.out_point if self.out_point is not None else self.last
        lo = max(self.first, min(lo, self.last))
        hi = max(lo, min(hi, self.last))
        return lo, hi

    @property
    def length(self) -> int:
        return self.last - self.first + 1

    @property
    def missing(self) -> list[int]:
        return self.seq.missing if self.seq else []

    @property
    def name(self) -> str:
        if self.kind == "movie":
            return os.path.basename(self.path)
        return self.seq.display_name if self.seq else os.path.basename(self.path)

    @property
    def display_path(self) -> str:
        if self.kind == "movie":
            return self.path
        return self.seq.pattern_path if self.seq else self.path

    @property
    def directory(self) -> str:
        return os.path.dirname(self.path)

    @property
    def resolution(self) -> tuple[int, int]:
        return self.info.width, self.info.height

    def bytes_per_frame(self) -> int:
        return self.info.bytes_per_frame(self.layer)

    def frame_path(self, frame: int) -> str:
        if self.kind == "movie" or not self.seq:
            return self.path
        return self.seq.path_for(frame)

    def set_layer(self, name: str) -> bool:
        for l in self.layers:
            if l.name == name or l.key == name:
                self.layer = l
                return True
        return False

    def is_float(self) -> bool:
        if self.layer.name not in ("RGBA", "A") and self.info.is_float:
            return True
        return self.info.is_float

    def close(self) -> None:
        try:
            self.reader.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- session

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "layer": self.layer.name,
            "fps_override": self.fps_override,
            "in": self.in_point,
            "out": self.out_point,
            "current": self.current,
            "colorspace": self.colorspace,
            "audio_path": self.audio_path,
            "audio_offset": self.audio_offset,
            "annotations": self.annotations.to_dict(),
        }

    def apply_dict(self, d: dict) -> None:
        self.set_layer(d.get("layer", self.layer.name))
        self.fps_override = float(d.get("fps_override") or 0.0)
        self.in_point = d.get("in")
        self.out_point = d.get("out")
        self.current = int(d.get("current", self.first))
        self.colorspace = d.get("colorspace", "") or ""
        self.audio_path = d.get("audio_path", self.audio_path) or ""
        self.audio_offset = int(d.get("audio_offset", 0))
        self.annotations.load_dict(d.get("annotations") or {})
