"""Generate sample media for tests and demos.

    python tools/make_test_media.py OUTPUT_DIR

Creates a multi-layer EXR sequence with a missing frame, an 8-bit PNG sequence,
an H.264 movie with a tone, a WAV file and a second version of the EXR shot.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np


def _pattern(w: int, h: int, t: float, hue: float = 0.0) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = x / max(w - 1, 1), y / max(h - 1, 1)
    r = 0.5 + 0.5 * np.sin(6.2831 * (u + t + hue))
    g = 0.5 + 0.5 * np.sin(6.2831 * (v - t) + 2.0)
    b = 0.5 + 0.5 * np.sin(6.2831 * (u + v) * 0.5 + 4.0 + t * 3)
    img = np.stack([r, g, b], axis=-1) * 0.8
    # A moving bright disc with values above 1.0 to exercise exposure.
    cx, cy = w * (0.2 + 0.6 * ((t * 1.7) % 1.0)), h * 0.5
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    disc = (d < h * 0.12).astype(np.float32)
    img += disc[..., None] * np.array([3.0, 2.0, 1.0], np.float32)
    # Grey ramp strip at the bottom.
    strip = y > h * 0.88
    img[strip] = np.repeat(u[strip][:, None], 3, axis=1)
    return img.astype(np.float32)


def write_exr_sequence(folder: str, name: str, frames: range, w=320, h=180, skip=(), hue=0.0) -> str:
    import OpenImageIO as oiio

    os.makedirs(folder, exist_ok=True)
    first = None
    for f in frames:
        if f in skip:
            continue
        t = (f - frames.start) / max(len(frames), 1)
        rgb = _pattern(w, h, t, hue)
        alpha = np.ones((h, w, 1), np.float32)
        alpha[: h // 10] = 0.0
        diffuse = rgb * 0.5
        depth = np.linspace(1, 100, w, dtype=np.float32)[None, :, None].repeat(h, 0)
        pixels = np.concatenate([rgb, alpha, diffuse, depth], axis=-1).astype(np.float16)
        spec = oiio.ImageSpec(w, h, 8, "half")
        spec.channelnames = ("R", "G", "B", "A", "diffuse.R", "diffuse.G", "diffuse.B", "Z")
        spec.attribute("compression", "zip")
        spec.attribute("FramesPerSecond", oiio.TypeDesc("rational"), (25, 1))
        path = os.path.join(folder, f"{name}.{f:04d}.exr")
        out = oiio.ImageOutput.create(path)
        out.open(path, spec)
        out.write_image(pixels)
        out.close()
        first = first or path
    return first


def write_png_sequence(folder: str, name: str, frames: range, w=256, h=144) -> str:
    import OpenImageIO as oiio

    os.makedirs(folder, exist_ok=True)
    first = None
    for f in frames:
        t = (f - frames.start) / max(len(frames), 1)
        rgb = np.clip(_pattern(w, h, t, 0.3), 0, 1) ** (1 / 2.2)
        px = (rgb * 255 + 0.5).astype(np.uint8)
        path = os.path.join(folder, f"{name}_{f:03d}.png")
        out = oiio.ImageOutput.create(path)
        out.open(path, oiio.ImageSpec(w, h, 3, "uint8"))
        out.write_image(px)
        out.close()
        first = first or path
    return first


def write_movie(path: str, nframes=48, w=320, h=180, fps=24, with_audio=True) -> str:
    import av

    container = av.open(path, "w")
    vs = container.add_stream("libx264" if "libx264" in av.codecs_available else "mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = w, h, "yuv420p"
    vs.options = {"crf": "18", "g": "12"}
    astream = None
    if with_audio:
        astream = container.add_stream("aac", rate=48000)
        astream.layout = "stereo"
    for i in range(nframes):
        rgb = np.clip(_pattern(w, h, i / nframes), 0, 1) ** (1 / 2.2)
        img = (rgb * 255).astype(np.uint8)
        # Frame number as a stack of bars so tests can read it back.
        for bit in range(8):
            if i >> bit & 1:
                img[4:14, 4 + bit * 12: 14 + bit * 12] = 255
            else:
                img[4:14, 4 + bit * 12: 14 + bit * 12] = 0
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        for pkt in vs.encode(frame):
            container.mux(pkt)
    for pkt in vs.encode():
        container.mux(pkt)
    if astream is not None:
        sr = 48000
        total = int(sr * nframes / fps)
        t = np.arange(total) / sr
        tone = (0.2 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
        data = np.stack([tone, tone])
        pos = 0
        size = 1024
        while pos < total:
            chunk = np.ascontiguousarray(data[:, pos:pos + size])
            af = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
            af.sample_rate = sr
            af.pts = pos
            for pkt in astream.encode(af):
                container.mux(pkt)
            pos += size
        for pkt in astream.encode():
            container.mux(pkt)
    container.close()
    return path


def write_wav(path: str, seconds=2.0, sr=48000) -> str:
    import wave

    t = np.arange(int(sr * seconds)) / sr
    tone = (0.25 * np.sin(2 * math.pi * 330 * t) * 32767).astype(np.int16)
    stereo = np.stack([tone, tone], axis=1)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())
    return path


def make_all(out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    return {
        "exr": write_exr_sequence(os.path.join(out, "shot_v001"), "shot_v001", range(1001, 1025), skip={1010}),
        "exr_v2": write_exr_sequence(os.path.join(out, "shot_v002"), "shot_v002", range(1001, 1025), hue=0.25),
        "png": write_png_sequence(os.path.join(out, "png"), "anim", range(1, 31)),
        "movie": write_movie(os.path.join(out, "clip.mp4")),
        "wav": write_wav(os.path.join(out, "tone.wav")),
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "sample_media"
    for k, v in make_all(target).items():
        print(f"{k:7s} {v}")
