#!/usr/bin/env python3
"""
Find the beat grid of a music file and write the cut list for render_two_paris.py.

  python beats.py paris/music.mp3 paris/beats.json --shots 18 [--start-beat 0] [--tail 2.2]

Kick-band onsets -> tempo by autocorrelation (60-180 bpm) -> phase by best onset alignment.
cuts[k] is the start of shot k (k = 0..shots-1) and cuts[shots] is where the logo lands;
"end" is the film length (logo landing + tail).
"""
import argparse
import json
import subprocess
import sys

import numpy as np

SR = 22050


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def onset_strength(x, lo=35, hi=160, hop=128, win=1024):
    n = (len(x) - win) // hop
    f = np.fft.rfftfreq(win, 1 / SR)
    band = (f >= lo) & (f < hi)
    env = np.empty(n, np.float32)
    w = np.hanning(win)
    for i in range(n):
        seg = x[i * hop:i * hop + win] * w
        env[i] = np.log1p(np.abs(np.fft.rfft(seg))[band].sum())
    o = np.maximum(0, np.diff(env, prepend=env[0]))
    return o, SR / hop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("music")
    ap.add_argument("out")
    ap.add_argument("--shots", type=int, default=18)
    ap.add_argument("--start-beat", type=int, default=0, help="skip this many beats before the first cut")
    ap.add_argument("--tail", type=float, default=2.2, help="seconds the end card holds after the logo lands")
    ap.add_argument("--bpm", type=float, help="force the tempo instead of detecting it")
    args = ap.parse_args()

    x = decode(args.music)
    o, fps = onset_strength(x)
    o = (o - o.mean()) / (o.std() + 1e-9)
    if args.bpm:
        period = 60.0 / args.bpm
    else:
        ac = np.correlate(o, o, "full")[len(o) - 1:]
        lag = np.arange(len(ac)) / fps
        m = (lag > 60 / 180) & (lag < 60 / 60)
        period = lag[m][np.argmax(ac[m])]
    # refine the period by maximising summed onset strength on the grid, then find the phase
    best = (None, -1)
    for p in np.linspace(period * 0.97, period * 1.03, 61):
        for ph in np.linspace(0, p, 48, endpoint=False):
            grid = np.arange(ph, len(x) / SR, p)
            idx = np.clip((grid * fps).astype(int), 0, len(o) - 1)
            s = o[idx].sum()
            if s > best[1]:
                best = ((p, ph), s)
    p, ph = best[0]
    bpm = 60.0 / p
    beats = np.arange(ph, len(x) / SR, p)
    # strongest beats = downbeats candidates (report only)
    idx = np.clip((beats * fps).astype(int), 0, len(o) - 1)
    strong = beats[np.argsort(o[idx])[::-1][:6]]
    print(f"tempo {bpm:.1f} bpm, period {p:.3f} s, phase {ph:.3f} s; beats {len(beats)}; strongest at {np.sort(strong).round(2).tolist()}", file=sys.stderr)
    cuts = beats[args.start_beat:args.start_beat + args.shots + 1]
    if len(cuts) < args.shots + 1:
        sys.exit("not enough beats in the music for that many shots")
    end = float(cuts[-1] + args.tail)
    json.dump({"bpm": round(bpm, 2), "period": round(float(p), 4), "phase": round(float(ph), 4),
               "cuts": [round(float(c), 4) for c in cuts], "end": round(end, 3)}, open(args.out, "w"), indent=1)
    print(f"cuts {cuts[0]:.2f} .. {cuts[-1]:.2f} s, end {end:.2f} s -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
