"""Detecção dos melhores momentos.

Combina três sinais, todos calculados localmente (grátis, sem internet):
  1. Energia do áudio (gritos, risadas, empolgação) em relação ao resto da live.
  2. Densidade de fala (trechos onde a conversa está acelerada).
  3. Expressões marcantes na transcrição ("meu deus", "não acredito", "wow"...),
     exclamações e risadas.
Depois testa todas as janelas que começam/terminam em limites naturais de frase
e escolhe as de maior pontuação, sem sobreposição.
"""
from __future__ import annotations

import math
import re
import wave
from dataclasses import dataclass, field

import numpy as np

from common import Cancelled, strip_accents


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Clip:
    start: float
    end: float
    score: float
    title: str
    reason: str
    text: str
    rank: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start


# --------------------------------------------------------------------------
# Léxico de empolgação (sem acentos, minúsculo). Pode ser ampliado à vontade.
# --------------------------------------------------------------------------
LEXICON = [
    # português
    "nossa", "caramba", "meu deus", "minha nossa", "nao acredito", "nao to acreditando",
    "socorro", "impossivel", "inacreditavel", "incrivel", "loucura", "que isso",
    "maluco", "mano do ceu", "gente", "olha isso", "olha so", "ganhei", "perdi",
    "acabou", "morri", "to chorando", "que porra", "puta que pariu", "bora", "vamo",
    "clutch", "gol", "gg", "ace", "pentakill", "boa", "eita", "uau", "aaa",
    # inglês
    "oh my god", "omg", "wow", "insane", "crazy", "no way", "lets go", "let's go",
    "holy", "what the", "unbelievable", "are you kidding", "oh no", "bro", "dude",
    "i cant believe", "are you serious", "clip that", "clip it", "poggers", "pog",
    # espanhol
    "dios mio", "increible", "no puede ser", "que locura", "vamos", "mierda",
    "no lo puedo creer", "madre mia", "joder",
]
_LEX_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(strip_accents(w)) for w in LEXICON) + r")(?![a-z0-9])"
)
_LAUGH_RE = re.compile(r"k{3,}|(?:ha){2,}|(?:he){2,}|(?:ah){2,}|rs{2,}|lol|lmao|kkk")


def keyword_hits(text: str) -> float:
    t = strip_accents(text).lower()
    hits = len(_LEX_RE.findall(t)) * 1.0
    hits += len(_LAUGH_RE.findall(t)) * 1.5
    hits += text.count("!") * 0.8
    hits += text.count("?") * 0.25
    return hits


# --------------------------------------------------------------------------
# Áudio
# --------------------------------------------------------------------------
def audio_energy_db(wav_path: str, cancel=None) -> np.ndarray:
    """Nível de áudio (dB) por segundo, lendo o WAV em blocos (baixo uso de RAM)."""
    with wave.open(wav_path, "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        if sw != 2:
            raise ValueError("WAV precisa ser 16-bit")
        total = int(math.ceil(n / sr))
        out = np.zeros(total, dtype=np.float32)
        i = 0
        chunk = sr * 60
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            raw = w.readframes(chunk)
            if not raw:
                break
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if ch > 1:
                a = a[: len(a) // ch * ch].reshape(-1, ch).mean(axis=1)
            secs = len(a) // sr
            if secs:
                body = a[: secs * sr].reshape(secs, sr)
                out[i : i + secs] = np.sqrt((body ** 2).mean(axis=1))
            rest = len(a) - secs * sr
            if rest > sr // 4:
                out[i + secs] = float(np.sqrt((a[secs * sr :] ** 2).mean()))
                secs += 1
            i += secs
    return 20.0 * np.log10(out + 1e-5)


# --------------------------------------------------------------------------
# Sinal de interesse por segundo
# --------------------------------------------------------------------------
def _smooth(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1 or len(x) == 0:
        return x
    return np.convolve(x, np.ones(k) / k, mode="same")


def _scale(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    lo, hi = np.percentile(x, [10, 98])
    return np.clip((x - lo) / (hi - lo + 1e-9), 0.0, 1.0)


@dataclass
class Interest:
    total: np.ndarray
    coverage: np.ndarray
    energy: np.ndarray
    speech: np.ndarray
    keywords: np.ndarray


def build_interest(n_seconds: int, energy_db: np.ndarray | None, segments: list[Segment]) -> Interest:
    n = max(1, int(n_seconds))
    # 1) energia
    if energy_db is not None and len(energy_db) > 0:
        e = np.full(n, float(np.min(energy_db)), dtype=np.float64)
        m = min(n, len(energy_db))
        e[:m] = energy_db[:m]
        energy = _scale(_smooth(e, 3))
    else:
        energy = np.zeros(n)
    # 2) densidade de fala e cobertura
    wcount = np.zeros(n)
    cover = np.zeros(n)
    kw = np.zeros(n)
    for s in segments:
        a = min(n - 1, max(0, int(s.start)))
        b = min(n, max(a + 1, int(math.ceil(s.end))))
        cover[a:b] = 1.0
        words = s.words or []
        if words:
            for w in words:
                wcount[min(n - 1, max(0, int(w.start)))] += 1
        else:
            wcount[a:b] += max(1, len(s.text.split())) / (b - a)
        kw[a:b] += keyword_hits(s.text) / (b - a)
    speech = _scale(_smooth(wcount, 6))
    kws = _smooth(kw, 8)
    pos = kws[kws > 0]
    ref = float(np.percentile(pos, 90)) if len(pos) else 1.0
    kws = np.clip(kws / (ref + 1e-9), 0.0, 1.0)

    if energy_db is not None and len(energy_db) > 0:
        total = 0.45 * energy + 0.25 * speech + 0.30 * kws
    else:
        total = 0.5 * speech + 0.5 * kws
    return Interest(total, _smooth(cover, 5), energy, speech, kws)


# --------------------------------------------------------------------------
# Escolha dos trechos
# --------------------------------------------------------------------------
_SENT_END = re.compile(r"[.!?…]['\")\]]*\s*$")


def _natural_end(segs: list[Segment], j: int) -> bool:
    if j + 1 >= len(segs):
        return True
    if _SENT_END.search(segs[j].text.strip()):
        return True
    return segs[j + 1].start - segs[j].end >= 0.6


def _title(text: str, n: int = 7) -> str:
    words = re.sub(r"[^\w\s'-]", "", text, flags=re.UNICODE).split()
    return " ".join(words[:n])


def find_clips(
    segments: list[Segment],
    interest: Interest,
    total_duration: float,
    n_clips: int,
    min_s: float,
    max_s: float,
    min_gap: float = 3.0,
) -> list[Clip]:
    segs = [s for s in segments if s.end > s.start and s.text.strip()]
    if not segs or n_clips <= 0:
        return []
    min_s = max(5.0, float(min_s))
    max_s = max(min_s, float(max_s))
    # deixa folga para o respiro de início/fim (0,25 s + 0,5 s)
    limit = max_s - 0.8 if max_s - 0.8 >= min_s else max_s

    I = interest.total
    P = np.concatenate([[0.0], np.cumsum(I)])
    C = np.concatenate([[0.0], np.cumsum(interest.coverage)])
    sm8 = _smooth(I, 8)
    N = len(I)

    def score(s: float, e: float) -> tuple[float, float]:
        a = min(N - 1, max(0, int(s)))
        b = min(N, max(a + 1, int(math.ceil(e))))
        mean = (P[b] - P[a]) / (b - a)
        cov = (C[b] - C[a]) / (b - a)
        peak = float(sm8[a:b].max())
        hook = float(I[a : min(b, a + 6)].mean())
        sc = 0.55 * mean + 0.30 * peak + 0.15 * hook
        sc *= min(1.0, cov / 0.5)
        sc += 0.03 * ((e - s) / max_s)
        return sc, cov

    cands: list[Clip] = []
    for i, si in enumerate(segs):
        found = False
        last_valid = None
        for j in range(i, len(segs)):
            sj = segs[j]
            dur = sj.end - si.start
            if dur > limit:
                break
            if dur < min_s:
                continue
            last_valid = j
            if _natural_end(segs, j):
                found = True
                cands.append(_make(segs, i, j, score))
        if not found and last_valid is not None:
            cands.append(_make(segs, i, last_valid, score))

    cands = [c for c in cands if c.score > 0]
    cands.sort(key=lambda c: -c.score)

    chosen: list[Clip] = []
    for c in cands:
        s = max(0.0, c.start)
        e = min(total_duration, c.end) if total_duration > 0 else c.end
        c.start, c.end = s, e
        if all(e + min_gap <= x.start or s >= x.end + min_gap for x in chosen):
            chosen.append(c)
            if len(chosen) >= n_clips:
                break

    for r, c in enumerate(chosen, 1):
        c.rank = r
        _explain(c, interest)
    chosen.sort(key=lambda c: c.start)
    return chosen


def _make(segs: list[Segment], i: int, j: int, score_fn) -> Clip:
    first, last = segs[i], segs[j]
    s = first.words[0].start if first.words else first.start
    e = last.words[-1].end if last.words else last.end
    s, e = s - 0.25, e + 0.5
    sc, _ = score_fn(first.start, last.end)
    text = " ".join(x.text.strip() for x in segs[i : j + 1])
    return Clip(start=s, end=e, score=float(sc), title=_title(first.text) or "corte", reason="", text=text)


def _explain(c: Clip, it: Interest) -> None:
    a = max(0, int(c.start))
    b = min(len(it.total), max(a + 1, int(math.ceil(c.end))))
    parts = {
        "áudio empolgado": (it.energy[a:b].mean(), it.energy.mean() + 1e-6),
        "fala intensa": (it.speech[a:b].mean(), it.speech.mean() + 1e-6),
        "expressões marcantes": (it.keywords[a:b].mean(), it.keywords.mean() + 1e-6),
    }
    c.reason = max(parts.items(), key=lambda kv: kv[1][0] / kv[1][1])[0]
