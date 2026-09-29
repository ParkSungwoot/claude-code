# PyInstaller build for Windows:  pyinstaller --noconfirm "COC_SEQ Player.spec"
# Output: dist/COC_SEQ Player/COC_SEQ Player.exe (folder build: starts fast, ship the whole folder)

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

sys.path.insert(0, os.path.abspath("."))
from cocseq import __version__  # noqa: E402

APP = "COC_SEQ Player"

hidden = []
hidden += collect_submodules("OpenGL.platform")
hidden += collect_submodules("OpenGL.arrays")
hidden += ["OpenGL.GL", "OpenGL.converters", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvg",
           "PySide6.QtNetwork"]
hidden += collect_submodules("av")

binaries = []
binaries += collect_dynamic_libs("OpenImageIO")
binaries += collect_dynamic_libs("PyOpenColorIO")
binaries += collect_dynamic_libs("av")
binaries += collect_dynamic_libs("sounddevice")

datas = [("assets/fonts", "assets/fonts"), ("assets/icon.png", "assets"), ("assets/icon.ico", "assets")]
datas += collect_data_files("OpenImageIO")
datas += collect_data_files("PyOpenColorIO")
datas += collect_data_files("_sounddevice_data")

excludes = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtLocation",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets", "PySide6.QtHttpServer",
    "PySide6.QtGraphs", "matplotlib", "IPython", "pytest",
]


def _version_tuple(v):
    parts = [int(p) for p in v.split(".") if p.isdigit()][:4]
    return tuple(parts + [0] * (4 - len(parts)))


version_file = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    vt = _version_tuple(__version__)
    version_file = VSVersionInfo(
        ffi=FixedFileInfo(filevers=vt, prodvers=vt),
        kids=[
            StringFileInfo([StringTable("041204B0", [
                StringStruct("CompanyName", "COC"),
                StringStruct("FileDescription", "COC_SEQ Player - 이미지 시퀀스 리뷰 플레이어"),
                StringStruct("FileVersion", __version__),
                StringStruct("InternalName", APP),
                StringStruct("OriginalFilename", APP + ".exe"),
                StringStruct("ProductName", APP),
                StringStruct("ProductVersion", __version__),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0412, 1200])]),
        ],
    )

a = Analysis(
    ["run.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP,
    icon="assets/icon.ico",
    console=False,
    disable_windowed_traceback=False,
    version=version_file,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP)
