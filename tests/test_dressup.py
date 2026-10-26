import json
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent.parent / "prototype"),
                str(Path(__file__).resolve().parent.parent)]
import dressup_fit as df  # noqa: E402


def body(scale=1.0, dx=0.0, vis=1.0):
    """A standing person facing the camera (keypoint units), scaled about (0.5, 0.5)."""
    pts = {"nose": (0.5, 0.2), "l_ear": (0.46, 0.2), "r_ear": (0.54, 0.2), "l_eye": (0.48, 0.19), "r_eye": (0.52, 0.19),
           "l_shoulder": (0.42, 0.3), "r_shoulder": (0.58, 0.3), "l_elbow": (0.4, 0.42), "r_elbow": (0.6, 0.42),
           "l_wrist": (0.39, 0.53), "r_wrist": (0.61, 0.53), "l_index": (0.39, 0.57), "r_index": (0.61, 0.57),
           "l_hip": (0.45, 0.55), "r_hip": (0.55, 0.55), "l_knee": (0.45, 0.72), "r_knee": (0.55, 0.72),
           "l_ankle": (0.45, 0.9), "r_ankle": (0.55, 0.9), "l_foot": (0.45, 0.94), "r_foot": (0.55, 0.94)}
    kp = [[0.0, 0.0, 0.0, 0.0] for _ in range(33)]
    for name, (x, y) in pts.items():
        kp[df.POINTS[name]] = [0.5 + (x - 0.5) * scale + dx, 0.5 + (y - 0.5) * scale, vis, 0.0]
    return kp


def to_screen(x, y):
    return x * 1000, y * 1000


def apply(M, p):
    return M @ np.array([p[0], p[1], 1.0])


def test_two_anchors_land_on_the_body_points():
    anchors = {"l_ear": [20, 50], "r_ear": [80, 50]}
    M = df.fit(anchors, body(), to_screen, 0.5)
    assert np.allclose(apply(M, (20, 50)), (460, 200), atol=1e-3)
    assert np.allclose(apply(M, (80, 50)), (540, 200), atol=1e-3)


def test_three_anchors_stretch_the_torso_piece():
    anchors = {"l_shoulder": [10, 10], "r_shoulder": [90, 10], "mid_hip": [50, 120]}
    M = df.fit(anchors, body(), to_screen, 0.5)
    assert np.allclose(apply(M, (10, 10)), (420, 300), atol=1e-3)
    assert np.allclose(apply(M, (90, 10)), (580, 300), atol=1e-3)
    assert np.allclose(apply(M, (50, 120)), (500, 550), atol=1e-3)


def test_pieces_scale_with_the_player():
    anchors = {"l_ear": [20, 50], "r_ear": [80, 50]}
    big = df.fit(anchors, body(1.0), to_screen, 0.5)
    small = df.fit(anchors, body(0.6), to_screen, 0.5)
    assert np.isclose(np.hypot(*small[:, 0]) / np.hypot(*big[:, 0]), 0.6, atol=1e-3)


def test_held_prop_stays_upright_but_moves_with_the_hand():
    up = df.held((0, 0), (0, 10), (100, 100), (100, 80), 0.0)  # arm points up: the staff doesn't flip
    assert np.allclose(apply(up, (0, 10)), (100, 80), atol=1e-4)  # the hand point still lands
    assert np.allclose(up[:, :2], np.eye(2) * 2, atol=1e-4)      # scaled x2, not turned
    full = df.held((0, 0), (0, 10), (100, 100), (100, 80), 1.0)
    assert np.allclose(full, df.similarity((0, 0), (0, 10), (100, 100), (100, 80)))


def test_head_size_steadied_by_the_shoulders():
    anchors = {"l_ear": [20, 50], "r_ear": [80, 50]}            # 60 px apart in the picture
    ref = {"l_shoulder": [-30, 200], "r_shoulder": [130, 200]}  # 160 px apart
    M = df.fit(anchors, body(), to_screen, 0.5, scale_ref=ref)
    ears, shoulders = 80 / 60, 160 / 160                        # each pair's own scale
    assert np.isclose(np.hypot(*M[:, 0]), np.sqrt(ears * shoulders), atol=1e-4)
    mid = apply(M, (50, 50))
    assert np.allclose(mid, (500, 200), atol=1e-3)               # still centred between the ears


def test_piece_hidden_when_its_body_points_are_not_seen():
    assert df.fit({"l_ear": [0, 0], "r_ear": [1, 0]}, body(vis=0.2), to_screen, 0.5) is None
    assert df.fit({"l_ear": [0, 0], "r_ear": [1, 0]}, None, to_screen, 0.5) is None


def test_head_view_follows_the_turn():
    views = [{"file": "f", "ratio": 0.0}, {"file": "a", "ratio": 0.15}, {"file": "b", "ratio": -0.15}]
    kp = body()
    assert df.pick_view(views, df.head_ratio(kp, to_screen, 0.5))["file"] == "f"
    kp[df.POINTS["nose"]][0] += 0.03   # nose moves toward one ear: head turned
    assert df.pick_view(views, df.head_ratio(kp, to_screen, 0.5))["file"] == "a"
    assert df.pick_view(views, None)["file"] == "f"


def test_mirrored_costume_flips_anchors_and_turns(tmp_path):
    meta = {"name": "TEST", "pieces": [{"name": "hat", "views": [
        {"file": "hat.png", "size": [100, 60], "anchors": {"l_ear": [80, 50], "r_ear": [20, 50]}, "ratio": 0.15}]}]}
    (tmp_path / "costume.json").write_text(json.dumps(meta))
    view = df.load_costume(tmp_path, mirror=True)["pieces"][0]["views"][0]
    assert view["anchors"] == {"l_ear": [20, 50], "r_ear": [80, 50]} and view["ratio"] == -0.15 and view["flip"]
    view = df.load_costume(tmp_path, mirror=False)["pieces"][0]["views"][0]
    assert view["anchors"]["l_ear"] == [80, 50] and not view["flip"]


def test_bbox_of_a_rotated_piece():
    M = df.similarity((0, 0), (10, 0), (100, 100), (100, 110))  # turned 90 degrees
    x0, y0, x1, y1 = df.bbox(M, 10, 4)
    assert np.allclose((x0, y0, x1, y1), (96, 100, 100, 110), atol=1e-4)


def test_smoother_keeps_visibility_and_resets():
    sm = df.Smoother()
    a = sm(body(), 0.0)
    assert a[df.POINTS["nose"]][2] == 1.0
    assert sm(None, 0.1) is None and sm.filters == {}


# ---- the game rules (dressup.py) with a fake lobby ----

import types  # noqa: E402

import dressup as du  # noqa: E402

CFG = {"dressup": {"smooth_min_cutoff": 1.5, "smooth_beta": 8.0, "sparkle_speed": 2.5, "photo_countdown": 3,
                   "photo_freeze": 2.5},
       "menu": {"hover_seconds": 1.2, "settings_hover_seconds": 2.5}, "game": {"gravity": 1.6}}


def game(pointers=()):
    hand = lambda: types.SimpleNamespace(pos=None, speed=0.0)  # noqa: E731
    me = types.SimpleNamespace(kp=body(), hands=[hand(), hand()], torso=0.2)
    view = types.SimpleNamespace(world=lambda x, y: (x * 0.75, y))
    lobby = types.SimpleNamespace(t=0.0, aspect=0.75, view=view, players=[me], pointers=lambda: list(pointers))
    return du.DressUp(CFG, lobby, ["knight", "wizard", "royal"], sparkly=["wizard"]), lobby, me


def run(g, lobby, seconds, step=1 / 30):
    for _ in range(int(seconds / step)):
        lobby.t += step
        g.update(step, True)


def test_hold_a_costume_tile_to_wear_it():
    g, lobby, me = game(pointers=[(0.5, 0.4)])      # the middle tile of the top row
    g.goto("pick")
    run(g, lobby, 1.0)
    assert g.state == "pick"
    run(g, lobby, 0.4)
    assert g.state == "wear" and g.key == "wizard" and "poof" in g.sounds


def test_photo_counts_down_then_freezes_the_picture():
    g, lobby, me = game()
    g.wear(0)
    g.pick("photo")
    run(g, lobby, 2.9)
    assert g.photo_t is not None and not g.frozen
    run(g, lobby, 0.2)
    assert g.frozen and g.fx.flash > 0 and "shutter" in g.sounds
    kp_before = g.kp
    me.kp = body(dx=0.1)                              # moving while frozen changes nothing
    run(g, lobby, 1.0)
    assert g.kp is kp_before
    run(g, lobby, 2.0)
    assert not g.frozen


def test_remote_changes_costume_and_goes_home():
    import pygame
    g, lobby, me = game()
    g.wear(0)
    g.press(pygame.K_RIGHT)
    assert g.key == "wizard"
    g.press(pygame.K_LEFT)
    g.press(pygame.K_LEFT)
    assert g.key == "royal"                           # wraps round
    g.press(pygame.K_ESCAPE)
    assert g.done


def test_swinging_a_wand_sparkles_only_for_magic_costumes():
    g, lobby, me = game()
    me.hands[0].pos, me.hands[0].speed = (0.3, 0.5), 2.0   # 10 torso-lengths per second
    g.wear(0)                                              # knight: no sparkles here
    g.fx.particles.clear()
    run(g, lobby, 0.2)
    assert not g.fx.particles
    g.wear(1)                                              # wizard
    g.fx.particles.clear()
    run(g, lobby, 0.2)
    assert g.fx.particles and "twinkle" in g.sounds
