# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: gera dist/CortesLive/CortesLive.exe (modo "pasta", abre rápido e dá menos alarme falso de antivírus)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ["faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers",
            "huggingface_hub", "tkinterdnd2", "yt_dlp", "yt_dlp_ejs", "certifi"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:  # pacote opcional ausente
        print(f"[spec] aviso: {pkg}: {e}")

# ffmpeg.exe, ffprobe.exe, deno.exe (baixados pelo setup_env.ps1)
datas += [("vendor", "vendor")]

a = Analysis(
    ["app/main.py"],
    pathex=["app"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "tensorflow", "matplotlib", "scipy", "pandas", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CortesLive",
    console=False,
    upx=False,
    icon="assets/icon.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CortesLive")
