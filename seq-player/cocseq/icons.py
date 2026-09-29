"""Icon set and app logo.

Every icon is original SVG markup on a 24x24 grid: 1.75 stroke, round caps and
joins, about 2 units of padding. Glyphs draw in ``currentColor``; the wrapper
template sets the stroke defaults and the colour is substituted at render
time. Transport glyphs (play, pause, stop, ...) are solid so they read at
16-20 px.

Public API::

    icon(name, color=None, size=20, checked_color=None, disabled_color=None) -> QIcon
    pixmap(name, size, color=None, dpr=2.0) -> QPixmap
    svg(name, color) -> bytes
    names() -> list[str]
    logo_pixmap(size, dpr=2.0) -> QPixmap
    app_icon() -> QIcon                      # window/taskbar icon, every common size
    clear_cache()                            # after PAL.accent changes
    LOGO_SVG, LOGO_SVG_SMALL, logo_svg(px)   # full-colour logo (small variant <= 24 px)
    render_image(svg_data, w, h=None) -> QImage
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from cocseq.theme import PAL

log = logging.getLogger(__name__)

STROKE = 1.75

# Solid shape, no outline (exact geometry).
SOLID = 'fill="currentColor" stroke="none"'
# Solid shape plus the default outline, which rounds its corners.
FILLED = 'fill="currentColor"'
# Soft tint used for secondary areas.
TINT = 'fill="currentColor" fill-opacity=".3"'

_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
    '<g fill="none" stroke="currentColor" stroke-width="{sw}" stroke-linecap="round" '
    'stroke-linejoin="round"{opacity}>{body}</g></svg>'
)


# --------------------------------------------------------------------------- geometry helpers


def _f(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _pt(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _p(xy: tuple[float, float]) -> str:
    return f"{_f(xy[0])} {_f(xy[1])}"


def _gear(cx: float, cy: float, teeth: int, r_out: float, r_in: float,
          tip: float, base: float) -> str:
    """Closed gear outline. ``tip``/``base`` are tooth half-widths in degrees."""
    step = 360.0 / teeth
    start = -90.0
    d = [f"M{_p(_pt(cx, cy, r_in, start - base))}"]
    for i in range(teeth):
        a = start + i * step
        d.append(f"L{_p(_pt(cx, cy, r_out, a - tip))}")
        d.append(f"A{_f(r_out)} {_f(r_out)} 0 0 1 {_p(_pt(cx, cy, r_out, a + tip))}")
        d.append(f"L{_p(_pt(cx, cy, r_in, a + base))}")
        d.append(f"A{_f(r_in)} {_f(r_in)} 0 0 1 {_p(_pt(cx, cy, r_in, a + step - base))}")
    d.append("Z")
    return f'<path d="{"".join(d)}"/>'


def _arc_arrow(cx: float, cy: float, r: float, a0: float, a1: float, head: float = 3.0) -> str:
    """Arc travelling from angle a0 to a1 (degrees, y down) with a chevron at a1."""
    p0, p1 = _pt(cx, cy, r, a0), _pt(cx, cy, r, a1)
    sweep = 1 if a1 > a0 else 0
    large = 1 if abs(a1 - a0) > 180 else 0
    arc = f"M{_p(p0)}A{_f(r)} {_f(r)} 0 {large} {sweep} {_p(p1)}"
    # Aim the head along the chord of the last stretch of arc; it reads truer than
    # the exact tangent on a tight curve.
    back = math.degrees(head * 0.9 / r) * (1 if sweep else -1)
    q = _pt(cx, cy, r, a1 - back)
    dx, dy = p1[0] - q[0], p1[1] - q[1]
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    wings = []
    for ang in (135.0, -135.0):
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        wings.append((p1[0] + head * (dx * c - dy * s), p1[1] + head * (dx * s + dy * c)))
    chevron = f"M{_p(wings[0])}L{_p(p1)}L{_p(wings[1])}"
    return f'<path d="{arc}"/><path d="{chevron}"/>'


def _checker(x: float, y: float, size: float, n: int, rx: float) -> str:
    """Rounded square with a checkerboard (transparency) pattern."""
    cell = size / n
    parts = []
    for j in range(n):
        for i in range(n):
            if (i + j) % 2:
                continue
            x0, y0 = x + i * cell, y + j * cell
            x1, y1 = x0 + cell, y0 + cell
            if i == 0 and j == 0:
                d = (f"M{_f(x0)} {_f(y1)}V{_f(y0 + rx)}A{_f(rx)} {_f(rx)} 0 0 1 {_f(x0 + rx)} {_f(y0)}"
                     f"H{_f(x1)}V{_f(y1)}Z")
            elif i == n - 1 and j == n - 1:
                d = (f"M{_f(x0)} {_f(y0)}H{_f(x1)}V{_f(y1 - rx)}A{_f(rx)} {_f(rx)} 0 0 1 "
                     f"{_f(x1 - rx)} {_f(y1)}H{_f(x0)}Z")
            else:
                d = f"M{_f(x0)} {_f(y0)}H{_f(x1)}V{_f(y1)}H{_f(x0)}Z"
            parts.append(d)
    return (f'<path d="{"".join(parts)}" fill="currentColor" fill-opacity=".55" stroke="none"/>'
            f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(size)}" height="{_f(size)}" rx="{_f(rx)}"/>')


def _mirror_x(markup: str) -> str:
    return f'<g transform="matrix(-1 0 0 1 24 0)">{markup}</g>'


# --------------------------------------------------------------------------- shared parts

_SPEAKER = '<path d="M11 5.5v13l-4.25-3.75H4.5a1 1 0 0 1-1-1v-3.5a1 1 0 0 1 1-1h2.25z"/>'
_DOC = ('<path d="M13.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 '
        '1.5-1.5V8.5z"/><path d="M13.5 3.5V7a1.5 1.5 0 0 0 1.5 1.5h3.5"/>')
_EYE = ('<path d="M2.75 12C5 7.75 8.25 5.5 12 5.5s7 2.25 9.25 6.5C19 16.25 15.75 18.5 12 18.5'
        'S5 16.25 2.75 12z"/><circle cx="12" cy="12" r="3"/>')
_LENS = '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.25 15.25 20 20"/>'
_FRAME = '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/>'
_V_LETTER = '<path d="M4.5 10l3.25 8.5L11 10"/>'
_DROP = '<path d="M12 7.25c-2.25 2.5-3.6 4.5-3.6 6.2a3.6 3.6 0 0 0 7.2 0c0-1.7-1.35-3.7-3.6-6.2z"/>'
_TRI_R = '<path d="M8 5.25 19 12 8 18.75z" ' + FILLED + '/>'
_STEP = ('<path d="M6 6.5 14 12l-8 5.5z" ' + FILLED + '/>'
         '<rect x="16.5" y="5.75" width="2.5" height="12.5" rx="1.25" ' + SOLID + '/>')
_SKIP = ('<path d="M4.25 7.25 9.75 12l-5.5 4.75z" ' + FILLED + '/>'
         '<path d="M10 7.25 15.5 12 10 16.75z" ' + FILLED + '/>'
         '<rect x="17.25" y="6" width="2.5" height="12" rx="1.25" ' + SOLID + '/>')
_IN_POINT = ('<path d="M10 4.5H7a.75.75 0 0 0-.75.75v13.5a.75.75 0 0 0 .75.75h3"/>'
             '<path d="M12.25 8.75v6.5L17.25 12z" ' + FILLED + '/>')
_NEXT_CLIP = ('<rect x="13.5" y="5" width="7" height="14" rx="1.75"/>'
              '<path d="M3.5 12h7.25"/><path d="M7.75 8.75 11 12l-3.25 3.25"/>')
_ROTATE_CW = _arc_arrow(12, 12.5, 7.5, -40, 255, head=3.25)
_LOGO_MARK = (
    '<path fill-rule="evenodd" ' + SOLID + ' d="M4.5 10h9A2 2 0 0 1 15.5 12v6.5a2 2 0 0 1-2 2h-9'
    'a2 2 0 0 1-2-2V12a2 2 0 0 1 2-2zM7.6 12.75v5l4.2-2.5z"/>'
    '<path d="M5.5 8.25V8.5a2 2 0 0 1 2-2h8.5a2 2 0 0 1 2 2V15a2 2 0 0 1-2 2h-.25"/>'
    '<path d="M8.5 4.5a2 2 0 0 1 2-2H19a2 2 0 0 1 2 2V11a2 2 0 0 1-2 2h-.25" stroke-opacity=".55"/>'
)


# --------------------------------------------------------------------------- the icon set

ICONS: dict[str, str] = {
    # ---- transport
    "play": _TRI_R,
    "play-reverse": _mirror_x(_TRI_R),
    "pause": (f'<rect x="6" y="5" width="4" height="14" rx="1.3" {SOLID}/>'
              f'<rect x="14" y="5" width="4" height="14" rx="1.3" {SOLID}/>'),
    "stop": f'<rect x="5.75" y="5.75" width="12.5" height="12.5" rx="2.5" {SOLID}/>',
    "step-forward": _STEP,
    "step-back": _mirror_x(_STEP),
    "skip-end": _SKIP,
    "skip-start": _mirror_x(_SKIP),
    "loop": ('<path d="M4 12.5V10a3.5 3.5 0 0 1 3.5-3.5H19"/><path d="M16 3.5l3 3-3 3"/>'
             '<path d="M20 11.5V14a3.5 3.5 0 0 1-3.5 3.5H5"/><path d="M8 14.5l-3 3 3 3"/>'),
    "loop-once": '<path d="M4 12h12.25"/><path d="M12 7.75 16.25 12 12 16.25"/><path d="M20 6v12"/>',
    "pingpong": ('<path d="M4 8.5h15.5"/><path d="M16 5l3.5 3.5L16 12"/>'
                 '<path d="M20 15.5H4.5"/><path d="M8 12l-3.5 3.5L8 19"/>'),
    "speed": ('<path d="M4.64 18.5A8.5 8.5 0 1 1 19.36 18.5"/><path d="M12 14.25l3.4-4.1"/>'
              f'<circle cx="12" cy="14.25" r="1.6" {SOLID}/>'),
    "single-frame": '<rect x="4.5" y="4.5" width="15" height="15" rx="2"/><path d="M10.25 9.75 12.5 8v8"/>',
    "in-point": _IN_POINT,
    "out-point": _mirror_x(_IN_POINT),
    "clear-range": ('<path d="M8 4.5H5.75a.75.75 0 0 0-.75.75v13.5a.75.75 0 0 0 .75.75H8"/>'
                    '<path d="M16 4.5h2.25a.75.75 0 0 1 .75.75v13.5a.75.75 0 0 1-.75.75H16"/>'
                    '<path d="M9.75 9.75l4.5 4.5M14.25 9.75l-4.5 4.5"/>'),
    "marker": ('<path d="M7 3.5h10A1.5 1.5 0 0 1 18.5 5v9.35a1.5 1.5 0 0 1-.5 1.1l-5 4.55a1.5 1.5 0 0 1'
               '-2 0l-5-4.55a1.5 1.5 0 0 1-.5-1.1V5A1.5 1.5 0 0 1 7 3.5z"/>'),
    "next-clip": _NEXT_CLIP,
    "prev-clip": _mirror_x(_NEXT_CLIP),
    "playlist": ('<path d="M4 5.5h15M4 10h15M4 14.5h6.5"/>'
                 f'<path d="M14.25 13.25v6.5l5.25-3.25z" {FILLED}/>'),
    # ---- audio
    "volume": _SPEAKER + '<path d="M14.5 9a4.25 4.25 0 0 1 0 6"/><path d="M17.25 6.25a8 8 0 0 1 0 11.5"/>',
    "volume-mute": _SPEAKER + '<path d="M15 9.5l5 5M20 9.5l-5 5"/>',
    "audio": '<path d="M4.5 10v4M8.25 7v10M12 4v16M15.75 8v8M19.5 9.5v5"/>',
    # ---- files and media
    "folder-open": ('<path d="M3.5 17.5V6.5A1.5 1.5 0 0 1 5 5h3.9l2 2h5.6a1.5 1.5 0 0 1 1.5 1.5v2"/>'
                    '<path d="M3.5 18.25 6.2 11.5a1.5 1.5 0 0 1 1.4-.95h12.85a.75.75 0 0 1 .7 1.03L18.6 18'
                    'a1.5 1.5 0 0 1-1.4 1H4.25a.75.75 0 0 1-.75-.75z"/>'),
    "file-plus": _DOC + '<path d="M12 11.5v6M9 14.5h6"/>',
    "pdf": _DOC + ('<g stroke-width="1.35"><path d="M7.9 18.25v-5h1.3a1.45 1.45 0 0 1 0 2.9H7.9"/>'
                   '<path d="M11.3 13.25v5h.6a2.1 2.5 0 0 0 0-5z"/>'
                   '<path d="M14.9 18.25v-5h2.1M14.9 15.6h1.7"/></g>'),
    "film": ('<rect x="4" y="3.5" width="16" height="17" rx="2"/>'
             '<path d="M8 3.5v17M16 3.5v17M4 8.25h4M4 12h4M4 15.75h4M16 8.25h4M16 12h4M16 15.75h4"/>'),
    "image": (_FRAME + '<circle cx="8.75" cy="9.25" r="1.6"/>'
              '<path d="M20.5 15.25l-4.15-4.15a1.2 1.2 0 0 0-1.7 0L6.25 19.5"/>'),
    "missing": (_FRAME + '<path d="M20.5 15.25l-4.15-4.15a1.2 1.2 0 0 0-1.7 0L6.25 19.5"/>'
                '<path d="M3.5 3.5l17 17"/>'),
    "sequence": ('<rect x="3" y="10" width="12" height="10" rx="1.75"/>'
                 '<path d="M6 10V8.75A1.75 1.75 0 0 1 7.75 7h8.5A1.75 1.75 0 0 1 18 8.75V17h-3"/>'
                 '<path d="M9 7V5.75A1.75 1.75 0 0 1 10.75 4h8.5A1.75 1.75 0 0 1 21 5.75V14h-3"/>'),
    "movie": ('<rect x="3.75" y="11" width="16.5" height="9" rx="1.5"/>'
              '<path d="M4 10 20.3 7.42 19.75 3.96 3.45 6.54z"/>'
              '<path d="M8.1 9.35 9.65 5.55M13 8.58l1.55-3.8"/>'),
    "layers": ('<path d="M12 3.5 20.5 8 12 12.5 3.5 8z"/>'
               '<path d="M3.5 12 12 16.5 20.5 12"/><path d="M3.5 16 12 20.5 20.5 16"/>'),
    "save": ('<path d="M5.5 3.5h10.1l4.9 4.9V18.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/>'
             '<path d="M8 3.5v3.25a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1V3.5"/>'
             '<path d="M7.25 20.5v-5a1 1 0 0 1 1-1h7.5a1 1 0 0 1 1 1v5"/>'),
    "export": ('<path d="M4 14.5v3.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3.5"/>'
               '<path d="M12 15.5V4"/><path d="M7.75 8.25 12 4l4.25 4.25"/>'),
    "camera": ('<path d="M3.5 9a2 2 0 0 1 2-2h2.25l1.5-2.1a1 1 0 0 1 .8-.4h3.9a1 1 0 0 1 .8.4L16.25 7H18.5'
               'a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.4"/>'),
    "notes": ('<path d="M13.5 20.5h-7a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v9z"/>'
              '<path d="M19.5 14.5H15a1.5 1.5 0 0 0-1.5 1.5v4.5"/><path d="M8 8h8M8 11.5h5"/>'),
    "link": ('<path d="M10.7 7.45 13.3 4.85a4.14 4.14 0 0 1 5.85 5.85L16.55 13.3"/>'
             '<path d="M13.3 16.55 10.7 19.15a4.14 4.14 0 0 1-5.85-5.85L7.45 10.7"/>'
             '<path d="M9.5 14.5 14.5 9.5"/>'),
    "version-up": _V_LETTER + '<path d="M17 19.5V5"/><path d="M13.75 8.25 17 5l3.25 3.25"/>',
    "version-down": _V_LETTER + '<path d="M17 4.5V19"/><path d="M13.75 15.75 17 19l3.25-3.25"/>',
    # ---- colour and scopes
    "sun": ('<circle cx="12" cy="12" r="3.75"/>'
            '<path d="M12 3.5v1.75M12 18.75v1.75M3.5 12h1.75M18.75 12h1.75M6 6l1.25 1.25'
            'M16.75 16.75 18 18M6 18l1.25-1.25M16.75 7.25 18 6"/>'),
    "gamma": ('<path d="M4.5 6.75c3.5 0 5.75 3.25 7.5 8.25"/><path d="M19.5 6.75C16.25 8.5 13.25 11.75 12 15"/>'
              '<path d="M12 15c1.3 2.1 1.45 4.75 0 4.75S10.7 17.1 12 15z"/>'),
    "contrast": f'<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5a8.5 8.5 0 0 1 0 17z" {SOLID}/>',
    "palette": ('<path d="M12 3.75C17 3.75 20.75 7.15 20.75 11.25C20.75 14.15 18.6 15.25 16.75 14.65'
                'C15.15 14.1 13.95 15.05 14.35 16.6C14.85 18.6 13.7 20.25 11.5 20.25'
                'C6.9 20.25 3.25 16.55 3.25 12C3.25 7.45 7 3.75 12 3.75z"/>'
                f'<circle cx="7.75" cy="12.25" r="1.25" {SOLID}/><circle cx="9.25" cy="8.25" r="1.25" {SOLID}/>'
                f'<circle cx="13.5" cy="7" r="1.25" {SOLID}/><circle cx="16.9" cy="9.4" r="1.25" {SOLID}/>'),
    "histogram": ('<path d="M3.5 19.5h17"/>'
                  f'<path d="M4.25 19.5C6 19.5 6.5 12 8.5 12s2.1 3.5 3.6 3.5 2-9.5 4.3-9.5 2.5 13.5 3.6 13.5z" {TINT}/>'),
    "waveform": (_FRAME + '<path d="M6.25 12C7.6 8.25 8.65 8.25 10 12S12.65 15.75 14 12 16.4 8.25 17.75 12"/>'),
    "vectorscope": ('<circle cx="12" cy="12" r="8.5"/>'
                    '<path d="M12 5.5v13M5.5 12h13" stroke-width="1.1" stroke-opacity=".55"/>'
                    f'<ellipse cx="9.9" cy="9.9" rx="3.2" ry="1.9" transform="rotate(-40 9.9 9.9)" {SOLID}/>'),
    "channels": ('<circle cx="12" cy="8.75" r="4.75"/><circle cx="8.5" cy="14.75" r="4.75"/>'
                 '<circle cx="15.5" cy="14.75" r="4.75"/>'),
    "alpha": _checker(4, 4, 16, 4, 2.5),
    "eyedropper": ('<path d="M11.25 7.75 16.25 12.75"/>'
                   '<path d="M13.5 10 16.6 6.9a2.12 2.12 0 0 1 3 3L16.5 13"/>'
                   '<path d="M12.75 11.25 6 18a1.5 1.5 0 0 1-1 .45H4.5V17.9a1.5 1.5 0 0 1 .45-1L11.75 10.1"/>'),
    "color-area": ('<rect x="3.5" y="3.5" width="17" height="17" rx="2" stroke-dasharray="2.2 2.2" '
                   'stroke-linecap="butt"/>' + _DROP),
    # ---- annotation
    "pen": ('<path d="M16.3 4.2a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L8.6 18.9 4 20l1.1-4.6z"/>'
            '<path d="M14.25 6.25l3.5 3.5"/>'),
    "eraser": ('<path d="M14.98 4.58 19.92 9.52 10.02 19.42 5.08 14.48z"/>'
               f'<path d="M8.26 11.3 13.2 16.24 10.02 19.42 5.08 14.48z" {TINT}/>'
               '<path d="M10.02 19.42H19.5"/>'),
    "rect": '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "arrow": '<path d="M5.5 18.5 18 6"/><path d="M9.5 6H18v8.5"/>',
    "line": '<path d="M7.4 16.6l9.2-9.2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/>',
    "text": '<path d="M5.5 7V5h13v2"/><path d="M12 5v14"/><path d="M9.5 19h5"/>',
    "undo": '<path d="M8.5 13.5 4 9l4.5-4.5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15.5 13.5 20 9l-4.5-4.5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "trash": ('<path d="M4 6.5h16"/><path d="M9 6.5V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v1.5"/>'
              '<path d="M6 6.5l.85 12.1a2 2 0 0 0 2 1.9h6.3a2 2 0 0 0 2-1.9L18 6.5"/>'
              '<path d="M10 10.5v6M14 10.5v6"/>'),
    "ghost": ('<path d="M5.5 20V11a6.5 6.5 0 0 1 13 0v9l-2.17-1.6-2.16 1.6L12 18.4 9.83 20l-2.16-1.6z"/>'
              f'<circle cx="9.5" cy="11" r="1.15" {SOLID}/><circle cx="14.5" cy="11" r="1.15" {SOLID}/>'),
    # ---- compare
    "compare": ('<rect x="4" y="4" width="16" height="16" rx="2.5"/>'
                f'<path d="M20 4H6.5A2.5 2.5 0 0 0 4 6.5V20z" {SOLID}/>'),
    "wipe": ('<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M12 3v18"/>'
             '<path d="M8.75 10 6.75 12l2 2M15.25 10l2 2-2 2"/>'),
    "overlay": ('<rect x="3.5" y="3.5" width="11.5" height="11.5" rx="2"/>'
                f'<rect x="9" y="9" width="11.5" height="11.5" rx="2" {TINT}/>'),
    "difference": ('<path fill-rule="evenodd" fill="currentColor" fill-opacity=".45" '
                   'd="M3.5 12a5.75 5.75 0 1 0 11.5 0a5.75 5.75 0 1 0-11.5 0z'
                   'M9 12a5.75 5.75 0 1 0 11.5 0a5.75 5.75 0 1 0-11.5 0z"/>'),
    "side-by-side": ('<rect x="3.5" y="5.5" width="7" height="13" rx="1.75"/>'
                     '<rect x="13.5" y="5.5" width="7" height="13" rx="1.75"/>'),
    "top-bottom": ('<rect x="5.5" y="3.5" width="13" height="7" rx="1.75"/>'
                   '<rect x="5.5" y="13.5" width="13" height="7" rx="1.75"/>'),
    "tile": ('<rect x="3.5" y="3.5" width="7" height="7" rx="1.75"/>'
             '<rect x="13.5" y="3.5" width="7" height="7" rx="1.75"/>'
             '<rect x="3.5" y="13.5" width="7" height="7" rx="1.75"/>'
             '<rect x="13.5" y="13.5" width="7" height="7" rx="1.75"/>'),
    "a-letter": ('<rect x="3.5" y="3.5" width="17" height="17" rx="4"/>'
                 '<path d="M8.25 16.75 12 7.25l3.75 9.5" stroke-width="2"/><path d="M9.6 13.5h4.8" stroke-width="2"/>'),
    "b-letter": ('<rect x="3.5" y="3.5" width="17" height="17" rx="4"/>'
                 '<path d="M9.25 12h3.5a2.375 2.375 0 0 1 0 4.75h-3.5V7.25h3a2.375 2.375 0 0 1 0 4.75" '
                 'stroke-width="2"/>'),
    # ---- view
    "fit": ('<path d="M3.5 8V5.5a2 2 0 0 1 2-2H8M16 3.5h2.5a2 2 0 0 1 2 2V8M20.5 16v2.5a2 2 0 0 1-2 2H16'
            'M8 20.5H5.5a2 2 0 0 1-2-2V16"/><rect x="8" y="8.5" width="8" height="7" rx="1.25"/>'),
    "fullscreen": ('<path d="M3.5 9V5a1.5 1.5 0 0 1 1.5-1.5h4M15 3.5h4A1.5 1.5 0 0 1 20.5 5v4'
                   'M20.5 15v4a1.5 1.5 0 0 1-1.5 1.5h-4M9 20.5H5A1.5 1.5 0 0 1 3.5 19v-4"/>'),
    "presentation": ('<path d="M3 4.5h18"/><path d="M4.5 4.5v9A1.5 1.5 0 0 0 6 15h12a1.5 1.5 0 0 0 1.5-1.5v-9"/>'
                     '<path d="M12 15v2.5M12 17.5l-3.5 3M12 17.5l3.5 3"/>'
                     f'<path d="M10.5 7.5v4.5l3.75-2.25z" {FILLED}/>'),
    "zoom-in": _LENS + '<path d="M10.5 8v5M8 10.5h5"/>',
    "zoom-out": _LENS + '<path d="M8 10.5h5"/>',
    "search": _LENS,
    "one-to-one": ('<path d="M5.75 9 8.25 7v10M15.75 9l2.5-2v10"/>'
                   f'<circle cx="12" cy="9.75" r="1.15" {SOLID}/><circle cx="12" cy="14.25" r="1.15" {SOLID}/>'),
    "mirror-h": ('<path d="M12 3v18" stroke-dasharray="1.6 2.4" stroke-linecap="butt"/>'
                 '<path d="M9 7 3.5 17H9z"/>' f'<path d="M15 7l5.5 10H15z" {FILLED}/>'),
    "mirror-v": ('<path d="M3 12h18" stroke-dasharray="1.6 2.4" stroke-linecap="butt"/>'
                 '<path d="M7 9 17 3.5V9z"/>' f'<path d="M7 15l10 5.5V15z" {FILLED}/>'),
    "rotate-cw": _ROTATE_CW,
    "rotate-ccw": _mirror_x(_ROTATE_CW),
    "safe-area": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
                  '<rect x="6.75" y="8" width="10.5" height="8" rx="1" stroke-dasharray="2 2" '
                  'stroke-linecap="butt"/>'),
    "grid": ('<rect x="3.5" y="3.5" width="17" height="17" rx="2"/>'
             '<path d="M9.17 3.5v17M14.83 3.5v17M3.5 9.17h17M3.5 14.83h17"/>'),
    "crosshair": ('<circle cx="12" cy="12" r="6.75"/><path d="M12 3v4.25M12 16.75V21M3 12h4.25M16.75 12H21"/>'
                  f'<circle cx="12" cy="12" r="1.1" {SOLID}/>'),
    "select-area": ('<path d="M16.5 9.25V5.5a2 2 0 0 0-2-2h-9a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3.75" '
                    'stroke-dasharray="2.2 2.2" stroke-linecap="butt"/>'
                    f'<path d="M11.5 11.5l8.75 3.2-3.7 1.55-1.55 3.7z" {FILLED}/>'),
    "hand": ('<path d="M7 13.25V8.25a1.5 1.5 0 0 1 3 0v3.5"/>'
             '<path d="M10 11.75V5.75a1.5 1.5 0 0 1 3 0v6"/>'
             '<path d="M13 11.75V6.75a1.5 1.5 0 0 1 3 0v5.5"/>'
             '<path d="M16 12.25v-3a1.5 1.5 0 0 1 3 0v5.25a6 6 0 0 1-6 6h-1.2c-1.95 0-3.2-.7-4.4-2.05'
             'L4.35 15.2a1.45 1.45 0 0 1 2.1-2L7 13.75"/>'),
    "hud": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
            '<path d="M6.5 8.25h5M6.5 11h3M13.5 15.75h4"/>'),
    "eye": _EYE,
    "eye-off": _EYE + '<path d="M4.25 4.25l15.5 15.5"/>',
    # ---- panels and tools
    "info": f'<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><circle cx="12" cy="7.75" r="1.15" {SOLID}/>',
    "settings": _gear(12, 12, 8, 8.9, 6.6, 9.0, 15.5) + '<circle cx="12" cy="12" r="2.75"/>',
    "keyboard": ('<rect x="2.75" y="5.5" width="18.5" height="13" rx="2"/>'
                 f'<g {SOLID}><circle cx="6.75" cy="9.5" r="1"/><circle cx="10.25" cy="9.5" r="1"/>'
                 '<circle cx="13.75" cy="9.5" r="1"/><circle cx="17.25" cy="9.5" r="1"/>'
                 '<circle cx="6.75" cy="12.5" r="1"/><circle cx="17.25" cy="12.5" r="1"/></g>'
                 '<path d="M9.5 15.25h5M10.25 12.5h3.5"/>'),
    "terminal": ('<rect x="3" y="4.5" width="18" height="15" rx="2"/>'
                 '<path d="M7 9.25 9.75 12 7 14.75"/><path d="M12.5 14.75h4.5"/>'),
    "globe": ('<circle cx="12" cy="12" r="8.5"/><ellipse cx="12" cy="12" rx="3.6" ry="8.5"/>'
              '<path d="M3.5 12h17"/>'),
    "lock": ('<rect x="5" y="10.5" width="14" height="10" rx="2"/>'
             '<path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/><path d="M12 14.5v2"/>'),
    "refresh": _arc_arrow(12, 12, 7.75, 165, 295, 3.0) + _arc_arrow(12, 12, 7.75, -15, 115, 3.0),
    "pin": ('<path d="M9 3.5h6"/><path d="M10 3.5v5.25L7 12.5h10l-3-3.75V3.5"/><path d="M12 12.5v8"/>'),
    "cache": ('<ellipse cx="12" cy="6.5" rx="7" ry="3"/>'
              '<path d="M5 6.5v11c0 1.66 3.13 3 7 3s7-1.34 7-3v-11"/>'
              '<path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3"/>'),
    "magnet": ('<path d="M5 5h4.5v6.5a2.5 2.5 0 0 0 5 0V5H19v6.5a7 7 0 0 1-14 0z"/>'
               '<path d="M5 8.75h4.5M14.5 8.75H19"/>'),
    # ---- generic ui
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "more": (f'<g {SOLID}><circle cx="5.5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/>'
             '<circle cx="18.5" cy="12" r="1.6"/></g>'),
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M6 15l6-6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "logo-mark": _LOGO_MARK,
}


# --------------------------------------------------------------------------- app logo

# Coral-to-rose tile, three stacked frames, a play triangle "cut" into the front
# frame (filled with the tile gradient in user space, so it reads as a hole).
_LOGO_TILE = """<linearGradient id="tile" x1="8" y1="4" x2="56" y2="60" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#FF9A52"/>
    <stop offset="0.45" stop-color="#FF7A45"/>
    <stop offset="1" stop-color="#E4426E"/>
  </linearGradient>"""

LOGO_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 64 64">
<defs>
  {_LOGO_TILE}
  <linearGradient id="gloss" x1="0" y1="2" x2="0" y2="36" gradientUnits="userSpaceOnUse">
    <stop offset="0" stop-color="#FFFFFF" stop-opacity="0.20"/>
    <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
  </linearGradient>
</defs>
<rect x="1.5" y="1.5" width="61" height="61" rx="13.75" fill="url(#tile)"/>
<rect x="25.5" y="13.5" width="28" height="22" rx="4.75" fill="#FFFFFF" fill-opacity="0.34"/>
<rect x="19" y="20" width="28" height="22" rx="4.75" fill="#FFFFFF" fill-opacity="0.6"/>
<rect x="12.5" y="26.5" width="28" height="22" rx="4.75" fill="#FFFFFF"/>
<path d="M23.5 32 L33 37.5 L23.5 43 Z" fill="url(#tile)" stroke="url(#tile)"
      stroke-width="2.2" stroke-linejoin="round"/>
<rect x="1.5" y="1.5" width="61" height="61" rx="13.75" fill="url(#gloss)"/>
<rect x="2" y="2" width="60" height="60" rx="13.25" fill="none" stroke="#FFFFFF"
      stroke-opacity="0.14" stroke-width="1"/>
</svg>"""

# Simplified, pixel-aligned variant for 24 px and below: two frames, larger play.
LOGO_SVG_SMALL = f"""<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 64 64">
<defs>
  {_LOGO_TILE}
</defs>
<rect x="0" y="0" width="64" height="64" rx="14" fill="url(#tile)"/>
<rect x="24" y="12" width="28" height="24" rx="5" fill="#FFFFFF" fill-opacity="0.5"/>
<rect x="12" y="24" width="28" height="28" rx="5" fill="#FFFFFF"/>
<path d="M21 31 L33 38 L21 45 Z" fill="url(#tile)" stroke="url(#tile)" stroke-width="2.5"
      stroke-linejoin="round"/>
</svg>"""


def logo_svg(pixels: int) -> str:
    """The logo document best suited to a render of ``pixels`` device pixels."""
    return LOGO_SVG_SMALL if pixels <= 24 else LOGO_SVG


# --------------------------------------------------------------------------- rendering

_icon_cache: dict[tuple, QIcon] = {}
_pixmap_cache: dict[tuple, QPixmap] = {}
_warned: set[str] = set()


def names() -> list[str]:
    return sorted(ICONS)


def clear_cache() -> None:
    """Forget rendered icons (call after the accent colour changes)."""
    _icon_cache.clear()
    _pixmap_cache.clear()


def _known(name: str) -> bool:
    if name in ICONS:
        return True
    if name not in _warned:
        _warned.add(name)
        log.warning("unknown icon %r", name)
    return False


def svg(name: str, color: str) -> bytes:
    """The icon as a standalone SVG document drawn in ``color``."""
    body = ICONS.get(name)
    if body is None:
        _known(name)
        body = ""
    c = QColor(color)
    if not c.isValid():
        c = QColor(PAL.text2)
    opacity = f' opacity="{_f(c.alphaF())}"' if c.alpha() < 255 else ""
    doc = _TEMPLATE.format(sw=_f(STROKE), opacity=opacity, body=body)
    return doc.replace("currentColor", c.name()).encode("utf-8")


def _render(data: bytes, width: int, height: int) -> QImage:
    img = QImage(max(1, width), max(1, height), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(data))
    if renderer.isValid():
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(p, QRectF(0, 0, width, height))
        p.end()
    return img


def render_image(data: bytes | str, width: int, height: int | None = None) -> QImage:
    """Render any SVG document to a QImage of exactly ``width`` x ``height`` pixels."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _render(data, width, height or width)


def _pixmap(name: str, size: int, color: str, dpr: float) -> QPixmap:
    key = (name, size, color, round(dpr, 3))
    pm = _pixmap_cache.get(key)
    if pm is None:
        px = max(1, round(size * dpr))
        pm = QPixmap.fromImage(_render(svg(name, color), px, px))
        pm.setDevicePixelRatio(dpr)
        _pixmap_cache[key] = pm
    return pm


def pixmap(name: str, size: int, color: str | None = None, dpr: float = 2.0) -> QPixmap:
    """Icon as a pixmap of ``size`` logical pixels at device pixel ratio ``dpr``."""
    _known(name)
    return _pixmap(name, size, color or PAL.text2, dpr)


def icon(name: str, color: str | None = None, size: int = 20,
         checked_color: str | None = None, disabled_color: str | None = None,
         active_color: str | None = None) -> QIcon:
    """A QIcon with Normal / Active (hover) / Disabled / Selected modes and an On state.

    ``color`` defaults to PAL.text2 and hover brightens to PAL.text. When a colour
    is given explicitly, hover keeps it unless ``active_color`` says otherwise.
    Checked buttons (On state) draw in ``checked_color`` (default PAL.accent).
    """
    normal = color or PAL.text2
    active = active_color or (PAL.text if color is None else color)
    checked = checked_color or PAL.accent
    disabled = disabled_color or PAL.text3
    key = (name, size, normal, active, checked, disabled, PAL.text)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached

    ic = QIcon()
    if not _known(name):
        blank = QPixmap(size, size)
        blank.fill(Qt.transparent)
        ic.addPixmap(blank)
        return ic

    plan = (
        (QIcon.Normal, QIcon.Off, normal),
        (QIcon.Active, QIcon.Off, active),
        (QIcon.Selected, QIcon.Off, PAL.text),
        (QIcon.Disabled, QIcon.Off, disabled),
        (QIcon.Normal, QIcon.On, checked),
        (QIcon.Active, QIcon.On, checked),
        (QIcon.Selected, QIcon.On, checked),
        (QIcon.Disabled, QIcon.On, disabled),
    )
    for mode, state, col in plan:
        for dpr in (1.0, 2.0):
            ic.addPixmap(_pixmap(name, size, col, dpr), mode, state)
    _icon_cache[key] = ic
    return ic


def logo_pixmap(size: int, dpr: float = 2.0) -> QPixmap:
    """The full-colour app logo, ``size`` logical pixels square."""
    key = ("__logo__", size, round(dpr, 3))
    pm = _pixmap_cache.get(key)
    if pm is None:
        px = max(1, round(size * dpr))
        pm = QPixmap.fromImage(render_image(logo_svg(px), px))
        pm.setDevicePixelRatio(dpr)
        _pixmap_cache[key] = pm
    return pm


LOGO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """Window / taskbar icon with a crisp render at every common size."""
    ic = QIcon()
    for s in LOGO_SIZES:
        ic.addPixmap(logo_pixmap(s, 1.0))
    ic.addPixmap(logo_pixmap(256, 2.0))
    return ic
