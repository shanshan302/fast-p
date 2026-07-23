# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


PROJECT_ROOT = Path(SPECPATH)
RUNTIME_ROOT = Path(os.environ["FAST_P_BUILD_RUNTIME"]).resolve()
VERSION_FILE = os.environ.get("FAST_P_VERSION_FILE") or None

if not RUNTIME_ROOT.is_dir():
    raise SystemExit(f"bundled runtime does not exist: {RUNTIME_ROOT}")

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=playwright_binaries,
    datas=[
        *playwright_datas,
        (str(RUNTIME_ROOT), "runtime"),
    ],
    hiddenimports=[
        *playwright_hiddenimports,
        "playwright.sync_api",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fast-P",
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
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Fast-P",
)
