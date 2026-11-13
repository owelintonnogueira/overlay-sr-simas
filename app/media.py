"""Tudo que toca ffmpeg/ffprobe e download por link (yt-dlp)."""
from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from pathlib import Path

from common import CREATE_NO_WINDOW, Cancelled, find_tool, try_find_tool


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
        creationflags=CREATE_NO_WINDOW,
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


def build_cut_args(src: str, start: float, dur: float, out: str, layout: str, src_size: tuple[int, int], with_subs: bool, fonts: bool) -> list[str]:
    ass = "ass=sub.ass" + (":fontsdir=fonts" if fonts else "")
    W, H = output_size(layout, *src_size)
    args = ["-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}"]
    if layout == "vertical_blur":
        fc = (
            "[0:v]split=2[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:3[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
            + ("," + ass if with_subs else "")
            + ",setsar=1[out]"
        )
        args += ["-filter_complex", fc, "-map", "[out]", "-map", "0:a:0?"]
    else:
        if layout == "vertical_crop":
            vf = ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920"]
        elif (W, H) != src_size:
            vf = [f"scale={W}:{H}"]
        else:
            vf = []
        if with_subs:
            vf.append(ass)
        vf.append("setsar=1")
        args += ["-vf", ",".join(vf)]
    args += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-movflags", "+faststart", out,
    ]
    return args


def cut_clip(src: str, start: float, dur: float, out: str, workdir: Path, layout: str, src_size: tuple[int, int], with_subs: bool, fonts: bool, cancel, on_progress=None) -> None:
    args = build_cut_args(src, start, dur, out, layout, src_size, with_subs, fonts)
    run_ffmpeg(args, cancel, cwd=str(workdir), duration=dur, on_progress=on_progress)
