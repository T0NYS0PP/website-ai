#!/usr/bin/env python3
"""
TWO — kinetic typography film in the "snapgram" reference style.

Style notes (from the reference):
  * 4:3 frame, 24 fps, heavy film grain + soft vignette
  * off-white "paper" scenes with small semi-bold type revealed word by word,
    dashed guide lines, a blinking cursor, hand-drawn circles / underlines,
    2-3 frame pixel glitches on cuts
  * black scenes with small white type on the left and a thermal-camera
    (orange heat-map) silhouette on the right, which later "cools" into a
    grey shadow on white
  * scattered single letters drifting on white with red scribbled circles
  * a giant cropped word on a red card as the opener, and again as the outro

Footage slots: scenes 3, 4 and 6 show a silhouette. With --footage DIR the
silhouette is cut from real clips (DIR/clipA.mp4, clipB.mp4, clipC.mp4, any
length; luminance is keyed and pushed through the thermal colour map).
Without it a procedural garment silhouette is used, so the film still works
as a complete piece.

Usage:
  python3 render_two.py out.mp4 [--footage DIR] [--scale 1.0] [--start S --end S]
"""
import argparse
import math
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ----------------------------------------------------------------- settings
FPS = 24
W, H = 1440, 1080          # 4:3 like the reference (rendered larger)
DURATION = 21.8

FONT_DIR = "/usr/share/fonts/opentype/inter/"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONT_DIR, name), int(size))


F_BODY = font("Inter-SemiBold.otf", 40)
F_BODY_LIGHT = font("Inter-Medium.otf", 40)
F_LETTER = font("InterDisplay-Medium.otf", 116)
F_GIANT = font("InterDisplay-Black.otf", 600)
F_TINY = font("Inter-Medium.otf", 26)

OFFWHITE = (233, 231, 227)
BLACK = (13, 12, 12)
RED = (214, 38, 28)
INK = (24, 22, 22)
INK_LIGHT = (160, 158, 155)       # colour of the word that was just typed
CHALK = (236, 233, 228)           # white type on black
CHALK_LIGHT = (120, 118, 115)
SHADOW = (58, 56, 54)             # the cooled silhouette on white

rng_global = np.random.default_rng(7)

# ----------------------------------------------------------------- helpers


def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_out(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp01(t)
    return t * t * (3 - 2 * t)


def mix_col(a, b, t):
    t = clamp01(t)
    return tuple(int(round(lerp(a[i], b[i], t))) for i in range(3))


def blink(t, period=0.9, duty=0.55):
    return (t % period) < period * duty


# ------------------------------------------------------------ backgrounds


def _vignette(strength):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx = (xx - W * 0.5) / (W * 0.5)
    dy = (yy - H * 0.5) / (H * 0.5)
    r = np.sqrt(dx * dx + dy * dy)
    v = 1 - strength * np.clip((r - 0.45) / 0.9, 0, 1) ** 1.6
    return v[..., None]


VIG_WHITE = _vignette(0.26)
VIG_BLACK = _vignette(0.10)


def _paper():
    base = np.ones((H, W, 3), np.float32) * np.array(OFFWHITE, np.float32)
    # faint diagonal light fall-off like a photographed sheet of paper
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = 1 - 0.07 * (xx / W) - 0.05 * (yy / H)
    base *= g[..., None]
    base *= VIG_WHITE
    return base


BG_PAPER = _paper()
BG_BLACK = np.ones((H, W, 3), np.float32) * np.array(BLACK, np.float32) * VIG_BLACK + 2.0
BG_RED = np.ones((H, W, 3), np.float32) * np.array(RED, np.float32) * _vignette(0.18)


def bg_image(kind, mix=0.0):
    """kind: 'paper' | 'black' | 'red'.  mix>0 blends black->paper."""
    if kind == "paper":
        arr = BG_PAPER
    elif kind == "red":
        arr = BG_RED
    else:
        arr = BG_BLACK
    if mix > 0:
        arr = BG_BLACK * (1 - mix) + BG_PAPER * mix
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- drawing


def dashed_line(draw, y, color, x0=0, x1=W, dash=18, gap=12, width=2):
    x = x0
    while x < x1:
        draw.line([(x, y), (min(x + dash, x1), y)], fill=color, width=width)
        x += dash + gap


def word_layout(text, fnt, x, y, align="left"):
    words = text.split()
    widths = [fnt.getlength(w) for w in words]
    space = fnt.getlength(" ")
    total = sum(widths) + space * (len(words) - 1)
    if align == "center":
        x = x - total / 2
    boxes = []
    cx = x
    for w, ww in zip(words, widths):
        boxes.append((cx, cx + ww))
        cx += ww + space
    return words, boxes, (x, y)


def draw_words(draw, text, fnt, x, y, t, times, color, light, align="left",
               cursor=True, cursor_color=None, fade=0.0):
    """Reveal words one by one. `times` is the reveal time of each word.
    The newest word is drawn in the lighter colour for a few frames, the
    way the reference "types" its lines."""
    words, boxes, _ = word_layout(text, fnt, x, y, align)
    n_shown = 0
    for i, w in enumerate(words):
        if t < times[i]:
            break
        n_shown = i + 1
        age = t - times[i]
        col = light if age < 3.0 / FPS else color
        if fade > 0:
            col = mix_col(light, color, age / fade)
        draw.text((boxes[i][0], y), w, font=fnt, fill=col, anchor="ls")
    if cursor and n_shown > 0 and n_shown < len(words):
        if blink(t, 0.5, 0.6):
            cx = boxes[n_shown - 1][1] + fnt.getlength(" ") * 0.6
            asc = fnt.getbbox("H")[3] - fnt.getbbox("H")[1]
            draw.line([(cx, y - asc * 1.05), (cx, y + asc * 0.15)],
                      fill=cursor_color or color, width=2)
    return words, boxes, n_shown


_scribble_cache = {}


def scribble_points(kind, seed, n=90):
    """Points for a hand-drawn stroke in unit space, with organic jitter."""
    key = (kind, seed, n)
    if key in _scribble_cache:
        return _scribble_cache[key]
    r = random.Random(seed)
    ph = [r.random() * 6.3 for _ in range(6)]
    pts = []
    if kind == "ellipse":
        start = -0.9 + r.random() * 0.6
        span = 2 * math.pi * (1.08 + r.random() * 0.1)
        for i in range(n):
            a = start + span * i / (n - 1)
            j = 1 + 0.045 * math.sin(3 * a + ph[0]) + 0.03 * math.sin(7 * a + ph[1])
            # the pen drifts outward slightly on the second lap
            j += 0.05 * (i / n)
            pts.append((math.cos(a) * j, math.sin(a) * j))
    elif kind == "underline":
        for i in range(n):
            u = i / (n - 1)
            yj = 0.18 * math.sin(u * 9 + ph[2]) + 0.1 * math.sin(u * 23 + ph[3])
            pts.append((u, yj))
    elif kind == "arc":
        for i in range(n):
            a = -2.6 + 2.1 * i / (n - 1)
            j = 1 + 0.03 * math.sin(5 * a + ph[4])
            pts.append((math.cos(a) * j, math.sin(a) * j))
    _scribble_cache[key] = pts
    return pts


def draw_scribble(draw, kind, cx, cy, rx, ry, progress, color, width=3, seed=1):
    if progress <= 0:
        return
    pts = scribble_points(kind, seed)
    k = max(2, int(len(pts) * clamp01(progress)))
    poly = [(cx + px * rx, cy + py * ry) for px, py in pts[:k]]
    draw.line(poly, fill=color, width=width, joint="curve")


def pixel_glitch(img, box, factor=16, seed=0):
    """Reference-style 2-3 frame pixelation with displaced scan bands."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(W, x1), min(H, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    crop = img.crop((x0, y0, x1, y1))
    w, h = crop.size
    small = crop.resize((max(1, w // factor), max(1, h // factor)), Image.NEAREST)
    big = np.array(small.resize((w, h), Image.NEAREST))
    r = random.Random(seed)
    for _ in range(3):
        a = r.randrange(0, h)
        b = min(h, a + r.randrange(4, max(5, h // 4)))
        big[a:b] = np.roll(big[a:b], r.randrange(-40, 40), axis=1)
    img.paste(Image.fromarray(big), (x0, y0))


def specks(draw, t, seed, count, color, region=(0, 0, W, H)):
    """Tiny ink specks drifting slowly (the reference's dust / crumbs)."""
    r = random.Random(seed)
    x0, y0, x1, y1 = region
    for i in range(count):
        bx = r.uniform(x0, x1)
        by = r.uniform(y0, y1)
        ph = r.random() * 6.3
        s = r.uniform(1.5, 4.0)
        x = bx + 14 * math.sin(t * 0.6 + ph)
        y = by + 9 * math.cos(t * 0.45 + ph * 1.3)
        draw.ellipse([x - s, y - s * 0.6, x + s, y + s * 0.6], fill=color)


# --------------------------------------------------------- silhouette slot

MASK_SCALE = 4                      # silhouette computed at quarter res
MW, MH = W // MASK_SCALE, H // MASK_SCALE

_noise_fields = [rng_global.random((7, 9)).astype(np.float32) for _ in range(16)]


def heat_noise(t):
    """Slow-shimmering low-frequency field in [0,1] at mask resolution."""
    f = t * 0.9
    i = int(f) % len(_noise_fields)
    j = (i + 1) % len(_noise_fields)
    a = f - int(f)
    fld = _noise_fields[i] * (1 - a) + _noise_fields[j] * a
    im = Image.fromarray(fld, mode="F").resize((MW, MH), Image.BICUBIC)
    return np.array(im, np.float32)


# garment outline (a loose tee on a hanger line), unit box coordinates
_GARMENT = [
    (0.40, 0.00), (0.33, 0.03), (0.10, 0.11), (0.00, 0.36), (0.07, 0.42),
    (0.19, 0.38), (0.17, 0.60), (0.16, 0.98), (0.84, 0.98), (0.83, 0.60),
    (0.81, 0.38), (0.93, 0.42), (1.00, 0.36), (0.90, 0.11), (0.67, 0.03),
    (0.60, 0.00), (0.56, 0.06), (0.50, 0.09), (0.44, 0.06),
]


def procedural_mask(t, slot):
    """Soft silhouette mask (float 0..1) at mask resolution."""
    sway = math.radians(1.6) * math.sin(t * 0.8 + slot)
    breathe = 1 + 0.012 * math.sin(t * 1.3 + slot * 2)
    # garment box on the right side of frame
    bx0, by0 = 0.50 * MW, 0.08 * MH
    bw, bh = 0.52 * MW, 1.05 * MH
    pivot = (bx0 + bw / 2, by0)
    pts = []
    for ux, uy in _GARMENT:
        x = bx0 + ux * bw
        y = by0 + uy * bh
        x = pivot[0] + (x - pivot[0]) * breathe
        y = pivot[1] + (y - pivot[1]) * breathe
        dx, dy = x - pivot[0], y - pivot[1]
        xr = pivot[0] + dx * math.cos(sway) - dy * math.sin(sway)
        yr = pivot[1] + dx * math.sin(sway) + dy * math.cos(sway)
        pts.append((xr, yr))
    m = Image.new("L", (MW, MH), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    # fabric folds: subtle vertical ripples cut into the edge
    arr = np.array(m, np.float32) / 255.0
    return arr


class FootageSlot:
    """Frames of a real clip, keyed by luminance, at mask resolution."""

    invert = False   # set True when the subject is darker than the backdrop

    def __init__(self, path, tmpdir):
        self.dir = os.path.join(tmpdir, os.path.basename(path) + "_frames")
        os.makedirs(self.dir, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-i", path,
            "-vf", f"fps={FPS},scale={MW}:{MH}:force_original_aspect_ratio=increase,"
                   f"crop={MW}:{MH},format=gray",
            os.path.join(self.dir, "%05d.png")], check=True)
        self.n = len(os.listdir(self.dir))

    def mask(self, t_local):
        i = int(t_local * FPS) % max(1, self.n) + 1
        im = Image.open(os.path.join(self.dir, f"{i:05d}.png"))
        arr = np.array(im, np.float32) / 255.0
        if self.invert:
            arr = 1.0 - arr
        # key: brighter than the dark backdrop -> part of the subject
        lo, hi = 0.18, 0.45
        return np.clip((arr - lo) / (hi - lo), 0, 1)


_THERMAL_STOPS = [
    (0.00, (0, 0, 0)),
    (0.10, (28, 0, 10)),
    (0.22, (96, 6, 22)),
    (0.38, (184, 28, 20)),
    (0.55, (236, 92, 22)),
    (0.72, (250, 160, 36)),
    (0.86, (254, 214, 110)),
    (1.00, (255, 252, 236)),
]
_TS = np.array([s for s, _ in _THERMAL_STOPS], np.float32)
_TC = np.array([c for _, c in _THERMAL_STOPS], np.float32)


def thermal_colormap(v):
    out = np.empty(v.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(v, _TS, _TC[:, c])
    return out


def render_silhouette(bg_arr, mask_small, t, mode, intensity=1.0, cool=0.0):
    """Composite the silhouette over bg_arr (float HxWx3).
    mode 'thermal' = heat map on black; cool in [0,1] fades it to a grey
    shadow on paper (used for the black->white transition)."""
    m = Image.fromarray((np.clip(mask_small, 0, 1) * 255).astype(np.uint8))
    soft = np.array(m.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255.0
    core = np.array(m.filter(ImageFilter.GaussianBlur(14)), np.float32) / 255.0
    noise = heat_noise(t)
    yy, xx = np.mgrid[0:MH, 0:MW].astype(np.float32)
    # smooth body heat: warmer towards the shoulders, slow low-frequency shimmer
    body = 0.50 + 0.22 * noise + 0.20 * (1 - yy / MH)
    v = (soft ** 1.1) * body * intensity
    # the bright rim the reference has where the fabric edge faces the lens
    rim = np.clip(soft - core, 0, 1) * 0.55
    v = v + rim * intensity
    # a hot spot that blooms near the bottom (the reference glows at the base)
    hx, hy = 0.75 * MW, 1.04 * MH
    glow = np.exp(-(((xx - hx) / (0.11 * MW)) ** 2 + ((yy - hy) / (0.17 * MH)) ** 2))
    v = v + glow * core * 0.8 * intensity
    v = np.clip(v, 0, 1)
    thermal = thermal_colormap(v)
    alpha = np.clip(soft * 2.2, 0, 1) * intensity
    # upscale to full res
    thermal_full = np.array(Image.fromarray(thermal.astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)
    alpha_full = np.array(Image.fromarray((alpha * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)[..., None] / 255.0
    out = bg_arr * (1 - alpha_full) + thermal_full * alpha_full
    if cool > 0:
        # grey shadow version on paper
        sharp = np.array(m.filter(ImageFilter.GaussianBlur(2.2)), np.float32) / 255.0
        a2 = np.array(Image.fromarray((sharp * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)[..., None] / 255.0
        shadow = bg_arr * (1 - a2 * 0.92) + np.array(SHADOW, np.float32) * a2 * 0.92
        out = out * (1 - cool) + shadow * cool
    return out


# ------------------------------------------------------------------ scenes

TEXT_L1 = "TWO began with one question:"
TEXT_L2 = "what does it really mean to create?"
TEXT_L3 = "Not clothes for the sake of clothes."
TEXT_L4a = "but something intentional,"
TEXT_L4b = "made with purpose."
TEXT_L5 = "Each piece carries that search."
TEXT_L6 = "I hope it resonates with you too."

S = dict(red=0.0, l1=0.55, l2=3.45, l3=6.25, l4=9.65, l5=13.05, l6=16.45, end=19.85)


def reveal_times(t0, n, step):
    return [t0 + i * step for i in range(n)]


def giant_word(img, draw, text, t_in, color, slide_from, dashes):
    """Oversized cropped wordmark with dashed guides, sliding in fast."""
    e = ease_out(t_in / 0.42)
    bbox = F_GIANT.getbbox(text)
    tw = bbox[2] - bbox[0]
    x = (W - tw) / 2 - 0.02 * W + slide_from * (1 - e)
    y = H * 0.5 + (bbox[3] - bbox[1]) * 0.5 - bbox[3] * 0.0
    base_y = H * 0.5 + (bbox[3] - bbox[1]) / 2
    draw.text((x, base_y), text, font=F_GIANT, fill=color, anchor="ls")
    if dashes:
        top = base_y - (bbox[3] - bbox[1]) - 22
        a = clamp01(t_in / 0.3)
        col = mix_col(color, color, 1)
        if a > 0.2:
            dashed_line(draw, int(top), col, width=2)
            dashed_line(draw, int(base_y + 22), col, width=2)


def frame_at(t, slots, frame_idx):
    """Return an HxWx3 uint8 frame for time t (seconds)."""
    glitch_boxes = []

    # ---------- scene 0: red card, giant TWO ---------------------------
    if t < S["l1"]:
        img = bg_image("red")
        d = ImageDraw.Draw(img)
        giant_word(img, d, "TWO", t - S["red"], BLACK, 0.25 * W, dashes=True)
        if t < 3 / FPS:
            glitch_boxes.append(((0, H * 0.25, W, H * 0.75), 22))

    # ---------- scene 1: "TWO began with one question:" ----------------
    elif t < S["l2"]:
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        t0 = S["l1"] + 0.12
        times = reveal_times(t0, 5, 0.22)
        y = H * 0.5
        # dashed guides fade in with the first word, out after the line
        ga = ease_out((t - t0) / 0.2) * (1 - ease_in_out((t - (t0 + 1.9)) / 0.4))
        if ga > 0.02:
            col = mix_col(OFFWHITE, INK, ga * 0.75)
            dashed_line(d, int(y - 44), col, dash=16, gap=12, width=2)
            dashed_line(d, int(y + 14), col, dash=16, gap=12, width=2)
        words, boxes, n = draw_words(d, TEXT_L1, F_BODY, W * 0.5, y, t, times,
                                     INK, INK_LIGHT, align="center")
        # hand-drawn underline beneath "question:"
        if n == 5:
            bx0, bx1 = boxes[4]
            p = (t - (t0 + 1.75)) / 0.55
            draw_scribble(d, "underline", bx0 - 6, y + 12, (bx1 - bx0) + 12, 10,
                          p, INK, width=3, seed=11)
        # a small bracket cursor at the far right like the reference
        if t - S["l1"] < 3 / FPS:
            glitch_boxes.append(((0, y - 70, W, y + 40), 14))
        specks(d, t, 3, 5, (90, 88, 86), (W * 0.1, H * 0.15, W * 0.9, H * 0.85))

    # ---------- scene 2: "what does it really mean to create?" ---------
    elif t < S["l3"]:
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        t0 = S["l2"] + 0.1
        times = reveal_times(t0, 7, 0.21)
        y = H * 0.5
        words, boxes, n = draw_words(d, TEXT_L2, F_BODY, W * 0.5, y, t, times,
                                     INK, INK_LIGHT, align="center")
        if n == 7:
            bx0, bx1 = boxes[6]
            p = (t - (t0 + 1.95)) / 0.6
            draw_scribble(d, "ellipse", (bx0 + bx1) / 2, y - 14,
                          (bx1 - bx0) / 2 + 26, 36, p, INK, width=3, seed=23)
        if t - S["l2"] < 2 / FPS:
            glitch_boxes.append(((0, y - 70, W, y + 40), 14))
        # the sentence "settles" with a faint second cursor blink at the end
        specks(d, t, 4, 6, (90, 88, 86), (W * 0.1, H * 0.15, W * 0.9, H * 0.85))

    # ---------- scene 3: black + thermal, "Not clothes for the sake..." -
    elif t < S["l4"]:
        img = bg_image("black")
        arr = np.array(img, np.float32)
        tl = t - S["l3"]
        fade_in = ease_out(tl / 0.5)
        arr = render_silhouette(arr, slots[0](tl), t, "thermal", intensity=fade_in)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        t0 = S["l3"] + 0.15
        times = [t0, t0 + 0.22] + reveal_times(t0 + 1.35, 5, 0.2)
        y = H * 0.47
        draw_words(d, TEXT_L3, F_BODY, W * 0.07, y, t, times, CHALK, CHALK_LIGHT,
                   cursor=True, fade=0.18)
        # chalk arc hovering near the garment's shoulder
        p = (t - (S["l3"] + 0.6)) / 0.5
        if 0 < p < 2.2:
            draw_scribble(d, "arc", W * 0.62, H * 0.17, 90, 46, min(1, p),
                          (240, 238, 232), width=2, seed=5)
        if tl < 2 / FPS:
            glitch_boxes.append(((W * 0.45, 0, W, H), 20))

    # ---------- scene 4: "but something intentional," / "made with purpose."
    elif t < S["l5"]:
        tl = t - S["l4"]
        cool = ease_in_out((t - (S["l4"] + 2.55)) / 0.55)   # black -> paper
        img = bg_image("black", mix=cool)
        arr = np.array(img, np.float32)
        arr = render_silhouette(arr, slots[1](tl), t, "thermal", intensity=1.0, cool=cool)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        y = H * 0.47
        col = mix_col(CHALK, INK, cool)
        light = mix_col(CHALK_LIGHT, INK_LIGHT, cool)
        if t < S["l4"] + 1.65:
            t0 = S["l4"] + 0.12
            draw_words(d, TEXT_L4a, F_BODY, W * 0.07, y, t, reveal_times(t0, 3, 0.22),
                       col, light, fade=0.18)
        else:
            t0 = S["l4"] + 1.7
            words, boxes, n = draw_words(d, TEXT_L4b, F_BODY, W * 0.07, y, t,
                                         reveal_times(t0, 3, 0.22), col, light, fade=0.18)
            if n == 3:
                bx0, bx1 = boxes[2]
                p = (t - (t0 + 0.95)) / 0.5
                draw_scribble(d, "underline", bx0 - 4, y + 12, (bx1 - bx0) + 8, 9,
                              p, mix_col(CHALK, RED, cool), width=3, seed=31)
            if t - t0 < 2 / FPS:
                glitch_boxes.append(((0, y - 70, W * 0.55, y + 40), 14))
        if tl < 2 / FPS:
            glitch_boxes.append(((0, 0, W, H), 18))

    # ---------- scene 5: paper, drifting letters, "Each piece carries..." -
    elif t < S["l6"]:
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        tl = t - S["l5"]
        letters = [
            ("T", 0.17 * W, 0.26 * H, 0.05, 0.0),
            ("W", 0.80 * W, 0.70 * H, 0.45, 2.1),
            ("O", 0.68 * W, 0.22 * H, 0.85, 4.0),
        ]
        for i, (ch, lx, ly, t_in, ph) in enumerate(letters):
            if tl < t_in:
                continue
            x = lx + 16 * math.sin(t * 0.55 + ph)
            y = ly + 11 * math.cos(t * 0.42 + ph * 1.7)
            d.text((x, y), ch, font=F_LETTER, fill=INK, anchor="mm")
            if tl - t_in < 3 / FPS:
                glitch_boxes.append(((x - 90, y - 90, x + 90, y + 90), 10))
            # red scribbled ring, staggered
            p = (tl - (1.55 + i * 0.42)) / 0.5
            draw_scribble(d, "ellipse", x, y + 2, 78, 70, p, RED, width=3, seed=40 + i)
        t0 = S["l5"] + 0.3
        y = H * 0.5
        draw_words(d, TEXT_L5, F_BODY, W * 0.5, y, t, reveal_times(t0, 5, 0.22),
                   INK, INK_LIGHT, align="center")
        specks(d, t, 9, 14, (70, 68, 66))
        specks(d, t, 10, 5, RED, (W * 0.1, H * 0.1, W * 0.9, H * 0.9))
        if tl < 2 / FPS:
            glitch_boxes.append(((0, 0, W, H), 18))

    # ---------- scene 6: black, "I hope it resonates with you too." -----
    elif t < S["end"]:
        img = bg_image("black")
        arr = np.array(img, np.float32)
        tl = t - S["l6"]
        fade_in = ease_out(tl / 0.6)
        fade_out = 1 - ease_in_out((t - (S["end"] - 0.6)) / 0.5)
        arr = render_silhouette(arr, slots[2](tl), t, "thermal",
                                intensity=0.85 * fade_in * fade_out)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        t0 = S["l6"] + 0.2
        y = H * 0.47
        words, boxes, n = draw_words(d, TEXT_L6, F_BODY, W * 0.07, y, t,
                                     reveal_times(t0, 7, 0.24), CHALK, CHALK_LIGHT, fade=0.2)
        if n == 7:
            bx0, bx1 = boxes[6]
            p = (t - (t0 + 1.9)) / 0.6
            draw_scribble(d, "ellipse", (bx0 + bx1) / 2, y - 14,
                          (bx1 - bx0) / 2 + 24, 34, p, (240, 238, 232), width=3, seed=51)
        if tl < 2 / FPS:
            glitch_boxes.append(((0, 0, W, H), 18))

    # ---------- scene 7: paper, giant TWO outro ------------------------
    else:
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        tl = t - S["end"]
        giant_word(img, d, "TWO", tl, INK, -0.22 * W, dashes=True)
        if tl < 3 / FPS:
            glitch_boxes.append(((0, H * 0.2, W, H * 0.8), 22))
        # tiny caption under the wordmark, typed
        if tl > 0.7:
            cap = "made with purpose."
            draw_words(d, cap, F_TINY, W * 0.5, H * 0.86, t, reveal_times(S["end"] + 0.75, 3, 0.18),
                       INK, INK_LIGHT, align="center", cursor=True)
        # final fade to paper-white is left to the cut; hold the card

    for box, factor in glitch_boxes:
        pixel_glitch(img, box, factor=factor, seed=frame_idx)

    # ---------- film layer: grain + micro flicker ----------------------
    arr = np.array(img, np.float32)
    grain = rng_global.normal(0, 5.2, (H, W, 1)).astype(np.float32)
    flicker = 1 + 0.012 * math.sin(frame_idx * 1.9) + 0.006 * math.sin(frame_idx * 0.37)
    arr = arr * flicker + grain
    return np.clip(arr, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--footage", help="dir with clipA.mp4 clipB.mp4 clipC.mp4")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=DURATION)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--key-invert", action="store_true",
                    help="footage subject is darker than its background")
    args = ap.parse_args()

    tmpdir = tempfile.mkdtemp(prefix="two_mv_")
    slots = []
    for i, name in enumerate(["clipA.mp4", "clipB.mp4", "clipC.mp4"]):
        path = os.path.join(args.footage, name) if args.footage else None
        if path and os.path.exists(path):
            FootageSlot.invert = args.key_invert
            fs = FootageSlot(path, tmpdir)
            slots.append(fs.mask)
            print(f"slot {i}: {path} ({fs.n} frames)", file=sys.stderr)
        else:
            slots.append(lambda tl, s=i: procedural_mask(tl, s))
            print(f"slot {i}: procedural garment silhouette", file=sys.stderr)

    n0 = int(args.start * FPS)
    n1 = int(args.end * FPS)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", args.out,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n0, n1):
        t = i / FPS
        fr = frame_at(t, slots, i)
        proc.stdin.write(fr.tobytes())
        if i % 48 == 0:
            print(f"  {t:5.2f}s / {args.end:.2f}s", file=sys.stderr)
    proc.stdin.close()
    proc.wait()
    print("done:", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
