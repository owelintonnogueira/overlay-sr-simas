"""Aceleração por placa de vídeo NVIDIA (CUDA) para a transcrição.

O faster-whisper precisa das bibliotecas cuBLAS e cuDNN 9 (CUDA 12). Elas não vêm no instalador
(são ~600 MB); se o PC tiver placa NVIDIA, o programa baixa uma vez só, com a sua permissão,
da página de bibliotecas do projeto whisper-standalone-win, e guarda em %APPDATA%\\CortesLive\\cuda.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from common import CREATE_NO_WINDOW, IS_WIN, Cancelled, data_dir

LIBS_API = "https://api.github.com/repos/Purfview/whisper-standalone-win/releases/tags/libs"
LIBS_PAGE = "https://github.com/Purfview/whisper-standalone-win/releases/tag/libs"
NEEDED = ("cublas64_12.dll", "cublaslt64_12.dll", "cudnn64_9.dll")

_dll_handles: list = []


def nvidia_gpu() -> dict | None:
    """{'name': ..., 'vram_mb': ...} se houver placa NVIDIA com driver instalado; senão None."""
    exes = ["nvidia-smi"]
    if IS_WIN:
        exes += [
            str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "nvidia-smi.exe"),
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]
    for exe in exes:
        try:
            p = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0 and p.stdout.strip():
            first = p.stdout.strip().splitlines()[0]
            name, _, mem = first.rpartition(",")
            try:
                return {"name": name.strip(), "vram_mb": int(mem.strip())}
            except ValueError:
                return {"name": first.strip(), "vram_mb": 0}
    return None


def cuda_dir() -> Path:
    return data_dir() / "cuda"


def _have_libs(d: Path) -> bool:
    if not d.exists():
        return False
    names = {p.name.lower() for p in d.glob("*.dll")}
    return all(n in names for n in NEEDED)


def libs_ready() -> bool:
    if _have_libs(cuda_dir()):
        return True
    return bool(shutil.which("cublas64_12.dll") and shutil.which("cudnn64_9.dll"))


def activate() -> None:
    d = cuda_dir()
    if d.exists():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            _dll_handles.append(os.add_dll_directory(str(d)))


def pick_asset(assets: list[dict]) -> dict | None:
    """Escolhe o .zip de bibliotecas para Windows + CUDA 12 (a versão mais nova)."""
    ok = [
        a for a in assets
        if a.get("name", "").lower().endswith(".zip")
        and "cuda12" in a["name"].lower()
        and "win" in a["name"].lower()
    ]
    return sorted(ok, key=lambda a: a["name"], reverse=True)[0] if ok else None


def download_libs(log, progress, cancel) -> None:
    hdr = {"User-Agent": "CortesLive", "Accept": "application/vnd.github+json"}
    with urllib.request.urlopen(urllib.request.Request(LIBS_API, headers=hdr), timeout=30) as r:
        release = json.load(r)
    asset = pick_asset(release.get("assets", []))
    if not asset:
        raise RuntimeError(f"Não achei o pacote de bibliotecas CUDA 12. Veja {LIBS_PAGE}")
    d = cuda_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "_download.zip"
    total = int(asset.get("size") or 0)
    log(f"Baixando bibliotecas da placa de vídeo ({total / 1e6:.0f} MB, só desta vez)...")
    done = 0
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "CortesLive"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            if cancel.is_set():
                f.close()
                tmp.unlink(missing_ok=True)
                raise Cancelled()
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                progress(min(1.0, done / total))
    with zipfile.ZipFile(tmp) as z:
        for info in z.infolist():
            if info.filename.lower().endswith(".dll"):
                with z.open(info) as src, open(d / Path(info.filename).name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    tmp.unlink(missing_ok=True)
    if not _have_libs(d):
        raise RuntimeError("O pacote baixado não tem as bibliotecas esperadas (cuBLAS / cuDNN 9).")
    log("Bibliotecas da placa de vídeo instaladas.")
