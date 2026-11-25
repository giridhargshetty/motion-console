# Project status: paused 2026-11-25

The prototype works and has been played at home. The mini PC it ran on (a Dell Wyse 7040) has been
reused for something else, so development is on hold. Everything needed to carry on is in this repo.

## What exists

A camera motion-game console: phone camera over USB -> MediaPipe pose -> pygame games on the TV.

- **Console** (`prototype/console.py`): Network screen -> calibration -> how many players -> TV-style
  home screen (`home.py`) with game tiles and Settings. Works with raised hands, a mouse, or a remote's
  arrows + OK. Ctrl+Q quits (exit code 10).
- **Fruit Slice** (`fruit_slice.py`): Classic (60 s) and Survival (5 lives), 1 or 2 players
  (BLUE vs ORANGE), 10 fruits, bombs, combos.
- **Boxing** (`boxing.py`, `boxing_draw.py`): first person vs a computer boxer (Rookie / Contender /
  Champ), block with both gloves up or dodge; punches must straighten the arm. Animated Mixamo boxer
  sprites in `assets/boxers/`.
- **Dress Up** (`dressup*.py`): magic-mirror costume game, 10 costumes in `assets/costumes/`.
- **Camera** (`player.py`): reads the DroidCam phone app directly over USB (adb, no PC client),
  auto-rotates (remembers the last good rotation), crops letterbox bars, tracks up to 2 people.
- **Art pipeline** (`tools/blender/`): Mixamo / Quaternius / Kenney models rendered to sprite frames
  headless with Blender. Raw downloads live in `assets/source/` on the dev laptop only (627 MB,
  git-ignored, licence: don't redistribute) - keep a copy if the laptop is ever wiped.
- **Tests**: `.venv\Scripts\python -m pytest -q tests` -> 68 passing (2026-11-25).

Phase 0 closed (see `bench/RESULTS.md`); Phase 1 prototype done and playtested; CLAUDE.md phases
2-4 (pose service, Godot, enclosure) not started.

## Measured on the mini PC (i5-6400, Ubuntu 26.04)

- Display 62 fps at 720p (the TV is set to 1280x720@60; drawing 4K on the CPU was the old slowdown).
- Pose: ~12-20 ms one person (full model), ~35 ms two people (lite model).

## Backup of the last box

`backups/minipc-2026-11-25/`
- `box-files.tar.gz`: `logs/` (perf, console, errors, `camera_rotation.json`),
  `prototype/highscores.json`, `prototype/config.local.toml` (fullscreen). Restore by extracting into
  the repo folder on the new box.
- `box-info.txt`: hardware, Python/package versions, kiosk pieces, USB devices.

High scores at backup: Classic 154, Survival 78; boxing wins Rookie 1, Contender 18, Champ 12.

## To set up a box again

Follow `deploy/README.md` (Linux kiosk section): Ubuntu Server, Tailscale, `ssh-copy-id`, then over SSH
clone the repo and run `deploy/linux/setup.sh` (it installs Python 3.12 via uv, adb, X/xinit,
NetworkManager, Tailscale, tty1 auto-login). If Ubuntu was installed without a network, run
`deploy/linux/enable_ethernet.sh` with sudo first. Updates afterwards: `deploy/linux/update.sh`.

Things learned the hard way:
- The phone needs USB debugging allowed for the box and USB tethering OFF; the DroidCam PC client
  must not run (it takes the phone's only video connection).
- The Wyse has no Wi-Fi card; the MT7601U USB adapter works out of the box.
- pygame's SDL has no Wayland support and cage's Xwayland crashed: the kiosk uses bare X (xinit).

## Idea for the future: run directly on Android TVs

Running on smart TVs (for example Hisense Android TVs in a hotel) without a PC: a server would host
the games as a web page (plus updates and scores), and each TV runs body tracking itself in the
browser, so no camera video ever leaves the room. Needs a rewrite of the games in JavaScript.
First steps:
1. TV model number -> look up its chip and memory.
2. Check a USB webcam works on the TV (a video-call app).
3. Build a small tracking-only test app and measure fps on the TV. Expect 1 player with the lite
   model to be borderline (15-30 fps); 2 players likely too slow. Fallback: a Google TV box per TV.
