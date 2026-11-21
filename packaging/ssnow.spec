# -*- mode: python -*-
# Build with: packaging/build_appimage.sh (run from the repo root).
# NOTE: keep paths relative to this file so the spec works on any machine.

import os

# SPECPATH is provided by PyInstaller: the directory containing this spec.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "scripts", "ssnow_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "ssnow_core", "data"), "ssnow_core/data"),
    ],
    hiddenimports=["ssnow_core", "ssnow_core.sources", "ssnow_desktop", "ssnow_desktop.views"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ssnow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
)
