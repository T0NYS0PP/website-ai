#!/usr/bin/env python3
"""
TWO — vertical beat-cut montage (second reference: a travel-diary style edit).

Format: 1080x1920, 24 fps, black. A 4:3 window shows one shot per beat.
During each shot a cut-out "sticker" of the NEXT shot's subject pops in above the
window, hovers with a little wobble, and drops into the window on the cut.
The last sticker is the TWO logotype on its red card, which lands as the end card.

Inputs (under --paris DIR):
  shots.txt                 idx clip t_in crop  (one line per shot, in order)
  shots/<idx>/NNN.png       graded 4:3 frames of each shot (976x732, 24 fps)
  stickers/<idx>_cut.png    RGBA cut-out of each shot's subject
  beats.json                {"cuts":[t0,t1,...], "end": t}  from beats.py (times of each cut)
Usage:
  python render_two_paris.py out.mp4 --paris paris --audio paris/mix.wav
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_two as R

W, H, FPS = 1080, 1920, 24
WIN_W, WIN_H = 976, 732
WIN_X, WIN_Y = (W - WIN_W) // 2, int(0.358 * H)          # like the reference: window at 36-74 % of the height
BLACK = (8, 8, 8)
RED = (214, 38, 28)
INK = (24, 22, 22)
OFFWHITE = (233, 231, 227)
F_GIANT = ImageFont.truetype("/usr/share/fonts/opentype/inter/InterDisplay-Black.otf", 420)
F_CAP = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf", 34)

rng = np.random.default_rng(11)
vrng = np.random.default_rng(23)
SRC_W, SRC_H = 1040, 780                 # shots are extracted oversized; the handheld crop wanders inside


def vhs(img, strong=False):
    """Camcorder / VHS look on the window image (PIL RGB WIN_W x WIN_H):
    soft luma, bleeding and shifted chroma, bloom, lifted blacks, noise, scanlines,
    dropout streaks, head-switching noise at the bottom, occasional tearing."""
    from PIL import ImageChops
    small = img.resize((WIN_W // 2, WIN_H // 2), Image.BILINEAR)
    y, cb, cr = small.convert("YCbCr").split()
    y = y.filter(ImageFilter.GaussianBlur(0.6))
    cb = cb.filter(ImageFilter.BoxBlur(4))
    cr = ImageChops.offset(cr.filter(ImageFilter.BoxBlur(4)), 3, 0)
    sm = Image.merge("YCbCr", (y, cb, cr)).convert("RGB")
    bloom = Image.fromarray(np.clip((np.array(sm, np.float32) - 150) * 1.6, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7))
    arr = np.array(sm.resize((WIN_W, WIN_H), Image.BILINEAR), np.float32)
    arr += 0.30 * np.array(bloom.resize((WIN_W, WIN_H), Image.BILINEAR), np.float32)
    arr = arr * 0.90 + 14.0                                   # lifted blacks, soft-clipped whites
    arr = np.where(arr > 225, 225 + (arr - 225) * 0.35, arr)
    arr += vrng.normal(0, 4.5, (WIN_H, WIN_W, 1)).astype(np.float32)
    arr += vrng.normal(0, 2.5, (WIN_H, WIN_W, 3)).astype(np.float32)
    arr[1::2] *= 0.94                                         # scanlines
    # dropout streaks
    for _ in range(vrng.integers(2, 7) + (10 if strong else 0)):
        r = vrng.integers(0, WIN_H); x0 = vrng.integers(0, WIN_W - 40); ln = vrng.integers(20, 160)
        arr[r, x0:x0 + ln] = np.clip(arr[r, x0:x0 + ln] + vrng.choice([70, -45]), 0, 255)
    # head-switching noise band at the bottom
    for r in range(WIN_H - 9, WIN_H):
        arr[r] = np.roll(arr[r], int(vrng.integers(-22, 22)), axis=0)
        arr[r] = arr[r] * 0.6 + vrng.normal(90, 40, (WIN_W, 1))
    # tearing: a band of rows shifted sideways
    if strong or vrng.random() < 0.05:
        r0 = vrng.integers(0, WIN_H - 70); h = vrng.integers(16, 64); dx = int(vrng.integers(8, 34)) * vrng.choice([-1, 1])
        arr[r0:r0 + h] = np.roll(arr[r0:r0 + h], dx, axis=1)
        if strong:
            r1 = vrng.integers(0, WIN_H - 40); arr[r1:r1 + 6] = np.clip(arr[r1:r1 + 6] * 1.4 + 40, 0, 255)
    # one-line vertical jitter
    arr = np.roll(arr, int(vrng.integers(-1, 2)), axis=0)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def handheld_path(n, seed):
    """Smooth random-walk offsets (pixels) for a handheld feel: slow drift plus a little tremor."""
    r = np.random.default_rng(seed)
    base = np.cumsum(r.normal(0, 1.6, (n + 24, 2)), axis=0)
    k = np.hanning(13); k /= k.sum()
    sm = np.stack([np.convolve(base[:, i], k, mode="same") for i in range(2)], 1)[:n]
    sm -= sm.mean(0)
    sm = np.clip(sm * 1.2, -26, 26)
    return sm + r.normal(0, 0.9, (n, 2))


def vhs_sticker(im):
    """Match the cut-outs to the window: a little saturation, softness and warmth, no outline."""
    rgb = im.convert("RGB").resize((im.width // 2, im.height // 2), Image.BILINEAR).resize(im.size, Image.BILINEAR)
    arr = np.array(rgb, np.float32)
    grey = arr.mean(2, keepdims=True)
    arr = grey + (arr - grey) * 1.35
    arr = (arr - 128) * 1.15 + 128 + 14
    arr *= np.array([1.05, 1.0, 0.96], np.float32)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
    out.putalpha(im.split()[3])
    return out


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * t


class Shot:
    def __init__(self, folder, seed=0):
        self.files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".png"))
        self.path = handheld_path(len(self.files) + 4, seed)

    def frame(self, i):
        i = min(max(i, 0), len(self.files) - 1)
        im = Image.open(self.files[i]).convert("RGB")
        if im.size != (WIN_W, WIN_H):
            ox, oy = self.path[i]
            x0 = int((im.width - WIN_W) / 2 + ox)
            y0 = int((im.height - WIN_H) / 2 + oy)
            x0 = min(max(x0, 0), im.width - WIN_W)
            y0 = min(max(y0, 0), im.height - WIN_H)
            im = im.crop((x0, y0, x0 + WIN_W, y0 + WIN_H))
        return im


def load_sticker(path, max_h=540, max_w=660):
    im = Image.open(path).convert("RGBA")
    s = min(max_h / im.height, max_w / im.width)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    return vhs_sticker(im)


def logo_sticker():
    """The TWO logotype on a red card, used as the final sticker and end card."""
    card = Image.new("RGBA", (WIN_W, WIN_H), RED + (255,))
    d = ImageDraw.Draw(card)
    bbox = F_GIANT.getbbox("TWO")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((WIN_W - tw) / 2 - bbox[0], (WIN_H - th) / 2 - bbox[1] - 20), "TWO", font=F_GIANT, fill=INK)
    return card


def paste_rotated(canvas, im, cx, cy, scale, angle, blur_v=0):
    if scale <= 0.01:
        return
    w, h = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    s = im.resize((w, h), Image.LANCZOS)
    if angle:
        s = s.rotate(angle, resample=Image.BICUBIC, expand=True)
    if blur_v > 0:
        # cheap vertical motion blur: stack offset copies
        n = 5
        acc = Image.new("RGBA", (s.width, s.height + blur_v), (0, 0, 0, 0))
        for k in range(n):
            layer = Image.new("RGBA", acc.size, (0, 0, 0, 0))
            layer.paste(s, (0, int(k * blur_v / (n - 1))), s)
            layer.putalpha(layer.split()[3].point(lambda v: int(v / n * 1.6)))
            acc = Image.alpha_composite(acc, layer)
        s = acc
    canvas.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--paris", default="paris")
    ap.add_argument("--audio")
    ap.add_argument("--crf", type=int, default=20)
    args = ap.parse_args()
    P = args.paris

    beats = json.load(open(os.path.join(P, "beats.json")))
    cuts = beats["cuts"]                     # start time of shot k = cuts[k]; the logo lands at cuts[-1]
    end_t = beats["end"]
    shots_meta = [l.split() for l in open(os.path.join(P, "shots.txt")) if l.strip() and not l.startswith("#")]
    shots = [Shot(os.path.join(P, "shots", m[0]), seed=i * 7 + 1) for i, m in enumerate(shots_meta)]
    stickers = [load_sticker(os.path.join(P, "stickers", m[0] + "_cut.png")) for m in shots_meta]
    n_shots = len(shots)
    assert len(cuts) >= n_shots + 1, "beats.json needs one cut per shot plus the logo landing"
    logo = logo_sticker()
    logo_small = logo.resize((int(WIN_W * 0.36), int(WIN_H * 0.36)), Image.LANCZOS)
    # sticker x positions: wander around the window's middle
    xs = [W / 2 + rng.uniform(-0.22, 0.22) * WIN_W for _ in range(n_shots + 1)]
    hover_y = WIN_Y - 6                      # sticker bottom sits right on the window's top edge
    total_frames = int(round(end_t * FPS))

    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-"]
    if args.audio:
        cmd += ["-i", args.audio, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for fi in range(total_frames):
        t = fi / FPS
        canvas = Image.new("RGBA", (W, H), BLACK + (255,))
        # which shot is playing
        k = max(0, max(i for i in range(len(cuts)) if cuts[i] <= t) if t >= cuts[0] else -1)
        if t < cuts[0]:
            k = 0                                    # pre-roll: the first shot dissolves in before beat 0
        if 0 <= k < n_shots:
            a, b = cuts[k], cuts[k + 1]
            local = t - a
            frame = shots[k].frame(int(round(local * FPS)))
            # impact: the new shot lands slightly big and settles
            z = 1.0 + 0.06 * (1 - ease_out(local / 0.17))
            if z > 1.001:
                fw, fh = frame.size
                cw, ch = int(fw / z), int(fh / z)
                frame = frame.crop(((fw - cw) // 2, (fh - ch) // 2, (fw - cw) // 2 + cw, (fh - ch) // 2 + ch)).resize((fw, fh), Image.BILINEAR)
            frame = vhs(frame, strong=(local < 2 / FPS))
            if k == 0 and t < cuts[0]:
                # opener: checkerboard dissolve into the first shot during the pre-roll
                p = t / max(cuts[0], 1e-6)
                frame = vhs(shots[0].frame(0))
                m = np.zeros((WIN_H, WIN_W), np.uint8)
                cell = 36
                yy, xx = np.mgrid[0:WIN_H, 0:WIN_W]
                phase = ((xx // cell) + (yy // cell)) % 2
                thr = (yy / WIN_H) * 0.6 + phase * 0.4
                m[(thr < p)] = 255
                frame.putalpha(Image.fromarray(m))
                canvas.alpha_composite(frame, (WIN_X, WIN_Y))
            else:
                canvas.paste(frame, (WIN_X, WIN_Y))
            # the NEXT shot's sticker: pop in, hover, drop on the cut
            nxt = stickers[k + 1] if k + 1 < n_shots else logo_small
            appear = a + 0.10
            drop_t = b - 0.12
            if t >= cuts[0] and appear <= t < b:
                if t < drop_t:
                    u = (t - appear) / 0.14
                    sc = 1.15 * ease_out(u) if u < 1 else 1.0 + 0.15 * (1 - ease_out((t - appear - 0.14) / 0.12))
                    wob = t - appear
                    ang = 4.0 * math.sin(wob * 9.0 + k)
                    bob = 6.0 * math.sin(wob * 7.0 + k * 1.3)
                    cy = hover_y - nxt.height / 2 + bob
                    paste_rotated(canvas, nxt, xs[k + 1], cy, sc, ang)
                else:
                    # falling into the window with vertical blur
                    u = (t - drop_t) / (b - drop_t)
                    cy0 = hover_y - nxt.height / 2
                    cy = cy0 + ease_in(u) * (WIN_Y + WIN_H * 0.55 - cy0)
                    paste_rotated(canvas, nxt, xs[k + 1], cy, 1.0, 0.0, blur_v=int(40 * u + 10))
        elif k >= n_shots:
            # end card: the red TWO card has landed in the window
            local = t - cuts[n_shots]
            z = 1.0 + 0.06 * (1 - ease_out(local / 0.17))
            card = logo.copy()
            if z > 1.001:
                cw, ch = int(WIN_W / z), int(WIN_H / z)
                card = card.crop(((WIN_W - cw) // 2, (WIN_H - ch) // 2, (WIN_W - cw) // 2 + cw, (WIN_H - ch) // 2 + ch)).resize((WIN_W, WIN_H), Image.BILINEAR)
            canvas.alpha_composite(card, (WIN_X, WIN_Y))
            if local > 0.45:
                d = ImageDraw.Draw(canvas)
                cap = "made with purpose."
                words = cap.split()
                n_show = min(len(words), int((local - 0.45) / 0.18) + 1)
                txt = " ".join(words[:n_show])
                tw = F_CAP.getlength(txt)
                d.text(((W - F_CAP.getlength(cap)) / 2, WIN_Y + WIN_H + 70), txt, font=F_CAP, fill=OFFWHITE)
        img = canvas.convert("RGB")
        arr = np.array(img, np.float32)
        arr += R.rng_global.normal(0, 3.5, (H, W, 1)).astype(np.float32)
        fade = min(max((t - (end_t - 0.4)) / 0.4, 0.0), 1.0)
        if fade > 0:
            arr *= (1 - fade)
        proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
        if fi % 48 == 0:
            print(f"  {t:5.2f}s / {end_t:.2f}s", file=sys.stderr)
    proc.stdin.close()
    proc.wait()
    print("done:", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
