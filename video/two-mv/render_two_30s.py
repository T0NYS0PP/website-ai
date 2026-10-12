#!/usr/bin/env python3
"""
TWO — 30 s cut with voice-over, music and real footage.

Builds on render_two.py (same look: paper/black scenes, word-by-word type, hand-drawn
marks, pixel glitches, thermal silhouettes, grain) and adds:
  * PLATES: full-bleed real-footage beats, printed into the film's own palette
    (ink/paper duotone with a little residual colour), no type on them
  * a PANEL: the walking figure cut out in colour in the thermal slot's exact
    geometry, which then ignites into the thermal silhouette (a match cut)
  * the cooled shadow "developing" into the printed real figure before the next cut
  * on-screen word reveals timed to the voice-over (audio/vo_timing.json from mix_audio.py)

Usage:
  python render_two_30s.py out.mp4 --footage footage --real real --timing audio/vo_timing.json
                           --audio audio/mix.wav [--start S --end S] [--crf N]
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_two as R
from render_two import (W, H, FPS, bg_image, draw_words, draw_scribble, dashed_line, pixel_glitch, specks,
                        render_silhouette, procedural_mask, FootageSlot, parse_clip_spec, giant_word,
                        ease_out, ease_in_out, clamp01, mix_col, reveal_times,
                        F_BODY, F_LETTER, F_TINY, INK, INK_LIGHT, CHALK, CHALK_LIGHT, RED, BLACK, OFFWHITE, SHADOW)

DURATION = 30.0

# ------------------------------------------------------------------ timeline
T = dict(
    red=(0.0, 0.6),        # giant TWO on red
    p1=(0.6, 3.0),         # paper: "TWO began with one question:"
    plateQ=(3.0, 4.0),     # real: hand on chin (04.mov)
    p2=(4.0, 6.97),        # paper: "what does it really mean to create?"
    panel=(6.97, 8.68),    # real: walking figure cut out in colour, in the thermal slot
    p3=(8.68, 12.12),      # ignition -> thermal walk: "Not clothes for the sake of clothes."
    p4=(12.12, 15.55),     # thermal seated profile -> cools to shadow -> develops into the print
    plateS=(15.55, 17.30), # real: hands on the embroidered cuff (10.mov)
    p5=(17.30, 20.7),      # paper letters: "Each piece carries that search."
    p6=(20.7, 24.13),      # thermal standing figure turns to us: "I hope it resonates with you too."
    plateG=(24.13, 27.56), # real: the gaze (04.mov)
    outro=(27.56, 30.0),   # giant TWO on paper (on the bed's last chord), caption, fade to flat paper white
)
# cuts sit 0-80 ms before the music bed's accents (69.8 bpm grid, see mix_audio.MUSIC_DELAY)
IGNITE = 8 / FPS           # seconds of real -> thermal cross at the start of p3
PHRASE_TEXT = {
    "p1": "TWO began with one question:",
    "p2": "what does it really mean to create?",
    "p3": "Not clothes for the sake of clothes.",
    "p4a": "but something intentional,",
    "p4b": "made with purpose.",
    "p5": "Each piece carries that search.",
    "p6": "I hope it resonates with you too.",
}
FALLBACK_START = {"p1": 0.8, "p2": 4.2, "p3": 8.9, "p4a": 12.35, "p4b": 14.05, "p5": 17.5, "p6": 20.9}
CLIPS = {
    "walk": "01.mov@2.45:scale=1.5:y=0.145",              # panel 2.45-4.16 s, thermal 4.16-7.6 s; feet clear the frame edge
    "seat": "05.mov@1.0:scale=1.5:y=0.22",                # seated profile, faces the text
    "stand": "10.mov@4.2:flip:scale=1.5:y=0.06",          # head turns to camera ~1.2 s in; clear of the text column
}
PLATES = {"plateQ": "Q", "plateS": "S", "plateG": "G"}
PLATE_PUSH = {"plateQ": 0.0, "plateS": 0.0, "plateG": 0.05}

VIG_PLATE = R._vignette(0.34)


def load_timing(path):
    times = {}
    if path and os.path.exists(path):
        for p in json.load(open(path))["phrases"]:
            tt = [w["t"] for w in p["words"]]
            for i in range(1, len(tt)):
                tt[i] = max(tt[i], tt[i - 1] + 0.06)
            times[p["key"]] = tt
    for k, text in PHRASE_TEXT.items():
        if k not in times:
            times[k] = reveal_times(FALLBACK_START[k], len(text.split()), 0.26)
    return times


# ------------------------------------------------------------ print grade
_DUO_PAPER = ([0.0, 0.5, 1.0], [(16, 13, 12), (128, 117, 106), (233, 231, 227)])
_DUO_BLACK = ([0.0, 0.5, 1.0], [(13, 12, 12), (122, 98, 78), (240, 222, 196)])


def print_grade(rgb, mode="paper", orig_blend=0.30):
    """Photographed footage printed into the film's palette: an ink/paper duotone of
    the luminance (S-curve, lifted black, white never brighter than the paper) with
    a little of the warm, desaturated original blended back so the embroidery keeps
    its gold. rgb: uint8 HxWx3 -> float32 HxWx3."""
    f = rgb.astype(np.float32) / 255.0
    y = 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]
    y = np.clip(0.45 + 1.25 * (y - 0.45), 0, 1)
    y = y * y * (3 - 2 * y) * 0.3 + y * 0.7            # soft shoulders
    stops, cols = _DUO_PAPER if mode == "paper" else _DUO_BLACK
    cols = np.array(cols, np.float32)
    duo = np.empty(f.shape, np.float32)
    for c in range(3):
        duo[..., c] = np.interp(y, stops, cols[:, c])
    grey = y[..., None] * 255.0
    sat = 0.60
    orig = f * 255.0
    orig = grey + (orig - grey) * sat
    orig = orig * np.array([1.06, 1.00, 0.90], np.float32)
    orig = np.clip(orig, 16, 236)
    return duo * (1 - orig_blend) + orig * orig_blend


class Plate:
    """PNG frames (1512x1134, ungraded) of a full-bleed real beat, printed on the fly."""

    def __init__(self, folder, push=0.0):
        self.files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".png"))
        self.push = push

    def frame(self, i, u):
        i = min(max(i, 0), len(self.files) - 1)
        im = Image.open(self.files[i]).convert("RGB")
        fw, fh = im.size
        z = 1.0 + self.push * ease_in_out(u)
        cw, ch = int(round(fw / z)), int(round(fh / z))
        x0, y0 = (fw - cw) // 2, (fh - ch) // 2
        im = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.LANCZOS)
        arr = print_grade(np.array(im), "paper") * VIG_PLATE
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


class Slots:
    """The three matted clips plus the colour frames the panel and the develop need."""

    def __init__(self, footage):
        self.walk = FootageSlot(**parse_clip_spec(CLIPS["walk"], footage), duration=5.2)
        self.seat = FootageSlot(**parse_clip_spec(CLIPS["seat"], footage), duration=4.4)
        self.stand = FootageSlot(**parse_clip_spec(CLIPS["stand"], footage), duration=3.8)
        for name, s in (("walk", self.walk), ("seat", self.seat), ("stand", self.stand)):
            print(f"{name}: {s.n} frames, matte={s.method}", file=sys.stderr)
        # colour frames: the whole panel + ignition for the walk, the develop window for the seat
        self.walk_rgb = self.walk.color(0.0, (T["panel"][1] - T["panel"][0]) + IGNITE + 0.1)
        dev0 = (T["p4"][1] - 1.0) - T["p4"][0]
        self.seat_rgb = self.seat.color(dev0, dev0 + 1.05)
        self.seat_rgb_t0 = dev0
        print(f"colour frames: walk {len(self.walk_rgb)}, seat {len(self.seat_rgb)}", file=sys.stderr)

    def walk_color(self, t_local):
        i = min(int(t_local * FPS), len(self.walk_rgb) - 1)
        return self.walk_rgb[i]

    def seat_color(self, t_local):
        i = min(max(int((t_local - self.seat_rgb_t0) * FPS), 0), len(self.seat_rgb) - 1)
        return self.seat_rgb[i]


def composite_cutout(bg_arr, rgb, alpha, mode):
    fig = print_grade(rgb, mode)
    return bg_arr * (1 - alpha) + fig * alpha


def frame_at(t, S, plates, times, idx):
    glitch = []

    def in_scene(k):
        return T[k][0] <= t < T[k][1]

    def tl(k):
        return t - T[k][0]

    def cut_glitch(k, box=(0, 0, W, H), factor=18, frames=2):
        if tl(k) < frames / FPS:
            glitch.append((box, factor))

    panel_box = (0.34 * W, 0, W, H)
    type_band = (0, H * 0.43, W, H * 0.55)

    # ---------- opener
    if in_scene("red"):
        img = bg_image("red")
        d = ImageDraw.Draw(img)
        giant_word(img, d, "TWO", tl("red"), BLACK, 0.25 * W, dashes=True)
        cut_glitch("red", (0, H * 0.25, W, H * 0.75), 22, 3)

    # ---------- plates (full-bleed real footage, printed; no type)
    elif any(in_scene(k) for k in PLATES):
        k = next(k for k in PLATES if in_scene(k))
        a, b = T[k]
        img = plates[k].frame(int(round((t - a) * FPS)), (t - a) / (b - a))
        cut_glitch(k, (0, 0, W, H), 20, 1 if k == "plateS" else 2)

    # ---------- p1
    elif in_scene("p1"):
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        y = H * 0.5
        tw = times["p1"]
        ga = ease_out((t - tw[0]) / 0.2) * (1 - ease_in_out((t - (tw[-1] + 0.55)) / 0.3))
        if ga > 0.02:
            col = mix_col(OFFWHITE, INK, ga * 0.75)
            dashed_line(d, int(y - 44), col, dash=16, gap=12, width=2)
            dashed_line(d, int(y + 14), col, dash=16, gap=12, width=2)
        words, boxes, n = draw_words(d, PHRASE_TEXT["p1"], F_BODY, W * 0.5, y, t, tw, INK, INK_LIGHT, align="center")
        if n == 5:
            bx0, bx1 = boxes[4]
            p = (t - (tw[-1] + 0.35)) / 0.3
            draw_scribble(d, "underline", bx0 - 6, y + 12, (bx1 - bx0) + 12, 10, p, INK, width=3, seed=11)
        specks(d, t, 3, 5, (90, 88, 86), (W * 0.1, H * 0.15, W * 0.9, H * 0.85))
        cut_glitch("p1", (0, y - 70, W, y + 40), 14, 2)

    # ---------- p2
    elif in_scene("p2"):
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        y = H * 0.5
        tw = times["p2"]
        words, boxes, n = draw_words(d, PHRASE_TEXT["p2"], F_BODY, W * 0.5, y, t, tw, INK, INK_LIGHT, align="center")
        if n == 7:
            bx0, bx1 = boxes[6]
            p = (t - (tw[-1] + 0.4)) / 0.5
            draw_scribble(d, "ellipse", (bx0 + bx1) / 2, y - 14, (bx1 - bx0) / 2 + 26, 36, p, INK, width=3, seed=23)
        specks(d, t, 4, 6, (90, 88, 86), (W * 0.1, H * 0.15, W * 0.9, H * 0.85))
        cut_glitch("p2", type_band, 14, 3)

    # ---------- panel: the walking figure, printed, in the thermal slot geometry, on paper
    elif in_scene("panel"):
        arr = np.array(bg_image("paper"), np.float32)
        s = tl("panel")
        alpha = S.walk.mask_full(s)
        arr = composite_cutout(arr, S.walk_color(s), alpha, "paper")
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        specks(d, t, 6, 4, (90, 88, 86), (W * 0.08, H * 0.15, W * 0.4, H * 0.85))
        cut_glitch("panel", panel_box, 20, 2)

    # ---------- p3: ignition, then the thermal walk continues the same clip
    elif in_scene("p3"):
        s = tl("p3")
        s_clip = (T["panel"][1] - T["panel"][0]) + s          # local time on the walk slot
        img = bg_image("black")
        arr = np.array(img, np.float32)
        ig = clamp01(s / IGNITE)
        heat = ease_out(ig)
        mask = S.walk.mask(s_clip)
        arr = render_silhouette(arr, mask, t, "thermal", intensity=heat)
        if ig < 1.0:
            alpha = S.walk.mask_full(s_clip) * (1 - ig)
            arr = composite_cutout(arr, S.walk_color(s_clip), alpha, "black")
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        y = H * 0.47
        draw_words(d, PHRASE_TEXT["p3"], F_BODY, W * 0.07, y, t, times["p3"], CHALK, CHALK_LIGHT, fade=0.18)
        ys, xs = np.nonzero(mask > 0.5)
        if len(ys) > 50:
            top = ys.min()
            head_x = xs[ys < top + 8].mean() * R.MASK_SCALE
            head_y = top * R.MASK_SCALE
            if s < 1.1:
                p = (s - 0.6) / 0.5
            elif s < 1.9:
                p = 1.0
            else:
                p = 1.0 - (s - 1.9) / 0.4
            if p > 0:
                draw_scribble(d, "arc", head_x + 10, head_y - 34, 80, 36, p, (240, 238, 232), width=2, seed=5)
        cut_glitch("p3", panel_box, 20, 2)

    # ---------- p4: thermal seated profile -> cooled shadow -> the print develops inside it
    elif in_scene("p4"):
        s = tl("p4")
        ta, tb = times["p4a"], times["p4b"]
        cool_t0 = tb[0] + 0.35
        cool = ease_in_out((t - cool_t0) / 0.5)
        dev_t0 = T["p4"][1] - 0.62                             # develop over 12 frames, then a short hold
        dev = ease_in_out((t - dev_t0) / (12 / FPS))
        img = bg_image("black", mix=cool)
        arr = np.array(img, np.float32)
        arr = render_silhouette(arr, S.seat.mask(s), t, "thermal", intensity=1.0 - cool, cool=cool)
        if dev > 0:
            alpha = S.seat.mask_full(s) * 0.92 * dev
            arr = composite_cutout(arr, S.seat_color(s), alpha, "paper")
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        y = H * 0.47
        col = INK if cool >= 0.5 else CHALK
        light = INK_LIGHT if cool >= 0.5 else CHALK_LIGHT
        if t < tb[0] - 0.05:
            draw_words(d, PHRASE_TEXT["p4a"], F_BODY, W * 0.07, y, t, ta, col, light, fade=0.18)
        else:
            words, boxes, n = draw_words(d, PHRASE_TEXT["p4b"], F_BODY, W * 0.07, y, t, tb, col, light, fade=0.18)
            if n == 3:
                bx0, bx1 = boxes[2]
                p = (t - (tb[-1] + 0.35)) / 0.5
                draw_scribble(d, "underline", bx0 - 4, y + 12, (bx1 - bx0) + 8, 9, p,
                              RED if cool >= 0.5 else CHALK, width=3, seed=31)
            if t - (tb[0] - 0.05) < 2 / FPS:
                glitch.append(((0, y - 70, W * 0.55, y + 40), 14))
        if T["p4"][1] - 2 / FPS <= t:                           # glitch on the panel just before the cut
            glitch.append((panel_box, 18))
        cut_glitch("p4", panel_box, 18, 2)

    # ---------- p5: paper letters
    elif in_scene("p5"):
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        s = tl("p5")
        letters = [("T", 0.17 * W, 0.26 * H, 0.05, 0.0), ("W", 0.80 * W, 0.70 * H, 0.40, 2.1), ("O", 0.68 * W, 0.22 * H, 0.75, 4.0)]
        for i, (ch, lx, ly, t_in, ph) in enumerate(letters):
            if s < t_in:
                continue
            x = lx + 16 * math.sin(t * 0.55 + ph)
            yy = ly + 11 * math.cos(t * 0.42 + ph * 1.7)
            d.text((x, yy), ch, font=F_LETTER, fill=INK, anchor="mm")
            if s - t_in < 3 / FPS:
                glitch.append(((x - 90, yy - 90, x + 90, yy + 90), 10))
            p = (s - (1.4 + i * 0.4)) / 0.5
            draw_scribble(d, "ellipse", x, yy + 2, 78, 70, p, RED, width=3, seed=40 + i)
        y = H * 0.5
        draw_words(d, PHRASE_TEXT["p5"], F_BODY, W * 0.5, y, t, times["p5"], INK, INK_LIGHT, align="center")
        specks(d, t, 9, 14, (70, 68, 66))
        specks(d, t, 10, 5, RED, (W * 0.1, H * 0.1, W * 0.9, H * 0.9))
        cut_glitch("p5", type_band, 14, 3)

    # ---------- p6: thermal standing figure, turns to us
    elif in_scene("p6"):
        img = bg_image("black")
        arr = np.array(img, np.float32)
        s = tl("p6")
        fade_in = 0.35 + 0.65 * ease_out(s / 0.25)
        fade_out = 1 - ease_in_out((s - 2.2) / 0.8)              # gone before the hand reaches the mouth
        arr = render_silhouette(arr, S.stand.mask(s), t, "thermal", intensity=0.95 * fade_in * fade_out)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        y = H * 0.47
        tw = times["p6"]
        words, boxes, n = draw_words(d, PHRASE_TEXT["p6"], F_BODY, W * 0.07, y, t, tw, CHALK, CHALK_LIGHT, fade=0.2)
        if n == 7:
            bx0, bx1 = boxes[6]
            p = (t - (tw[-1] + 0.4)) / 0.55
            draw_scribble(d, "ellipse", (bx0 + bx1) / 2, y - 14, (bx1 - bx0) / 2 + 24, 34, p, (240, 238, 232), width=3, seed=51)
        cut_glitch("p6", (0, 0, W, H), 18, 2)

    # ---------- outro
    else:
        img = bg_image("paper")
        d = ImageDraw.Draw(img)
        s = tl("outro")
        guides = 1 - ease_in_out((s - 1.55) / 0.3)
        giant_word(img, d, "TWO", s, INK, -0.22 * W, dashes=guides > 0.5)
        if s > 0.55:
            draw_words(d, "made with purpose.", F_TINY, W * 0.5, H * 0.86, t,
                       reveal_times(T["outro"][0] + 0.6, 3, 0.2), INK, INK_LIGHT, align="center", cursor=True)
        cut_glitch("outro", (0, H * 0.2, W, H * 0.8), 22, 3)

    for box, factor in glitch:
        pixel_glitch(img, box, factor=factor, seed=idx)

    arr = np.array(img, np.float32)
    grain = R.rng_global.normal(0, 5.2, (H, W, 1)).astype(np.float32)
    flicker = 1 + 0.012 * math.sin(idx * 1.9) + 0.006 * math.sin(idx * 0.37)
    arr = arr * flicker + grain
    # the last 0.8 s: fade to flat paper white, grain and flicker going with it
    fade = ease_in_out((t - (DURATION - 0.8)) / 0.8)
    if fade > 0:
        arr = arr * (1 - fade) + np.array(OFFWHITE, np.float32) * fade
    return np.clip(arr, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--footage", default="footage")
    ap.add_argument("--real", default="real")
    ap.add_argument("--timing", default="audio/vo_timing.json")
    ap.add_argument("--audio", help="mix.wav to mux into the output")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=DURATION)
    ap.add_argument("--crf", type=int, default=20)
    args = ap.parse_args()

    times = load_timing(args.timing)
    S = Slots(args.footage)
    plates = {k: Plate(os.path.join(args.real, v), PLATE_PUSH[k]) for k, v in PLATES.items()}

    n0, n1 = int(args.start * FPS), int(args.end * FPS)
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if args.audio:
        cmd += ["-i", args.audio, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n0, n1):
        t = i / FPS
        proc.stdin.write(frame_at(t, S, plates, times, i).tobytes())
        if i % 48 == 0:
            print(f"  {t:5.2f}s / {args.end:.2f}s", file=sys.stderr)
    proc.stdin.close()
    proc.wait()
    print("done:", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
