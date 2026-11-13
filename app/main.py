"""Cortes de Live – interface gráfica (tema laranja e preto)."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import gpu  # noqa: E402
import media  # noqa: E402
import pipeline  # noqa: E402
import subdialog  # noqa: E402
import theme as T  # noqa: E402
from common import Cancelled  # noqa: E402

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except Exception:  # noqa: BLE001
    HAS_DND = False

APP_NAME = "Cortes de Live"
PRESETS = {
    "Shorts / Reels / TikTok (30–60 s)": (30, 60),
    "Curto (1–2 min)": (60, 120),
    "Médio (2–3 min)": (120, 180),
    "Longo (3–5 min)": (180, 300),
    "Extra longo (5–10 min)": (300, 600),
    "Personalizado": None,
}
GPU_CHOICES = {
    "Automática (placa de vídeo + processador)": "auto",
    "Desligada (só processador)": "off",
}
SETTINGS = common.data_dir() / "config.json"
LOG_FILE = common.data_dir() / "log.txt"


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.result_dir: Path | None = None
        self.sub_style: dict = {}
        self._drop_hot = False
        root.title(APP_NAME)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"880x{min(960, max(640, sh - 80))}+{max(0, (sw - 880) // 2)}+20")
        root.minsize(820, 620)
        try:
            root.iconbitmap(str(common.base_dir() / "assets" / "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        T.apply(root)
        self._vars()
        self._build()
        self._load_settings()
        self._draw_drop()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(100, self._poll)

    # ------------------------------------------------------------------ vars
    def _vars(self):
        self.v_source = tk.StringVar()
        self.v_n = tk.StringVar(value="10")
        self.v_preset = tk.StringVar(value="Shorts / Reels / TikTok (30–60 s)")
        self.v_min = tk.StringVar(value="30")
        self.v_max = tk.StringVar(value="60")
        self.v_layout = tk.StringVar(value="Vertical 9:16 – fundo desfocado")
        self.v_subs = tk.BooleanVar(value=True)
        self.v_srt = tk.BooleanVar(value=False)
        self.v_lang = tk.StringVar(value="Português")
        self.v_model = tk.StringVar(value="small – equilibrado (recomendado)")
        self.v_quality = tk.StringVar(value="1080p")
        self.v_cookies = tk.StringVar(value="Nenhum")
        self.v_gpu = tk.StringVar(value="Automática (placa de vídeo + processador)")
        self.v_cpu = tk.StringVar(value="80")
        self.v_out = tk.StringVar(value=str(common.default_output_dir()))
        self.v_status = tk.StringVar(value="Pronto para começar.")
        self.v_source.trace_add("write", lambda *a: self._draw_drop())

    # -------------------------------------------------------------------- UI
    def _card(self, parent, title: str) -> tk.Frame:
        f = tk.Frame(parent, bg=T.CARD, highlightthickness=1, highlightbackground=T.BORDER, highlightcolor=T.BORDER)
        f.pack(fill="x", pady=(10, 0))
        tk.Label(f, text=title.upper(), bg=T.CARD, fg=T.ORANGE, font=(T.FONT, 9, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        inner = tk.Frame(f, bg=T.CARD)
        inner.pack(fill="x", padx=14, pady=(6, 12))
        return inner

    def _build(self):
        outer = ttk.Frame(self.root, padding=(24, 18, 24, 16))
        outer.pack(fill="both", expand=True)

        # cabeçalho
        hdr = ttk.Frame(outer)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✂", bg=T.ORANGE, fg=T.ON_ORANGE, font=(T.FONT, 18, "bold"), width=3, pady=5).pack(side="left")
        titles = ttk.Frame(hdr)
        titles.pack(side="left", padx=14)
        ttk.Label(titles, text="Cortes de Live", style="H.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Ache os melhores momentos, corte e legende — grátis e no seu PC", style="Muted.TLabel").pack(anchor="w")

        # 1 · vídeo
        c1 = self._card(outer, "1 · Vídeo ou link")
        self.drop = tk.Canvas(c1, height=88, bg=T.CARD_ALT, highlightthickness=0, cursor="hand2")
        self.drop.pack(fill="x")
        self.drop.bind("<Configure>", lambda e: self._draw_drop())
        self.drop.bind("<Button-1>", lambda e: self._pick_file())
        self.drop.bind("<Enter>", lambda e: self._hot(True))
        self.drop.bind("<Leave>", lambda e: self._hot(False))
        if HAS_DND:
            for w in (self.drop, self.root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
        r = tk.Frame(c1, bg=T.CARD)
        r.pack(fill="x", pady=(10, 0))
        tk.Label(r, text="ou cole um link:", bg=T.CARD, fg=T.MUTED, font=(T.FONT, 10)).pack(side="left")
        ttk.Entry(r, textvariable=self.v_source).pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(c1, text="YouTube, Twitch, Kick, TikTok, Instagram, X/Twitter, Facebook e centenas de outros sites.",
                 bg=T.CARD, fg=T.MUTED, font=(T.FONT, 9)).pack(anchor="w", pady=(6, 0))

        # 2 · cortes
        c2 = self._card(outer, "2 · Cortes")
        g = tk.Frame(c2, bg=T.CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        self._lab(g, 0, 0, "Quantidade de cortes")
        ttk.Spinbox(g, from_=1, to=200, textvariable=self.v_n, width=8).grid(row=0, column=1, sticky="w", pady=5)
        self._lab(g, 0, 2, "Formato")
        ttk.Combobox(g, textvariable=self.v_layout, values=list(media.LAYOUTS), state="readonly").grid(row=0, column=3, sticky="ew", pady=5)
        self._lab(g, 1, 0, "Duração de cada corte")
        cb = ttk.Combobox(g, textvariable=self.v_preset, values=list(PRESETS), state="readonly")
        cb.grid(row=1, column=1, sticky="ew", pady=5)
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        self._lab(g, 1, 2, "Mín. / Máx. (segundos)")
        f = tk.Frame(g, bg=T.CARD)
        f.grid(row=1, column=3, sticky="w", pady=5)
        ttk.Spinbox(f, from_=5, to=3600, textvariable=self.v_min, width=6, command=self._custom).pack(side="left")
        tk.Label(f, text="  até  ", bg=T.CARD, fg=T.MUTED).pack(side="left")
        ttk.Spinbox(f, from_=5, to=3600, textvariable=self.v_max, width=6, command=self._custom).pack(side="left")
        self._lab(g, 2, 0, "Idioma da fala")
        ttk.Combobox(g, textvariable=self.v_lang, values=list(pipeline.LANGUAGES), state="readonly").grid(row=2, column=1, sticky="ew", pady=5)
        self._lab(g, 2, 2, "Qualidade da transcrição")
        ttk.Combobox(g, textvariable=self.v_model, values=list(pipeline.MODELS), state="readonly").grid(row=2, column=3, sticky="ew", pady=5)

        # 3 · desempenho
        c3 = self._card(outer, "3 · Desempenho e download")
        g = tk.Frame(c3, bg=T.CARD)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        g.columnconfigure(3, weight=1)
        self._lab(g, 0, 0, "Placa de vídeo")
        ttk.Combobox(g, textvariable=self.v_gpu, values=list(GPU_CHOICES), state="readonly").grid(row=0, column=1, sticky="ew", pady=5)
        self._lab(g, 0, 2, "Limite do processador (%)")
        ttk.Spinbox(g, from_=30, to=100, increment=5, textvariable=self.v_cpu, width=8).grid(row=0, column=3, sticky="w", pady=5)
        self._lab(g, 1, 0, "Qualidade do download")
        ttk.Combobox(g, textvariable=self.v_quality, values=["720p", "1080p", "Melhor"], state="readonly").grid(row=1, column=1, sticky="ew", pady=5)
        self._lab(g, 1, 2, "Cookies do navegador")
        ttk.Combobox(g, textvariable=self.v_cookies, values=["Nenhum", "Chrome", "Edge", "Firefox", "Brave"], state="readonly").grid(row=1, column=3, sticky="ew", pady=5)

        # 4 · legenda e saída
        c4 = self._card(outer, "4 · Legenda e saída")
        chk = tk.Frame(c4, bg=T.CARD)
        chk.pack(fill="x")
        ttk.Checkbutton(chk, text="Legendas no vídeo", variable=self.v_subs, style="Card.TCheckbutton").pack(side="left", padx=(0, 18))
        ttk.Checkbutton(chk, text="Salvar também arquivo .srt", variable=self.v_srt, style="Card.TCheckbutton").pack(side="left", padx=(0, 18))
        ttk.Button(chk, text="Personalizar legenda…", command=self._open_sub_dialog).pack(side="left")
        o = tk.Frame(c4, bg=T.CARD)
        o.pack(fill="x", pady=(10, 0))
        tk.Label(o, text="Salvar em:", bg=T.CARD, fg=T.MUTED).pack(side="left")
        ttk.Entry(o, textvariable=self.v_out).pack(side="left", fill="x", expand=True, padx=10)
        ttk.Button(o, text="Escolher…", command=self._pick_out).pack(side="left")

        # ação
        act = ttk.Frame(outer)
        act.pack(fill="x", pady=(14, 8))
        self.btn_go = ttk.Button(act, text="Gerar cortes", style="Accent.TButton", command=self._start)
        self.btn_go.pack(side="left", fill="x", expand=True)
        self.btn_cancel = ttk.Button(act, text="Cancelar", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(8, 0), ipady=4)
        self.btn_open = ttk.Button(act, text="Abrir pasta", command=self._open_result, state="disabled")
        self.btn_open.pack(side="left", padx=(8, 0), ipady=4)

        self.bar = ttk.Progressbar(outer, maximum=1000)
        self.bar.pack(fill="x")
        ttk.Label(outer, textvariable=self.v_status, style="Muted.TLabel").pack(anchor="w", pady=(5, 6))
        self.log = tk.Text(outer, height=5, bg=T.CARD_ALT, fg=T.TEXT, relief="flat", wrap="word", font=("Consolas", 9),
                           state="disabled", highlightthickness=1, highlightbackground=T.BORDER, insertbackground=T.ORANGE,
                           padx=8, pady=6)
        self.log.pack(fill="both", expand=True)

    def _lab(self, parent, r, c, text):
        tk.Label(parent, text=text, bg=T.CARD, fg=T.TEXT, font=(T.FONT, 10)).grid(row=r, column=c, sticky="w", pady=5, padx=(0, 10))

    # ----------------------------------------------------------- zona de soltar
    def _hot(self, on: bool):
        self._drop_hot = on
        self._draw_drop()

    def _draw_drop(self):
        c = getattr(self, "drop", None)
        if c is None:
            return
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 60)
        c.configure(bg=T.HOVER if self._drop_hot else T.CARD_ALT)
        c.create_rectangle(4, 4, w - 4, h - 4, outline=T.ORANGE if self._drop_hot else T.ORANGE_DIM, dash=(7, 5), width=2)
        src = self.v_source.get().strip().strip('"')
        if src:
            if _is_url(src):
                title, sub = "Link colado", src[:90]
            else:
                p = Path(src)
                size = ""
                try:
                    size = f" • {p.stat().st_size / 1e9:.2f} GB" if p.stat().st_size > 1e9 else f" • {p.stat().st_size / 1e6:.0f} MB"
                except OSError:
                    pass
                title, sub = p.name[:80], "Clique para trocar o vídeo" + size
        else:
            title = "Arraste o vídeo para cá" if HAS_DND else "Clique para escolher o vídeo"
            sub = "ou clique aqui para escolher • MP4, MKV, MOV, AVI, WEBM, TS…"
        c.create_text(w / 2, h / 2 - 11, text=title, fill=T.TEXT, font=(T.FONT, 14, "bold"))
        c.create_text(w / 2, h / 2 + 15, text=sub, fill=T.MUTED, font=(T.FONT, 9))

    # ------------------------------------------------------------ callbacks
    def _on_drop(self, event):
        files = self.root.tk.splitlist(event.data)
        if files:
            self.v_source.set(files[0])

    def _pick_file(self):
        p = filedialog.askopenfilename(
            title="Escolha o vídeo",
            filetypes=[("Vídeos", "*.mp4 *.mkv *.mov *.avi *.webm *.flv *.ts *.m4v *.wmv"), ("Todos", "*.*")],
        )
        if p:
            self.v_source.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory(title="Pasta para salvar os cortes")
        if p:
            self.v_out.set(p)

    def _on_preset(self, _=None):
        pr = PRESETS.get(self.v_preset.get())
        if pr:
            self.v_min.set(str(pr[0]))
            self.v_max.set(str(pr[1]))

    def _custom(self):
        self.v_preset.set("Personalizado")

    def _open_sub_dialog(self):
        src = self.v_source.get().strip().strip('"')
        video = src if src and not _is_url(src) and Path(src).is_file() else None
        dlg = subdialog.SubtitleDialog(self.root, self.sub_style, video, self.v_layout.get())
        self.root.wait_window(dlg)
        if dlg.result is not None:
            self.sub_style = dlg.result
            self._save_settings()
            self._log("Estilo de legenda atualizado.")

    def _log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

    # ------------------------------------------------------------ execução
    def _start(self):
        try:
            n = int(self.v_n.get())
            mn, mx = float(self.v_min.get()), float(self.v_max.get())
            cpu = int(float(self.v_cpu.get()))
            assert 1 <= n <= 200 and 5 <= mn <= mx and 30 <= cpu <= 100
        except (ValueError, AssertionError):
            messagebox.showwarning(APP_NAME, "Confira a quantidade (1–200), as durações (mínima ≤ máxima, em segundos) e o limite do processador (30–100%).")
            return
        if not self.v_source.get().strip():
            messagebox.showwarning(APP_NAME, "Solte um vídeo aqui ou cole um link.")
            return
        opts = pipeline.Options(
            source=self.v_source.get(), out_dir=self.v_out.get(), n_clips=n, min_s=mn, max_s=mx,
            model=pipeline.MODELS[self.v_model.get()], language=pipeline.LANGUAGES[self.v_lang.get()],
            layout=self.v_layout.get(), subtitles=self.v_subs.get(), sub_style=self.sub_style or None,
            save_srt=self.v_srt.get(), quality=self.v_quality.get(), cookies_browser=self.v_cookies.get(),
            gpu=GPU_CHOICES.get(self.v_gpu.get(), "auto"), cpu_limit=cpu,
        )
        if opts.gpu == "auto":
            g = gpu.nvidia_gpu()
            if g and not gpu.libs_ready():
                opts.allow_cuda_download = messagebox.askyesno(
                    APP_NAME,
                    f"Placa de vídeo NVIDIA detectada: {g['name']}.\n\n"
                    "Para usá-la na transcrição, preciso baixar bibliotecas gratuitas da NVIDIA "
                    "(cerca de 600 MB, uma vez só).\n\nBaixar agora?\n\n"
                    "(Se você responder Não, a transcrição usa o processador; a codificação do vídeo ainda pode usar a placa.)",
                )
        self._save_settings()
        self.cancel.clear()
        self.btn_go.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_open.configure(state="disabled")
        self.bar["value"] = 0
        self._log("—" * 40)
        self.thread = threading.Thread(target=self._worker, args=(opts,), daemon=True)
        self.thread.start()

    def _worker(self, opts):
        try:
            files = pipeline.run(
                opts,
                log=lambda m: self.q.put(("log", m)),
                progress=lambda f, m: self.q.put(("prog", (f, m))),
                cancel=self.cancel,
            )
            self.q.put(("done", files))
        except Cancelled:
            self.q.put(("cancelled", None))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", (str(e), traceback.format_exc())))

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "prog":
                    self.bar["value"] = data[0] * 1000
                    self.v_status.set(data[1])
                elif kind == "done":
                    self._finish("Pronto!")
                    if data:
                        self.result_dir = Path(data[0]).parent
                        self.btn_open.configure(state="normal")
                    messagebox.showinfo(APP_NAME, f"{len(data)} cortes gerados!\n\nPasta: {self.result_dir}")
                    self._open_result()
                elif kind == "cancelled":
                    self._finish("Cancelado.")
                    self._log("Cancelado pelo usuário.")
                elif kind == "error":
                    self._finish("Deu erro.")
                    self._log("ERRO: " + data[0])
                    self._log(data[1])
                    messagebox.showerror(APP_NAME, f"Algo deu errado:\n\n{data[0][:600]}\n\nDetalhes em: {LOG_FILE}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, status: str):
        self.v_status.set(status)
        self.btn_go.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    def _cancel(self):
        self.cancel.set()
        self.v_status.set("Cancelando...")

    def _open_result(self):
        if self.result_dir and self.result_dir.exists():
            try:
                os.startfile(str(self.result_dir))  # type: ignore[attr-defined]
            except AttributeError:
                pass

    # ------------------------------------------------------------ preferências
    def _save_settings(self):
        keys = ["n", "preset", "min", "max", "layout", "subs", "srt", "lang", "model", "quality", "cookies", "gpu", "cpu", "out"]
        try:
            data = {k: getattr(self, f"v_{k}").get() for k in keys}
            data["sub_style"] = self.sub_style
            SETTINGS.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data.get("sub_style"), dict):
            self.sub_style = data["sub_style"]
        for k, v in data.items():
            var = getattr(self, f"v_{k}", None)
            if var is not None and k != "source":
                try:
                    var.set(v)
                except tk.TclError:
                    pass

    def _close(self):
        self.cancel.set()
        self._save_settings()
        self.root.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
