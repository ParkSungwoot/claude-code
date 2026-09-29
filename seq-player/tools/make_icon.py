"""Render the app logo to assets/icon.png (256 px) and a multi-size assets/icon.ico.

Run from the seq-player folder:

    python tools/make_icon.py

Every size in the .ico is its own render (sizes of 24 px and below use the
simplified small logo), so small icons stay crisp instead of being scaled down
from the 256 px image.
"""

from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Headless render: never needs (or wants) a display.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from cocseq import icons  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _to_pil(img: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.convertToFormat(QImage.Format_ARGB32).save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def render(size: int) -> Image.Image:
    return _to_pil(icons.render_image(icons.logo_svg(size), size))


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    out_dir = os.path.join(ROOT, "assets")
    os.makedirs(out_dir, exist_ok=True)

    images = {s: render(s) for s in SIZES}

    png_path = os.path.join(out_dir, "icon.png")
    images[256].save(png_path, format="PNG")

    ico_path = os.path.join(out_dir, "icon.ico")
    images[256].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=[images[s] for s in SIZES if s != 256],
    )

    print(f"wrote {png_path}")
    print(f"wrote {ico_path}  ({', '.join(str(s) for s in SIZES)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
