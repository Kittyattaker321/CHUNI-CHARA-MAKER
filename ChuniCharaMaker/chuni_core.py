# Chuni Chara Maker
# Copyright (C) 2026 Chuni Chara Maker contributors
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# LICENSE file for details.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Image + DDS + XML-text helpers for Chuni Chara Maker (no game-folder logic here; see chuni_mod.py).
"""
from __future__ import annotations

import html as _html
import os
import re
import shutil
import struct
from dataclasses import dataclass, field
from html import escape as _html_escape

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# --------------------------------------------------------------------------------------
# Image targets
# --------------------------------------------------------------------------------------

TARGETS = {
    "00": 1080,  # login, transform select, skill trigger, results
    "01": 512,   # character select, in-play preview
    "02": 128,   # nameplate
}
TARGET_INFO = {
    "00": "1080×1080 · login / skill / results",
    "01": "512×512 · character select / in play",
    "02": "128×128 · nameplate",
}


# --------------------------------------------------------------------------------------
# Source image prep
# --------------------------------------------------------------------------------------

def load_source(path: str) -> Image.Image:
    im = Image.open(path)
    im.load()
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


def has_transparency(im: Image.Image) -> bool:
    a = np.asarray(im.getchannel("A"))
    return bool((a < 250).mean() > 0.01)


def remove_flat_background(im: Image.Image, tolerance: int = 40, soften: bool = True) -> Image.Image:
    """Remove a flat/near-flat background touching the image edges (flood fill from the border)."""
    arr = np.asarray(im.convert("RGBA")).astype(np.int32)
    h, w = arr.shape[:2]
    rgb = arr[..., :3]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    # most common border colour (quantised) = background
    q = (border // 8)
    keys, counts = np.unique(q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2], return_counts=True)
    k = keys[np.argmax(counts)]
    sel = (q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]) == k
    bg = border[sel].mean(0)
    dist = np.sqrt(((rgb - bg) ** 2).sum(-1))
    close = (dist <= tolerance).astype(np.uint8) * 255
    mask = Image.fromarray(close, "L")
    # pad by 1px so a single flood from the corner reaches every border region
    padded = Image.new("L", (w + 2, h + 2), 255)
    padded.paste(mask, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    bgmask = np.asarray(padded)[1:-1, 1:-1] == 128
    alpha = arr[..., 3].astype(np.float32)
    alpha[bgmask] = 0
    if soften:
        # anti-alias the cut: partial alpha on the edge based on colour distance
        edge = np.asarray(Image.fromarray((bgmask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
        edge &= ~bgmask
        # pixels within 2px of the removed area: estimate how much background is mixed in
        near = np.asarray(Image.fromarray((bgmask * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
        near &= ~bgmask
        t = np.clip((dist - tolerance * 0.5) / max(tolerance * 2.5, 1), 0, 1)
        t = np.where(edge, np.minimum(t, 0.85), t)
        a_est = np.where(near, 255 * t, 255.0)
        alpha = np.minimum(alpha, a_est)
        # remove the background colour from the semi-transparent edge ("colour decontamination")
        af = np.clip(alpha / 255.0, 1e-3, 1)[..., None]
        clean = (rgb - (1 - af) * bg) / af
        rgb = np.where(near[..., None], np.clip(clean, 0, 255), rgb)
    out = arr.copy()
    out[..., :3] = rgb
    out[..., 3] = alpha.astype(np.int32)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def remove_background_ai(im: Image.Image) -> Image.Image:
    from rembg import remove  # optional dependency
    return remove(im).convert("RGBA")


def rembg_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("rembg") is not None
    except Exception:
        return False


def content_bbox(im: Image.Image, thresh: int = 16):
    a = np.asarray(im.getchannel("A"))
    ys, xs = np.nonzero(a > thresh)
    if len(xs) == 0:
        return (0, 0, im.width, im.height)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def auto_frames(im: Image.Image) -> dict:
    """Default square crop boxes (x, y, size) in source pixels, modelled on the game's own art."""
    x0, y0, x1, y1 = content_bbox(im)
    w, h = x1 - x0, y1 - y0
    a = np.asarray(im.getchannel("A")).astype(np.float32)

    def center_x(top, bottom):
        band = a[max(top, 0):max(bottom, top + 1), x0:x1]
        col = band.sum(0)
        if col.sum() <= 0:
            return (x0 + x1) / 2
        return x0 + float((col * np.arange(len(col))).sum() / col.sum())

    # _00: whole character, ~3% headroom, feet/bottom touching the bottom edge (game fades it out)
    s0 = max(h / 0.97, w / 0.92)
    cx = center_x(y0, y1)
    f00 = (cx - s0 / 2, y1 - s0 + s0 * 0.015, s0)
    if w / 0.92 > h / 0.97:  # wide image: centre vertically instead
        f00 = (cx - s0 / 2, (y0 + y1) / 2 - s0 / 2, s0)
    # _01: tighter, head to thighs (~top 72% of the character)
    s1 = max(h * 0.72, min(w, h) * 0.6)
    cx1 = center_x(y0, y0 + int(s1))
    f01 = (cx1 - s1 / 2, y0 - s1 * 0.01, s1)
    # _02: face / head close-up near the top of the character
    s2 = max(min(h * 0.22, w * 0.8), 16)
    cx2 = center_x(y0, y0 + int(s2 * 1.2))
    f02 = (cx2 - s2 / 2, y0 + s2 * 0.05, s2)
    return {"00": f00, "01": f01, "02": f02}


def render_frame(im: Image.Image, frame, size: int, fade_bottom: float = 0.0) -> Image.Image:
    """Crop the square frame (may extend past the image -> transparent) and resize to size×size."""
    x, y, s = frame
    s = max(s, 1.0)
    # Pillow's affine-free path: crop with integer box at 2x precision then resize
    box = (int(round(x)), int(round(y)), int(round(x + s)), int(round(y + s)))
    crop = im.crop(box)  # areas outside the image become transparent black
    out = crop.resize((size, size), Image.LANCZOS, reducing_gap=3.0) if crop.size != (size, size) else crop.copy()
    if fade_bottom > 0:
        arr = np.asarray(out).copy()
        n = max(int(size * fade_bottom), 1)
        t = np.linspace(1.0, 0.0, n, dtype=np.float32)
        t = t * t * (3 - 2 * t)  # smoothstep
        arr[size - n:, :, 3] = (arr[size - n:, :, 3].astype(np.float32) * t[:, None]).astype(np.uint8)
        out = Image.fromarray(arr, "RGBA")
    return out


# --------------------------------------------------------------------------------------
# BC3 / DXT5 encoder
# --------------------------------------------------------------------------------------

_CW = np.array([0.38, 0.5, 0.12], np.float32)  # perceptual channel weights (≈ luma)


def bleed_transparent(arr: np.ndarray, iterations: int = 8) -> np.ndarray:
    """Fill RGB of fully transparent pixels from neighbours so edges don't get dark fringes."""
    rgb = arr[..., :3].astype(np.float32)
    known = arr[..., 3] > 0
    if known.all() or not known.any():
        return arr
    filled = known.copy()
    acc = rgb * filled[..., None]
    for _ in range(iterations):
        if filled.all():
            break
        k = filled.astype(np.float32)
        pad_c = np.pad(acc, ((1, 1), (1, 1), (0, 0)))
        pad_k = np.pad(k, 1)
        sc = sum(pad_c[1 + dy:pad_c.shape[0] - 1 + dy, 1 + dx:pad_c.shape[1] - 1 + dx]
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        sk = sum(pad_k[1 + dy:pad_k.shape[0] - 1 + dy, 1 + dx:pad_k.shape[1] - 1 + dx]
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1))
        new = (~filled) & (sk > 0)
        acc[new] = sc[new] / sk[new][:, None]
        filled |= new
    mean = rgb[known].mean(0)
    acc[~filled] = mean
    out = arr.copy()
    out[..., :3] = np.where(known[..., None], arr[..., :3], np.clip(np.rint(acc), 0, 255).astype(np.uint8))
    return out


def _to565(c):
    r = np.clip(np.rint(c[..., 0] * 31 / 255), 0, 31).astype(np.int32)
    g = np.clip(np.rint(c[..., 1] * 63 / 255), 0, 63).astype(np.int32)
    b = np.clip(np.rint(c[..., 2] * 31 / 255), 0, 31).astype(np.int32)
    return (r << 11) | (g << 5) | b


def _from565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)


def _color_palette(c0, c1):
    e0, e1 = _from565(c0), _from565(c1)
    return np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], 1)  # (N,4,3)


def _assign(px, pal, w):
    d = (((px[:, :, None, :] - pal[:, None, :, :]) ** 2) * _CW).sum(-1)  # (N,16,4)
    idx = d.argmin(-1)
    err = (np.take_along_axis(d, idx[..., None], -1)[..., 0] * w).sum(-1)
    return idx, err


_FACT = np.array([1.0, 0.0, 2 / 3, 1 / 3], np.float32)  # weight of e0 for each index


def _encode_color(px, a):
    n = px.shape[0]
    w = 0.03 + a / 255.0
    wsum = w.sum(1, keepdims=True)
    mean = (px * w[..., None]).sum(1) / wsum
    sw = np.sqrt(_CW)
    d = (px - mean[:, None]) * sw
    cov = np.einsum("nki,nkj,nk->nij", d, d, w)
    axis = np.ones((n, 3), np.float32)
    for _ in range(8):
        axis = np.einsum("nij,nj->ni", cov, axis)
        axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-12
    axis = axis / sw
    axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-12
    t = ((px - mean[:, None]) * axis[:, None]).sum(-1)
    vis = a > 0
    big = np.where(vis.any(1, keepdims=True), vis, True)
    tmax = np.where(big, t, -1e9).max(1)
    tmin = np.where(big, t, 1e9).min(1)
    inset = (tmax - tmin) / 16
    e0 = mean + axis * (tmax - inset)[:, None]
    e1 = mean + axis * (tmin + inset)[:, None]
    c0, c1 = _to565(np.clip(e0, 0, 255)), _to565(np.clip(e1, 0, 255))
    idx, err = _assign(px, _color_palette(c0, c1), w)

    # least-squares refinement of endpoints
    for _ in range(2):
        f = _FACT[idx]                      # (N,16)
        g = 1 - f
        aa = (w * f * f).sum(1)
        bb = (w * f * g).sum(1)
        cc = (w * g * g).sum(1)
        det = aa * cc - bb * bb
        ok = np.abs(det) > 1e-6
        rx = (w[..., None] * f[..., None] * px).sum(1)
        ry = (w[..., None] * g[..., None] * px).sum(1)
        sdet = np.where(ok, det, 1)[:, None]
        ne0 = (cc[:, None] * rx - bb[:, None] * ry) / sdet
        ne1 = (aa[:, None] * ry - bb[:, None] * rx) / sdet
        nc0 = _to565(np.clip(ne0, 0, 255))
        nc1 = _to565(np.clip(ne1, 0, 255))
        nidx, nerr = _assign(px, _color_palette(nc0, nc1), w)
        better = ok & (nerr < err)
        c0 = np.where(better, nc0, c0)
        c1 = np.where(better, nc1, c1)
        idx = np.where(better[:, None], nidx, idx)
        err = np.where(better, nerr, err)

    # BC3 colour is always 4-colour mode, but keep c0 > c1 for maximum decoder compatibility
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    remap = np.array([1, 0, 3, 2])
    idx = np.where(swap[:, None], remap[idx], idx)
    eq = c0 == c1
    idx = np.where(eq[:, None], 0, idx)
    bits = (idx.astype(np.uint64) << (2 * np.arange(16, dtype=np.uint64))).sum(1)
    return c0.astype(np.uint16), c1.astype(np.uint16), bits.astype(np.uint32)


def _alpha_pal8(a0, a1):
    a0 = a0.astype(np.float32)[:, None]
    a1 = a1.astype(np.float32)[:, None]
    i = np.arange(1, 7, dtype=np.float32)[None]
    mids = ((7 - i) * a0 + i * a1) / 7
    return np.concatenate([a0, a1, mids], 1)


def _alpha_pal6(a0, a1):
    a0 = a0.astype(np.float32)[:, None]
    a1 = a1.astype(np.float32)[:, None]
    i = np.arange(1, 5, dtype=np.float32)[None]
    mids = ((5 - i) * a0 + i * a1) / 5
    n = a0.shape[0]
    return np.concatenate([a0, a1, mids, np.zeros((n, 1), np.float32), np.full((n, 1), 255, np.float32)], 1)


def _encode_alpha(a):
    af = a.astype(np.float32)
    amax = a.max(1).astype(np.int32)
    amin = a.min(1).astype(np.int32)
    # mode 8: a0 > a1
    a0 = amax
    a1 = amin
    pal8 = _alpha_pal8(a0, a1)
    d8 = np.abs(af[:, :, None] - pal8[:, None, :])
    i8 = d8.argmin(-1)
    e8 = (np.take_along_axis(d8, i8[..., None], -1)[..., 0] ** 2).sum(1)
    # mode 6: a0 <= a1, with explicit 0 and 255
    inner = (a > 0) & (a < 255)
    lo = np.where(inner, a, 255).min(1).astype(np.int32)
    hi = np.where(inner, a, 0).max(1).astype(np.int32)
    none = ~inner.any(1)
    lo = np.where(none, 0, lo)
    hi = np.where(none, 255, hi)
    pal6 = _alpha_pal6(lo, hi)
    d6 = np.abs(af[:, :, None] - pal6[:, None, :])
    i6 = d6.argmin(-1)
    e6 = (np.take_along_axis(d6, i6[..., None], -1)[..., 0] ** 2).sum(1)
    use6 = (e6 < e8) | (a0 == a1)
    # when a0 == a1 in mode 8 the decoder would switch to mode 6 anyway; mode 6 handles it
    r0 = np.where(use6, lo, a0)
    r1 = np.where(use6, hi, a1)
    idx = np.where(use6[:, None], i6, i8)
    bits = (idx.astype(np.uint64) << (3 * np.arange(16, dtype=np.uint64))).sum(1)
    return r0.astype(np.uint8), r1.astype(np.uint8), bits


def encode_bc3(im: Image.Image) -> bytes:
    arr = np.asarray(im.convert("RGBA"))
    h, w = arr.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        arr = np.pad(arr, ((0, ph), (0, pw), (0, 0)), mode="edge")
    arr = bleed_transparent(arr)
    H, W = arr.shape[:2]
    blocks = arr.reshape(H // 4, 4, W // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    out = np.zeros((blocks.shape[0], 16), np.uint8)
    step = 8192
    for s in range(0, blocks.shape[0], step):
        b = blocks[s:s + step]
        px = b[..., :3].astype(np.float32)
        a = b[..., 3]
        a0, a1, abits = _encode_alpha(a)
        c0, c1, cbits = _encode_color(px, a.astype(np.float32))
        o = out[s:s + step]
        o[:, 0] = a0
        o[:, 1] = a1
        for k in range(6):
            o[:, 2 + k] = ((abits >> np.uint64(8 * k)) & np.uint64(255)).astype(np.uint8)
        o[:, 8] = c0 & 255
        o[:, 9] = c0 >> 8
        o[:, 10] = c1 & 255
        o[:, 11] = c1 >> 8
        for k in range(4):
            o[:, 12 + k] = (cbits >> (8 * k)) & 255
    return out.tobytes()


def dds_header_bc3(width: int, height: int) -> bytes:
    """Same header layout as the game's files (and Paint.NET): no mipmaps, linear size set."""
    linear = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    hdr = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, height, width, linear, 0, 0)
    hdr += b"\x00" * 44
    hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DXT5", 0, 0, 0, 0, 0)
    hdr += struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    assert len(hdr) == 128
    return hdr


def save_dds_bc3(im: Image.Image, path: str):
    data = dds_header_bc3(im.width, im.height) + encode_bc3(im)   # built in memory first; no temp file
    with open(path, "wb") as f:                                    # is ever made in the game folder
        f.write(data)


# --------------------------------------------------------------------------------------
# XML editing (text-level so the game's formatting/encoding is preserved exactly)
# --------------------------------------------------------------------------------------

def _x(s: str) -> str:
    return _html_escape(s, quote=False)


def _set_idstr_in(block: str, id_value=None, str_value=None) -> str:
    if id_value is not None:
        block = re.sub(r"<id>-?\d+</id>", f"<id>{int(id_value)}</id>", block, count=1)
    if str_value is not None:
        new = f"<str>{_x(str_value)}</str>" if str_value != "" else "<str />"
        block = re.sub(r"<str>.*?</str>|<str\s*/>", lambda m: new, block, count=1, flags=re.S)
    return block


def _edit_block(text: str, tag: str, fn) -> str:
    m = re.search(rf"(<{tag}>)(.*?)(</{tag}>)", text, re.S)
    if not m:
        return text
    return text[:m.start(2)] + fn(m.group(2)) + text[m.end(2):]


def _set_simple(text: str, tag: str, value: str) -> str:
    v = _x(value)
    pat = rf"<{tag}>.*?</{tag}>|<{tag}\s*/>"
    if re.search(pat, text, re.S):
        new = f"<{tag}>{v}</{tag}>" if value != "" else f"<{tag} />"
        return re.sub(pat, lambda m: new, text, count=1, flags=re.S)
    return text


def read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def block(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1) if m else None


def simple(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return _html.unescape(m.group(1)) if m else ""


def idstr(b: str | None):
    if b is None:
        return None, ""
    mid = re.search(r"<id>(-?\d+)</id>", b)
    ms = re.search(r"<str>(.*?)</str>", b, re.S)
    return (int(mid.group(1)) if mid else None), (_html.unescape(ms.group(1)) if ms else "")


def set_idstr(text: str, tag: str, id_value=None, str_value=None) -> str:
    return _edit_block(text, tag, lambda b: _set_idstr_in(b, id_value, str_value))


def set_simple(text: str, tag: str, value: str) -> str:
    return _set_simple(text, tag, value)


def edit_block(text: str, tag: str, fn) -> str:
    return _edit_block(text, tag, fn)


# --------------------------------------------------------------------------------------
# Uncompressed DDS + header inspection
# --------------------------------------------------------------------------------------

def save_dds_rgba(im: Image.Image, path: str):
    """32-bit uncompressed A8R8G8B8 (lossless, 4x the size of BC3) — also accepted by the game."""
    im = im.convert("RGBA")
    w, h = im.size
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000  # CAPS|HEIGHT|WIDTH|PITCH|PIXELFORMAT
    hdr = struct.pack("<4sIIIIIII", b"DDS ", 124, flags, h, w, w * 4, 0, 0) + b"\x00" * 44
    hdr += struct.pack("<II4sIIIII", 32, 0x41, b"\x00\x00\x00\x00", 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000)
    hdr += struct.pack("<IIIII", 0x1000, 0, 0, 0, 0)
    arr = bleed_transparent(np.asarray(im))
    bgra = arr[..., [2, 1, 0, 3]].tobytes()
    with open(path, "wb") as f:
        f.write(hdr + bgra)


def save_dds(im: Image.Image, path: str, fmt: str = "bc3"):
    if fmt == "rgba":
        save_dds_rgba(im, path)
    else:
        save_dds_bc3(im, path)


def dds_info(path: str) -> dict | None:
    """Return {'w','h','format','ok'} from a DDS header, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            d = f.read(128)
        size = os.path.getsize(path)
    except OSError:
        return None
    if len(d) < 128 or d[:4] != b"DDS ":
        return {"w": 0, "h": 0, "format": "not a DDS", "ok": False}
    h, w = struct.unpack("<II", d[12:20])
    pf_flags = struct.unpack("<I", d[80:84])[0]
    fourcc = d[84:88]
    bits = struct.unpack("<I", d[88:92])[0]
    if pf_flags & 0x4:
        fmt = fourcc.decode("ascii", "replace")
        need = ((w + 3) // 4) * ((h + 3) // 4) * (16 if fourcc in (b"DXT5", b"DXT3") else 8)
    else:
        fmt = f"RGBA{bits}"
        need = w * h * bits // 8
    return {"w": w, "h": h, "format": fmt, "ok": size >= 128 + need}


def _write_text_like(path: str, text: str, like: str):
    """Write text using the same BOM convention as the original file."""
    bom = False
    try:
        with open(like, "rb") as f:
            bom = f.read(3) == b"\xef\xbb\xbf"
    except OSError:
        pass
    data = text.encode("utf-8")
    with open(path, "wb") as f:
        if bom:
            f.write(b"\xef\xbb\xbf")
        f.write(data)


def default_sort_name(name: str) -> str:
    return name.upper().replace(" ", "")


# --------------------------------------------------------------------------------------
# Recover crop boxes from already-made images (when no project file exists)
# --------------------------------------------------------------------------------------

def _feat(im: Image.Image, size: int) -> np.ndarray:
    """Premultiplied grey + alpha channels, float32, at size x size."""
    a = np.asarray(im.convert("RGBA").resize((size, size), Image.BILINEAR)).astype(np.float32) / 255.0
    g = (a[..., 0] * 0.3 + a[..., 1] * 0.59 + a[..., 2] * 0.11) * a[..., 3]
    return np.stack([g, a[..., 3]], 0)


def locate_crop(big: Image.Image, small: Image.Image, low: int = 96, pad_frac: float = 0.5):
    """Find where `small` (a resized square crop) sits inside `big`. Returns (x, y, size) in big's
    pixels, or None. The crop may hang over the edges of `big` (that part is transparent)."""
    W = big.width
    P = int(low * pad_frac)
    B = _feat(big, low)
    B = np.pad(B, ((0, 0), (P, P), (P, P)))
    H = B.shape[1]
    N = 1 << int(np.ceil(np.log2(H * 2)))
    FB = np.fft.rfft2(B, s=(N, N))
    B2 = (B ** 2).sum(0)
    I = np.pad(B2.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    best = None
    for k in range(10, H + 1, 2):
        T = _feat(small, k)
        FT = np.fft.rfft2(T[:, ::-1, ::-1], s=(N, N))
        corr = np.fft.irfft2(FB * FT, s=(N, N)).sum(0)[k - 1:H, k - 1:H]
        win = I[k:, k:] - I[:-k, k:] - I[k:, :-k] + I[:-k, :-k]
        err = (win - 2 * corr + (T ** 2).sum()) / (k * k)
        if (T[1] > 0.05).mean() < 0.02:
            continue
        iy, ix = np.unravel_index(np.argmin(err), err.shape)
        e = float(err[iy, ix])
        if best is None or e < best[0]:
            best = (e, ix - P, iy - P, k)
    if best is None:
        return None
    _, x, y, k = best
    sc = W / low
    x, y, s = x * sc, y * sc, k * sc
    # refine at higher resolution around the coarse answer
    ref = 64
    tgt = _feat(small, ref)
    bigR = big.convert("RGBA")
    step = max(1.0, sc / 3)
    cand = (float("inf"), x, y, s)
    for ds in (-2, -1, 0, 1, 2):
        ss = s + ds * step
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                xx, yy = x + dx * step, y + dy * step
                crop = bigR.crop((int(round(xx)), int(round(yy)), int(round(xx + ss)), int(round(yy + ss))))
                e = float(((_feat(crop, ref) - tgt) ** 2).mean())
                if e < cand[0]:
                    cand = (e, xx, yy, ss)
    return cand[1], cand[2], cand[3]
