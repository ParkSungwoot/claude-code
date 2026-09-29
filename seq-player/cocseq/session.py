"""Save and restore the whole review state (.cocseq JSON files)."""

from __future__ import annotations

import json
import logging
import os

from cocseq import APP_NAME, __version__

log = logging.getLogger(__name__)
VERSION = 1


def session_dict(win) -> dict:
    sources = win.sources
    idx = {s.id: i for i, s in enumerate(sources)}
    v = win.viewer
    return {
        "version": VERSION,
        "app": APP_NAME,
        "app_version": __version__,
        "sources": [s.to_dict() for s in sources],
        "a": idx.get(win.a.id) if win.a is not None else None,
        "compare": {
            "mode": win.compare_mode,
            "slots": [idx.get(s.id) if s is not None else None for s in win.compare_slots],
            "wipe": [v.wipe_pos.x(), v.wipe_pos.y(), v.wipe_angle],
            "overlay": v.overlay_opacity,
            "diff_gain": v.diff_gain,
            "align": win.compare_align,
            "offset": win.compare_offset,
        },
        "display": v.display.to_dict(),
        "view": {
            "mirror_x": v.mirror_x,
            "mirror_y": v.mirror_y,
            "rotation": v.rotation,
            "background": v.background,
            "filter_linear": v.filter_linear,
            "safe_areas": v.show_safe_areas,
            "aspect_guide": v.aspect_guide,
            "env": [v.env_mode, v.env_yaw, v.env_pitch, v.env_fov],
        },
        "playback": {"loop": win.playback.loop_mode, "play_all": win.playback.play_all_frames},
    }


def save_session(win, path: str) -> None:
    data = session_dict(win)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_session(win, path: str) -> list[str]:
    """Restore a session into the window. Returns warnings (e.g. files that were not found)."""
    from PySide6.QtCore import QPointF

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError("COC_SEQ Player 세션 파일이 아닙니다.")
    warnings = []
    win.close_all(confirm=False)
    opened = []
    base = os.path.dirname(os.path.abspath(path))
    for sd in data.get("sources", []):
        p = sd.get("path", "")
        if not os.path.exists(p):
            # Allow sessions to move together with their media (relative lookup).
            alt = os.path.join(base, os.path.basename(os.path.dirname(p)), os.path.basename(p))
            if os.path.exists(alt):
                p = alt
            else:
                warnings.append(p)
                opened.append(None)
                continue
        src = win.add_source_path(p, activate=False, restore=sd)
        opened.append(src)
    v = win.viewer
    disp = data.get("display") or {}
    v.display.apply_dict(disp)
    view = data.get("view") or {}
    v.mirror_x = bool(view.get("mirror_x", False))
    v.mirror_y = bool(view.get("mirror_y", False))
    v.rotation = int(view.get("rotation", 0))
    v.background = view.get("background", v.background)
    v.filter_linear = bool(view.get("filter_linear", True))
    v.show_safe_areas = bool(view.get("safe_areas", False))
    v.aspect_guide = view.get("aspect_guide", "") or ""
    env = view.get("env") or [False, 0, 0, 90]
    v.env_mode, v.env_yaw, v.env_pitch, v.env_fov = bool(env[0]), float(env[1]), float(env[2]), float(env[3])
    pb = data.get("playback") or {}
    win.playback.set_loop_mode(pb.get("loop", win.playback.loop_mode))
    win.playback.play_all_frames = bool(pb.get("play_all", win.playback.play_all_frames))
    cmp_ = data.get("compare") or {}
    slots = []
    for i in cmp_.get("slots", [None, None, None])[:3]:
        slots.append(opened[i] if isinstance(i, int) and 0 <= i < len(opened) else None)
    while len(slots) < 3:
        slots.append(None)
    win.compare_slots = slots
    wipe = cmp_.get("wipe", [0.5, 0.5, 0.0])
    v.wipe_pos = QPointF(float(wipe[0]), float(wipe[1]))
    v.wipe_angle = float(wipe[2])
    v.overlay_opacity = float(cmp_.get("overlay", 0.5))
    v.diff_gain = float(cmp_.get("diff_gain", 1.0))
    win.compare_align = cmp_.get("align", win.compare_align)
    win.compare_offset = int(cmp_.get("offset", 0))
    a = data.get("a")
    target = opened[a] if isinstance(a, int) and 0 <= a < len(opened) else next((s for s in opened if s), None)
    if target is not None:
        win.set_a(target)
    win.set_compare_mode(cmp_.get("mode", "A"))
    win.after_session_load()
    return warnings
