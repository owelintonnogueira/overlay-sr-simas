"""Tk de mentira: permite importar e exercitar a LÓGICA das janelas onde não há tkinter (ex.: este sandbox).

Não testa aparência — só fluxo (variáveis com trace, desenho no Canvas, callbacks, estados).
"""
import sys
import types


class TclError(Exception):
    pass


class _Var:
    default = ""

    def __init__(self, master=None, value=None, name=None):
        self._v = self.default if value is None else value
        self._cbs = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in list(self._cbs):
            cb()

    def trace_add(self, mode, cb):
        self._cbs.append(lambda: cb("n", "", "w"))


class StringVar(_Var):
    default = ""


class DoubleVar(_Var):
    default = 0.0

    def get(self):
        return float(self._v)


class BooleanVar(_Var):
    default = False

    def get(self):
        return bool(self._v)


class _W:
    queue: list = []

    def __init__(self, *a, **k):
        self.master = a[0] if a else None
        self.kw = dict(k)
        self.tk = types.SimpleNamespace(splitlist=lambda s: tuple(str(s).split("|")))

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None

    def configure(self, **k):
        self.kw.update(k)

    config = configure

    def __setitem__(self, k, v):
        self.kw[k] = v

    def after_idle(self, f, *a):
        _W.queue.append(f)

    def after(self, ms, f=None, *a):
        if f is not None:
            _W.queue.append(("later", f))
        return "id"

    def winfo_width(self):
        return 800

    def winfo_height(self):
        return 88

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def wait_window(self, w):
        pass

    def destroy(self):
        self.destroyed = True


class Canvas(_W):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.items = []

    def _add(self, kind, args, kw):
        self.items.append(dict(kind=kind, args=args, **kw))

    def create_text(self, *a, **k):
        self._add("text", a, k)

    def create_rectangle(self, *a, **k):
        self._add("rect", a, k)

    def create_image(self, *a, **k):
        self._add("image", a, k)

    def delete(self, tag):
        if tag == "all":
            self.items = []
        else:
            self.items = [i for i in self.items if i.get("tags") != tag]

    def tagged(self, tag):
        return [i for i in self.items if i.get("tags") == tag]


class Font:
    def __init__(self, family="", size=10, weight="normal", **k):
        self.family, self.size = family, size

    def measure(self, text):
        return int(len(text) * abs(self.size) * 0.6)

    def metrics(self, what):
        return int(abs(self.size) * 1.2)


class PhotoImage:
    def __init__(self, *a, **k):
        pass

    def width(self):
        return 100

    def height(self):
        return 100


class Style:
    def __init__(self, *a, **k):
        pass

    def configure(self, *a, **k):
        pass

    def map(self, *a, **k):
        pass

    def theme_use(self, *a, **k):
        pass


def install():
    """Registra módulos falsos tkinter, tkinter.ttk, .font, .filedialog, .messagebox, .colorchooser."""
    tk = types.ModuleType("tkinter")
    ttk = types.ModuleType("tkinter.ttk")
    font = types.ModuleType("tkinter.font")
    fd = types.ModuleType("tkinter.filedialog")
    mb = types.ModuleType("tkinter.messagebox")
    cc = types.ModuleType("tkinter.colorchooser")

    for name in ("Tk", "Toplevel", "Frame", "Label", "Button", "Text", "Entry", "Scrollbar"):
        setattr(tk, name, type(name, (_W,), {}))
    tk.Canvas, tk.StringVar, tk.DoubleVar, tk.BooleanVar = Canvas, StringVar, DoubleVar, BooleanVar
    tk.PhotoImage, tk.TclError = PhotoImage, TclError
    for name in ("Frame", "Label", "Button", "Entry", "Combobox", "Spinbox", "Checkbutton", "Scale", "Progressbar"):
        setattr(ttk, name, type(name, (_W,), {}))
    ttk.Style = Style
    font.Font = Font
    fd.askopenfilename = lambda **k: ""
    fd.askdirectory = lambda **k: ""
    mb.showinfo = mb.showwarning = mb.showerror = lambda *a, **k: None
    mb.askyesno = lambda *a, **k: True
    cc.askcolor = lambda **k: (None, "#123456")
    tk.ttk, tk.font, tk.filedialog, tk.messagebox, tk.colorchooser = ttk, font, fd, mb, cc
    sys.modules.update({
        "tkinter": tk, "tkinter.ttk": ttk, "tkinter.font": font, "tkinter.filedialog": fd,
        "tkinter.messagebox": mb, "tkinter.colorchooser": cc,
    })
    return tk


def flush():
    """Executa os callbacks agendados com after_idle (os 'after' com atraso são ignorados)."""
    n = 0
    while _W.queue:
        f = _W.queue.pop(0)
        if isinstance(f, tuple):
            continue
        f()
        n += 1
    return n
