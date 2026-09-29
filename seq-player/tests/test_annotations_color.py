import numpy as np

from cocseq.annotations import AnnotationStore, Shape, render_layer
from cocseq.color.ocio_mgr import ColorManager


def test_annotation_undo_redo_and_hold():
    st = AnnotationStore()
    st.add(10, Shape("pen", [(0, 0), (5, 5)]))
    st.add(10, Shape("rect", [(1, 1), (4, 4)], hold=3))
    st.add(20, Shape("text", [(2, 2)], text="hi"))
    assert st.annotated_frames() == [10, 20]
    assert len(st.visible(10)) == 2
    assert [s.kind for s, _a in st.visible(12)] == ["rect"]
    assert st.visible(13) == []
    ghosts = st.visible(11, ghost=2)
    assert any(a < 1.0 for _s, a in ghosts)
    assert st.undo() == 20
    assert st.annotated_frames() == [10]
    assert st.redo() == 20
    assert st.next_frame(10, 1) == 20 and st.next_frame(20, 1) is None and st.next_frame(20, -1) == 10
    st.set_note(15, "check the edge")
    assert 15 in st.annotated_frames()
    d = st.to_dict()
    other = AnnotationStore()
    other.load_dict(d)
    assert other.annotated_frames() == [10, 15, 20]
    assert other.frames[20][0].text == "hi" and other.notes[15] == "check the edge"
    st.clear_frame(10)
    assert 10 not in st.annotated_frames()


def test_render_layer_eraser(qapp):
    from PySide6.QtGui import QTransform

    shapes = [(Shape("rect", [(2, 2), (30, 30)], "#FF0000", 4, fill=True), 1.0),
              (Shape("eraser", [(10, 16), (22, 16)], size=3), 1.0)]
    img = render_layer((40, 40), shapes, QTransform())
    red = img.pixelColor(2, 16)
    assert red.red() > 200 and red.alpha() > 200
    erased = img.pixelColor(16, 16)
    assert erased.alpha() == 0


def test_color_manager_builtin():
    cm = ColorManager()
    assert cm.load("ocio://studio-config-latest", prefer_env=False)
    assert "sRGB - Display" in cm.displays()
    assert "Un-tone-mapped" in cm.views("sRGB - Display")
    assert cm.resolve_colorspace("lin_rec709_srgb") == "Linear Rec.709 (sRGB)"
    assert cm.resolve_colorspace("does-not-exist") == "ACEScg"   # falls back to scene_linear
    pipe = cm.pipeline("ACEScg", "sRGB - Display", "ACES 2.0 - SDR 100 nits (Rec.709)")
    assert not pipe.error and "ocio_disp" in pipe.to_disp.text
    assert any(t.kind in ("1d", "2d", "3d") for t in pipe.to_disp.textures) or pipe.to_disp.textures == []
    data = cm.pipeline("Raw", "sRGB - Display", "Un-tone-mapped")
    assert "return c;" in data.to_disp.text
    fn = cm.cpu_function("Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped")
    out = fn(np.array([[[0.18, 0.18, 0.18], [1.0, 1.0, 1.0]]], np.float32))
    assert abs(out[0, 0, 0] - 0.4613) < 5e-3 and abs(out[0, 1, 0] - 1.0) < 5e-3


def test_color_manager_bad_config_falls_back(tmp_path):
    bad = tmp_path / "broken.ocio"
    bad.write_text("not: [a valid config")
    cm = ColorManager()
    assert cm.load(str(bad), prefer_env=False)       # falls back to the built-in config
    assert cm.uri == "ocio://studio-config-latest"
    pipe = cm.pipeline("sRGB Encoded Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped", lut=str(tmp_path / "x.cube"))
    assert pipe.error                                 # missing LUT -> fallback shader, no crash
