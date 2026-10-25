#!/usr/bin/env bash
# Kiosk launcher (Linux). Auto-login on tty1 runs this (set up by setup.sh):
#   1. pulls the latest version from GitHub (skipped quietly when offline)
#   2. runs the game full screen on a bare X server (xinit, no desktop), restarting it if it crashes
#      (pygame's SDL has no native Wayland support, and cage's Xwayland crashed under it)
# Ctrl+Q in the game stops the loop and leaves a shell on tty1 for maintenance.
# Logs: logs/console.log and logs/game_errors.log

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/console.log"
log() { echo "$(date -Is)  $*" >> "$LOG"; }
cd "$REPO_DIR" || exit 1
log "---- console start ----"

# 1. Update. GIT_TERMINAL_PROMPT=0 so an access problem fails fast instead of waiting for input.
export GIT_TERMINAL_PROMPT=0
req_before="$(sha256sum requirements.txt)"
for try in 1 2 3 4 5; do
    if out="$(timeout 20 git pull --ff-only 2>&1)"; then
        log "update: $out"
        break
    fi
    log "update try $try failed: $out"
    sleep 3
done
if [ "$(sha256sum requirements.txt)" != "$req_before" ]; then
    log "requirements.txt changed: installing packages"
    .venv/bin/pip install -q -r requirements.txt >> "$LOG" 2>&1
fi

# The game connects to the phone itself (adb forward + DroidCam app); start adb early.
adb start-server >/dev/null 2>&1 || true

# 2. Game loop. Exit code 10 means Ctrl+Q: stop and hand tty1 over to a shell. Anything else
#    (an update stopping the game, a crash) starts it again.
while true; do
    log "starting game"
    rm -f "$LOG_DIR/.game_exit"
    xinit "$REPO_DIR/deploy/linux/run_game.sh" -- :0 vt1 -keeptty -nolisten tcp >> "$LOG_DIR/xorg.log" 2>&1
    code="$(cat "$LOG_DIR/.game_exit" 2>/dev/null || echo 1)"
    log "game exited with code $code"
    [ "$code" -eq 10 ] && break
    sleep 3
done
log "---- console stopped (Ctrl+Q pressed) ----"
exec bash  # non-login shell: doesn't re-run .bash_profile, so the console doesn't restart
