# PyInstaller spec for Knocknock.
#
# Build a single-file, windowed executable:
#
#     .venv\Scripts\pyinstaller.exe packaging\knocknock.spec --noconfirm
#
# The result is dist\Knocknock.exe. config.json is generated next to the
# executable on first run, so the app stays portable.

from pathlib import Path

# __file__ is not defined when PyInstaller executes this spec.
PROJECT_ROOT = Path(SPECPATH).resolve().parent
ICON_PATH = PROJECT_ROOT / "packaging" / "knocknock.ico"

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    # config.example.json is read at runtime as the template. Ship it inside the
    # bundle so a fresh executable still gets sensible defaults; the user's own
    # config.json is written next to the executable instead.
    datas=[(str(PROJECT_ROOT / "config.example.json"), ".")],
    hiddenimports=[
        # Qt submodules that are imported lazily or only referenced by name.
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim the Qt build down to what this app actually uses.
    excludes=[
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "tkinter",
        "unittest",
        "pydoc_data",
        "setuptools",
        "pip",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Knocknock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window: this is a tray application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)
