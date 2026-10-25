#!/usr/bin/env bash
# X client started by console.sh through xinit: the only program on the X display.
# Keeps the TV from blanking, runs the game, and records its exit code for console.sh
# (xinit itself doesn't pass the client's exit code on).
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
xset s off s noblank -dpms 2>/dev/null || true
# A 4K TV defaults to 3840x2160 at 30 Hz: far more pixels than needed and a choppy 30 Hz.
# Ask for 1080p at 60 Hz (the game draws at 720p and the GPU scales it up anyway).
out="$(xrandr 2>/dev/null | awk '/ connected/ {print $1; exit}')"
if [ -n "$out" ]; then
    xrandr --output "$out" --mode 1920x1080 --rate 60 2>/dev/null \
        || xrandr --output "$out" --mode 1920x1080 2>/dev/null || true
fi
"$REPO_DIR/.venv/bin/python" "$REPO_DIR/prototype/fruit_slice.py" 2>> "$REPO_DIR/logs/game_errors.log"
echo $? > "$REPO_DIR/logs/.game_exit"
