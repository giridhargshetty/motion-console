"""Boxing rules: gesture checks, the computer boxer's timeline, and 5-hit win/lose (no camera)."""

import random
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
import boxing as bx  # noqa: E402

SPEC = {"name": "TEST", "sprite": "test", "windup": 1.0, "guard_chance": 0.0, "attack_every": [2.0, 2.0]}


def pose(nose=(0.5, 0.2), lw=(0.4, 0.55), rw=(0.6, 0.55)):
    """A standing person (torso 0.25 high) with wrists where given."""
    kp = [[0.5, 0.5, 0.99, 0.0] for _ in range(33)]
    kp[bx.NOSE] = [*nose, 0.99, 0.0]
    kp[bx.L_SHOULDER], kp[bx.R_SHOULDER] = [0.45, 0.3, 0.99, 0.0], [0.55, 0.3, 0.99, 0.0]
    kp[bx.L_HIP], kp[bx.R_HIP] = [0.47, 0.55, 0.99, 0.0], [0.53, 0.55, 0.99, 0.0]
    kp[bx.L_WRIST], kp[bx.R_WRIST] = [*lw, 0.99, 0.0], [*rw, 0.99, 0.0]
    return kp


GUARD = pose(lw=(0.46, 0.22), rw=(0.54, 0.22))


# ---- gestures ----

def test_guard_needs_both_gloves_up_in_front_of_the_face():
    assert bx.guarding(GUARD)
    assert not bx.guarding(pose())                                     # arms down
    assert not bx.guarding(pose(lw=(0.46, 0.22)))                      # one glove up
    assert not bx.guarding(pose(lw=(0.1, 0.22), rw=(0.9, 0.22)))       # arms up but wide apart


def test_dodge_by_leaning_or_ducking():
    t = 0.25
    assert bx.dodged((0.5, 0.2), (0.5 + 0.6 * t, 0.2), t)       # leaned
    assert bx.dodged((0.5, 0.2), (0.5, 0.2 + 0.5 * t), t)       # ducked
    assert not bx.dodged((0.5, 0.2), (0.52, 0.21), t)           # barely moved
    assert not bx.dodged(None, (0.9, 0.2), t)


def test_punch_types():
    assert bx.classify_punch(0.2, -3.5, 0, 3.0, 2.5) == "jab"     # fast, mostly up/forward on screen
    assert bx.classify_punch(4.0, 0.5, 0, 3.0, 2.5) == "hook"     # fast sideways swing
    assert bx.classify_punch(0.3, 0.2, 3.0, 3.0, 2.5) == "jab"    # straight at the camera (depth)
    assert bx.classify_punch(1.0, 1.0, 0.5, 3.0, 2.5) is None     # too slow


def test_aimed_at_the_boxer():
    target = (0.375, 0.33)
    assert bx.aimed_at((0.38, 0.35), (0, 0), target, 0.32)         # ended on the boxer
    assert bx.aimed_at((0.1, 0.6), (3, -3), target, 0.32)          # far, but heading there
    assert not bx.aimed_at((0.1, 0.9), (-3, 3), target, 0.32)      # punching away


# ---- the computer boxer ----

def test_opponent_winds_up_then_punches_then_recovers():
    opp = bx.Opponent(SPEC, random.Random(1))
    opp.start(0.0)
    events = []
    t = 0.0
    while t < 4.0:
        t += 0.05
        if opp.update(t) == "impact":
            events.append(round(t, 2))
    # attacks every 2 s, 1 s of wind-up: the first punch lands about 3 s in
    assert events and 2.9 <= events[0] <= 3.1
    assert opp.state in ("punch", "recover")


def test_boxer_still_attacks_when_you_punch_non_stop():
    opp = bx.Opponent(SPEC, random.Random(3))
    opp.start(0.0)
    t, impacts = 0.0, 0
    while t < 12.0:
        t += 0.05
        if t >= opp.immune_until and opp.state != "guard":
            opp.take_hit(t, 0.6)  # a punch lands whenever possible (punches on his guard are blocked)
        if opp.update(t) == "impact":
            impacts += 1
    assert impacts >= 2


def test_counter_during_windup_scores_but_the_punch_still_comes():
    opp = bx.Opponent(SPEC, random.Random(1))
    opp.start(0.0)
    opp.go("windup", 1.0, 1.0)
    opp.take_hit(1.2, 0.6)
    assert opp.state == "windup"
    assert opp.update(2.05) == "impact"


def test_hit_stuns_and_gives_brief_immunity():
    opp = bx.Opponent(SPEC, random.Random(1))
    opp.start(0.0)
    opp.take_hit(1.0, 0.6)
    assert opp.state == "stunned" and opp.immune_until == 1.6


# ---- whole fights with a fake lobby ----

def fake_lobby(kp):
    hand = lambda: types.SimpleNamespace(pos=None, t=None)  # noqa: E731
    me = types.SimpleNamespace(kp=kp, hands=[hand(), hand()], torso=0.25, last_seen=0.0)
    lobby = types.SimpleNamespace(t=0.0, aspect=0.75, players=[me], hands=me.hands,
                                  hands_up=lambda kp: False)
    return lobby, me


def fight(kp, wins_needed=5):
    lobby, me = fake_lobby(kp)
    saved = {}
    g = bx.Boxing({"boxing": {"hits_to_win": wins_needed, "hits_to_lose": 5, "punch_speed": 3.0,
                              "punch_forward_speed": 2.5, "punch_cooldown": 0.35, "hit_immunity": 0.6,
                              "dodge_lean": 0.5, "dodge_duck": 0.4, "result_seconds": 2.0,
                              "boxers": [SPEC]},
                   "menu": {"hover_seconds": 1.2, "settings_hover_seconds": 2.5},
                   "game": {"gravity": 1.6, "hands_up_seconds": 1.0, "pause_after_seconds": 1.0}},
                  lobby, {}, saved.update, random.Random(2))
    g.pick("boxer0")
    g.goto("countdown")

    def run(seconds, step=1 / 30):
        for _ in range(int(seconds / step)):
            lobby.t += step
            me.last_seen = lobby.t
            g.update(step, False)
    return g, lobby, me, run, saved


def test_standing_still_you_lose_after_five_hits():
    g, lobby, me, run, saved = fight(pose())
    run(3.2)
    assert g.state == "fight"
    run(30)
    assert g.state == "result" and not g.won and g.taken == 5
    assert saved == {}  # no win recorded


def test_covering_up_blocks_every_punch():
    g, lobby, me, run, saved = fight(GUARD)
    run(25)
    assert g.state == "fight" and g.taken == 0


def test_five_landed_punches_win_and_count():
    g, lobby, me, run, saved = fight(pose())
    run(3.2)
    for _ in range(5):
        lobby.t += 1.0                      # past the immunity after each hit
        g.opponent.state = "idle"           # not covering up
        g.land_punch("jab", (0.37, 0.33))
    assert g.state == "result" and g.won and g.landed == 5
    assert saved == {"boxing_test": 1}


def test_punches_on_a_guarding_boxer_are_blocked():
    g, lobby, me, run, saved = fight(pose())
    run(3.2)
    g.opponent.go("guard", lobby.t, 5.0)
    g.land_punch("jab", (0.37, 0.33))
    assert g.landed == 0
