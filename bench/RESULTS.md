# Phase 0 benchmark results

**Gate:** one player at ≥ 30 fps on the mini PC.

## Verdict (2026-10-25): Phase 0 closed

- **PASS on the dev laptop** (Ryzen 7 5800HS): full model 31.6 fps (camera-capped), 15 ms pose, 97% detection.
- Real play confirms it: the Phase 1 fruit-slice prototype ran with no noticeable lag and comfortable cutting.
- **Still to do, carried forward:**
  - Re-run `bench_pose.py` on the **mini PC** once the console is set up there (the gate names the mini PC; these numbers are from the laptop).
  - Latency test (240 fps slow-mo) on the TV.
  - Second-person-behind run (no second person available yet; also covered by the Phase 2 regression clips).

## Setup

| Item | Value |
| --- | --- |
| CPU | AMD Ryzen 7 5800HS (8 cores), CPU only |
| OS / Python | Windows 11, Python 3.12, mediapipe 1.1.1, opencv-python 5.0.0.93 |
| Camera | Android phone via DroidCam 7.2.1 over USB, `--backend msmf --cam 1` |
| Resolution | 640×480 requested |
| Distance | ~2 m, one player |

## Runs

| Date | Model | Res | Frames | Loop fps | Pose ms avg / p95 | Detected | Latency ms | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-25 | lite | 640×480 | 7417 | 51.2 | 11.3 / 20.2 | 61% | — | PASS |
| 2026-10-25 | full | 640×480 | 948 (30 s) | 31.6 | 15.0 / 16.3 | 97% | — | PASS |
| — | full, 2nd person behind | 640×480 | | | | | | deferred: no 2nd person available |

## Notes

- DroidCam 7's virtual webcam is visible to OpenCV only through Media Foundation (`msmf`); DirectShow can't open it. After the driver install it delivered blank green frames until the PC was rebooted.
- Loop fps is capped by the camera, not the CPU. Full model: 15 ms pose time means the CPU could do ~65 fps, but the loop ran at 31.6 because DroidCam delivers ~30 real frames/s. The lite run's 51 fps likely counted repeated frames from the virtual webcam. Pose ms is the number to compare between models.
- Full model is affordable: only ~4 ms slower than lite, with p95 16.3 ms (steadier than lite's 20.2). Prefer **full** for accuracy unless later phases need the CPU time.
- Full run used the timed mode (5 s countdown, 30 s measured), so 97% detection reflects tracking quality with the player in frame.
- Lite run detection 61% is because the player walked out of frame (to press `q`); while in frame, tracking held steady. Keep runs short (30–60 s) or stay in frame so detection % reflects tracking quality.
- Latency (camera → screen) not yet measured: fullscreen on the TV (`f`), film hand + screen at 240 fps, `ms = frames / 240 × 1000`.
