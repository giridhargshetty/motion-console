#!/usr/bin/env bash
# One-time setup of an Ubuntu Server 24.04 mini PC as a motion console (kiosk).
# Run on the mini PC, from inside the cloned repo, as the user who will own the console:
#     bash deploy/linux/setup.sh
# Installs packages, builds the Python environment, downloads the pose models, and makes
# the box boot straight into the game: auto-login on tty1 -> deploy/linux/console.sh -> cage.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
USER_NAME="$(id -un)"
step() { printf '\n==> %s\n' "$*"; }

step "System packages"
sudo apt-get update
# cage: minimal full-screen Wayland compositor (one app, no desktop); xwayland lets SDL use X11.
# android-sdk-platform-tools-common: udev rules so adb can reach the phone without root.
# network-manager: lets the game's Wi-Fi screen scan and join networks (nmcli).
sudo apt-get install -y git curl python3-venv python3-pip adb android-sdk-platform-tools-common \
    cage xwayland libgl1 libglib2.0-0 fonts-dejavu-core alsa-utils network-manager
getent group netdev >/dev/null || sudo groupadd netdev
for group in plugdev video render input audio netdev; do
    getent group "$group" >/dev/null && sudo usermod -aG "$group" "$USER_NAME"
done

step "Wi-Fi managed by NetworkManager (so the console can change it)"
# Ubuntu Server uses systemd-networkd; hand networking to NetworkManager. Networks already set up
# in the installer (in /etc/netplan) carry over. Applied at the reboot at the end, not now, so an
# SSH session over the network isn't cut mid-setup.
sudo tee /etc/netplan/90-motion-console-nm.yaml >/dev/null <<'EOF'
network:
  version: 2
  renderer: NetworkManager
EOF
sudo chmod 600 /etc/netplan/90-motion-console-nm.yaml
sudo systemctl enable NetworkManager
# Members of netdev (the console user) may scan and join Wi-Fi without a password prompt.
sudo tee /etc/polkit-1/rules.d/50-motion-console-network.rules >/dev/null <<'EOF'
polkit.addRule(function (action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.isInGroup("netdev")) {
        return polkit.Result.YES;
    }
});
EOF

step "Tailscale (remote access; reconnects by itself whenever there's internet)"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled
if ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale needs a one-time sign-in: run  sudo tailscale up  and open the link it prints."
fi

step "Python environment (a few minutes)"
cd "$REPO_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -c "import sys; sys.path.insert(0, 'prototype'); import player; player.get_model('full'); player.get_model('lite')"
if [ ! -f prototype/config.local.toml ]; then
    printf '# Settings for this machine only (not in git). Overrides prototype/config.toml.\n[game]\nfullscreen = true\n' \
        > prototype/config.local.toml
fi
chmod +x deploy/linux/console.sh

step "Auto-login on tty1"
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER_NAME --noclear %I \$TERM
EOF

step "Start the console when tty1 logs in"
MARK="# motion-console kiosk"
if ! grep -q "$MARK" "$HOME/.bash_profile" 2>/dev/null; then
    # A .bash_profile stops bash reading .profile, so keep .profile's settings.
    [ -f "$HOME/.bash_profile" ] || echo '[ -f ~/.profile ] && . ~/.profile' > "$HOME/.bash_profile"
    cat >> "$HOME/.bash_profile" <<EOF

$MARK (SSH logins are unaffected)
if [ "\$(tty)" = "/dev/tty1" ]; then
    exec "$REPO_DIR/deploy/linux/console.sh"
fi
EOF
fi

step "Faster, quieter boot"
# Don't hold boot for up to 2 minutes waiting for the network; console.sh retries the update itself.
sudo systemctl mask systemd-networkd-wait-online.service NetworkManager-wait-online.service
# No boot menu delay, no console blanking on the TV.
sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=0/' /etc/default/grub
if ! grep -q 'consoleblank=0' /etc/default/grub; then
    sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 consoleblank=0"/' /etc/default/grub
fi
sudo update-grub

step "Done. Reboot to start the console:  sudo reboot"
