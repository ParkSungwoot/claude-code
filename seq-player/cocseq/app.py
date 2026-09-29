"""Application start-up: OpenGL format, theme, single instance, main window."""

from __future__ import annotations

import getpass
import json
import logging
import os
import sys


def log_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "state")
    path = os.path.join(base, "COC", "COC_SEQ_Player", "logs")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.join(os.path.expanduser("~"))
    return path


def _setup_logging() -> None:
    import faulthandler
    from logging.handlers import RotatingFileHandler

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if sys.stderr is not None:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(fmt))
        root.addHandler(h)
    try:
        fh = RotatingFileHandler(os.path.join(log_dir(), "app.log"), maxBytes=2_000_000, backupCount=2,
                                 encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        root.addHandler(fh)
        global _crash_file
        _crash_file = open(os.path.join(log_dir(), "crash.log"), "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except Exception:
        pass
    logging.getLogger("OpenGL").setLevel(logging.WARNING)
    try:
        from cocseq.ui.panels.logs import install_log_handler

        install_log_handler()
    except Exception:
        pass


def _server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"COC_SEQ_Player-{user}"


def _send_to_running(paths: list[str]) -> bool:
    """Hand the files to an already running instance. True when one answered."""
    from PySide6.QtNetwork import QLocalSocket

    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(json.dumps({"open": paths}).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _start_server(window):
    from PySide6.QtNetwork import QLocalServer

    server = QLocalServer(window)
    QLocalServer.removeServer(_server_name())
    if not server.listen(_server_name()):
        return None

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            try:
                data = json.loads(bytes(conn.readAll()).decode("utf-8") or "{}")
            except ValueError:
                data = {}
            paths = [p for p in data.get("open", []) if p]
            if paths:
                window.open_paths(paths)
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()

        conn.readyRead.connect(read)

    server.newConnection.connect(on_connection)
    return server


_crash_file = None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--self-test" in argv:
        from cocseq import selftest

        i = argv.index("--self-test")
        out = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
        return selftest.run(out)
    software_gl = "--software-gl" in argv or os.environ.get("COCSEQ_SOFTWARE_GL") == "1"
    new_instance = "--new-instance" in argv
    paths = [os.path.abspath(a) for a in argv[1:] if not a.startswith("--")]

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("COC.SEQPlayer")
        except Exception:
            pass

    from PySide6.QtCore import QCoreApplication, Qt, QTimer
    from PySide6.QtGui import QGuiApplication, QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(1)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if software_gl:
        from cocseq.viewer.glsetup import use_software_gl

        use_software_gl()
        QCoreApplication.setAttribute(Qt.AA_UseSoftwareOpenGL)
    elif sys.platform == "win32":
        QCoreApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    from cocseq import APP_NAME, ORG_NAME, __version__

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    _setup_logging()

    from cocseq import icons, theme
    from cocseq.prefs import store

    st = store()
    theme.load_fonts()
    theme.set_accent(st.prefs.accent)
    theme.apply_theme(app)
    if hasattr(icons, "app_icon"):
        app.setWindowIcon(icons.app_icon())

    if st.prefs.single_instance and not new_instance and paths and _send_to_running(paths):
        return 0

    from cocseq.ui.main_window import MainWindow

    win = MainWindow(st, software_gl=software_gl)
    if st.prefs.single_instance:
        win._ipc_server = _start_server(win)
    if st.prefs.open_maximized:
        win.showMaximized()
    else:
        win.show()
    if paths:
        QTimer.singleShot(50, lambda: win.open_paths(paths))
    return app.exec()
