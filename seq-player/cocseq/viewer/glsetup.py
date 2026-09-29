"""Software OpenGL on Windows.

With Qt::AA_UseSoftwareOpenGL, Qt draws through Mesa's opengl32sw.dll (shipped with
PySide6) instead of the system opengl32.dll. PyOpenGL must then call into that same DLL,
otherwise every function beyond OpenGL 1.1 resolves to NULL. Call `use_software_gl()`
before anything imports OpenGL.GL.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def software_gl_dll() -> str | None:
    candidates = []
    try:
        import PySide6

        candidates.append(os.path.join(os.path.dirname(PySide6.__file__), "opengl32sw.dll"))
    except Exception:
        pass
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates += [os.path.join(base, "PySide6", "opengl32sw.dll"), os.path.join(base, "opengl32sw.dll")]
    candidates.append(os.path.join(os.path.dirname(sys.executable), "opengl32sw.dll"))
    return next((c for c in candidates if os.path.isfile(c)), None)


def use_software_gl() -> str | None:
    """Make Qt and PyOpenGL share Mesa's software OpenGL. Returns the DLL path used."""
    if sys.platform != "win32":
        return None
    path = software_gl_dll()
    if path is None:
        log.warning("opengl32sw.dll not found; software OpenGL unavailable")
        return None
    os.environ["QT_OPENGL_DLL"] = path
    import ctypes

    lib = ctypes.WinDLL(path)
    from OpenGL import platform

    plat = platform.PLATFORM
    if "GL" in vars(plat):
        log.warning("PyOpenGL already bound to %s", plat.GL)
    plat.GL = lib
    plat.OpenGL = lib
    log.info("software OpenGL: %s", path)
    return path
