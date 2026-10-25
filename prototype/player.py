"""Camera + MediaPipe pose for the Phase 1 prototype.

Pose runs on its own thread on the newest camera frame, so the game can draw at display
rate while tracking runs at camera rate. latest() returns (seq, frame, people, t), where
people is a list (up to [pose] max_players) of keypoint lists: 33 x [x, y, visibility],
normalised 0..1, origin top-left, mirrored like the §3 schema; empty when nobody is seen.
get_player() returns just the first person, or None.

Also crops DroidCam's black letterbox bars, and with rotate = "auto" works out which
way up the camera is by checking which rotation shows an upright person.
Phase 2 moves this into pose_service.
"""

import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_{0}/float16/latest/pose_landmarker_{0}.task")

BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}
ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}

# BlazePose keypoint indices used by the games
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_WRIST, R_WRIST = 15, 16
L_PINKY, R_PINKY = 17, 18
L_INDEX, R_INDEX = 19, 20
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26

BONES = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (24, 26), (26, 28),
]


def get_model(name):
    MODEL_DIR.mkdir(exist_ok=True)
    path = MODEL_DIR / f"pose_landmarker_{name}.task"
    if not path.exists():
        print(f"Downloading {name} pose model...")
        urllib.request.urlretrieve(MODEL_URL.format(name), path)
    return str(path)


def make_landmarker(model, mode, num_poses=1):
    return vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=get_model(model)),
        running_mode=mode,
        num_poses=num_poses,
    ))


ROTATION_FILE = MODEL_DIR.parent / "logs" / "camera_rotation.json"  # logs/ is not in git


def load_rotation(path=ROTATION_FILE):
    try:
        deg = json.loads(Path(path).read_text())["rotate"]
        return deg if deg in ROTATIONS else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_rotation(deg, path=ROTATION_FILE):
    try:
        Path(path).parent.mkdir(exist_ok=True)
        Path(path).write_text(json.dumps({"rotate": deg}))
    except OSError:
        pass


def is_upright(lm, min_vis=0.5, min_torso=0.08):
    """A clearly visible STANDING person, as the rotation check needs (coordinates 0..1 of the image):
      - shoulders, hips and knees seen; nose above shoulders above hips above knees
      - torso near vertical, and not tiny (people far away are often mis-fitted)
      - thighs pointing down: a seated person's knees sit near hip height
    A loose check (just head above hips) let people sitting on a sofa, or a poor fit of a
    sideways body, pick the wrong rotation."""
    def mid(a, b):
        return (lm[a].x + lm[b].x) / 2, (lm[a].y + lm[b].y) / 2
    if min(lm[i].visibility for i in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP, L_KNEE, R_KNEE)) < min_vis:
        return False
    sx, sy = mid(L_SHOULDER, R_SHOULDER)
    hx, hy = mid(L_HIP, R_HIP)
    kx, ky = mid(L_KNEE, R_KNEE)
    torso = hy - sy
    thigh = ky - hy
    return (lm[NOSE].y < sy < hy < ky
            and torso >= min_torso and torso > 1.5 * abs(hx - sx)
            and thigh > 0.5 * torso and thigh > 1.2 * abs(kx - hx))


def content_box(frame, threshold=20):
    """Bounding box (x0, y0, x1, y1) of the non-black part of the frame, or None."""
    brightest = frame.max(axis=2)
    rows = np.flatnonzero(brightest.max(axis=1) > threshold)
    cols = np.flatnonzero(brightest.max(axis=0) > threshold)
    if rows.size < frame.shape[0] // 4 or cols.size < frame.shape[1] // 4:
        return None  # nearly all black (lens covered?): don't crop
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def is_blank(frame):
    """True for 'no signal' pictures: DroidCam's flat green frame or its black 'Start DroidCam' screen."""
    small = frame[::8, ::8].reshape(-1, 3)
    return small.std(axis=0).max() < 4 or small.mean() < 12  # one flat colour, or nearly all black


class Camera:
    """Reads frames on a thread and keeps only the newest one, so stale frames are dropped.

    Console-friendly: if the camera is missing or stops delivering, it keeps retrying
    instead of crashing, so plugging the phone in late still works."""

    RETRY_SECONDS = 2.0

    def __init__(self, index, backend, width, height):
        if backend == "dshow" and os.name != "nt":
            backend = "any"
        self.index, self.backend, self.size = index, backend, (width, height)
        self.cap = None
        self.connected = False
        self.status = "starting"
        self._frame = None
        self._seq = 0
        self._running = True
        self._new = threading.Condition()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self):
        cap = cv2.VideoCapture(self.index, BACKENDS[self.backend])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap if cap.isOpened() else None

    def _run(self):
        last_ok = time.perf_counter()
        while self._running:
            if self.cap is None:
                self.cap = self._open()
                if self.cap is None:
                    self.status = f"camera {self.index} not found"
                    time.sleep(self.RETRY_SECONDS)
                    continue
                last_ok = time.perf_counter()
            ok, frame = self.cap.read()
            if ok:
                last_ok = time.perf_counter()
                self.connected, self.status = True, "ok"
                with self._new:
                    self._frame = frame
                    self._seq += 1
                    self._new.notify_all()
            elif time.perf_counter() - last_ok > 3:  # stopped delivering: reopen
                self.connected = False
                self.cap.release()
                self.cap = None

    def read(self, last_seq, timeout=1.0):
        """Wait for a frame newer than last_seq. Returns (seq, frame); frame is None on timeout."""
        with self._new:
            if not self._new.wait_for(lambda: self._seq != last_seq, timeout):
                return last_seq, None
            return self._seq, self._frame

    def close(self):
        self._running = False
        self._thread.join(timeout=3)
        if self.cap is not None:
            self.cap.release()


ADB_CANDIDATES = [
    r"C:\Program Files\DroidCam\Client\data\obs-plugins\droidcam-obs\adb\adb.exe",  # ships with DroidCam
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\adb.exe"),
]


def find_adb(configured="auto"):
    if configured not in ("auto", "none"):
        return configured
    for path in [shutil.which("adb"), *ADB_CANDIDATES]:
        if path and Path(path).exists():
            return path
    return None


class DroidCamUSB:
    """Phone camera straight from the DroidCam phone app over USB: no DroidCam PC client,
    no virtual webcam driver. Same read()/close()/connected interface as Camera.

    Wire format, learned from the open-source droidcam-obs-plugin (GPL-2.0; read for the
    protocol only, no code copied):
      adb forward tcp:<local> tcp:4747, connect, send
      "GET /v5/video/jpg/<w>x<h>/port/<local>/os/.../nonce/.../", then the app streams packets:
      8-byte big-endian pts, 4-byte big-endian length, payload (one JPEG picture).
      pts = 0xFFFFFFFFFFFFFFFF marks a codec-config packet (not used for JPEG).
    The app serves one client at a time, so close the DroidCam PC client when using this.
    """

    APP_PORT = 4747
    APPS = ("com.dev47apps.obsdroidcam", "com.dev47apps.droidcam")
    NO_PTS = (1 << 64) - 1
    MAX_PACKET = 16 * 1024 * 1024

    def __init__(self, width, height, local_port=4747, adb="auto", host="127.0.0.1"):
        self.size = (width, height)
        self.local_port = local_port
        self.host = host
        self.use_adb = adb != "none"  # "none": port already forwarded (or a test server)
        self.adb = find_adb(adb) if self.use_adb else None
        self.connected = False
        self.status = "starting"
        self._frame = None
        self._seq = 0
        self._running = True
        self._new = threading.Condition()
        self._next_launch = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _adb_run(self, *args, timeout=8):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
        try:
            return subprocess.run([self.adb, *args], capture_output=True, text=True,
                                  timeout=timeout, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _launch_app(self):
        """Wake the phone and open the DroidCam app (at most every 15 s)."""
        if not self.adb or time.monotonic() < self._next_launch:
            return
        self._next_launch = time.monotonic() + 15
        listing = self._adb_run("shell", "pm", "list", "packages")
        installed = {line.strip() for line in (listing.stdout if listing else "").splitlines()}
        app = next((a for a in self.APPS if f"package:{a}" in installed), None)
        if app:
            self._adb_run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            self._adb_run("shell", "monkey", "-p", app, "-c", "android.intent.category.LAUNCHER", "1")

    def _connect(self):
        if self.use_adb:
            if not self.adb:
                self.status = "adb not found"
                return None
            r = self._adb_run("forward", f"tcp:{self.local_port}", f"tcp:{self.APP_PORT}")
            if r is None or r.returncode != 0:
                self.status = "phone not found over USB"
                return None
        sock = socket.create_connection((self.host, self.local_port), timeout=3)
        w, h = self.size
        sock.sendall((f"GET /v5/video/jpg/{w}x{h}/port/{self.local_port}"
                      f"/os/windows/obs/30.0.0/client/251/hdr/0/nonce/5912/").encode())
        return sock

    @staticmethod
    def _recv(sock, n):
        buf = bytearray(n)
        view = memoryview(buf)
        got = 0
        while got < n:
            k = sock.recv_into(view[got:], n - got)
            if k == 0:
                raise ConnectionError("closed by the phone")
            got += k
        return bytes(buf)

    def _run(self):
        while self._running:
            sock = None
            try:
                sock = self._connect()
                if sock is None:
                    time.sleep(2)
                    continue
                sock.settimeout(3)
                while self._running:
                    pts, length = struct.unpack(">QI", self._recv(sock, 12))
                    if length == 0 or length > self.MAX_PACKET:
                        raise ConnectionError(f"bad packet length {length}")
                    payload = self._recv(sock, length)
                    if pts == self.NO_PTS:
                        continue
                    frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue
                    self.connected, self.status = True, "ok"
                    with self._new:
                        self._frame = frame
                        self._seq += 1
                        self._new.notify_all()
            except (OSError, ConnectionError, struct.error):
                # App closed, phone locked or unplugged: try to open the app, then reconnect.
                self.connected = False
                self.status = "waiting for the DroidCam app on the phone"
                self._launch_app()
                time.sleep(2)
            finally:
                if sock is not None:
                    sock.close()

    def read(self, last_seq, timeout=1.0):
        with self._new:
            if not self._new.wait_for(lambda: self._seq != last_seq, timeout):
                return last_seq, None
            return self._seq, self._frame

    def close(self):
        self._running = False
        self._thread.join(timeout=4)


def open_camera(cam):
    if cam["backend"] == "droidcam_usb":
        return DroidCamUSB(cam["width"], cam["height"], cam.get("usb_port", 4747), cam.get("adb", "auto"))
    return Camera(cam["index"], cam["backend"], cam["width"], cam["height"])


class PoseTracker:
    def __init__(self, cfg):
        cam = cfg["camera"]
        self.auto_rotate = cam["rotate"] == "auto"
        self.rotate = 0 if self.auto_rotate else int(cam["rotate"])
        self.rotation_locked = not self.auto_rotate
        if self.auto_rotate and (saved := load_rotation()) is not None:
            # Start the right way up from the last successful calibration; the calibration
            # screen still re-checks, in case the phone was turned since.
            self.rotate, self.rotation_locked = saved, True
        self.mirror = cam["mirror"]
        self.crop_bars = cam["crop_bars"]
        self.camera = open_camera(cam)
        self.model = cfg["pose"]["model"]
        self.max_people = cfg["pose"].get("max_players", 1)
        self.want_people = self.max_people  # the game lowers this to 1 for 1-player rounds
        self._people = self.want_people
        self.landmarker = make_landmarker(self.model, vision.RunningMode.VIDEO, self._people)
        self._probe = make_landmarker("lite", vision.RunningMode.IMAGE) if self.auto_rotate else None
        self._votes = []
        self.recheck_rotation = False  # the game sets this on the calibration screen
        self._box = None
        self._box_age = 0
        self.pose_ms = 0.0
        self.signal = False  # True once real pictures arrive (not DroidCam's placeholder)
        self._lock = threading.Lock()
        self._latest = (0, None, [], 0.0)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def latest(self):
        """(seq, frame, people, t): seq goes up by one per processed frame."""
        with self._lock:
            return self._latest

    def get_player(self):
        people = self.latest()[2]
        return people[0] if people else None

    def remember_rotation(self):
        """Called when calibration succeeds: the picture is right, so start this way next time."""
        if self.auto_rotate:
            save_rotation(self.rotate)

    def cycle_rotation(self):
        """Manual override (R key): stops auto-rotation."""
        self.rotate = (self.rotate + 90) % 360
        self.rotation_locked = True
        self.auto_rotate = False
        return self.rotate

    def _run(self):
        cam_seq, n, last_ts = 0, 0, -1
        t0 = time.perf_counter()
        while self._running:
            cam_seq, frame = self.camera.read(cam_seq)
            self.signal = frame is not None and not is_blank(frame)
            if not self.signal:  # tell the game nobody is visible, rather than repeat old keypoints
                with self._lock:
                    self._latest = (self._latest[0] + 1, None, [], time.perf_counter())
                continue
            frame = self._crop(frame)
            want = max(1, min(self.want_people, self.max_people))
            if want != self._people:
                # Looking for one person is faster than two, and passers-by can't join in.
                self.landmarker.close()
                self.landmarker = make_landmarker(self.model, vision.RunningMode.VIDEO, want)
                self._people = want
            if self.auto_rotate and (not self.rotation_locked and n % 10 == 0
                                     or self.recheck_rotation and n % 30 == 0):
                self._probe_rotation(frame)
            n += 1
            if ROTATIONS[self.rotate] is not None:
                frame = cv2.rotate(frame, ROTATIONS[self.rotate])

            t = time.perf_counter()
            ts = max(int((t - t0) * 1000), last_ts + 1)  # must strictly increase
            last_ts = ts
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self.landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            self.pose_ms = (time.perf_counter() - t) * 1000

            # Pose runs on the unmirrored picture so left/right keypoint labels stay true to
            # the player's body; only x is mirrored, together with the displayed frame.
            shown = cv2.flip(frame, 1) if self.mirror else frame
            people = [[[1 - p.x if self.mirror else p.x, p.y, p.visibility] for p in lm]
                      for lm in result.pose_landmarks]
            with self._lock:
                self._latest = (self._latest[0] + 1, shown, people, t)

    def _crop(self, frame):
        if not self.crop_bars:
            return frame
        self._box_age -= 1
        if self._box_age <= 0:
            self._box_age = 60  # re-check every ~2 s
            box = content_box(frame)
            # Only move the crop for a real change, so the picture doesn't wobble.
            if box is None or self._box is None or max(abs(a - b) for a, b in zip(box, self._box)) > 8:
                self._box = box
        if self._box is None:
            return frame
        x0, y0, x1, y1 = self._box
        return np.ascontiguousarray(frame[y0:y1, x0:x1])

    def _probe_rotation(self, frame):
        """Try all four rotations; keep the one showing an upright person (head above hips)."""
        best, best_score = None, 0.0
        for deg, code in ROTATIONS.items():
            img = frame if code is None else cv2.rotate(frame, code)
            res = self._probe.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                              data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
            if not res.pose_landmarks:
                continue
            if is_upright(res.pose_landmarks[0]):
                lm = res.pose_landmarks[0]
                score = sum(lm[i].visibility for i in (NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)) / 5
                if score > best_score:
                    best, best_score = deg, score
        self._vote(best if best_score >= 0.6 else None)

    def _vote(self, best):
        """One rotation check's winner (None = no upright person seen)."""
        if best is None:
            self._votes.clear()
            return
        self._votes = (self._votes + [best])[-3:]
        if not self.rotation_locked:
            if self._votes[-2:] == [best, best]:
                self.rotate = best  # twice in a row: show it this way up
            if self._votes == [best] * 3:
                self.rotation_locked = True  # three in a row: settled
        elif self._votes == [best] * 3 and best != self.rotate:
            self.rotate = best  # re-check on the calibration screen: the phone was turned

    def close(self):
        self._running = False
        self._thread.join(timeout=2)
        self.camera.close()
        self.landmarker.close()
        if self._probe:
            self._probe.close()
