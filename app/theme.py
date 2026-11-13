"""Tema laranja e preto compartilhado por todas as janelas."""
from __future__ import annotations

from tkinter import ttk

BG = "#0b0b0d"          # fundo da janela (quase preto)
PANEL = "#131316"
CARD = "#1a1a1f"        # cartões
CARD_ALT = "#101013"    # áreas rebaixadas (zona de soltar, log)
HOVER = "#26262d"
BORDER = "#2d2d35"
ORANGE = "#ff7a1a"
ORANGE_HOVER = "#ff9440"
ORANGE_DIM = "#6b3510"
ON_ORANGE = "#140a00"   # texto sobre laranja
TEXT = "#f6f1ea"
MUTED = "#9d9ba3"

FONT = "Segoe UI"


def apply(root) -> None:
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=TEXT, fieldbackground=CARD, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, troughcolor=CARD, focuscolor=CARD, font=(FONT, 10))

    for suffix, bg in (("", BG), ("Card.", CARD)):
        s.configure(f"{suffix}TFrame", background=bg)
        s.configure(f"{suffix}TLabel", background=bg, foreground=TEXT)
        s.configure(f"{suffix}TCheckbutton", background=bg, foreground=TEXT, focuscolor=bg,
                    indicatorbackground=CARD_ALT, indicatorforeground=ON_ORANGE,
                    upperbordercolor=BORDER, lowerbordercolor=BORDER, padding=(2, 3))
        s.map(f"{suffix}TCheckbutton",
              background=[("active", bg)],
              indicatorbackground=[("selected", ORANGE), ("active", HOVER)],
              foreground=[("disabled", MUTED)])
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("Card.Muted.TLabel", background=CARD, foreground=MUTED)
    s.configure("H.TLabel", font=(FONT, 20, "bold"), foreground=TEXT)
    s.configure("Accent.TLabel", foreground=ORANGE)

    # botões
    s.configure("TButton", background=CARD, foreground=TEXT, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD,
                focuscolor=CARD, padding=(14, 8), borderwidth=1, relief="flat")
    s.map("TButton", background=[("active", HOVER), ("pressed", ORANGE_DIM)],
          bordercolor=[("active", ORANGE)], foreground=[("disabled", MUTED)])
    s.configure("Accent.TButton", background=ORANGE, foreground=ON_ORANGE, bordercolor=ORANGE, lightcolor=ORANGE,
                darkcolor=ORANGE, font=(FONT, 12, "bold"), padding=(16, 11))
    s.map("Accent.TButton", background=[("active", ORANGE_HOVER), ("pressed", "#e56a0f"), ("disabled", "#3b2412")],
          bordercolor=[("active", ORANGE_HOVER), ("disabled", "#3b2412")], foreground=[("disabled", "#7d6650")],
          lightcolor=[("active", ORANGE_HOVER), ("disabled", "#3b2412")], darkcolor=[("active", ORANGE_HOVER), ("disabled", "#3b2412")])
    s.configure("Ghost.TButton", background=CARD, padding=(10, 6))

    # campos
    for w in ("TEntry", "TSpinbox", "TCombobox"):
        s.configure(w, fieldbackground=CARD_ALT, foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                    darkcolor=BORDER, insertcolor=ORANGE, padding=(6, 5), selectbackground=ORANGE, selectforeground=ON_ORANGE)
    s.configure("TCombobox", background=CARD, arrowcolor=ORANGE)
    s.configure("TSpinbox", background=CARD, arrowcolor=ORANGE)
    s.map("TCombobox", fieldbackground=[("readonly", CARD_ALT)], foreground=[("readonly", TEXT)],
          selectbackground=[("readonly", CARD_ALT)], selectforeground=[("readonly", TEXT)],
          bordercolor=[("focus", ORANGE), ("active", ORANGE_DIM)], lightcolor=[("focus", ORANGE)], darkcolor=[("focus", ORANGE)])
    s.map("TEntry", bordercolor=[("focus", ORANGE)], lightcolor=[("focus", ORANGE)], darkcolor=[("focus", ORANGE)])
    s.map("TSpinbox", bordercolor=[("focus", ORANGE)], lightcolor=[("focus", ORANGE)], darkcolor=[("focus", ORANGE)])

    # sliders e barra de progresso
    s.configure("Horizontal.TScale", background=ORANGE, troughcolor=CARD_ALT, bordercolor=BORDER,
                lightcolor=ORANGE, darkcolor=ORANGE, gripcount=0)
    s.map("Horizontal.TScale", background=[("active", ORANGE_HOVER)])
    s.configure("Horizontal.TProgressbar", background=ORANGE, troughcolor=CARD_ALT, bordercolor=BG,
                lightcolor=ORANGE, darkcolor=ORANGE, thickness=10)

    # lista suspensa dos combobox
    root.option_add("*TCombobox*Listbox.background", CARD_ALT)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ORANGE)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ORANGE)
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
