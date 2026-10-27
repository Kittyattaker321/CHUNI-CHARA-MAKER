# Chuni Chara Maker
# Copyright (C) 2026 Chuni Chara Maker contributors
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Chuni Chara Maker — make your own CHUNITHM characters and option folders.

  * New character: adds a brand-new character with its own ID (like community packs).
  * Replace: takes over an existing character slot (delete yours and the original is back).
  * Transformations: up to 9 extra looks per character, each with a name and unlock rank.
  * Groups: make your own character group.
  * Check folder: finds mistakes in any option folder (yours or someone else's) and fixes the safe ones.

Everything is written to bin\\option\\<your folder>. Base game files are never changed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import traceback

try:
    import ctypes
    if sys.platform == "win32":
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import chuni_core as cc
import chuni_mod as cm
import chuni_theme as th

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def resource(name: str) -> str | None:
    """A file shipped next to the program (like the window icon), or None."""
    p = os.path.join(APP_DIR, name)
    return p if os.path.isfile(p) else None


def _data_dir() -> str:
    """One fixed place for settings + projects, so they survive updates and moving the program."""
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    d = os.path.join(base, "ChuniCharaMaker") if base else os.path.join(os.path.expanduser("~"), ".chunicharamaker")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return APP_DIR


DATA_DIR = _data_dir()
SETTINGS = os.path.join(DATA_DIR, "settings.json")
LEGACY_SETTINGS = os.path.join(APP_DIR, "settings.json")


def project_roots() -> list:
    """Where saved projects may be: the fixed data folder first, then next to the program (older versions)."""
    roots = [DATA_DIR]
    if os.path.abspath(APP_DIR) != os.path.abspath(DATA_DIR):
        roots.append(APP_DIR)
    return roots


def find_project(option: str, chara_id: int):
    for r in project_roots():
        p = cm.load_project(cm.project_dir(r, option, chara_id))
        if p:
            return p
    return None

FRAME_COLORS = {"00": "#3fa7ff", "01": "#ff9f1c", "02": "#2ee59d"}
FRAME_LABELS = {"00": "Large 1080", "01": "Select 512", "02": "Nameplate 128"}
FORMATS = {"BC3 (like the game)": "bc3", "Uncompressed (4x size)": "rgba"}


def load_settings() -> dict:
    for p in (SETTINGS, LEGACY_SETTINGS):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def save_settings(d: dict):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def checker(w: int, h: int, s: int = 8) -> Image.Image:
    im = Image.new("RGB", (w, h), th.CHECK_A)
    tile = Image.new("RGB", (s, s), th.CHECK_B)
    for y in range(0, h, s):
        for x in range((y // s) % 2 * s, w, 2 * s):
            im.paste(tile, (x, y))
    return im


def on_checker(im: Image.Image, size: int | None = None) -> Image.Image:
    if size and im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    bg = checker(im.width, im.height).convert("RGBA")
    bg.alpha_composite(im.convert("RGBA"))
    return bg.convert("RGB")


class Form:
    """One look of the character: index 0 = base, 1..9 = transformations."""

    def __init__(self, index: int, name: str = "", rank: int = 5):
        self.index = index
        self.name = name
        self.rank = rank
        self.original: Image.Image | None = None   # as opened
        self.src: Image.Image | None = None        # after background removal
        self.path = ""
        self.frames: dict = {}
        self.linked = True   # transformations: boxes move along when the Base's boxes move

    def set_image(self, im: Image.Image, path: str = "", frames: dict | None = None):
        self.original = im
        self.src = im
        self.path = path
        self.frames = {k: list(v) for k, v in (frames or cc.auto_frames(im)).items()}

    def render(self) -> dict:
        return {k: cc.render_frame(self.src, self.frames[k], n)   # the game fades the large art itself
                for k, n in cc.TARGETS.items()}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.scan: cm.GameScan | None = None
        self.mode = "new"            # new | replace | edit
        self.target_id: int | None = None
        self.forms: list[Form] = [Form(0)]
        self.cur = 0
        self.active = tk.StringVar(value="00")
        self.view = (1.0, 0.0, 0.0)
        self.drag = None
        self.dirty = False
        self._preview_job = None
        self._photos = {}
        self.sort_edited = False
        self._loading_form = False

        self.ui = max(1.0, root.winfo_fpixels("1i") / 96.0)
        root.title("Chuni Chara Maker")
        try:   # window + taskbar icon
            png = resource("icon.png")
            if png:
                self._icon = tk.PhotoImage(file=png)
                root.iconphoto(True, self._icon)
            ico = resource("icon.ico")
            if ico and sys.platform == "win32":
                root.iconbitmap(default=ico)
        except Exception:
            pass
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.ui = max(0.8, min(self.ui, (sw - 40) / 1440, (sh - 90) / 900))
        root.geometry(f"{int(1440 * self.ui)}x{int(900 * self.ui)}+10+10")
        root.minsize(min(int(1150 * self.ui), sw - 40), min(int(720 * self.ui), sh - 90))
        self.F = th.apply(root, max(self.ui, root.winfo_fpixels("1i") / 96.0))

        self._build()
        root.after(50, lambda: th.dark_titlebar(root))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        game = self.settings.get("game") or ""
        if game:
            self.game_var.set(game)
        if not self.settings.get("welcome_done"):
            root.after(250, self.welcome_dialog)
        elif game:
            root.after(100, self.load_game)

    # ================================================================== layout
    def _build(self):
        r = self.root
        top = ttk.Frame(r, padding=(14, 9), style="Header.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Chuni Chara Maker", style="Title.TLabel").pack(side="left", padx=(0, 22))
        ttk.Label(top, text="Game", style="Header.TLabel").pack(side="left")
        self.game_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.game_var, width=26).pack(side="left", padx=6)
        ttk.Button(top, text="Browse…", command=self.browse_game, style="Header.TButton").pack(side="left")
        ttk.Button(top, text="Load", command=self.load_game, style="Header.TButton").pack(side="left", padx=(4, 18))
        ttk.Label(top, text="Option folder", style="Header.TLabel").pack(side="left")
        self.opt_var = tk.StringVar(value=self.settings.get("option", "AXXX"))
        oe = ttk.Entry(top, textvariable=self.opt_var, width=6)
        oe.pack(side="left", padx=6)
        oe.bind("<Return>", lambda e: self.load_game())
        oe.bind("<FocusOut>", lambda e: self._option_changed())
        ttk.Button(top, text="Open", command=self.open_option_folder, style="Header.TButton").pack(side="left")
        ttk.Button(top, text="Rename…", command=self.rename_option_dialog,
                   style="Header.TButton").pack(side="left", padx=(4, 0))
        ttk.Button(top, text="+ New option folder", command=self.new_option_dialog,
                   style="Header.TButton").pack(side="left", padx=(4, 0))
        ttk.Button(top, text="Check a folder…", command=self.check_dialog, style="Header.TButton").pack(side="right")
        self.fmt_var = tk.StringVar(value=self.settings.get("fmt") if self.settings.get("fmt") in FORMATS else list(FORMATS)[0])
        ttk.Combobox(top, textvariable=self.fmt_var, values=list(FORMATS), state="readonly",
                     width=19).pack(side="right", padx=(6, 14))
        ttk.Label(top, text="DDS", style="Header.TLabel").pack(side="right")

        body = ttk.Frame(r, padding=(14, 12, 14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_middle(body)
        self._build_right(body)

        self.status = tk.StringVar(value="Ready.")
        bar = ttk.Frame(r, padding=(14, 5), style="Header.TFrame")
        bar.pack(fill="x", side="bottom", before=body)
        ttk.Label(bar, textvariable=self.status, style="Status.TLabel").pack(side="left")
        self.refresh_forms_strip()
        self.update_previews()
        self.update_target_label()

    def _section(self, parent, num: str, title: str):
        f = ttk.Frame(parent)
        if num:
            ttk.Label(f, text=num, style="Step.TLabel").pack(side="left", padx=(0, 8))
        ttk.Label(f, text=title, style="Head.TLabel").pack(side="left")
        return f

    def _toplevel(self):
        d = tk.Toplevel(self.root)
        d.configure(background=th.BG)
        d.after(30, lambda: th.dark_titlebar(d))
        return d

    def _build_left(self, body):
        left = ttk.Frame(body, width=int(390 * self.ui))
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.grid_propagate(False)
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)
        self._section(left, "1", "Character").grid(row=0, column=0, sticky="w")
        bf = ttk.Frame(left)
        bf.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        ttk.Button(bf, text="+ New character", command=self.new_character, style="Accent.TButton").pack(side="left")
        self.view_mode = tk.StringVar(value="mine")
        ttk.Radiobutton(bf, text="My folder", value="mine", variable=self.view_mode, style="Chip.Toolbutton",
                        command=self.fill_tree).pack(side="left", padx=(12, 0))
        ttk.Radiobutton(bf, text="All (to replace)", value="all", variable=self.view_mode, style="Chip.Toolbutton",
                        command=self.fill_tree).pack(side="left", padx=(2, 0))
        sf = ttk.Frame(left)
        sf.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(sf, text="Search", style="Hint.TLabel").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.fill_tree())
        ttk.Entry(sf, textvariable=self.search_var).pack(side="left", fill="x", expand=True, padx=4)

        tf = ttk.Frame(left)
        tf.grid(row=3, column=0, sticky="nsew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        cols = ("id", "name", "group", "src")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("id", "ID", 56), ("name", "Name", 150), ("group", "Group", 110), ("src", "From", 52)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=int(w * self.ui), stretch=c in ("name", "group"))
        self.tree.tag_configure("custom", foreground=th.PRIMARY)
        self.tree.tag_configure("odd", foreground=th.DANGER)
        self.tree.grid(row=0, column=0, sticky="nsew")
        nf = ttk.Frame(tf)
        nf.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.odd_note = ttk.Label(nf, text="", style="Warn.TLabel", wraplength=int(370 * self.ui), justify="left")
        self.odd_note.pack(side="top", anchor="w")
        self.btn_match = ttk.Button(nf, text="Match them now", command=self.match_folder)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Double-1>", lambda e: self.use_selected())

        pv = ttk.Frame(left)
        pv.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.slot_img = ttk.Label(pv)
        self.slot_img.pack(side="left")
        info = ttk.Frame(pv)
        info.pack(side="left", fill="both", expand=True, padx=8)
        self.slot_info = ttk.Label(info, text="", wraplength=int(190 * self.ui), justify="left")
        self.slot_info.pack(anchor="nw")
        self.btn_use = ttk.Button(info, text="Use this", command=self.use_selected, state="disabled")
        self.btn_use.pack(anchor="nw", pady=(6, 2))
        self.btn_delete = ttk.Button(info, text="Remove from my folder", command=self.delete_selected,
                                     state="disabled", style="Danger.TButton")
        self.btn_delete.pack(anchor="nw")

    def _build_middle(self, body):
        mid = ttk.Frame(body)
        mid.grid(row=0, column=1, sticky="nsew")
        mid.rowconfigure(3, weight=1)
        mid.columnconfigure(0, weight=1)
        self._section(mid, "2", "Look").grid(row=0, column=0, sticky="w")
        self.forms_bar = ttk.Frame(mid)
        self.forms_bar.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        tb = ttk.Frame(mid)
        tb.grid(row=2, column=0, sticky="ew", pady=(2, 8))
        ttk.Button(tb, text="Open image…", command=self.open_image).pack(side="left")
        ttk.Button(tb, text="Remove background", command=self.remove_bg).pack(side="left", padx=(8, 2))
        self.tol = tk.IntVar(value=40)
        ttk.Label(tb, text="tolerance", style="Hint.TLabel").pack(side="left", padx=(4, 4))
        ttk.Scale(tb, from_=5, to=120, variable=self.tol, length=int(80 * self.ui)).pack(side="left")
        if cc.rembg_available():
            ttk.Button(tb, text="AI cut-out", command=self.remove_bg_ai).pack(side="left", padx=4)
        ttk.Button(tb, text="Undo cut", command=self.restore_src).pack(side="left", padx=4)
        ttk.Button(tb, text="Auto-frame", command=self.auto_frame).pack(side="left", padx=(8, 0))

        self.canvas = tk.Canvas(mid, bg=th.CANVAS, highlightthickness=1, highlightbackground=th.LINE,
                                highlightcolor=th.LINE, cursor="fleur")
        self.canvas.grid(row=3, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<MouseWheel>", lambda e: self.zoom_active(1 / 1.05 if e.delta > 0 else 1.05))
        self.canvas.bind("<Button-4>", lambda e: self.zoom_active(1 / 1.05))
        self.canvas.bind("<Button-5>", lambda e: self.zoom_active(1.05))
        for key, d in (("<Left>", (-1, 0)), ("<Right>", (1, 0)), ("<Up>", (0, -1)), ("<Down>", (0, 1))):
            self.root.bind(key, lambda e, d=d: self.nudge(*d))

        fb = ttk.Frame(mid)
        fb.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(fb, text="Box", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        for k in ("00", "01", "02"):
            ttk.Radiobutton(fb, text=FRAME_LABELS[k], value=k, variable=self.active, style=f"Box{k}.Toolbutton",
                            command=self.redraw).pack(side="left", padx=(0, 4))
        ttk.Label(fb, text="Drag to move. Wheel or corner to resize. Arrow keys nudge.",
                  style="Hint.TLabel").pack(side="left", padx=10)

    def _build_right(self, body):
        right = ttk.Frame(body, width=int(340 * self.ui))
        right.grid(row=0, column=2, sticky="nsew", padx=(16, 0))
        right.grid_propagate(False)
        right.columnconfigure(0, weight=1)
        self._section(right, "", "Preview").grid(row=0, column=0, sticky="w")
        pr = ttk.Frame(right)
        pr.grid(row=1, column=0, sticky="w", pady=(6, 4))
        c00 = ttk.Frame(pr)
        c00.pack(side="left", anchor="n")
        self.p00 = ttk.Label(c00)
        self.p00.pack()
        ttk.Label(c00, text="Large 1080", style="Cap00.TLabel").pack(anchor="w")
        col = ttk.Frame(pr)
        col.pack(side="left", anchor="n", padx=(8, 0))
        self.p01 = ttk.Label(col)
        self.p01.pack()
        ttk.Label(col, text="Select 512", style="Cap01.TLabel").pack(anchor="w")
        self.p02 = ttk.Label(col)
        self.p02.pack(pady=(4, 0))
        ttk.Label(col, text="Nameplate 128", style="Cap02.TLabel").pack(anchor="w")

        self._section(right, "3", "Details").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.target_lbl = ttk.Label(right, text="", style="Target.TLabel", wraplength=int(320 * self.ui))
        self.target_lbl.grid(row=5, column=0, sticky="w", pady=(0, 2))
        form = ttk.Frame(right)
        form.grid(row=6, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.id_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.sort_var = tk.StringVar()
        self.works_var = tk.StringVar(value="9000 · CHUNITHM")
        self.illus_var = tk.StringVar()
        self.name_var.trace_add("write", self._name_changed)
        r = 0
        ttk.Label(form, text="ID").grid(row=r, column=0, sticky="w", pady=2)
        idf = ttk.Frame(form)
        idf.grid(row=r, column=1, sticky="ew")
        self.id_entry = ttk.Entry(idf, textvariable=self.id_var, width=8)
        self.id_entry.pack(side="left")
        ttk.Label(idf, text="any free ID ending in 0", style="Hint.TLabel").pack(side="left", padx=4)
        r += 1
        ttk.Label(form, text="Name").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.name_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1
        ttk.Label(form, text="Sort name").grid(row=r, column=0, sticky="w", pady=2)
        se = ttk.Entry(form, textvariable=self.sort_var)
        se.grid(row=r, column=1, sticky="ew", pady=2)
        se.bind("<Key>", lambda e: setattr(self, "sort_edited", True))
        r += 1
        ttk.Label(form, text="Group").grid(row=r, column=0, sticky="w", pady=2)
        gf = ttk.Frame(form)
        gf.grid(row=r, column=1, sticky="ew")
        self.works_box = ttk.Combobox(gf, textvariable=self.works_var, values=["9000 · CHUNITHM"])
        self.works_box.pack(side="left", fill="x", expand=True)
        self.btn_group_new = ttk.Button(gf, text="New…", width=5, command=self.new_group_dialog)
        self.btn_group_new.pack(side="left", padx=(4, 0))
        r += 1
        ttk.Label(form, text="Illustrator").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.illus_var).grid(row=r, column=1, sticky="ew", pady=2)
        r += 1
        ttk.Label(form, text="Version label").grid(row=r, column=0, sticky="w", pady=2)
        tgf = ttk.Frame(form)
        tgf.grid(row=r, column=1, sticky="ew")
        self.tag_var = tk.StringVar()
        self.tag_box = ttk.Combobox(tgf, textvariable=self.tag_var, state="readonly")
        self.tag_box.pack(side="left", fill="x", expand=True)
        self.btn_tag_new = ttk.Button(tgf, text="New…", width=5, command=self.new_tag_dialog)
        self.btn_tag_new.pack(side="left", padx=(4, 0))

        r += 1
        tif = ttk.Frame(form)
        tif.grid(row=r, column=1, sticky="ew")
        self.tag_info = ttk.Label(tif, text="", style="Hint.TLabel", wraplength=int(240 * self.ui), justify="left")
        self.tag_info.pack(side="top", anchor="w")
        tbr = ttk.Frame(tif)
        tbr.pack(side="top", anchor="w", pady=(1, 2))
        self.btn_tag_rename = ttk.Button(tbr, text="Rename…", command=self.rename_tag_dialog)
        self.btn_tag_fix = ttk.Button(tbr, text="", command=self.fix_tag_conflict)
        self.tag_var.trace_add("write", lambda *_: self.update_tag_info())
        r += 1
        nwf = ttk.Frame(form)
        nwf.grid(row=r, column=0, columnspan=2, sticky="ew")
        self.lead_info = ttk.Label(nwf, text="", style="Hint.TLabel", wraplength=int(320 * self.ui), justify="left")
        self.lead_info.pack(side="top", anchor="w")

        self.form_box = ttk.LabelFrame(right, text="This look", padding=4)
        self.form_box.grid(row=7, column=0, sticky="ew", pady=(4, 2))
        self.form_box.columnconfigure(1, weight=1)
        self.fname_var = tk.StringVar()
        self.frank_var = tk.StringVar(value="5")
        self.fname_var.trace_add("write", self._form_fields_changed)
        self.frank_var.trace_add("write", self._form_fields_changed)
        self.linked_var = tk.BooleanVar(value=True)
        self.linked_row = ttk.Frame(self.form_box)
        self.linked_cb = ttk.Checkbutton(self.linked_row, text="Move with the Base's boxes", variable=self.linked_var,
                                         command=self._linked_changed)
        self.linked_cb.pack(side="left")
        ttk.Button(self.linked_row, text="Match Base", command=self.match_base).pack(side="right")
        self.fname_lbl = ttk.Label(self.form_box, text="Transformation name")
        self.fname_entry = ttk.Entry(self.form_box, textvariable=self.fname_var)
        self.frank_lbl = ttk.Label(self.form_box, text="Unlocks at rank")
        self.frank_spin = ttk.Spinbox(self.form_box, from_=1, to=200, textvariable=self.frank_var, width=6)

        opts = ttk.Frame(right)
        opts.grid(row=8, column=0, sticky="ew")
        self.keep_forms = tk.BooleanVar(value=False)
        self.keep_cb = ttk.Checkbutton(opts, text="Keep the original's transformations", variable=self.keep_forms)
        self.keep_cb.grid(row=0, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.btn_save = ttk.Button(right, text="Add to my folder", style="Big.TButton", command=self.save)
        self.btn_save.grid(row=9, column=0, sticky="ew", pady=(10, 0))

    # ================================================================== game
    def browse_game(self):
        d = filedialog.askdirectory(title="Select your CHUNITHM folder (contains data and bin)")
        if d:
            self.game_var.set(d)
            self.load_game()

    def _option_changed(self):
        if self.scan and self.opt_var.get().strip().upper() != self.scan.my_option:
            self.load_game()

    def load_game(self, then=None):
        path = self.game_var.get().strip().strip('"')
        root = cm.find_game_root(path) if path else None
        if not root:
            messagebox.showerror("Game folder", "Couldn't find data\\A000 and bin\\option under that folder.\n"
                                                "Pick the folder that contains both 'data' and 'bin'.")
            return
        opt = self.opt_var.get().strip().upper() or "AXXX"
        err = cm.validate_option_name(opt)
        if err:
            messagebox.showwarning("Option folder", err)
            return
        self.opt_var.set(opt)
        self.game_var.set(root)
        self.settings.update(game=root, option=opt)
        save_settings(self.settings)
        self.status.set("Scanning characters…")

        def work():
            try:
                scan = cm.scan_game(root, opt, progress=lambda m: self.root.after(0, self.status.set, m))
                self.root.after(0, self._scan_done, scan, then)
            except Exception as e:
                traceback.print_exc()
                self.root.after(0, messagebox.showerror, "Scan failed", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, scan: cm.GameScan, then=None):
        stale = self.mode in ("edit", "replace") and (
            self.target_id not in scan.slots or (self.mode == "edit" and not scan.slots[self.target_id].custom))
        self.scan = scan
        if stale:
            self.dirty = False
            self.new_character()
        self.refresh_works()
        self.refresh_tags()
        mine = [s for s in scan.slots.values() if s.custom]
        self.status.set(f"Found {len(scan.slots)} characters in {len(scan.sources)} folders · "
                        f"{len(mine)} in your folder {scan.my_option}")
        if not mine and self.view_mode.get() == "mine":
            self.view_mode.set("mine")
        self.fill_tree()
        if self.mode == "new" and not self.dirty:
            self.id_var.set(str(cm.next_free_id(scan, int(self.settings.get("start_id", 70000)))))
        self.update_target_label()
        self.update_tag_info()
        self.apply_lead_lock()
        if then:
            then()
        else:
            self.root.after(300, self.maybe_offer_label)

    def refresh_works(self):
        if not self.scan:
            return
        vals = [f"{i} · {n}" + (" (mine)" if i in self.scan.my_works else "") for i, n in sorted(self.scan.works.items())]
        mine = [v for v in vals if v.endswith("(mine)")]
        self.works_box["values"] = mine + [v for v in vals if v not in mine]

    def tag_label(self, i) -> str:
        v, title = self.scan.release_tags.get(i, ("", f"label {i}"))
        warn = "  ⚠" if self.scan.tag_conflict(i) else ""
        return f"{i} · {title}  [{self.scan.tag_source(i)}]{warn}"

    def update_tag_info(self):
        if not self.scan:
            return
        i = self.selected_tag()
        if i is None:
            self.tag_info.configure(text="", style="Hint.TLabel")
            return
        conflict = self.scan.tag_conflict(i)
        mine = i in self.scan.my_tags and not self.lead_locked()
        if mine:
            self.btn_tag_rename.pack(side="left")
        else:
            self.btn_tag_rename.pack_forget()
        if conflict and mine:
            self.btn_tag_fix.configure(text=f"Move mine to {cm.next_free_tag(self.scan)}", width=0)
            self.btn_tag_fix.pack(side="left", padx=(4, 0))
        else:
            self.btn_tag_fix.pack_forget()
        if conflict:
            self.tag_info.configure(style="Warn.TLabel", text=f"⚠ ID {i} conflict: used by {', '.join(conflict)}")
        elif i in self.scan.my_tags:
            self.tag_info.configure(style="Good.TLabel", text=f"Label ID {i} · yours ({self.scan.my_option}) · no conflicts")
        elif i < cm.CUSTOM_TAG_MIN:
            self.tag_info.configure(style="Hint.TLabel", text=f"Label ID {i} · official, from {self.scan.tag_source(i)}")
        else:
            self.tag_info.configure(style="Hint.TLabel", text=f"Label ID {i} · from {self.scan.tag_source(i)}")

    def refresh_tags(self, select: int | None = None):
        if not self.scan:
            return
        mine = sorted(self.scan.my_tags)
        official = sorted((i for i in self.scan.release_tags if i not in self.scan.my_tags), reverse=True)
        self.tag_box["values"] = [self.tag_label(i) for i in mine + official]
        if select is not None and select in self.scan.release_tags:
            self.tag_var.set(self.tag_label(select))
        elif not self.tag_var.get() and self.scan.newest_tag is not None:
            self.tag_var.set(self.tag_label(self.scan.newest_tag))

    def selected_tag(self) -> int | None:
        try:
            return int(self.tag_var.get().split("·")[0].strip())
        except ValueError:
            return None

    def rename_tag_dialog(self):
        if not self.scan:
            return
        i = self.selected_tag()
        if i is None or i not in self.scan.my_tags:
            messagebox.showinfo("Rename label", "You can only rename version labels from your own folder "
                                                f"({self.scan.my_option}). Official ones belong to the game.")
            return
        d = self._toplevel()
        d.title("Rename version label")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Label ID {i} (stays the same — every character and group using it shows the new "
                           "text automatically).", wraplength=330, style="Hint.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        title = tk.StringVar(value=cm.my_tag_title(self.scan, i))
        ttk.Label(fr, text="Text").grid(row=1, column=0, sticky="w")
        te = ttk.Entry(fr, textvariable=title, width=32)
        te.grid(row=1, column=1, sticky="ew", pady=2)
        te.focus_set()
        te.select_range(0, "end")

        def ok():
            try:
                cm.rename_my_tag(self.scan, i, title.get())
            except Exception as e:
                messagebox.showerror("Rename label", str(e), parent=d)
                return
            self.refresh_tags(select=i)
            self.update_tag_info()
            note = "" if self.scan.tag_source(i) == self.scan.my_option else \
                f" (but {self.scan.tag_source(i)} also uses ID {i} and loads later — use 'Move mine to…' to fix)"
            self.status.set(f"Version label {i} renamed to '{title.get().strip()}'{note}. Restart the game to see it.")
            d.destroy()
        bf = ttk.Frame(fr)
        bf.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Rename", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: ok())

    def fix_tag_conflict(self):
        i = self.selected_tag()
        if i is None or i not in self.scan.my_tags:
            return
        new = cm.next_free_tag(self.scan)
        if not messagebox.askyesno("Fix label conflict",
                                   f"Move your label '{self.scan.release_tags[i][1]}' from ID {i} to free ID {new}?\n\n"
                                   f"Every character and group in {self.scan.my_option} that uses it is updated."):
            return
        try:
            done = cm.renumber_my_tag(self.scan, i, new)
        except Exception as e:
            messagebox.showerror("Fix label conflict", str(e))
            return
        self.refresh_tags(select=new)
        self.update_tag_info()
        self.status.set(f"Label moved to ID {new}: " + "; ".join(done))

    def new_tag_dialog(self, suggest_title: str = ""):
        if not self.scan:
            messagebox.showwarning("Version label", "Load your game folder first.")
            return
        d = self._toplevel()
        d.title("New version label")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="The version label is the text shown above the group name when you get the "
                           "character (e.g. 'CHUNITHM X-VERSE').",
                  wraplength=330).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        rec = cm.next_free_tag(self.scan)
        tid = tk.StringVar(value=str(rec))
        title = tk.StringVar(value="")
        ttk.Label(fr, text="Label ID").grid(row=1, column=0, sticky="w")
        idrow = ttk.Frame(fr)
        idrow.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Entry(idrow, textvariable=tid, width=8).pack(side="left")
        ttk.Button(idrow, text=f"Use recommended ({rec})", command=lambda: tid.set(str(rec))).pack(side="left", padx=6)
        check = ttk.Label(fr, text="")
        check.grid(row=2, column=1, sticky="w")

        def validate(*_):
            try:
                p = cm.tag_id_problem(self.scan, int(tid.get()))
            except ValueError:
                p = "The ID must be a number."
            check.configure(text=p or "✓ Free — no other folder uses this ID.", style="Warn.TLabel" if p else "Good.TLabel",
                            wraplength=330)
            return p
        tid.trace_add("write", validate)
        validate()
        ttk.Label(fr, text="Version label name").grid(row=3, column=0, sticky="w", padx=(0, 6))
        te = ttk.Entry(fr, textvariable=title, width=32)
        te.grid(row=3, column=1, sticky="ew", pady=2)
        te.focus_set()
        official = sorted(i for i in self.scan.release_tags if i < cm.CUSTOM_TAG_MIN)
        custom = sorted(i for i in self.scan.release_tags if i >= cm.CUSTOM_TAG_MIN)
        used = (f"In use — official: {official[0]}–{official[-1]}" if official else "In use — official: none") + \
            ("; custom: " + ", ".join(f"{i} ({', '.join(self.scan.tag_defs.get(i, ['?']))})" for i in custom)
             if custom else "; custom: none")
        ttk.Label(fr, text=used + f".\nIDs below {cm.CUSTOM_TAG_MIN} are kept for future CHUNITHM versions.",
                  style="Hint.TLabel", wraplength=330, justify="left").grid(row=4, column=0, columnspan=2, sticky="w",
                                                                           pady=(6, 0))

        def ok():
            try:
                i = int(tid.get())
                cm.create_release_tag(self.scan, i, title.get())
            except Exception as e:
                messagebox.showerror("New version label", str(e), parent=d)
                return
            self.refresh_tags(select=i)
            self.dirty = True
            self.status.set(f"Created version label {i} '{title.get().strip()}' in {self.scan.my_option}. "
                            "It's applied to the character (and your group) when you save.")
            d.destroy()
        bf = ttk.Frame(fr)
        bf.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Create", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: ok())
        if suggest_title:
            title.set(suggest_title)

    def example_name(self) -> str:
        """Example text for labels/groups: the character's sort name, or the option folder's name."""
        ex = self.sort_var.get().strip() if hasattr(self, "sort_var") else ""
        return ex or self.opt_var.get().strip().upper() or "AXXX"

    # ------------------------------------------------------------------ first start
    def welcome_dialog(self):
        d = self._toplevel()
        d.title("Welcome to Chuni Chara Maker")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=16)
        fr.pack(fill="both", expand=True)
        fr.columnconfigure(1, weight=1)
        ttk.Label(fr, text="Make your own option folder", style="Head.TLabel").grid(row=0, column=0, columnspan=3,
                                                                                    sticky="w")
        ttk.Label(fr, text="Everything you make goes into your own option folder inside bin\\option, so the game's "
                           "files are never changed. Its name must be A + 3 letters or numbers. "
                           "Rename AXXX to whatever you like — you can also rename it later.",
                  wraplength=460, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 10))
        game = tk.StringVar(value=self.game_var.get())
        ttk.Label(fr, text="Game folder").grid(row=2, column=0, sticky="w")
        ttk.Entry(fr, textvariable=game, width=44).grid(row=2, column=1, sticky="ew", pady=2)

        def browse():
            p = filedialog.askdirectory(parent=d, title="Select your CHUNITHM folder (contains data and bin)")
            if p:
                game.set(p)
        ttk.Button(fr, text="Browse…", command=browse).grid(row=2, column=2, padx=(4, 0))
        name = tk.StringVar(value="AXXX")
        ttk.Label(fr, text="Option folder name").grid(row=3, column=0, sticky="w")
        nrow = ttk.Frame(fr)
        nrow.grid(row=3, column=1, columnspan=2, sticky="w", pady=2)
        ne = ttk.Entry(nrow, textvariable=name, width=8)
        ne.pack(side="left")

        def load_last():
            r = cm.find_game_root(game.get().strip().strip('"')) if game.get().strip() else None
            sugs = self._load_last_names(r, name.get()) if r else []
            if sugs:
                name.set(sugs[0])
        ttk.Button(nrow, text="Make it load last", command=load_last).pack(side="left", padx=(8, 0))
        ne.focus_set()
        ne.select_range(0, "end")
        check = ttk.Label(fr, text="", wraplength=460, justify="left")
        check.grid(row=4, column=0, columnspan=3, sticky="w")
        used = ttk.Label(fr, text="", style="Hint.TLabel", wraplength=460, justify="left")
        used.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        order = ttk.Label(fr, text="", style="Hint.TLabel", wraplength=460, justify="left")
        order.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        def validate(*_):
            root = cm.find_game_root(game.get().strip().strip('"')) if game.get().strip() else None
            if not root:
                check.configure(text="Pick the game folder that contains 'data' and 'bin'.", style="Warn.TLabel")
                used.configure(text="")
                return None, None
            existing = cm.existing_option_folders(root)
            used.configure(text="Already used in bin\\option: " + (", ".join(existing) or "nothing"))
            n = name.get().strip().upper()
            if not cm.validate_option_name(n):
                txt, sty = self._load_order_text(root, n)
                order.configure(text=txt, style=sty)
            else:
                order.configure(text="")
            p = cm.option_name_problem(root, n)
            if p and "already exists" in p:
                check.configure(text=f"{n} already exists. Pick a new name so you don't mix your characters "
                                     "into another folder.", style="Warn.TLabel")
                return root, None
            if p:
                check.configure(text=p, style="Warn.TLabel")
                return root, None
            check.configure(text=f"✓ bin\\option\\{n} will be created.", style="Good.TLabel")
            return root, n
        name.trace_add("write", validate)
        game.trace_add("write", validate)
        validate()

        def create():
            root, n = validate()
            if not root or not n:
                return
            self.game_var.set(root)
            self.opt_var.set(n)
            self.settings.update(welcome_done=True, game=root, option=n)
            save_settings(self.settings)
            d.destroy()

            def made():
                cm._ensure_option(self.scan, lambda m: None)
                self.status.set(f"Created your option folder bin\\option\\{n}. Click '+ New character' to start.")
                self.root.after(200, self.folder_setup_dialog)
            self.load_game(then=made)

        def skip():
            self.settings["welcome_done"] = True
            save_settings(self.settings)
            d.destroy()
            if game.get().strip():
                self.game_var.set(game.get().strip())
                self.load_game()

        bf = ttk.Frame(fr)
        bf.grid(row=7, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(bf, text="Create my option folder", command=create).pack(side="left", padx=4)
        ttk.Button(bf, text="Use an existing one / skip", command=skip).pack(side="left")
        d.bind("<Return>", lambda e: create())
        d.protocol("WM_DELETE_WINDOW", skip)

    def _load_last_names(self, root: str, typed: str = "") -> list:
        """Free folder names that load after EVERY option folder you have (the game loads them A->Z, Z = last).
        AZZZ is the very last name possible; 'AZ' + your own letters is a personal one that still loads last."""
        existing = {x.upper() for x in cm.existing_option_folders(root)}
        latest = max(existing) if existing else "A000"
        t = re.sub(r"[^A-Z]", "", (typed or "").upper()[1:])
        cands = ["AZZZ"]
        if len(t) >= 2:
            cands += [f"AZ{t[:2]}", f"AZZ{t[0]}"]
        cands += [f"AZZ{c}" for c in "YXWVUTSRQPONMLKJIHGFEDCBA"]
        out = []
        for c in cands:
            if c not in out and c not in existing and c > latest and not cm.validate_option_name(c):
                out.append(c)
        return out[:3]

    def _load_order_text(self, root: str, n: str) -> tuple:
        """What loads after a folder called n (and can overwrite it). Returns (text, style)."""
        ttk.Style(self.root).configure("Amber.TLabel", foreground=th.WARN, font=self.F["small"])
        info = cm.load_order(root, n)
        after = info["after"]
        if not after:
            return (f"✓ {n} loads last: no other option folder loads after it, so nothing can overwrite it.",
                    "Good.TLabel")
        lines = [f"⚠ {len(after)} option folder{'s' if len(after) != 1 else ''} load after {n}. The game loads "
                 "option folders A→Z, and a later folder wins when two change the same thing:"]
        for label, summary, has_sort in after[:8]:
            lines.append(f"   • {label}: {summary}" + (" (has its own group list)" if has_sort else ""))
        if len(after) > 8:
            lines.append(f"   • …and {len(after) - 8} more")
        if any(h for _, _, h in after):
            lines.append("The app adds your groups to their group lists whenever you save, and it picks character "
                         "IDs no other folder uses, so your characters stay visible.")
        last = max(l.upper() for l, _, _ in after)
        sugs = self._load_last_names(root, n)
        if sugs:
            lines.append(f"Want nothing to overwrite it? Click 'Make it load last' to use {sugs[0]}"
                         + (f" (or type {' / '.join(sugs[1:])})" if len(sugs) > 1 else "") + ".")
        else:
            lines.append(f"No free name loads after {last}, because {last} is the last possible name.")
        return "\n".join(lines), "Amber.TLabel"

    def _free_option_name(self, root: str) -> str:
        """A free custom-looking name to start with: AXXX, then AXXA, AXXB…"""
        used = {n.upper() for n in cm.existing_option_folders(root)}
        for cand in ["AXXX"] + [f"AXX{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWYZ"] + \
                [f"AX{a}{b}" for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]:
            if cand not in used:
                return cand
        return "AXXX"

    # ---------------------------------------------------------------- version label + group for a folder
    def _my_folders(self) -> set:
        """Option folders this app has made / used (so their labels and groups are listed first)."""
        fd = self.settings.get("folder_defaults", {})
        return {self.scan.my_option} | set(fd) | set(self.settings.get("label_offered", []))

    def _custom_tags(self) -> list:
        """Version labels made in custom option folders (yours or others): [(id, title, folders)]."""
        sc = self.scan
        out = [(i, sc.release_tags[i][1], [f for f in sc.tag_defs.get(i, []) if not cm.is_official_option(f)])
               for i in sorted(sc.release_tags)
               if any(not cm.is_official_option(f) for f in sc.tag_defs.get(i, []))]
        mine = self._my_folders()
        used = {v.get("tag") for v in self.settings.get("folder_defaults", {}).values()}
        return sorted(out, key=lambda t: (not (t[0] in used or mine & set(t[2])), t[0]))   # yours first

    def _custom_groups(self) -> list:
        sc = self.scan
        out = [(w, sc.works[w], [f for f in sc.group_defs.get(w, []) if not cm.is_official_option(f)])
               for w in sorted(sc.works)
               if any(not cm.is_official_option(f) for f in sc.group_defs.get(w, []))]
        mine = self._my_folders()
        used = {v.get("works") for v in self.settings.get("folder_defaults", {}).values()}
        return sorted(out, key=lambda g: (not (g[0] in used or mine & set(g[2])), g[0]))

    def _label_group_sections(self, fr) -> tuple:
        """Version label + group pickers: make a new one, or reuse one you already made.
        Returns (validate() -> error text or None, values() -> dict)."""
        W = 470
        tags, groups = self._custom_tags(), self._custom_groups()
        out = {}

        # ---- version label
        lf = ttk.LabelFrame(fr, text="Version label", padding=8)
        lf.pack(fill="x", pady=(10, 0))
        ttk.Label(lf, text="The text shown above the group name when you get a character.", style="Hint.TLabel",
                  wraplength=W).grid(row=0, column=0, columnspan=3, sticky="w")
        tmode = tk.StringVar(value="new")
        rec = cm.next_free_tag(self.scan)
        tid, tname = tk.StringVar(value=str(rec)), tk.StringVar()
        ttk.Radiobutton(lf, text="Make a new version label", value="new", variable=tmode).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(lf, text="Label ID").grid(row=2, column=0, sticky="w", padx=(22, 6))
        ttk.Entry(lf, textvariable=tid, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(lf, text=f"recommended: {rec}", style="Hint.TLabel").grid(row=2, column=2, sticky="w", padx=6)
        ttk.Label(lf, text="Version label name").grid(row=3, column=0, sticky="w", padx=(22, 6))
        ttk.Entry(lf, textvariable=tname, width=30).grid(row=3, column=1, columnspan=2, sticky="ew", pady=2)
        tchoices = [f"{i} · {t}  ({', '.join(fs)})" for i, t, fs in tags]
        tpick = tk.StringVar(value=tchoices[0] if tchoices else "")
        r = ttk.Radiobutton(lf, text="Use one that already exists (same label as another folder)", value="old",
                            variable=tmode)
        r.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        cb = ttk.Combobox(lf, textvariable=tpick, values=tchoices, state="readonly", width=40)
        cb.grid(row=5, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        if not tchoices:
            r.configure(state="disabled")
            cb.configure(state="disabled")
            tpick.set("(none made yet)")
        else:
            tmode.set("old")   # most people want the same label as their other folder

        # ---- group
        gf = ttk.LabelFrame(fr, text="Group", padding=8)
        gf.pack(fill="x", pady=(10, 0))
        ttk.Label(gf, text="The group the characters in this folder are sorted into.", style="Hint.TLabel",
                  wraplength=W).grid(row=0, column=0, columnspan=3, sticky="w")
        gmode = tk.StringVar(value="new")
        grec = cm.next_free_group(self.scan, int(self.settings.get("group_start", 7000)))
        gid, gname = tk.StringVar(value=str(grec)), tk.StringVar()
        ttk.Radiobutton(gf, text="Make a new group", value="new", variable=gmode).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(gf, text="Group ID").grid(row=2, column=0, sticky="w", padx=(22, 6))
        ttk.Entry(gf, textvariable=gid, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(gf, text=f"recommended: {grec}", style="Hint.TLabel").grid(row=2, column=2, sticky="w", padx=6)
        ttk.Label(gf, text="Group name").grid(row=3, column=0, sticky="w", padx=(22, 6))
        ttk.Entry(gf, textvariable=gname, width=30).grid(row=3, column=1, columnspan=2, sticky="ew", pady=2)
        gchoices = [f"{w} · {n}  ({', '.join(fs)})" for w, n, fs in groups]
        gpick = tk.StringVar(value=gchoices[0] if gchoices else "")
        r2 = ttk.Radiobutton(gf, text="Use one that already exists (same group as another folder)", value="old",
                             variable=gmode)
        r2.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        cb2 = ttk.Combobox(gf, textvariable=gpick, values=gchoices, state="readonly", width=40)
        cb2.grid(row=5, column=0, columnspan=3, sticky="w", padx=(22, 0), pady=2)
        if not gchoices:
            r2.configure(state="disabled")
            cb2.configure(state="disabled")
            gpick.set("(none made yet)")
        else:
            gmode.set("old")

        def _id(text):
            try:
                return int(text.split("·")[0].strip())
            except ValueError:
                return None

        def validate():
            if tmode.get() == "new":
                try:
                    p = cm.tag_id_problem(self.scan, int(tid.get()))
                except ValueError:
                    p = "The label ID must be a number."
                if p:
                    return "Version label: " + p
                if not tname.get().strip():
                    return "Give the version label a name."
            elif _id(tpick.get()) is None:
                return "Pick a version label."
            if gmode.get() == "new":
                try:
                    g = int(gid.get())
                except ValueError:
                    return "The group ID must be a number."
                if not 1 <= g <= 999999:
                    return "Group ID must be between 1 and 999999."
                if g in self.scan.works:
                    return f"Group ID {g} is already '{self.scan.works[g]}'. Free ID: {grec}."
                if not gname.get().strip():
                    return "Give the group a name."
            elif _id(gpick.get()) is None:
                return "Pick a group."
            return None

        def values():
            return {"tag_mode": tmode.get(),
                    "tag": int(tid.get()) if tmode.get() == "new" else _id(tpick.get()),
                    "tag_name": tname.get().strip(),
                    "group_mode": gmode.get(),
                    "group": int(gid.get()) if gmode.get() == "new" else _id(gpick.get()),
                    "group_name": gname.get().strip()}
        for v in (tmode, tid, tname, tpick, gmode, gid, gname, gpick):
            v.trace_add("write", lambda *_: out.get("changed", lambda: None)())
        return validate, values, out

    def _apply_folder_setup(self, v: dict) -> str:
        """Make / pick the version label and group for the folder that's now loaded."""
        sc = self.scan
        if v["tag_mode"] == "new":
            cm.create_release_tag(sc, v["tag"], v["tag_name"])
        if v["group_mode"] == "new":
            cm.create_group(sc, v["group"], v["group_name"], v["tag"])
        self.settings.setdefault("folder_defaults", {})[sc.my_option] = {"works": v["group"], "tag": v["tag"]}
        offered = self.settings.setdefault("label_offered", [])
        if sc.my_option not in offered:
            offered.append(sc.my_option)
        save_settings(self.settings)
        self.refresh_works()
        self.refresh_tags(select=v["tag"])
        tag_t = sc.release_tags.get(v["tag"], ("", v["tag"]))[1]
        return f"group '{sc.works.get(v['group'], v['group'])}' + version label '{tag_t}'"

    def _center(self, d):
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_reqheight()) // 4
        d.geometry(f"+{max(0, x)}+{max(0, y)}")

    def new_option_dialog(self):
        """Make another option folder for a new set of characters (with its version label + group)."""
        g = self.game_var.get().strip().strip('"')
        root = cm.find_game_root(g) if g else None
        if not root:
            messagebox.showwarning("New option folder", "Pick your game folder first (Browse… at the top).")
            return
        if not self.scan:
            self.load_game(then=self.new_option_dialog)
            return
        if self.dirty and not messagebox.askyesno("New option folder", "Unsaved changes to the current character "
                                                                        "will be lost. Continue?"):
            return
        d = self._toplevel()
        d.title("New option folder")
        d.transient(self.root)
        d.resizable(False, False)
        fr = ttk.Frame(d, padding=16)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Make a new option folder", style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text="Start a new set of characters in its own folder inside bin\\option. Your other "
                           "option folders stay as they are; switch back any time by typing their name next to "
                           "'Option folder'.", wraplength=470, justify="left").pack(anchor="w", pady=(4, 8))
        row = ttk.Frame(fr)
        row.pack(anchor="w")
        ttk.Label(row, text="Folder name").pack(side="left")
        # start with a name that loads after every other folder, so nothing overwrites the new one
        name = tk.StringVar(value=(self._load_last_names(root) or [self._free_option_name(root)])[0])
        ne = ttk.Entry(row, textvariable=name, width=8)
        ne.pack(side="left", padx=(8, 0))
        ttk.Label(row, text="A + 3 letters", style="Hint.TLabel").pack(side="left", padx=8)

        def load_last():
            sugs = self._load_last_names(root, name.get())
            if sugs:
                name.set(sugs[0])
            else:
                messagebox.showinfo("Load last", "No free name loads after every folder you have: the last "
                                                 "possible name (AZZZ) is already used.", parent=d)
        ttk.Button(row, text="Make it load last", command=load_last).pack(side="left")
        used_txt = ", ".join(cm.existing_option_folders(root)) or "nothing yet"
        ttk.Label(fr, text=f"Already in bin\\option: {used_txt}", style="Hint.TLabel", wraplength=470,
                  justify="left").pack(anchor="w", pady=(4, 0))
        order = ttk.Label(fr, text="", style="Hint.TLabel", wraplength=470, justify="left")
        order.pack(anchor="w", pady=(6, 0))
        validate_lg, values, hook = self._label_group_sections(fr)
        check = ttk.Label(fr, text="", wraplength=470, justify="left")
        check.pack(anchor="w", pady=(10, 0))
        btns = ttk.Frame(fr)
        btns.pack(fill="x", pady=(10, 0))
        ok_btn = ttk.Button(btns, text="Create and switch to it", style="Accent.TButton")
        ok_btn.pack(side="right")
        ttk.Button(btns, text="Cancel", command=d.destroy).pack(side="right", padx=(0, 6))

        def validate(*_):
            n = name.get().strip().upper()
            p = cm.option_name_problem(root, n)
            if not p and cm.is_official_option(n):
                p = "A + three numbers is how official option folders are named. Use letters, like AXXX."
            if not cm.validate_option_name(n):
                txt, sty = self._load_order_text(root, n)
                order.configure(text=txt, style=sty)
            else:
                order.configure(text="")
            p = p or validate_lg()
            if p:
                check.configure(text=p, style="Warn.TLabel")
                ok_btn.configure(state="disabled")
                return None
            check.configure(text=f"✓ bin\\option\\{n} will be created.", style="Good.TLabel")
            ok_btn.configure(state="normal")
            return n
        hook["changed"] = validate

        def create(_=None):
            n = validate()
            if not n:
                return
            v = values()
            d.destroy()
            self.dirty = False
            self.opt_var.set(n)
            self.settings["option"] = n
            save_settings(self.settings)

            def made():
                try:
                    cm._ensure_option(self.scan, lambda m: None)
                    what = self._apply_folder_setup(v)
                except Exception as e:
                    traceback.print_exc()
                    messagebox.showerror("New option folder", str(e))
                    return
                self.view_mode.set("mine")
                self.new_character()
                self.fill_tree()
                self.status.set(f"Created bin\\option\\{n} with {what}. Click '+ New character' to add the "
                                "first character.")
            self.load_game(then=made)
        ok_btn.configure(command=create)
        name.trace_add("write", validate)
        validate()
        d.bind("<Return>", create)
        d.bind("<Escape>", lambda e: d.destroy())
        self._center(d)
        d.grab_set()
        ne.focus_set()
        ne.select_range(0, "end")

    def folder_setup_dialog(self):
        """After the welcome window made the first option folder: pick its version label + group."""
        if not self.scan:
            return
        d = self._toplevel()
        d.title(f"Set up {self.scan.my_option}")
        d.transient(self.root)
        d.resizable(False, False)
        fr = ttk.Frame(d, padding=16)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=f"Version label and group for {self.scan.my_option}", style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text="Every character in this folder gets this version label and group. You can change them "
                           "later on the folder's first character.", wraplength=470, justify="left").pack(
            anchor="w", pady=(4, 0))
        validate_lg, values, hook = self._label_group_sections(fr)
        check = ttk.Label(fr, text="", style="Warn.TLabel", wraplength=470, justify="left")
        check.pack(anchor="w", pady=(10, 0))
        btns = ttk.Frame(fr)
        btns.pack(fill="x", pady=(10, 0))
        ok_btn = ttk.Button(btns, text="Save", style="Accent.TButton")
        ok_btn.pack(side="right")
        ttk.Button(btns, text="Later", command=d.destroy).pack(side="right", padx=(0, 6))

        def validate(*_):
            p = validate_lg()
            check.configure(text=p or "")
            ok_btn.configure(state="disabled" if p else "normal")
            return p
        hook["changed"] = validate

        def ok(_=None):
            if validate():
                return
            try:
                what = self._apply_folder_setup(values())
            except Exception as e:
                messagebox.showerror("Set up folder", str(e), parent=d)
                return
            d.destroy()
            self.new_character()
            self.status.set(f"{self.scan.my_option} uses {what}. Click '+ New character' to start.")
        ok_btn.configure(command=ok)
        validate()
        d.bind("<Return>", ok)
        self._center(d)
        d.grab_set()

    def rename_option_dialog(self):
        if not self.scan:
            messagebox.showwarning("Rename", "Load your game folder first.")
            return
        if self.dirty and not messagebox.askyesno("Rename", "Unsaved changes to the current character will be lost. "
                                                            "Continue?"):
            return
        cur = self.scan.my_option
        d = self._toplevel()
        d.title("Rename option folder")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        exists = os.path.isdir(self.scan.my_dir)
        ttk.Label(fr, text=f"Rename bin\\option\\{cur}" + ("" if exists else " (not created yet)") +
                           ". Characters, groups and labels inside keep their IDs. Close the game first. "
                           "Folders load in name order, so if two folders change the same thing, the one "
                           "later in the alphabet wins.", wraplength=380, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        name = tk.StringVar(value=cur)
        ttk.Label(fr, text="New name").grid(row=1, column=0, sticky="w")
        ne = ttk.Entry(fr, textvariable=name, width=8)
        ne.grid(row=1, column=1, sticky="w")
        ne.focus_set()
        ne.select_range(0, "end")
        check = ttk.Label(fr, text="", wraplength=380)
        check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def validate(*_):
            n = name.get().strip().upper()
            if n == cur:
                check.configure(text="Type a new name.", style="Hint.TLabel")
                return None
            p = cm.option_name_problem(self.scan.root, n)
            check.configure(text=p or f"✓ {cur} → {n}", style="Warn.TLabel" if p else "Good.TLabel")
            return None if p else n
        name.trace_add("write", validate)
        validate()

        def ok():
            n = validate()
            if not n:
                return
            try:
                done = cm.rename_option_folder(self.scan, n, DATA_DIR)
                if os.path.abspath(APP_DIR) != os.path.abspath(DATA_DIR):
                    old_p = os.path.join(APP_DIR, "my_characters", cur)
                    if os.path.isdir(old_p) and not os.path.exists(os.path.join(APP_DIR, "my_characters", n)):
                        os.rename(old_p, os.path.join(APP_DIR, "my_characters", n))
            except Exception as e:
                messagebox.showerror("Rename", f"Couldn't rename (is the game or a folder window open?)\n\n{e}",
                                     parent=d)
                return
            offered = self.settings.get("label_offered", [])
            if cur in offered:
                offered.append(n)
            self.settings["option"] = n
            save_settings(self.settings)
            self.opt_var.set(n)
            self.dirty = False
            d.destroy()
            self.status.set(f"Renamed {cur} to {n}." + (" " + "; ".join(done) if done else ""))
            self.load_game(then=lambda: self.status.set(f"Renamed {cur} to {n}."))
        bf = ttk.Frame(fr)
        bf.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Rename", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: ok())

    def maybe_offer_label(self, is_new: bool | None = None):
        """New option folder without its own version label: offer one (once per folder)."""
        s = self.scan
        if not s or s.my_tags:
            return
        asked = self.settings.setdefault("label_offered", [])
        if s.my_option in asked:
            return
        asked.append(s.my_option)
        save_settings(self.settings)
        if is_new is None:
            is_new = not os.path.isdir(s.my_dir)
        rec = cm.next_free_tag(s)
        if messagebox.askyesno(
                "Version label for " + s.my_option,
                (f"{s.my_option} is a new option folder." if is_new else f"{s.my_option} has no version label of its own.")
                + f"\n\nGive it its own version label (the text shown above the group name when you get a "
                  f"character)? Make your own, like '{self.example_name()}'.\n\nRecommended free label ID: {rec}\n"
                  f"(You can also do this later with 'New…' next to Version label.)"):
            self.new_tag_dialog(suggest_title=self.example_name())

    def fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.slot_img.configure(image="")
        self.slot_info.configure(text="")
        self.btn_use.configure(state="disabled")
        self.btn_delete.configure(state="disabled")
        if not self.scan:
            return
        q = self.search_var.get().strip().lower()
        only_mine = self.view_mode.get() == "mine"
        odd = self.odd_slots()
        lead = self.lead()
        for s in sorted(self.scan.slots.values(), key=lambda s: s.chara_id):
            if only_mine and not s.custom:
                continue
            if not s.dds_dir and not s.custom:
                continue
            label = s.name + (f"  (+{s.transforms} forms)" if s.transforms else "")
            if q and q not in f"{s.chara_id} {s.name} {s.works} {s.source}".lower():
                continue
            src = s.source + (" (repl.)" if s.custom and s.replaces else "")
            if s.chara_id in odd:
                label = "⚠ " + label
            self.tree.insert("", "end", iid=str(s.chara_id), values=(s.chara_id, label, s.works, src),
                             tags=("odd",) if s.chara_id in odd else (("custom",) if s.custom else ()))
        if odd and lead:
            self.odd_note.configure(text=f"⚠ {len(odd)} of your characters don't have the same group / version "
                                         f"label as '{lead.name}', the first one in {self.scan.my_option}.")
            self.btn_match.configure(text=f"Match them to '{lead.name[:18]}' now")
            self.btn_match.pack(side="top", anchor="w", pady=(2, 0))
        else:
            self.odd_note.configure(text="")
            self.btn_match.pack_forget()
        if only_mine and not self.tree.get_children():
            self.slot_info.configure(text=f"Your folder {self.scan.my_option} is empty.\n"
                                          "Click '+ New character', or switch to 'All' to replace one.")

    def selected_slot(self):
        sel = self.tree.selection()
        if not sel or not self.scan:
            return None
        return self.scan.slots.get(int(sel[0]))

    def on_tree_select(self, _e=None):
        s = self.selected_slot()
        if not s:
            return
        im = cm.load_dds_image(self.scan, s.image_id, "01")
        size = int(150 * self.ui)
        self._photos["slot"] = ImageTk.PhotoImage(on_checker(im, size) if im else checker(size, size))
        self.slot_img.configure(image=self._photos["slot"])
        tf = f"\n{s.transforms} transformation(s)" if s.transforms else ""
        kind = ("yours (replaces a game character)" if s.replaces else "yours (new character)") if s.custom \
            else f"from {s.source}"
        why = self.odd_slots().get(s.chara_id)
        self.slot_info.configure(text=f"{s.name}\nID {s.chara_id}\n{s.works}\n{kind}{tf}" +
                                 ("\n\n⚠ " + "\n⚠ ".join(why) if why else ""))
        self.btn_use.configure(state="normal", text="Edit this" if s.custom else "Replace this one")
        self.btn_delete.configure(state="normal" if s.custom else "disabled")

    def open_option_folder(self):
        if not self.scan:
            return
        p = self.scan.my_dir if os.path.isdir(self.scan.my_dir) else cm.option_dir(self.scan.root)
        try:
            os.startfile(p)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("Folder", p)

    # ================================================================== targets
    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        return messagebox.askyesno("Unsaved changes", "Discard the character you're working on?")

    def new_character(self):
        if not self._confirm_discard():
            return
        self.mode = "new"
        self.target_id = None
        self.forms = [Form(0)]
        self.cur = 0
        self.name_var.set("")
        self.sort_var.set("")
        self.sort_edited = False
        self.illus_var.set("")
        if self.scan:
            self.refresh_tags(select=self.scan.newest_tag)
            self.id_var.set(str(cm.next_free_id(self.scan, int(self.settings.get("start_id", 70000)))))
            mine = [i for i in self.scan.my_works]
            if mine:
                w = sorted(mine)[0]
                self.works_var.set(f"{w} · {self.scan.works[w]} (mine)")
            fd = self.settings.get("folder_defaults", {}).get(self.scan.my_option)
            if fd and self.lead() is None:   # empty folder: the group + label picked when it was made
                if fd.get("works") in self.scan.works:
                    self.works_var.set(self._works_text(fd["works"]))
                if fd.get("tag") in self.scan.release_tags:
                    self.tag_var.set(self.tag_label(fd["tag"]))
        self.dirty = False
        self.after_target_change()

    def use_selected(self):
        s = self.selected_slot()
        if not s:
            return
        if s.custom:
            self.edit_character(s)
        else:
            self.replace_character(s)

    def replace_character(self, s):
        if self.mode in ("new", "replace"):
            pass  # keep the artwork already prepared, just change which slot it goes into
        elif not self._confirm_discard():
            return
        else:
            self.forms = [Form(0)]
            self.cur = 0
            self.name_var.set("")
            self.sort_edited = False
        self.mode = "replace"
        self.target_id = s.chara_id
        self.refresh_tags(select=self.scan.newest_tag)
        self.id_var.set(str(s.chara_id))
        self.keep_forms.set(False)
        self.after_target_change()
        self.status.set(f"Will replace '{s.name}' (ID {s.chara_id}). Open your image, then click Replace.")

    def edit_character(self, s):
        if not self._confirm_discard():
            return
        self._show_busy(f"One second… setting up '{s.name}'")
        self.root.after(40, lambda: self._edit_load_guarded(s))   # let the little window appear first

    def _edit_load_guarded(self, s):
        try:
            self._edit_load(s)
        except Exception as e:   # never leave the little window stuck on screen
            traceback.print_exc()
            self._close_busy()
            messagebox.showerror("Open character", f"Couldn't open '{s.name}':\n{e}")

    def _edit_load(self, s):
        self.mode = "edit"
        self.target_id = s.chara_id
        self.id_var.set(str(s.chara_id))
        self.name_var.set(s.name)
        self.sort_var.set(s.sort_name)
        self.sort_edited = True
        self.illus_var.set(s.illustrator)
        self.refresh_tags(select=s.release_tag if s.release_tag is not None else self.scan.newest_tag)
        self.works_var.set(f"{s.works_id} · {s.works}" + (" (mine)" if s.works_id in self.scan.my_works else ""))
        proj = find_project(self.scan.my_option, s.chara_id)
        saved = {}
        if proj:
            data, sources = proj
            for fi in data.get("forms", []):
                saved[fi["index"]] = (fi, sources.get(fi["index"]))
        # the game files decide which looks exist; the project supplies pictures + box positions
        looks = [(0, "", 1, s.image_id)] + [(f.index, f.name, f.rank, f.image_id) for f in s.forms]
        forms, recover = [], []
        for idx, fname, rank, iid in looks:
            fi, src = saved.get(idx, (None, None))
            f = Form(idx, fname or (fi or {}).get("name", ""), rank)
            if fi and src is not None and fi.get("frames"):
                f.set_image(src, fi.get("path", ""), fi.get("frames"))
                f.linked = fi.get("linked", True)
            else:
                im = cm.load_dds_image(self.scan, iid, "00")
                if im is not None:
                    fr = cc.auto_frames(im)
                    fr["00"] = (0.0, 0.0, float(im.width))
                    f.set_image(im, "", fr)
                    recover.append((f, iid))
            forms.append(f)
        self.forms = sorted(forms, key=lambda f: f.index)
        self.cur = 0
        self.dirty = False
        self.after_target_change()
        if not recover:
            self.status.set(f"Editing '{s.name}' — boxes restored from your saved project.")
            self.root.after(150, self._close_busy)   # boxes are drawn; close once they're on screen
            return
        self.status.set(f"Editing '{s.name}' — no saved project found, finding your box positions "
                        "from the game files…")
        scan, token = self.scan, object()
        self._recover_token = token

        def work():
            found = []
            for f, iid in recover:
                for k in ("01", "02"):
                    small = cm.load_dds_image(scan, iid, k)
                    try:
                        r = cc.locate_crop(f.src, small) if small is not None else None
                    except Exception:
                        r = None
                    if r:
                        found.append((f, k, list(r)))
            self.root.after(0, done, found)

        def done(found):
            self._close_busy()
            if getattr(self, "_recover_token", None) is not token or self.target_id != s.chara_id:
                return
            for f, k, r in found:
                f.frames[k] = r
            self._snap_base()
            self.redraw()
            self.schedule_preview()
            self.status.set(f"Editing '{s.name}' — boxes rebuilt from the game files (no saved project was "
                            "found). From now on your boxes are saved when you click Save changes.")
        threading.Thread(target=work, daemon=True).start()

    def delete_selected(self):
        s = self.selected_slot()
        if not (s and s.custom and self.scan):
            return
        what = "The original character comes back." if s.replaces else "It's removed from the game."
        if not messagebox.askyesno("Remove", f"Delete '{s.name}' (ID {s.chara_id}) from {self.scan.my_option}?\n{what}"):
            return
        removed = cm.delete_character(self.scan, s.chara_id)
        pdir = cm.project_dir(DATA_DIR, self.scan.my_option, s.chara_id)
        self.status.set(f"Removed {len(removed)} folder(s). Rescanning… (project copy kept in {pdir})")
        if self.target_id == s.chara_id:
            self.dirty = False
            self.new_character()
        self.load_game()

    def after_target_change(self):
        self._snap_base()
        self.apply_lead_lock()
        self.refresh_forms_strip()
        self.load_form_fields()
        self.redraw()
        self.schedule_preview()
        self.update_target_label()

    def update_target_label(self):
        opt = self.opt_var.get().strip().upper()
        if self.mode == "new":
            self.target_lbl.configure(text=f"NEW character → {opt}")
            self.btn_save.configure(text=f"Add to {opt}")
            self.id_entry.configure(state="normal")
        elif self.mode == "replace":
            s = self.scan.slots.get(self.target_id) if self.scan else None
            self.target_lbl.configure(text=f"REPLACING '{s.name if s else self.target_id}' (ID {self.target_id}) → {opt}")
            self.btn_save.configure(text="Replace character")
            self.id_entry.configure(state="disabled")
        else:
            self.target_lbl.configure(text=f"EDITING your character ID {self.target_id} in {opt}")
            self.btn_save.configure(text="Save changes")
            self.id_entry.configure(state="disabled")
        if self.mode == "replace" and len(self.forms) == 1:
            self.keep_cb.grid()
        else:
            self.keep_cb.grid_remove()

    # ================================================================== forms
    @property
    def form(self) -> Form:
        return self.forms[self.cur]

    def refresh_forms_strip(self):
        for w in self.forms_bar.winfo_children():
            w.destroy()
        ttk.Label(self.forms_bar, text="Looks", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        self.form_choice = tk.IntVar(value=self.cur)
        for i, f in enumerate(self.forms):
            label = "Base" if f.index == 0 else f"T{f.index} {f.name[:14]}".rstrip()
            if f.src is None:
                label += " (no image)"
            ttk.Radiobutton(self.forms_bar, text=label, value=i, variable=self.form_choice, style="Chip.Toolbutton",
                            command=lambda: self.select_form(self.form_choice.get())).pack(side="left", padx=(0, 4))
        if len(self.forms) < cm.MAX_FORMS:
            ttk.Button(self.forms_bar, text="+ Transformation", command=self.add_form).pack(side="left", padx=(10, 2))
        if self.cur > 0 and self.cur == len(self.forms) - 1:
            ttk.Button(self.forms_bar, text="Remove this look", command=self.remove_form,
                       style="Danger.TButton").pack(side="left")

    def select_form(self, i):
        self.cur = i
        self.load_form_fields()
        self.refresh_forms_strip()
        self.redraw()
        self.schedule_preview()

    def add_form(self):
        n = len(self.forms)
        nm = self.name_var.get().strip()
        f = Form(n, f"{nm}: Form {n}" if nm else f"Form {n}", 5 * n)
        self.forms.append(f)
        self.dirty = True
        self.select_form(n)
        self.update_target_label()
        self.status.set(f"Added transformation {n}. Open an image for it.")

    def remove_form(self):
        if self.cur == 0:
            return
        del self.forms[self.cur]
        self.cur = len(self.forms) - 1
        self.dirty = True
        self.select_form(self.cur)
        self.update_target_label()

    def load_form_fields(self):
        self._loading_form = True
        f = self.form
        if f.index == 0:
            self.form_box.configure(text="This look: Base")
            for w in (self.fname_lbl, self.fname_entry, self.frank_lbl, self.frank_spin, self.linked_row):
                w.grid_remove()
            self.form_box.grid_remove()   # nothing to set for the Base look
        else:
            self.form_box.grid()
            self.form_box.configure(text=f"This look: Transformation {f.index}")
            self.fname_lbl.grid(row=1, column=0, sticky="w", pady=2)
            self.fname_entry.grid(row=1, column=1, sticky="ew", pady=2, padx=(6, 0))
            self.frank_lbl.grid(row=2, column=0, sticky="w", pady=2)
            self.frank_spin.grid(row=2, column=1, sticky="w", pady=2, padx=(6, 0))
            self.linked_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 0))
            self.linked_var.set(f.linked)
            self.fname_var.set(f.name)
            self.frank_var.set(str(f.rank))
        self._loading_form = False

    def _form_fields_changed(self, *_):
        if self._loading_form or self.form.index == 0:
            return
        self.form.name = self.fname_var.get()
        try:
            self.form.rank = max(1, int(self.frank_var.get()))
        except ValueError:
            pass
        self.dirty = True

    # ================================================================== box positions across looks
    # A new transformation's boxes start where the Base's are. After that:
    #   * moving / resizing a box on a TRANSFORMATION only changes that transformation;
    #   * moving / resizing a box on the BASE moves the same box on every transformation with
    #     "Move with the Base's boxes" ticked, by the same amount, so their own fine-tuning is kept.
    # If a transformation's picture is a different size, positions and moves are scaled to it.
    @staticmethod
    def _scaled(frames: dict, src_from, src_to) -> dict:
        if src_from is None or src_to is None or src_from.size == src_to.size:
            return {k: list(v) for k, v in frames.items()}
        fx, fy = src_to.width / src_from.width, src_to.height / src_from.height
        return {k: [v[0] * fx, v[1] * fy, v[2] * fx] for k, v in frames.items()}

    def _snap_base(self):
        """Remember the Base's boxes, so the next change to them can be passed on as a move."""
        b = self.forms[0]
        self._base_last = (b, {k: list(v) for k, v in b.frames.items()})

    def sync_boxes(self, src_form: Form | None = None):
        cur = src_form or self.form
        if cur.index != 0:
            return   # a transformation's boxes only move that transformation
        last = getattr(self, "_base_last", None)
        if not last or last[0] is not cur or cur.src is None:
            self._snap_base()
            return
        old = last[1]
        for t in self.forms[1:]:
            if not t.linked or t.src is None:
                continue
            fx, fy = t.src.width / cur.src.width, t.src.height / cur.src.height
            for k, v in cur.frames.items():
                if k in old and k in t.frames:
                    tx, ty, ts = t.frames[k]
                    t.frames[k] = [tx + (v[0] - old[k][0]) * fx, ty + (v[1] - old[k][1]) * fy,
                                   max(16.0, ts + (v[2] - old[k][2]) * fx)]
        self._snap_base()

    def _linked_changed(self):
        f = self.form
        if f.index == 0:
            return
        f.linked = self.linked_var.get()
        self.dirty = True
        self.status.set(f"Transformation {f.index} moves along when you move the Base's boxes." if f.linked else
                        f"Transformation {f.index} stays put when you move the Base's boxes.")

    def match_base(self):
        """Put this transformation's boxes exactly where the Base's are."""
        f, b = self.form, self.forms[0]
        if f.index == 0 or f.src is None or b.src is None:
            return
        f.frames = self._scaled(b.frames, b.src, f.src)
        self.dirty = True
        self.status.set(f"Transformation {f.index}'s boxes are where the Base's are again.")
        self.redraw()
        self.schedule_preview()


    # ================================================================== image
    def open_image(self):
        p = filedialog.askopenfilename(
            title="Character image",
            initialdir=self.settings.get("imgdir") or os.path.expanduser("~"),
            filetypes=[("Images", "*.png *.webp *.jpg *.jpeg *.bmp *.gif *.tga *.dds *.psd"), ("All files", "*.*")])
        if p:
            self.load_image_path(p)

    def load_image_path(self, p):
        try:
            im = cc.load_source(p)
        except Exception as e:
            messagebox.showerror("Open image", f"Couldn't open that image:\n{e}")
            return
        self.settings["imgdir"] = os.path.dirname(p)
        save_settings(self.settings)
        self.form.set_image(im, p)
        f = self.form
        donor = None
        if f.index != 0 and f.linked:
            donor = self.forms[0] if self.forms[0].src is not None else None
        elif f.index == 0:   # Base opened after a transformation: keep the boxes already placed there
            donor = next((t for t in self.forms[1:] if t.linked and t.src is not None), None)
        if donor is not None:
            f.frames = self._scaled(donor.frames, donor.src, im)
        if f.index == 0:
            self._snap_base()
        self.dirty = True
        if self.form.index == 0 and not self.name_var.get():
            self.name_var.set(os.path.splitext(os.path.basename(p))[0].replace("_", " ")[:24])
        msg = f"Opened {os.path.basename(p)} ({im.width}×{im.height})"
        if not cc.has_transparency(im):
            msg += " — no transparency: try 'Remove background'"
        if max(im.size) < 1080:
            msg += " — small image, the 1080 version will be upscaled"
        self.status.set(msg)
        self.refresh_forms_strip()
        self.redraw()
        self.schedule_preview()

    def remove_bg(self):
        f = self.form
        if not f.original:
            return
        f.src = cc.remove_flat_background(f.original, int(self.tol.get()))
        self.dirty = True
        self.status.set(f"Removed flat background (tolerance {int(self.tol.get())}). "
                        "Raise it if bits remain, lower it if the character gets eaten.")
        self._after_cutout(f)

    def remove_bg_ai(self):
        f = self.form
        if not f.original:
            return
        self.status.set("Running AI cut-out (first run downloads a model)…")

        def work():
            try:
                out = cc.remove_background_ai(f.original)
                self.root.after(0, self._ai_done, f, out)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "AI cut-out", str(e))
        threading.Thread(target=work, daemon=True).start()

    def _ai_done(self, f, out):
        f.src = out
        self.dirty = True
        self.status.set("AI cut-out done.")
        self._after_cutout(f)

    def _after_cutout(self, f: Form):
        """After a cut-out the boxes are re-fitted, except on a look that shares its boxes with others
        (re-fitting would move them on every look)."""
        if f.index != 0 and f.linked and self.forms[0].src is not None:
            self._disp_key = None
            self.redraw()
            self.schedule_preview()
        else:
            self.auto_frame()

    def restore_src(self):
        f = self.form
        if f.original:
            f.src = f.original
            self.redraw()
            self.schedule_preview()

    def auto_frame(self):
        f = self.form
        if not f.src:
            return
        f.frames = {k: list(v) for k, v in cc.auto_frames(f.src).items()}
        self.sync_boxes(f)
        self.redraw()
        self.schedule_preview()

    # ================================================================== canvas
    def redraw(self):
        c = self.canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        f = self.form
        if not f.src:
            what = "base look" if f.index == 0 else f"transformation {f.index}"
            c.create_text(cw / 2, ch / 2, fill=th.MUTED, font=self.F["head"], justify="center",
                          text=f"Open an image for the {what}\n(PNG with transparency works best)")
            return
        src, frames = f.src, f.frames
        xs = [0, src.width] + [v[0] for v in frames.values()] + [v[0] + v[2] for v in frames.values()]
        ys = [0, src.height] + [v[1] for v in frames.values()] + [v[1] + v[2] for v in frames.values()]
        bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
        scale = min((cw - 40) / (bx1 - bx0), (ch - 40) / (by1 - by0))
        ox = (cw - (bx1 - bx0) * scale) / 2 - bx0 * scale
        oy = (ch - (by1 - by0) * scale) / 2 - by0 * scale
        if self.drag:
            scale, ox, oy = self.view
        self.view = (scale, ox, oy)
        dw, dh = max(1, int(src.width * scale)), max(1, int(src.height * scale))
        key = (id(src), dw, dh)
        if getattr(self, "_disp_key", None) != key:
            bright = on_checker(src.resize((dw, dh), Image.BILINEAR))
            self._disp = (bright, Image.eval(bright, lambda v: int(v * 0.38)))
            self._disp_key = key
        bright, dark = self._disp
        act = self.active.get()
        ax, ay, asz = frames[act]
        bx = (int(ax * scale), int(ay * scale), int((ax + asz) * scale), int((ay + asz) * scale))
        clip = (max(bx[0], 0), max(bx[1], 0), min(bx[2], dw), min(bx[3], dh))
        disp = dark.copy()
        if clip[2] > clip[0] and clip[3] > clip[1]:
            disp.paste(bright.crop(clip), clip[:2])
        self._photos["canvas"] = ImageTk.PhotoImage(disp)
        c.create_image(ox, oy, image=self._photos["canvas"], anchor="nw")
        for k in [k for k in ("00", "01", "02") if k != act] + [act]:
            x, y, s = frames[k]
            x0, y0 = ox + x * scale, oy + y * scale
            x1, y1 = x0 + s * scale, y0 + s * scale
            col = FRAME_COLORS[k]
            if k == act:
                c.create_rectangle(x0, y0, x1, y1, outline=col, width=3)
                c.create_rectangle(x1 - 7, y1 - 7, x1 + 7, y1 + 7, fill=col, outline="white")
            else:
                c.create_rectangle(x0, y0, x1, y1, outline=col, width=1, dash=(5, 4))
            c.create_text(x0 + 6, y0 + 4, text=FRAME_LABELS[k], fill=col, anchor="nw", font=("Segoe UI", 9, "bold"))

    def _to_src(self, ex, ey):
        s, ox, oy = self.view
        return (ex - ox) / s, (ey - oy) / s

    def on_press(self, e):
        f = self.form
        if not f.src:
            return
        sx, sy = self._to_src(e.x, e.y)
        scale = self.view[0]
        act = self.active.get()
        x, y, s = f.frames[act]
        if abs(sx - (x + s)) * scale < 12 and abs(sy - (y + s)) * scale < 12:
            self.drag = ("resize", act, sx, sy, list(f.frames[act]))
            return
        hit = act
        for k in [act] + [k for k in ("02", "01", "00") if k != act]:
            fx, fy, fs = f.frames[k]
            if fx <= sx <= fx + fs and fy <= sy <= fy + fs:
                hit = k
                break
        self.active.set(hit)
        self.drag = ("move", hit, sx, sy, list(f.frames[hit]))
        self.redraw()

    def on_drag(self, e):
        if not self.drag:
            return
        mode, k, sx0, sy0, f0 = self.drag
        sx, sy = self._to_src(e.x, e.y)
        dx, dy = sx - sx0, sy - sy0
        if e.state & 0x0001:
            dx, dy = dx * 0.25, dy * 0.25
        if mode == "move":
            self.form.frames[k] = [f0[0] + dx, f0[1] + dy, f0[2]]
        else:
            self.form.frames[k] = [f0[0], f0[1], max(16.0, f0[2] + max(dx, dy))]
        self.sync_boxes()
        self.dirty = True
        self.redraw()
        self.schedule_preview(30)

    def on_release(self, _e):
        self.drag = None
        self.redraw()
        self.schedule_preview()

    def zoom_active(self, factor):
        f = self.form
        if not f.src:
            return
        k = self.active.get()
        x, y, s = f.frames[k]
        ns = max(16.0, s * factor)
        f.frames[k] = [x + (s - ns) / 2, y + (s - ns) / 2, ns]
        self.sync_boxes()
        self.dirty = True
        self.redraw()
        self.schedule_preview()

    def nudge(self, dx, dy):
        f = self.form
        if not f.src or isinstance(self.root.focus_get(), (ttk.Entry, tk.Entry, ttk.Combobox, ttk.Spinbox)):
            return
        k = self.active.get()
        step = max(1.0, f.frames[k][2] / 200)
        f.frames[k][0] += dx * step
        f.frames[k][1] += dy * step
        self.sync_boxes()
        self.dirty = True
        self.redraw()
        self.schedule_preview()

    # ================================================================== preview
    def schedule_preview(self, ms=80):
        if self._preview_job:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(ms, self.update_previews)

    def update_previews(self):
        self._preview_job = None
        sizes = {"00": int(200 * self.ui), "01": int(128 * self.ui), "02": int(64 * self.ui)}
        f = self.form
        for k, lab in (("00", self.p00), ("01", self.p01), ("02", self.p02)):
            n = sizes[k]
            if f.src and k in f.frames:
                im = on_checker(cc.render_frame(f.src, f.frames[k], n))
            else:
                im = checker(n, n)
            self._photos["p" + k] = ImageTk.PhotoImage(im)
            lab.configure(image=self._photos["p" + k])

    def _name_changed(self, *_):
        if not self.sort_edited:
            self.sort_var.set(cc.default_sort_name(self.name_var.get()))

    # ================================================================== groups
    def new_group_dialog(self):
        if not self.scan:
            messagebox.showwarning("Group", "Load your game folder first.")
            return
        d = self._toplevel()
        d.title("New group")
        d.transient(self.root)
        d.grab_set()
        fr = ttk.Frame(d, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Groups are the folders characters are sorted into (like 'CHUNITHM').",
                  wraplength=300).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        gid = tk.StringVar(value=str(cm.next_free_group(self.scan, int(self.settings.get("group_start", 7000)))))
        gname = tk.StringVar(value="My Characters")
        ttk.Label(fr, text="Group ID").grid(row=1, column=0, sticky="w")
        ttk.Entry(fr, textvariable=gid, width=10).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(fr, text="Group name").grid(row=2, column=0, sticky="w", padx=(0, 6))
        ne = ttk.Entry(fr, textvariable=gname, width=30)
        ne.grid(row=2, column=1, sticky="ew", pady=2)
        ne.focus_set()

        def ok():
            try:
                i = int(gid.get())
                cm.create_group(self.scan, i, gname.get().strip() or "My Characters", self.selected_tag())
            except Exception as e:
                messagebox.showerror("New group", str(e), parent=d)
                return
            self.refresh_works()
            self.works_var.set(f"{i} · {self.scan.works[i]} (mine)")
            self.status.set(f"Created group {i} '{self.scan.works[i]}' in {self.scan.my_option} "
                            "(group sort lists updated).")
            d.destroy()
        bf = ttk.Frame(fr)
        bf.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bf, text="Create", command=ok).pack(side="left", padx=4)
        ttk.Button(bf, text="Cancel", command=d.destroy).pack(side="left")
        d.bind("<Return>", lambda e: ok())

    # ================================================================== check folder
    def check_dialog(self, folder: str | None = None):
        if not self.scan:
            messagebox.showwarning("Check", "Load your game folder first.")
            return
        if folder is None:
            folder = filedialog.askdirectory(
                title="Option folder to check (yours, another one in bin\\option, or a downloaded pack)",
                initialdir=self.scan.my_dir if os.path.isdir(self.scan.my_dir) else cm.option_dir(self.scan.root))
            if not folder:
                return
        folder = os.path.abspath(folder)
        d = self._toplevel()
        d.title(f"Check — {folder}")
        d.geometry(f"{int(820 * self.ui)}x{int(520 * self.ui)}")
        fr = ttk.Frame(d, padding=10)
        fr.pack(fill="both", expand=True)
        txt = tk.Text(fr, wrap="word", font=self.F["body"], relief="flat", background=th.WELL, foreground=th.TEXT,
                      insertbackground=th.TEXT, padx=10, pady=8, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        for tag, col in (("ERROR", th.DANGER), ("WARN", th.WARN), ("OK", th.OK), ("INFO", th.MUTED)):
            txt.tag_configure(tag, foreground=col)

        def run():
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            res = cm.check_folder(self.scan, folder)
            for lvl, msg in res:
                txt.insert("end", f"{lvl:5}  ", lvl)
                txt.insert("end", msg + "\n")
            txt.configure(state="disabled")

        def fix():
            if not messagebox.askyesno("Fix", "Apply the safe automatic fixes to this folder?\n\n"
                                              "• rename misnamed DDS files to what DDSImage.xml expects\n"
                                              "• rebuild the group sort lists with all your game's groups\n"
                                              "• add data.conf if missing", parent=d):
                return
            done = cm.fix_folder(self.scan, folder)
            run()
            txt.configure(state="normal")
            txt.insert("1.0", "FIXED:\n" + ("\n".join("  • " + x for x in done) or "  nothing to fix") + "\n\n", "OK")
            txt.configure(state="disabled")

        def install():
            name = os.path.basename(folder).upper()
            if cm.validate_option_name(name):
                name = "A" + "".join(ch for ch in name if ch.isalnum())[:3].upper().ljust(3, "0")
            dst = os.path.join(cm.option_dir(self.scan.root), name)
            if os.path.exists(dst):
                messagebox.showerror("Install", f"{dst} already exists.", parent=d)
                return
            if not messagebox.askyesno("Install", f"Copy this folder into your game as\n{dst} ?", parent=d):
                return
            shutil.copytree(folder, dst)
            messagebox.showinfo("Install", f"Installed as {name}. Start the game to see it.", parent=d)
            d.destroy()
            self.load_game()

        bf = ttk.Frame(fr)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Re-check", command=run).pack(side="left")
        ttk.Button(bf, text="Fix", command=fix).pack(side="left", padx=6)
        inside = os.path.abspath(os.path.dirname(folder)) == os.path.abspath(cm.option_dir(self.scan.root))
        if not inside:
            ttk.Button(bf, text="Copy into game…", command=install).pack(side="left")
        ttk.Button(bf, text="Close", command=d.destroy).pack(side="right")
        run()

    # ================================================================== save
    # ================================================================== one group + label per folder
    # The FIRST character in your option folder (lowest ID, top of the "My folder" list) decides the group
    # and version label for every character in that folder. Only that one can change them, and saving it
    # gives all the others the same group + label. Every other character just follows it (the fields are
    # locked). An empty folder's first character can pick freely.
    def lead(self, exclude: int | None = None):
        """The first character in your folder (lowest ID). Replacements of official characters don't count:
        they keep the game's own group + label."""
        if not self.scan:
            return None
        mine = sorted((s for s in self.scan.slots.values() if s.custom and s.chara_id != exclude
                       and not self.scan.official_original(s.chara_id)), key=lambda s: s.chara_id)
        return mine[0] if mine else None

    def official_lock_slot(self):
        """The game's own version of the character being replaced/edited, if it's an official character
        (from an official option A000, A001…). Its group + version label can't be changed."""
        if not self.scan or self.target_id is None:
            return None
        if self.mode == "replace":
            return self.scan.official_original(self.target_id)
        if self.mode == "edit":
            s = self.scan.slots.get(self.target_id)
            if s and s.custom and s.replaces:
                return self.scan.official_original(self.target_id)
        return None

    def editing_lead(self) -> bool:
        ld = self.lead()
        return self.mode == "edit" and ld is not None and self.target_id == ld.chara_id

    def group_lock(self):
        """('official', original) | ('lead', first character) | None when group + label may be changed."""
        o = self.official_lock_slot()
        if o is not None:
            return "official", o
        ld = self.lead()
        if ld is not None and not self.editing_lead():
            return "lead", ld
        return None

    def lead_locked(self) -> bool:
        return self.group_lock() is not None

    def _works_text(self, g) -> str:
        return f"{g} · {self.scan.works.get(g, g)}" + (" (mine)" if g in self.scan.my_works else "")

    def apply_lock_values(self, slot=None):
        """Put the locked group + label into the fields."""
        lk = self.group_lock()
        slot = slot or (lk[1] if lk else None)
        if not slot:
            return
        self.works_var.set(self._works_text(slot.works_id) if slot.works_id in self.scan.works
                           else f"{slot.works_id} · {slot.works}")
        if slot.release_tag is not None and slot.release_tag in self.scan.release_tags:
            self.tag_var.set(self.tag_label(slot.release_tag))

    def apply_lead_lock(self):
        if not hasattr(self, "lead_info"):
            return
        lk = self.group_lock()
        if lk:
            self.apply_lock_values(lk[1])
        st = "disabled" if lk else "normal"
        self.works_box.configure(state=st)
        self.tag_box.configure(state="disabled" if lk else "readonly")
        self.btn_group_new.configure(state=st)
        self.btn_tag_new.configure(state=st)
        ld = self.lead()
        if lk and lk[0] == "official":
            self.lead_info.configure(text=f"🔒 Official character (from {lk[1].source}): it keeps the game's own "
                                          "group and version label.")
        elif lk:
            self.lead_info.configure(text=f"🔒 Group and version label follow '{ld.name}' (ID {ld.chara_id}), the "
                                          f"first character in {self.scan.my_option}. Edit that one to change "
                                          "them for every character here.")
        elif ld is not None:
            n = sum(1 for s in self.scan.slots.values() if s.custom and not self.scan.official_original(s.chara_id)) - 1
            self.lead_info.configure(text=f"This is the first character in {self.scan.my_option}: its group and "
                                          f"version label are used by every character you add here." +
                                          (f" Changing them changes them for the other {n} too when you save."
                                           if n > 0 else ""))
        else:
            self.lead_info.configure(text="")
        self.update_tag_info()

    def odd_slots(self) -> dict:
        """Your characters whose group or label differs from the first one in the folder: {id: [reasons]}."""
        out = {}
        ld = self.lead()
        if not ld:
            return out
        for s in self.scan.slots.values():
            if not s.custom or s.chara_id == ld.chara_id or self.scan.official_original(s.chara_id):
                continue
            why = []
            if s.works_id != ld.works_id:
                why.append(f"In group '{s.works}', but '{ld.name}' (the first one) is in '{ld.works}'.")
            if ld.release_tag is not None and s.release_tag != ld.release_tag:
                why.append(f"Version label {s.release_tag} instead of {ld.release_tag} like '{ld.name}'.")
            if why:
                out[s.chara_id] = why
        return out

    def match_folder(self):
        """Give every character in the folder the first one's group + label now (no need to re-save them)."""
        ld = self.lead()
        if not ld or not messagebox.askyesno(
                "Match group + label",
                f"Give every character in {self.scan.my_option} the same group and version label as "
                f"'{ld.name}'?\n\nGroup: {ld.works}\nVersion label: "
                f"{self.scan.release_tags.get(ld.release_tag, ('', ld.release_tag))[1]}"):
            return
        try:
            changed = cm.apply_group_and_tag(self.scan, ld.works_id, ld.works, ld.release_tag)
        except Exception as e:
            messagebox.showerror("Match group + label", str(e))
            return
        self.fill_tree()
        self.apply_lead_lock()
        self.status.set(f"Updated {len(changed)} character(s) to match '{ld.name}'.")

    def save(self):
        if not self.scan:
            messagebox.showwarning("Save", "Load your game folder first.")
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Save", "Give your character a name.")
            return
        missing = [("Base" if f.index == 0 else f"transformation {f.index}") for f in self.forms if f.src is None]
        if missing:
            messagebox.showwarning("Save", "Open an image for: " + ", ".join(missing))
            return
        opt = self.opt_var.get().strip().upper()
        if opt != self.scan.my_option:
            self.load_game(then=self.save)
            return
        wtxt = self.works_var.get().replace("(mine)", "").strip()
        try:
            wid = int(wtxt.split("·")[0].strip())
            wname = wtxt.split("·", 1)[1].strip() if "·" in wtxt else self.scan.works.get(wid, "CHUNITHM")
        except ValueError:
            messagebox.showwarning("Group", "Group must look like '9000 · CHUNITHM'.")
            return
        lock = self.group_lock()
        save_tag = self.selected_tag()
        if lock:   # official character, or not the first one in the folder: group + label are fixed
            wid, wname = lock[1].works_id, lock[1].works
            self.apply_lock_values(lock[1])
            save_tag = lock[1].release_tag if lock[0] == "official" else self.selected_tag()
        sync_others = lock is None
        if wid not in self.scan.works:
            if not messagebox.askyesno("Group", f"Group {wid} doesn't exist yet. Create it as '{wname}'?"):
                return
            cm.create_group(self.scan, wid, wname, self.selected_tag())
            self.refresh_works()
        if self.mode == "new":
            try:
                cid = int(self.id_var.get())
            except ValueError:
                messagebox.showwarning("ID", "The ID must be a number ending in 0, like 70000.")
                return
            p = cm.id_problem(self.scan, cid)
            if p:
                messagebox.showwarning("ID", p + f"\n\nNext free ID: {cm.next_free_id(self.scan, cid)}")
                return
            msg = f"Add '{name}' as a new character (ID {cid}) to {opt}?"
        elif self.mode == "replace":
            cid = self.target_id
            s = self.scan.slots[cid]
            msg = (f"Replace '{s.name}' (ID {cid}) with '{name}'?\n\nThe original isn't deleted — remove yours "
                   f"from {opt} any time to get it back.")
        else:
            cid = self.target_id
            msg = f"Save changes to '{name}' (ID {cid})?"
        n_forms = len(self.forms) - 1
        if n_forms:
            msg += f"\n\nIncludes {n_forms} transformation(s)."
        others = [x for x in self.scan.slots.values() if x.custom and x.chara_id != cid
                  and not self.scan.official_original(x.chara_id)]
        new_tag = save_tag
        moving = [x for x in others if x.works_id != wid or (new_tag is not None and x.release_tag != new_tag)]
        if sync_others and moving:
            msg += (f"\n\nThis is the first character in {opt}, so your other {len(moving)} character(s) there "
                    f"get the same group and version label too.")
        if not messagebox.askyesno("Save character", msg):
            return
        self.settings["option"] = opt
        self.settings["fmt"] = self.fmt_var.get()
        save_settings(self.settings)
        self.btn_save.configure(state="disabled")
        self.status.set("Rendering and encoding DDS files…")
        self._show_saving(name, len(self.forms))
        forms = list(self.forms)
        mode = self.mode
        args = dict(mode=mode, chara_id=cid, name=name, sort_name=self.sort_var.get().strip() or cc.default_sort_name(name),
                    works_id=wid, works_name=wname, illustrator=self.illus_var.get().strip(),
                    keep_original_forms=self.keep_forms.get(), fmt=FORMATS.get(self.fmt_var.get(), "bc3"),
                    release_tag=save_tag)

        def work():
            try:
                rendered = {}
                for i, f in enumerate(forms):
                    what = "Base" if f.index == 0 else f"transformation {f.index}"
                    self.root.after(0, self._saving_step, f"Cropping the pictures ({what})…", i, len(forms) + 1)
                    rendered[f.index] = f.render()
                specs = [cm.FormSpec(f.index, rendered[f.index], f.name, f.rank) for f in forms]
                self.root.after(0, self._saving_step, "Converting to DDS and writing the game files…",
                                len(forms), len(forms) + 1)
                res = cm.write_character(self.scan, forms=specs, **args)
                if sync_others and moving:
                    self.root.after(0, self._saving_step, "Giving your other characters the same group + label…",
                                    len(forms), len(forms) + 1)
                    cm.apply_group_and_tag(self.scan, wid, wname, args["release_tag"], skip=cid)
                self.root.after(0, self._saving_step, "Saving your project…", len(forms) + 1, len(forms) + 1)
                cm.save_project(
                    cm.project_dir(DATA_DIR, self.scan.my_option, cid),
                    {"chara_id": cid, "name": name, "mode": mode, "works_id": wid, "works": wname,
                     "forms": [{"index": f.index, "name": f.name, "rank": f.rank, "frames": f.frames,
                                "path": f.path, "linked": f.linked} for f in forms]},
                    sources={f.index: f.src for f in forms}, outputs=rendered)
                self.root.after(0, self._saved, res, cid, name, wname)
            except Exception as e:
                traceback.print_exc()
                self.root.after(0, self._save_failed, e)
        threading.Thread(target=work, daemon=True).start()

    # ================================================================== "one second" while a character opens
    def _show_busy(self, text: str):
        self._close_busy()
        d = self._toplevel()
        d.title("One second…")
        d.transient(self.root)
        d.resizable(False, False)
        d.protocol("WM_DELETE_WINDOW", lambda: None)
        fr = ttk.Frame(d, padding=(22, 16))
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text=text, style="Head.TLabel").pack(anchor="w")
        ttk.Label(fr, text="Placing the Large, Select and Nameplate boxes…", style="Hint.TLabel").pack(anchor="w",
                                                                                                     pady=(4, 8))
        st = ttk.Style(self.root)
        st.configure("Wait.Horizontal.TProgressbar", troughcolor=th.WELL, background=th.PRIMARY,
                     bordercolor=th.LINE, lightcolor=th.PRIMARY, darkcolor=th.PRIMARY)
        bar = ttk.Progressbar(fr, mode="indeterminate", length=int(300 * self.ui), style="Wait.Horizontal.TProgressbar")
        bar.pack(fill="x")
        bar.start(12)
        self._busy = d
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_reqheight()) // 3
        d.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            d.grab_set()
        except tk.TclError:
            pass

    def _close_busy(self):
        d = getattr(self, "_busy", None)
        self._busy = None
        if d:
            try:
                d.grab_release()
                d.destroy()
            except tk.TclError:
                pass

    # ================================================================== "please wait" while saving
    def _show_saving(self, name: str, n_looks: int):
        self._close_saving()
        d = self._toplevel()
        d.title("Saving… please wait")
        d.transient(self.root)
        d.resizable(False, False)
        d.protocol("WM_DELETE_WINDOW", lambda: None)   # goes away by itself when the save is done
        fr = ttk.Frame(d, padding=18)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Saving your character…", style="Head.TLabel").pack(anchor="w")
        looks = f" and its {n_looks - 1} transformation(s)" if n_looks > 1 else ""
        ttk.Label(fr, text=f"Please wait while '{name}'{looks} is saved and converted to the game's\n"
                           "DDS format. This can take a little while.", justify="left").pack(anchor="w", pady=(4, 12))
        st = ttk.Style(self.root)
        st.configure("Wait.Horizontal.TProgressbar", troughcolor=th.WELL, background=th.PRIMARY,
                     bordercolor=th.LINE, lightcolor=th.PRIMARY, darkcolor=th.PRIMARY)
        bar = ttk.Progressbar(fr, mode="determinate", length=int(400 * self.ui), maximum=n_looks + 1,
                              style="Wait.Horizontal.TProgressbar")
        bar.pack(fill="x")
        lbl = ttk.Label(fr, text="Starting…", style="Hint.TLabel")
        lbl.pack(anchor="w", pady=(6, 0))
        self._saving = (d, bar, lbl)
        d.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - d.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - d.winfo_reqheight()) // 3
        d.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            d.grab_set()
        except tk.TclError:
            pass

    def _saving_step(self, text: str, i: int, n: int):
        if getattr(self, "_saving", None):
            d, bar, lbl = self._saving
            bar.configure(maximum=n, value=i)
            lbl.configure(text=text)

    def _close_saving(self):
        w = getattr(self, "_saving", None)
        self._saving = None
        if w:
            try:
                w[0].grab_release()
                w[0].destroy()
            except tk.TclError:
                pass

    def _saved(self, res, cid, name, wname):
        self._close_saving()
        self.btn_save.configure(state="normal")
        self.mode = "edit"
        self.target_id = cid
        self.dirty = False
        self.view_mode.set("mine")
        self.fill_tree()
        if self.tree.exists(str(cid)):
            self.tree.selection_set(str(cid))
            self.tree.see(str(cid))
        self.update_target_label()
        self.apply_lead_lock()
        self.status.set(f"Saved '{name}' (ID {cid}) in {res['option']}. Start the game and look in '{wname}'.")
        messagebox.showinfo("Done", f"'{name}' is ready.\n\nStart the game and find it in the '{wname}' group.")

    def _save_failed(self, e):
        self._close_saving()
        self.btn_save.configure(state="normal")
        self.status.set(f"Failed: {e}")
        messagebox.showerror("Save failed", str(e))

    def on_close(self):
        if self._confirm_discard():
            self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
