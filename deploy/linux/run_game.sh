#!/usr/bin/env bash
# X client started by console.sh through xinit: the only program on the X display.
# Keeps the TV from blanking, runs the game, and records its exit code for console.sh
# (xinit itself doesn't pass the client's exit code on).
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
xset s off s noblank -dpms 2>/dev/null || true
"$REPO_DIR/.venv/bin/python" "$REPO_DIR/prototype/fruit_slice.py" 2>> "$REPO_DIR/logs/game_errors.log"
echo $? > "$REPO_DIR/logs/.game_exit"
