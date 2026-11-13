"""Tudo que toca ffmpeg/ffprobe e download por link (yt-dlp)."""
from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from pathlib import Path

from common import BELOW_NORMAL_PRIORITY, CREATE_NO_WINDOW, Cancelled, find_tool, try_find_tool

# Preenchido pelo pipeline: nº de threads e prioridade dos processos do ffmpeg
CONFIG = {"threads": os.cpu_count() or 4, "low_priority": False}


def _popen(cmd: list[str], cwd: str | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW | (BELOW_NORMAL_PRIORITY if CONFIG["low_priority"] else 0),
    )


def run_ffmpeg(args: list[str], cancel, cwd: str | None = None, duration: float | None = None, on_progress=None) -> None:
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = _popen(cmd, cwd)
    tail: deque[str] = deque(maxlen=40)
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled()
            line = line.strip()
            tail.append(line)
            if on_progress and duration and (line.startswith("out_time_us=") or line.startswith("out_time_ms=")):
                try:
                    secs = int(line.split("=", 1)[1]) / 1_000_000
                    on_progress(max(0.0, min(1.0, secs / duration)))
                except ValueError:
                    pass
        rc = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if cancel.is_set():
        raise Cancelled()
    if rc != 0:
        raise RuntimeError("O ffmpeg falhou:\n" + "\n".join(list(tail)[-15:]))


def probe(path: str | Path) -> dict:
    p = subprocess.run(
        [find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Não consegui ler o arquivo de vídeo:\n{p.stderr.strip()[-400:]}")
    data = json.loads(p.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if v is None:
        raise RuntimeError("Esse arquivo não tem imagem de vídeo.")
    dur = float(data["format"].get("duration") or v.get("duration") or 0)
    if dur <= 0:
        raise RuntimeError("Não consegui descobrir a duração do vídeo.")
    return {"duration": dur, "width": int(v["width"]), "height": int(v["height"])}


def extract_audio(src: str | Path, wav: str | Path, cancel, duration: float, on_progress=None) -> None:
    run_ffmpeg(
        ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
        cancel, duration=duration, on_progress=on_progress,
    )


# --------------------------------------------------------------------------
# Download por link
# --------------------------------------------------------------------------
def download(url: str, dest_dir: Path, quality: str, cookies_browser: str, on_progress, log, cancel) -> Path:
    import yt_dlp

    dest_dir.mkdir(parents=True, exist_ok=True)
    h = {"720p": 720, "1080p": 1080}.get(quality)
    fmt = f"bv*[height<={h}]+ba/b[height<={h}]/b" if h else "bv*+ba/b"

    def hook(d):
        if cancel.is_set():
            raise Cancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total), d.get("_percent_str", "").strip())

    opts: dict = {
        "outtmpl": str(dest_dir / "%(title).80B [%(id)s].%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [hook],
        "ffmpeg_location": str(Path(find_tool("ffmpeg")).parent),
    }
    deno = try_find_tool("deno")
    if deno:  # YouTube exige um runtime JS (desde 2025)
        os.environ["PATH"] = str(Path(deno).parent) + os.pathsep + os.environ.get("PATH", "")
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if cookies_browser and cookies_browser.lower() not in ("nenhum", "none", ""):
        opts["cookiesfrombrowser"] = (cookies_browser.lower(),)

    log("Baixando o vídeo do link...")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get("is_live"):
                raise RuntimeError("Essa transmissão ainda está ao vivo. Espere terminar para cortar.")
            rd = info.get("requested_downloads") or []
            path = Path(rd[0]["filepath"]) if rd and rd[0].get("filepath") else Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as e:
        if cancel.is_set():
            raise Cancelled()
        msg = str(e)
        if "Sign in" in msg or "bot" in msg.lower() or "cookies" in msg.lower():
            msg += "\n\nDica: escolha seu navegador em 'Cookies do navegador' (você precisa estar logado nele)."
        raise RuntimeError(msg)
    if not path.exists():
        mp4 = path.with_suffix(".mp4")
        if mp4.exists():
            path = mp4
        else:
            raise RuntimeError("O download terminou mas não achei o arquivo.")
    return path


# --------------------------------------------------------------------------
# Corte + legenda
# --------------------------------------------------------------------------
LAYOUTS = {
    "Original (horizontal)": "original",
    "Vertical 9:16 – recorte central": "vertical_crop",
    "Vertical 9:16 – fundo desfocado": "vertical_blur",
}


def output_size(layout: str, src_w: int, src_h: int) -> tuple[int, int]:
    if layout != "original":
        return 1080, 1920
    w, h = src_w, src_h
    if h > 1080:  # limita a 1080p para não ficar pesado
        w, h = round(src_w * 1080 / src_h), 1080
    return w - w % 2, h - h % 2


def video_filter_args(layout: str, src_size: tuple[int, int], with_subs: bool, fonts: bool, tail: str = "") -> list[str]:
    """Filtros de imagem do corte (formato + legenda). 'tail' é acrescentado no final (usado na prévia)."""
    ass = "ass=sub.ass" + (":fontsdir=fonts" if fonts else "")
    W, H = output_size(layout, *src_size)
    t = ("," + tail) if tail else ""
    if layout == "vertical_blur":
        fc = (
            "[0:v]split=2[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:3[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
            + ("," + ass if with_subs else "")
            + ",setsar=1" + t + "[out]"
        )
        return ["-filter_complex", fc, "-map", "[out]"]
    if layout == "vertical_crop":
        vf = ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920"]
    elif (W, H) != src_size:
        vf = [f"scale={W}:{H}"]
    else:
        vf = []
    if with_subs:
        vf.append(ass)
    vf.append("setsar=1")
    if tail:
        vf.append(tail)
    return ["-vf", ",".join(vf)]


def build_cut_args(src: str, start: float, dur: float, out: str, layout: str, src_size: tuple[int, int], with_subs: bool, fonts: bool, venc: list[str] | None = None) -> list[str]:
    args = ["-threads", str(CONFIG["threads"]), "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]
    args += video_filter_args(layout, src_size, with_subs, fonts)
    if layout == "vertical_blur":
        args += ["-map", "0:a:0?"]
    args += (venc or _x264())
    args += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", out]
    return args


def render_preview(video: str | None, layout: str, workdir: Path, png: str, fonts: bool, cancel) -> None:
    """Gera um quadro (PNG) com a legenda já queimada (sub.ass em workdir), usando o mesmo motor do corte."""
    if video:
        info = probe(video)
        src_size = (info["width"], info["height"])
        inp = ["-ss", f"{min(max(info['duration'] * 0.3, 0), 600):.2f}", "-i", video]
    else:
        src_size = (1920, 1080)
        inp = ["-f", "lavfi", "-i", "color=c=0x2b3a67:s=1920x1080:d=4:r=25"]
    vertical = layout != "original"
    tail = "scale=270:-2" if vertical else "scale=480:-2"
    args = [*inp, "-ss", "1.2", *video_filter_args(layout, src_size, True, fonts, tail), "-frames:v", "1", "-an", png]
    run_ffmpeg(args, cancel, cwd=str(workdir))


def _x264() -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", str(CONFIG["threads"])]


# Codificadores por placa de vídeo, em ordem de preferência
GPU_ENCODERS = [
    ("NVIDIA NVENC", ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0"]),
    ("Intel Quick Sync", ["-c:v", "h264_qsv", "-global_quality", "23", "-preset", "veryfast"]),
    ("AMD AMF", ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "22"]),
]
_enc = {"name": "Processador (x264)", "args": None, "gpu": False}


def _encoder_works(args: list[str]) -> bool:
    try:
        p = subprocess.run(
            [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi",
             "-i", "color=c=black:s=640x360:d=0.3:r=25", "-frames:v", "5", *args,
             "-pix_fmt", "yuv420p", "-f", "null", "-"],
            capture_output=True, timeout=25, creationflags=CREATE_NO_WINDOW,
        )
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def select_encoder(use_gpu: bool) -> str:
    """Escolhe o codificador (placa de vídeo se funcionar, senão processador). Retorna o nome."""
    _enc.update(name="Processador (x264)", args=None, gpu=False)
    if use_gpu:
        for name, args in GPU_ENCODERS:
            if _encoder_works(args):
                _enc.update(name=name, args=args, gpu=True)
                break
    return _enc["name"]


def cut_clip(src: str, start: float, dur: float, out: str, workdir: Path, layout: str, src_size: tuple[int, int], with_subs: bool, fonts: bool, cancel, on_progress=None, log=None) -> None:
    def attempt():
        args = build_cut_args(src, start, dur, out, layout, src_size, with_subs, fonts, _enc["args"])
        run_ffmpeg(args, cancel, cwd=str(workdir), duration=dur, on_progress=on_progress)

    try:
        attempt()
    except RuntimeError as e:
        if not _enc["gpu"]:
            raise
        if log:
            log(f"A placa de vídeo recusou a codificação ({_enc['name']}); voltando para o processador.")
        _enc.update(name="Processador (x264)", args=None, gpu=False)
        attempt()
