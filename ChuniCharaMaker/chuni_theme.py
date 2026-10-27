# Chuni Chara Maker
# Copyright (C) 2026 Chuni Chara Maker contributors
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Look & feel for Chuni Chara Maker: a dark "arcade cabinet at night" theme built on ttk's clam engine.

Colours
  BG      window surface (deep indigo)        WELL    sunken areas: lists, entries, picture area
  HEAD    darker header / status strips       LINE    borders
  TEXT / MUTED                                ACCENT  selection + focus (blue)
  PRIMARY the one bright button (Save)        BOX[k]  the three crop-box colours, reused in the UI
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#1d2133"
HEAD = "#151827"
WELL = "#262b42"
LINE = "#363d5c"
TEXT = "#e8ebf5"
MUTED = "#98a0bc"
ACCENT = "#5b8cff"
ACCENT_DIM = "#3a4f8f"
PRIMARY = "#ffc61a"
PRIMARY_HI = "#ffd556"
PRIMARY_INK = "#1b1500"
DANGER = "#ff7a7a"
OK = "#62d796"
WARN = "#ffb84d"
CANVAS = "#12141f"
CHECK_A = (38, 42, 62)
CHECK_B = (48, 53, 77)
BOX = {"00": "#3fa7ff", "01": "#ff9f1c", "02": "#2ee59d"}


def _family(candidates, fallback):
    try:
        have = set(tkfont.families())
    except tk.TclError:
        return fallback
    for c in candidates:
        if c in have:
            return c
    return fallback


def apply(root: tk.Tk, ui: float = 1.0) -> dict:
    """Install the theme. Returns the font tuples used, for widgets that take a font directly."""
    style = ttk.Style(root)
    style.theme_use("clam")
    body = _family(["Segoe UI", "Noto Sans", "DejaVu Sans"], "TkDefaultFont")
    disp = _family(["Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold", "Noto Sans", "DejaVu Sans"], body)
    disp_weight = "normal" if "Bahnschrift SemiBold" == disp else "bold"
    F = {
        "body": (body, 10),
        "small": (body, 9),
        "bold": (body, 10, "bold"),
        "head": (disp, 14, disp_weight),
        "step": (disp, 14, disp_weight),
        "title": (disp, 15, disp_weight),
        "primary": (disp, 13, disp_weight),
        "chip": (body, 9, "bold"),
    }
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=body, size=10)
        except tk.TclError:
            pass

    root.configure(background=BG)
    root.option_add("*TCombobox*Listbox.background", WELL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", F["body"])
    root.option_add("*Toplevel.background", BG)

    pad = max(4, int(5 * ui))
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=WELL, bordercolor=LINE,
                    lightcolor=LINE, darkcolor=LINE, troughcolor=WELL, focuscolor=ACCENT,
                    selectbackground=ACCENT, selectforeground="#ffffff", insertcolor=TEXT,
                    font=F["body"], arrowcolor=MUTED)
    style.map(".", foreground=[("disabled", "#5d6482")])

    # frames + labels
    style.configure("TFrame", background=BG)
    style.configure("Header.TFrame", background=HEAD)
    style.configure("Header.TLabel", background=HEAD, foreground=MUTED)
    style.configure("Title.TLabel", background=HEAD, foreground=TEXT, font=F["title"])
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Head.TLabel", font=F["head"], foreground=TEXT)
    style.configure("Step.TLabel", font=F["step"], foreground=PRIMARY)
    style.configure("Target.TLabel", font=F["bold"], foreground=ACCENT)
    style.configure("Hint.TLabel", foreground=MUTED, font=F["small"])
    style.configure("Warn.TLabel", foreground=DANGER, font=F["small"])
    style.configure("Good.TLabel", foreground=OK, font=F["small"])
    style.configure("Status.TLabel", background=HEAD, foreground=MUTED, font=F["small"])
    for k, col in BOX.items():
        style.configure(f"Cap{k}.TLabel", foreground=col, font=F["chip"])
    style.configure("TLabelframe", background=BG, bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
    style.configure("TLabelframe.Label", background=BG, foreground=MUTED, font=F["small"])

    # buttons
    style.configure("TButton", background=WELL, foreground=TEXT, bordercolor=LINE, lightcolor=WELL,
                    darkcolor=WELL, focuscolor=ACCENT, padding=(int(10 * ui), pad), relief="flat")
    style.map("TButton",
              background=[("disabled", BG), ("pressed", ACCENT_DIM), ("active", "#343a58")],
              bordercolor=[("focus", ACCENT), ("active", "#4a527a")],
              lightcolor=[("active", "#343a58")], darkcolor=[("active", "#343a58")])
    style.configure("Header.TButton", background="#232842", lightcolor="#232842", darkcolor="#232842")
    style.configure("Big.TButton", background=PRIMARY, foreground=PRIMARY_INK, bordercolor=PRIMARY,
                    lightcolor=PRIMARY, darkcolor=PRIMARY, font=F["primary"], padding=(12, int(9 * ui)))
    style.map("Big.TButton",
              background=[("disabled", "#5c5330"), ("pressed", "#e0aa00"), ("active", PRIMARY_HI)],
              foreground=[("disabled", "#2a2412")],
              lightcolor=[("active", PRIMARY_HI)], darkcolor=[("active", PRIMARY_HI)],
              bordercolor=[("focus", "#ffffff")])
    style.configure("Danger.TButton", foreground=DANGER)
    style.configure("Accent.TButton", background=ACCENT_DIM, lightcolor=ACCENT_DIM, darkcolor=ACCENT_DIM,
                    bordercolor=ACCENT)
    style.map("Accent.TButton", background=[("active", "#4862a8"), ("pressed", ACCENT)])

    # chip-style radio buttons (segmented choices, looks, boxes)
    style.configure("Chip.Toolbutton", background=WELL, foreground=MUTED, bordercolor=LINE,
                    lightcolor=WELL, darkcolor=WELL, padding=(int(10 * ui), int(4 * ui)), font=F["chip"])
    style.map("Chip.Toolbutton",
              background=[("selected", ACCENT_DIM), ("active", "#343a58")],
              foreground=[("selected", "#ffffff"), ("active", TEXT)],
              bordercolor=[("selected", ACCENT)],
              lightcolor=[("selected", ACCENT_DIM)], darkcolor=[("selected", ACCENT_DIM)])
    for k, col in BOX.items():
        style.configure(f"Box{k}.Toolbutton", background=WELL, foreground=col, bordercolor=LINE,
                        lightcolor=WELL, darkcolor=WELL, padding=(int(10 * ui), int(4 * ui)), font=F["chip"])
        style.map(f"Box{k}.Toolbutton",
                  background=[("selected", col), ("active", "#343a58")],
                  foreground=[("selected", CANVAS)],
                  bordercolor=[("selected", col)],
                  lightcolor=[("selected", col)], darkcolor=[("selected", col)])

    # inputs
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(w, fieldbackground=WELL, foreground=TEXT, bordercolor=LINE, lightcolor=WELL,
                        darkcolor=WELL, insertcolor=TEXT, padding=(int(6 * ui), int(3 * ui)),
                        arrowcolor=MUTED, background=WELL)
        style.map(w, bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  fieldbackground=[("disabled", BG), ("readonly", WELL)],
                  foreground=[("disabled", "#6b7290")],
                  background=[("active", "#343a58")], arrowcolor=[("active", TEXT)])
    style.map("TCombobox", selectbackground=[("readonly", WELL)], selectforeground=[("readonly", TEXT)])
    for w in ("TCheckbutton", "TRadiobutton"):
        style.configure(w, background=BG, foreground=TEXT, indicatorbackground=WELL, indicatorforeground=TEXT,
                        upperbordercolor=LINE, lowerbordercolor=LINE, focuscolor=BG)
        style.map(w, background=[("active", BG)],
                  indicatorbackground=[("selected", ACCENT), ("pressed", ACCENT_DIM)],
                  indicatorforeground=[("selected", "#ffffff")])
    style.configure("Horizontal.TScale", background=MUTED, troughcolor=WELL, bordercolor=LINE,
                    lightcolor=MUTED, darkcolor=MUTED)
    style.map("Horizontal.TScale", background=[("active", ACCENT)])
    for o in ("Vertical", "Horizontal"):
        style.configure(f"{o}.TScrollbar", background=WELL, troughcolor=BG, bordercolor=BG,
                        lightcolor=WELL, darkcolor=WELL, arrowcolor=MUTED, gripcount=0)
        style.map(f"{o}.TScrollbar", background=[("active", "#3c4366")])

    # character list
    rh = int(24 * ui)
    style.configure("Treeview", background=WELL, fieldbackground=WELL, foreground=TEXT, bordercolor=LINE,
                    lightcolor=WELL, darkcolor=WELL, rowheight=rh, font=F["body"])
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=HEAD, foreground=MUTED, bordercolor=LINE,
                    lightcolor=HEAD, darkcolor=HEAD, relief="flat", font=F["chip"], padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", WELL)])
    return F


def dark_titlebar(win: tk.Misc):
    """Windows 10/11: ask for a dark title bar so the window frame matches the theme."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass
