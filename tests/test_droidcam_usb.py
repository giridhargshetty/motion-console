"""DroidCamUSB against a fake DroidCam app on localhost (no phone or adb needed)."""

import socket
import struct
import sys
import threading
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
from player import DroidCamUSB  # noqa: E402


def jpeg(value, w=64, h=48):
    img = np.full((h, w, 3), value, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


def fake_app(packets):
    """Serve one connection: remember the request, then send the given packets."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    seen = {}

    def serve():
        conn, _ = server.accept()
        with conn:
            seen["request"] = conn.recv(1024).decode()
            for pts, payload in packets:
                conn.sendall(struct.pack(">QI", pts, len(payload)) + payload)
            threading.Event().wait(1.0)  # keep the socket open while the client reads
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1], seen


def test_reads_jpeg_frames_and_skips_config_packet():
    port, seen = fake_app([
        (DroidCamUSB.NO_PTS, b"\x00\x00\x00\x01config"),  # codec config: ignored
        (1000, jpeg(50)),
        (2000, jpeg(200)),
    ])
    cam = DroidCamUSB(640, 480, local_port=port, adb="none")
    try:
        seq, frame = 0, None
        for _ in range(20):
            seq, f = cam.read(seq, timeout=1.0)
            if f is not None:
                frame = f
                if abs(int(f.mean()) - 200) < 10:
                    break
        assert frame is not None and frame.shape == (48, 64, 3)
        assert abs(int(frame.mean()) - 200) < 10   # newest picture wins
        assert cam.connected and cam.status == "ok"
        assert seen["request"].startswith("GET /v5/video/jpg/640x480/port/")
    finally:
        cam.close()


def test_reports_waiting_when_nothing_listens():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again: nobody listens here
    cam = DroidCamUSB(640, 480, local_port=port, adb="none")
    try:
        frame = None
        for _ in range(6):  # Windows takes ~2 s to refuse a connection to a closed port
            _, frame = cam.read(0, timeout=1.0)
            if "waiting" in cam.status:
                break
        assert frame is None
        assert not cam.connected
        assert "waiting" in cam.status
    finally:
        cam.close()
