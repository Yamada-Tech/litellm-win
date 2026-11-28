# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

launcher_dir = os.path.dirname(os.path.abspath(SPEC))

launcher_datas, launcher_binaries, launcher_hidden = collect_all("pystray")
launcher_datas += collect_all("PIL")[0]

datas = launcher_datas
binaries = launcher_binaries
hiddenimports = launcher_hidden + ["pystray._win32"]

a = Analysis(
    ["litellm_tray.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(launcher_dir, "utf8_runtime_hook.py")],
    excludes=[
        "torch", "tensorflow", "matplotlib", "pandas", "scipy",
        "pytest", "mutmut", "mypy", "ruff", "black", "isort",
    ],
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
    name="LiteLLMTray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
