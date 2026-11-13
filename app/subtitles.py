"""Geração de legendas (ASS para queimar no vídeo, SRT para exportar)."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from highlights import Segment, Word


@dataclass
class SubStyle:
    max_words: int = 4
    max_chars: int = 28
    max_gap: float = 0.8
    uppercase: bool = False
    animated: bool = True        # destaca a palavra falada
    font_ratio: float = 0.055    # tamanho da fonte relativo à altura do vídeo
    margin_v_ratio: float = 0.08
    highlight: str = "&H0000E5FF&"  # amarelo (BGR)


STYLE_HORIZONTAL = SubStyle(max_words=6, max_chars=38, font_ratio=0.052, margin_v_ratio=0.07)
STYLE_VERTICAL = SubStyle(max_words=3, max_chars=20, uppercase=True, font_ratio=0.040, margin_v_ratio=0.24)


def clip_words(segments: list[Segment], start: float, end: float) -> list[Word]:
    """Palavras dentro do corte, com tempos relativos ao início do corte."""
    out: list[Word] = []
    for s in segments:
        if s.end < start - 0.5 or s.start > end + 0.5:
            continue
        words = s.words or _spread(s)
        for w in words:
            if w.start >= start - 0.05 and w.end <= end + 0.05 and w.text.strip():
                out.append(Word(max(0.0, w.start - start), max(0.0, w.end - start), w.text.strip()))
    return out


def _spread(s: Segment) -> list[Word]:
    toks = s.text.split()
    if not toks:
        return []
    step = (s.end - s.start) / len(toks)
    return [Word(s.start + k * step, s.start + (k + 1) * step, t) for k, t in enumerate(toks)]


def make_chunks(words: list[Word], style: SubStyle) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            too_long = len(cur) >= style.max_words or len(" ".join(x.text for x in cur) + " " + w.text) > style.max_chars
            gap = w.start - cur[-1].end
            ends_sentence = cur[-1].text.rstrip().endswith((".", "!", "?", "…"))
            if too_long or gap > style.max_gap or ends_sentence:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def _t_ass(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _t_srt(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _esc(text: str, upper: bool) -> str:
    t = text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")
    return t.upper() if upper else t


def build_ass(chunks: list[list[Word]], size: tuple[int, int], style: SubStyle, font_family: str) -> str:
    W, H = size
    fs = max(18, int(H * style.font_ratio))
    outline = max(2, int(fs * 0.09))
    mv = int(H * style.margin_v_ratio)
    mx = int(W * 0.05)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_family},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,"
        f"{outline},1,2,{mx},{mx},{mv},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines: list[str] = []
    for k, ch in enumerate(chunks):
        end_chunk = ch[-1].end + 0.15
        if k + 1 < len(chunks):
            end_chunk = min(end_chunk, chunks[k + 1][0].start)
        end_chunk = max(end_chunk, ch[0].start + 0.2)
        if not style.animated:
            text = _esc(" ".join(w.text for w in ch), style.uppercase)
            lines.append(f"Dialogue: 0,{_t_ass(ch[0].start)},{_t_ass(end_chunk)},Default,,0,0,0,,{text}")
            continue
        for i, w in enumerate(ch):
            ws = ch[0].start if i == 0 else w.start
            we = ch[i + 1].start if i + 1 < len(ch) else end_chunk
            if we <= ws:
                we = ws + 0.1
            parts = []
            for q, x in enumerate(ch):
                t = _esc(x.text, style.uppercase)
                parts.append(f"{{\\c{style.highlight}}}{t}{{\\c&HFFFFFF&}}" if q == i else t)
            lines.append(f"Dialogue: 0,{_t_ass(ws)},{_t_ass(we)},Default,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"


def build_srt(chunks: list[list[Word]]) -> str:
    out = []
    for n, ch in enumerate(chunks, 1):
        out.append(f"{n}\n{_t_srt(ch[0].start)} --> {_t_srt(ch[-1].end + 0.15)}\n{' '.join(w.text for w in ch)}\n")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Fonte: copia uma fonte do sistema para a pasta de trabalho, para o ffmpeg
# encontrá-la sem depender de configuração de fontes.
# --------------------------------------------------------------------------
_FONT_CANDIDATES = [
    ("arialbd.ttf", "Arial"),
    ("segoeuib.ttf", "Segoe UI"),
    ("calibrib.ttf", "Calibri"),
    ("verdanab.ttf", "Verdana"),
    ("DejaVuSans-Bold.ttf", "DejaVu Sans"),
]


def prepare_font(workdir: Path) -> tuple[str, bool]:
    """Retorna (família da fonte, se existe a pasta 'fonts' em workdir)."""
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/TTF")]
    for fname, family in _FONT_CANDIDATES:
        for d in dirs:
            p = d / fname
            if p.exists():
                fd = workdir / "fonts"
                fd.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, fd / fname)
                return family, True
    return "Arial", False
