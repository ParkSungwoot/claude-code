import numpy as np

from cocseq.media.audio import decode_audio
from cocseq.media.readers import MovieReader, SequenceReader, detect_layers
from cocseq.media.seqscan import scan_from_file
from cocseq.media.source import MediaSource


def test_detect_layers_single_part():
    layers = detect_layers([("", ["R", "G", "B", "A", "diffuse.R", "diffuse.G", "diffuse.B", "Z", "N.X", "N.Y", "N.Z"])])
    names = [l.name for l in layers]
    assert names[0] == "RGBA"
    rgba = layers[0]
    assert rgba.channels == ["R", "G", "B", "A"]
    diffuse = next(l for l in layers if l.name == "diffuse")
    assert diffuse.channels == ["diffuse.R", "diffuse.G", "diffuse.B"]
    assert diffuse.indices == [4, 5, 6]
    n = next(l for l in layers if l.name == "N")
    assert [c.split(".")[-1] for c in n.channels] == ["X", "Y", "Z"]
    assert any(l.name == "Z" for l in layers)


def test_detect_layers_multi_part():
    layers = detect_layers([("rgba", ["R", "G", "B", "A"]), ("spec", ["spec.R", "spec.G", "spec.B"])])
    assert [l.part for l in layers] == [0, 1]
    assert layers[1].name == "spec"


def test_exr_sequence(media):
    seq = scan_from_file(media["exr"])
    r = SequenceReader(seq)
    info = r.probe()
    assert info.pixel_type == "half" and info.is_float
    assert abs(info.fps - 25.0) < 1e-6
    assert [l.name for l in info.layers] == ["RGBA", "Z", "diffuse"]
    f = r.read(1001, info.layers[0])
    assert f.pixels.dtype == np.float16 and f.pixels.shape == (180, 320, 4)
    z = r.read(1001, info.layers[1])
    assert z.pixels.shape == (180, 320, 1)
    assert r.read(1010, info.layers[0]).missing        # the gap
    assert f.value_at(0, 0) is not None and f.value_at(999, 0) is None


def test_png_sequence(media):
    seq = scan_from_file(media["png"])
    r = SequenceReader(seq)
    info = r.probe()
    assert info.pixel_type == "uint8" and not info.is_float
    f = r.read(5, info.layers[0])
    assert f.pixels.dtype == np.uint8 and f.pixels.shape[2] == 3


def _frame_number(frame):
    px = frame.pixels
    return sum(1 << b for b in range(8) if px[9, 9 + b * 12, 0] > 128) + 1


def test_movie_frame_accurate_random_access(media):
    r = MovieReader(media["movie"], start_frame=1)
    info = r.probe()
    assert (info.first, info.last) == (1, 48)
    assert info.has_audio
    for n in (1, 2, 30, 7, 48, 12, 13, 47, 1):
        f = r.read(n)
        assert not f.missing
        assert _frame_number(f) == n, n
    assert r.read(49).missing


def test_movie_start_frame_zero(media):
    r = MovieReader(media["movie"], start_frame=0)
    info = r.probe()
    assert (info.first, info.last) == (0, 47)
    assert _frame_number(r.read(0)) == 1


def test_audio_decode(media):
    tr = decode_audio(media["movie"])
    assert tr is not None and tr.rate == 48000
    assert 1.8 < tr.duration < 2.3
    assert tr.samples.dtype == np.int16 and tr.samples.shape[1] == 2
    wav = decode_audio(media["wav"])
    assert abs(wav.duration - 2.0) < 0.05
    s = wav.slice(-0.5, 0.5)
    assert s.shape == (48000, 2) and np.all(s[:23000] == 0)
    assert wav.peaks(100).max() > 0.2


def test_media_source(media):
    src = MediaSource.open(media["exr"])
    assert src.kind == "sequence" and src.first == 1001 and src.last == 1024
    assert src.missing == [1010]
    assert src.fps == 25.0
    src.in_point, src.out_point = 1005, 1010
    assert src.range == (1005, 1010)
    assert src.set_layer("diffuse") and src.layer.name == "diffuse"
    d = src.to_dict()
    other = MediaSource.open(media["exr"])
    other.apply_dict(d)
    assert other.layer.name == "diffuse" and other.range == (1005, 1010)
    mov = MediaSource.open(media["movie"])
    assert mov.kind == "movie" and mov.audio_path == media["movie"]
