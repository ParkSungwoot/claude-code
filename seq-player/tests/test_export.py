import glob
import os
import time

import numpy as np
import pytest


@pytest.fixture()
def viewer_env(qapp, media):
    from cocseq.color.ocio_mgr import ColorManager
    from cocseq.media.source import MediaSource
    from cocseq.prefs import Prefs
    from cocseq.viewer.gl_viewer import SlotInput, ViewerWidget

    cm = ColorManager()
    cm.load("ocio://studio-config-latest", prefer_env=False)
    v = ViewerWidget()
    v.resize(480, 280)
    v.set_color_manager(cm)
    v.display.display, v.display.view = cm.resolve_display_view("sRGB - Display", "Un-tone-mapped")
    src = MediaSource.open(media["exr"])
    src.colorspace = cm.default_colorspace(src, Prefs())
    v.set_slots([SlotInput(src, src.reader.read(1001, src.layer))])
    v.show()
    end = time.time() + 2
    while time.time() < end:
        qapp.processEvents()
    yield v, src, cm
    v.close()


def test_png_sequence_matches_viewer(viewer_env, tmp_path):
    from cocseq.annotations import Shape
    from cocseq.export import Exporter, ExportSettings

    v, src, _cm = viewer_env
    src.annotations.add(1005, Shape("rect", [(20, 20), (120, 90)], "#FF0000", 6))
    s = ExportSettings(path=str(tmp_path / "out.####.png"), fmt="png", first=1003, last=1008,
                       burn_annotations=True)
    Exporter().run(s, src, v)
    files = sorted(glob.glob(str(tmp_path / "out.*.png")))
    assert [os.path.basename(f) for f in files] == [f"out.{n}.png" for n in range(1003, 1009)]
    import OpenImageIO as oiio

    img = oiio.ImageBuf(files[0]).get_pixels(oiio.FLOAT)
    assert img.shape[:2] == (180, 320)
    ref = v.render_to_array(src, src.reader.read(1003, src.layer)) if v._gl_ok else None
    if ref is not None:
        assert np.abs(img[..., :3] - np.clip(ref[..., :3], 0, 1)).max() < 1.5 / 255
    ann = oiio.ImageBuf(files[2]).get_pixels(oiio.FLOAT)    # frame 1005
    r, g, b = ann[20, 70, :3]
    assert r > 0.9 and g < 0.2 and b < 0.2


def test_exr_raw_is_exact(viewer_env, tmp_path):
    from cocseq.export import Exporter, ExportSettings

    v, src, _cm = viewer_env
    s = ExportSettings(path=str(tmp_path / "raw.####.exr"), fmt="exr", first=1001, last=1002, apply_color=False)
    Exporter().run(s, src, v)
    import OpenImageIO as oiio

    out = oiio.ImageBuf(str(tmp_path / "raw.1001.exr")).get_pixels(oiio.HALF)
    orig = src.reader.read(1001, src.layer).pixels
    assert np.array_equal(out[..., :orig.shape[2]], orig)


def test_movie_with_audio(viewer_env, media, tmp_path):
    import av

    from cocseq.export import Exporter, ExportSettings
    from cocseq.media.source import MediaSource

    v, _src, cm = viewer_env
    from cocseq.prefs import Prefs

    mov = MediaSource.open(media["movie"])
    mov.colorspace = cm.default_colorspace(mov, Prefs())
    s = ExportSettings(path=str(tmp_path / "review.mp4"), fmt="mp4_h264", first=5, last=28, include_audio=True)
    Exporter().run(s, mov, v)
    c = av.open(str(tmp_path / "review.mp4"))
    try:
        assert len(c.streams.video) == 1 and len(c.streams.audio) == 1
        n = sum(1 for _ in c.decode(video=0))
        assert n == 24
    finally:
        c.close()


def test_annotation_pdf(viewer_env, tmp_path):
    from cocseq.annotations import Shape
    from cocseq.export import write_annotations_pdf

    v, src, _cm = viewer_env
    src.annotations.add(1002, Shape("arrow", [(10, 10), (80, 60)], "#FFB23F", 4))
    src.annotations.set_note(1002, "화살표 부분 확인")
    path = str(tmp_path / "notes.pdf")
    write_annotations_pdf(path, v, src)
    data = open(path, "rb").read()
    assert data.startswith(b"%PDF") and len(data) > 5000
