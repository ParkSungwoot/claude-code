import os

from cocseq.media.seqscan import (Sequence, find_version, scan_directory, scan_from_file, split_frame, version_of,
                                  with_version)


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x")


def test_split_frame():
    assert split_frame("shot.1001.exr") == ("shot.", 1001, 4, ".exr")
    assert split_frame("render_0001.png") == ("render_", 1, 4, ".png")
    assert split_frame("shot_v002.0042.dpx") == ("shot_v002.", 42, 4, ".dpx")
    assert split_frame("img12.jpg") == ("img", 12, 2, ".jpg")
    assert split_frame("name.-005.exr") == ("name.", -5, 3, ".exr")
    assert split_frame("plate.exr") is None
    assert split_frame("noext") is None


def test_scan_padded_with_gap(tmp_path):
    for f in (1001, 1002, 1004, 1005):
        touch(str(tmp_path / f"a.{f:04d}.exr"))
    touch(str(tmp_path / "a.1003.jpg"))            # other extension: not part of it
    touch(str(tmp_path / "b.1003.exr"))            # other prefix
    seq = scan_from_file(str(tmp_path / "a.1002.exr"))
    assert seq.frames == [1001, 1002, 1004, 1005]
    assert seq.missing == [1003]
    assert seq.pattern == "a.####.exr"
    assert seq.path_for(1004) == str(tmp_path / "a.1004.exr")


def test_scan_unpadded(tmp_path):
    for f in (1, 2, 9, 10, 11, 100):
        touch(str(tmp_path / f"u_{f}.png"))
    seq = scan_from_file(str(tmp_path / "u_10.png"))
    assert seq.padding == 0
    assert seq.frames == [1, 2, 9, 10, 11, 100]
    assert seq.path_for(9) == str(tmp_path / "u_9.png")


def test_single_file_and_no_detect(tmp_path):
    touch(str(tmp_path / "plate.exr"))
    seq = scan_from_file(str(tmp_path / "plate.exr"))
    assert seq.single_file and seq.frames == [1]
    touch(str(tmp_path / "x.0001.exr"))
    touch(str(tmp_path / "x.0002.exr"))
    one = scan_from_file(str(tmp_path / "x.0002.exr"), detect=False)
    assert one.single_file.endswith("x.0002.exr")


def test_scan_directory(tmp_path):
    for f in range(1, 4):
        touch(str(tmp_path / f"s.{f:04d}.exr"))
    touch(str(tmp_path / "clip.mov"))
    touch(str(tmp_path / "music.wav"))
    touch(str(tmp_path / "still.png"))
    touch(str(tmp_path / "notes.txt"))
    items = scan_directory(str(tmp_path))
    kinds = [(it.kind, os.path.basename(it.path)) for it in items]
    assert ("sequence", "s.0001.exr") in kinds
    assert ("movie", "clip.mov") in kinds
    assert ("audio", "music.wav") in kinds
    assert ("sequence", "still.png") in kinds
    assert not any(n == "notes.txt" for _k, n in kinds)


def test_versions(tmp_path):
    for v in (1, 2, 5):
        touch(str(tmp_path / f"v{v:03d}" / f"shot_v{v:03d}.1001.exr"))
    p1 = str(tmp_path / "v001" / "shot_v001.1001.exr")
    assert version_of(p1)[1] == 1
    assert with_version(p1, 2) == str(tmp_path / "v002" / "shot_v002.1001.exr")
    nxt = find_version(p1, 1, True)
    assert nxt and "v002" in nxt
    nxt2 = find_version(nxt, 1, True)
    assert nxt2 and "v005" in nxt2
    assert find_version(nxt2, 1, True) is None
    assert "v001" in find_version(nxt, -1, True)


def test_sequence_display():
    s = Sequence("/d", "shot.", ".exr", 4, [1, 2, 3])
    assert s.display_name == "shot"
    assert s.first == 1 and s.last == 3 and len(s) == 3
