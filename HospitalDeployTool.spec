# -*- mode: python ; coding: utf-8 -*-
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs


PROJECT_ROOT = Path.cwd()

ICON_FILE = str(PROJECT_ROOT / "hospital_deploy_tool" / "app_icon.ico")

hiddenimports = []
hiddenimports += collect_submodules("paramiko")
hiddenimports += collect_submodules("bcrypt")
hiddenimports += collect_submodules("nacl")

# ---------- 只收集必要的 PySide2 DLL ----------
# 白名单策略：仅保留 QtCore/Gui/Widgets + 必要运行时，进一步缩小体积
_ALLOWED_PYSIDE2_DLLS = {
    "pyside2.abi3.dll",
    "Qt5Core.dll",
    "Qt5Gui.dll",
    "Qt5Widgets.dll",
    "Qt5Network.dll",
    "d3dcompiler_47.dll",
    "libEGL.dll",
    "libGLESv2.dll",
    "concrt140.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_codecvt_ids.dll",
    "ucrtbase.dll",
    "vcomp140.dll",
    "vccorlib140.dll",
    "vcamp140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}

pyside2_binaries = [
    (src, dst) for src, dst in collect_dynamic_libs("PySide2")
    if Path(src).name in _ALLOWED_PYSIDE2_DLLS
]
pyside2_binaries += collect_dynamic_libs("shiboken2")

# 只收集 platforms 和 styles 插件（窗口必需），进一步只保留必要文件
import PySide2
_pyside2_dir = Path(PySide2.__file__).parent
_plugins_dir = _pyside2_dir / "plugins"
_NEEDED_PLUGIN_FILES = {
    "platforms": {"qwindows.dll"},
    "styles": {"qwindowsvistastyle.dll"},
}
pyside2_datas = []
if _plugins_dir.exists():
    for subdir in _plugins_dir.iterdir():
        if subdir.is_dir() and subdir.name in _NEEDED_PLUGIN_FILES:
            for f in subdir.iterdir():
                if f.is_file() and f.name in _NEEDED_PLUGIN_FILES[subdir.name]:
                    dst = str(Path("PySide2") / "plugins" / subdir.name)
                    pyside2_datas.append((str(f), dst))

# ---------- 排除不需要的 PySide2 Python 子模块 ----------
_EXCLUDE_QT_MODULES = [
    "PySide2.QtWebEngine", "PySide2.QtWebEngineCore", "PySide2.QtWebEngineWidgets",
    "PySide2.QtWebChannel", "PySide2.QtQuick", "PySide2.QtQml",
    "PySide2.QtMultimedia", "PySide2.QtMultimediaWidgets",
    "PySide2.Qt3DCore", "PySide2.Qt3DRender", "PySide2.Qt3DInput",
    "PySide2.QtSensors", "PySide2.QtBluetooth", "PySide2.QtNfc",
    "PySide2.QtPositioning", "PySide2.QtLocation", "PySide2.QtSerialPort",
    "PySide2.QtPdf", "PySide2.QtPdfWidgets", "PySide2.QtCharts",
    "PySide2.QtDataVisualization", "PySide2.QtVirtualKeyboard",
    "PySide2.QtRemoteObjects", "PySide2.QtSql", "PySide2.QtTest",
    "PySide2.QtDesigner", "PySide2.QtHelp", "PySide2.QtSvg",
    "PySide2.QtSvgWidgets", "PySide2.QtXml", "PySide2.QtNetwork",
    "PySide2.QtOpenGL", "PySide2.QtOpenGLWidgets",
    "PySide2.QtDBus", "PySide2.QtConcurrent",
]

a = Analysis(
    ["launch.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=pyside2_binaries,
    datas=[
        (str(PROJECT_ROOT / "README.md"), "."),
        (ICON_FILE, "hospital_deploy_tool"),
    ] + pyside2_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDE_QT_MODULES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HospitalDeployTool",
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
    icon=ICON_FILE,
)
