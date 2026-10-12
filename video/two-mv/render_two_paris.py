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


def ease_out(t):
    t = min(max(t, 0.0), 1.0)
    return 1 - (1 - t) ** 3


def ease_in(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * t


class Shot:
    def __init__(self, folder):
        self.files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".png"))

    def frame(self, i):
        return Image.open(self.files[min(max(i, 0), len(self.files) - 1)]).convert("RGB")


def load_sticker(path, max_h=520, max_w=640):
    im = Image.open(path).convert("RGBA")
    s = min(max_h / im.height, max_w / im.width)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    # a thin paper-white outline, like a cut sticker
    a = im.split()[3]
    edge = a.filter(ImageFilter.MaxFilter(7))
    outline = Image.new("RGBA", im.size, (240, 238, 232, 0))
    outline.putalpha(edge)
    out = Image.alpha_composite(outline, im)
    return out


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
    shots = [Shot(os.path.join(P, "shots", m[0])) for m in shots_meta]
    stickers = [load_sticker(os.path.join(P, "stickers", m[0] + "_cut.png")) for m in shots_meta]
    n_shots = len(shots)
    assert len(cuts) >= n_shots + 1, "beats.json needs one cut per shot plus the logo landing"
    logo = logo_sticker()
    logo_small = logo.resize((int(WIN_W * 0.36), int(WIN_H * 0.36)), Image.LANCZOS)
    # sticker x positions: wander around the window's middle
    xs = [W / 2 + rng.uniform(-0.22, 0.22) * WIN_W for _ in range(n_shots + 1)]
    hover_y = WIN_Y - 40                     # sticker bottom sits a little above the window
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
            if k == 0 and t < cuts[0]:
                # opener: checkerboard dissolve into the first shot during the pre-roll
                p = t / max(cuts[0], 1e-6)
                frame = shots[0].frame(0)
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
        proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
        if fi % 48 == 0:
            print(f"  {t:5.2f}s / {end_t:.2f}s", file=sys.stderr)
    proc.stdin.close()
    proc.wait()
    print("done:", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
