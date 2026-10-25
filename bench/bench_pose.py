r"""
Phase 0 benchmark: how fast can this machine track one player with MediaPipe Pose?

Usage (Windows, PowerShell):
    py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt
    .venv\Scripts\python bench\bench_pose.py --list   # find your camera index and backend
    .venv\Scripts\python bench\bench_pose.py --backend msmf --cam 1 --model lite   # DroidCam
    .venv\Scripts\python bench\bench_pose.py --backend msmf --cam 1 --model full

Keys while running:  q = quit and print summary,  f = toggle fullscreen
By default it counts down 5 s (--delay) so you can walk into position, those frames are
not counted, then measures for 30 s (--seconds) and stops by itself. --seconds 0 = until q.

What it measures:
  - camera fps     : how many frames the camera actually delivers
  - pose ms        : MediaPipe time per frame (avg and p95)
  - loop fps       : end-to-end frames processed per second
Gate (from the roadmap): loop fps >= 30 with one player in frame.

Latency test: run fullscreen on the TV, film your hand AND the screen together
with your phone's 240 fps slow-mo, then count frames between your hand moving
and the big red dot moving. frames / 240 * 1000 = latency in ms.
"""

import argparse
import os
import statistics
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

MODEL_URLS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}

# BlazePose landmark pairs for a body skeleton (face omitted)
BONES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 31), (24, 26), (26, 28), (28, 32),
]
RIGHT_WRIST = 16


# DirectShow opens fast on Windows; let OpenCV pick the backend elsewhere (Linux in Phase 4).
# DroidCam 7's virtual webcam is only visible to OpenCV through Media Foundation: use --backend msmf.
BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}
DEFAULT_BACKEND = "dshow" if os.name == "nt" else "any"


def get_model(name):
    path = Path(__file__).parent / f"pose_landmarker_{name}.task"
    if not path.exists():
        print(f"Downloading {name} model...")
        urllib.request.urlretrieve(MODEL_URLS[name], path)
    return str(path)


def open_camera(index, width, height, backend):
    cap = cv2.VideoCapture(index, BACKENDS[backend])
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 60)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep only the newest frame
    return cap


def list_cameras():
    backends = ["dshow", "msmf"] if os.name == "nt" else ["any"]
    for name in backends:
        for i in range(6):
            cap = cv2.VideoCapture(i, BACKENDS[name])
            ok, frame = cap.read()
            if ok:
                h, w = frame.shape[:2]
                print(f"  --backend {name} --cam {i}: {w}x{h}")
            cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--model", choices=MODEL_URLS.keys(), default="lite")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--backend", choices=BACKENDS.keys(), default=DEFAULT_BACKEND)
    ap.add_argument("--seconds", type=float, default=30,
                    help="stop by itself after this many measured seconds (0 = run until q)")
    ap.add_argument("--delay", type=float, default=5,
                    help="countdown before measuring, to walk into position")
    ap.add_argument("--list", action="store_true", help="list cameras and exit")
    args = ap.parse_args()

    if args.list:
        list_cameras()
        return

    options = vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=get_model(args.model)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
    )
    landmarker = vision.PoseLandmarker.create_from_options(options)
    cap = open_camera(args.cam, args.width, args.height, args.backend)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {args.cam}. Try --list.")

    win = "Phase 0 benchmark"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    fullscreen = False

    pose_ms, loop_times, read_times = [], [], []
    detected = frames = 0
    t_start = last = time.perf_counter()
    t_measure = t_start + args.delay  # frames before this are shown but not counted

    while True:
        t0 = time.perf_counter()
        ok, frame = cap.read()
        t1 = time.perf_counter()
        if not ok:
            print("Camera stopped delivering frames.")
            break
        measuring = t1 >= t_measure

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect_for_video(image, int((t1 - t_start) * 1000))
        t2 = time.perf_counter()

        h, w = frame.shape[:2]
        if result.pose_landmarks:
            detected += measuring
            lm = result.pose_landmarks[0]
            pts = [(int(p.x * w), int(p.y * h)) for p in lm]
            for a, b in BONES:
                cv2.line(frame, pts[a], pts[b], (0, 255, 0), 3)
            cv2.circle(frame, pts[RIGHT_WRIST], 22, (0, 0, 255), -1)  # latency marker

        now = time.perf_counter()
        if measuring:
            read_times.append(t1 - t0)
            pose_ms.append((t2 - t1) * 1000)
            loop_times.append(now - last)
            frames += 1
        last = now

        if measuring:
            recent = loop_times[-30:]
            fps = len(recent) / sum(recent) if sum(recent) > 0 else 0
            status = f"loop {fps:4.1f} fps | pose {pose_ms[-1]:4.1f} ms | {args.model}"
            if args.seconds:
                status += f" | {max(0, t_measure + args.seconds - now):3.0f} s left"
        else:
            status = f"GET IN POSITION... measuring in {t_measure - now:.0f} s"
        cv2.putText(frame, status, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.imshow(win, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if args.seconds and now >= t_measure + args.seconds:
            break
        if key == ord("f"):
            fullscreen = not fullscreen
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)

    cap.release()
    cv2.destroyAllWindows()

    if frames < 30:
        print("Too few frames for a summary.")
        return
    steady = loop_times[10:]  # skip warm-up
    loop_fps = len(steady) / sum(steady)
    p95 = statistics.quantiles(pose_ms[10:], n=20)[18]
    print("\n=== Phase 0 result ===")
    print(f"camera index      : {args.cam} via {args.backend}  ({args.width}x{args.height} requested)")
    print(f"model             : {args.model}")
    print(f"frames            : {frames}")
    print(f"loop fps          : {loop_fps:.1f}   (gate: >= 30)")
    print(f"pose ms avg / p95 : {statistics.mean(pose_ms[10:]):.1f} / {p95:.1f}")
    print(f"player detected   : {100 * detected / frames:.0f}% of frames")
    print("PASS" if loop_fps >= 30 else "BELOW GATE - try --model lite or --width 480 --height 360")


if __name__ == "__main__":
    main()
