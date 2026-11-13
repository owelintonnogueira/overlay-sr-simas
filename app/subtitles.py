"""Geração de legendas (ASS para queimar no vídeo, SRT para exportar), totalmente personalizável."""
from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from highlights import Segment, Word


@dataclass
class SubStyle:
    font: str = "Arial"
    scale: float = 1.0              # multiplica o tamanho padrão do formato (1.0 = 100%)
    pos_pct: float = -1.0           # altura da legenda: % da tela a partir da base; -1 = automático
    halign: str = "center"          # left | center | right
    text_color: str = "#FFFFFF"
    highlight_color: str = "#FFE500"
    outline_color: str = "#000000"
    outline_scale: float = 1.0      # espessura do contorno (1.0 = padrão)
    box: bool = False               # fundo escuro atrás do texto
    animated: bool = True           # destaca a palavra que está sendo falada
    uppercase: str = "auto"         # auto | yes | no
    max_words: int = 0              # palavras por linha; 0 = automático


PRESETS: dict[str, dict] = {
    "Dinâmica – palavra falada em destaque": dict(animated=True, box=False, text_color="#FFFFFF", highlight_color="#FFE500", outline_color="#000000", outline_scale=1.0),
    "Clássica – branca com contorno": dict(animated=False, box=False, text_color="#FFFFFF", highlight_color="#FFFFFF", outline_color="#000000", outline_scale=1.0),
    "Caixa escura (estilo TV)": dict(animated=False, box=True, text_color="#FFFFFF", highlight_color="#FFFFFF", outline_color="#000000", outline_scale=1.0),
    "Amarela (estilo cinema)": dict(animated=False, box=False, text_color="#FFE500", highlight_color="#FFE500", outline_color="#000000", outline_scale=1.0),
    "Neon – ciano com destaque rosa": dict(animated=True, box=False, text_color="#00F0FF", highlight_color="#FF2E9A", outline_color="#101020", outline_scale=1.2),
}


def style_from_dict(d: dict | None) -> SubStyle:
    names = {f.name for f in fields(SubStyle)}
    return SubStyle(**{k: v for k, v in (d or {}).items() if k in names})


def style_to_dict(s: SubStyle) -> dict:
    return asdict(s)


# Padrões por formato: (horizontal, vertical)
_LAYOUT = {
    False: dict(font_ratio=0.052, pos=7.0, max_words=6, upper=False),
    True: dict(font_ratio=0.040, pos=24.0, max_words=3, upper=True),
}


def params(style: SubStyle, vertical: bool) -> dict:
    d = _LAYOUT[vertical]
    mw = style.max_words if style.max_words > 0 else d["max_words"]
    upper = d["upper"] if style.uppercase == "auto" else style.uppercase == "yes"
    return dict(
        font_ratio=d["font_ratio"] * max(0.2, style.scale),
        pos_pct=d["pos"] if style.pos_pct < 0 else style.pos_pct,
        max_words=mw,
        max_chars=max(14, mw * 9),
        upper=upper,
    )


# --------------------------------------------------------------------------
# Palavras / linhas
# --------------------------------------------------------------------------
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


def make_chunks(words: list[Word], style: SubStyle, vertical: bool, max_gap: float = 0.8) -> list[list[Word]]:
    p = params(style, vertical)
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            too_long = len(cur) >= p["max_words"] or len(" ".join(x.text for x in cur) + " " + w.text) > p["max_chars"]
            gap = w.start - cur[-1].end
            ends_sentence = cur[-1].text.rstrip().endswith((".", "!", "?", "…"))
            if too_long or gap > max_gap or ends_sentence:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


# --------------------------------------------------------------------------
# Formatos de saída
# --------------------------------------------------------------------------
def _t_ass(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _t_srt(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 255, 255, 255


def ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b = _rgb(hex_color)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_tag_color(hex_color: str) -> str:
    r, g, b = _rgb(hex_color)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _esc(text: str, upper: bool) -> str:
    t = text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")
    return t.upper() if upper else t


_ALIGN = {"left": 1, "center": 2, "right": 3}


def build_ass(chunks: list[list[Word]], size: tuple[int, int], style: SubStyle, font_family: str, vertical: bool) -> str:
    W, H = size
    p = params(style, vertical)
    fs = max(14, int(H * p["font_ratio"]))
    mv = int(H * min(95.0, max(0.0, p["pos_pct"])) / 100.0)
    mx = int(W * 0.05)
    if style.box:
        border_style, outline = 3, max(4, int(fs * 0.22))
        outline_colour = ass_color(style.outline_color, alpha=0x50)  # caixa semitransparente
        shadow = 0
    else:
        border_style, outline = 1, max(0, int(round(fs * 0.09 * style.outline_scale)))
        outline_colour = ass_color(style.outline_color)
        shadow = 1 if style.outline_scale > 0 else 0
    align = _ALIGN.get(style.halign, 2)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_family},{fs},{ass_color(style.text_color)},&H000000FF,{outline_colour},&H64000000,"
        f"-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{align},{mx},{mx},{mv},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    hi, base = ass_tag_color(style.highlight_color), ass_tag_color(style.text_color)
    lines: list[str] = []
    for k, ch in enumerate(chunks):
        end_chunk = ch[-1].end + 0.15
        if k + 1 < len(chunks):
            end_chunk = min(end_chunk, chunks[k + 1][0].start)
        end_chunk = max(end_chunk, ch[0].start + 0.2)
        if not style.animated:
            text = _esc(" ".join(w.text for w in ch), p["upper"])
            lines.append(f"Dialogue: 0,{_t_ass(ch[0].start)},{_t_ass(end_chunk)},Default,,0,0,0,,{text}")
            continue
        for i, w in enumerate(ch):
            ws = ch[0].start if i == 0 else w.start
            we = ch[i + 1].start if i + 1 < len(ch) else end_chunk
            if we <= ws:
                we = ws + 0.1
            parts = []
            for q, x in enumerate(ch):
                t = _esc(x.text, p["upper"])
                parts.append(f"{{\\c{hi}}}{t}{{\\c{base}}}" if q == i else t)
            lines.append(f"Dialogue: 0,{_t_ass(ws)},{_t_ass(we)},Default,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"


def build_srt(chunks: list[list[Word]]) -> str:
    out = []
    for n, ch in enumerate(chunks, 1):
        out.append(f"{n}\n{_t_srt(ch[0].start)} --> {_t_srt(ch[-1].end + 0.15)}\n{' '.join(w.text for w in ch)}\n")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Fontes: copia a fonte escolhida para a pasta de trabalho, para o ffmpeg achá-la
# sem depender da configuração de fontes do sistema.
# --------------------------------------------------------------------------
FONTS: dict[str, str] = {
    "Arial": "arialbd.ttf",
    "Arial Black": "ariblk.ttf",
    "Impact": "impact.ttf",
    "Segoe UI": "segoeuib.ttf",
    "Verdana": "verdanab.ttf",
    "Calibri": "calibrib.ttf",
    "Trebuchet MS": "trebucbd.ttf",
    "Tahoma": "tahomabd.ttf",
    "Georgia": "georgiab.ttf",
    "Comic Sans MS": "comicbd.ttf",
    "Bahnschrift": "bahnschrift.ttf",
    "DejaVu Sans": "DejaVuSans-Bold.ttf",  # Linux (testes)
}


def _font_dirs() -> list[Path]:
    return [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts",
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/TTF"),
    ]


def _find_font_file(fname: str) -> Path | None:
    for d in _font_dirs():
        p = d / fname
        if p.exists():
            return p
    return None


def available_fonts() -> list[str]:
    found = [fam for fam, f in FONTS.items() if _find_font_file(f)]
    return found or ["Arial"]


def prepare_font(workdir: Path, family: str) -> tuple[str, bool]:
    """Retorna (família realmente usada, se existe a pasta 'fonts' em workdir)."""
    order = [family] + [f for f in FONTS if f != family]
    for fam in order:
        src = _find_font_file(FONTS.get(fam, ""))
        if src:
            fd = workdir / "fonts"
            fd.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, fd / src.name)
            return fam, True
    return "Arial", False
