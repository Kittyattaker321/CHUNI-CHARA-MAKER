# Chuni Chara Maker
# Copyright (C) 2026 Chuni Chara Maker contributors
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Game-folder logic for Chuni Chara Maker.

Two ways to make a character, both written into your own option folder (bin/option/A***):
  * REPLACE  – take over an existing character's ID (the original comes back if you delete yours)
  * NEW      – add a brand-new character with its own ID, like community packs do (80000+ etc.)

Each character has a base look plus up to 9 transformations ("forms"), each with its own
three DDS images, a name and the character rank that unlocks it.  Image IDs are always
<chara id> + <form number>, e.g. chara 70000 -> images 70000, 70001, 70002 …

Also handles custom groups (charaWorks + the WorksSort/WorksNameSort lists) and can check any
option folder for the usual mistakes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field

from PIL import Image

import chuni_core as cc

MAX_FORMS = 10  # base + 9 transformations

# ---------------------------------------------------------------- fallback templates
# Used only if the game's own files can't be found. Same layout as the game's XML.
_CHARA_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<CharaData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>chara000000</dataName>
  <releaseTagName>
    <id>0</id>
    <str>v1 1.00.00</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>2800</id>
    <str>v2_45 00_0</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>0</id>
    <str />
    <data />
  </name>
  <explainText />
  <sortName />
  <works>
    <id>9000</id>
    <str>CHUNITHM</str>
    <data />
  </works>
  <illustratorName>
    <id>50</id>
    <str />
    <data />
  </illustratorName>
  <defaultHave>true</defaultHave>
  <rareType>0</rareType>
  <normCondition>
    <conditions />
  </normCondition>
  <ranking>false</ranking>
  <defaultImages>
    <id>0</id>
    <str />
    <data />
  </defaultImages>
""" + "".join(f"""  <addImages{n}>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages{n}>
""" for n in range(1, 10)) + """  <priority>0</priority>
  <ranks />
</CharaData>"""

_DDS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<DDSImageData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>ddsImage000000</dataName>
  <name>
    <id>0</id>
    <str />
    <data />
  </name>
  <ddsFile0>
    <path />
  </ddsFile0>
  <ddsFile1>
    <path />
  </ddsFile1>
  <ddsFile2>
    <path />
  </ddsFile2>
  <netOpenName>
    <id>2800</id>
    <str>v2_45 00_0</str>
    <data />
  </netOpenName>
</DDSImageData>"""

_WORKS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<CharaWorksData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>charaWorks000000</dataName>
  <releaseTagName>
    <id>4</id>
    <str>v1 1.20.00</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>2800</id>
    <str>v2_45 00_0</str>
    <data />
  </netOpenName>
  <name>
    <id>0</id>
    <str />
    <data />
  </name>
  <sortName />
  <priority>0</priority>
  <ranks />
</CharaWorksData>"""

DEFAULT_DATA_CONF = """#-----------------------------------------------------------
# data.conf
#-----------------------------------------------------------

[Version]
Name = CHUNITHM
VerMajor   = 2
VerMinor   = 45
VerRelease = 0
"""

SORT_FILES = ("WorksSort.xml", "WorksNameSort.xml")


def crlf(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\n", "\r\n")


def image_str(image_id: int) -> str:
    return f"chara{image_id // 10:04d}_{image_id % 10:02d}"


def dds_names(image_id: int) -> dict:
    b, v = divmod(image_id, 10)
    return {k: f"CHU_UI_Character_{b:04d}_{v:02d}_{k}.dds" for k in cc.TARGETS}


# ---------------------------------------------------------------- scanning

@dataclass
class FormInfo:
    index: int
    name: str
    rank: int
    image_id: int


@dataclass
class CharaSlot:
    chara_id: int
    name: str
    sort_name: str
    works_id: int
    works: str
    illustrator: str
    image_id: int
    image_str: str
    forms: list            # FormInfo for transformations (index >= 1)
    chara_dir: str
    source: str
    dds_dir: str | None = None
    custom: bool = False   # lives in my option folder
    replaces: bool = False  # my folder overrides a character that exists elsewhere
    release_tag: int | None = None  # version label id (releaseTagName)

    @property
    def transforms(self) -> int:
        return len(self.forms)


@dataclass
class GameScan:
    root: str
    my_option: str
    sources: list = field(default_factory=list)          # [(label, path)]
    slots: dict = field(default_factory=dict)            # chara_id -> CharaSlot (highest priority)
    other_ids: set = field(default_factory=set)          # chara ids defined outside my folder
    dds_dirs: dict = field(default_factory=dict)         # image_id -> dir (highest priority)
    other_dds: dict = field(default_factory=dict)        # image_id -> dir, ignoring my folder
    works: dict = field(default_factory=dict)            # works_id -> name
    my_works: set = field(default_factory=set)           # groups defined in my folder
    data_conf: str | None = None
    chara_template: str | None = None
    dds_template: str | None = None
    works_template: str | None = None
    release_tags: dict = field(default_factory=dict)     # tag id -> (version str, title)
    my_tags: set = field(default_factory=set)            # tags defined in my folder
    tag_template: str | None = None
    tag_defs: dict = field(default_factory=dict)         # tag id -> [folder labels that define it]
    group_defs: dict = field(default_factory=dict)       # works id -> [folder labels that define it]
    originals: dict = field(default_factory=dict)        # chara_id -> CharaSlot as defined outside my folder

    def official_original(self, chara_id: int):
        """The game's own version of this character if it comes from an OFFICIAL option (A000, A001…), else None."""
        o = self.originals.get(chara_id)
        return o if o is not None and is_official_option(o.source) else None

    def tag_source(self, tag_id: int) -> str:
        defs = self.tag_defs.get(tag_id, [])
        return defs[-1] if defs else "?"

    def tag_conflict(self, tag_id: int) -> list:
        """Folders that define the same label ID (more than one = conflict)."""
        defs = self.tag_defs.get(tag_id, [])
        return defs if len(defs) > 1 else []

    @property
    def newest_tag(self) -> int | None:
        official = [i for i in self.release_tags if i < CUSTOM_TAG_MIN]
        return max(official) if official else (max(self.release_tags) if self.release_tags else None)

    def tag_ref(self, tag_id: int) -> tuple:
        return tag_id, self.release_tags.get(tag_id, ("", ""))[0]

    @property
    def my_dir(self) -> str:
        return os.path.join(option_dir(self.root), self.my_option)


def is_official_option(label: str) -> bool:
    """Official option folders are 'A' + three digits (A000, A001, A123…). Custom ones use letters (AXXX, AMYC…)."""
    return bool(re.fullmatch(r"A\d{3}", (label or "").upper()))


def find_game_root(path: str) -> str | None:
    p = os.path.abspath(path)
    for _ in range(4):
        if os.path.isdir(os.path.join(p, "data", "A000")) or (
                os.path.isdir(os.path.join(p, "data")) and os.path.isdir(os.path.join(p, "bin", "option"))):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return None


def option_dir(root: str) -> str:
    return os.path.join(root, "bin", "option")


def list_sources(root: str) -> list:
    out = []
    a000 = os.path.join(root, "data", "A000")
    if os.path.isdir(a000):
        out.append(("A000", a000))
    od = option_dir(root)
    if os.path.isdir(od):
        for n in sorted(os.listdir(od), key=str.upper):
            full = os.path.join(od, n)
            if os.path.isdir(full) and n.upper().startswith("A") and len(n) == 4:
                out.append((n, full))
    return out


_KINDS = (("chara", "characters"), ("charaWorks", "groups"), ("ddsImage", "character pictures"),
          ("music", "songs"), ("cueFile", "sounds"), ("systemVoice", "system voices"), ("releaseTag", "version labels"),
          ("mapIcon", "map icons"), ("avatarAccessory", "avatar items"), ("namePlate", "nameplates"),
          ("trophy", "trophies"), ("map", "maps"), ("event", "events"))


def folder_summary(path: str) -> tuple:
    """(short description of what an option folder changes, has its own group list?)"""
    parts = []
    names = {n.lower(): n for n in os.listdir(path)} if os.path.isdir(path) else {}
    for key, word in _KINDS:
        n = names.get(key.lower())
        if not n or not os.path.isdir(os.path.join(path, n)):
            continue
        if key == "chara":
            c = sum(1 for x in os.listdir(os.path.join(path, n)) if re.fullmatch(r"chara\d+", x))
            if c:
                parts.append(f"{c} character{'s' if c != 1 else ''}")
        elif key != "ddsImage":
            parts.append(word)
    known = {k.lower() for k, _ in _KINDS} | {"data.conf"}
    if any(k not in known for k in names):
        parts.append("other game data")
    has_sort = any(os.path.isfile(os.path.join(path, "charaWorks", f)) for f in SORT_FILES)
    return (", ".join(parts) or "nothing yet"), has_sort


def load_order(root: str, name: str) -> dict:
    """Where an option folder called `name` would load: the game loads option folders A->Z and the LATER one
    wins when two change the same thing. {'before': [labels], 'after': [(label, summary, has_group_list)]}"""
    name = name.upper()
    before, after = [], []
    for label, src in list_sources(root):
        if label.upper() == name or label.upper() == "A000":
            continue
        if label.upper() < name:
            before.append(label)
        else:
            summary, has_sort = folder_summary(src)
            after.append((label, summary, has_sort))
    return {"before": before, "after": after}


def parse_chara(text: str) -> dict:
    cid, name = cc.idstr(cc.block(text, "name"))
    wid, works = cc.idstr(cc.block(text, "works"))
    _, illus = cc.idstr(cc.block(text, "illustratorName"))
    iid, istr = cc.idstr(cc.block(text, "defaultImages"))
    forms = []
    for n in range(1, 10):
        b = cc.block(text, f"addImages{n}")
        if not b or "<changeImg>true</changeImg>" not in b:
            continue
        _, fname = cc.idstr(cc.block(b, "charaName"))
        fid, _ = cc.idstr(cc.block(b, "image"))
        m = re.search(r"<rank>(\d+)</rank>", b)
        if fid is not None and fid >= 0:
            forms.append(FormInfo(n, fname, int(m.group(1)) if m else 1, fid))
    rt, _ = cc.idstr(cc.block(text, "releaseTagName"))
    return dict(release_tag=rt, chara_id=cid, name=name, sort_name=cc.simple(text, "sortName"), works_id=wid, works=works,
                illustrator=illus, image_id=iid, image_str=istr, forms=forms)


def scan_game(root: str, my_option: str = "AXXX", progress=None) -> GameScan:
    my_option = my_option.upper()
    scan = GameScan(root=root, my_option=my_option, sources=list_sources(root))
    for i, (label, src) in enumerate(scan.sources):
        mine = label.upper() == my_option
        if progress:
            progress(f"Reading {label} ({i + 1}/{len(scan.sources)})…")
        dc = os.path.join(src, "data.conf")
        if os.path.isfile(dc) and not mine:
            scan.data_conf = dc
        wd = os.path.join(src, "charaWorks")
        if os.path.isdir(wd):
            for n in os.listdir(wd):
                x = os.path.join(wd, n, "CharaWorks.xml")
                if os.path.isfile(x):
                    try:
                        t = cc.read_text(x)
                    except OSError:
                        continue
                    wid, wname = cc.idstr(cc.block(t, "name"))
                    if wid is not None:
                        scan.works[wid] = wname
                        scan.group_defs.setdefault(wid, []).append(label)
                        if mine:
                            scan.my_works.add(wid)
                        if label == "A000" and wid == 9000:
                            scan.works_template = t
        rd = os.path.join(src, "releaseTag")
        if os.path.isdir(rd):
            for n in os.listdir(rd):
                x = os.path.join(rd, n, "ReleaseTag.xml")
                if os.path.isfile(x):
                    try:
                        t = cc.read_text(x)
                    except OSError:
                        continue
                    rid, rstr = cc.idstr(cc.block(t, "name"))
                    if rid is not None:
                        scan.release_tags[rid] = (rstr, cc.simple(t, "titleName"))
                        scan.tag_defs.setdefault(rid, []).append(label)
                        if mine:
                            scan.my_tags.add(rid)
                        if scan.tag_template is None:
                            scan.tag_template = t
        dd = os.path.join(src, "ddsImage")
        if os.path.isdir(dd):
            for n in os.listdir(dd):
                m = re.fullmatch(r"ddsImage(\d+)", n)
                if m:
                    p = os.path.join(dd, n)
                    scan.dds_dirs[int(m.group(1))] = p
                    if not mine:
                        scan.other_dds[int(m.group(1))] = p
                    if scan.dds_template is None and label == "A000":
                        x = os.path.join(p, "DDSImage.xml")
                        if os.path.isfile(x):
                            scan.dds_template = cc.read_text(x)
        cd = os.path.join(src, "chara")
        if os.path.isdir(cd):
            for n in os.listdir(cd):
                if not re.fullmatch(r"chara\d+", n):
                    continue
                x = os.path.join(cd, n, "Chara.xml")
                if not os.path.isfile(x):
                    continue
                try:
                    t = cc.read_text(x)
                except OSError:
                    continue
                info = parse_chara(t)
                if info["chara_id"] is None or info["image_id"] is None:
                    continue
                if label == "A000" and not info["forms"] and "<conditions />" in t and (
                        scan.chara_template is None or info["chara_id"] == 1320):
                    scan.chara_template = t
                slot = CharaSlot(
                    chara_id=info["chara_id"], name=info["name"], sort_name=info["sort_name"],
                    works_id=info["works_id"] or 0, works=info["works"], illustrator=info["illustrator"],
                    image_id=info["image_id"], image_str=info["image_str"], forms=info["forms"],
                    chara_dir=os.path.join(cd, n), source=label, custom=mine, release_tag=info["release_tag"],
                    replaces=mine and info["chara_id"] in scan.other_ids)
                if not mine:
                    scan.other_ids.add(info["chara_id"])
                    scan.originals[info["chara_id"]] = slot
                scan.slots[info["chara_id"]] = slot   # later folders win, like in the game
    for s in scan.slots.values():
        s.dds_dir = scan.dds_dirs.get(s.image_id)
        if s.custom:
            s.replaces = s.chara_id in scan.other_ids
    if scan.data_conf is None:
        a = os.path.join(root, "data", "A000", "data.conf")
        scan.data_conf = a if os.path.isfile(a) else None
    return scan


def dds_paths(dds_dir: str, image_id: int) -> dict:
    """{'00': path, ...} using the folder's DDSImage.xml file names (falls back to standard names)."""
    names = {}
    x = os.path.join(dds_dir, "DDSImage.xml")
    if os.path.isfile(x):
        t = cc.read_text(x)
        for k in range(3):
            b = cc.block(t, f"ddsFile{k}")
            m = re.search(r"<path>(.*?)</path>", b or "", re.S)
            if m and m.group(1).strip():
                names[f"0{k}"] = m.group(1).strip()
    for k, v in dds_names(image_id).items():
        names.setdefault(k, v)
    return {k: os.path.join(dds_dir, v) for k, v in names.items()}


def load_dds_image(scan: GameScan, image_id: int, which: str = "01") -> Image.Image | None:
    d = scan.dds_dirs.get(image_id)
    if not d:
        return None
    try:
        im = Image.open(dds_paths(d, image_id)[which])
        im.load()
        return im.convert("RGBA")
    except Exception:
        return None


def next_free_id(scan: GameScan, start: int = 70000) -> int:
    used_img = set(scan.dds_dirs)
    cid = max(10, start - start % 10)
    while cid < 99990:
        if cid not in scan.slots and not any((cid + k) in used_img for k in range(MAX_FORMS)):
            return cid
        cid += 10
    raise ValueError("No free character IDs left below 99990")


def id_problem(scan: GameScan, chara_id: int, editing: int | None = None) -> str | None:
    if chara_id % 10:
        return "Character IDs must end in 0 (the last digit is the transformation number)."
    if not 10 <= chara_id <= 99980:
        return "Use an ID between 10 and 99980."
    if chara_id == editing:
        return None
    if chara_id in scan.slots:
        s = scan.slots[chara_id]
        return f"ID {chara_id} is already used by '{s.name}' ({s.source})."
    for k in range(MAX_FORMS):
        if chara_id + k in scan.dds_dirs:
            return f"Image ID {chara_id + k} is already used in {os.path.basename(os.path.dirname(os.path.dirname(scan.dds_dirs[chara_id + k])))}."
    return None


def validate_option_name(name: str) -> str | None:
    if not re.fullmatch(r"A[A-Z0-9]{3}", name.upper()):
        return "Option folder must be 4 characters: A + 3 letters/numbers (like AXXX)."
    if name.upper() == "A000":
        return "A000 is the base game data, pick another name (like AXXX)."
    return None


# ---------------------------------------------------------------- writing

@dataclass
class FormSpec:
    index: int              # 0 = base look, 1..9 = transformation
    images: dict            # {'00','01','02'} -> PIL image at the exact size
    name: str = ""          # transformation name (shown in game), ignored for index 0
    rank: int = 1           # character rank that unlocks it, ignored for index 0


def _ensure_option(scan: GameScan, log) -> str:
    opt = scan.my_dir
    for sub in ("chara", "ddsImage"):
        os.makedirs(os.path.join(opt, sub), exist_ok=True)
    conf = os.path.join(opt, "data.conf")
    if not os.path.isfile(conf):
        if scan.data_conf and os.path.isfile(scan.data_conf):
            shutil.copyfile(scan.data_conf, conf)
        else:
            with open(conf, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(DEFAULT_DATA_CONF)
        log(f"data.conf -> {conf}")
    return opt


def _write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def write_character(scan: GameScan, *, mode: str, chara_id: int, name: str, sort_name: str,
                    works_id: int, works_name: str, illustrator: str, forms: list,
                    keep_original_forms: bool = False, fmt: str = "bc3", release_tag: int | None = None,
                    log=lambda m: None) -> dict:
    """mode: 'new' (fresh ID) | 'replace' (override an existing character) | 'edit' (one already in my folder).
    forms: list[FormSpec], must contain index 0; indexes must be 0..n-1 without gaps."""
    err = validate_option_name(scan.my_option)
    if err:
        raise ValueError(err)
    idx = sorted(f.index for f in forms)
    if not idx or idx != list(range(len(idx))):
        raise ValueError("Forms must be numbered 0..n without gaps (0 = base look).")
    if len(idx) > MAX_FORMS:
        raise ValueError("A character can have at most 9 transformations.")
    for f in forms:
        for k, n in cc.TARGETS.items():
            if f.images[k].size != (n, n):
                raise ValueError(f"Form {f.index} image _{k} must be {n}x{n}")

    slot = scan.slots.get(chara_id)
    if mode == "new":
        p = id_problem(scan, chara_id)
        if p:
            raise ValueError(p)
        base_img = chara_id
        text = scan.chara_template or _CHARA_TEMPLATE
        template_like = None
    else:
        if not slot:
            raise ValueError(f"Character {chara_id} not found")
        base_img = slot.image_id
        if base_img % 10 and len(forms) > 1:
            raise ValueError("This slot's image ID doesn't end in 0, so it can't have transformations.")
        src_xml = os.path.join(slot.chara_dir, "Chara.xml")
        text = cc.read_text(src_xml)
        template_like = src_xml

    opt = _ensure_option(scan, log)

    # ---- Chara.xml
    text = cc.set_simple(text, "dataName", f"chara{chara_id:06d}")
    text = cc.set_idstr(text, "name", chara_id, name)
    text = cc.set_simple(text, "sortName", sort_name)
    text = cc.set_idstr(text, "works", works_id, works_name)
    text = cc.set_idstr(text, "illustratorName", 50, illustrator)
    text = cc.set_simple(text, "defaultHave", "true")
    text = cc.set_simple(text, "disableFlag", "false")
    base_str = slot.image_str if (mode != "new" and slot and slot.image_str) else image_str(base_img)
    text = cc.set_idstr(text, "defaultImages", base_img, base_str)
    if release_tag is not None:
        text = cc.set_idstr(text, "releaseTagName", *scan.tag_ref(release_tag))
    by_index = {f.index: f for f in forms}
    keep = keep_original_forms and mode == "replace" and len(forms) == 1
    for n in range(1, 10):
        f = by_index.get(n)
        if keep:
            continue

        def put(b, f=f):
            if f is None:
                b = re.sub(r"<changeImg>\w+</changeImg>", "<changeImg>false</changeImg>", b)
                b = cc.set_idstr(b, "charaName", -1, "Invalid")
                b = cc.set_idstr(b, "image", -1, "Invalid")
                return re.sub(r"<rank>\d+</rank>", "<rank>1</rank>", b)
            iid = base_img + n
            b = re.sub(r"<changeImg>\w+</changeImg>", "<changeImg>true</changeImg>", b)
            b = cc.set_idstr(b, "charaName", iid, f.name or f"{name} {n}")
            b = cc.set_idstr(b, "image", iid, image_str(iid))
            return re.sub(r"<rank>\d+</rank>", f"<rank>{max(1, int(f.rank))}</rank>", b)
        text = cc.edit_block(text, f"addImages{n}", put)

    dst_chara = os.path.join(opt, "chara", f"chara{chara_id:06d}")
    os.makedirs(dst_chara, exist_ok=True)
    if template_like:
        cc._write_text_like(os.path.join(dst_chara, "Chara.xml"), text, template_like)
    else:
        _write(os.path.join(dst_chara, "Chara.xml"), crlf(text))
    log(f"Chara.xml -> {dst_chara}")

    # ---- images
    written = {}
    for f in forms:
        iid = base_img + f.index
        dst = os.path.join(opt, "ddsImage", f"ddsImage{iid:06d}")
        existing = scan.dds_dirs.get(iid)
        if not os.path.isdir(dst):
            if existing and os.path.isfile(os.path.join(existing, "DDSImage.xml")) and mode != "new":
                shutil.copytree(existing, dst)
            else:
                os.makedirs(dst, exist_ok=True)
        xml = os.path.join(dst, "DDSImage.xml")
        if not os.path.isfile(xml):
            t = scan.dds_template or _DDS_TEMPLATE
            t = cc.set_simple(t, "dataName", f"ddsImage{iid:06d}")
            t = cc.set_idstr(t, "name", iid, image_str(iid))
            for k, fname in enumerate(dds_names(iid).values()):
                t = cc.edit_block(t, f"ddsFile{k}", lambda b, fname=fname: re.sub(
                    r"<path>.*?</path>|<path\s*/>", f"<path>{fname}</path>", b, count=1, flags=re.S))
            _write(xml, crlf(t))
        paths = dds_paths(dst, iid)
        for k in cc.TARGETS:
            cc.save_dds(f.images[k], paths[k], fmt)
        written[iid] = dst
        scan.dds_dirs[iid] = dst
        log(f"images -> {dst}")

    # ---- remove leftover forms of this character from my folder
    if not keep:
        for n in range(len(forms), MAX_FORMS):
            stale = os.path.join(opt, "ddsImage", f"ddsImage{base_img + n:06d}")
            if base_img % 10 == 0 and os.path.isdir(stale):
                shutil.rmtree(stale)
                scan.dds_dirs.pop(base_img + n, None)
                if base_img + n in scan.other_dds:
                    scan.dds_dirs[base_img + n] = scan.other_dds[base_img + n]
                log(f"removed old form folder {stale}")

    if works_id in scan.my_works:
        if release_tag is not None:
            set_group_release_tag(scan, works_id, release_tag)
        write_sort_files(scan, opt)
    else:
        sync_sort_lists(scan)   # a folder that loads later must still list this character's group

    # ---- update the in-memory scan
    scan.slots[chara_id] = CharaSlot(
        chara_id=chara_id, name=name, sort_name=sort_name, works_id=works_id, works=works_name,
        illustrator=illustrator, image_id=base_img, image_str=image_str(base_img),
        forms=[FormInfo(f.index, f.name, f.rank, base_img + f.index) for f in sorted(forms, key=lambda f: f.index)
               if f.index > 0],
        chara_dir=dst_chara, source=scan.my_option, dds_dir=written.get(base_img), custom=True,
        replaces=chara_id in scan.other_ids, release_tag=release_tag)
    return {"option": opt, "chara": dst_chara, "images": written}


def delete_character(scan: GameScan, chara_id: int) -> list:
    """Remove a character (and its form images) from my folder. Replaced originals come back."""
    slot = scan.slots.get(chara_id)
    if not slot or not slot.custom:
        return []
    opt = scan.my_dir
    removed = []
    p = os.path.join(opt, "chara", f"chara{chara_id:06d}")
    if os.path.isdir(p):
        shutil.rmtree(p)
        removed.append(p)
    base = slot.image_id - slot.image_id % 10
    for k in range(MAX_FORMS):
        d = os.path.join(opt, "ddsImage", f"ddsImage{base + k:06d}")
        if os.path.isdir(d):
            shutil.rmtree(d)
            removed.append(d)
    return removed


# ---------------------------------------------------------------- groups (charaWorks)

def _sort_ids(path: str) -> list:
    try:
        t = cc.read_text(path)
    except OSError:
        return []
    lst = cc.block(t, "SortList") or ""
    return [int(x) for x in re.findall(r"<id>(-?\d+)</id>", lst)]


def sort_union(scan: GameScan, fname: str, exclude: str | None = None) -> list:
    """Sort order from A000 first, then every other folder's extra groups (in load order)."""
    order, seen = [], set()
    for label, src in scan.sources:
        if exclude and os.path.abspath(src) == os.path.abspath(exclude):
            continue
        for i in _sort_ids(os.path.join(src, "charaWorks", fname)):
            if i not in seen:
                seen.add(i)
                order.append(i)
    return order


def sort_xml(ids: list) -> str:
    items = "".join(f"    <StringID>\r\n      <id>{i}</id>\r\n      <str />\r\n      <data />\r\n    </StringID>\r\n"
                    for i in ids)
    return ('<?xml version="1.0" encoding="utf-8"?>\r\n'
            '<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\r\n'
            "  <dataName>charaWorks</dataName>\r\n  <SortList>\r\n" + items + "  </SortList>\r\n</SerializeSortData>")


def folder_works_ids(folder: str) -> list:
    out = []
    wd = os.path.join(folder, "charaWorks")
    if os.path.isdir(wd):
        for n in sorted(os.listdir(wd)):
            x = os.path.join(wd, n, "CharaWorks.xml")
            if os.path.isfile(x):
                wid, _ = cc.idstr(cc.block(cc.read_text(x), "name"))
                if wid is not None:
                    out.append(wid)
    return out


def all_group_ids(scan: GameScan, fname: str, extra_folder: str | None = None) -> list:
    """Every group the game will load, in sort order: the sort lists' order first, then any group that's
    defined in a folder but missing from every list (in load order)."""
    ids = sort_union(scan, fname)
    for label, src in scan.sources:
        for i in folder_works_ids(src):
            if i not in ids:
                ids.append(i)
    if extra_folder:
        ids += [i for i in folder_works_ids(extra_folder) if i not in ids]
    return ids


def write_sort_files(scan: GameScan, folder: str):
    """Write WorksSort.xml + WorksNameSort.xml = every group the game knows + this folder's groups.
    (A folder's sort list replaces the game's, so an incomplete one hides other groups.)"""
    for fname in SORT_FILES:
        _write(os.path.join(folder, "charaWorks", fname), sort_xml(all_group_ids(scan, fname, folder)))
    sync_sort_lists(scan)


def sync_sort_lists(scan: GameScan) -> list:
    """The game only uses the sort list of the LAST option folder (A→Z) that has one, and hides every group that
    isn't on it. So a custom folder that loads after yours (e.g. AZZZ after AMYC) would hide your groups.
    Add any missing groups to the end of every custom option folder's sort lists. Official folders (A000,
    A001…) load before custom ones, so they're left alone. Returns the folders that were updated."""
    changed = []
    for label, src in scan.sources:
        if is_official_option(label):
            continue
        for fname in SORT_FILES:
            p = os.path.join(src, "charaWorks", fname)
            if not os.path.isfile(p):
                continue
            have = _sort_ids(p)
            want = all_group_ids(scan, fname)
            missing = [i for i in want if i not in have]
            if missing:
                cc._write_text_like(p, sort_xml(have + missing), p)
                if label not in changed:
                    changed.append(label)
    return changed


def create_group(scan: GameScan, works_id: int, name: str, release_tag: int | None = None) -> str:
    if works_id in scan.works and works_id not in scan.my_works:
        raise ValueError(f"Group ID {works_id} is already '{scan.works[works_id]}'.")
    if not 1 <= works_id <= 999999:
        raise ValueError("Group ID must be between 1 and 999999.")
    _ensure_option(scan, lambda m: None)
    t = scan.works_template or _WORKS_TEMPLATE
    t = cc.set_simple(t, "dataName", f"charaWorks{works_id:06d}")
    t = cc.set_idstr(t, "name", works_id, name)
    t = cc.set_simple(t, "sortName", name)
    tag = release_tag if release_tag is not None else scan.newest_tag
    if tag is not None:
        t = cc.set_idstr(t, "releaseTagName", *scan.tag_ref(tag))
    d = os.path.join(scan.my_dir, "charaWorks", f"charaWorks{works_id:06d}")
    _write(os.path.join(d, "CharaWorks.xml"), crlf(t))
    scan.works[works_id] = name
    scan.my_works.add(works_id)
    if scan.my_option not in scan.group_defs.setdefault(works_id, []):
        scan.group_defs[works_id].append(scan.my_option)
    write_sort_files(scan, scan.my_dir)
    return d


def apply_group_and_tag(scan: GameScan, works_id: int, works_name: str, tag: int | None,
                        skip: int | None = None) -> list:
    """Give EVERY character in my folder this group and version label (the folder's characters belong
    together). Only Chara.xml is touched; pictures stay as they are. Returns the names that changed."""
    changed = []
    for sl in sorted(scan.slots.values(), key=lambda s: s.chara_id):
        if not sl.custom or sl.chara_id == skip or scan.official_original(sl.chara_id):
            continue   # replacements of official characters keep the game's own group + label
        x = os.path.join(sl.chara_dir, "Chara.xml")
        if not os.path.isfile(x) or not os.path.abspath(x).startswith(os.path.abspath(scan.my_dir)):
            continue
        t = cc.read_text(x)
        new = cc.set_idstr(t, "works", works_id, works_name)
        if tag is not None:
            new = cc.set_idstr(new, "releaseTagName", *scan.tag_ref(tag))
        if new != t:
            cc._write_text_like(x, new, x)
            changed.append(sl.name)
        sl.works_id, sl.works = works_id, works_name
        if tag is not None:
            sl.release_tag = tag
    if works_id in scan.my_works:
        if tag is not None:
            set_group_release_tag(scan, works_id, tag)
        write_sort_files(scan, scan.my_dir)
    return changed


def set_group_release_tag(scan: GameScan, works_id: int, tag: int):
    """Change the version label of one of MY groups (shown above the group name in game)."""
    x = os.path.join(scan.my_dir, "charaWorks", f"charaWorks{works_id:06d}", "CharaWorks.xml")
    if os.path.isfile(x):
        t = cc.read_text(x)
        new = cc.set_idstr(t, "releaseTagName", *scan.tag_ref(tag))
        if new != t:
            _write(x, new)


# ---------------------------------------------------------------- version labels (releaseTag)

_TAG_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<ReleaseTagData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>releaseTag000000</dataName>
  <name>
    <id>0</id>
    <str />
    <data />
  </name>
  <titleName />
</ReleaseTagData>"""


# Official labels are numbered 0, 1, 2 … one per game version (X-VERSE-X is 20). IDs below
# CUSTOM_TAG_MIN are left free for future official versions so a game update never collides.
CUSTOM_TAG_MIN = 90


def next_free_tag(scan: GameScan, start: int = CUSTOM_TAG_MIN) -> int:
    """Recommended label ID: first ID >= 90 that no folder (game, option folders, yours) uses."""
    t = max(start, CUSTOM_TAG_MIN)
    while t in scan.release_tags or t in scan.tag_defs:
        t += 1
    return t


def tag_id_problem(scan: GameScan, tag_id: int) -> str | None:
    if not CUSTOM_TAG_MIN <= tag_id <= 9999:
        return (f"Use a label ID from {CUSTOM_TAG_MIN} to 9999. Lower IDs belong to official CHUNITHM "
                f"versions (they're up to {scan.newest_tag} now and a game update adds the next one).")
    defs = scan.tag_defs.get(tag_id, [])
    if defs:
        return (f"Label ID {tag_id} is already used by '{scan.release_tags.get(tag_id, ('', '?'))[1]}' "
                f"in {', '.join(defs)}.")
    return None


def create_release_tag(scan: GameScan, tag_id: int, title: str) -> str:
    """Add a custom version label to my folder, the same way A001 adds X-VERSE-X."""
    p = tag_id_problem(scan, tag_id)
    if p:
        raise ValueError(p)
    if not title.strip():
        raise ValueError("Give the label a title.")
    # version string in the game's format, based on the newest official one: "v2 2.45.00" -> "v2 2.45.<id>"
    base = scan.release_tags.get(scan.newest_tag, ("v2 2.45.00", ""))[0] if scan.newest_tag is not None else "v2 2.45.00"
    m = re.match(r"(v\d+ \d+\.\d+)\.\d+", base)
    vstr = f"{m.group(1) if m else 'v2 2.45'}.{tag_id:02d}"
    _ensure_option(scan, lambda m: None)
    t = scan.tag_template or _TAG_TEMPLATE
    t = cc.set_simple(t, "dataName", f"releaseTag{tag_id:06d}")
    t = cc.set_idstr(t, "name", tag_id, vstr)
    t = cc.set_simple(t, "titleName", title.strip())
    d = os.path.join(scan.my_dir, "releaseTag", f"releaseTag{tag_id:06d}")
    _write(os.path.join(d, "ReleaseTag.xml"), crlf(t))
    scan.release_tags[tag_id] = (vstr, title.strip())
    scan.my_tags.add(tag_id)
    scan.tag_defs.setdefault(tag_id, []).append(scan.my_option)
    return d


def rename_my_tag(scan: GameScan, tag_id: int, title: str) -> str:
    """Change the text of one of MY version labels. Characters/groups point at the ID, so nothing else changes."""
    if tag_id not in scan.my_tags:
        raise ValueError(f"Label {tag_id} isn't defined in your folder {scan.my_option}, so it can't be renamed here.")
    title = title.strip()
    if not title:
        raise ValueError("Give the label some text.")
    x = os.path.join(scan.my_dir, "releaseTag", f"releaseTag{tag_id:06d}", "ReleaseTag.xml")
    if not os.path.isfile(x):
        raise FileNotFoundError(x)
    t = cc.read_text(x)
    if re.search(r"<titleName>.*?</titleName>|<titleName\s*/>", t, re.S):
        t = cc.set_simple(t, "titleName", title)
    else:
        t = t.replace("</ReleaseTagData>", f"  <titleName>{cc._x(title)}</titleName>\r\n</ReleaseTagData>")
    _write(x, t)
    if scan.tag_source(tag_id) == scan.my_option:  # only shown in game if my folder is the one that wins
        old = scan.release_tags.get(tag_id, ("", ""))
        scan.release_tags[tag_id] = (old[0], title)
    return x


def my_tag_title(scan: GameScan, tag_id: int) -> str:
    x = os.path.join(scan.my_dir, "releaseTag", f"releaseTag{tag_id:06d}", "ReleaseTag.xml")
    return cc.simple(cc.read_text(x), "titleName") if os.path.isfile(x) else ""


def existing_option_folders(root: str) -> list:
    od = option_dir(root)
    return sorted(n for n in os.listdir(od) if os.path.isdir(os.path.join(od, n))) if os.path.isdir(od) else []


def option_name_problem(root: str, name: str, current: str | None = None) -> str | None:
    """None if `name` can be used for a NEW option folder (or is the current one)."""
    err = validate_option_name(name)
    if err:
        return err
    if current and name.upper() == current.upper():
        return None
    if name.upper() in (n.upper() for n in existing_option_folders(root)):
        return f"{name.upper()} already exists in bin\\option."
    return None


def rename_option_folder(scan: GameScan, new: str, app_dir: str | None = None) -> list:
    """Rename my option folder on disk (and its project copies). IDs inside don't change."""
    new = new.upper()
    p = option_name_problem(scan.root, new, None)
    if p:
        raise ValueError(p)
    done = []
    if os.path.isdir(scan.my_dir):
        os.rename(scan.my_dir, os.path.join(option_dir(scan.root), new))
        done.append(f"bin\\option\\{scan.my_option} -> {new}")
    if app_dir:
        old_p = os.path.join(app_dir, "my_characters", scan.my_option)
        if os.path.isdir(old_p):
            os.rename(old_p, os.path.join(app_dir, "my_characters", new))
            done.append(f"my_characters\\{scan.my_option} -> {new}")
    return done


def renumber_my_tag(scan: GameScan, old: int, new: int) -> list:
    """Move one of MY version labels to a new ID and update every character/group in my folder that uses it."""
    if old not in scan.my_tags:
        raise ValueError(f"Label {old} isn't defined in your folder {scan.my_option}.")
    p = tag_id_problem(scan, new)
    if p:
        raise ValueError(p)
    changed = []
    src = os.path.join(scan.my_dir, "releaseTag", f"releaseTag{old:06d}")
    t = cc.read_text(os.path.join(src, "ReleaseTag.xml"))
    title = cc.simple(t, "titleName")
    vstr = re.sub(r"\.\d+$", f".{new:02d}", cc.idstr(cc.block(t, "name"))[1] or "v2 2.45.00")
    t = cc.set_simple(t, "dataName", f"releaseTag{new:06d}")
    t = cc.set_idstr(t, "name", new, vstr)
    dst = os.path.join(scan.my_dir, "releaseTag", f"releaseTag{new:06d}")
    _write(os.path.join(dst, "ReleaseTag.xml"), t)
    shutil.rmtree(src)
    changed.append(f"releaseTag{old:06d} -> releaseTag{new:06d}")
    for sub, fname in (("chara", "Chara.xml"), ("charaWorks", "CharaWorks.xml")):
        d = os.path.join(scan.my_dir, sub)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            x = os.path.join(d, n, fname)
            if not os.path.isfile(x):
                continue
            tx = cc.read_text(x)
            if cc.idstr(cc.block(tx, "releaseTagName"))[0] == old:
                _write(x, cc.set_idstr(tx, "releaseTagName", new, vstr))
                changed.append(f"{n} now uses label {new}")
    # update scan
    scan.my_tags.discard(old)
    scan.my_tags.add(new)
    defs = [f for f in scan.tag_defs.get(old, []) if f != scan.my_option]
    if defs:
        scan.tag_defs[old] = defs
    else:
        scan.tag_defs.pop(old, None)
        scan.release_tags.pop(old, None)
    scan.tag_defs.setdefault(new, []).append(scan.my_option)
    scan.release_tags[new] = (vstr, title)
    for sl in scan.slots.values():
        if sl.custom and sl.release_tag == old:
            sl.release_tag = new
    return changed


def next_free_group(scan: GameScan, start: int = 7000) -> int:
    g = start
    while g in scan.works:
        g += 1
    return g


# ---------------------------------------------------------------- checker

def check_folder(scan: GameScan, folder: str) -> list:
    """Return [(level, message)] with level in 'ERROR', 'WARN', 'OK', 'INFO'."""
    out = []
    folder = os.path.abspath(folder)
    name = os.path.basename(folder)
    inside = os.path.abspath(os.path.dirname(folder)) == os.path.abspath(option_dir(scan.root))
    if not re.fullmatch(r"A[A-Za-z0-9]{3}", name):
        out.append(("WARN", f"Folder name '{name}' must be 4 characters starting with A to be loaded "
                            f"(e.g. A{name[:3].upper() if len(name) >= 3 else 'X00'})."))
    if not os.path.isfile(os.path.join(folder, "data.conf")):
        out.append(("INFO", "No data.conf (most option folders have one; Chuni Chara Maker adds it automatically)."))

    known_tags = {i for i in scan.release_tags if os.path.abspath(scan.my_dir) != folder or i not in scan.my_tags}
    rd = os.path.join(folder, "releaseTag")
    local_titles = {}
    if os.path.isdir(rd):
        for n in os.listdir(rd):
            x = os.path.join(rd, n, "ReleaseTag.xml")
            if os.path.isfile(x):
                t = cc.read_text(x)
                rid, _ = cc.idstr(cc.block(t, "name"))
                if rid is not None:
                    known_tags.add(rid)
                    local_titles[rid] = cc.simple(t, "titleName")

    def tag_title(i):
        return local_titles.get(i) or scan.release_tags.get(i, ("", f"#{i}"))[1]

    others_chara = {}
    others_img = {}
    for label, src in scan.sources:
        if os.path.abspath(src) == folder:
            continue
        cd = os.path.join(src, "chara")
        if os.path.isdir(cd):
            for n in os.listdir(cd):
                m = re.fullmatch(r"chara(\d+)", n)
                if m:
                    others_chara.setdefault(int(m.group(1)), label)
        dd = os.path.join(src, "ddsImage")
        if os.path.isdir(dd):
            for n in os.listdir(dd):
                m = re.fullmatch(r"ddsImage(\d+)", n)
                if m:
                    others_img.setdefault(int(m.group(1)), label)

    local_img = {}
    dd = os.path.join(folder, "ddsImage")
    if os.path.isdir(dd):
        for n in sorted(os.listdir(dd)):
            m = re.fullmatch(r"ddsImage(\d+)", n)
            if not m:
                continue
            iid = int(m.group(1))
            local_img[iid] = os.path.join(dd, n)
            d = local_img[iid]
            xml = os.path.join(d, "DDSImage.xml")
            if not os.path.isfile(xml):
                out.append(("ERROR", f"{n}: DDSImage.xml is missing."))
                continue
            paths = dds_paths(d, iid)
            for k, p in paths.items():
                if not os.path.isfile(p):
                    present = [f for f in os.listdir(d) if f.lower().endswith(f"_{k}.dds")]
                    hint = f" (folder has {present[0]})" if present else ""
                    out.append(("ERROR", f"{n}: DDSImage.xml wants {os.path.basename(p)} but it's missing{hint}."))
                    continue
                info = cc.dds_info(p)
                want = cc.TARGETS[k]
                if not info or not info["ok"]:
                    out.append(("ERROR", f"{n}: {os.path.basename(p)} is damaged or not a DDS."))
                elif (info["w"], info["h"]) != (want, want):
                    out.append(("ERROR", f"{n}: {os.path.basename(p)} is {info['w']}x{info['h']}, "
                                         f"should be {want}x{want}."))
            if iid in others_img:
                out.append(("INFO", f"{n} overrides the image from {others_img[iid]}."))

    cd = os.path.join(folder, "chara")
    n_chara = 0
    used_works = set()
    if os.path.isdir(cd):
        for n in sorted(os.listdir(cd)):
            x = os.path.join(cd, n, "Chara.xml")
            if not re.fullmatch(r"chara\d+", n):
                continue
            if not os.path.isfile(x):
                out.append(("ERROR", f"{n}: Chara.xml is missing."))
                continue
            n_chara += 1
            t = cc.read_text(x)
            info = parse_chara(t)
            cid = info["chara_id"]
            label = f"{n} '{info['name']}'"
            if cid is None or f"chara{cid:06d}" != n:
                out.append(("ERROR", f"{label}: <name><id> is {cid}, folder name says {n[5:]}."))
            dn = cc.simple(t, "dataName")
            if dn and dn != n:
                out.append(("WARN", f"{label}: <dataName> is {dn}, should be {n}."))
            used_works.add(info["works_id"])
            if scan.release_tags and info["release_tag"] is not None and info["release_tag"] not in known_tags:
                out.append(("ERROR", f"{label}: version label (releaseTagName) {info['release_tag']} doesn't exist."))
            if info["works_id"] not in scan.works and info["works_id"] not in folder_works_ids(folder):
                out.append(("ERROR", f"{label}: group ID {info['works_id']} doesn't exist."))
            for iid, what in [(info["image_id"], "base image")] + [(f.image_id, f"form '{f.name}'")
                                                                    for f in info["forms"]]:
                if iid is None:
                    continue
                if iid not in local_img and iid not in others_img:
                    out.append(("ERROR", f"{label}: {what} uses ddsImage{iid:06d}, which doesn't exist."))
            if cid is not None and cid in others_chara:
                out.append(("INFO", f"{label} replaces a character from {others_chara[cid]}."))
            if "<defaultHave>true</defaultHave>" not in t:
                out.append(("INFO", f"{label}: defaultHave is false, so it must be unlocked in game."))

    # IDs this folder defines that other folders also define (the folder loaded last wins)
    for tid, ttl in sorted(local_titles.items()):
        others = [f for f in scan.tag_defs.get(tid, []) if f not in (name, name.upper())]
        if others:
            out.append(("WARN", f"Version label ID {tid} '{ttl}' is also defined in {', '.join(others)} "
                                f"('{scan.release_tags.get(tid, ('', '?'))[1]}'). Only one can win - "
                                f"give yours a free ID like {next_free_tag(scan)}."))
        elif tid < CUSTOM_TAG_MIN:
            out.append(("WARN", f"Version label ID {tid} '{ttl}' is in the range official versions use "
                                f"(next one will be {(scan.newest_tag or 20) + 1}). A game update may overwrite it; "
                                f"IDs {CUSTOM_TAG_MIN}+ are safe."))
        else:
            out.append(("INFO", f"Defines version label ID {tid} '{ttl}'."))
    for gid in folder_works_ids(folder):
        others = [f for f in scan.group_defs.get(gid, []) if f not in (name, name.upper())]
        if others:
            out.append(("WARN", f"Group ID {gid} is also defined in {', '.join(others)} - one will hide the other."))

    # groups' version labels
    wd = os.path.join(folder, "charaWorks")
    if os.path.isdir(wd):
        for n in sorted(os.listdir(wd)):
            x = os.path.join(wd, n, "CharaWorks.xml")
            if os.path.isfile(x):
                t = cc.read_text(x)
                rt, _ = cc.idstr(cc.block(t, "releaseTagName"))
                _, gname = cc.idstr(cc.block(t, "name"))
                if rt is not None and scan.release_tags and rt not in known_tags:
                    out.append(("ERROR", f"{n} '{gname}': version label {rt} doesn't exist."))
                elif rt is not None:
                    out.append(("INFO", f"Group '{gname}' shows the label '{tag_title(rt)}' above its name in game."))

    # group sort lists
    groups = folder_works_ids(folder)
    for fname in SORT_FILES:
        p = os.path.join(folder, "charaWorks", fname)
        if os.path.isfile(p):
            have = set(_sort_ids(p))
            game = sort_union(scan, fname, exclude=folder)
            missing = [i for i in game if i not in have]
            if missing:
                out.append(("WARN", f"{fname} is missing {len(missing)} groups your game has "
                                    f"(e.g. {', '.join(map(str, missing[:6]))}). It replaces the game's list, "
                                    "so those groups can disappear. Use 'Fix' to merge."))
            lost = [g for g in groups if g not in have]
            if lost:
                out.append(("WARN", f"{fname} doesn't list this folder's group(s) {lost}."))
        elif groups:
            out.append(("WARN", f"Folder adds group(s) {groups} but has no {fname}. Use 'Fix' to create it."))

    # characters (same ID) that a folder loading later overrides: the game shows theirs, not this folder's
    if inside and os.path.isdir(cd := os.path.join(folder, "chara")):
        over = {}
        for n in os.listdir(cd):
            m = re.fullmatch(r"chara(\d+)", n)
            s = scan.slots.get(int(m.group(1))) if m else None
            if s and s.source.upper() > name.upper() and os.path.abspath(os.path.dirname(s.chara_dir)) != \
                    os.path.abspath(cd):
                over.setdefault(s.source, []).append(int(m.group(1)))
        for label, ids in sorted(over.items()):
            out.append(("WARN", f"{label} loads after {name} and has character(s) with the same ID "
                                f"{sorted(ids)[:8]}{'…' if len(ids) > 8 else ''}: the game shows {label}'s version."))

    # groups this folder's characters use must also be on the sort list the game ends up using: the one of the
    # last folder (A->Z) that has a sort list. A folder loading later with an older list hides them.
    used = set(groups)
    cd = os.path.join(folder, "chara")
    if os.path.isdir(cd):
        for n in os.listdir(cd):
            x = os.path.join(cd, n, "Chara.xml")
            if os.path.isfile(x):
                wid, _ = cc.idstr(cc.block(cc.read_text(x), "works"))
                if wid is not None:
                    used.add(wid)
    if inside and used:
        for label, src in scan.sources:
            if os.path.abspath(src) == folder or label.upper() <= name.upper():
                continue
            for fname in SORT_FILES[:1]:
                p = os.path.join(src, "charaWorks", fname)
                if os.path.isfile(p):
                    hidden = sorted(g for g in used if g not in set(_sort_ids(p)))
                    if hidden:
                        out.append(("ERROR", f"{label} loads after {name} and its group list doesn't include "
                                             f"group(s) {hidden}, so the game hides them (and their characters). "
                                             "Use 'Fix' to add them."))

    errors = sum(1 for lvl, _ in out if lvl == "ERROR")
    warns = sum(1 for lvl, _ in out if lvl == "WARN")
    def pl(n, word):
        return f"{n} {word}" + ("" if n == 1 else "s")
    summary = (f"{pl(n_chara, 'character')}, {pl(len(local_img), 'image set')}, {pl(len(groups), 'group')}"
               + ("" if inside else " · not inside your game's bin\\option yet"))
    out.insert(0, ("OK" if not errors and not warns else "INFO",
                   summary + (" · no problems found" if not errors and not warns else
                              f" · {errors} error(s), {warns} warning(s)")))
    return out


def fix_folder(scan: GameScan, folder: str) -> list:
    """Safe automatic fixes: rename misnamed DDS files to what DDSImage.xml expects,
    merge the group sort lists, add data.conf. Returns a list of what changed."""
    done = []
    folder = os.path.abspath(folder)
    dd = os.path.join(folder, "ddsImage")
    if os.path.isdir(dd):
        for n in sorted(os.listdir(dd)):
            m = re.fullmatch(r"ddsImage(\d+)", n)
            d = os.path.join(dd, n)
            if not m or not os.path.isfile(os.path.join(d, "DDSImage.xml")):
                continue
            for k, p in dds_paths(d, int(m.group(1))).items():
                if os.path.isfile(p):
                    continue
                cands = [f for f in os.listdir(d) if f.lower().endswith(f"_{k}.dds")
                         and f not in [os.path.basename(q) for q in dds_paths(d, int(m.group(1))).values()]]
                if len(cands) == 1:
                    os.rename(os.path.join(d, cands[0]), p)
                    done.append(f"{n}: renamed {cands[0]} -> {os.path.basename(p)}")
    synced = sync_sort_lists(scan)
    if synced:
        done.append(f"Added missing groups to the group lists in {', '.join(synced)} (folders that load later "
                    "would otherwise hide them)")
    groups = folder_works_ids(folder)
    needs_sort = bool(groups) or any(os.path.isfile(os.path.join(folder, "charaWorks", f)) for f in SORT_FILES)
    if needs_sort:
        write_sort_files(scan, folder)
        done.append("Rebuilt WorksSort.xml + WorksNameSort.xml with all of your game's groups"
                    + (f" + {groups}" if groups else ""))
    if not os.path.isfile(os.path.join(folder, "data.conf")) and scan.data_conf:
        shutil.copyfile(scan.data_conf, os.path.join(folder, "data.conf"))
        done.append("Added data.conf")
    return done


# ---------------------------------------------------------------- projects (re-editable sources)

def project_dir(app_dir: str, option: str, chara_id: int) -> str:
    return os.path.join(app_dir, "my_characters", option.upper(), str(chara_id))


def save_project(folder: str, data: dict, sources: dict, outputs: dict):
    """sources: {form_index: PIL source image (after cut-out)}; outputs: {form_index: {'00':..}}"""
    os.makedirs(folder, exist_ok=True)

    def put_png(im, name):  # write to a temp name, then swap in, so a crash never leaves half a file
        tmp = os.path.join(folder, name + ".tmp")
        im.save(tmp, format="PNG")
        os.replace(tmp, os.path.join(folder, name))
    for i, im in sources.items():
        put_png(im, f"form{i}_source.png")
    for i, ims in outputs.items():
        for k, im in ims.items():
            put_png(im, f"form{i}_{k}.png")
    tmp = os.path.join(folder, "project.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(folder, "project.json"))


def load_project(folder: str) -> tuple[dict, dict] | None:
    p = os.path.join(folder, "project.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None  # damaged project: the caller rebuilds from the game files
    sources = {}
    for fi in data.get("forms", []):
        sp = os.path.join(folder, f"form{fi['index']}_source.png")
        if os.path.isfile(sp):
            try:
                sources[fi["index"]] = cc.load_source(sp)
            except Exception:
                pass  # damaged picture: this look is rebuilt from the game files
    return data, sources
