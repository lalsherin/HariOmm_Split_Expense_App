#!/usr/bin/env python3
"""Draw the Split Ledger launcher icon as PNGs. Pure stdlib (zlib + struct)."""
import os, zlib, struct

NAVY = (0x1B, 0x4F, 0xA0)
WHITE = (0xFF, 0xFF, 0xFF)
SS = 4  # supersampling factor


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)


def in_round_rect(x, y, x0, y0, x1, y1, r):
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size, full_bleed):
    """full_bleed: solid navy tile. Otherwise a transparent adaptive foreground."""
    S = size * SS
    if full_bleed:
        bg_box = (0.0, 0.0, float(S), float(S))
        bg_r = S * 0.22
        mark_scale = 0.62          # lines occupy 62% of the tile
    else:
        bg_box = None
        mark_scale = 0.42          # inside the adaptive-icon safe zone

    mw = S * mark_scale
    left = (S - mw) / 2.0
    # three ledger rules: full, full, two-thirds — same device as the app mark
    bar_h = mw * 0.135
    gap = mw * 0.145
    total_h = bar_h * 3 + gap * 2
    top = (S - total_h) / 2.0
    bars = []
    for i, frac in enumerate((1.0, 1.0, 0.6)):
        y0 = top + i * (bar_h + gap)
        bars.append((left, y0, left + mw * frac, y0 + bar_h, bar_h / 2.0))

    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            ra = ga = ba = aa = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = px * SS + sx + 0.5
                    y = py * SS + sy + 0.5
                    on_mark = any(in_round_rect(x, y, *b) for b in bars)
                    if on_mark:
                        r, g, b, a = WHITE + (255,)
                    elif bg_box and in_round_rect(x, y, bg_box[0], bg_box[1], bg_box[2], bg_box[3], bg_r):
                        r, g, b, a = NAVY + (255,)
                    else:
                        r = g = b = a = 0
                    ra += r * a; ga += g * a; ba += b * a; aa += a
            n = SS * SS
            if aa == 0:
                row += bytes((0, 0, 0, 0))
            else:
                row += bytes((ra // aa, ga // aa, ba // aa, aa // n))
        rows.append(row)
    return rows


BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "res")
DENS = [("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)]

for name, scale in DENS:
    legacy = int(round(48 * scale))
    write_png(os.path.join(BASE, "mipmap-" + name, "ic_launcher.png"), legacy, legacy, render(legacy, True))
    fg = int(round(108 * scale))
    write_png(os.path.join(BASE, "mipmap-" + name, "ic_launcher_fg.png"), fg, fg, render(fg, False))
    print("mipmap-%-8s legacy %3dpx  foreground %3dpx" % (name, legacy, fg))
