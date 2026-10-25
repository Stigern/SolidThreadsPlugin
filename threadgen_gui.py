"""Window for the SolidCraft thread generator."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import repair
import sc_live
import theme
import threadgen as tg
from theme import PAL

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
        tk.Label(self.win, text=self.text, justify="left", background=PAL["tip_bg"], foreground=PAL["tip_fg"],
                 relief="solid", borderwidth=1, padx=6, pady=4,
                 highlightbackground=PAL["border"]).pack()

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
                               anchor="center", background=PAL["preview_bg"], foreground=PAL["dim"])
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
            ttk.Label(parent, text=unit, foreground=PAL["dim"]).grid(row=r, column=2, sticky="w", padx=(4, 0))
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
            un = ttk.Label(g, text=unit, foreground=PAL["dim"])
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


class ThreadDiagram(tk.Canvas):
    """A to-scale section through a bolt and nut with the current settings.

    Two pitches of the ISO basic profile along the axis: the nut on top, the bolt
    below, the gap between them coloured. Each setting has its own mark (pitch,
    height, grip, tolerance gap, nominal diameter); the one being hovered or
    edited is drawn in the accent colour."""

    def __init__(self, parent):
        self.s = float(parent.tk.call("tk", "scaling")) / (96 / 72)  # 1 at 96 dpi
        self.W, self.H = int(430 * self.s), int(222 * self.s)
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0,
                         background=PAL["bg"])

    def _font(self, on, size=8):
        return ("Segoe UI", size, "bold" if on else "normal")

    def draw(self, d, p, o, height, key=None):
        s, P = self.s, p
        self.delete("all")
        geo_b = sc_live.thread_geometry(d, p, o, False, height)
        geo_n = sc_live.thread_geometry(d, p, o, True, height)
        R = d / 2
        h0 = sc_live.ISO_HEIGHT * p
        trim = (1 - height) * h0
        b_crest = R - o / 2 - trim            # shaft surface
        n_crest = R + o / 2 - h0 + trim       # hole surface

        def basic(z):  # ISO basic profile: crest flat P/8 at R, root flat P/4 at R - h0
            u = z % P
            u = min(u, P - u)
            if u <= P / 16:
                return R
            if u <= 0.375 * P:
                return R - (u - P / 16) * h0 / (0.3125 * P)
            return R - h0

        x0, x1 = 46 * s, self.W - 158 * s           # plot area
        y0, y1 = 10 * s, self.H - 58 * s
        z0, z1 = -0.7 * P, 1.7 * P
        r_lo, r_hi = R - o / 2 - h0 - 0.45 * h0, R + o / 2 + 0.45 * h0
        X = lambda z: x0 + (z - z0) / (z1 - z0) * (x1 - x0)
        Y = lambda r: y0 + (r_hi - r) / (r_hi - r_lo) * (y1 - y0)
        on = lambda k: key == k
        col = lambda k: PAL["accent"] if on(k) else PAL["dim"]

        # the gap is what shows between the two parts
        self.create_rectangle(x0, y0, x1, y1, fill=PAL["gap"] if on("tolerance") else PAL["gap_dim"],
                              outline="")
        n = 240
        zs = [z0 + (z1 - z0) * i / n for i in range(n + 1)]
        nut = [(X(z), Y(max(basic(z) + o / 2, n_crest))) for z in zs]
        bolt = [(X(z), Y(min(basic(z) - o / 2, b_crest))) for z in zs]
        self.create_polygon([(x0, y0)] + nut + [(x1, y0)], fill=PAL["nut"], outline=PAL["line"])
        self.create_polygon([(x0, y1)] + bolt + [(x1, y1)], fill=PAL["bolt"], outline=PAL["line"])
        self.create_text(x0 + 5 * s, y0 + 4 * s, text="nut / hole", anchor="nw",
                         fill=PAL["nut_text"], font=self._font(False))
        self.create_text(x0 + 5 * s, y1 - 4 * s, text="bolt / shaft", anchor="sw",
                         fill=PAL["bolt_text"], font=self._font(False))

        # nominal diameter
        yR = Y(R)
        self.create_line(x0 - 6 * s, yR, x1, yR, fill=col("diameter"), dash=(3, 3),
                         width=2 if on("diameter") else 1)
        self.create_text(x0 - 8 * s, yR, text=f"Ø{d:g}", anchor="e", fill=col("diameter"),
                         font=self._font(on("diameter")))

        # pitch: crest to crest, under the drawing
        yp = y1 + 14 * s
        for z in (0, P):
            self.create_line(X(z), Y(b_crest), X(z), yp + 4 * s, fill=col("pitch"), dash=(2, 3))
        self.create_line(X(0), yp, X(P), yp, fill=col("pitch"), arrow="both",
                         width=2 if on("pitch") else 1)
        self.create_text((X(0) + X(P)) / 2, yp + 3 * s, text=f"pitch {p:g} mm", anchor="n",
                         fill=col("pitch"), font=self._font(on("pitch")))

        # height of the bolt's teeth, and the grip between the parts, on the right
        xa, xb, xt = x1 + 12 * s, x1 + 24 * s, x1 + 34 * s
        b_root = R - o / 2 - h0
        for r in (b_root, b_crest):
            self.create_line(X(P * 1.5), Y(r), xa + 4 * s, Y(r), fill=col("height"), dash=(2, 3))
        self.create_line(xa, Y(b_root), xa, Y(b_crest), fill=col("height"), arrow="both",
                         width=2 if on("height") else 1)
        self.create_text(xt, Y(b_root), text=f"height {height * h0:.2f} mm ({height:.0%})",
                         anchor="sw", fill=col("height"), font=self._font(on("height")))
        grip = b_crest - n_crest
        gcol = PAL["err"] if grip < 0.3 * h0 else col("height")
        if grip > 0:
            self.create_line(X(P * 1.1), Y(n_crest), xb + 4 * s, Y(n_crest), fill=gcol, dash=(2, 3))
            self.create_line(xb, Y(n_crest), xb, Y(b_crest), fill=gcol, width=3)
            self.create_text(xt, (Y(n_crest) + Y(b_crest)) / 2, text=f"grip {grip:.2f} mm",
                             anchor="w", fill=gcol, font=self._font(on("height")))
        else:
            self.create_text(xt, (y0 + y1) / 2, text="no grip!", anchor="w", fill=PAL["err"],
                             font=self._font(True))

        # tolerance: the gap on a flank
        zf = 0.22 * P
        yf = (Y(basic(zf) + o / 2) + Y(basic(zf) - o / 2)) / 2
        self.create_line(X(zf), yf, x1 + 8 * s, y0 + 8 * s, fill=col("tolerance"))
        tol = sc_live.tolerance_class(o)
        self.create_text(x1 + 10 * s, y0 + 8 * s, text=f"gap {tol}", anchor="w",
                         fill=col("tolerance"), font=self._font(on("tolerance")))

        # what the thread is cut as
        cut = (f"bolt {geo_b['designation']}"
               + (f" on Ø{geo_b['surface']:.3g}" if geo_b["surface"] else "")
               + f"   ·   hole {geo_n['designation']}"
               + (f" in Ø{geo_n['surface']:.3g}" if geo_n["surface"] else f" in Ø{d - p:g}"))
        self.create_text(4 * s, self.H - 2 * s, text=cut, anchor="sw", fill=PAL["dim"],
                         font=self._font(False, 7))
        if on("length"):
            self.create_text(x1, y1 + 14 * s, text="length runs along the axis →", anchor="ne",
                             fill=PAL["accent"], font=self._font(True))


class FaceTab(ttk.Frame):
    """Cuts a thread with print clearance into the face selected in SolidCraft."""

    # SolidCraft's Thread cuts 60° threads from an "M<diameter>x<pitch>" designation,
    # so ISO metric and UNC sizes work; trapezoidal ones don't.
    STANDARDS = (tg.PRINTED, "ISO metric coarse", "ISO metric fine", "UNC (inch)")
    # CustomThreads' tolerance classes: O.2 = 0.2 mm off each diameter of this part
    TOLERANCES = ("O.0  tight", "O.1", "O.15", "O.2", "O.4", "O.8  loose")
    HEIGHTS = ("100%  full", "95%", "90%", "85%", "80%", "75%", "70%  low")

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
        self.face_lbl = ttk.Label(self, text="No face yet.", foreground=PAL["dim"],
                                  wraplength=360, justify="left")
        self.face_lbl.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(self, text="2.  Choose the thread.").grid(row=3, column=0, columnspan=3, sticky="w")
        r = 4
        std = ttk.Combobox(self, textvariable=var("standard", tg.PRINTED),
                           values=self.STANDARDS, state="readonly", width=36)
        std.bind("<<ComboboxSelected>>", lambda e: self._on_standard())
        self._row(r, "Standard", std); r += 1
        std.grid_configure(columnspan=2)  # wide: keep the unit column close to the fields
        Tip(std, "3D-printed metric: ISO 60° profile with a coarse 2, 2.5, 3.5 or 5 mm pitch,\n"
                 "deep enough to print well at 0.2-0.3 mm layers (after CustomThreads).\n"
                 "The pitch follows the size (2 below M6, 2.5 to M16, 3.5 to M30, then 5)\n"
                 "until you pick one. 2 mm is experimental: M4-M5 get a thin core.\n"
                 "Standard ISO sizes fit metal screws, but their fine pitch prints poorly.")
        self.pitch_auto = True  # until the user picks a size, the pitch follows the diameter
        self.size_cb = ttk.Combobox(self, textvariable=var("size", "M10x2.5"), state="readonly", width=20)
        self.size_cb.bind("<<ComboboxSelected>>", lambda e: (setattr(self, "pitch_auto", False),
                                                             self._on_size()))
        self._row(r, "Size", self.size_cb, key="diameter"); r += 1
        self._row(r, "Diameter", ttk.Entry(self, textvariable=var("diameter", "10"), width=10), "mm",
                  key="diameter"); r += 1
        pitch = ttk.Entry(self, textvariable=var("pitch", "2.5"), width=10)
        pitch.bind("<Key>", lambda e: setattr(self, "pitch_auto", False))
        self._row(r, "Pitch", pitch, "mm", key="pitch"); r += 1
        cl = ttk.Combobox(self, textvariable=var("tolerance", "O.2"), values=self.TOLERANCES, width=10)
        self._row(r, "Tolerance", cl, "O.2 = 0.2 mm on the diameter", key="tolerance"); r += 1
        Tip(cl, "How much looser than nominal this part is, on its diameter\n"
                "(CustomThreads' classes): a bolt gets this much smaller,\n"
                "a hole this much larger. Printed bolt + printed nut: both get it.\n"
                "Start with O.2 on both; O.4 if tight, O.15 or O.1 if loose.\n"
                "Any number works too, e.g. 0.3.")
        ht = ttk.Combobox(self, textvariable=var("height", "100%  full"), values=self.HEIGHTS, width=10)
        self._row(r, "Height", ht, "how far the teeth stick out", key="height"); r += 1
        Tip(ht, "Lower teeth with flat tops: a shaft is made thinner and a hole wider\n"
                "before the thread is cut, so the teeth stick out less. The flanks\n"
                "stay put, so a bolt and nut with the same height still fit, but\n"
                "they grip over less depth (the drawing shows the grip).\n"
                "Use the same height on both parts. 80% is a good low setting;\n"
                "70% grips only about a quarter as deep as 100%.")
        self._row(r, "Length", ttk.Entry(self, textvariable=var("length", ""), width=10),
                  "mm (blank = whole face)", key="length"); r += 1

        self.diagram = ThreadDiagram(self)
        self.diagram.grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0)); r += 1
        for k in ("diameter", "pitch", "tolerance", "height"):
            self.v[k].trace_add("write", lambda *a: self._redraw())

        self.b_add = ttk.Button(self, text="Add thread", command=self.add, style="Accent.TButton")
        self.b_add.grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 4)); r += 1
        self.status = ttk.Label(self, text="", wraplength=420, justify="left")
        self.status.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1

        ttk.Separator(self).grid(row=r, column=0, columnspan=3, sticky="ew", pady=(12, 8)); r += 1
        ttk.Label(self, text="3.  Export for printing, repaired by Windows.").grid(
            row=r, column=0, columnspan=3, sticky="w"); r += 1
        exp = ttk.Frame(self)
        exp.grid(row=r, column=0, columnspan=3, sticky="w", pady=(6, 0)); r += 1
        self.b_export = ttk.Button(exp, text="Export repaired 3MF", command=self.export)
        self.b_export.grid(row=0, column=0, sticky="w")
        Tip(self.b_export, "Saves the selected body (or every body, if nothing is selected)\n"
                           "as 3MF and runs Windows' model repair on it, the same repair\n"
                           "3D Builder and the slicers' \"Fix model\" use: holes closed,\n"
                           "flipped and crossing triangles fixed. Your design in SolidCraft\n"
                           "is not changed. Saved to the output folder of the STL tab.")
        ttk.Checkbutton(exp, text="Open in slicer", variable=var("open_slicer", True, tk.BooleanVar)
                        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Checkbutton(self, text="Keep this window on top", variable=var("ontop", True, tk.BooleanVar),
                        command=lambda: root.attributes("-topmost", self.v["ontop"].get())
                        ).grid(row=r, column=0, columnspan=3, sticky="w", pady=(12, 0))
        root.attributes("-topmost", True)
        self._focus_key = None
        self._on_standard()
        self._redraw()

    def _row(self, r, label, widget, unit="", key=None):
        lab = ttk.Label(self, text=label)
        lab.grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=r, column=1, sticky="w", pady=2)
        parts = [lab, widget]
        if unit:
            un = ttk.Label(self, text=unit, foreground=PAL["dim"])
            un.grid(row=r, column=2, sticky="w", padx=(4, 0))
            parts.append(un)
        if key:  # point at this setting in the drawing while hovered or edited
            for w in parts:
                w.bind("<Enter>", lambda e, k=key: self._redraw(k), add="+")
                w.bind("<Leave>", lambda e: self._redraw(self._focus_key), add="+")
            widget.bind("<FocusIn>", lambda e, k=key: (setattr(self, "_focus_key", k),
                                                       self._redraw(k)), add="+")
            widget.bind("<FocusOut>", lambda e: (setattr(self, "_focus_key", None),
                                                 self._redraw()), add="+")

    def _height(self):
        """"80%" (or "80%  low") -> 0.8."""
        s = (self.v["height"].get().split() or [""])[0].rstrip("%").replace(",", ".")
        try:
            x = float(s)
        except ValueError:
            raise ValueError("Height must be a percentage, like 80%") from None
        if not 50 <= x <= 100:
            raise ValueError("Height must be between 50% and 100%")
        return x / 100

    def _redraw(self, key=None):
        try:
            d = float(self.v["diameter"].get().replace(",", "."))
            p = float(self.v["pitch"].get().replace(",", "."))
            o = self._tolerance()
            h = self._height()
        except (ValueError, KeyError):
            return  # half-typed value: keep the last drawing
        if d > 0 and p > 0:
            self.diagram.draw(d, p, o, h, key)

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

    def _pick_size(self, d, p, face_d=None, internal=False):
        """Select the size for the face SolidCraft measured.

        With the 3D-printed standard: a shaft's own diameter, or for a hole the
        diameter whose tap drill (diameter - pitch) the hole is. Otherwise the
        standard size matching SolidCraft's fit (d, p), if there is one."""
        if self.v["standard"].get() == tg.PRINTED and face_d:
            try:
                chosen = float(self.v["pitch"].get())
            except ValueError:
                chosen = None
            if self.pitch_auto or chosen not in tg.PRINTED_PITCHES:
                # the pitch that suits the size; for a hole the size depends on the pitch
                pitches = [p for p in tg.PRINTED_PITCHES
                           if tg.printed_pitch(round(face_d + p) if internal else round(face_d)) == p]
                pitch = pitches[0] if pitches else 2.5
            else:
                pitch = chosen
            name = f"M{round(face_d + pitch) if internal else round(face_d)}x{pitch:g}"
            if name in tg.PRINTED_METRIC:
                self.v["size"].set(name)
                self._on_size()
                return
        for std in self.STANDARDS[1:]:
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
        if x <= 0:
            raise ValueError(f"{label} must be more than 0")
        return x

    def _tolerance(self):
        """The diameter offset: "O.2" (or "O.2  tight") -> 0.2; a plain number is mm."""
        s = (self.v["tolerance"].get().split() or [""])[0].replace(",", ".")
        if s[:1] in ("O", "o"):
            s = "0" + s[1:]
        try:
            x = float(s)
        except ValueError:
            raise ValueError("Tolerance must be a class like O.2 or a number in mm") from None
        if x < 0:
            raise ValueError("Tolerance can't be negative")
        return x

    def _bg(self, label, fn, done):
        if self.busy:
            return
        self.busy = True
        for b in (self.b_use, self.b_add, self.b_export):
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
            for b in (self.b_use, self.b_add, self.b_export):
                b.state(["!disabled"])
            res, err = box[0]
            if err:
                self.status.configure(text=str(err), foreground=PAL["err"])
            else:
                done(res)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(80, poll)

    @staticmethod
    def _describe(info):
        kind = "Hole" if info["internal"] else "Shaft"
        length = info["end"] - info["start"]
        size = f"Ø{info['face_diameter']:.4g} mm, " if info.get("face_diameter") else ""
        return (f"{kind} on {info['body']}: {size}{length:g} mm long "
                f"(ISO would be {info['designation']}).")

    def _hint(self, info):
        """For a hole: the drill the chosen thread wants (diameter - pitch)."""
        if not info.get("internal") or not info.get("face_diameter"):
            return ""
        try:
            want = float(self.v["diameter"].get()) - float(self.v["pitch"].get())
        except ValueError:
            return ""
        have = info["face_diameter"]
        if abs(have - want) < 0.3:
            return ""
        return (f" Tip: for {self.v['size'].get() or 'this thread'} the hole should be "
                f"about Ø{want:g} mm; it is Ø{have:.4g} mm"
                + (", so the thread will be shallow." if have > want else "."))

    def use_face(self):
        def fn(c):
            face = sc_live.selected_face(c)
            info = sc_live.probe_face(c, face)
            info["face"] = face
            return info

        def done(info):
            self.face = info["face"]
            self._pick_size(info["major_diameter"], info["pitch"],
                            info.get("face_diameter"), info["internal"])
            self.face_lbl.configure(text=self._describe(info) + self._hint(info), foreground="")
            self.status.configure(text="")

        self._bg("Reading the selection…", fn, done)

    def add(self):
        try:
            d = self._num("diameter", "Diameter")
            p = self._num("pitch", "Pitch")
            offset = self._tolerance()
            height = self._height()
            length = self._num("length", "Length", optional=True)
        except ValueError as e:
            self.status.configure(text=str(e), foreground=PAL["err"])
            return
        if offset > p / 2:
            self.status.configure(text=f"Tolerance can be at most {p / 2:g} mm for this pitch.",
                                  foreground=PAL["err"])
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
            res = sc_live.add_thread(c, face, d, p, offset, info["internal"], length,
                                     height=height, info=info)
            res["info"] = info
            return res

        def done(res):
            self.face = None  # the thread replaced that face
            self.face_lbl.configure(text=self._describe(res["info"]), foreground="")
            how = f"cut as {res['designation']}"
            if res.get("surface"):
                kind = "hole" if res["info"]["internal"] else "shaft"
                how += f", {kind} set to Ø{res['surface']:.3g} mm first"
            undo = "Ctrl+Z twice" if res.get("steps", 1) > 1 else "Ctrl+Z"
            self.status.configure(
                text=f"Added “{res['name']}” ({how}). Undo with {undo} in SolidCraft. "
                     "Select another face to add more.",
                foreground=PAL["ok"])

        self._bg("Cutting the thread… (a few seconds)", fn, done)

    def export(self):
        out_dir = tg.load_settings().get("out_dir") or DEFAULT_OUT
        open_slicer = self.v["open_slicer"].get()

        def fn(c):
            sel = (c.call("ui.selection") or {}).get("selection") or []
            bodies = sorted({s["body"] for s in sel if s.get("body")})
            doc = c.call("document.inspect") or {}
            name = str(doc.get("name") or doc.get("title") or "design")
            stem = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in
                           (name + ("_" + "_".join(bodies) if bodies else ""))).strip() or "design"
            os.makedirs(out_dir, exist_ok=True)
            raw = os.path.join(tempfile.gettempdir(), "threadgen_export_raw.3mf")
            params = {"path": raw, "format": "3mf"}
            if bodies:
                params["bodies"] = bodies
            c.execute("file.save_mesh", params)
            dst = os.path.join(out_dir, f"{stem}_repaired.3mf")
            k = 2
            while os.path.exists(dst):
                dst = os.path.join(out_dir, f"{stem}_repaired ({k}).3mf")
                k += 1
            res = repair.repair_file(raw, dst)
            res["bodies"] = bodies
            return res

        def done(res):
            b, a = res["before"], res["after"]
            what = ", ".join(res["bodies"]) if res["bodies"] else "all bodies"
            if b["problems"]:
                fixed = (f"{b['problems']} problem(s) found "
                         f"({b['open_edges']} open, {b['flipped_edges']} flipped, "
                         f"{b['non_manifold_edges']} non-manifold edges), {a['problems']} left")
            else:
                fixed = "no holes or flipped faces found"
            cleaned = res["windows"]["triangles_before"] - res["windows"]["triangles_after"]
            if cleaned:
                fixed += f"; Windows cleaned up {cleaned:,} triangles"
            self.status.configure(
                text=f"Exported {what} to {os.path.basename(res['path'])}: {fixed}.",
                foreground=PAL["err"] if a["problems"] else PAL["ok"])
            if open_slicer and sys.platform == "win32":
                try:
                    os.startfile(res["path"])  # the app 3MF files open with, usually the slicer
                except OSError as e:
                    self.status.configure(text=self.status.cget("text") + f" (couldn't open it: {e})")

        self._bg("Exporting and repairing… (can take a little while)", fn, done)


def run_gui():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    theme.apply(root)  # dark or light, as SolidCraft (or Windows) is
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
