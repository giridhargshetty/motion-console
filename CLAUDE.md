# DIY Motion Console — Project Brief for Claude Code

A camera-based motion game console, inspired by the Nex Playground. One camera watches the player, a pose model tracks their body, and games react to their movement. No controllers.

This file is the full handoff from planning. Read it before writing code. Decisions marked **(decided)** are settled; don't reopen them without a measured reason.

---

## 1. Goal and scope

**v1 goal:** a box that plugs into a TV over HDMI, tracks **one player** with one camera, and runs 3 motion games from a gesture-driven launcher.

**Done means:**
- 1 player tracked at **≥ 30 fps**
- Control **stays with the locked player** when someone walks through the frame
- Movement shows on screen within **≤ 100 ms** (camera to display)
- **3 games + a launcher**, all driven by gestures (raise a hand to select; no keyboard)
- Powers on straight into the launcher (Phase 4)

**Out of scope for v1:** multiplayer, online store, accounts, depth sensing, voice control.

**Why single-player (decided):** it removes multi-person ID tracking, the hardest technical piece, and makes MediaPipe Pose (built for one person on CPU) the obvious model. Keep `players` as a **list** in the protocol so multiplayer can return later without a rewrite.

**The real constraint:** tracking is ~30% of the effort. Game feel for kids is ~70%. Don't over-engineer the vision side.

---

## 2. Environment

| Item | Value |
| --- | --- |
| Dev machine | Dell mini PC, **Windows** (x64), CPU only |
| Python | **3.11 or 3.12** (MediaPipe lags newest Python) — use `py -3.11` |
| Camera (Phase 0) | Android phone via **DroidCam over USB** (virtual webcam). Not Wi-Fi: adds latency. |
| Camera (later) | USB UVC webcam, ≥ 90° FOV. Candidates: Lenovo 300 FHD (95°, 30 fps), Kreo Owl (78°, 60 fps), ELP USBFHD01M-H120 (125° H, low distortion) |
| Game engine | **Godot 4** |
| OS plan | Stay on Windows for Phases 0–3. Move to Linux in Phase 4 for kiosk boot. |

**Windows notes:**
- Open cameras with `cv2.VideoCapture(i, cv2.CAP_DSHOW)`, request MJPG, set `CAP_PROP_BUFFERSIZE=1`.
- scrcpy's phone-as-webcam mode needs v4l2loopback (Linux only). On Windows use DroidCam.
- Write code that is OS-portable (pathlib, no hardcoded `\`), because Phase 4 moves to Linux.

**Camera rules (decided):**
- USB + UVC only. No IP/CCTV/Wi-Fi cameras for live play: H.264 buffering adds hundreds of ms.
- No fisheye > ~140°. Pose accuracy drops at frame edges where hands go.
- No CSI ribbon cameras (Pi/Jetson only; the mini PC has no CSI port).

---

## 3. Architecture (decided)

Two processes, one WebSocket. Python owns seeing the player. Godot owns the fun. Either side can be swapped without touching the other.

```
┌──────────────── Pose service (Python) ────────────────┐      ┌──── Game runtime (Godot 4) ────┐
│ Camera or recorded clip (JSON replay)                 │      │ WebSocket client               │
│   → MediaPipe Pose (BlazePose, 33 keypoints)          │      │   → Player node + gesture      │
│   → Player lock (ignore passers-by)                   │ WS   │     signals                    │
│   → Smoothing (One Euro) + play-zone mask             │ ───► │   → Launcher                   │
│   → Gesture library                                   │      │   → Games                      │
│   → WebSocket server (one JSON message per frame)     │      │                                │
└───────────────────────────────────────────────────────┘      └────────────────────────────────┘
```

Games never touch the camera. Adding a game is pure Godot work.

### Message schema (draft v0)

One message per processed frame, server → client:

```json
{
  "v": 0,
  "t": 1729790000.123,
  "frame": 1842,
  "players": [
    {
      "id": 1,
      "locked": true,
      "kp": [[0.51, 0.22, 0.98], "... 33 x [x, y, visibility], normalised 0..1"],
      "box": [0.30, 0.10, 0.70, 0.95]
    }
  ],
  "events": [
    {"player": 1, "gesture": "swipe", "hand": "right", "speed": 2.4}
  ]
}
```

- Coordinates normalised to 0..1, origin top-left, **mirrored** so the screen acts like a mirror.
- `players` is a list with ≤ 1 entry in v1.
- `events` are edge-triggered (fire once per gesture), not level states.
- Default endpoint: `ws://127.0.0.1:8765`.
- Bump `v` on any breaking change.

---

## 4. Repo layout (proposed)

```
motion-console/
├── CLAUDE.md                  # this file
├── bench/
│   └── bench_pose.py          # Phase 0 benchmark (already written, see §6)
├── pose_service/
│   ├── __main__.py            # python -m pose_service
│   ├── camera.py              # capture + replay source behind one interface
│   ├── pose.py                # MediaPipe wrapper → get_player()
│   ├── lock.py                # player lock
│   ├── filters.py             # One Euro filter
│   ├── zone.py                # play-zone mask
│   ├── gestures/              # one module per gesture + registry
│   ├── server.py              # WebSocket broadcast
│   ├── record.py              # save sessions as JSON
│   └── config.toml
├── tests/
│   ├── clips/                 # recorded JSON sessions (regression fixtures)
│   └── test_*.py
├── prototype/                 # Phase 1 pygame fruit ninja (throwaway)
└── godot/
    ├── addons/motion_input/   # WS client, Player node, gesture signals
    ├── launcher/
    └── games/
        ├── fruit_slice/
        ├── runner/
        └── goalkeeper/
```

---

## 5. Repo harvest: what to take from existing projects

No repo is the base. Take one idea/module from each. **Check each repo's licence before copying code; where none is stated, reimplement the pattern rather than copy.**

| Repo | Take | Leave | Lands in |
| --- | --- | --- | --- |
| [tunneee/FPTU_Ninja_Fruit_VR](https://github.com/tunneee/FPTU_Ninja_Fruit_VR) | Fruit spawn + physics, slice detection via wrist-velocity trail, "hands up to start", fruit class | pygame rendering, gift/reward system | Phase 1 prototype; ported to Godot in Phase 3 |
| [Quanghihicoder/Exercise_Pose_Tracking_Game](https://github.com/Quanghihicoder/Exercise_Pose_Tracking_Game) | Body action → discrete input (jump, duck, lean) | The games, pygame | `gestures/` |
| [Jamesun921/cam-run](https://github.com/Jamesun921/cam-run) | Run-in-place detection, distance-to-camera ("step back"), movement-intensity metric | Three.js scene, AI companion | `gestures/`, onboarding |
| [Sahriz/TNM114](https://github.com/Sahriz/TNM114) | Architecture: Python vision → Godot 4 over WebSocket; Godot listener script | Their TensorFlow hand classifier | `server.py`, Godot addon |
| [astyashish/ActTrack](https://github.com/astyashish/ActTrack) | Joint-angle calc; JSON record/replay of motion sessions | UDP→Unity, GUI. **Non-commercial licence: reimplement, don't copy** | `record.py`, test harness |
| [AVGCS (PyPI)](https://pypi.org/project/avgcs/) | Abstraction: body part → game control, configured per game | Tracker classes | Per-game config |
| [Cool-Coder174/CV_PA9](https://github.com/Cool-Coder174/CV_PA9) | Keypoint gesture rules (fist, open hand) for reference | YOLO model, keyboard sim | Reference only |

**Written ourselves:** player lock, play-zone mask, One Euro smoothing, gesture registry, launcher, kiosk boot.

---

## 6. Phases and gates

Don't start the next phase until the gate passes. A tracking problem found after the games are built costs 3× to fix.

### Phase 0 — Benchmark (week 1) ✅ closed 2026-10-25 (see `bench/RESULTS.md`)

`bench/bench_pose.py` already exists (copy it into the repo). It runs MediaPipe PoseLandmarker in VIDEO mode, draws the skeleton, puts a big red dot on the right wrist for the latency test, and prints a summary on `q`.

Tasks:
- [x] Set up venv, install `mediapipe opencv-python`, run `--list` to find the DroidCam camera index (DroidCam = `--backend msmf --cam 1`)
- [x] Run `--model lite` and `--model full` at 640×480 with one player 2 m from the camera (on the laptop; re-run on the mini PC)
- [ ] *Deferred to Phase 2 clips:* Re-run with a second person walking behind the player
- [ ] *Deferred:* Latency: fullscreen on TV (`f`), film hand + screen with phone 240 fps slow-mo, count frames. `ms = frames / 240 × 1000`
- [x] Record results in `bench/RESULTS.md` (model, resolution, loop fps, pose ms avg/p95, detection %, latency ms)
- [ ] Optional improvement: add `--json-out` to write the summary as JSON for later comparison

**Gate:** one player at **≥ 30 fps** on the mini PC. If not, try `--model lite --width 480 --height 360` before buying hardware.

### Phase 1 — Single-player prototype (weeks 2–3)

- [x] Clone FPTU_Ninja_Fruit_VR into `prototype/_reference/` (no licence: git-ignored, study only), run with a camera patch
- [x] Reimplemented as our own `prototype/fruit_slice.py`; pose behind `get_player()` in `prototype/player.py`
- [x] Add One Euro smoothing to wrists (`pose_service/filters.py`); slice speed scales with body size (torso-lengths/s). *Still to playtest with a child*
- [x] Make thresholds config values, not magic numbers (`prototype/config.toml`)

**Gate:** a child plays 5 minutes unprompted; measured latency < 120 ms.

### Phase 2 — Pose service (weeks 4–6)

- [ ] `python -m pose_service`: camera → pose → player lock → One Euro → play-zone mask → gestures → WS
- [ ] **Player lock:** lock whoever holds a hand above their head for 1 s; then follow the skeleton nearest their last position; release after N s lost
- [ ] **Play zone:** ignore detections whose box height is below a threshold (too far = background person) or whose centre is outside the configured zone
- [ ] Gestures: `hands_up`, `swipe` (left/right hand, speed), `jump`, `duck`, `lean` (left/right), `run_in_place`, `too_close` (step back prompt)
- [ ] Each gesture: pure function of a short keypoint history → event or nothing. Unit-testable without a camera.
- [ ] WS server broadcasting the schema in §3
- [ ] `record` mode: save raw keypoint sessions as JSON; `replay` mode feeds them through the same pipeline
- [ ] Regression tests: 10 recorded clips with someone walking behind the player

**Gate:** in all 10 clips, control never jumps to the other person.

### Phase 3 — Games and launcher (weeks 7–10)

- [ ] Godot 4 addon `motion_input`: WS client autoload, `Player` node exposing keypoints, signals per gesture, auto-reconnect
- [ ] Debug overlay: skeleton drawn over the game, toggleable
- [ ] Game 1: fruit slice (FPTU logic ported)
- [ ] Game 2: endless runner (run in place to move, jump/duck to dodge)
- [ ] Game 3: goalkeeper or whack-a-mole (reach for targets at frame edges)
- [ ] Launcher: hold a hand up 1 s to select; "step back" prompt when too close

**Gate:** one player completes all 3 games with no keyboard touched.

### Phase 4 — The box (weeks 11–14)

- [ ] Decide compute: keep the mini PC, or a Raspberry Pi 5 (one-person MediaPipe is light enough to try)
- [ ] Linux + kiosk boot: systemd starts the pose service and Godot fullscreen, no desktop visible
- [ ] Final camera + privacy shutter + status LED
- [ ] 3D-printed enclosure under the TV

**Gate:** cold boot to launcher < 40 s; 1-hour session with no fps drop from heat.

### Phase 5 — Content (ongoing)

One game every 2–3 weeks. Playtest with kids before polishing. Test on clips recorded at home.

---

## 7. Engineering rules

- **Measure, don't guess.** Every performance claim comes with a number from the benchmark or a test.
- **Latency budget ≤ 100 ms end to end.** Never add buffering (queues, multi-frame batching) without measuring its cost. Always process the newest frame; drop stale ones.
- **No camera needed for tests.** Everything after `pose.py` must run from recorded JSON.
- **Config over constants.** Thresholds (swipe speed, lock time, zone size) live in `config.toml`.
- **Kids first.** Gestures must trigger for small, fast, imprecise movements. Prefer generous thresholds with debouncing over strict ones.
- **Licences:** MediaPipe Apache-2.0, Godot MIT. **Avoid Ultralytics YOLO (AGPL)** unless we deliberately decide to. Don't copy code from ActTrack (non-commercial).
- Keep the pose service runnable on Linux even while developing on Windows.

---

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Pose too slow on CPU | Phase 0 benchmark; lite model or 480p input |
| Fisheye distortion | Use ≤ ~120° lenses |
| Control jumps to another person | Player lock + replay regression tests |
| Background people trigger input | Play-zone mask + minimum box height |
| Games feel flat | Playtest every game with kids before polishing |
| Phone overheats as camera | Keep it charging; it's a Phase 0 stand-in only |

---

## 9. Open questions

- Dell mini PC CPU model (decides Phase 0 odds) — check with `wmic cpu get name`.
- Play depth from TV to player in the target room (< 2 m → need ≥ 95° FOV camera).
- The mini PC was also planned as a second home-server machine. It can't be both the server and the box under the TV. Decide before Phase 4.
- Home use only, or a possible product later? Decides licence choices now.

---

## 10. First session checklist for Claude Code

1. Create the repo layout in §4 (empty modules are fine), `git init`, add `.gitignore` (venv, `*.task` model files, `__pycache__`).
2. Put `bench_pose.py` in `bench/`.
3. Create a venv with Python 3.11/3.12, install `mediapipe opencv-python`, pin versions in `requirements.txt`.
4. Run `py -3.11 bench/bench_pose.py --list` and help me identify the DroidCam camera.
5. Run the lite and full benchmarks, then write `bench/RESULTS.md`.
6. Stop and report results against the Phase 0 gate before starting Phase 1.
