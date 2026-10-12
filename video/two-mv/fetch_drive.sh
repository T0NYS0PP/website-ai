#!/usr/bin/env bash
# Download the link-shared "TWO MV" clips into ./footage/ (ids in clips.txt).
# Needs the environment to allow drive.google.com and drive.usercontent.google.com.
# Usage: ./fetch_drive.sh            # all clips in clips.txt
#        ./fetch_drive.sh 07 04 01   # only these
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p footage
want="$*"
while IFS=$'\t' read -r id name; do
  [[ -z "$id" || "$id" == \#* ]] && continue
  if [[ -n "$want" ]] && ! grep -qw "${name%.mov}" <<<"$want"; then continue; fi
  echo "fetching $name"
  curl -sSL --retry 3 -o "footage/$name" \
    "https://drive.usercontent.google.com/download?id=${id}&export=download&confirm=t"
  ls -la "footage/$name"
done < clips.txt
