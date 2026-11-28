# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# site-packages の editable install が別チェックアウトを指していても、このリポジトリの
# litellm を同梱させる
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(SPEC))))

litellm_datas, litellm_binaries, litellm_hidden = collect_all("litellm")
extras_datas, extras_binaries, extras_hidden = collect_all("litellm_proxy_extras")
enterprise_datas, enterprise_binaries, enterprise_hidden = collect_all("litellm_enterprise")
tiktoken_ext_datas, tiktoken_ext_binaries, tiktoken_ext_hidden = collect_all("tiktoken_ext")

EXCLUDED_DATAS = ("tests", "goldens", "fixtures", "__pycache__", ".git", "docs")
EXCLUDED_EXTS = (".md", ".txt", ".jsonl", ".lock", ".bak")

def _keep_data(src, dst):
    normalized = src.replace("\\", "/")
    segments = normalized.split("/")
    if any(part in segments for part in EXCLUDED_DATAS):
        return False
    if src.lower().endswith(EXCLUDED_EXTS):
        return False
    return True

datas = [(s, d) for s, d in litellm_datas + extras_datas + enterprise_datas + tiktoken_ext_datas if _keep_data(s, d)]
binaries = litellm_binaries + extras_binaries + enterprise_binaries + tiktoken_ext_binaries
hiddenimports = (
    litellm_hidden
    + extras_hidden
    + enterprise_hidden
    + tiktoken_ext_hidden
    + collect_submodules("litellm")
    + ["pystray._win32", "tiktoken_ext.openai_public"]
)

a = Analysis(
    ["litellm_tray.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(os.path.dirname(os.path.abspath(SPEC)), "utf8_runtime_hook.py")],
    excludes=[
        "torch", "tensorflow", "matplotlib", "pandas", "scipy",
        "polars", "soundfile", "ldap3", "gunicorn", "granian", "uvloop",
        "azure.identity", "azure.storage.blob", "boto3", "pyroscope",
        "grpc", "grpcio",
        "onnxruntime", "librosa", "soundfile", "pytest", "mutmut", "mypy",
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
