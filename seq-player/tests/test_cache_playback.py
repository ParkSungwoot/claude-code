import time

import numpy as np

from cocseq.media.cache import FrameCache, Prefetcher, window_frames
from cocseq.media.frame import Frame
from cocseq.playback import Playback


def fr(n, nbytes=100):
    return Frame(np.zeros(nbytes, np.uint8).reshape(1, -1, 1), n)


def test_window_loop():
    w = window_frames(8, 1, 10, 1, "loop", 6, 0.0)
    assert w == [8, 9, 10, 1, 2, 3]


def test_window_once_stops():
    w = window_frames(8, 1, 10, 1, "once", 6, 0.0)
    assert w == [8, 9, 10]


def test_window_pingpong_and_backwards():
    assert window_frames(9, 1, 10, 1, "pingpong", 5, 0.0) == [9, 10, 8, 7, 6]
    assert window_frames(3, 1, 10, -1, "loop", 4, 0.0) == [3, 2, 1, 10]


def test_window_behind_and_full_range():
    w = window_frames(5, 1, 100, 1, "loop", 20, 0.25)
    assert w[0] == 5 and 4 in w and 3 in w
    full = window_frames(5, 1, 10, 1, "once", 50, 0.2)
    assert sorted(full) == list(range(1, 11))


def test_cache_budget_and_priority():
    c = FrameCache(1000)
    prio = {("s", "l", i): i for i in range(20)}
    pf = lambda k: prio.get(k, float("inf"))  # noqa: E731
    for i in range(10):
        assert c.put(("s", "l", i), fr(i, 100), pf, pf(("s", "l", i)))
    assert c.used == 1000
    # A more important frame evicts the least important one.
    prio[("s", "l", 50)] = -1
    assert c.put(("s", "l", 50), fr(50), pf, -1)
    assert not c.contains(("s", "l", 9))
    # A less important frame cannot push out more important ones.
    assert not c.put(("s", "l", 15), fr(15), pf, 15)
    assert c.frames_for("s", "l") == set(range(9)) | {50}
    c.drop_source("s")
    assert c.used == 0


class FakeReader:
    def __init__(self):
        self.reads = []

    def read(self, f, layer):
        self.reads.append(f)
        return Frame(np.zeros((2, 2, 3), np.uint8), f, (0, 0, 2, 2), (0, 0, 2, 2))


class FakeSource:
    kind = "sequence"
    id = 77

    def __init__(self):
        from cocseq.media.frame import Layer

        self.reader = FakeReader()
        self.layer = Layer("RGBA", 0, ["R", "G", "B"], [0, 1, 2])

    def bytes_per_frame(self):
        return 12


def test_prefetcher_fills_in_order(qapp):
    cache = FrameCache(12 * 5)
    pf = Prefetcher(cache, threads=1)
    src = FakeSource()
    pf.set_wanted([(src, src.layer, f) for f in (5, 6, 7, 8, 9, 10, 11)])
    deadline = time.time() + 5
    while len(cache.frames_for(src.id, src.layer.key)) < 5 and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    time.sleep(0.2)
    assert cache.frames_for(src.id, src.layer.key) == {5, 6, 7, 8, 9}
    assert src.reader.reads[:5] == [5, 6, 7, 8, 9]
    pf.shutdown()


def test_playback_step_and_range(qapp):
    pb = Playback()
    seen = []
    pb.frameChanged.connect(seen.append)
    pb.set_clip(1, 10, 1)
    pb.step(1)
    assert pb.frame == 2
    pb.set_in(3)
    pb.set_out(5)
    assert pb.range() == (3, 5)
    pb.seek(5)
    pb.step(1)                    # loop wraps inside in/out
    assert pb.frame == 3
    pb.set_loop_mode("once")
    pb.seek(5)
    pb.step(1)
    assert pb.frame == 5
    pb.goto_start()
    assert pb.frame == 3
    pb.set_out(2)                 # out before in clears in
    assert pb.in_point is None and pb.range() == (1, 2)


def test_playback_plays_every_frame_and_stops_once(qapp):
    pb = Playback()
    pb.set_clip(1, 6, 1, fps=200)
    pb.set_loop_mode("once")
    shown = []
    pb.frameChanged.connect(shown.append)
    ended = []
    pb.reachedEnd.connect(ended.append)
    ready = {1, 2, 3}
    pb.is_ready = lambda f: f in ready
    pb.play(1)
    deadline = time.time() + 2
    while time.time() < deadline and pb.frame < 3:
        qapp.processEvents()
    for _ in range(30):
        qapp.processEvents()
        time.sleep(0.002)
    assert pb.frame == 3 and pb.playing          # waits for frame 4
    ready.update({4, 5, 6})
    deadline = time.time() + 2
    while time.time() < deadline and pb.playing:
        qapp.processEvents()
    assert not pb.playing and pb.frame == 6 and ended
    assert shown == [2, 3, 4, 5, 6]


def test_playback_pingpong(qapp):
    pb = Playback()
    pb.set_clip(1, 3, 1, fps=300)
    pb.set_loop_mode("pingpong")
    shown = []
    pb.frameChanged.connect(shown.append)
    pb.play(1)
    deadline = time.time() + 2
    while time.time() < deadline and len(shown) < 6:
        qapp.processEvents()
    pb.stop()
    assert shown[:6] == [2, 3, 2, 1, 2, 3]


def test_playback_realtime_drops_frames(qapp):
    pb = Playback()
    pb.set_clip(1, 1000, 1, fps=1000)
    pb.play_all_frames = False
    shown = []
    pb.frameChanged.connect(shown.append)
    pb.play(1)
    t0 = time.time()
    while time.time() - t0 < 0.2:
        qapp.processEvents()
    pb.stop()
    assert pb.frame > 100
    assert len(shown) < pb.frame   # some frames skipped to keep real time
