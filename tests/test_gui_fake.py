"""Testa a lógica das janelas com um Tk de mentira.  python tests/test_gui_fake.py"""
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tests"))
import os  # noqa: E402

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="appdata_")

import fake_tk  # noqa: E402

tk = fake_tk.install()

import pipeline  # noqa: E402
import subtitles as subs  # noqa: E402

pipeline.make_preview_background = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem ffmpeg no teste"))
import main  # noqa: E402
import subdialog  # noqa: E402


def texts(c):
    return [i for i in c.tagged("sub") if i["kind"] == "text"]


def main_test():
    # ---------------- janela de legenda ----------------
    root = tk.Tk()
    dlg = subdialog.SubtitleDialog(root, {}, None, "Vertical 9:16 – recorte central")
    c = dlg.canvas
    fake_tk.flush()
    t0 = texts(c)
    # vertical + automático: MAIÚSCULAS, 3 palavras, uma delas em destaque
    assert t0, "a prévia inicial deve desenhar texto"
    assert any(i["fill"] == "#FFE500" for i in t0), "palavra em destaque ausente"
    base_y = [i for i in t0 if i["fill"] == "#FFE500"][0]["args"][1]
    assert abs(base_y - dlg.ch * (1 - 0.24)) < 1.5, base_y   # altura automática do vertical = 24%
    assert "ESSA" in [i["text"] for i in t0] or "ESSA É A".split()[0] in [i["text"] for i in t0]

    # mexer no slider de ALTURA tem que desligar o automático e mover o texto
    assert dlg.v_auto.get() is True
    dlg.v_pos.set(60)
    assert dlg.v_auto.get() is False, "slider de altura deve desligar o modo automático"
    fake_tk.flush()
    y = [i for i in texts(c) if i["fill"] == "#FFE500"][0]["args"][1]
    assert abs(y - dlg.ch * 0.40) < 1.5, y

    # tamanho
    size1 = [i for i in texts(c)][0]["font"].size
    dlg.v_scale.set(200)
    fake_tk.flush()
    size2 = [i for i in texts(c)][0]["font"].size
    assert abs(size2) >= abs(size1) * 1.9, (size1, size2)

    # alinhamento à esquerda
    dlg.v_halign.set("Esquerda")
    fake_tk.flush()
    xs = sorted({i["args"][0] for i in texts(c) if i["fill"] in ("#FFFFFF", "#FFE500")})
    assert abs(xs[0] - dlg.cw * 0.05) < 1.0, xs

    # cores
    dlg.v_text.set("#00FF00")
    dlg.v_high.set("#FF00FF")
    fake_tk.flush()
    fills = {i["fill"] for i in texts(c)}
    assert "#00FF00" in fills and "#FF00FF" in fills, fills

    # caixa: aparece retângulo e some o contorno (só 1 item de texto por palavra)
    dlg.v_box.set(True)
    fake_tk.flush()
    assert any(i["kind"] == "rect" for i in c.tagged("sub"))
    assert len(texts(c)) == 3, len(texts(c))
    dlg.v_box.set(False)
    fake_tk.flush()
    assert len(texts(c)) > 3  # contorno desenhado de novo

    # palavras por linha
    dlg.v_words.set("1")
    fake_tk.flush()
    assert len({i["text"] for i in texts(c) if i["fill"] != "#000000"}) == 1

    # preset clássico: sem animação -> nenhuma palavra em destaque
    dlg.v_words.set("Automático")
    dlg.v_preset.set("Clássica – branca com contorno")
    dlg._apply_preset()
    fake_tk.flush()
    assert dlg.v_anim.get() is False
    assert all(i["fill"] != "#FF00FF" for i in texts(c))

    # automático de volta + posições rápidas
    dlg.v_auto.set(True)
    dlg._auto_toggled()
    assert abs(dlg.v_pos.get() - 24) < 0.01 and dlg.v_auto.get()
    dlg._set_pos(82)
    assert dlg.v_auto.get() is False and dlg.v_pos.get() == 82

    # coleta e conclusão
    d = dlg._collect()
    st = subs.style_from_dict(d)
    assert st.pos_pct == 82 and st.halign == "left" and st.scale == 2.0
    dlg._ok()
    assert dlg.result == d and dlg._closed

    # formato horizontal: prévia 16:9, 6 palavras por linha
    dlg2 = subdialog.SubtitleDialog(root, {"pos_pct": 40}, None, "Original (horizontal)")
    fake_tk.flush()
    assert (dlg2.cw, dlg2.ch) == (520, 292)
    assert len(texts(dlg2.canvas)) >= 6
    assert dlg2.v_auto.get() is False and dlg2.v_pos.get() == 40
    dlg2._cancel()
    assert dlg2.result is None

    # ---------------- janela principal ----------------
    app = main.App(tk.Tk())
    app.v_source.set("https://www.youtube.com/watch?v=abc")
    assert any("Link colado" in str(i.get("text")) for i in app.drop.items)
    app.sub_style = d
    app.v_cpu.set("70")
    seen = {}

    def fake_run(opts, log=None, progress=None, cancel=None):
        seen["opts"] = opts
        log("ok")
        progress(1.0, "Pronto!")
        return [Path("/tmp/x/cortes/01.mp4")]

    pipeline.run = fake_run
    main.gpu.nvidia_gpu = lambda: None
    app._start()
    app.thread.join(timeout=5)
    app._poll()
    o = seen["opts"]
    assert o.cpu_limit == 70 and o.gpu == "auto" and o.sub_style == d and o.n_clips == 10
    assert (o.min_s, o.max_s) == (30, 60)

    # validações
    app.v_cpu.set("10")
    seen.clear()
    app._start()
    assert not seen, "limite de CPU inválido não deve iniciar"
    app.v_cpu.set("80")
    app.v_min.set("100"); app.v_max.set("50")
    app._start()
    assert not seen, "mínimo maior que máximo não deve iniciar"

    # preset de duração
    app.v_preset.set("Médio (2–3 min)")
    app._on_preset()
    assert (app.v_min.get(), app.v_max.get()) == ("120", "180")
    print("TESTES DA INTERFACE (lógica) PASSARAM")


if __name__ == "__main__":
    main_test()
