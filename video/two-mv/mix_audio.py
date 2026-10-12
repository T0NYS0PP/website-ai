#!/usr/bin/env python3
"""
Build the 30 s soundtrack for the TWO film and the word-timing file for the renderer.

Inputs (all under --audio DIR):
  vo_take.mp3           the chosen ElevenLabs voice-over take (one continuous read)
  vo_words.json         Scribe transcript of that take: {"words":[{"text","start","end"}, ...]}
  music.mp3             the 30 s music bed
Outputs:
  DIR/mix.wav           the finished soundtrack (-14 LUFS integrated, -1 dBTP)
  DIR/vo_timing.json    absolute on-screen reveal times per phrase, consumed by render_two_30s.py

Design (numbers from measuring the stems):
  * The VO is cut into its seven segments and placed at PLACEMENT, leaving the
    music-only gaps for the real-footage beats. 1970s-radio chain: band-limited,
    6:1 compression, tape-style soft clip, mono.
  * Phrase-initial word onsets are snapped to the audible attack (Scribe starts
    35-95 ms late); on-screen words lead the audible onset by LEAD.
  * The bed is ducked by a deterministic -8 dB envelope built from the phrase
    windows (a sidechain compressor either muted it or pumped), with static
    gains and one final trim to -14 LUFS: voice ~-13, bed solo ~-17, bed under
    voice ~-25 LUFS short-term.
  * Radio texture: a static burst and a tuning click under the opener, a faint
    constant floor, hiss that rises with the voice, and a 50 ms tick on each cut.
  * MUSIC_DELAY puts the bed's accent grid (69.8 bpm) on the picture cuts and its
    last chord on the end card.
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

import numpy as np

SR = 48000
TOTAL = 30.0
MUSIC_DELAY = 1.07       # bed accents at 0.79 + k*1.716 s then land 0-80 ms after the cuts
LEAD = 0.10              # on-screen word leads the audible onset by this much
PHRASES = [
    ("p1", "TWO began with one question:"),
    ("p2", "what does it really mean to create?"),
    ("p3", "Not clothes for the sake of clothes."),
    ("p4a", "but something intentional,"),
    ("p4b", "made with purpose."),
    ("p5", "Each piece carries that search."),
    ("p6", "I hope it resonates with you too."),
]
PLACEMENT = {"p1": 0.8, "p2": 4.2, "p3": 8.9, "p4a": 12.35, "p4b": 14.05, "p5": 17.5, "p6": 20.9}
CUTS = [0.6, 2.9, 4.0, 6.97, 8.68, 12.12, 15.55, 17.30, 20.7, 24.13, 27.56]   # picture cuts (render_two_30s.T)

VO_GAIN_DB = 3.4         # radio stem measured -16.4 LUFS -> ~-13
BED_GAIN_DB = -0.5       # music.mp3 measured -16.8 LUFS -> ~-17.3 solo
DUCK_DB = -8.0


def run(cmd):
    subprocess.run(cmd, check=True)


def decode(path, sr=SR, mono=True):
    """Decode any audio file to float32 numpy via ffmpeg."""
    ac = "1" if mono else "2"
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-acodec", "pcm_f32le",
                          "-ac", ac, "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    return a if mono else a.reshape(-1, 2)


def write_wav(path, data, sr=SR):
    """Write float32 PCM WAV (mono (n,) or stereo (n,2))."""
    data = np.asarray(data, np.float32)
    ch = 1 if data.ndim == 1 else data.shape[1]
    payload = data.tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, ch, sr, sr * ch * 4, ch * 4, 32)
    hdr += b"data" + struct.pack("<I", len(payload))
    with open(path, "wb") as f:
        f.write(hdr + payload)


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_words(words):
    """Map the transcript's words onto the script phrases, in order."""
    flat = [(k, w) for k, t in PHRASES for w in t.split()]
    out = {k: [] for k, _ in PHRASES}
    j = 0
    for k, w in flat:
        target = norm(w)
        found = None
        for jj in range(j, min(j + 4, len(words))):
            tw = norm(words[jj]["text"])
            if tw and (tw == target or tw.startswith(target[:4]) or target.startswith(tw[:4])):
                found = jj
                break
        if found is None:
            while j < len(words) and not norm(words[j]["text"]):
                j += 1
            found = min(j, len(words) - 1)
        out[k].append([w, float(words[found]["start"]), float(words[found]["end"])])
        j = found + 1
    return out


def snap_onsets(aligned, take):
    """Phrase-initial starts: first 5 ms frame above -45 dBFS within 150 ms before Scribe's start."""
    hop = int(SR * 0.005)
    n = len(take) // hop
    rms = np.sqrt((take[:n * hop].reshape(n, hop) ** 2).mean(1))
    db = 20 * np.log10(rms + 1e-9)
    for k, ws in aligned.items():
        s = ws[0][1]
        i1 = int(s / 0.005)
        i0 = max(0, i1 - 30)
        above = np.nonzero(db[i0:i1 + 1] > -45)[0]
        if len(above):
            new = (i0 + above[0]) * 0.005
            print(f"  {k}: onset {s:.3f} -> {new:.3f} ({(new - s) * 1000:+.0f} ms)", file=sys.stderr)
            ws[0][1] = new
    return aligned


def envelope(windows, total, down=0.15, up=0.8, pre=0.2, post=0.3, depth_db=DUCK_DB):
    """Gain envelope: 1 outside the (merged) phrase windows, 10^(depth/20) inside, raised-cosine ramps."""
    n = int(total * SR)
    g = np.ones(n, np.float32)
    low = 10 ** (depth_db / 20)
    merged = []
    for a, b in sorted(windows):
        a, b = a - pre, b + post
        if merged and a - merged[-1][1] < 0.8:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    for a, b in merged:
        i0, i1 = int(max(0, a) * SR), int(min(total, b) * SR)
        g[i0:i1] = low
        nd = int(down * SR)
        r = np.linspace(0, 1, nd, dtype=np.float32)
        s0 = max(0, i0 - nd)
        g[s0:i0] = 1 - (1 - low) * (0.5 - 0.5 * np.cos(np.pi * r))[nd - (i0 - s0):]
        nu = int(up * SR)
        r = np.linspace(0, 1, nu, dtype=np.float32)
        s1 = min(n, i1 + nu)
        g[i1:s1] = low + (1 - low) * (0.5 - 0.5 * np.cos(np.pi * r))[:s1 - i1]
    return g, merged


def gate(windows, total, pre=0.15, post=0.4, ramp=0.08):
    """0/1 envelope opening around the phrase windows (for the hiss)."""
    n = int(total * SR)
    g = np.zeros(n, np.float32)
    for a, b in windows:
        i0, i1 = int(max(0, a - pre) * SR), int(min(total, b + post) * SR)
        g[i0:i1] = 1
    k = int(ramp * SR)
    if k > 1:
        kern = np.hanning(k).astype(np.float32)
        kern /= kern.sum()
        g = np.convolve(g, kern, mode="same").astype(np.float32)
    return g


def measure_lufs(path):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    tail = out[out.rfind("Integrated loudness"):]
    I = float(re.search(r"I:\s*(-?[\d.]+) LUFS", tail).group(1))
    tp = float(re.search(r"Peak:\s*(-?[\d.]+) dBFS", tail).group(1))
    return I, tp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    args = ap.parse_args()
    d = args.audio
    vo = os.path.join(d, "vo_take.mp3")
    words = [w for w in json.load(open(os.path.join(d, "vo_words.json")))["words"]
             if w.get("type", "word") == "word" and norm(w.get("text", ""))]
    take = decode(vo)
    aligned = snap_onsets(align_words(words), take)

    # ---- timing file for the renderer + phrase windows on the timeline
    timing = {"phrases": []}
    segs, windows = [], []
    for k, text in PHRASES:
        ws = aligned[k]
        s0, s1 = ws[0][1], ws[-1][2]
        place = PLACEMENT[k]
        timing["phrases"].append({
            "key": k, "text": text, "start": place, "end": place + (s1 - s0),
            "words": [{"w": w, "t": round(place + (s - s0) - LEAD, 3)} for w, s, e in ws],
        })
        segs.append((k, s0, s1, place))
        windows.append((place, place + (s1 - s0)))
    json.dump(timing, open(os.path.join(d, "vo_timing.json"), "w"), indent=1)
    for p in timing["phrases"]:
        print(f'{p["key"]:4s} {p["start"]:6.2f}-{p["end"]:6.2f}  ' + " ".join(f'{w["w"]}@{w["t"]}' for w in p["words"]), file=sys.stderr)

    # ---- 1970s radio chain on the whole take (mono, 48 kHz)
    radio = ("aformat=channel_layouts=mono,"
             "highpass=f=230:p=2,lowpass=f=4600:p=2,"
             "acompressor=threshold=-18dB:ratio=6:attack=10:release=120:makeup=5,"
             "equalizer=f=380:t=q:w=1.0:g=1.5,equalizer=f=1900:t=q:w=1.1:g=2.5,equalizer=f=3400:t=q:w=1.5:g=1.0,"
             "asoftclip=type=tanh:threshold=0.55:output=0.9,"
             "lowpass=f=5200:p=2,alimiter=limit=0.9:attack=3:release=60")
    vo_radio = os.path.join(d, "vo_radio.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", vo, "-af", radio, "-ar", str(SR), vo_radio])
    vr = decode(vo_radio)

    # ---- cut the segments with handles and place them
    n = int(TOTAL * SR)
    vo_track = np.zeros(n, np.float32)
    pre, post, fi, fo = 0.22, 0.28, 0.10, 0.15
    for k, s0, s1, place in segs:
        a = max(0.0, s0 - pre)
        b = min(len(vr) / SR, s1 + post)
        seg = vr[int(a * SR):int(b * SR)].copy()
        ni, no = int(fi * SR), int(fo * SR)
        seg[:ni] *= np.linspace(0, 1, ni, dtype=np.float32)
        seg[-no:] *= np.linspace(1, 0, no, dtype=np.float32)
        start = int((place - (s0 - a)) * SR)
        vo_track[start:start + len(seg)] += seg
    vo_track *= 10 ** (VO_GAIN_DB / 20)

    # ---- music bed: delayed, static gain, ducked by the phrase envelope
    bed = decode(os.path.join(d, "music.mp3"), mono=False)
    bed_track = np.zeros((n, 2), np.float32)
    off = int(MUSIC_DELAY * SR)
    m = min(len(bed), n - off)
    bed_track[off:off + m] = bed[:m]
    fade_in = int(0.5 * SR)
    bed_track[off:off + fade_in] *= np.linspace(0, 1, fade_in, dtype=np.float32)[:, None]
    fo_n = int(0.5 * SR)
    bed_track[-fo_n:] *= np.linspace(1, 0, fo_n, dtype=np.float32)[:, None]
    bed_track *= 10 ** (BED_GAIN_DB / 20)
    duck, merged = envelope(windows, TOTAL)
    print("duck windows:", [(round(a, 2), round(b, 2)) for a, b in merged], file=sys.stderr)
    bed_track *= duck[:, None]

    # ---- radio texture
    rng = np.random.default_rng(7)
    tex = np.zeros(n, np.float32)
    # static burst under the red card (0-0.56 s), band-limited white noise
    burst_n = int(0.6 * SR)
    burst = rng.standard_normal(burst_n).astype(np.float32)
    write_wav(os.path.join(d, "_burst_raw.wav"), burst)
    run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(d, "_burst_raw.wav"), "-af",
         "bandpass=f=1800:width_type=h:w=2600,afade=t=in:d=0.02,afade=t=out:st=0.42:d=0.14,volume=-17dB",
         os.path.join(d, "_burst.wav")])
    b = decode(os.path.join(d, "_burst.wav"))
    tex[:len(b)] += b
    # tuning click just before the first cut
    t = np.arange(int(0.03 * SR)) / SR
    click = (0.35 * np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.004)).astype(np.float32)
    i = int(0.59 * SR)
    tex[i:i + len(click)] += click
    # pink-ish hiss: constant faint floor + a louder band that rises with the voice
    white = rng.standard_normal(n).astype(np.float32)
    write_wav(os.path.join(d, "_hiss_raw.wav"), white)
    run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(d, "_hiss_raw.wav"), "-af",
         "highpass=f=300:p=2,lowpass=f=4500:p=2,volume=-25dB", os.path.join(d, "_hiss.wav")])
    hiss = decode(os.path.join(d, "_hiss.wav"))[:n]
    g = gate(windows, TOTAL)
    tex[:len(hiss)] += hiss * (0.18 + 0.82 * g[:len(hiss)])          # floor ~-59 dBFS, voiced ~-44
    # a 50 ms static tick on each picture cut (not where a word starts within 120 ms)
    word_starts = [w["t"] + LEAD for p in timing["phrases"] for w in p["words"]]
    for c in CUTS:
        if any(abs(c - ws) < 0.12 for ws in word_starts):
            continue
        strong = c in (0.6, 27.56)
        dur = 0.08 if strong else 0.05
        tk = rng.standard_normal(int(dur * SR)).astype(np.float32)
        write_wav(os.path.join(d, "_tick_raw.wav"), tk)
        run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(d, "_tick_raw.wav"), "-af",
             f"bandpass=f=2500:width_type=h:w=3000,afade=t=in:d=0.004,afade=t=out:st={dur-0.022:.3f}:d=0.022,"
             f"volume={-26 if strong else -30}dB", os.path.join(d, "_tick.wav")])
        tk = decode(os.path.join(d, "_tick.wav"))
        i = int(c * SR)
        tex[i:i + len(tk)] += tk[:n - i]
    # the last 0.2 s: nothing
    tex[int((TOTAL - 0.2) * SR):] = 0

    # ---- sum, trim to -14 LUFS, limit
    mix = bed_track + vo_track[:, None] + tex[:, None]
    pre_path = os.path.join(d, "_premix.wav")
    write_wav(pre_path, mix)
    I, tp = measure_lufs(pre_path)
    trim = -14.0 - I
    print(f"premix {I:.1f} LUFS, TP {tp:.1f} dBFS -> trim {trim:+.1f} dB", file=sys.stderr)
    out = os.path.join(d, "mix.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", pre_path, "-af",
         f"volume={trim:.2f}dB,alimiter=limit=0.891:attack=5:release=50:level=false,aformat=sample_fmts=s16",
         "-ar", str(SR), out])
    I2, tp2 = measure_lufs(out)
    print(f"mix {I2:.1f} LUFS, TP {tp2:.1f} dBFS -> {out}", file=sys.stderr)
    for f in os.listdir(d):
        if f.startswith("_"):
            os.remove(os.path.join(d, f))


if __name__ == "__main__":
    main()
