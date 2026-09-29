"""User preferences, stored as JSON inside QSettings (an .ini file per user)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from PySide6.QtCore import QObject, QSettings, Signal

from cocseq import APP_ID, ORG_NAME
from cocseq.utils import default_cache_gb, default_threads


@dataclass
class Prefs:
    # General
    single_instance: bool = True
    open_maximized: bool = True
    recent_max: int = 15
    accent: str = "#FF7A45"
    auto_detect_sequence: bool = True

    # Playback
    default_fps: float = 24.0
    loop_mode: str = "loop"            # loop | once | pingpong
    play_all_frames: bool = True       # False: keep real time and drop frames
    autoplay_on_open: bool = False
    missing_frame: str = "black"       # black | hold
    time_display: str = "frames"       # frames | timecode | seconds
    movie_start_frame: int = 1
    compare_align: str = "relative"    # relative | absolute
    playlist_continuous: bool = False  # after the last frame go on to the next clip

    # Cache
    cache_gb: float = field(default_factory=default_cache_gb)
    reader_threads: int = field(default_factory=default_threads)
    cache_behind_ratio: float = 0.15

    # Color
    ocio_config: str = "ocio://studio-config-latest"
    ocio_prefer_env: bool = True
    cs_float: str = "Linear Rec.709 (sRGB)"
    cs_int: str = "sRGB Encoded Rec.709 (sRGB)"
    cs_movie: str = "sRGB Encoded Rec.709 (sRGB)"
    display: str = "sRGB - Display"
    view: str = "Un-tone-mapped"

    # Viewer
    background: str = "dark"           # dark | gray | checker | custom
    background_color: str = "#202020"
    checker_size: int = 16
    hud: bool = True
    hud_items: list = field(default_factory=lambda: ["name", "frame", "resolution", "fps", "layer"])
    filter_linear: bool = True
    safe_area_ratio: str = ""          # aspect guide: "", "16:9", "1.85", "2.39", ...
    zoom_to_fit_on_open: bool = True

    # Audio
    audio_device: str = ""
    volume: float = 0.8
    muted: bool = False
    audio_scrub: bool = False

    # Annotation defaults
    pen_color: str = "#FF4D5E"
    pen_size: float = 4.0
    ghost_frames: int = 0

    # Hotkeys: action id -> key sequence string ("" disables)
    hotkeys: dict = field(default_factory=dict)

    # Remembered state
    recent_files: list = field(default_factory=list)
    recent_sessions: list = field(default_factory=list)
    last_dir: str = ""
    panel: str = "playlist"
    panel_visible: bool = True
    panel_width: int = 330

    def add_recent(self, path: str, session: bool = False) -> None:
        items = self.recent_sessions if session else self.recent_files
        if path in items:
            items.remove(path)
        items.insert(0, path)
        del items[self.recent_max:]


class PrefsStore(QObject):
    """Holds the one Prefs object and tells the app when it changes."""

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings(QSettings.IniFormat, QSettings.UserScope, ORG_NAME, APP_ID)
        self.prefs = self._load()

    def _load(self) -> Prefs:
        prefs = Prefs()
        raw = self.settings.value("prefs_json", "")
        if not raw:
            return prefs
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return prefs
        known = {f.name: f for f in fields(Prefs)}
        for key, value in data.items():
            if key not in known:
                continue
            default = getattr(prefs, key)
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int) and not isinstance(value, bool):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(default, float):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
            elif type(default) is not type(value):
                continue
            setattr(prefs, key, value)
        return prefs

    def save(self) -> None:
        self.settings.setValue("prefs_json", json.dumps(asdict(self.prefs), ensure_ascii=False))
        self.settings.sync()

    def apply(self, prefs: Prefs) -> None:
        self.prefs = prefs
        self.save()
        self.changed.emit()

    def value(self, key: str, default=None):
        return self.settings.value(key, default)

    def set_value(self, key: str, value) -> None:
        self.settings.setValue(key, value)


_store: PrefsStore | None = None


def store() -> PrefsStore:
    global _store
    if _store is None:
        _store = PrefsStore()
    return _store


def prefs() -> Prefs:
    return store().prefs
