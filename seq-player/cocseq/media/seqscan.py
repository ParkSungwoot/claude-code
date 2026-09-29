"""Find image sequences on disk.

A file such as ``shot_v002.1001.exr`` belongs to the sequence ``shot_v002.####.exr``:
the last run of digits in the file name (before the extension) is the frame number.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

MOVIE_EXTS = {
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mxf", ".webm", ".wmv", ".flv", ".mpg",
    ".mpeg", ".ts", ".m2ts", ".mts", ".ogv", ".3gp", ".gif", ".y4m", ".dv", ".vob",
}
AUDIO_EXTS = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".aif", ".aiff", ".wma", ".opus"}
_FALLBACK_IMAGE_EXTS = {
    ".exr", ".sxr", ".mxr", ".dpx", ".cin", ".tif", ".tiff", ".tx", ".png", ".jpg", ".jpeg",
    ".jpe", ".jfif", ".tga", ".bmp", ".dib", ".hdr", ".rgbe", ".psd", ".psb", ".webp",
    ".sgi", ".rgb", ".rgba", ".pic", ".iff", ".jp2", ".j2k", ".ppm", ".pgm", ".pbm",
    ".pnm", ".pfm", ".dds", ".ico", ".rla", ".fits",
}

_image_exts: set[str] | None = None


def image_exts() -> set[str]:
    """Image extensions that OpenImageIO can read here (plus a safe fallback list)."""
    global _image_exts
    if _image_exts is None:
        exts = set(_FALLBACK_IMAGE_EXTS)
        try:
            import OpenImageIO as oiio

            for entry in oiio.get_string_attribute("extension_list").split(";"):
                if ":" in entry:
                    fmt, ext_list = entry.split(":", 1)
                    if fmt in ("null", "term", "zfile", "gif"):
                        continue
                    exts.update("." + e.lower() for e in ext_list.split(",") if e)
        except Exception:
            pass
        exts -= MOVIE_EXTS
        _image_exts = exts
    return _image_exts


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_image(path: str) -> bool:
    return ext_of(path) in image_exts()


def is_movie(path: str) -> bool:
    return ext_of(path) in MOVIE_EXTS


def is_audio(path: str) -> bool:
    return ext_of(path) in AUDIO_EXTS


def is_media(path: str) -> bool:
    return is_image(path) or is_movie(path)


_TRAILING_DIGITS = re.compile(r"^(?P<prefix>.*?)(?P<neg>(?<=[._\-])-)?(?P<digits>\d+)$")


def split_frame(filename: str) -> tuple[str, int, int, str] | None:
    """('shot.', 1001, 4, '.exr') for 'shot.1001.exr'; None when there is no frame number."""
    stem, ext = os.path.splitext(filename)
    if not ext:
        return None
    m = _TRAILING_DIGITS.match(stem)
    if not m:
        return None
    digits = m.group("digits")
    frame = int(digits)
    if m.group("neg"):
        frame = -frame
    return m.group("prefix"), frame, len(digits), ext


@dataclass
class Sequence:
    directory: str
    prefix: str
    ext: str
    padding: int                # 0 means frame numbers are not zero padded
    frames: list[int] = field(default_factory=list)
    single_file: str = ""       # a lone image without a frame number

    @property
    def first(self) -> int:
        return self.frames[0] if self.frames else 1

    @property
    def last(self) -> int:
        return self.frames[-1] if self.frames else 1

    @property
    def missing(self) -> list[int]:
        if not self.frames or self.single_file:
            return []
        have = set(self.frames)
        return [f for f in range(self.first, self.last + 1) if f not in have]

    def path_for(self, frame: int) -> str:
        if self.single_file:
            return self.single_file
        if self.padding > 0:
            num = f"-{abs(frame):0{self.padding}d}" if frame < 0 else f"{frame:0{self.padding}d}"
        else:
            num = str(frame)
        return os.path.join(self.directory, f"{self.prefix}{num}{self.ext}")

    @property
    def pattern(self) -> str:
        """Display form, e.g. shot.####.exr."""
        if self.single_file:
            return os.path.basename(self.single_file)
        hashes = "#" * self.padding if self.padding > 0 else "#"
        return f"{self.prefix}{hashes}{self.ext}"

    @property
    def pattern_path(self) -> str:
        return self.single_file or os.path.join(self.directory, self.pattern)

    @property
    def display_name(self) -> str:
        if self.single_file:
            return os.path.basename(self.single_file)
        name = self.prefix.rstrip("._- ")
        return name or self.pattern

    def __len__(self) -> int:
        return len(self.frames)


def _is_padded(digits_len: int, frame: int) -> bool:
    return digits_len > len(str(abs(frame)))


def _group_key(prefix: str, ext: str) -> tuple[str, str]:
    return prefix, ext.lower()


def _build(directory: str, prefix: str, ext: str, entries: list[tuple[int, int]]) -> list[Sequence]:
    """entries: (frame, digit_count). Files with different fixed paddings become separate sequences."""
    by_pad: dict[int, list[int]] = {}
    for frame, ndig in entries:
        pad = ndig if _is_padded(ndig, frame) else 0
        by_pad.setdefault(pad, []).append(frame)
    # An unpadded group whose numbers all have the same length is really a padded one.
    seqs = []
    unpadded = by_pad.pop(0, [])
    for pad, frames in by_pad.items():
        # Unpadded numbers that are exactly `pad` digits long also match this padding.
        take = [f for f in unpadded if len(str(abs(f))) == pad]
        if take:
            unpadded = [f for f in unpadded if f not in set(take)]
            frames = frames + take
        seqs.append(Sequence(directory, prefix, ext, pad, sorted(set(frames))))
    if unpadded:
        lengths = {len(str(abs(f))) for f in unpadded}
        pad = lengths.pop() if len(lengths) == 1 and len(unpadded) > 1 else 0
        seqs.append(Sequence(directory, prefix, ext, pad, sorted(set(unpadded))))
    return seqs


def scan_from_file(path: str, detect: bool = True) -> Sequence:
    """The sequence that `path` belongs to (just that file when it has no frame number)."""
    path = os.path.abspath(path)
    directory, filename = os.path.split(path)
    parts = split_frame(filename) if detect else None
    if parts is None:
        return Sequence(directory, os.path.splitext(filename)[0], ext_of(filename), 0, [1], single_file=path)
    prefix, frame, ndig, ext = parts
    entries: list[tuple[int, int]] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                name = entry.name
                if not name.startswith(prefix) or not name.lower().endswith(ext.lower()):
                    continue
                p = split_frame(name)
                if p and p[0] == prefix and p[3].lower() == ext.lower():
                    entries.append((p[1], p[2]))
    except OSError:
        entries = [(frame, ndig)]
    if not entries:
        entries = [(frame, ndig)]
    for seq in _build(directory, prefix, ext, entries):
        if frame in seq.frames and (seq.padding == 0 or seq.padding == ndig or not _is_padded(ndig, frame)):
            if len(seq.frames) == 1:
                seq.single_file = ""
            return seq
    return Sequence(directory, prefix, ext, ndig if _is_padded(ndig, frame) else 0, [frame])


@dataclass
class ScanItem:
    kind: str                 # "sequence" | "movie" | "audio"
    path: str                 # first file / movie path
    sequence: Sequence | None = None


def scan_directory(directory: str, recursive: bool = False) -> list[ScanItem]:
    """All sequences, single images, movies and audio files in a folder."""
    items: list[ScanItem] = []
    groups: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    singles: list[str] = []
    dirs = [directory]
    while dirs:
        d = dirs.pop(0)
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if recursive:
                    dirs.append(entry.path)
                continue
            path = entry.path
            if is_movie(path):
                items.append(ScanItem("movie", path))
            elif is_audio(path):
                items.append(ScanItem("audio", path))
            elif is_image(path):
                p = split_frame(entry.name)
                if p is None:
                    singles.append(path)
                else:
                    key = (d,) + _group_key(p[0], p[3])
                    groups.setdefault(key, []).append((p[1], p[2], p[3]))
    for (d, prefix, _ext), entries in groups.items():
        ext = entries[0][2]
        for seq in _build(d, prefix, ext, [(f, n) for f, n, _ in entries]):
            items.append(ScanItem("sequence", seq.path_for(seq.first), seq))
    for path in singles:
        items.append(ScanItem("sequence", path, scan_from_file(path, detect=False)))
    order = {"sequence": 0, "movie": 1, "audio": 2}
    items.sort(key=lambda it: (order[it.kind], it.path.lower()))
    return items


# ---------------------------------------------------------------- versions

_VERSION_RE = re.compile(r"([vV])(\d+)")


def version_of(path: str) -> tuple[str, int, int] | None:
    """('v', 3, 3) for .../shot_v003..., using the last version token in the path."""
    matches = list(_VERSION_RE.finditer(path))
    if not matches:
        return None
    m = matches[-1]
    return m.group(1), int(m.group(2)), len(m.group(2))


def with_version(path: str, number: int) -> str | None:
    """Swap every token equal to the last version token for another version number."""
    info = version_of(path)
    if info is None:
        return None
    letter, current, width = info
    old = f"{letter}{current:0{width}d}"
    new = f"{letter}{number:0{width}d}"
    return re.sub(rf"(?<![A-Za-z]){re.escape(old)}(?!\d)", new, path)


def find_version(path: str, step: int, is_sequence: bool, max_gap: int = 50) -> str | None:
    """Next (step=+1) or previous (step=-1) version that exists on disk."""
    info = version_of(path)
    if info is None:
        return None
    number = info[1]
    for _ in range(max_gap):
        number += step
        if number < 0:
            return None
        candidate = with_version(path, number)
        if not candidate:
            return None
        if os.path.exists(candidate):
            return candidate
        if is_sequence:
            directory, filename = os.path.split(candidate)
            parts = split_frame(filename)
            if parts and os.path.isdir(directory):
                prefix, _f, _n, ext = parts
                try:
                    with os.scandir(directory) as it:
                        for entry in it:
                            p = split_frame(entry.name)
                            if p and p[0] == prefix and p[3].lower() == ext.lower():
                                return entry.path
                except OSError:
                    pass
    return None
