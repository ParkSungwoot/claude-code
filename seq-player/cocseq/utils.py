"""Small helpers shared across the app: resources, time formatting, memory."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path


def resource_path(*parts: str) -> str:
    """Path to a bundled resource, both from source and from a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = Path(__file__).resolve().parent.parent
    return str(Path(base, *parts))


def total_ram_bytes() -> int:
    """Physical memory of this machine, or 8 GB when it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys)
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        return 8 * 1024 ** 3


def default_cache_gb() -> float:
    gb = total_ram_bytes() / 1024 ** 3
    return float(max(1, min(32, round(gb * 0.4))))


def default_threads() -> int:
    return max(2, min(8, (os.cpu_count() or 4)))


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def fps_label(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-3:
        return str(int(round(fps)))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def frames_to_timecode(frame: int, fps: float, start_offset: int = 0) -> str:
    """HH:MM:SS:FF. Non-integer rates (23.976, 29.97) count with the rounded rate."""
    fps_i = max(1, int(round(fps)))
    f = frame - start_offset
    sign = "-" if f < 0 else ""
    f = abs(f)
    ff = f % fps_i
    total_s = f // fps_i
    ss = total_s % 60
    mm = (total_s // 60) % 60
    hh = total_s // 3600
    return f"{sign}{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def timecode_to_frames(tc: str, fps: float) -> int | None:
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return None
    try:
        hh, mm, ss, ff = (int(p) for p in parts)
    except ValueError:
        return None
    fps_i = max(1, int(round(fps)))
    return ((hh * 60 + mm) * 60 + ss) * fps_i + ff


def frames_to_seconds(frame: int, fps: float, start: int = 0) -> str:
    return f"{(frame - start) / max(fps, 1e-6):.2f}s"


def format_frame(frame: int, mode: str, fps: float, start: int, tc_start: int = 0) -> str:
    if mode == "timecode":
        return frames_to_timecode(frame - start + tc_start, fps)
    if mode == "seconds":
        return frames_to_seconds(frame, fps, start)
    return str(frame)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def nice_step(span: float, target_count: int) -> float:
    """A round step (1, 2, 5 x 10^n) that splits `span` into about target_count pieces."""
    if span <= 0 or target_count <= 0:
        return 1.0
    raw = span / target_count
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag
