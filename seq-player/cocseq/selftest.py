"""`COC_SEQ Player.exe --self-test report.txt`: checks that a build can read, color manage,
decode and draw without opening a window. Exit code 0 when nothing failed."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback


def run(out_path: str | None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []
    failed = False

    def check(name: str, fn, required: bool = True):
        nonlocal failed
        try:
            detail = fn() or ""
            lines.append(f"OK    {name} {detail}".rstrip())
        except Exception as exc:
            if required:
                failed = True
            lines.append(f"{'FAIL' if required else 'WARN'}  {name}: {exc}")
            lines.append("      " + traceback.format_exc().replace("\n", "\n      ").rstrip())

    import numpy as np
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    if QApplication.instance() is None:
        if sys.platform == "win32":
            QCoreApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
        app = QApplication(["selftest"])
    else:
        app = QApplication.instance()
    from cocseq import theme

    theme.load_fonts()
    tmp = tempfile.mkdtemp(prefix="cocseq_selftest_")

    def images():
        import OpenImageIO as oiio

        from cocseq.media.readers import SequenceReader
        from cocseq.media.seqscan import scan_from_file

        for i in (1, 2, 3):
            px = np.full((32, 48, 4), i / 4.0, np.float16)
            path = os.path.join(tmp, f"t.{i:04d}.exr")
            spec = oiio.ImageSpec(48, 32, 4, "half")
            o = oiio.ImageOutput.create(path)
            o.open(path, spec)
            o.write_image(px)
            o.close()
        seq = scan_from_file(os.path.join(tmp, "t.0002.exr"))
        r = SequenceReader(seq)
        info = r.probe()
        f = r.read(3, info.layers[0])
        assert seq.frames == [1, 2, 3], seq.frames
        assert abs(float(f.pixels[0, 0, 0]) - 0.75) < 1e-3
        fmts = oiio.get_string_attribute("format_list")
        for need in ("openexr", "dpx", "tiff", "png", "jpeg"):
            assert need in fmts, f"OIIO format {need} missing"
        return f"OIIO {oiio.VERSION_STRING}"

    def color():
        from cocseq.color.ocio_mgr import ColorManager

        cm = ColorManager()
        assert cm.load("ocio://studio-config-latest", prefer_env=False), cm.error
        pipe = cm.pipeline("ACEScg", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
        assert not pipe.error, pipe.error
        fn = cm.cpu_function("Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped")
        v = fn(np.array([[[0.18, 0.18, 0.18]]], np.float32))
        assert abs(float(v[0, 0, 0]) - 0.4613) < 0.01, v
        import PyOpenColorIO as ocio

        return f"OCIO {ocio.__version__}"

    def movie():
        import av

        from cocseq.media.audio import decode_audio
        from cocseq.media.readers import MovieReader

        path = os.path.join(tmp, "t.mp4")
        c = av.open(path, "w")
        vs = c.add_stream("libx264", rate=24)
        vs.width, vs.height, vs.pix_fmt = 64, 48, "yuv420p"
        a = c.add_stream("aac", rate=48000)
        a.layout = "stereo"
        for i in range(12):
            img = np.full((48, 64, 3), i * 20, np.uint8)
            for p in vs.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                c.mux(p)
        for p in vs.encode():
            c.mux(p)
        for k in range(12):
            af = av.AudioFrame.from_ndarray(np.zeros((2, 1024), np.float32), format="fltp", layout="stereo")
            af.sample_rate = 48000
            af.pts = k * 1024
            for p in a.encode(af):
                c.mux(p)
        for p in a.encode():
            c.mux(p)
        c.close()
        r = MovieReader(path)
        info = r.probe()
        assert info.last - info.first + 1 == 12, (info.first, info.last)
        f = r.read(7)
        assert f.pixels is not None and f.pixels.shape == (48, 64, 3)
        tr = decode_audio(path)
        assert tr is not None and tr.duration > 0.1
        return f"PyAV {av.__version__}"

    def audio_out():
        from cocseq.media.audio import output_devices, sd

        if sd is None:
            raise RuntimeError("sounddevice/PortAudio not loaded")
        return f"{len(output_devices())} output device(s)"

    def gl():
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create():
            raise RuntimeError("no OpenGL 3.3 context (offscreen)")
        surf = QOffscreenSurface()
        surf.setFormat(ctx.format())
        surf.create()
        if not ctx.makeCurrent(surf):
            raise RuntimeError("makeCurrent failed")
        from OpenGL import GL

        from cocseq.color.ocio_mgr import ColorManager
        from cocseq.viewer import gl_viewer
        from cocseq.viewer.shaders import COMPOSITE_FRAGMENT, VERTEX, color_program_source

        gl_viewer._link(VERTEX, COMPOSITE_FRAGMENT)
        cm = ColorManager()
        cm.load("ocio://studio-config-latest", prefer_env=False)
        pipe = cm.pipeline("ACEScg", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
        gl_viewer._link(VERTEX, color_program_source(pipe.to_lin.text, pipe.to_disp.text))
        ver = GL.glGetString(GL.GL_VERSION)
        ctx.doneCurrent()
        return (ver or b"").decode(errors="replace")

    def fonts():
        from PySide6.QtGui import QFontDatabase

        fams = QFontDatabase.families()
        assert "Pretendard" in fams, "Pretendard font not bundled"
        return ""

    check("images (OpenImageIO)", images)
    check("color (OpenColorIO)", color)
    check("movies + audio decode (PyAV/FFmpeg)", movie)
    check("audio output (PortAudio)", audio_out, required=False)
    check("OpenGL shaders (software GL)", gl, required=False)
    check("fonts", fonts, required=False)
    from cocseq import __version__

    del app
    header = f"COC_SEQ Player {__version__} self-test  ({sys.platform}, Python {sys.version.split()[0]})"
    report = header + "\n" + "\n".join(lines) + "\n" + ("RESULT: FAIL" if failed else "RESULT: OK") + "\n"
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(report)
    if sys.stdout is not None:
        try:
            sys.stdout.write(report)
        except Exception:
            pass
    return 1 if failed else 0
