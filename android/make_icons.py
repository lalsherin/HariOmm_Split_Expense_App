#!/usr/bin/env python3
"""Cut the launcher icons out of the Split Buddy brand artwork.

Source: ../brand/split-buddy-logo.png — the supplied 1024x1024 logo, the mark
above a wordmark on a dark tile.

Two things have to happen to turn that into an app icon, and neither is
optional:

1. **The wordmark comes off.** A launcher icon is 48dp — about 9mm. "SplitBuddy
   by Hexanxt" at that size is a grey smudge, and Google Play rejects icons
   whose text is illegible. Only the mark survives.

2. **The mark is cut out of its background rather than cropped with it.** An
   adaptive icon is the foreground layer alone, masked to whatever shape the
   launcher wants — circle, squircle, teardrop — over a separate background.
   A foreground that carried its own dark square would show as a dark square
   inside the mask, with the real background never visible.

   The cut is a proper matte, not a threshold. The artwork is a bright mark
   composited on a flat dark tile, so for each pixel:

       pixel = bg*(1-a) + colour*a

   Alpha comes from how far the pixel has travelled from the background, and
   the colour is then un-mixed back out of it. Thresholding instead would
   leave a dark fringe everywhere the mark is anti-aliased against the tile —
   visible as a dirty outline at icon sizes, which is exactly where it would
   be least forgivable.

Outputs, at all five densities:
    ic_launcher.png      legacy: the mark on a rounded brand tile
    ic_launcher_fg.png   adaptive foreground: the mark alone, transparent
and one 512x512 PNG for the Play Store listing.

Run it from this directory:  python3 make_icons.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "brand", "split-buddy-logo.png")
RES = os.path.join(HERE, "res")
PLAY = os.path.join(HERE, "..", "playstore", "listing")

# Density buckets. Legacy icons are 48dp, adaptive layers 108dp.
DENS = [("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)]

# Of the 108dp adaptive canvas, only the middle 66dp is guaranteed to survive
# every launcher's mask. Anything outside it may be shaved off.
#
# The mark is a tall diagonal sliver, so fitting it by bounding box wastes
# room — its corners are empty. FG_FILL is set from the furthest *ink*, not
# the furthest pixel of the box, and then backed off ~6% so a circular mask
# never shaves the tip. Measured, not guessed: see the check at the end.
SAFE = 66 / 108
FG_FILL = SAFE * 0.75
# The legacy icon has no mask to worry about, so the mark can be bigger.
LEGACY_FILL = 0.68
CORNER = 0.22            # rounded-tile radius, as a fraction of the size


def load_mark():
    """The mark, cut free of its tile, as a tight RGBA image. Also the tile
    colour, which becomes the icon background so the brand reads the same."""
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    bg = im.getpixel((4, 4))

    px = im.load()

    def dist(p):
        return abs(p[0] - bg[0]) + abs(p[1] - bg[1]) + abs(p[2] - bg[2])

    # The wordmark sits under a clear horizontal gap. Find the gap, keep what
    # is above it, and never assume a fixed crop — the artwork may change.
    ink = [any(dist(px[x, y]) > 90 for x in range(0, w, 3)) for y in range(h)]
    first = ink.index(True)
    gap = None
    y = first
    while y < h:
        if not ink[y]:
            run = y
            while run < h and not ink[run]:
                run += 1
            if run - y > 12:            # a real gap, not a gap inside a glyph
                gap = y
                break
            y = run
        else:
            y += 1
    if gap is None:
        raise SystemExit("could not find the gap between the mark and the text")

    # Widest excursion from the background, used to normalise alpha.
    top = im.crop((0, 0, w, gap))
    peak = max(dist(p) for p in top.getdata())

    out = Image.new("RGBA", top.size, (0, 0, 0, 0))
    op = out.load()
    tp = top.load()
    for yy in range(top.size[1]):
        for xx in range(top.size[0]):
            p = tp[xx, yy]
            a = dist(p) / (peak * 0.40)          # fully opaque well before the peak
            if a <= 0.004:
                continue
            a = min(1.0, a)
            # un-mix: recover the mark's own colour from the composite
            c = tuple(min(255, max(0, int(round(bg[i] + (p[i] - bg[i]) / a))))
                      for i in range(3))
            op[xx, yy] = c + (int(round(a * 255)),)

    return out.crop(out.getbbox()), bg


def fit(mark, canvas, fill):
    """The mark centred on a transparent square, occupying `fill` of it."""
    w, h = mark.size
    target = canvas * fill
    scale = min(target / w, target / h)
    m = mark.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                    Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(m, ((canvas - m.size[0]) // 2, (canvas - m.size[1]) // 2), m)
    return out


def rounded_tile(size, colour, radius):
    """A rounded square of `colour`, anti-aliased by drawing big and shrinking."""
    from PIL import ImageDraw
    ss = 4
    big = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        [0, 0, size * ss - 1, size * ss - 1], radius=radius * size * ss,
        fill=colour + (255,))
    return big.resize((size, size), Image.LANCZOS)


def main():
    mark, bg = load_mark()
    print("mark cut from the artwork: %dx%d, tile colour #%02X%02X%02X"
          % (mark.size[0], mark.size[1], *bg))

    for name, scale in DENS:
        legacy = round(48 * scale)
        tile = rounded_tile(legacy, bg, CORNER)
        tile.alpha_composite(fit(mark, legacy, LEGACY_FILL))
        d = os.path.join(RES, "mipmap-" + name)
        os.makedirs(d, exist_ok=True)
        tile.save(os.path.join(d, "ic_launcher.png"))

        fg_size = round(108 * scale)
        fit(mark, fg_size, FG_FILL).save(os.path.join(d, "ic_launcher_fg.png"))
        print("mipmap-%-8s legacy %3dpx   foreground %3dpx" % (name, legacy, fg_size))

    os.makedirs(PLAY, exist_ok=True)
    store = Image.new("RGB", (512, 512), bg)
    m = fit(mark, 512, 0.62)
    store.paste(m, (0, 0), m)
    store.save(os.path.join(PLAY, "icon-512.png"))
    print("playstore/listing/icon-512.png   512px, no transparency, as Play requires")

    check_safe_zone()
    print("\nic_launcher_bg in res/values/colors.xml should be "
          "#FF%02X%02X%02X to match the tile." % bg)


def check_safe_zone():
    """Fail loudly if the mark could be clipped by a circular mask.

    Worth doing every run: it is the one mistake here that nobody notices
    until the icon is on a home screen with its tip sliced off, and by then
    it is in an APK somebody has installed.
    """
    import math
    fg = Image.open(os.path.join(RES, "mipmap-xxxhdpi", "ic_launcher_fg.png"))
    s = fg.size[0]
    c = s / 2
    safe = s * SAFE / 2
    px = fg.load()
    worst = 0.0
    for y in range(s):
        for x in range(s):
            if px[x, y][3] > 8:
                worst = max(worst, math.hypot(x - c, y - c))
    pct = worst / safe * 100
    print("furthest ink sits at %.0f%% of the safe radius" % pct)
    if worst > safe:
        raise SystemExit("the mark would be clipped by a circular mask — "
                         "lower FG_FILL")


if __name__ == "__main__":
    main()
