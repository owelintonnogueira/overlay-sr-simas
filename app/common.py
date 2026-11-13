"""Utilitários comuns: caminhos, ferramentas externas (ffmpeg/deno), formatação."""
from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0
BELOW_NORMAL_PRIORITY = 0x00004000 if IS_WIN else 0



def cpu_threads(limit_pct: float) -> int:
    """Quantidade de threads proporcional ao limite de uso (ex.: 80% de 8 núcleos = 6)."""
    n = os.cpu_count() or 4
    return max(1, int(n * max(5.0, min(100.0, float(limit_pct))) / 100.0))


_job = {"handle": None}


def limit_cpu(limit_pct: float) -> bool:
    """Windows: coloca o programa (e os ffmpeg filhos) num Job Object com TETO de CPU.

    O Windows garante que o conjunto todo não passa de limit_pct% do processador, qualquer que seja
    o nº de threads. Retorna True se a trava foi aplicada.
    """
    if not IS_WIN:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k.SetInformationJobObject.restype = wintypes.BOOL
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.GetCurrentProcess.restype = wintypes.HANDLE

        class CPU_RATE(ctypes.Structure):
            _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]

        rate = int(max(5.0, min(100.0, float(limit_pct))) * 100)  # unidades de 1/100 de %
        info = CPU_RATE(0x1 | 0x4, rate)  # ENABLE | HARD_CAP
        fresh = _job["handle"] is None
        if fresh:
            _job["handle"] = k.CreateJobObjectW(None, None)
            if not _job["handle"]:
                return False
        if not k.SetInformationJobObject(_job["handle"], 15, ctypes.byref(info), ctypes.sizeof(info)):
            return False
        if fresh and not k.AssignProcessToJobObject(_job["handle"], k.GetCurrentProcess()):
            _job["handle"] = None
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


class Cancelled(Exception):
    """Lançada quando o usuário cancela o processamento."""


def base_dir() -> Path:
    """Raiz do app (pasta do projeto, ou a pasta _internal do PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def find_tool(name: str) -> str:
    """Localiza ffmpeg/ffprobe/deno: primeiro em vendor/, depois no PATH."""
    exe = name + (".exe" if IS_WIN else "")
    for d in (base_dir() / "vendor", Path(sys.executable).parent / "vendor"):
        p = d / exe
        if p.exists():
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"Não encontrei '{name}'. Reinstale o programa (ele já vem com o {name})."
    )


def try_find_tool(name: str) -> str | None:
    try:
        return find_tool(name)
    except FileNotFoundError:
        return None


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "CortesLive"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_output_dir() -> Path:
    vids = Path.home() / "Videos"
    return (vids if vids.exists() else Path.home()) / "CortesLive"


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def slugify(text: str, maxlen: int = 40) -> str:
    s = strip_accents(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:maxlen].strip("-")) or "corte"


def safe_name(text: str, maxlen: int = 60) -> str:
    """Nome de pasta seguro para Windows, mantendo acentos."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:maxlen].strip(" .")) or "video"


def fmt_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}h{(s % 3600) // 60:02d}m{s % 60:02d}s"


def fmt_clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
