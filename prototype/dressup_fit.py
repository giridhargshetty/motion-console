"""Fitting costume pieces onto a player (Dress Up): pure functions, no drawing, unit-tested.

A piece is a picture plus anchors: body points (like the ears or the shoulders) at known pixels in
that picture, written by tools/blender/render_costume.py. Fitting maps the anchors onto the player's
keypoints on screen:
  2 anchors -> similarity (position, rotation, one scale): head pieces, gloves, boots, props
  3 anchors -> affine (also stretch and shear): torso pieces and capes follow both shoulders and the hips
so every piece sizes itself to the player, small child or grown-up.

Head pieces come in a few turned views; pick_view chooses the one matching how far the nose sits
from the middle of the ears.
"""

import json
import math
from pathlib import Path

import numpy as np

from pose_service.filters import OneEuroFilter

POINTS = {"nose": 0, "l_eye": 2, "r_eye": 5, "l_ear": 7, "r_ear": 8, "l_shoulder": 11, "r_shoulder": 12,
          "l_elbow": 13, "r_elbow": 14, "l_wrist": 15, "r_wrist": 16, "l_index": 19, "r_index": 20,
          "l_hip": 23, "r_hip": 24, "l_knee": 25, "r_knee": 26, "l_ankle": 27, "r_ankle": 28,
          "l_foot": 31, "r_foot": 32}
DERIVED = {"mid_hip": ("l_hip", "r_hip"), "mid_shoulder": ("l_shoulder", "r_shoulder")}
ASSETS = Path(__file__).resolve().parent.parent / "assets" / "costumes"


def body_point(kp, name, min_vis):
    """(x, y) of a named body point in keypoint units, or None if it isn't seen well enough."""
    if kp is None:
        return None
    if name in DERIVED:
        a, b = (body_point(kp, n, min_vis) for n in DERIVED[name])
        return None if a is None or b is None else ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    p = kp[POINTS[name]]
    return (p[0], p[1]) if p[2] >= min_vis else None


def similarity(a_src, b_src, a_dst, b_dst):
    """2x3 matrix taking a_src -> a_dst and b_src -> b_dst with rotation + one scale (no stretch)."""
    sx, sy = b_src[0] - a_src[0], b_src[1] - a_src[1]
    dx, dy = b_dst[0] - a_dst[0], b_dst[1] - a_dst[1]
    den = sx * sx + sy * sy
    if den < 1e-9:
        return None
    c = (dx * sx + dy * sy) / den     # scale * cos(angle)
    s = (dy * sx - dx * sy) / den     # scale * sin(angle)
    tx = a_dst[0] - (c * a_src[0] - s * a_src[1])
    ty = a_dst[1] - (s * a_src[0] + c * a_src[1])
    return np.array([[c, -s, tx], [s, c, ty]], dtype=np.float32)


def held(a_src, b_src, a_dst, b_dst, rotate):
    """Like similarity, but turning only `rotate` (0..1) of the way with the body (0 = stays upright,
    like a staff held in the hand); b (the hand) still lands exactly."""
    M = similarity(a_src, b_src, a_dst, b_dst)
    if M is None or rotate >= 1:
        return M
    scale, angle = math.hypot(M[0, 0], M[1, 0]), math.atan2(M[1, 0], M[0, 0]) * rotate
    c, s = scale * math.cos(angle), scale * math.sin(angle)
    tx = b_dst[0] - (c * b_src[0] - s * b_src[1])
    ty = b_dst[1] - (s * b_src[0] + c * b_src[1])
    return np.array([[c, -s, tx], [s, c, ty]], dtype=np.float32)


def affine3(src, dst):
    """2x3 matrix taking three src points to three dst points, or None if src are in a line."""
    S = np.array([[p[0] for p in src], [p[1] for p in src], [1.0, 1.0, 1.0]])
    if abs(np.linalg.det(S)) < 1e-6:
        return None
    D = np.array([[p[0] for p in dst], [p[1] for p in dst]])
    return (D @ np.linalg.inv(S)).astype(np.float32)


def fit(anchors, kp, to_screen, min_vis, rotate=1.0, scale_ref=None):
    """Matrix placing a piece (anchors: {body point: [px, py]} in its picture) on screen, or None
    when any anchor's body point isn't seen. to_screen maps keypoint (x, y) to screen pixels.
    rotate < 1 (two anchors only): the piece turns less than the body (see held).
    scale_ref (two anchors only): two more body points, like the shoulders, at their pixels in the
    picture; the size becomes the geometric mean of both pairs' scales. Ears alone are a short,
    wobbly ruler; shoulders steady it."""
    names = list(anchors)
    dst = []
    for name in names:
        p = body_point(kp, name, min_vis)
        if p is None:
            return None
        dst.append(to_screen(*p))
    src = [anchors[n] for n in names]
    if len(names) == 2:
        M = held(src[0], src[1], dst[0], dst[1], rotate)
        if M is not None and scale_ref:
            M = steady(M, scale_ref, kp, to_screen, min_vis, dst)
        return M
    if len(names) == 3:
        return affine3(src, dst)
    raise ValueError(f"a piece needs 2 or 3 anchors, not {len(names)}")


def steady(M, scale_ref, kp, to_screen, min_vis, dst):
    """Rescale M about the middle of its anchors to the geometric mean of its own scale and the
    scale_ref pair's (unchanged if those points aren't seen)."""
    (na, pa), (nb, pb) = scale_ref.items()
    qa, qb = body_point(kp, na, min_vis), body_point(kp, nb, min_vis)
    src_d = math.dist(pa, pb)
    if qa is None or qb is None or src_d < 1e-6:
        return M
    ref = math.dist(to_screen(*qa), to_screen(*qb)) / src_d
    now = math.hypot(M[0, 0], M[1, 0])
    if now < 1e-9:
        return M
    k = math.sqrt(ref / now)  # new scale sqrt(now * ref), as a factor on the current one
    cx, cy = (dst[0][0] + dst[1][0]) / 2, (dst[0][1] + dst[1][1]) / 2
    S = np.array([[k, 0, cx - k * cx], [0, k, cy - k * cy], [0, 0, 1]], dtype=np.float32)
    return (S @ np.vstack([M, [0, 0, 1]]))[:2]


def head_ratio(kp, to_screen, min_vis):
    """How far the head is turned: nose's sideways offset from the middle of the ears, in shoulder
    widths (0 = facing the camera). None if not seen."""
    nose = body_point(kp, "nose", min_vis)
    ears = [body_point(kp, n, min_vis * 0.4) for n in ("l_ear", "r_ear")]  # one ear hides when turned
    shoulders = [body_point(kp, n, min_vis) for n in ("l_shoulder", "r_shoulder")]
    if nose is None or None in ears or None in shoulders:
        return None
    (nx, _), (ax, _), (bx, _) = (to_screen(*p) for p in (nose, *ears))
    (sx, sy), (tx, ty) = (to_screen(*p) for p in shoulders)
    width = math.hypot(tx - sx, ty - sy)
    return (nx - (ax + bx) / 2) / width if width > 1e-6 else None


def pick_view(views, ratio):
    """The view drawn for this head turn: the one whose ratio is closest (front if unknown)."""
    if ratio is None or len(views) == 1:
        return min(views, key=lambda v: abs(v.get("ratio", 0.0)))
    return min(views, key=lambda v: abs(v.get("ratio", 0.0) - ratio))


def bbox(M, w, h):
    """Screen rectangle (x0, y0, x1, y1) covered by a w x h picture placed with M."""
    corners = np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], dtype=np.float32) @ M.T
    return corners[:, 0].min(), corners[:, 1].min(), corners[:, 0].max(), corners[:, 1].max()


def load_costume(folder, mirror):
    """costume.json with the pieces' anchors ready for a mirrored screen: when the picture is
    mirrored, each piece is drawn flipped (view["flip"]), so its anchors and turn ratio flip too."""
    meta = json.loads((Path(folder) / "costume.json").read_text())
    for piece in meta["pieces"]:
        for view in piece["views"]:
            view["path"] = str(Path(folder) / view["file"])
            view["flip"] = bool(mirror)
            if mirror:
                w = view["size"][0]
                view["anchors"] = {k: [w - x, y] for k, (x, y) in view["anchors"].items()}
                if "scale_ref" in view:
                    view["scale_ref"] = {k: [w - x, y] for k, (x, y) in view["scale_ref"].items()}
                view["ratio"] = -view.get("ratio", 0.0)
    return meta


def costume_names(order):
    """Costumes in the configured order that have been rendered."""
    return [n for n in order if (ASSETS / n / "costume.json").exists()]


def sparkly(names):
    """Costumes holding something that sparkles when swung (a piece marked "sparkle")."""
    return [n for n in names
            if any(p.get("sparkle") for p in json.loads((ASSETS / n / "costume.json").read_text())["pieces"])]


class Smoother:
    """One Euro filter on every keypoint's x and y, so pieces sit still when the player does."""

    def __init__(self, min_cutoff=1.5, beta=8.0):
        self.args = (min_cutoff, beta)
        self.filters = {}

    def __call__(self, kp, t):
        if kp is None:
            self.filters.clear()  # start fresh when the player comes back
            return None
        out = []
        for i, p in enumerate(kp):
            fx, fy = self.filters.setdefault(i, (OneEuroFilter(*self.args), OneEuroFilter(*self.args)))
            out.append([fx(p[0], t), fy(p[1], t), *p[2:]])
        return out
