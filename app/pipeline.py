"""Orquestra tudo: baixar → áudio → transcrever → achar melhores trechos → cortar com legenda."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import highlights as hl
import media
import subtitles as subs
from common import Cancelled, fmt_clock, fmt_hms, safe_name, slugify

LANGUAGES = {
    "Automático": None, "Português": "pt", "English": "en", "Español": "es",
    "Français": "fr", "Deutsch": "de", "Italiano": "it", "日本語": "ja",
}
MODELS = {
    "tiny – muito rápido, precisão básica": "tiny",
    "base – rápido, boa para começar": "base",
    "small – equilibrado (recomendado)": "small",
    "medium – mais preciso, bem mais lento": "medium",
}


@dataclass
class Options:
    source: str
    out_dir: str
    n_clips: int = 10
    min_s: float = 30
    max_s: float = 60
    model: str = "small"
    language: str | None = None
    layout: str = "vertical_blur"
    subtitles: bool = True
    animated: bool = True
    save_srt: bool = False
    quality: str = "1080p"
    cookies_browser: str = "Nenhum"
    device: str = "auto"


def _noop(*a, **k):
    pass


# --------------------------------------------------------------------------
# Transcrição (faster-whisper, 100% local)
# --------------------------------------------------------------------------
def transcribe(wav: str, model_name: str, language: str | None, device_pref: str, duration: float, log, progress, cancel):
    from faster_whisper import WhisperModel

    attempts = []
    if device_pref in ("auto", "gpu"):
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                attempts.append(("cuda", "float16"))
        except Exception:
            pass
    attempts.append(("cpu", "int8"))

    for dev, ctype in attempts:
        try:
            log(f"Carregando o modelo de voz '{model_name}' ({'placa de vídeo' if dev == 'cuda' else 'processador'})... "
                "Na primeira vez ele é baixado da internet (uma vez só).")
            model = WhisperModel(model_name, device=dev, compute_type=ctype, cpu_threads=os.cpu_count() or 4)
            seg_iter, info = model.transcribe(
                wav,
                language=language,
                beam_size=1,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 600},
                condition_on_previous_text=False,
            )
            log(f"Transcrevendo (idioma: {info.language})...")
            out: list[hl.Segment] = []
            for s in seg_iter:
                if cancel.is_set():
                    raise Cancelled()
                words = [hl.Word(float(w.start), float(w.end), w.word.strip()) for w in (s.words or []) if w.word.strip()]
                out.append(hl.Segment(float(s.start), float(s.end), s.text.strip(), words))
                progress(min(1.0, s.end / duration))
            return out
        except Cancelled:
            raise
        except Exception as e:  # noqa: BLE001
            if dev == "cpu":
                raise
            log(f"Placa de vídeo não utilizável ({e}). Usando o processador.")
    raise RuntimeError("Falha na transcrição")


def _seg_to_json(segs: list[hl.Segment]) -> list[dict]:
    return [
        {"s": s.start, "e": s.end, "t": s.text, "w": [[w.start, w.end, w.text] for w in s.words]}
        for s in segs
    ]


def _seg_from_json(data: list[dict]) -> list[hl.Segment]:
    return [
        hl.Segment(d["s"], d["e"], d["t"], [hl.Word(a, b, c) for a, b, c in d["w"]])
        for d in data
    ]


# --------------------------------------------------------------------------
# Pipeline principal
# --------------------------------------------------------------------------
def run(opts: Options, log=_noop, progress=_noop, cancel=None) -> list[Path]:
    """progress(frac_0_a_1, mensagem). Retorna a lista de arquivos gerados."""
    import threading

    cancel = cancel or threading.Event()
    t0 = time.time()
    src = opts.source.strip().strip('"')
    if not src:
        raise ValueError("Escolha um vídeo ou cole um link.")
    out_root = Path(opts.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) fonte do vídeo ------------------------------------------------------
    if re.match(r"https?://", src, re.I):
        progress(0.0, "Baixando o vídeo...")
        video = media.download(
            src, out_root / "_baixados", opts.quality, opts.cookies_browser,
            on_progress=lambda f, txt: progress(0.15 * f, f"Baixando o vídeo... {txt}"),
            log=log, cancel=cancel,
        )
    else:
        video = Path(src)
        if not video.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {video}")
    progress(0.15, "Lendo o vídeo...")
    info = media.probe(video)
    duration = info["duration"]
    log(f"Vídeo: {video.name} — duração {fmt_clock(duration)}, {info['width']}x{info['height']}")

    folder = out_root / safe_name(video.stem)
    cache = folder / "_cache"
    work = folder / "_work"
    cache.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    # 2) transcrição + energia (com cache para reaproveitar em novas execuções)
    st = video.stat()
    key = hashlib.sha1(f"{video.resolve()}|{st.st_size}|{int(st.st_mtime)}|{opts.model}|{opts.language}".encode()).hexdigest()[:16]
    f_tr, f_en = cache / f"transcricao_{key}.json", cache / f"energia_{key}.npy"
    if f_tr.exists() and f_en.exists():
        log("Reaproveitando a transcrição desta mesma live (já analisada antes).")
        segments = _seg_from_json(json.loads(f_tr.read_text(encoding="utf-8")))
        energy = np.load(f_en)
        progress(0.70, "Transcrição reaproveitada")
    else:
        wav = cache / "audio.wav"
        progress(0.15, "Extraindo o áudio...")
        media.extract_audio(video, wav, cancel, duration, on_progress=lambda f: progress(0.15 + 0.05 * f, "Extraindo o áudio..."))
        log("Analisando volume do áudio...")
        energy = hl.audio_energy_db(str(wav), cancel)
        segments = transcribe(
            str(wav), opts.model, opts.language, opts.device, duration, log,
            lambda f: progress(0.20 + 0.50 * f, f"Transcrevendo a fala... {int(f * 100)}%"), cancel,
        )
        wav.unlink(missing_ok=True)
        f_tr.write_text(json.dumps(_seg_to_json(segments), ensure_ascii=False), encoding="utf-8")
        np.save(f_en, energy)
    if not segments:
        raise RuntimeError("Não encontrei fala nesse vídeo, então não tenho como escolher trechos.")

    # 3) melhores trechos ----------------------------------------------------
    progress(0.70, "Escolhendo os melhores momentos...")
    interest = hl.build_interest(int(duration) + 1, energy, segments)
    clips = hl.find_clips(segments, interest, duration, opts.n_clips, opts.min_s, opts.max_s)
    if not clips:
        raise RuntimeError(
            "Não achei trechos com essa duração. Tente aumentar a duração máxima ou diminuir a mínima."
        )
    if len(clips) < opts.n_clips:
        log(f"Só encontrei {len(clips)} trechos bons e distintos (você pediu {opts.n_clips}).")
    else:
        log(f"Escolhi {len(clips)} trechos.")

    # 4) corte + legenda -----------------------------------------------------
    clips_dir = folder / "cortes"
    clips_dir.mkdir(exist_ok=True)
    layout = media.LAYOUTS.get(opts.layout, opts.layout)
    vertical = layout != "original"
    style = subs.SubStyle(**vars(subs.STYLE_VERTICAL if vertical else subs.STYLE_HORIZONTAL))
    style.animated = opts.animated
    out_size = media.output_size(layout, info["width"], info["height"])
    font_family, has_fonts = subs.prepare_font(work)

    produced: list[tuple[hl.Clip, Path]] = []
    by_rank = sorted(clips, key=lambda c: c.rank)
    for k, c in enumerate(by_rank, 1):
        base = 0.72 + 0.28 * (k - 1) / len(by_rank)
        span = 0.28 / len(by_rank)
        progress(base, f"Cortando {k}/{len(by_rank)}...")
        name = f"{c.rank:02d}_{slugify(c.title, 30)}_{fmt_hms(c.start)}.mp4"
        out = clips_dir / name
        words = subs.clip_words(segments, c.start, c.end)
        chunks = subs.make_chunks(words, style)
        with_subs = opts.subtitles and bool(chunks)
        if with_subs:
            (work / "sub.ass").write_text(subs.build_ass(chunks, out_size, style, font_family), encoding="utf-8")
        if opts.save_srt and chunks:
            (clips_dir / (out.stem + ".srt")).write_text(subs.build_srt(chunks), encoding="utf-8")
        media.cut_clip(
            str(video), c.start, c.duration, str(out), work, layout, (info["width"], info["height"]),
            with_subs, has_fonts, cancel,
            on_progress=lambda f, b=base, s=span, k=k: progress(b + s * f, f"Cortando {k}/{len(by_rank)}..."),
        )
        produced.append((c, out))
        log(f"✔ {name}  ({fmt_clock(c.start)} → {fmt_clock(c.end)}, {c.reason})")

    _write_summary(folder / "resumo_cortes.txt", video, produced)
    shutil.rmtree(work, ignore_errors=True)
    progress(1.0, "Pronto!")
    log(f"Concluído em {int(time.time() - t0)}s. Cortes em: {clips_dir}")
    return [p for _, p in produced]


def _write_summary(path: Path, video: Path, produced: list[tuple[hl.Clip, Path]]) -> None:
    lines = [f"Cortes de: {video.name}", ""]
    for c, p in produced:
        lines += [
            f"#{c.rank:02d}  {p.name}",
            f"    trecho: {fmt_clock(c.start)} → {fmt_clock(c.end)}  ({int(c.duration)}s)",
            f"    motivo: {c.reason}  |  pontuação: {c.score:.2f}",
            f"    fala: {c.text[:160]}{'…' if len(c.text) > 160 else ''}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
