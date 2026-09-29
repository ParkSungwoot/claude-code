"""Audio: decode a track into memory with PyAV and play it with PortAudio (sounddevice)."""

from __future__ import annotations

import logging
import threading

import numpy as np
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

RATE = 48000

try:
    import sounddevice as sd
except Exception as exc:  # pragma: no cover - PortAudio missing
    sd = None
    log.warning("sounddevice unavailable: %s", exc)


class AudioTrack:
    def __init__(self, samples: np.ndarray, rate: int = RATE, start: float = 0.0, path: str = ""):
        self.samples = samples          # (n, 2) int16
        self.rate = rate
        self.start = start              # seconds of audio before (-) / after (+) the first video frame
        self.path = path

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.rate)

    def slice(self, t0: float, t1: float) -> np.ndarray:
        """float32 stereo samples between two track times (zero padded outside)."""
        a = int(round(t0 * self.rate))
        b = int(round(t1 * self.rate))
        n = max(0, b - a)
        out = np.zeros((n, 2), np.float32)
        lo, hi = max(a, 0), min(b, len(self.samples))
        if hi > lo:
            out[lo - a: hi - a] = self.samples[lo:hi].astype(np.float32) / 32768.0
        return out

    def peaks(self, buckets: int) -> np.ndarray:
        """Max absolute amplitude per bucket, for drawing a waveform."""
        if len(self.samples) == 0 or buckets <= 0:
            return np.zeros(max(buckets, 0), np.float32)
        mono = np.abs(self.samples.astype(np.int32)).max(axis=1)
        edges = np.linspace(0, len(mono), buckets + 1).astype(np.int64)
        out = np.zeros(buckets, np.float32)
        for i in range(buckets):
            seg = mono[edges[i]:edges[i + 1]]
            if len(seg):
                out[i] = seg.max() / 32768.0
        return out


def decode_audio(path: str, rate: int = RATE, max_seconds: float = 4 * 3600) -> AudioTrack | None:
    """Decode the first audio stream of a file to 16-bit stereo."""
    try:
        import av
    except Exception:
        return None
    try:
        container = av.open(path, metadata_errors="ignore")
    except Exception as exc:
        log.warning("audio open %s: %s", path, exc)
        return None
    try:
        if not container.streams.audio:
            return None
        stream = container.streams.audio[0]
        stream.thread_type = "AUTO"
        start = 0.0
        if stream.start_time is not None and stream.time_base:
            start = float(stream.start_time * stream.time_base)
        if container.streams.video:
            vs = container.streams.video[0]
            if vs.start_time is not None and vs.time_base:
                start -= float(vs.start_time * vs.time_base)
        resampler = av.AudioResampler(format="s16", layout="stereo", rate=rate)
        chunks = []
        total = 0
        limit = int(max_seconds * rate)

        def add(frames):
            nonlocal total
            for rf in frames:
                arr = rf.to_ndarray().reshape(-1, 2)
                chunks.append(arr)
                total += len(arr)

        for frame in container.decode(stream):
            add(resampler.resample(frame))
            if total > limit:
                break
        add(resampler.resample(None))
        if not chunks:
            return None
        samples = np.ascontiguousarray(np.concatenate(chunks).astype(np.int16))
        return AudioTrack(samples, rate, start, path)
    except Exception as exc:
        log.warning("audio decode %s: %s", path, exc)
        return None
    finally:
        container.close()


class AudioLoader(QObject):
    """Decodes tracks on background threads."""

    loaded = Signal(int, object)     # source id, AudioTrack or None

    def load(self, source_id: int, path: str) -> None:
        def run():
            track = decode_audio(path)
            self.loaded.emit(source_id, track)

        threading.Thread(target=run, name="audio-decode", daemon=True).start()


def output_devices() -> list[str]:
    if sd is None:
        return []
    try:
        return [d["name"] for d in sd.query_devices() if d.get("max_output_channels", 0) > 0]
    except Exception:
        return []


class AudioEngine(QObject):
    """Plays one track from a position; reports the playback clock."""

    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.volume = 0.8
        self.muted = False
        self.device: str = ""
        self._track: AudioTrack | None = None
        self._pos = 0                  # next sample index to output (may be negative: leading silence)
        self._stream = None
        self._lock = threading.Lock()
        self._latency = 0.0
        self._playing = False
        self._scrub_left = 0

    @property
    def available(self) -> bool:
        return sd is not None

    @property
    def playing(self) -> bool:
        return self._playing

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, v))

    def set_muted(self, m: bool) -> None:
        self.muted = m

    def set_device(self, name: str) -> None:
        if name != self.device:
            self.device = name
            self._close_stream()

    def _device_index(self):
        if not self.device or sd is None:
            return None
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["name"] == self.device and d.get("max_output_channels", 0) > 0:
                    return i
        except Exception:
            pass
        return None

    def _ensure_stream(self) -> bool:
        if sd is None:
            return False
        if self._stream is not None:
            return True
        try:
            self._stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                                           device=self._device_index(), callback=self._callback,
                                           latency="low", blocksize=0)
            self._stream.start()
            lat = self._stream.latency
            self._latency = float(lat[1] if isinstance(lat, (tuple, list)) else lat)
            return True
        except Exception as exc:
            log.warning("audio output failed: %s", exc)
            self._stream = None
            self.error.emit(f"오디오 출력 장치를 열 수 없습니다: {exc}")
            return False

    def _close_stream(self) -> None:
        s = self._stream
        self._stream = None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            track = self._track
            if track is None or not (self._playing or self._scrub_left > 0):
                outdata.fill(0)
                return
            a = self._pos
            b = a + frames
            out = np.zeros((frames, 2), np.float32)
            lo, hi = max(a, 0), min(b, len(track.samples))
            if hi > lo:
                out[lo - a: hi - a] = track.samples[lo:hi] * (1.0 / 32768.0)
            if self._scrub_left > 0 and not self._playing:
                keep = min(frames, self._scrub_left)
                out[keep:] = 0
                self._scrub_left -= keep
            self._pos = b
            gain = 0.0 if self.muted else self.volume
            outdata[:] = out * gain

    def play(self, track: AudioTrack, track_time: float) -> bool:
        """Start playing `track` at `track_time` seconds (track time, 0 = first sample)."""
        if track is None or not self._ensure_stream():
            return False
        with self._lock:
            self._track = track
            self._pos = int(round(track_time * track.rate))
            self._playing = True
            self._scrub_left = 0
        return True

    def stop(self) -> None:
        with self._lock:
            self._playing = False
            self._scrub_left = 0

    def scrub(self, track: AudioTrack, track_time: float, seconds: float) -> None:
        if track is None or not self._ensure_stream():
            return
        with self._lock:
            self._track = track
            self._pos = int(round(track_time * track.rate))
            self._scrub_left = int(seconds * track.rate)

    def position(self) -> float | None:
        """Track time currently heard, or None when not playing."""
        with self._lock:
            if not self._playing or self._track is None:
                return None
            return self._pos / float(self._track.rate) - self._latency

    def shutdown(self) -> None:
        self.stop()
        self._close_stream()
