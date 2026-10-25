"""Window for the SolidCraft thread generator."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import sc_live
import threadgen as tg

# bundled files live next to the script, or in PyInstaller's unpack folder
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(tg.documents_dir(), "SolidCraft Threads")
CUSTOM = "Custom"

HELP = {
    "clearance": "Gap added on every surface of this part, in mm.\n"
                 "Bolts get thinner, nuts get wider. A printed bolt and a printed\n"
                 "nut end up with twice this gap. FDM: 0.1-0.2, resin: 0.05-0.1.",
    "pitch": "Distance between neighbouring thread crests (mm).",
    "starts": "Number of interleaved threads. 2-4 starts screw on faster\n"
              "(each turn advances starts x pitch). Bolt and nut must match.",
    "depth": "Radial depth of the thread. Leave blank for the standard depth.",
    "chamfer": "Lead-in bevel on the thread ends. Blank = automatic.",
}


class Tip:
    def __init__(self, widget, text):
        self.widget, self.text, self.win = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.win = tk.Toplevel(self.widget)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{x}+{y}")
        tk.Label(self.win, text=self.text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, padx=6, pady=4).pack()

    def hide(self, _):
        if self.win:
            self.win.destroy()
            self.win = None


class App(ttk.Frame):
    def __init__(self, root: tk.Tk, parent=None):
        super().__init__(parent or root, padding=10)
        self.root = root
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.v = {}
        self.preview_img = None
        self.busy = False

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self._build_controls(left)

        right = ttk.LabelFrame(self, text="Preview", padding=6)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.canvas = tk.Label(right, text="Press Preview to render the part\nin SolidCraft",
                               anchor="center", background="#eef0f3")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.info = ttk.Label(right, text="", justify="left")
        self.info.grid(row=1, column=0, sticky="w", pady=(6, 0))

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bar.columnconfigure(0, weight=1)
        self.status = ttk.Label(bar, text=self._sc_status())
        self.status.grid(row=0, column=0, sticky="w")
        self.b_locate = ttk.Button(bar, text="Locate SolidCraft…", command=self.locate)
        self.b_locate.grid(row=0, column=1, padx=4)
        self.b_install = ttk.Button(bar, text="Install as SolidCraft plugin", command=self.install)
        if self._can_install():
            self.b_install.grid(row=0, column=5, padx=(12, 0))
        self.b_prev = ttk.Button(bar, text="Preview", command=self.preview)
        self.b_prev.grid(row=0, column=2, padx=4)
        self.b_save = ttk.Button(bar, text="Save STL", command=self.save)
        self.b_save.grid(row=0, column=3, padx=4)
        self.b_open = ttk.Button(bar, text="Open in SolidCraft", command=self.open_sc)
        self.b_open.grid(row=0, column=4, padx=4)
        self._refresh_sc()

        self._on_standard()
        self._on_part()

    # -- layout ---------------------------------------------------------------
    def _var(self, key, value="", kind=tk.StringVar):
        var = kind(value=value)
        self.v[key] = var
        return var

    def _row(self, parent, r, label, widget, help_key=None, unit=""):
        lab = ttk.Label(parent, text=label)
        lab.grid(row=r, column=0, sticky="w", pady=2)
        widget.grid(row=r, column=1, sticky="ew", pady=2)
        if unit:
            ttk.Label(parent, text=unit, foreground="#666").grid(row=r, column=2, sticky="w", padx=(4, 0))
        if help_key:
            Tip(lab, HELP[help_key])
            Tip(widget, HELP[help_key])
        return widget

    def _entry(self, parent, key, value="", width=10):
        return ttk.Entry(parent, textvariable=self._var(key, value), width=width)

    def _build_controls(self, f):
        # part
        g = ttk.LabelFrame(f, text="Part", padding=6)
        g.grid(row=0, column=0, sticky="ew")
        self._var("part", "pair")
        for i, p in enumerate(tg.PART_TYPES):
            ttk.Radiobutton(g, text=tg.PART_LABELS[p], value=p, variable=self.v["part"],
                            command=self._on_part).grid(row=i, column=0, sticky="w")

        # thread
        g = ttk.LabelFrame(f, text="Thread", padding=6)
        g.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        g.columnconfigure(1, weight=1)
        std = ttk.Combobox(g, textvariable=self._var("standard", "ISO metric coarse"),
                           values=list(tg.STANDARDS) + [CUSTOM], state="readonly", width=24)
        std.bind("<<ComboboxSelected>>", lambda e: self._on_standard())
        self._row(g, 0, "Standard", std)
        self.size_cb = ttk.Combobox(g, textvariable=self._var("size", "M10"), state="readonly", width=24)
        self.size_cb.bind("<<ComboboxSelected>>", lambda e: self._on_size())
        self._row(g, 1, "Size", self.size_cb)
        self.e_d = self._row(g, 2, "Diameter", self._entry(g, "diameter", "10"), unit="mm")
        self.e_p = self._row(g, 3, "Pitch", self._entry(g, "pitch", "1.5"), "pitch", "mm")
        prof = ttk.Combobox(g, textvariable=self._var("profile", tg.PROFILE_LABELS["iso"]),
                            values=list(tg.PROFILE_LABELS.values()), state="readonly", width=24)
        self._row(g, 4, "Profile", prof)
        self._row(g, 5, "Starts", ttk.Spinbox(g, from_=1, to=8, width=8,
                                               textvariable=self._var("starts", "1")), "starts")
        self._row(g, 6, "Depth", self._entry(g, "depth", ""), "depth", "mm (blank = auto)")
        ttk.Checkbutton(g, text="Left-hand thread", variable=self._var("left", False, tk.BooleanVar)
                        ).grid(row=7, column=1, sticky="w")

        # fit
        g = ttk.LabelFrame(f, text="Fit & print", padding=6)
        g.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        g.columnconfigure(1, weight=1)
        self._row(g, 0, "Clearance", self._entry(g, "clearance", "0.15"), "clearance", "mm per part")
        self._row(g, 1, "Chamfer", self._entry(g, "chamfer", ""), "chamfer", "mm (blank = auto)")
        self._row(g, 2, "Quality", ttk.Combobox(g, textvariable=self._var("quality", "normal"),
                                                 values=list(tg.QUALITY), state="readonly", width=10))

        # dimensions
        g = ttk.LabelFrame(f, text="Dimensions (blank = standard)", padding=6)
        g.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        g.columnconfigure(1, weight=1)
        self.dim_rows = {}
        shapes = ("hex", "round", "square")
        items = [
            ("length", "Length", self._entry(g, "length", "20"), "mm"),
            ("shank", "Plain shank", self._entry(g, "shank", "0"), "mm"),
            ("head_shape", "Head shape", ttk.Combobox(g, textvariable=self._var("head_shape", "hex"),
                                                       values=shapes, state="readonly", width=8), ""),
            ("head_flats", "Head width", self._entry(g, "head_flats"), "mm"),
            ("head_height", "Head height", self._entry(g, "head_height"), "mm"),
            ("nut_shape", "Nut shape", ttk.Combobox(g, textvariable=self._var("nut_shape", "hex"),
                                                     values=shapes, state="readonly", width=8), ""),
            ("nut_flats", "Nut width", self._entry(g, "nut_flats"), "mm"),
            ("nut_height", "Nut height", self._entry(g, "nut_height"), "mm"),
        ]
        for r, (key, label, w, unit) in enumerate(items):
            lab = ttk.Label(g, text=label)
            un = ttk.Label(g, text=unit, foreground="#666")
            self.dim_rows[key] = (lab, w, un, r)

        # output
        g = ttk.LabelFrame(f, text="Output folder", padding=6)
        g.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        g.columnconfigure(0, weight=1)
        ttk.Entry(g, textvariable=self._var("out", tg.load_settings().get("out_dir") or DEFAULT_OUT), width=32).grid(row=0, column=0, sticky="ew")
        ttk.Button(g, text="…", width=3, command=self._browse).grid(row=0, column=1, padx=(4, 0))

    # -- events -------------------------------------------------------------
    def _sc_status(self):
        sc = tg.find_solidcraft()
        return "SolidCraft found" if sc["cli"] else "SolidCraft not found: Save STL still works without it"

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.v["out"].get() or DEFAULT_OUT)
        if d:
            self.v["out"].set(d)
            tg.save_settings(out_dir=d)

    def _refresh_sc(self):
        found = bool(tg.find_solidcraft()["cli"])
        self.status.configure(text=self._sc_status())
        for b in (self.b_prev, self.b_open):
            b.state(["!disabled"] if found else ["disabled"])
        if found:
            self.b_locate.grid_remove()
        else:
            self.b_locate.grid()

    def _can_install(self):
        """Offered by the .exe when it is not already running from the plugins folder."""
        folder = tg.plugin_folder()
        if not getattr(sys, "frozen", False) or not folder:
            return False
        here = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.normcase(here) != os.path.normcase(os.path.abspath(folder))

    def install(self):
        files = [sys.executable] + [os.path.join(HERE, f) for f in ("README.md", "LICENSE")
                                    if os.path.isfile(os.path.join(HERE, f))]
        try:
            dest = tg.install_plugin(files)
        except (OSError, RuntimeError) as e:
            messagebox.showerror("Thread Generator", f"Could not install: {e}")
            return
        self.b_install.grid_remove()
        messagebox.showinfo("Thread Generator",
                            f"Installed in {dest}.\n\nIt now shows in SolidCraft under "
                            "Preferences > Plugins. You can start it from that folder.")

    def locate(self):
        d = filedialog.askdirectory(title="Folder that contains solidcraft-cli.exe")
        if not d:
            return
        if not os.path.isfile(os.path.join(d, "solidcraft-cli.exe")):
            messagebox.showerror("Thread Generator", "solidcraft-cli.exe is not in that folder.")
            return
        tg.save_settings(solidcraft_home=d)
        self._refresh_sc()

    def _on_standard(self):
        std = self.v["standard"].get()
        if std == CUSTOM:
            self.size_cb.configure(values=[], state="disabled")
            self.v["size"].set("")
            return
        table, kind = tg.STANDARDS[std]
        self.size_cb.configure(values=list(table), state="readonly")
        if self.v["size"].get() not in table:
            self.v["size"].set("M10" if "M10" in table else next(iter(table)))
        self.v["profile"].set(tg.PROFILE_LABELS[kind])
        self._on_size()

    def _on_size(self):
        std = self.v["standard"].get()
        if std == CUSTOM:
            return
        table, _ = tg.STANDARDS[std]
        d, p = table[self.v["size"].get()]
        self.v["diameter"].set(f"{d:g}")
        self.v["pitch"].set(f"{p:.4g}")

    def _on_part(self):
        part = self.v["part"].get()
        show = {
            "bolt": ("length", "shank", "head_shape", "head_flats", "head_height"),
            "rod": ("length",),
            "nut": ("nut_shape", "nut_flats", "nut_height"),
            "pair": ("length", "shank", "head_shape", "head_flats", "head_height",
                     "nut_shape", "nut_flats", "nut_height"),
            "cutter": ("length",),
        }[part]
        for key, (lab, w, un, r) in self.dim_rows.items():
            if key in show:
                lab.grid(row=r, column=0, sticky="w", pady=2)
                w.grid(row=r, column=1, sticky="ew", pady=2)
                un.grid(row=r, column=2, sticky="w", padx=(4, 0))
            else:
                lab.grid_remove(); w.grid_remove(); un.grid_remove()

    # -- spec ---------------------------------------------------------------
    def _num(self, key, label, optional=False, integer=False):
        s = self.v[key].get().strip().replace(",", ".")
        if not s:
            if optional:
                return None
            raise ValueError(f"{label} is required")
        try:
            return int(s) if integer else float(s)
        except ValueError:
            raise ValueError(f"{label} must be a number") from None

    def spec(self) -> tg.ThreadSpec:
        prof_label = self.v["profile"].get()
        profile = next(k for k, v in tg.PROFILE_LABELS.items() if v == prof_label)
        std = self.v["standard"].get()
        size = self.v["size"].get() if std != CUSTOM else ""
        d = self._num("diameter", "Diameter")
        p = self._num("pitch", "Pitch")
        if size:
            d0, p0 = tg.STANDARDS[std][0][size]
            if abs(d - d0) > 1e-6 or abs(p - p0) > 1e-4:
                size = ""  # edited away from the standard size
        return tg.ThreadSpec(
            part=self.v["part"].get(), diameter=d, pitch=p, profile=profile,
            starts=self._num("starts", "Starts", integer=True),
            left_hand=self.v["left"].get(),
            depth=self._num("depth", "Depth", optional=True),
            clearance=self._num("clearance", "Clearance"),
            length=self._num("length", "Thread length"),
            shank=self._num("shank", "Plain shank", optional=True) or 0.0,
            head_shape=self.v["head_shape"].get(),
            head_flats=self._num("head_flats", "Head width", optional=True),
            head_height=self._num("head_height", "Head height", optional=True),
            nut_shape=self.v["nut_shape"].get(),
            nut_flats=self._num("nut_flats", "Nut width", optional=True),
            nut_height=self._num("nut_height", "Nut height", optional=True),
            chamfer=self._num("chamfer", "Chamfer", optional=True),
            quality=self.v["quality"].get(), size=size)

    # -- actions ------------------------------------------------------------
    def _work(self, label, fn, done):
        if self.busy:
            return
        try:
            spec = self.spec()
            spec.resolved()
        except (ValueError, StopIteration) as e:
            messagebox.showerror("Thread Generator", str(e))
            return
        self.busy = True
        for b in (self.b_prev, self.b_save, self.b_open):
            b.state(["disabled"])
        self.status.configure(text=label)
        self.root.configure(cursor="watch")

        box = []

        def run():
            try:
                box.append((fn(spec), None))
            except Exception as e:  # report anything to the user
                box.append((None, e))

        def poll():
            if box:
                finish(*box[0])
            else:
                self.root.after(50, poll)

        def finish(res, err):
            self.busy = False
            self.b_save.state(["!disabled"])
            self._refresh_sc()
            self.root.configure(cursor="")
            if err:
                self.status.configure(text="Failed")
                messagebox.showerror("Thread Generator", str(err))
            else:
                done(res)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(50, poll)

    def _describe(self, res):
        lines = []
        for p in res["parts"]:
            sx, sy, sz = p["size_mm"]
            ok = "OK" if p["closed"] else "WARNING: " + p["check"]
            lines.append(f"{os.path.basename(p['file'])}:  {sx:g} x {sy:g} x {sz:g} mm,  "
                         f"{p['volume_mm3'] / 1000:.2f} cm³,  {p['triangles']:,} triangles,  {ok}")
        s = res["spec"]
        lines.append(f"Ø{s['diameter']:g} mm, pitch {s['pitch']:g} mm, depth {s['depth']:.3g} mm, "
                     f"clearance {s['clearance']:g} mm" + (", left-hand" if s["left_hand"] else ""))
        return "\n".join(lines)

    def preview(self):
        tmp = os.path.join(tempfile.gettempdir(), "solidcraft_threadgen_preview")

        w = max(320, self.canvas.winfo_width() - 4)
        h = max(260, self.canvas.winfo_height() - 4)

        def fn(spec):
            res = tg.generate(spec, tmp, design=True)
            res["png"] = tg.snapshot(res["design"], os.path.join(tmp, "preview.png"), w, h)
            return res

        def done(res):
            self.preview_img = tk.PhotoImage(file=res["png"])
            self.canvas.configure(image=self.preview_img, text="")
            self.info.configure(text=self._describe(res))
            self.status.configure(text="Preview ready")

        self._work("Rendering preview…", fn, done)

    def save(self):
        out = self.v["out"].get() or DEFAULT_OUT

        def done(res):
            self.info.configure(text=self._describe(res))
            self.status.configure(text=f"Saved to {out}")
            if sys.platform == "win32":
                os.startfile(out)

        self._work("Saving…", lambda spec: tg.generate(spec, out), done)

    def open_sc(self):
        out = self.v["out"].get() or DEFAULT_OUT

        def fn(spec):
            res = tg.generate(spec, out, design=True)
            tg.open_in_solidcraft(res["design"])
            return res

        def done(res):
            self.info.configure(text=self._describe(res))
            self.status.configure(text=f"Opened {os.path.basename(res['design'])} in SolidCraft")

        self._work("Opening in SolidCraft…", fn, done)


class FaceTab(ttk.Frame):
    """Cuts a thread with print clearance into the face selected in SolidCraft."""

    # SolidCraft's Thread cuts 60° threads from an "M<diameter>x<pitch>" designation,
    # so ISO metric and UNC sizes work; trapezoidal ones don't.
    STANDARDS = ("ISO metric coarse", "ISO metric fine", "UNC (inch)")
    CLEARANCES = ("0", "0.1", "0.15", "0.2", "0.25", "0.3", "0.4")

    def __init__(self, root: tk.Tk, parent):
        super().__init__(parent, padding=12)
        self.root = root
        self.v = {}
        self.busy = False
        self.face = None  # the face "Use selected face" read
        self.columnconfigure(2, weight=1)
        var = lambda k, val="", kind=tk.StringVar: self.v.setdefault(k, kind(value=val))

        ttk.Label(self, text="1.  In SolidCraft, select a shaft's round face or the inside of a hole.",
                  wraplength=360, justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
        self.b_use = ttk.Button(self, text="Use selected face", command=self.use_face)
        self.b_use.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 2))
        self.face_lbl = ttk.Label(self, text="No face yet.", foreground="#555",
                                  wraplength=360, justify="left")
        self.face_lbl.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(self, text="2.  Choose the thread.").grid(row=3, column=0, columnspan=3, sticky="w")
        r = 4
        std = ttk.Combobox(self, textvariable=var("standard", "ISO metric coarse"),
                           values=self.STANDARDS, state="readonly", width=20)
        std.bind("<<ComboboxSelected>>", lambda e: self._on_standard())
        self._row(r, "Standard", std); r += 1
        self.size_cb = ttk.Combobox(self, textvariable=var("size", "M10"), state="readonly", width=20)
        self.size_cb.bind("<<ComboboxSelected>>", lambda e: self._on_size())
        self._row(r, "Size", self.size_cb); r += 1
        self._row(r, "Diameter", ttk.Entry(self, textvariable=var("diameter", "10"), width=10), "mm"); r += 1
        self._row(r, "Pitch", ttk.Entry(self, textvariable=var("pitch", "1.5"), width=10), "mm"); r += 1
        cl = ttk.Combobox(self, textvariable=var("clearance", "0.2"), values=self.CLEARANCES, width=8)
        self._row(r, "Clearance", cl, "mm per side"); r += 1
        Tip(cl, "How much looser than nominal, on each side (radius).\n"
                "Bolts get 2x this smaller in diameter, holes 2x larger.\n"
                "Printed bolt + printed nut: give both a clearance.\n"
                "FDM: 0.1-0.2 per part. Resin: 0.05-0.1.")
        self._row(r, "Length", ttk.Entry(self, textvariable=var("length", ""), width=10),
                  "mm (blank = whole face)"); r += 1

        self.b_add = ttk.Button(self, text="Add thread", command=self.add)
        self.b_add.grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 4)); r += 1
        self.status = ttk.Label(self, text="", wraplength=360, justify="left")
        self.status.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        ttk.Checkbutton(self, text="Keep this window on top", variable=var("ontop", True, tk.BooleanVar),
                        command=lambda: root.attributes("-topmost", self.v["ontop"].get())
                        ).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 0))
        root.attributes("-topmost", True)
        self._on_standard()

    def _row(self, r, label, widget, unit=""):
        ttk.Label(self, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="w", pady=2)
        if unit:
            ttk.Label(self, text=unit, foreground="#666").grid(row=r, column=2, sticky="w", padx=(4, 0))

    def _on_standard(self):
        table, _ = tg.STANDARDS[self.v["standard"].get()]
        self.size_cb.configure(values=list(table))
        if self.v["size"].get() not in table:
            self.v["size"].set("M10" if "M10" in table else next(iter(table)))
        self._on_size()

    def _on_size(self):
        d, p = tg.STANDARDS[self.v["standard"].get()][0][self.v["size"].get()]
        self.v["diameter"].set(f"{d:g}")
        self.v["pitch"].set(f"{p:.4g}")

    def _pick_size(self, d, p):
        """Select the standard size matching diameter d and pitch p, if there is one."""
        for std in self.STANDARDS:
            for name, (d0, p0) in tg.STANDARDS[std][0].items():
                if abs(d0 - d) < 0.01 and abs(p0 - p) < 0.001:
                    self.v["standard"].set(std)
                    self._on_standard()
                    self.v["size"].set(name)
                    self._on_size()
                    return
        self.v["diameter"].set(f"{d:g}")
        self.v["pitch"].set(f"{p:g}")

    def _num(self, key, label, optional=False):
        s = self.v[key].get().strip().replace(",", ".")
        if not s and optional:
            return None
        try:
            x = float(s)
        except ValueError:
            raise ValueError(f"{label} must be a number") from None
        if x < 0 or (x == 0 and key != "clearance"):
            raise ValueError(f"{label} must be more than 0")
        return x

    def _bg(self, label, fn, done):
        if self.busy:
            return
        self.busy = True
        for b in (self.b_use, self.b_add):
            b.state(["disabled"])
        self.status.configure(text=label, foreground="")
        box = []

        def run():
            try:
                with sc_live.Client() as c:
                    box.append((fn(c), None))
            except Exception as e:  # shown to the user
                box.append((None, e))

        def poll():
            if not box:
                self.root.after(80, poll)
                return
            self.busy = False
            for b in (self.b_use, self.b_add):
                b.state(["!disabled"])
            res, err = box[0]
            if err:
                self.status.configure(text=str(err), foreground="#b00020")
            else:
                done(res)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(80, poll)

    @staticmethod
    def _describe(info):
        kind = "Hole (internal thread)" if info["internal"] else "Shaft (external thread)"
        length = info["end"] - info["start"]
        return (f"{kind} on {info['body']}: fits {info['designation']} "
                f"(Ø{info['major_diameter']:g} mm), {length:g} mm long.")

    def use_face(self):
        def fn(c):
            face = sc_live.selected_face(c)
            info = sc_live.probe_face(c, face)
            info["face"] = face
            return info

        def done(info):
            self.face = info["face"]
            self.face_lbl.configure(text=self._describe(info), foreground="")
            self._pick_size(info["major_diameter"], info["pitch"])
            self.status.configure(text="")

        self._bg("Reading the selection…", fn, done)

    def add(self):
        try:
            d = self._num("diameter", "Diameter")
            p = self._num("pitch", "Pitch")
            clearance = self._num("clearance", "Clearance")
            length = self._num("length", "Length", optional=True)
        except ValueError as e:
            self.status.configure(text=str(e), foreground="#b00020")
            return
        if clearance > p / 3:
            self.status.configure(text=f"Clearance can be at most {p / 3:.2f} mm for this pitch.",
                                  foreground="#b00020")
            return

        remembered = self.face

        def fn(c):
            # the face selected now, else the one from "Use selected face"
            try:
                face = sc_live.selected_face(c)
            except RuntimeError:
                if not remembered:
                    raise
                face = remembered
            info = sc_live.probe_face(c, face)
            res = sc_live.add_thread(c, face, d, p, clearance, info["internal"], length)
            res["info"] = info
            return res

        def done(res):
            self.face = None  # the thread replaced that face
            self.face_lbl.configure(text=self._describe(res["info"]), foreground="")
            self.status.configure(
                text=f"Added “{res['name']}” (cut as {res['designation']}). "
                     "Undo with Ctrl+Z in SolidCraft. Select another face to add more.",
                foreground="#1b7f3b")

        self._bg("Cutting the thread… (a few seconds)", fn, done)


def run_gui():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    root.title(f"SolidCraft Thread Generator {tg.__version__}")
    icon = os.path.join(HERE, "icon.ico")
    if os.path.isfile(icon):
        try:
            root.iconbitmap(icon)
        except tk.TclError:
            pass
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    tabs = ttk.Notebook(root)
    tabs.grid(sticky="nsew")
    face = FaceTab(root, tabs)
    parts = App(root, tabs)
    tabs.add(face, text="Thread a face in SolidCraft")
    tabs.add(parts, text="Make parts (STL)")
    # window size per tab: the face panel opens small, beside SolidCraft
    root.update_idletasks()
    sizes = {0: f"{face.winfo_reqwidth() + 40}x{face.winfo_reqheight() + 70}"}
    root.geometry(sizes[0])

    def on_tab(_):
        cur = tabs.index("current")
        root.attributes("-topmost", cur == 0 and face.v["ontop"].get())
        root.minsize(*((300, 300) if cur == 0 else (900, 560)))
        if sizes.get(cur):
            root.geometry(sizes[cur])
        elif cur == 1:
            root.geometry("")  # natural size of the parts tab

    ready = []  # sizes seen while the window first appears are not the user's

    def remember(_):
        if ready and root.state() == "normal":
            sizes[tabs.index("current")] = f"{root.winfo_width()}x{root.winfo_height()}"

    tabs.bind("<<NotebookTabChanged>>", on_tab)
    root.bind("<Configure>", lambda e: e.widget is root and remember(e))

    def settle():
        root.geometry(sizes[0])
        root.after(300, lambda: ready.append(True))

    root.after(200, settle)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
