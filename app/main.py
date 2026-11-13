"""Cortes de Live – interface gráfica."""
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
import media  # noqa: E402
import pipeline  # noqa: E402
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
BG, FG, CARD, ACCENT, MUTED = "#14151a", "#eceef4", "#1d1f27", "#7c5cff", "#8b90a0"
SETTINGS = common.data_dir() / "config.json"
LOG_FILE = common.data_dir() / "log.txt"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.result_dir: Path | None = None
        root.title(APP_NAME)
        root.geometry("820x860")
        root.minsize(760, 760)
        root.configure(bg=BG)
        self._style()
        self._vars()
        self._build()
        self._load_settings()
        root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(100, self._poll)

    # ---------------------------------------------------------------- estilo
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, fieldbackground=CARD, font=("Segoe UI", 10))
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Card.TLabel", background=CARD)
        s.configure("H.TLabel", font=("Segoe UI", 18, "bold"))
        s.configure("TCheckbutton", background=BG, foreground=FG)
        s.map("TCheckbutton", background=[("active", BG)])
        s.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG)
        s.configure("TCombobox", fieldbackground=CARD, foreground=FG, arrowcolor=FG)
        s.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", FG)])
        s.configure("TSpinbox", fieldbackground=CARD, foreground=FG, arrowcolor=FG)
        s.configure("TButton", background=CARD, foreground=FG, padding=8, borderwidth=0)
        s.map("TButton", background=[("active", "#2a2d38")])
        s.configure("Accent.TButton", background=ACCENT, foreground="white", font=("Segoe UI", 11, "bold"), padding=12)
        s.map("Accent.TButton", background=[("active", "#6a4be8"), ("disabled", "#3a3560")])
        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD, borderwidth=0)

    def _vars(self):
        self.v_source = tk.StringVar()
        self.v_n = tk.StringVar(value="10")
        self.v_preset = tk.StringVar(value="Shorts / Reels / TikTok (30–60 s)")
        self.v_min = tk.StringVar(value="30")
        self.v_max = tk.StringVar(value="60")
        self.v_layout = tk.StringVar(value="Vertical 9:16 – fundo desfocado")
        self.v_subs = tk.BooleanVar(value=True)
        self.v_anim = tk.BooleanVar(value=True)
        self.v_srt = tk.BooleanVar(value=False)
        self.v_lang = tk.StringVar(value="Português")
        self.v_model = tk.StringVar(value="small – equilibrado (recomendado)")
        self.v_quality = tk.StringVar(value="1080p")
        self.v_cookies = tk.StringVar(value="Nenhum")
        self.v_out = tk.StringVar(value=str(common.default_output_dir()))
        self.v_status = tk.StringVar(value="Pronto para começar.")

    # ------------------------------------------------------------------- UI
    def _build(self):
        pad = {"padx": 20}
        ttk.Label(self.root, text="✂  Cortes de Live", style="H.TLabel").pack(anchor="w", pady=(16, 0), **pad)
        ttk.Label(self.root, text="Solte um vídeo ou cole um link. O programa acha os melhores momentos, corta e legenda — tudo grátis e offline.",
                  style="Muted.TLabel", wraplength=760).pack(anchor="w", pady=(0, 10), **pad)

        # zona de soltar
        self.drop = tk.Label(
            self.root, text="⬇  Arraste o vídeo aqui\nou clique para escolher o arquivo",
            bg=CARD, fg=FG, font=("Segoe UI", 12), height=4, cursor="hand2",
            highlightthickness=2, highlightbackground=ACCENT, highlightcolor=ACCENT,
        )
        self.drop.pack(fill="x", pady=(0, 8), **pad)
        self.drop.bind("<Button-1>", lambda e: self._pick_file())
        if HAS_DND:
            for w in (self.drop, self.root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)
        else:
            self.drop.configure(text="Clique para escolher o arquivo de vídeo")

        row = ttk.Frame(self.root)
        row.pack(fill="x", pady=(0, 10), **pad)
        ttk.Label(row, text="Vídeo ou link:").pack(side="left")
        ttk.Entry(row, textvariable=self.v_source).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(self.root, text="Links aceitos: YouTube, Twitch, Kick, TikTok, Instagram, X/Twitter, Facebook e centenas de outros.",
                  style="Muted.TLabel").pack(anchor="w", **pad)

        # opções
        box = ttk.Frame(self.root)
        box.pack(fill="x", pady=10, **pad)
        box.columnconfigure(1, weight=1)
        box.columnconfigure(3, weight=1)

        def lab(r, c, t):
            ttk.Label(box, text=t).grid(row=r, column=c, sticky="w", pady=5, padx=(0, 8))

        lab(0, 0, "Quantidade de cortes")
        ttk.Spinbox(box, from_=1, to=200, textvariable=self.v_n, width=8).grid(row=0, column=1, sticky="w")
        lab(0, 2, "Formato")
        ttk.Combobox(box, textvariable=self.v_layout, values=list(media.LAYOUTS), state="readonly").grid(row=0, column=3, sticky="ew")

        lab(1, 0, "Duração de cada corte")
        cb = ttk.Combobox(box, textvariable=self.v_preset, values=list(PRESETS), state="readonly")
        cb.grid(row=1, column=1, sticky="ew")
        cb.bind("<<ComboboxSelected>>", self._on_preset)
        lab(1, 2, "Mín. / Máx. (segundos)")
        f = ttk.Frame(box)
        f.grid(row=1, column=3, sticky="w")
        ttk.Spinbox(f, from_=5, to=3600, textvariable=self.v_min, width=6, command=self._custom).pack(side="left")
        ttk.Label(f, text="  até  ").pack(side="left")
        ttk.Spinbox(f, from_=5, to=3600, textvariable=self.v_max, width=6, command=self._custom).pack(side="left")

        lab(2, 0, "Idioma da fala")
        ttk.Combobox(box, textvariable=self.v_lang, values=list(pipeline.LANGUAGES), state="readonly").grid(row=2, column=1, sticky="ew")
        lab(2, 2, "Qualidade da transcrição")
        ttk.Combobox(box, textvariable=self.v_model, values=list(pipeline.MODELS), state="readonly").grid(row=2, column=3, sticky="ew")

        lab(3, 0, "Qualidade do download")
        ttk.Combobox(box, textvariable=self.v_quality, values=["720p", "1080p", "Melhor"], state="readonly").grid(row=3, column=1, sticky="ew")
        lab(3, 2, "Cookies do navegador")
        ttk.Combobox(box, textvariable=self.v_cookies, values=["Nenhum", "Chrome", "Edge", "Firefox", "Brave"], state="readonly").grid(row=3, column=3, sticky="ew")

        chk = ttk.Frame(self.root)
        chk.pack(fill="x", **pad)
        ttk.Checkbutton(chk, text="Legendas no vídeo", variable=self.v_subs).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(chk, text="Palavra falada em destaque", variable=self.v_anim).pack(side="left", padx=(0, 18))
        ttk.Checkbutton(chk, text="Salvar também arquivo .srt", variable=self.v_srt).pack(side="left")

        outr = ttk.Frame(self.root)
        outr.pack(fill="x", pady=10, **pad)
        ttk.Label(outr, text="Salvar em:").pack(side="left")
        ttk.Entry(outr, textvariable=self.v_out).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(outr, text="Escolher…", command=self._pick_out).pack(side="left")

        # ação
        act = ttk.Frame(self.root)
        act.pack(fill="x", pady=(4, 6), **pad)
        self.btn_go = ttk.Button(act, text="Gerar cortes", style="Accent.TButton", command=self._start)
        self.btn_go.pack(side="left", fill="x", expand=True)
        self.btn_cancel = ttk.Button(act, text="Cancelar", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=(8, 0))
        self.btn_open = ttk.Button(act, text="Abrir pasta", command=self._open_result, state="disabled")
        self.btn_open.pack(side="left", padx=(8, 0))

        self.bar = ttk.Progressbar(self.root, maximum=1000)
        self.bar.pack(fill="x", **pad)
        ttk.Label(self.root, textvariable=self.v_status, style="Muted.TLabel").pack(anchor="w", pady=(4, 6), **pad)
        self.log = tk.Text(self.root, height=9, bg=CARD, fg=FG, relief="flat", wrap="word", font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, pady=(0, 16), **pad)

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
            assert 1 <= n <= 200 and 5 <= mn <= mx
        except (ValueError, AssertionError):
            messagebox.showwarning(APP_NAME, "Confira a quantidade (1–200) e as durações (mínima ≤ máxima, em segundos).")
            return
        if not self.v_source.get().strip():
            messagebox.showwarning(APP_NAME, "Solte um vídeo aqui ou cole um link.")
            return
        opts = pipeline.Options(
            source=self.v_source.get(), out_dir=self.v_out.get(), n_clips=n, min_s=mn, max_s=mx,
            model=pipeline.MODELS[self.v_model.get()], language=pipeline.LANGUAGES[self.v_lang.get()],
            layout=self.v_layout.get(), subtitles=self.v_subs.get(), animated=self.v_anim.get(),
            save_srt=self.v_srt.get(), quality=self.v_quality.get(), cookies_browser=self.v_cookies.get(),
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
        keys = ["n", "preset", "min", "max", "layout", "subs", "anim", "srt", "lang", "model", "quality", "cookies", "out"]
        try:
            SETTINGS.write_text(json.dumps({k: getattr(self, f"v_{k}").get() for k in keys}), encoding="utf-8")
        except OSError:
            pass

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in data.items():
            var = getattr(self, f"v_{k}", None)
            if var is not None:
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
