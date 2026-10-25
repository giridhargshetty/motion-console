# Mini PC as a console

Goal: plug the phone in by USB, the TV by HDMI, power on, and the game appears on the TV.
Changes are made on the laptop and pushed to GitHub; the mini PC pulls them at every start.

```
laptop:  edit -> test -> git commit -> git push  ──►  GitHub (private repo)
mini PC: power on -> auto sign-in -> console.ps1: git pull -> phone app + DroidCam -> game
```

## What happens at power-on

1. Windows signs in automatically (set up once, below).
2. The Startup shortcut runs `deploy/console.ps1`, which:
   - pulls the latest code (reinstalls packages only if `requirements.txt` changed);
   - stops the DroidCam PC client if it's running (it would take the phone's only video connection);
   - runs the game fullscreen. If it crashes, it starts again after 3 s.
3. The game connects to the phone over USB by itself (`backend = "droidcam_usb"`): it forwards a port
   with `adb`, wakes the phone and opens the DroidCam app if needed, and reads the pictures directly.
   No DroidCam PC client or virtual webcam is involved. It shows "Connecting to the camera..." with the
   reason until pictures arrive, then asks the player to stand in the middle.

**Esc** in the game quits to the desktop for maintenance (needs a keyboard). Logs: `logs\console.log` and `logs\game_errors.log`.

## One-time setup on the mini PC

1. Copy `deploy\setup_minipc.ps1` to the mini PC (USB stick, or download it from the GitHub repo page) and run in PowerShell:
   ```
   powershell -ExecutionPolicy Bypass -File setup_minipc.ps1 -RepoUrl https://github.com/<you>/<repo>.git
   ```
   It installs Git, Python 3.12 and Google's `adb` (Android platform tools) if missing, clones to
   `%USERPROFILE%\motion-console`, installs packages, downloads the pose models, writes
   `prototype\config.local.toml` (fullscreen on), and adds the Startup shortcut.
   For a private repo, Git opens a GitHub sign-in window once and remembers it.
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

## Updating

On the laptop: commit and `git push`. Next time the mini PC starts (or after Esc + restart), it pulls the new version.
Machine-only settings stay in `prototype\config.local.toml`, which git ignores, so updates never overwrite them.

## If something goes wrong

| Symptom | Check |
| --- | --- |
| "Connecting... (phone not found over USB)" | Cable plugged in? USB debugging allowed for this PC? Run `adb devices`: the phone should say `device`, not `unauthorized`. |
| "Connecting... (waiting for the DroidCam app)" | Phone unlocked? Open the DroidCam app by hand once. Is the DroidCam PC client running somewhere? It steals the connection. |
| "Connecting... (adb not found)" | Re-run setup, or `winget install -e --id Google.PlatformTools`, or set `adb` in `config.local.toml`. |
| Game doesn't start at all | `logs\console.log`, `logs\game_errors.log`; run `.venv\Scripts\python prototype\fruit_slice.py` by hand to see errors. |
| Update not arriving | `logs\console.log` "update" lines; run `git pull` in the folder to see the error (sign-in, network). |
