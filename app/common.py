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
