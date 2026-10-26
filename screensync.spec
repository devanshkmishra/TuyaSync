# -*- mode: python ; coding: utf-8 -*-

import os
import sys


assets_dir = os.path.join("screensync", "assets")
asset_files = (
    "tuyasync-app-icon.png",
    "tuyasync-menubar.png",
    "tuyasync-menubar-white.png",
    "TuyaSync.ico",
    "TuyaSync.icns",
)
platform_hiddenimports = []
# The interface only uses QtCore, QtGui, and QtWidgets. Leaving out the rest of
# Qt keeps the bundle tens of megabytes smaller.
qt_excludes = [
    "tkinter",
    *(
        f"PySide6.{module}"
        for module in (
            "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic", "Qt3DRender",
            "QtBluetooth", "QtCharts", "QtDataVisualization", "QtDesigner", "QtGraphs",
            "QtHelp", "QtLocation", "QtMultimedia", "QtMultimediaWidgets", "QtNetworkAuth",
            "QtNfc", "QtOpenGL", "QtOpenGLWidgets", "QtPdf", "QtPdfWidgets", "QtPositioning",
            "QtQml", "QtQuick", "QtQuick3D", "QtQuickControls2", "QtQuickWidgets",
            "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort",
            "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvgWidgets", "QtTest",
            "QtTextToSpeech", "QtUiTools", "QtWebChannel", "QtWebEngineCore",
            "QtWebEngineQuick", "QtWebEngineWidgets", "QtWebSockets", "QtXml",
        )
    ),
]
if sys.platform == "win32":
    platform_hiddenimports.extend(
        (
            "screensync.audio.windows",
            "screensync.now_playing.windows_media",
            "soundcard",
            "winrt.windows.media.control",
            "winrt.windows.storage.streams",
        )
    )


a = Analysis(
    [os.path.join("screensync", "ui.py")],
    pathex=[],
    binaries=[],
    datas=[(os.path.join(assets_dir, filename), assets_dir) for filename in asset_files],
    hiddenimports=platform_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=qt_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)


if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="TuyaSync",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=os.path.join(assets_dir, "TuyaSync.icns"),
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name="TuyaSync",
    )
    app = BUNDLE(
        collected,
        name="TuyaSync.app",
        icon=os.path.join(assets_dir, "TuyaSync.icns"),
        bundle_identifier="com.tuyasync.app",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="TuyaSync",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        # Compressing Qt's DLLs with UPX can corrupt them.
        upx_exclude=["Qt6*.dll", "qwindows.dll", "PySide6*.pyd", "shiboken6*.pyd", "shiboken6*.dll"],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=os.path.join(assets_dir, "TuyaSync.ico"),
    )
