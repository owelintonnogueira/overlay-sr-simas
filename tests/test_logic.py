"""Teste de ponta a ponta SEM Whisper/internet: vídeo sintético + transcrição falsa.

Rode:  python tests/test_logic.py
"""
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import highlights as hl  # noqa: E402
import media  # noqa: E402
import pipeline  # noqa: E402
import subtitles as subs  # noqa: E402

DUR = 240
HOT = [(60, 85), (150, 175)]  # trechos "empolgantes" plantados


def make_media(tmp: Path) -> Path:
    sr = 16000
    rng = np.random.default_rng(1)
    t = np.arange(DUR * sr) / sr
    audio = 0.02 * rng.standard_normal(len(t))
    for a, b in HOT:
        m = (t >= a) & (t < b)
        audio[m] = 0.45 * np.sin(2 * np.pi * 440 * t[m]) + 0.1 * rng.standard_normal(m.sum())
    wav = tmp / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    vid = tmp / "live_teste.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=25:duration={DUR}",
         "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(vid)],
        check=True,
    )
    return vid


def fake_segments():
    segs = []
    t = 0.0
    k = 0
    while t < DUR - 6:
        hot = any(a <= t < b for a, b in HOT)
        n = 14 if hot else 6
        text = "Meu deus, não acredito nisso, que loucura, gente!" if hot else "então é isso aí vamos seguir com calma"
        words = text.split()[:n]
        dur = 4.6
        step = dur / len(words)
        ws = [hl.Word(t + i * step, t + (i + 1) * step - 0.05, w) for i, w in enumerate(words)]
        segs.append(hl.Segment(t, t + dur, " ".join(words), ws))
        t += 5.0
        k += 1
    return segs


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cortes_test_"))
    print("tmp:", tmp)
    vid = make_media(tmp)
    segs = fake_segments()

    # ---- 1) escolha de trechos -------------------------------------------------
    wav = tmp / "a.wav"
    energy = hl.audio_energy_db(str(wav))
    assert abs(len(energy) - DUR) <= 1, len(energy)
    it = hl.build_interest(DUR + 1, energy, segs)
    clips = hl.find_clips(segs, it, DUR, 2, 20, 40)
    print("clips:", [(round(c.start), round(c.end), round(c.score, 2), c.reason) for c in clips])
    assert len(clips) == 2
    for c in clips:
        assert 20 <= c.duration <= 41, c.duration
        assert any(a - 5 <= c.start and c.end <= b + 5 for a, b in HOT), (c.start, c.end)
    assert clips[0].end <= clips[1].start  # sem sobreposição
    many = hl.find_clips(segs, it, DUR, 50, 20, 40)
    print("pediu 50 ->", len(many))
    assert 3 <= len(many) < 50
    for x, y in zip(many, many[1:]):
        assert x.end <= y.start
    assert hl.find_clips(segs, it, DUR, 5, 500, 600) == []  # duração impossível

    # ---- 2) legendas ---------------------------------------------------------
    words = subs.clip_words(segs, 60, 90)
    assert words and words[0].start >= 0
    ch = subs.make_chunks(words, subs.STYLE_VERTICAL)
    assert all(len(c) <= 3 for c in ch)
    ass = subs.build_ass(ch, (1080, 1920), subs.STYLE_VERTICAL, "Arial")
    assert "Dialogue:" in ass and "PlayResX: 1080" in ass
    assert "00:00:00,000" in subs.build_srt(ch)

    # ---- 3) pipeline completo nos 3 formatos (transcrição simulada) --------------
    pipeline.transcribe = lambda *a, **k: segs  # type: ignore[assignment]
    for layout, size in [("Original (horizontal)", (1280, 720)),
                         ("Vertical 9:16 – recorte central", (1080, 1920)),
                         ("Vertical 9:16 – fundo desfocado", (1080, 1920))]:
        opts = pipeline.Options(source=str(vid), out_dir=str(tmp / "saida"), n_clips=2, min_s=20, max_s=40,
                                layout=layout, save_srt=True, model="fake" + layout[:3])
        logs = []
        files = pipeline.run(opts, log=logs.append, progress=lambda f, m: None, cancel=threading.Event())
        assert len(files) == 2, files
        for f in files:
            info = media.probe(f)
            print(layout, f.name, info)
            assert (info["width"], info["height"]) == size, info
            assert 19 <= info["duration"] <= 41.5, info
            assert f.with_suffix(".srt").exists()
        frame = tmp / f"frame_{layout[:12].replace(' ', '_')}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "3", "-i", str(files[0]), "-frames:v", "1", str(frame)], check=True)
        print("frame:", frame)

    # cache: segunda execução reaproveita a transcrição
    opts.n_clips = 3
    logs = []
    pipeline.transcribe = lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria transcrever de novo"))  # type: ignore
    files = pipeline.run(opts, log=logs.append, progress=lambda f, m: None, cancel=threading.Event())
    assert any("Reaproveitando" in l for l in logs)

    # cancelamento
    ev = threading.Event(); ev.set()
    try:
        opts.model = "outro"
        pipeline.run(opts, cancel=ev)
        raise SystemExit("deveria cancelar")
    except Exception as e:  # noqa: BLE001
        assert e.__class__.__name__ == "Cancelled", repr(e)
    print("\nTODOS OS TESTES PASSARAM")


if __name__ == "__main__":
    main()
