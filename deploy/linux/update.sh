#!/usr/bin/env bash
# Update a running console without a reboot or password (run over SSH as the console user):
#     bash ~/motion-console/deploy/linux/update.sh
# Pulls the latest code, then stops the game; console.sh starts it again with the new code.
# If the console was stopped (Ctrl+Q), restarts the tty1 session so it comes back up.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_DIR"
git pull --ff-only
if [ "$(sha256sum requirements.txt)" != "$(git show HEAD@{1}:requirements.txt 2>/dev/null | sha256sum)" ]; then
    .venv/bin/pip install -q -r requirements.txt
fi
if pgrep -f "deploy/linux/[c]onsole.sh" >/dev/null; then
    pkill -f "[.]venv/bin/python $REPO_DIR/prototype/fruit_slice.py" || true
    echo "game restarting with $(git log --oneline -1)"
else
    pkill -HUP -t tty1 -u "$(id -un)" || true  # hang up the tty1 shell: auto-login starts the console again
    echo "console restarting with $(git log --oneline -1)"
fi
