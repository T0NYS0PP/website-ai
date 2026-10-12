#!/usr/bin/env python3
"""
Build the 30 s soundtrack for the TWO film and the word-timing file for the renderer.

Inputs (all under --audio DIR):
  vo_take.mp3           the chosen ElevenLabs voice-over take (one continuous read)
  vo_words.json         Scribe transcript of that take: {"words":[{"text","start","end"}, ...]}
  music.mp3             the 30 s music bed
Outputs:
  DIR/mix.wav           the finished soundtrack (-14 LUFS, TP -1 dB)
  DIR/vo_timing.json    absolute on-screen reveal times per phrase, consumed by render_two_30s.py

The VO is cut into its six sentences (seven segments, "but something intentional," and
"made with purpose." are separate) and each segment is placed on the timeline at the
times in PLACEMENT, leaving room for the real-footage beats. Everything goes through a
1970s-radio chain: band-limited, compressed, lightly saturated, mono, faint hiss.
"""
import argparse
import json
import os
import re
import subprocess
import sys

# segment boundaries measured on the take (seconds), and where each lands in the film
PHRASES = [
    ("p1", "TWO began with one question:"),
    ("p2", "what does it really mean to create?"),
    ("p3", "Not clothes for the sake of clothes."),
    ("p4a", "but something intentional,"),
    ("p4b", "made with purpose."),
    ("p5", "Each piece carries that search."),
    ("p6", "I hope it resonates with you too."),
]
PLACEMENT = {"p1": 0.8, "p2": 4.2, "p3": 9.0, "p4a": 12.2, "p4b": 13.9, "p5": 18.2, "p6": 20.9}
LEAD = 0.083         # text appears two frames before the word is heard
TOTAL = 30.0
MUSIC_DELAY = 2.2    # the bed enters under the end of the first line; its last chord then rings under the end card


def run(cmd):
    subprocess.run(cmd, check=True)


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def align_words(words):
    """Map the transcript's words onto the script phrases, in order. Returns
    {phrase_key: [(script_word, start, end), ...]} and the segment spans."""
    script = [(k, t.split()) for k, t in PHRASES]
    flat = [(k, i, w) for k, ws in script for i, w in enumerate(ws)]
    out = {k: [] for k, _ in PHRASES}
    j = 0
    for k, i, w in flat:
        # find the next transcript word that matches (fuzzy: prefix match on letters)
        target = norm(w)
        found = None
        for jj in range(j, min(j + 4, len(words))):
            tw = norm(words[jj]["text"])
            if not tw:
                continue
            if tw == target or tw.startswith(target[:4]) or target.startswith(tw[:4]):
                found = jj
                break
        if found is None:
            # fall back: take the next word-like token
            while j < len(words) and not norm(words[j]["text"]):
                j += 1
            found = min(j, len(words) - 1)
        out[k].append((w, float(words[found]["start"]), float(words[found]["end"])))
        j = found + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--music-gain", type=float, default=-21.0, help="music level in LUFS before ducking")
    args = ap.parse_args()
    d = args.audio
    vo = os.path.join(d, "vo_take.mp3")
    words = json.load(open(os.path.join(d, "vo_words.json")))["words"]
    words = [w for w in words if w.get("type", "word") == "word" or norm(w.get("text", ""))]
    aligned = align_words(words)

    # ---- timing file for the renderer
    timing = {"phrases": []}
    segs = []
    for k, text in PHRASES:
        ws = aligned[k]
        seg_start = ws[0][1]
        seg_end = ws[-1][2]
        place = PLACEMENT[k]
        timing["phrases"].append({
            "key": k, "text": text, "start": place, "end": place + (seg_end - seg_start),
            "words": [{"w": w, "t": round(place + (s - seg_start) - LEAD, 3)} for w, s, e in ws],
        })
        segs.append((k, seg_start, seg_end, place))
    json.dump(timing, open(os.path.join(d, "vo_timing.json"), "w"), indent=1)
    for p in timing["phrases"]:
        print(f'{p["key"]:4s} {p["start"]:6.2f}-{p["end"]:6.2f}  ' + " ".join(f'{w["w"]}@{w["t"]}' for w in p["words"]), file=sys.stderr)

    # ---- 1970s radio chain on the whole take, then cut + place segments
    radio = ("aformat=channel_layouts=mono,"
             "highpass=f=230:p=2,lowpass=f=4600:p=2,"
             "acompressor=threshold=-18dB:ratio=6:attack=10:release=120:makeup=5,"
             "equalizer=f=380:t=q:w=1.0:g=1.5,equalizer=f=1900:t=q:w=1.1:g=2.5,equalizer=f=3400:t=q:w=1.5:g=1.0,"
             "asoftclip=type=tanh:threshold=0.55:output=0.9,"
             "lowpass=f=5200:p=2,alimiter=limit=0.9:attack=3:release=60")
    vo_radio = os.path.join(d, "vo_radio.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", vo, "-af", radio, "-ar", "48000", vo_radio])

    # each segment: cut with handles, short fades, delay to its place
    inputs, filt, tags = [], [], []
    for n, (k, s0, s1, place) in enumerate(segs):
        pre, post = 0.10, 0.18
        a = max(0.0, s0 - pre)
        dur = (s1 + post) - a
        delay_ms = int(round((place - (s0 - a)) * 1000))
        inputs += ["-i", vo_radio]
        filt.append(f"[{n}:a]atrim=start={a:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:d=0.04,afade=t=out:st={dur-0.08:.3f}:d=0.08,adelay={delay_ms}|{delay_ms}[v{n}]")
        tags.append(f"[v{n}]")
    nvo = len(segs)
    filt.append("".join(tags) + f"amix=inputs={nvo}:normalize=0,apad=whole_dur={TOTAL}[vo]")
    vo_track = os.path.join(d, "vo_track.wav")
    run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", ";".join(filt), "-map", "[vo]",
         "-t", str(TOTAL), "-ar", "48000", "-ac", "1", vo_track])

    # ---- music: trim to 30 s, gentle tail, level, duck under the voice
    music = os.path.join(d, "music.mp3")
    music_track = os.path.join(d, "music_track.wav")
    dms = int(round(MUSIC_DELAY * 1000))
    run(["ffmpeg", "-v", "error", "-y", "-i", music, "-af",
         f"atrim=0:{TOTAL - MUSIC_DELAY},asetpts=PTS-STARTPTS,afade=t=in:d=0.5,"
         f"loudnorm=I={args.music_gain}:TP=-3:LRA=9,aformat=channel_layouts=stereo,adelay={dms}|{dms},"
         f"apad=whole_dur={TOTAL},afade=t=out:st={TOTAL-0.4}:d=0.4",
         "-ar", "48000", music_track])

    # ---- radio texture: static burst at the opener + faint hiss bed
    tex = os.path.join(d, "texture.wav")
    run(["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"anoisesrc=color=white:seed=7:d={TOTAL}:r=48000",
         "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=3:d={TOTAL}:r=48000",
         "-filter_complex",
         "[0:a]bandpass=f=1400:w=900,atrim=0:0.55,asetpts=PTS-STARTPTS,"
         "afade=t=in:d=0.02,afade=t=out:st=0.12:d=0.3,volume=-17dB,apad=whole_dur=30[burst];"
         "[1:a]highpass=f=250,lowpass=f=4500,volume=-50dB[hiss];"
         "[burst][hiss]amix=inputs=2:normalize=0,aformat=channel_layouts=mono[tex]",
         "-map", "[tex]", "-t", str(TOTAL), tex])

    # ---- final mix: duck music with the voice as sidechain, sum, loudness-normalise
    mix = os.path.join(d, "mix.wav")
    run(["ffmpeg", "-v", "error", "-y", "-i", vo_track, "-i", music_track, "-i", tex,
         "-filter_complex",
         "[0:a]asplit=2[vo_sc][vo_main];"
         "[1:a][vo_sc]sidechaincompress=threshold=0.02:ratio=4:attack=80:release=500:makeup=1:level_sc=4[duck];"
         "[vo_main]aformat=channel_layouts=stereo,volume=0dB[vo2];"
         "[2:a]aformat=channel_layouts=stereo[tex2];"
         "[vo2][duck][tex2]amix=inputs=3:normalize=0,loudnorm=I=-14:TP=-1:LRA=11,aformat=sample_fmts=s16:sample_rates=48000[out]",
         "-map", "[out]", "-t", str(TOTAL), mix])
    print("wrote", mix, file=sys.stderr)


if __name__ == "__main__":
    main()
