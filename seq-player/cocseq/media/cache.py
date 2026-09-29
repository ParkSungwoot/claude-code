"""RAM frame cache and background readers that keep it filled around the playhead."""

from __future__ import annotations

import logging
import math
import threading
from typing import Callable, Iterable

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from cocseq.media.frame import Frame, Layer

log = logging.getLogger(__name__)

Key = tuple  # (source_id, layer_key, frame_no)
INF = float("inf")


class FrameCache:
    """Frames kept in memory up to a byte budget. Thread safe."""

    def __init__(self, budget_bytes: int):
        self.budget = int(budget_bytes)
        self._lock = threading.Lock()
        self._frames: dict[Key, Frame] = {}
        self._index: dict[tuple, set[int]] = {}
        self._used = 0

    @property
    def used(self) -> int:
        return self._used

    def set_budget(self, budget_bytes: int) -> None:
        with self._lock:
            self.budget = int(budget_bytes)
            if self._used > self.budget:
                self._evict_locked(self._used - self.budget, lambda k: INF, -1)

    def get(self, key: Key) -> Frame | None:
        with self._lock:
            return self._frames.get(key)

    def contains(self, key: Key) -> bool:
        return key in self._frames

    def frames_for(self, source_id: int, layer_key: str) -> set[int]:
        with self._lock:
            return set(self._index.get((source_id, layer_key), ()))

    def _remove_locked(self, key: Key) -> None:
        f = self._frames.pop(key, None)
        if f is not None:
            self._used -= f.nbytes
            idx = self._index.get(key[:2])
            if idx is not None:
                idx.discard(key[2])

    def _evict_locked(self, need: int, prio_of: Callable[[Key], float], my_prio: float) -> int:
        victims = sorted(self._frames.keys(), key=prio_of, reverse=True)
        for k in victims:
            if need <= 0:
                break
            if prio_of(k) <= my_prio:
                break
            nbytes = self._frames[k].nbytes
            self._remove_locked(k)
            need -= nbytes
        return need

    def can_admit(self, nbytes: int, prio: float, prio_of: Callable[[Key], float]) -> bool:
        with self._lock:
            deficit = self._used + nbytes - self.budget
            if deficit <= 0:
                return True
            for k, f in self._frames.items():
                if prio_of(k) > prio:
                    deficit -= f.nbytes
                    if deficit <= 0:
                        return True
            return False

    def put(self, key: Key, frame: Frame, prio_of: Callable[[Key], float] = lambda k: INF,
            prio: float = 0) -> bool:
        with self._lock:
            if key in self._frames:
                self._remove_locked(key)
            need = self._used + frame.nbytes - self.budget
            if need > 0:
                need = self._evict_locked(need, prio_of, prio)
                if need > 0:
                    return False
            self._frames[key] = frame
            self._used += frame.nbytes
            self._index.setdefault(key[:2], set()).add(key[2])
            return True

    def drop_source(self, source_id: int) -> None:
        with self._lock:
            for k in [k for k in self._frames if k[0] == source_id]:
                self._remove_locked(k)

    def drop_frame(self, key: Key) -> None:
        with self._lock:
            self._remove_locked(key)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._index.clear()
            self._used = 0


def window_frames(center: int, first: int, last: int, direction: int, loop_mode: str,
                  count: int, behind_ratio: float = 0.15) -> list[int]:
    """Frames to keep cached, most important first: the playhead, then ahead of it, then behind."""
    if last < first:
        return []
    span = last - first + 1
    count = max(1, min(count, span))
    center = min(max(center, first), last)
    d = -1 if direction < 0 else 1
    n_behind = int(count * behind_ratio) if count < span else 0
    n_ahead = count - 1 - n_behind

    def step_seq(start: int, step: int, n: int) -> list[int]:
        """The next n distinct frames when playing from `start` (bounces and wraps like playback)."""
        out: list[int] = []
        seen = {start}
        f = start
        s = step
        for _ in range(4 * span + 4):
            if len(out) >= n:
                break
            f += s
            if f > last or f < first:
                if loop_mode == "loop":
                    f = first if f > last else last
                elif loop_mode == "pingpong":
                    s = -s
                    f += 2 * s
                    if f > last or f < first:
                        break
                else:
                    break
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    ahead = step_seq(center, d, n_ahead)
    behind = step_seq(center, -d, n_behind) if n_behind else []
    order = [center] + ahead[:6] + behind[:2] + ahead[6:] + behind[2:]
    seen = set()
    result = []
    for f in order:
        if f not in seen:
            seen.add(f)
            result.append(f)
    if count >= span and len(result) < span:
        for f in range(first, last + 1):
            if f not in seen:
                result.append(f)
    return result


class Prefetcher(QObject):
    """Worker threads that read the frames of the wanted list into the cache, in order."""

    frameLoaded = Signal(int, str, int)   # source id, layer key, frame number

    def __init__(self, cache: FrameCache, threads: int = 4):
        super().__init__()
        self.cache = cache
        self._cond = threading.Condition()
        self._wanted: list[tuple] = []     # (source, layer, frame_no)
        self._prio: dict[Key, int] = {}
        self._inflight: set[Key] = set()
        self._busy: set[int] = set()       # movie sources being decoded
        self._stop = False
        self._paused = False
        self._threads: list[threading.Thread] = []
        self.set_threads(threads)

    def set_threads(self, n: int) -> None:
        n = max(1, int(n))
        while len(self._threads) < n:
            t = threading.Thread(target=self._worker, name=f"reader-{len(self._threads)}", daemon=True)
            self._threads.append(t)
            t.start()

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def set_paused(self, paused: bool) -> None:
        with self._cond:
            self._paused = paused
            self._cond.notify_all()

    def prio_of(self, key: Key) -> float:
        return self._prio.get(key, INF)

    def set_wanted(self, items: Iterable[tuple]) -> None:
        items = list(items)
        prio = {}
        for i, (src, layer, f) in enumerate(items):
            prio.setdefault((src.id, layer.key if src.kind != "movie" else "movie", f), i)
        with self._cond:
            self._wanted = items
            self._prio = prio
            self._cond.notify_all()

    @staticmethod
    def key_for(src, layer: Layer, frame_no: int) -> Key:
        return (src.id, layer.key if src.kind != "movie" else "movie", frame_no)

    def _pick(self):
        for i, (src, layer, f) in enumerate(self._wanted):
            key = self.key_for(src, layer, f)
            if key in self._inflight or self.cache.contains(key):
                continue
            if src.kind == "movie" and src.id in self._busy:
                continue
            nbytes = src.bytes_per_frame()
            if not self.cache.can_admit(nbytes, i, self.prio_of):
                return None
            return src, layer, f, key, i
        return None

    def _worker(self) -> None:
        while True:
            with self._cond:
                job = None
                while not self._stop:
                    if not self._paused:
                        job = self._pick()
                        if job is not None:
                            break
                    self._cond.wait(0.25)
                if self._stop:
                    return
                src, layer, f, key, prio = job
                self._inflight.add(key)
                if src.kind == "movie":
                    self._busy.add(src.id)
            loaded: dict[int, Frame] = {}
            try:
                reader = src.reader
                if src.kind == "movie":
                    with reader.lock:
                        loaded = reader.read_many(f)
                else:
                    loaded = {f: reader.read(f, layer)}
            except Exception as exc:
                log.exception("reading frame %s of %s", f, src.name)
                loaded = {f: Frame.missing_frame(f, str(exc))}
            finally:
                with self._cond:
                    self._inflight.discard(key)
                    self._busy.discard(src.id)
            for fno, frame in loaded.items():
                k = self.key_for(src, layer, fno)
                p = self.prio_of(k)
                if fno != f and p == INF:
                    continue  # decoded on the way but not wanted
                if self.cache.put(k, frame, self.prio_of, p if p != INF else prio):
                    self.frameLoaded.emit(src.id, k[1], fno)
            with self._cond:
                self._cond.notify_all()


# ------------------------------------------------------------------ thumbnails


def to_preview_rgba8(frame: Frame, display_fn: Callable[[np.ndarray], np.ndarray] | None,
                     max_w: int) -> QImage | None:
    """Small 8-bit preview image of a frame. `display_fn` maps float RGB(A) to display values."""
    if frame is None or frame.pixels is None:
        return None
    px = frame.pixels
    h, w = px.shape[:2]
    step = max(1, int(math.floor(w / max(1, max_w * 2))))
    small = px[::step, ::step]
    f = Frame(np.ascontiguousarray(small), frame.frame_no, (0, 0, small.shape[1], small.shape[0]))
    rgb = f.normalized()
    c = rgb.shape[2]
    if c == 1:
        rgb = np.repeat(rgb, 3, axis=2)
    elif c == 2:
        rgb = np.repeat(rgb[:, :, :1], 3, axis=2)
    else:
        rgb = rgb[:, :, :3]
    rgb = np.ascontiguousarray(rgb, np.float32)
    if display_fn is not None:
        try:
            rgb = display_fn(rgb)
        except Exception:
            log.debug("preview color transform failed", exc_info=True)
    out = (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)
    out = np.ascontiguousarray(out)
    hh, ww = out.shape[:2]
    img = QImage(out.data, ww, hh, ww * 3, QImage.Format_RGB888).copy()
    par = frame.par or 1.0
    target_w = min(max_w, int(ww * par))
    target_h = max(1, int(round(target_w * hh / (ww * par))))
    from PySide6.QtCore import Qt

    return img.scaled(target_w, target_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


class ThumbnailService(QObject):
    """Makes small preview images on one background thread, newest request first."""

    ready = Signal(int, int, int, QImage)   # source id, frame, width, image

    def __init__(self, cache: FrameCache | None = None):
        super().__init__()
        self.cache = cache
        self._cond = threading.Condition()
        self._jobs: list[tuple] = []
        self._readers: dict[int, object] = {}
        self._display_fns: dict[int, Callable] = {}
        self._done: dict[tuple, QImage] = {}
        self._order: list[tuple] = []
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="thumbnails", daemon=True)
        self._thread.start()

    def set_display_fn(self, source_id: int, fn: Callable | None) -> None:
        self._display_fns[source_id] = fn
        with self._cond:
            for k in [k for k in self._done if k[0] == source_id]:
                self._done.pop(k, None)

    def cached(self, source_id: int, frame: int, width: int) -> QImage | None:
        return self._done.get((source_id, frame, width))

    def request(self, src, frame: int, width: int) -> QImage | None:
        key = (src.id, frame, width)
        img = self._done.get(key)
        if img is not None:
            return img
        with self._cond:
            self._jobs = [j for j in self._jobs if j[1] != key][-24:]
            self._jobs.append((src, key))
            self._cond.notify()
        return None

    def forget(self, source_id: int) -> None:
        with self._cond:
            r = self._readers.pop(source_id, None)
            for k in [k for k in self._done if k[0] == source_id]:
                self._done.pop(k, None)
        if r is not None:
            try:
                r.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._jobs and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                src, key = self._jobs.pop()   # newest first
            try:
                frame = None
                if self.cache is not None:
                    frame = self.cache.get(Prefetcher.key_for(src, src.layer, key[1]))
                if frame is None or frame.pixels is None:
                    reader = self._readers.get(src.id)
                    if reader is None:
                        reader = src.reader.clone()
                        self._readers[src.id] = reader
                    frame = reader.read(key[1], src.layer)
                img = to_preview_rgba8(frame, self._display_fns.get(src.id), key[2])
                if img is None:
                    continue
                with self._cond:
                    self._done[key] = img
                    self._order.append(key)
                    if len(self._order) > 400:
                        old = self._order.pop(0)
                        self._done.pop(old, None)
                self.ready.emit(key[0], key[1], key[2], img)
            except Exception:
                log.debug("thumbnail failed", exc_info=True)
