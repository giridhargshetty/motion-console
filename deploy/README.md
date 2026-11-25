# Mini PC as a console

Goal: plug the phone in by USB, the TV by HDMI, power on, and the game appears on the TV.
Changes are made on the laptop and pushed to GitHub; the mini PC pulls them at every start.

The mini PC runs **Ubuntu Server 24.04** as a kiosk (recommended, below). The Windows setup
further down still works if you ever need it.

## Linux kiosk (recommended)

```
laptop:  edit -> test -> git commit -> git push  ──►  GitHub (this repo, or your fork)
mini PC: power on -> auto-login tty1 -> console.sh: git pull -> xinit (bare X, full screen) -> game
                                                           game: adb -> DroidCam phone app -> pictures
```

No desktop, no login screen, no pop-ups. Ctrl+Q in the game (keyboard) leaves a shell on the TV for
maintenance; everything else is done over SSH from the laptop via Tailscale.

### Controls: no keyboard or mouse needed

Every console screen works three ways: **hands** (hover over a button ~1 s), **mouse** (click), or a
**remote with arrow keys + OK** (a USB air-mouse remote acts as mouse *and* keyboard on Linux with no
setup). The TV's own remote can't reach a PC: that needs HDMI-CEC, which PCs almost never have
(a USB-CEC adapter could add it later).

- Start-up shows a **Network** screen: Wi-Fi name, internet, remote access (Tailscale). When online it
  goes on to the game after 10 s by itself.
- **CHOOSE WI-FI** lists nearby networks; pick one, type the password on the on-screen keyboard
  (or a real keyboard), CONNECT. The menu's **WI-FI / SETTINGS** box opens the same screens later.
- Remote in the game menu: Left = Classic, Right = Survival, Down = Wi-Fi/settings, OK = start.
  Esc/Back goes back a screen; only **Ctrl+Q** quits the console.
- Tailscale starts at every boot and reconnects by itself whenever Wi-Fi is up. In the Tailscale admin
  console, turn off **key expiry** for this machine so it never needs signing in again.

### Install (you, once, about 30 minutes)

1. Download **Ubuntu Server** (24.04 LTS or newer; tested on 26.04) from ubuntu.com/download/server
   and write it to a USB stick with balenaEtcher. This erases the mini PC's disk. A network cable is
   easiest during the install; if it was installed without a network, run
   `sudo bash deploy/linux/enable_ethernet.sh` afterwards to switch on the wired port.
2. Boot the mini PC from the stick (Dell: F12 at power-on for the boot menu). In the installer:
   use the whole disk, pick a username/password, and tick **Install OpenSSH server**.
3. After the reboot, sign in on the mini PC and add it to Tailscale:
   `curl -fsSL https://tailscale.com/install.sh | sh` then `sudo tailscale up` and open the link it shows.
4. On the laptop: `ssh-copy-id <user>@<mini-pc-tailscale-name>` and type the mini PC password once.
5. BIOS (F2 at power-on): **AC Recovery = Power On**, so the box starts as soon as it gets power.

### Setup (on the box, or over SSH)

1. `git clone https://github.com/giridhargshetty/motion-console.git ~/motion-console`
   (or your own fork: the box pulls updates from wherever it was cloned from).
2. `bash ~/motion-console/deploy/linux/setup.sh` installs packages (Python 3.12 via uv, adb + phone udev rules,
   a bare X server), builds `.venv`, downloads the pose models, writes `prototype/config.local.toml`
   (fullscreen), sets auto-login on tty1 to start `deploy/linux/console.sh`, and speeds up boot.
3. Phone: plug it in, tap **Allow** on "Allow USB debugging?" (tick "Always allow"), and turn on
   Developer options -> **Stay awake**.
4. `sudo reboot`, then check `logs/console.log`, and the frame rate and pose time on the debug line (`D`).

### Updating

Push to the repo the box was cloned from; then either restart the box, or over SSH:
`bash ~/motion-console/deploy/linux/update.sh` (pulls, then restarts the game; no password or reboot).

## Windows (alternative)

```
laptop:  edit -> test -> git commit -> git push  ──►  GitHub
mini PC: power on -> auto sign-in -> console.ps1: git pull -> phone app + DroidCam -> game
```

### What happens at power-on

1. Windows signs in automatically (set up once, below).
2. The Startup shortcut runs `deploy/console.ps1`, which:
   - pulls the latest code (reinstalls packages only if `requirements.txt` changed);
   - stops the DroidCam PC client if it's running (it would take the phone's only video connection);
   - runs the game fullscreen. If it crashes, it starts again after 3 s.
3. The game connects to the phone over USB by itself (`backend = "droidcam_usb"`): it forwards a port
   with `adb`, wakes the phone and opens the DroidCam app if needed, and reads the pictures directly.
   No DroidCam PC client or virtual webcam is involved. It shows "Connecting to the camera..." with the
   reason until pictures arrive, then asks the player to stand in the middle.

**Ctrl+Q** in the game quits to the desktop for maintenance (needs a keyboard). Logs: `logs\console.log` and `logs\game_errors.log`.

### One-time setup on the mini PC

1. Copy `deploy\setup_minipc.ps1` to the mini PC (USB stick, or download it from the GitHub repo page) and run in PowerShell:
   ```
   powershell -ExecutionPolicy Bypass -File setup_minipc.ps1 -RepoUrl https://github.com/giridhargshetty/motion-console.git
   ```
   It installs Git, Python 3.12 and Google's `adb` (Android platform tools) if missing, clones to
   `%USERPROFILE%\motion-console`, installs packages, downloads the pose models, writes
   `prototype\config.local.toml` (fullscreen on), and adds the Startup shortcut.
2. **Phone:** the DroidCam app installed (Play Store), USB debugging on, and Developer options ->
   **Stay awake** on, so the screen doesn't lock while it's charging over USB. The first time you plug it
   into the mini PC, tap **Allow** on "Allow USB debugging?" with "Always allow from this computer" ticked.
   The DroidCam **PC client is not needed**; if it's installed, the launcher stops it.
3. *(Only if you use a USB webcam instead of the phone:* set `backend = "msmf"` and `index` in
   `prototype\config.local.toml`; find the index with `.venv\Scripts\python bench\bench_pose.py --list`.)
4. **Windows settings** (do these by hand):
   - Automatic sign-in: Settings -> Accounts -> Sign-in options -> turn off "Only allow Windows Hello
     sign-in", then run `netplwiz` and untick "Users must enter a user name and password". Anyone who can
     power on the box gets this account, so use an account without personal data on it.
   - Settings -> System -> Power -> Screen and sleep: **Never** when plugged in.
   - Settings -> System -> Notifications: off (no pop-ups over the game).
   - Make the TV the main display (Settings -> System -> Display).
5. **BIOS** (F2 at boot on Dell): Power Management -> **AC Recovery** = Power On, so the box starts as soon as it gets power.
6. Test: restart. The game should come up on the TV with no keyboard or mouse.
7. Check the Phase 0 gate on this machine: the game's debug line (right panel) shows fps and pose ms.
   Add the numbers to `bench/RESULTS.md`; the gate names this machine.

### Updating (Windows)

On the laptop: commit and `git push`. Next time the mini PC starts (or after Ctrl+Q + restart), it pulls the new version.
Machine-only settings stay in `prototype\config.local.toml`, which git ignores, so updates never overwrite them.

## If something goes wrong (both)

| Symptom | Check |
| --- | --- |
| "Connecting... (phone not found over USB)" | Cable plugged in? USB debugging allowed for this PC? Run `adb devices`: the phone should say `device`, not `unauthorized`. |
| "Connecting... (waiting for the DroidCam app)" | Phone unlocked? Open the DroidCam app by hand once. Is the DroidCam PC client running somewhere? It steals the connection. |
| "Connecting... (adb not found)" | Re-run setup, or `winget install -e --id Google.PlatformTools`, or set `adb` in `config.local.toml`. |
| Game doesn't start at all | `logs\console.log`, `logs\game_errors.log`; run `.venv\Scripts\python prototype\console.py` by hand to see errors. |
| Update not arriving | `logs\console.log` "update" lines; run `git pull` in the folder to see the error (sign-in, network). |
