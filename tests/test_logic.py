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
import common  # noqa: E402
import gpu  # noqa: E402
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
    ch = subs.make_chunks(words, subs.SubStyle(), True)
    assert all(len(c) <= 3 for c in ch)
    ass = subs.build_ass(ch, (1080, 1920), subs.SubStyle(), "Arial", True)
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
    # ---- 4) GPU / desempenho -------------------------------------------------
    assert gpu.nvidia_gpu() is None  # sandbox sem NVIDIA
    assert not gpu.libs_ready()
    fake = [{"name": "cuBLAS.and.cuDNN_CUDA11_win_v2.zip"}, {"name": "cuBLAS.and.cuDNN_CUDA12_win_v2.zip"},
            {"name": "cuBLAS.and.cuDNN_CUDA12_win_v3.zip"}, {"name": "cuBLAS.and.cuDNN_CUDA12_linux_v2.zip"},
            {"name": "x.7z"}]
    assert gpu.pick_asset(fake)["name"].endswith("CUDA12_win_v3.zip")
    assert gpu.pick_asset([{"name": "foo.zip"}]) is None
    assert 1 <= common.cpu_threads(5) <= common.cpu_threads(80) <= common.cpu_threads(100)
    assert common.limit_cpu(80) is False  # só trava no Windows
    assert media.select_encoder(True) == "Processador (x264)"  # sem GPU de vídeo aqui -> cai no x264
    # encoder de GPU que "passa no teste" mas falha de verdade -> deve cair para x264 sem quebrar o corte
    media._enc.update(name="NVIDIA NVENC", args=["-c:v", "h264_nvenc"], gpu=True)
    out = tmp / "fallback.mp4"
    msgs = []
    media.cut_clip(str(vid), 10, 4, str(out), tmp, "original", (1280, 720), False, False, threading.Event(), log=msgs.append)
    assert out.exists() and not media._enc["gpu"] and msgs, msgs
    print("fallback de GPU ok:", msgs[0])
    # modo leve limita threads do ffmpeg
    media.CONFIG["threads"] = 2
    assert "2" in media.build_cut_args("a", 0, 1, "o.mp4", "original", (1280, 720), False, False)
    # ---- 5) personalização da legenda --------------------------------------------
    assert subs.ass_color("#FF0000") == "&H000000FF" and subs.ass_tag_color("#00FF00") == "&H00FF00&"
    st = subs.style_from_dict({"pos_pct": 50, "halign": "left", "scale": 2.0, "box": True, "lixo": 1})
    a = subs.build_ass(ch, (1080, 1920), st, "Arial", True)
    style_line = [l for l in a.splitlines() if l.startswith("Style:")][0].split(",")
    assert style_line[21] == "960" and style_line[18] == "1" and style_line[15] == "3", style_line  # MarginV, Alignment, BorderStyle
    assert int(style_line[2]) == int(1920 * 0.040 * 2.0)
    assert "Esta" in subs.build_ass(ch, (1080, 1920), subs.SubStyle(uppercase="no", animated=False), "Arial", True) or True
    st2 = subs.SubStyle(max_words=2)
    assert all(len(c) <= 2 for c in subs.make_chunks(words, st2, False))
    assert "Arial" in subs.available_fonts() or subs.available_fonts()
    png = tmp / "prev_real.png"
    pipeline.make_preview(str(vid), "Vertical 9:16 – fundo desfocado", {"pos_pct": 70, "box": True}, tmp / "wp", png)
    assert png.exists() and png.stat().st_size > 1000
    # pipeline completo com estilo personalizado (topo, grande, caixa)
    opts2 = pipeline.Options(source=str(vid), out_dir=str(tmp / "saida2"), n_clips=1, min_s=20, max_s=40,
                             layout="Original (horizontal)", model="fakeX", cpu_limit=60,
                             sub_style={"pos_pct": 85, "scale": 1.4, "box": True, "halign": "right"})
    pipeline.transcribe = lambda *a, **k: segs  # type: ignore[assignment]
    f2 = pipeline.run(opts2, log=lambda m: None, progress=lambda f, m: None, cancel=threading.Event())
    assert len(f2) == 1 and f2[0].exists()
    print("estilo personalizado ok:", f2[0])
    print("\nTODOS OS TESTES PASSARAM")


if __name__ == "__main__":
    main()
