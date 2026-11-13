"""Janela "Personalizar legenda".

A prévia ao vivo é desenhada na hora (sem esperar o ffmpeg) a cada mudança nos controles.
O botão "Conferir com o motor final" mostra o quadro exato, renderizado pelo mesmo ffmpeg do corte.
"""
from __future__ import annotations

import math
import queue
import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, ttk
from tkinter import font as tkfont

import media
import pipeline
import subtitles as subs
import theme as T

HALIGN = {"Esquerda": "left", "Centro": "center", "Direita": "right"}
UPPER = {"Automática": "auto", "Sempre MAIÚSCULAS": "yes", "Normal": "no"}
POS_QUICK = {"Embaixo": 8, "Terço inferior": 24, "Meio": 45, "Topo": 82}
AUTO_POS = {False: 7, True: 24}  # altura automática (horizontal / vertical), só para mostrar no slider


def _key(d: dict, value):
    return next((k for k, v in d.items() if v == value), next(iter(d)))


def _mix(hex_a: str, rgb_b: tuple[int, int, int], t: float) -> str:
    h = hex_a.lstrip("#")
    try:
        a = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        a = (0, 0, 0)
    return "#%02x%02x%02x" % tuple(int(a[i] * t + rgb_b[i] * (1 - t)) for i in range(3))


class SubtitleDialog(tk.Toplevel):
    """dlg = SubtitleDialog(root, style_dict, video_path_or_None, layout_label); root.wait_window(dlg); dlg.result"""

    def __init__(self, parent, style: dict | None, video: str | None, layout_label: str):
        super().__init__(parent)
        self.result: dict | None = None
        self.video, self.layout_label = video, layout_label
        self.vertical = media.LAYOUTS.get(layout_label, layout_label) != "original"
        self.cw, self.ch = (290, 516) if self.vertical else (520, 292)
        self.title("Personalizar legenda")
        self.configure(bg=T.CARD)
        self.transient(parent)
        self.resizable(False, False)
        self.q: queue.Queue = queue.Queue()
        self.tmp = Path(tempfile.mkdtemp(prefix="cortes_prev_"))
        self._fonts: dict = {}
        self._bg_img = None
        self._exact_img = None
        self._pending = False
        self._busy = False
        self._seq = 0
        self._closed = False

        st = subs.style_from_dict(style)
        fonts = subs.available_fonts()
        self.v_preset = tk.StringVar(value="Personalizada")
        self.v_font = tk.StringVar(value=st.font if st.font in fonts else fonts[0])
        self.v_scale = tk.DoubleVar(value=round(st.scale * 100))
        self.v_auto = tk.BooleanVar(value=st.pos_pct < 0)
        self.v_pos = tk.DoubleVar(value=AUTO_POS[self.vertical] if st.pos_pct < 0 else st.pos_pct)
        self.v_halign = tk.StringVar(value=_key(HALIGN, st.halign))
        self.v_text = tk.StringVar(value=st.text_color)
        self.v_high = tk.StringVar(value=st.highlight_color)
        self.v_out = tk.StringVar(value=st.outline_color)
        self.v_outw = tk.DoubleVar(value=round(st.outline_scale * 100))
        self.v_box = tk.BooleanVar(value=st.box)
        self.v_anim = tk.BooleanVar(value=st.animated)
        self.v_upper = tk.StringVar(value=_key(UPPER, st.uppercase))
        self.v_words = tk.StringVar(value="Automático" if st.max_words <= 0 else str(st.max_words))
        self.v_note = tk.StringVar(value="Prévia ao vivo — muda na hora, conforme você ajusta.")

        self._build()
        for v in (self.v_font, self.v_scale, self.v_auto, self.v_pos, self.v_halign, self.v_text, self.v_high,
                  self.v_out, self.v_outw, self.v_box, self.v_anim, self.v_upper, self.v_words):
            v.trace_add("write", lambda *a: self._changed())
        # mexer no slider de altura desliga o modo automático
        self.v_pos.trace_add("write", lambda *a: self._pos_moved())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(120, self._poll)
        threading.Thread(target=self._load_bg, daemon=True).start()
        self._draw_now()
        self.grab_set()
        self.focus_set()

    # ------------------------------------------------------------------ UI
    def _build(self):
        left = ttk.Frame(self, style="Card.TFrame", padding=(18, 16, 10, 16))
        left.grid(row=0, column=0, sticky="n")
        right = ttk.Frame(self, style="Card.TFrame", padding=(10, 16, 18, 16))
        right.grid(row=0, column=1, sticky="n")
        r = 0

        def row(label, widget, sticky="ew"):
            nonlocal r
            ttk.Label(left, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=5, padx=(0, 12))
            widget.grid(row=r, column=1, sticky=sticky, pady=5)
            r += 1

        def combo(var, values):
            return ttk.Combobox(left, textvariable=var, values=values, state="readonly", width=30)

        cb = combo(self.v_preset, ["Personalizada"] + list(subs.PRESETS))
        cb.bind("<<ComboboxSelected>>", self._apply_preset)
        row("Estilo pronto", cb)
        row("Fonte", combo(self.v_font, subs.available_fonts()))
        row("Tamanho", self._slider(left, self.v_scale, 40, 250, "%"))
        row("Alinhamento", combo(self.v_halign, list(HALIGN)))

        ttk.Checkbutton(left, text="Altura automática (ideal para cada formato)", variable=self.v_auto,
                        style="Card.TCheckbutton", command=self._auto_toggled).grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 0))
        r += 1
        row("Altura (0% = base, 100% = topo)", self._slider(left, self.v_pos, 3, 92, "%"))
        quick = ttk.Frame(left, style="Card.TFrame")
        for name, val in POS_QUICK.items():
            ttk.Button(quick, text=name, style="Ghost.TButton", command=lambda v=val: self._set_pos(v)).pack(side="left", padx=(0, 6))
        row("Posições rápidas", quick, "w")

        row("Cor do texto", self._color_btn(left, self.v_text), "w")
        row("Cor da palavra em destaque", self._color_btn(left, self.v_high), "w")
        row("Cor do contorno / caixa", self._color_btn(left, self.v_out), "w")
        row("Espessura do contorno", self._slider(left, self.v_outw, 0, 250, "%"))
        row("Palavras por linha", combo(self.v_words, ["Automático", "1", "2", "3", "4", "5", "6", "8"]))
        row("Maiúsculas", combo(self.v_upper, list(UPPER)))
        ttk.Checkbutton(left, text="Destacar a palavra que está sendo falada", variable=self.v_anim,
                        style="Card.TCheckbutton").grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1
        ttk.Checkbutton(left, text="Fundo escuro atrás do texto (caixa)", variable=self.v_box,
                        style="Card.TCheckbutton").grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        btns = ttk.Frame(left, style="Card.TFrame")
        btns.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Button(btns, text="Restaurar padrão", command=self._reset).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=self._cancel).pack(side="right")
        ttk.Button(btns, text="Usar esta legenda", style="Accent.TButton", command=self._ok).pack(side="right", padx=(0, 8))

        self.canvas = tk.Canvas(right, width=self.cw, height=self.ch, bg="#2b3a67", highlightthickness=2,
                                highlightbackground=T.ORANGE_DIM, highlightcolor=T.ORANGE_DIM)
        self.canvas.pack()
        ttk.Label(right, textvariable=self.v_note, style="Card.Muted.TLabel", wraplength=self.cw).pack(pady=(8, 2), anchor="w")
        src = "do seu vídeo" if self.video else "de exemplo"
        ttk.Label(right, text=f"Quadro {src} • {self.layout_label}", style="Card.Muted.TLabel", wraplength=self.cw).pack(anchor="w")
        ttk.Button(right, text="Conferir com o motor final", command=self._exact).pack(pady=(10, 0), anchor="w")

    def _slider(self, parent, var, lo, hi, unit):
        f = ttk.Frame(parent, style="Card.TFrame")
        ttk.Scale(f, from_=lo, to=hi, variable=var, orient="horizontal", length=200).pack(side="left")
        lab = ttk.Label(f, width=6, text=f"{int(var.get())}{unit}", style="Card.TLabel")
        lab.pack(side="left", padx=(8, 0))
        var.trace_add("write", lambda *a, v=var, l=lab, u=unit: l.configure(text=f"{int(v.get())}{u}"))
        return f

    def _color_btn(self, parent, var: tk.StringVar):
        def paint():
            col = var.get()
            h = col.lstrip("#")
            try:
                lum = 0.299 * int(h[0:2], 16) + 0.587 * int(h[2:4], 16) + 0.114 * int(h[4:6], 16)
            except ValueError:
                lum = 0
            fg = "#000000" if lum > 140 else "#ffffff"
            btn.configure(bg=col, activebackground=col, text=col.upper(), fg=fg, activeforeground=fg)

        btn = tk.Button(parent, relief="flat", bd=0, width=14, pady=5, highlightthickness=2,
                        highlightbackground=T.BORDER, cursor="hand2", font=(T.FONT, 9, "bold"),
                        command=lambda: self._pick(var))
        var.trace_add("write", lambda *a: paint())
        paint()
        return btn

    def _pick(self, var):
        c = colorchooser.askcolor(color=var.get(), parent=self, title="Escolha a cor")
        if c and c[1]:
            var.set(c[1].upper())

    # ------------------------------------------------------------ ações
    def _set_pos(self, val):
        self._busy = True
        self.v_auto.set(False)
        self._busy = False
        self.v_pos.set(val)

    def _pos_moved(self):
        if not self._busy and self.v_auto.get():
            self._busy = True
            self.v_auto.set(False)
            self._busy = False

    def _auto_toggled(self):
        if self.v_auto.get():  # volta o slider para o valor automático (só para exibir)
            self._busy = True
            self.v_pos.set(AUTO_POS[self.vertical])
            self._busy = False
            self._changed()

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
        fonts = subs.available_fonts()
        self.v_font.set(d.font if d.font in fonts else fonts[0])
        self.v_scale.set(100)
        self._busy = True
        self.v_auto.set(True)
        self.v_pos.set(AUTO_POS[self.vertical])
        self._busy = False
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
            halign=HALIGN.get(self.v_halign.get(), "center"),
            text_color=self.v_text.get(),
            highlight_color=self.v_high.get(),
            outline_color=self.v_out.get(),
            outline_scale=round(self.v_outw.get() / 100, 2),
            box=bool(self.v_box.get()),
            animated=bool(self.v_anim.get()),
            uppercase=UPPER.get(self.v_upper.get(), "auto"),
            max_words=int(w) if w.isdigit() else 0,
        )

    def _ok(self):
        self.result = self._collect()
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        self._closed = True
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.destroy()

    # ------------------------------------------------------- prévia ao vivo
    def _changed(self):
        """Qualquer controle mudou: redesenha a prévia (agrupando mudanças seguidas)."""
        if not self._pending:
            self._pending = True
            self.after_idle(self._draw_now)

    def _font(self, family: str, px: int):
        key = (family, px)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=family, size=-px, weight="bold")
        return self._fonts[key]

    def _draw_now(self):
        self._pending = False
        if self._closed:
            return
        c = self.canvas
        c.delete("sub")
        c.delete("exact")
        self.v_note.set("Prévia ao vivo — muda na hora, conforme você ajusta.")
        st = subs.style_from_dict(self._collect())
        p = subs.params(st, self.vertical)
        chunks = subs.make_chunks(pipeline.preview_words(), st, self.vertical)
        t = pipeline.PREVIEW_TIME
        chunk = next((ch for ch in chunks if ch[0].start <= t <= ch[-1].end + 0.15), chunks[0])
        hi = max((i for i, w in enumerate(chunk) if w.start <= t), default=0) if st.animated else -1

        fs = max(7, int(self.ch * p["font_ratio"]))
        font = self._font(st.font, fs)
        texts = [(w.text.upper() if p["upper"] else w.text) for w in chunk]
        space = font.measure(" ")
        widths = [font.measure(x) for x in texts]
        total = sum(widths) + space * (len(texts) - 1)
        margin = self.cw * 0.05
        if st.halign == "left":
            x = margin
        elif st.halign == "right":
            x = self.cw - margin - total
        else:
            x = (self.cw - total) / 2
        y = self.ch - self.ch * min(95.0, max(0.0, p["pos_pct"])) / 100.0   # base do texto
        lh = font.metrics("linespace")

        if st.box:
            pad = fs * 0.22
            fill = _mix(st.outline_color, (40, 50, 90), 0.69)
            c.create_rectangle(x - pad, y - lh - pad, x + total + pad, y + pad, fill=fill, outline=fill, tags="sub")
            ring = 0.0
        else:
            ring = fs * 0.09 * st.outline_scale
        cx = x
        for i, (txt, w) in enumerate(zip(texts, widths)):
            color = st.highlight_color if i == hi else st.text_color
            if ring >= 0.5:
                for k in range(12):
                    a = 2 * math.pi * k / 12
                    c.create_text(cx + ring * math.cos(a), y + ring * math.sin(a), text=txt, anchor="sw",
                                  font=font, fill=st.outline_color, tags="sub")
            c.create_text(cx, y, text=txt, anchor="sw", font=font, fill=color, tags="sub")
            cx += w + space

    # ----------------------------------------------- fundo e prévia exata
    def _load_bg(self):
        png = self.tmp / "bg.png"
        try:
            pipeline.make_preview_background(self.video, self.layout_label, self.tmp / "bgw", png, self.cw)
            self.q.put(("bg", 0, str(png)))
        except Exception as e:  # noqa: BLE001
            self.q.put(("note", 0, "Sem imagem de fundo (" + str(e)[-80:] + ")"))

    def _exact(self):
        self._seq += 1
        seq, style = self._seq, self._collect()
        self.v_note.set("Renderizando com o motor final...")
        png = self.tmp / f"exact_{seq}.png"

        def work():
            try:
                pipeline.make_preview(self.video, self.layout_label, style, self.tmp / f"w{seq}", png, width=self.cw)
                self.q.put(("exact", seq, str(png)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("note", seq, "Não consegui renderizar: " + str(e)[-120:]))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                kind, seq, data = self.q.get_nowait()
                if kind == "bg":
                    self._bg_img = tk.PhotoImage(file=data)
                    self.canvas.create_image(0, 0, anchor="nw", image=self._bg_img, tags="bg")
                    self.canvas.tag_lower("bg")
                elif kind == "exact" and seq == self._seq:
                    self._exact_img = tk.PhotoImage(file=data)
                    self.canvas.delete("sub")
                    self.canvas.delete("exact")
                    self.canvas.create_image(0, 0, anchor="nw", image=self._exact_img, tags="exact")
                    self.v_note.set("Mostrando a renderização exata. Mexa em qualquer controle para voltar à prévia ao vivo.")
                elif kind == "note":
                    self.v_note.set(data)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.after(120, self._poll)
        except tk.TclError:
            pass
