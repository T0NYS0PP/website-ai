#!/usr/bin/env bash
# For each clip in footage/: a 480p proxy (proxies/NAME.mp4) and a contact sheet
# (proxies/NAME_sheet.jpg, one frame every 2 s, with timestamps) to choose shots.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p proxies
for f in footage/*.mov footage/*.mp4; do
  [ -e "$f" ] || continue
  n=$(basename "${f%.*}")
  [ -e "proxies/$n.mp4" ] || ffmpeg -v error -y -i "$f" -vf "scale=-2:480" -c:v libx264 -preset fast -crf 24 -pix_fmt yuv420p -an -movflags +faststart "proxies/$n.mp4"
  ffmpeg -v error -y -i "proxies/$n.mp4" -vf "fps=1/2,scale=320:-1,drawtext=fontfile=/usr/share/fonts/opentype/inter/Inter-SemiBold.otf:text='%{pts\:hms}':x=8:y=8:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6,tile=6x6" -frames:v 1 "proxies/${n}_sheet.jpg"
  echo "$n -> $(stat -c %s proxies/$n.mp4) bytes"
done
