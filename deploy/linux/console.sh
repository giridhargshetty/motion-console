#!/usr/bin/env bash
# Kiosk launcher (Linux). Auto-login on tty1 runs this (set up by setup.sh):
#   1. pulls the latest version from GitHub (skipped quietly when offline)
#   2. runs the game full screen inside cage, restarting it if it crashes
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

# 2. Game loop. Exit code 0 means Ctrl+Q: stop and hand tty1 over to a shell.
while true; do
    log "starting game"
    cage -s -- "$REPO_DIR/.venv/bin/python" "$REPO_DIR/prototype/fruit_slice.py" 2>> "$LOG_DIR/game_errors.log"
    code=$?
    log "game exited with code $code"
    [ "$code" -eq 0 ] && break
    sleep 3
done
log "---- console stopped (Ctrl+Q pressed) ----"
exec bash  # non-login shell: doesn't re-run .bash_profile, so the console doesn't restart
