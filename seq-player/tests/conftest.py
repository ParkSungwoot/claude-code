import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    import make_test_media

    out = tmp_path_factory.mktemp("media")
    paths = make_test_media.make_all(str(out))
    paths["root"] = str(out)
    return paths


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication.instance() or QApplication(["tests"])
    from cocseq import theme

    theme.load_fonts()
    theme.apply_theme(app)
    yield app


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """Keep QSettings (preferences) of tests away from the user's real ones."""
    from PySide6.QtCore import QSettings

    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    import cocseq.prefs as prefs_mod

    monkeypatch.setattr(prefs_mod, "_store", None)
    yield tmp_path
