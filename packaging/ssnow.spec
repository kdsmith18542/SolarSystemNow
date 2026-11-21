# -*- mode: python -*-

import sys

a = Analysis(
    ["/media/keith/Data2/ss-now/scripts/ssnow_gui.py"],
    pathex=["/media/keith/Data2/ss-now"],
    binaries=[],
    datas=[],
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
