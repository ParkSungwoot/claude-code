"""Per-frame drawings and notes on a clip, with undo, plus the code that paints them."""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform

TOOLS = ("pen", "eraser", "line", "arrow", "rect", "ellipse", "text")


@dataclass
class Shape:
    kind: str
    points: list = field(default_factory=list)   # [(x, y)] in image pixels (display window)
    color: str = "#FF4D5E"
    size: float = 4.0                            # stroke width in image pixels
    opacity: float = 1.0
    text: str = ""
    fill: bool = False
    hold: int = 1                                # frames the shape stays visible (>= 1)

    def bounds(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class AnnotationStore:
    def __init__(self):
        self.frames: dict[int, list[Shape]] = {}
        self.notes: dict[int, str] = {}
        self._undo: list[tuple[int, list[Shape], str]] = []
        self._redo: list[tuple[int, list[Shape], str]] = []
        self.revision = 0

    # ---------------------------------------------------------------- edits

    def _snapshot(self, frame: int) -> None:
        self._undo.append((frame, copy.deepcopy(self.frames.get(frame, [])), self.notes.get(frame, "")))
        del self._undo[:-200]
        self._redo.clear()

    def _changed(self) -> None:
        self.revision += 1

    def add(self, frame: int, shape: Shape) -> None:
        self._snapshot(frame)
        self.frames.setdefault(frame, []).append(shape)
        self._changed()

    def clear_frame(self, frame: int) -> None:
        if frame in self.frames or frame in self.notes:
            self._snapshot(frame)
            self.frames.pop(frame, None)
            self._changed()

    def clear_all(self) -> None:
        self.frames.clear()
        self.notes.clear()
        self._undo.clear()
        self._redo.clear()
        self._changed()

    def set_note(self, frame: int, text: str) -> None:
        text = text.strip()
        if self.notes.get(frame, "") == text:
            return
        if text:
            self.notes[frame] = text
        else:
            self.notes.pop(frame, None)
        self._changed()

    def _swap(self, src: list, dst: list) -> int | None:
        if not src:
            return None
        frame, shapes, note = src.pop()
        dst.append((frame, copy.deepcopy(self.frames.get(frame, [])), self.notes.get(frame, "")))
        if shapes:
            self.frames[frame] = shapes
        else:
            self.frames.pop(frame, None)
        if note:
            self.notes[frame] = note
        else:
            self.notes.pop(frame, None)
        self._changed()
        return frame

    def undo(self) -> int | None:
        return self._swap(self._undo, self._redo)

    def redo(self) -> int | None:
        return self._swap(self._redo, self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    # ---------------------------------------------------------------- queries

    def annotated_frames(self) -> list[int]:
        return sorted(set(f for f, s in self.frames.items() if s) | set(self.notes))

    def is_empty(self) -> bool:
        return not any(self.frames.values()) and not self.notes

    def next_frame(self, frame: int, step: int) -> int | None:
        frames = self.annotated_frames()
        if step > 0:
            later = [f for f in frames if f > frame]
            return later[0] if later else None
        earlier = [f for f in frames if f < frame]
        return earlier[-1] if earlier else None

    def visible(self, frame: int, ghost: int = 0) -> list[tuple[Shape, float]]:
        """Shapes to draw on `frame` with their opacity (held shapes and onion-skin ghosts)."""
        out: list[tuple[Shape, float]] = []
        for f, shapes in self.frames.items():
            if not shapes:
                continue
            d = frame - f
            for s in shapes:
                if 0 <= d < max(1, s.hold):
                    out.append((s, 1.0))
                elif ghost and 0 < abs(d) <= ghost and not (0 <= d < s.hold):
                    out.append((s, 0.35 * (1.0 - (abs(d) - 1) / ghost)))
        # Ghosts first so the current frame draws on top.
        out.sort(key=lambda t: t[1])
        return out

    # ---------------------------------------------------------------- session

    def to_dict(self) -> dict:
        return {
            "frames": {str(f): [asdict(s) for s in shapes] for f, shapes in self.frames.items() if shapes},
            "notes": {str(f): t for f, t in self.notes.items()},
        }

    def load_dict(self, d: dict) -> None:
        self.frames = {}
        for f, shapes in (d.get("frames") or {}).items():
            items = []
            for s in shapes:
                try:
                    s = dict(s)
                    s["points"] = [tuple(p) for p in s.get("points", [])]
                    items.append(Shape(**s))
                except TypeError:
                    continue
            self.frames[int(f)] = items
        self.notes = {int(f): t for f, t in (d.get("notes") or {}).items()}
        self._undo.clear()
        self._redo.clear()
        self._changed()


# ------------------------------------------------------------------ painting


def _pen(shape: Shape, scale: float, alpha: float) -> QPen:
    c = QColor(shape.color)
    c.setAlphaF(max(0.0, min(1.0, shape.opacity * alpha)))
    pen = QPen(c, max(0.5, shape.size))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCosmetic(False)
    return pen


def _smooth_path(points: list) -> QPainterPath:
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(QPointF(*points[0]))
    if len(points) == 1:
        path.lineTo(QPointF(points[0][0] + 0.01, points[0][1]))
        return path
    for i in range(1, len(points) - 1):
        mid = QPointF((points[i][0] + points[i + 1][0]) / 2, (points[i][1] + points[i + 1][1]) / 2)
        path.quadTo(QPointF(*points[i]), mid)
    path.lineTo(QPointF(*points[-1]))
    return path


def text_font(shape: Shape) -> QFont:
    f = QFont("Pretendard")
    f.setFamilies(["Pretendard", "Malgun Gothic", "Segoe UI"])
    f.setPixelSize(max(6, int(shape.size * 6)))
    f.setWeight(QFont.DemiBold)
    return f


def paint_shape(p: QPainter, shape: Shape, alpha: float = 1.0) -> None:
    """Draw one shape; `p` is already transformed to image pixel coordinates."""
    pts = shape.points
    if not pts:
        return
    if shape.kind == "eraser":
        p.save()
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        pen = QPen(Qt.black, max(1.0, shape.size * 3))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(_smooth_path(pts))
        p.restore()
        return
    pen = _pen(shape, 1.0, alpha)
    p.setPen(pen)
    fill = QColor(pen.color())
    fill.setAlphaF(fill.alphaF() * 0.25)
    p.setBrush(fill if shape.fill else Qt.NoBrush)
    if shape.kind == "pen":
        p.setBrush(Qt.NoBrush)
        p.drawPath(_smooth_path(pts))
    elif shape.kind in ("line", "arrow") and len(pts) >= 2:
        a, b = QPointF(*pts[0]), QPointF(*pts[-1])
        p.drawLine(a, b)
        if shape.kind == "arrow":
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            head = max(10.0, shape.size * 4.0)
            spread = math.radians(26)
            left = QPointF(b.x() - head * math.cos(ang - spread), b.y() - head * math.sin(ang - spread))
            right = QPointF(b.x() - head * math.cos(ang + spread), b.y() - head * math.sin(ang + spread))
            p.setBrush(pen.color())
            p.drawPolygon(QPolygonF([b, left, right]))
    elif shape.kind in ("rect", "ellipse") and len(pts) >= 2:
        r = QRectF(QPointF(*pts[0]), QPointF(*pts[-1])).normalized()
        if shape.kind == "rect":
            p.drawRect(r)
        else:
            p.drawEllipse(r)
    elif shape.kind == "text" and shape.text:
        p.setFont(text_font(shape))
        c = QColor(shape.color)
        c.setAlphaF(shape.opacity * alpha)
        # Soft shadow keeps text readable on bright images.
        shadow = QColor(0, 0, 0, int(140 * alpha))
        p.setPen(shadow)
        x, y = pts[0]
        off = max(1.0, shape.size * 0.3)
        for i, line in enumerate(shape.text.split("\n")):
            p.drawText(QPointF(x + off, y + off + i * shape.size * 7.2), line)
        p.setPen(c)
        for i, line in enumerate(shape.text.split("\n")):
            p.drawText(QPointF(x, y + i * shape.size * 7.2), line)


def render_layer(size: tuple[int, int], shapes: list[tuple[Shape, float]], transform: QTransform,
                 extra: Shape | None = None) -> QImage:
    """Draw shapes into a transparent image (so the eraser only erases drawings)."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setTransform(transform)
    for shape, alpha in shapes:
        paint_shape(p, shape, alpha)
    if extra is not None:
        paint_shape(p, extra, 1.0)
    p.end()
    return img
