"""Janela "Personalizar legenda" com prévia ao vivo (renderizada pelo mesmo ffmpeg do corte final)."""
from __future__ import annotations

import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, ttk

import pipeline
import subtitles as subs

HALIGN = {"Esquerda": "left", "Centro": "center", "Direita": "right"}
UPPER = {"Automática": "auto", "Sempre MAIÚSCULAS": "yes", "Normal": "no"}
POS_QUICK = {"Embaixo": 8, "Terço inferior": 24, "Meio": 45, "Topo": 82}


def _key(d: dict, value):
    return next((k for k, v in d.items() if v == value), next(iter(d)))


class SubtitleDialog(tk.Toplevel):
    """Use: dlg = SubtitleDialog(root, style_dict, video_path_or_None, layout_label, theme); root.wait_window(dlg); dlg.result"""

    def __init__(self, parent, style: dict | None, video: str | None, layout_label: str, theme: dict):
        super().__init__(parent)
        self.result: dict | None = None
        self.video, self.layout_label, self.th = video, layout_label, theme
        self.title("Personalizar legenda")
        self.configure(bg=theme["bg"])
        self.transient(parent)
        self.q: queue.Queue = queue.Queue()
        self.seq = 0
        self.after_id = None
        self.tmp = Path(tempfile.mkdtemp(prefix="cortes_prev_"))
        self._img = None

        st = subs.style_from_dict(style)
        self.v_preset = tk.StringVar(value="Personalizada")
        self.v_font = tk.StringVar(value=st.font if st.font in subs.available_fonts() else subs.available_fonts()[0])
        self.v_scale = tk.DoubleVar(value=round(st.scale * 100))
        self.v_auto = tk.BooleanVar(value=st.pos_pct < 0)
        self.v_pos = tk.DoubleVar(value=24 if st.pos_pct < 0 else st.pos_pct)
        self.v_halign = tk.StringVar(value=_key(HALIGN, st.halign))
        self.v_text = tk.StringVar(value=st.text_color)
        self.v_high = tk.StringVar(value=st.highlight_color)
        self.v_out = tk.StringVar(value=st.outline_color)
        self.v_outw = tk.DoubleVar(value=round(st.outline_scale * 100))
        self.v_box = tk.BooleanVar(value=st.box)
        self.v_anim = tk.BooleanVar(value=st.animated)
        self.v_upper = tk.StringVar(value=_key(UPPER, st.uppercase))
        self.v_words = tk.StringVar(value="Automático" if st.max_words <= 0 else str(st.max_words))
        self.lbl = {}

        self._build()
        for v in (self.v_font, self.v_scale, self.v_auto, self.v_pos, self.v_halign, self.v_text, self.v_high,
                  self.v_out, self.v_outw, self.v_box, self.v_anim, self.v_upper, self.v_words):
            v.trace_add("write", lambda *a: self._schedule())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(150, self._poll)
        self._schedule(0)
        self.grab_set()
        self.focus_set()

    # ------------------------------------------------------------------ UI
    def _build(self):
        th = self.th
        left = ttk.Frame(self, padding=14)
        left.grid(row=0, column=0, sticky="ns")
        right = ttk.Frame(self, padding=14)
        right.grid(row=0, column=1, sticky="n")
        r = 0

        def row(label, widget):
            nonlocal r
            ttk.Label(left, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="ew", pady=4)
            r += 1

        cb = ttk.Combobox(left, textvariable=self.v_preset, values=list(subs.PRESETS), state="readonly", width=34)
        cb.bind("<<ComboboxSelected>>", self._apply_preset)
        row("Estilo pronto", cb)
        row("Fonte", ttk.Combobox(left, textvariable=self.v_font, values=subs.available_fonts(), state="readonly", width=34))
        row("Tamanho", self._slider(left, self.v_scale, 40, 250, "%"))
        row("Alinhamento", ttk.Combobox(left, textvariable=self.v_halign, values=list(HALIGN), state="readonly", width=34))

        ttk.Checkbutton(left, text="Posição automática (recomendado para cada formato)", variable=self.v_auto).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1
        row("Altura (0% = base, 100% = topo)", self._slider(left, self.v_pos, 3, 92, "%"))
        quick = ttk.Frame(left)
        for name, val in POS_QUICK.items():
            ttk.Button(quick, text=name, command=lambda v=val: self._set_pos(v)).pack(side="left", padx=(0, 6))
        row("Posições rápidas", quick)

        row("Cor do texto", self._color_btn(left, self.v_text))
        row("Cor da palavra em destaque", self._color_btn(left, self.v_high))
        row("Cor do contorno / caixa", self._color_btn(left, self.v_out))
        row("Espessura do contorno", self._slider(left, self.v_outw, 0, 250, "%"))
        row("Palavras por linha", ttk.Combobox(left, textvariable=self.v_words, values=["Automático", "1", "2", "3", "4", "5", "6", "8"], state="readonly", width=34))
        row("Maiúsculas", ttk.Combobox(left, textvariable=self.v_upper, values=list(UPPER), state="readonly", width=34))
        ttk.Checkbutton(left, text="Destacar a palavra que está sendo falada", variable=self.v_anim).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1
        ttk.Checkbutton(left, text="Fundo escuro atrás do texto (caixa)", variable=self.v_box).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        btns = ttk.Frame(left)
        btns.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Button(btns, text="Restaurar padrão", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="Usar esta legenda", style="Accent.TButton", command=self._ok).pack(side="right", padx=(0, 8))

        self.preview = tk.Label(right, bg=th["card"], fg=th["muted"], text="Gerando prévia...", width=44, height=22)
        self.preview.pack()
        src = "do seu vídeo" if self.video else "de exemplo"
        ttk.Label(right, text=f"Prévia com quadro {src} • {self.layout_label}", style="Muted.TLabel", wraplength=320).pack(pady=(8, 0))

    def _slider(self, parent, var, lo, hi, unit):
        f = ttk.Frame(parent)
        s = ttk.Scale(f, from_=lo, to=hi, variable=var, orient="horizontal", length=210)
        s.pack(side="left")
        lab = ttk.Label(f, width=6, text=f"{int(var.get())}{unit}")
        lab.pack(side="left", padx=(8, 0))
        var.trace_add("write", lambda *a, v=var, l=lab, u=unit: l.configure(text=f"{int(v.get())}{u}"))
        return f

    def _color_btn(self, parent, var: tk.StringVar):
        b = tk.Button(parent, text="      ", bg=var.get(), activebackground=var.get(), relief="flat", width=10,
                      command=lambda: self._pick(var, b))
        var.trace_add("write", lambda *a, v=var, bb=b: bb.configure(bg=v.get(), activebackground=v.get()))
        return b

    def _pick(self, var, btn):
        c = colorchooser.askcolor(color=var.get(), parent=self, title="Escolha a cor")
        if c and c[1]:
            var.set(c[1].upper())

    # ------------------------------------------------------------ ações
    def _set_pos(self, val):
        self.v_auto.set(False)
        self.v_pos.set(val)

    def _apply_preset(self, _=None):
        p = subs.PRESETS.get(self.v_preset.get())
        if not p:
            return
        self.v_anim.set(p["animated"])
        self.v_box.set(p["box"])
        self.v_text.set(p["text_color"])
        self.v_high.set(p["highlight_color"])
        self.v_out.set(p["outline_color"])
        self.v_outw.set(round(p["outline_scale"] * 100))

    def _reset(self):
        d = subs.SubStyle()
        self.v_font.set(d.font if d.font in subs.available_fonts() else subs.available_fonts()[0])
        self.v_scale.set(100)
        self.v_auto.set(True)
        self.v_halign.set(_key(HALIGN, d.halign))
        self.v_upper.set(_key(UPPER, d.uppercase))
        self.v_words.set("Automático")
        self.v_preset.set(next(iter(subs.PRESETS)))
        self._apply_preset()

    def _collect(self) -> dict:
        w = self.v_words.get()
        return dict(
            font=self.v_font.get(),
            scale=round(self.v_scale.get() / 100, 2),
            pos_pct=-1.0 if self.v_auto.get() else round(self.v_pos.get(), 1),
            halign=HALIGN[self.v_halign.get()],
            text_color=self.v_text.get(),
            highlight_color=self.v_high.get(),
            outline_color=self.v_out.get(),
            outline_scale=round(self.v_outw.get() / 100, 2),
            box=bool(self.v_box.get()),
            animated=bool(self.v_anim.get()),
            uppercase=UPPER[self.v_upper.get()],
            max_words=0 if w == "Automático" else int(w),
        )

    def _ok(self):
        self.result = self._collect()
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        if self.after_id:
            self.after_cancel(self.after_id)
        self.destroy()

    # ------------------------------------------------------------ prévia
    def _schedule(self, delay=450):
        if self.after_id:
            self.after_cancel(self.after_id)
        self.after_id = self.after(delay, self._render)

    def _render(self):
        self.after_id = None
        self.seq += 1
        seq, style = self.seq, self._collect()
        png = self.tmp / f"prev_{seq}.png"

        def work():
            try:
                pipeline.make_preview(self.video, self.layout_label, style, self.tmp / "w", png)
                self.q.put(("img", seq, str(png)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", seq, str(e)[-200:]))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, seq, data = self.q.get_nowait()
                if seq != self.seq:
                    continue
                if kind == "img":
                    self._img = tk.PhotoImage(file=data)
                    self.preview.configure(image=self._img, text="", width=self._img.width(), height=self._img.height())
                else:
                    self.preview.configure(image="", text="Não consegui gerar a prévia:\n" + data, width=44, height=22)
        except queue.Empty:
            pass
        except tk.TclError:
            return  # janela fechada
        try:
            self.after(150, self._poll)
        except tk.TclError:
            pass
