"""Light and dark looks for the generator's window, following SolidCraft.

The palette `PAL` is filled in by `apply()`; widgets read their colours from it.
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

# Close to SolidCraft's own dark theme (panels, fields, accent blue).
DARK = {
    "dark": True,
    "bg": "#24272e", "panel": "#2b2f37", "field": "#1b1d22", "fg": "#e4e7eb",
    "dim": "#9aa2ad", "border": "#3d424c", "accent": "#4d8dff", "accent_fg": "#ffffff",
    "hover": "#343944", "ok": "#5fd38d", "err": "#ff7a7a", "warn": "#f0b45a",
    "tip_bg": "#33373f", "tip_fg": "#e4e7eb", "preview_bg": "#2b2f37",
    "bolt": "#7f97b8", "nut": "#5b6676", "gap": "#f0b45a", "gap_dim": "#7a5a2c",
    "line": "#c9ced6", "bolt_text": "#14171c", "nut_text": "#e4e7eb",
}
LIGHT = {
    "dark": False,
    "bg": "#f0f0f0", "panel": "#ffffff", "field": "#ffffff", "fg": "#1f2328",
    "dim": "#666666", "border": "#c8c8c8", "accent": "#2f6fdb", "accent_fg": "#ffffff",
    "hover": "#e5e5e5", "ok": "#1b7f3b", "err": "#b00020", "warn": "#9a6400",
    "tip_bg": "#ffffe0", "tip_fg": "#1f2328", "preview_bg": "#eef0f3",
    "bolt": "#9db3d3", "nut": "#c3c9d2", "gap": "#f5a623", "gap_dim": "#f6dcae",
    "line": "#3a3f47", "bolt_text": "#1f2328", "nut_text": "#1f2328",
}

PAL: dict = dict(LIGHT)


def solidcraft_is_dark() -> bool | None:
    """SolidCraft's theme, read from the running app (None if it isn't running)."""
    try:
        import sc_live
        with sc_live.Client(timeout=5) as c:
            prefs = c.call("ui.prefs", {}) or {}  # no settings given: reads only
        dark = prefs.get("dark")
        return bool(dark) if dark is not None else None
    except Exception:
        return None


def windows_is_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def detect() -> bool:
    dark = solidcraft_is_dark()
    return windows_is_dark() if dark is None else dark


def _dark_title_bar(root: tk.Tk, dark: bool):
    if sys.platform != "win32":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                         ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def apply(root: tk.Tk, dark: bool | None = None) -> dict:
    """Style the window light or dark (default: as SolidCraft, else as Windows)."""
    if dark is None:
        dark = detect()
    PAL.clear()
    PAL.update(DARK if dark else LIGHT)
    p = PAL
    style = ttk.Style(root)
    if not dark:
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        root.configure(bg=p["bg"])
        _dark_title_bar(root, False)
        return p

    style.theme_use("clam")
    root.configure(bg=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["field"], selectbackground=p["accent"],
                    selectforeground=p["accent_fg"], insertcolor=p["fg"], focuscolor=p["accent"])
    style.map(".", foreground=[("disabled", p["dim"])])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"])
    style.configure("TButton", background=p["panel"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["panel"], darkcolor=p["panel"], padding=(10, 4))
    style.map("TButton", background=[("disabled", p["bg"]), ("pressed", p["accent"]),
                                     ("active", p["hover"])],
              foreground=[("disabled", p["dim"]), ("pressed", p["accent_fg"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    lightcolor=p["accent"], darkcolor=p["accent"], bordercolor=p["accent"])
    style.map("Accent.TButton", background=[("disabled", p["panel"]), ("active", "#3b7cf0")])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(w, fieldbackground=p["field"], foreground=p["fg"], background=p["panel"],
                        bordercolor=p["border"], lightcolor=p["field"], darkcolor=p["field"],
                        arrowcolor=p["fg"], insertcolor=p["fg"])
        style.map(w, fieldbackground=[("readonly", p["field"]), ("disabled", p["bg"])],
                  foreground=[("disabled", p["dim"]), ("readonly", p["fg"])],
                  bordercolor=[("focus", p["accent"])],
                  background=[("active", p["hover"]), ("pressed", p["hover"]),
                              ("readonly", p["panel"]), ("!disabled", p["panel"])],
                  arrowcolor=[("disabled", p["dim"]), ("!disabled", p["fg"])])
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"],
                    indicatorbackground=p["field"], indicatorforeground=p["accent_fg"])
    style.map("TCheckbutton", background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"],
                    indicatorbackground=p["field"], indicatorforeground=p["accent_fg"])
    style.map("TRadiobutton", background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"])])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"],
                    lightcolor=p["bg"], darkcolor=p["bg"], tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=p["panel"], foreground=p["dim"],
                    bordercolor=p["border"], lightcolor=p["panel"], darkcolor=p["panel"],
                    padding=(12, 5))
    style.map("TNotebook.Tab", background=[("selected", p["bg"])],
              foreground=[("selected", p["fg"])], lightcolor=[("selected", p["bg"])])
    style.configure("Vertical.TScrollbar", background=p["panel"], arrowcolor=p["fg"])
    # the drop-down lists of comboboxes are plain Tk listboxes
    root.option_add("*TCombobox*Listbox.background", p["field"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])
    _dark_title_bar(root, True)
    return p
