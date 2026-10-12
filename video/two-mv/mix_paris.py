#!/usr/bin/env python3
"""
Soundtrack for the vertical beat-cut montage: the beat plus small synthesized
sticker sounds (a pop when a sticker appears, a whoosh-thud when it drops on the cut).

  python mix_paris.py --music paris/beat.mp3 --beats paris/beats.json --out paris/mix.wav
"""
import argparse
import json
import re
import struct
import subprocess

import numpy as np

SR = 48000


def decode(path, mono=False):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-acodec", "pcm_f32le",
                          "-ac", "1" if mono else "2", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    return a if mono else a.reshape(-1, 2)


def write_wav(path, data):
    data = np.asarray(data, np.float32)
    ch = 1 if data.ndim == 1 else data.shape[1]
    payload = data.tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, ch, SR, SR * ch * 4, ch * 4, 32)
    hdr += b"data" + struct.pack("<I", len(payload))
    open(path, "wb").write(hdr + payload)


def pop(rng):
    """A short soft 'pop': pitched blip with a fast decay."""
    n = int(0.07 * SR)
    t = np.arange(n) / SR
    f = 900 * np.exp(-t / 0.02) + 320
    env = np.exp(-t / 0.018)
    return (0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env).astype(np.float32)


def whoosh_thud(rng):
    """Falling sticker: a short descending noise whoosh then a low thud on landing."""
    n1 = int(0.12 * SR)
    t = np.arange(n1) / SR
    noise = rng.standard_normal(n1).astype(np.float32)
    # crude band sweep: mix of two one-pole lowpass outputs
    out = np.zeros(n1, np.float32)
    y = 0.0
    for i in range(n1):
        a = 0.25 - 0.22 * (i / n1)
        y = y + a * (noise[i] - y)
        out[i] = y
    w = out * np.hanning(n1) * 0.9
    n2 = int(0.14 * SR)
    t2 = np.arange(n2) / SR
    thud = (np.sin(2 * np.pi * (70 * np.exp(-t2 / 0.05) + 45) * t2) * np.exp(-t2 / 0.045)).astype(np.float32)
    seg = np.zeros(n1 + n2, np.float32)
    seg[:n1] += w
    seg[n1 - int(0.02 * SR):n1 - int(0.02 * SR) + n2] += 0.9 * thud
    return seg


def measure_lufs(path):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    tail = out[out.rfind("Integrated loudness"):]
    return float(re.search(r"I:\s*(-?[\d.]+) LUFS", tail).group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", required=True)
    ap.add_argument("--beats", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    beats = json.load(open(args.beats))
    cuts, end = beats["cuts"], beats["end"]
    n = int(end * SR)
    rng = np.random.default_rng(5)

    music = decode(args.music)
    track = np.zeros((n, 2), np.float32)
    m = min(len(music), n)
    track[:m] = music[:m]
    fo = int(0.8 * SR)
    track[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None] ** 1.5

    sfx = np.zeros(n, np.float32)
    for k in range(len(cuts) - 1):
        # pop 0.10 s after the cut (sticker appears)
        i = int((cuts[k] + 0.10) * SR)
        p = pop(rng)
        sfx[i:i + len(p)] += p[:n - i]
        # whoosh starting 0.12 s before the next cut, thud on the cut
        j = int((cuts[k + 1] - 0.12) * SR)
        w = whoosh_thud(rng)
        sfx[j:j + len(w)] += w[:n - j]
    sfx_db = -16.0
    mix = track + (sfx * 10 ** (sfx_db / 20))[:, None]
    fz = int(0.3 * SR)
    mix[-fz:] *= np.linspace(1, 0, fz, dtype=np.float32)[:, None]
    pre = args.out + ".pre.wav"
    write_wav(pre, mix)
    I = measure_lufs(pre)
    trim = -14.0 - I
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", pre, "-af",
                    f"volume={trim:.2f}dB,alimiter=limit=0.891:attack=5:release=50:level=false,aformat=sample_fmts=s16",
                    "-ar", str(SR), args.out], check=True)
    print(f"premix {I:.1f} LUFS -> trim {trim:+.1f} dB; mix {measure_lufs(args.out):.1f} LUFS -> {args.out}")
    subprocess.run(["rm", "-f", pre])


if __name__ == "__main__":
    main()
