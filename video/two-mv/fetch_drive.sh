#!/usr/bin/env bash
# Download link-shared Google Drive files into ./footage/
# Usage: ./fetch_drive.sh <fileId> <outname.mov> [...]
# Requires the environment to allow drive.google.com and drive.usercontent.google.com.
set -euo pipefail
mkdir -p footage
while [ $# -ge 2 ]; do
  id="$1"; out="footage/$2"; shift 2
  echo "fetching $out"
  curl -sSL -o "$out" \
    "https://drive.usercontent.google.com/download?id=${id}&export=download&confirm=t"
  ls -la "$out"
done
