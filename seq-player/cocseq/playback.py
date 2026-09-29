"""Playback clock: advances the current frame in time, with loop modes and in/out range."""

from __future__ import annotations

import collections
import math
import time
from typing import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal

LOOP_MODES = ("loop", "once", "pingpong")


class Playback(QObject):
    frameChanged = Signal(int)
    stateChanged = Signal(int)          # 0 stopped, 1 forward, -1 backward
    fpsChanged = Signal(float)
    loopModeChanged = Signal(str)
    rangeChanged = Signal()
    measuredFps = Signal(float)
    reachedEnd = Signal(int)            # direction; emitted when "once" playback hits the end
    wrapped = Signal(int)               # playback jumped to the other end (loop) - restart audio

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = 1
        self.first = 1
        self.last = 1
        self.in_point: int | None = None
        self.out_point: int | None = None
        self.fps = 24.0
        self.direction = 0
        self.loop_mode = "loop"
        self.play_all_frames = True
        self.is_ready: Callable[[int], bool] = lambda f: True
        # When set, returns seconds of audio heard since the last start (or None).
        self.audio_elapsed: Callable[[], float | None] | None = None
        self.on_start: Callable[[int, int], None] | None = None   # (frame, direction) when a run begins
        self.on_stop: Callable[[], None] | None = None

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(3)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._anchor = 1
        self._steps = 0
        self._next_time = 0.0
        self._shown: collections.deque = collections.deque(maxlen=240)
        self._fps_report = QTimer(self)
        self._fps_report.setInterval(500)
        self._fps_report.timeout.connect(self._report_fps)

    # ---------------------------------------------------------------- range

    @property
    def playing(self) -> bool:
        return self.direction != 0

    def range(self) -> tuple[int, int]:
        lo = self.in_point if self.in_point is not None else self.first
        hi = self.out_point if self.out_point is not None else self.last
        lo = max(self.first, min(lo, self.last))
        hi = max(lo, min(hi, self.last))
        return lo, hi

    def set_clip(self, first: int, last: int, frame: int, in_point=None, out_point=None, fps: float = 24.0) -> None:
        self.first, self.last = int(first), int(max(first, last))
        self.in_point, self.out_point = in_point, out_point
        self.fps = float(fps) if fps > 0 else 24.0
        self.fpsChanged.emit(self.fps)
        self.rangeChanged.emit()
        self.frame = max(self.first, min(int(frame), self.last))
        self._restart_clock()
        self.frameChanged.emit(self.frame)

    def set_in(self, frame: int | None) -> None:
        if frame is not None and self.out_point is not None and frame > self.out_point:
            self.out_point = None
        self.in_point = frame
        self.rangeChanged.emit()

    def set_out(self, frame: int | None) -> None:
        if frame is not None and self.in_point is not None and frame < self.in_point:
            self.in_point = None
        self.out_point = frame
        self.rangeChanged.emit()

    def set_fps(self, fps: float) -> None:
        fps = max(0.1, min(float(fps), 1000.0))
        if abs(fps - self.fps) > 1e-6:
            self.fps = fps
            self._restart_clock()
            self.fpsChanged.emit(fps)

    def set_loop_mode(self, mode: str) -> None:
        if mode in LOOP_MODES and mode != self.loop_mode:
            self.loop_mode = mode
            self.loopModeChanged.emit(mode)

    def cycle_loop_mode(self) -> str:
        i = (LOOP_MODES.index(self.loop_mode) + 1) % len(LOOP_MODES)
        self.set_loop_mode(LOOP_MODES[i])
        return self.loop_mode

    # ---------------------------------------------------------------- transport

    def seek(self, frame: int) -> None:
        frame = max(self.first, min(int(frame), self.last))
        if frame != self.frame:
            self.frame = frame
            self.frameChanged.emit(frame)
        if self.playing:
            self._restart_clock()

    def step(self, n: int) -> None:
        if self.playing:
            self.stop()
        lo, hi = self.range()
        f = self.frame + n
        if self.first <= self.frame <= self.last and (lo <= self.frame <= hi):
            if f > hi:
                f = lo if self.loop_mode == "loop" and n == 1 else hi
            elif f < lo:
                f = hi if self.loop_mode == "loop" and n == -1 else lo
        self.seek(f)

    def goto_start(self) -> None:
        self.seek(self.range()[0])

    def goto_end(self) -> None:
        self.seek(self.range()[1])

    def play(self, direction: int = 1) -> None:
        direction = 1 if direction >= 0 else -1
        lo, hi = self.range()
        if not (lo <= self.frame <= hi):
            self.frame = lo if direction > 0 else hi
            self.frameChanged.emit(self.frame)
        elif self.loop_mode == "once" and ((direction > 0 and self.frame >= hi) or (direction < 0 and self.frame <= lo)):
            self.frame = lo if direction > 0 else hi
            self.frameChanged.emit(self.frame)
        was = self.direction
        self.direction = direction
        self._restart_clock()
        self._shown.clear()
        if not self._timer.isActive():
            self._timer.start()
            self._fps_report.start()
        if was != direction:
            self.stateChanged.emit(direction)

    def stop(self) -> None:
        if self.direction == 0:
            return
        self.direction = 0
        self._timer.stop()
        self._fps_report.stop()
        if self.on_stop:
            self.on_stop()
        self.stateChanged.emit(0)
        self.measuredFps.emit(0.0)

    def toggle(self, direction: int = 1) -> None:
        if self.playing:
            self.stop()
        else:
            self.play(direction)

    # ---------------------------------------------------------------- clock

    def _restart_clock(self) -> None:
        self._clock.restart()
        self._anchor = self.frame
        self._steps = 0
        self._next_time = 1.0 / self.fps
        if self.playing and self.on_start:
            self.on_start(self.frame, self.direction)

    def _next_frame(self, f: int) -> tuple[int | None, str]:
        """Frame after f in the playing direction and what happened: "", "wrap", "bounce" or "end"."""
        lo, hi = self.range()
        d = self.direction
        nf = f + d
        if lo <= nf <= hi:
            return nf, ""
        if self.loop_mode == "loop":
            return (lo if d > 0 else hi), "wrap"
        if self.loop_mode == "pingpong":
            return max(lo, min(hi, f - d)), "bounce"
        return None, "end"

    def _commit(self, event: str) -> None:
        if event == "bounce":
            self.direction = -self.direction
            self.stateChanged.emit(self.direction)

    def _elapsed(self) -> float:
        if self.audio_elapsed is not None:
            t = self.audio_elapsed()
            if t is not None:
                return max(0.0, t)
        return self._clock.nsecsElapsed() / 1e9

    def _show(self, f: int) -> None:
        self.frame = f
        self._shown.append(time.perf_counter_ns())
        self.frameChanged.emit(f)

    def _tick(self) -> None:
        if not self.playing:
            return
        audio = self.audio_elapsed() if self.audio_elapsed is not None else None
        if not self.play_all_frames or audio is not None:
            target = int(math.floor(self._elapsed() * self.fps + 1e-6))
            if target <= self._steps:
                return
            f = self.frame
            event = ""
            for _ in range(min(target - self._steps, 10000)):
                nf, event = self._next_frame(f)
                if nf is None:
                    self._show(f)
                    self.stop()
                    self.reachedEnd.emit(1)
                    return
                f = nf
                self._commit(event)
                if event:
                    break
            self._steps = target
            self._show(f)
            if event:
                self._restart_clock()
                self.wrapped.emit(self.direction)
            return
        # Play every frame: wait for the next frame to be ready.
        now = self._clock.nsecsElapsed() / 1e9
        if now < self._next_time:
            return
        nf, event = self._next_frame(self.frame)
        if nf is None:
            self.stop()
            self.reachedEnd.emit(1)
            return
        if not self.is_ready(nf):
            return
        self._commit(event)
        self._show(nf)
        period = 1.0 / self.fps
        self._next_time += period
        if now - self._next_time > period * 2:
            self._next_time = now + period
        if event:
            self.wrapped.emit(self.direction)

    def _report_fps(self) -> None:
        if len(self._shown) < 2:
            return
        now = time.perf_counter_ns()
        recent = [t for t in self._shown if now - t < 1_000_000_000]
        if len(recent) >= 2:
            span = (recent[-1] - recent[0]) / 1e9
            if span > 0:
                self.measuredFps.emit((len(recent) - 1) / span)
