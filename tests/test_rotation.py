import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
from player import PoseTracker, is_upright  # noqa: E402


def body(points):
    """Landmark list with only nose, shoulders and hips set: {index: (x, y)}."""
    lm = [types.SimpleNamespace(x=0.5, y=0.5, visibility=0.9) for _ in range(33)]
    for i, (x, y) in points.items():
        lm[i].x, lm[i].y = x, y
    return lm


STANDING = {0: (0.5, 0.2), 11: (0.45, 0.3), 12: (0.55, 0.3), 23: (0.47, 0.55), 24: (0.53, 0.55)}
# Lying on its side, but with a poor fit that still puts the head slightly above the hips.
SIDEWAYS = {0: (0.2, 0.48), 11: (0.32, 0.49), 12: (0.32, 0.5), 23: (0.6, 0.52), 24: (0.6, 0.53)}


def test_standing_person_is_upright():
    assert is_upright(body(STANDING))


def test_sideways_person_is_not_upright_even_with_head_above_hips():
    assert not is_upright(body(SIDEWAYS))


def fake_tracker(rotate=0, locked=False):
    tr = PoseTracker.__new__(PoseTracker)
    tr.rotate, tr.rotation_locked, tr._votes = rotate, locked, []
    return tr


def vote(tr, winners):
    for deg in winners:
        tr._vote(deg)


def test_locks_after_three_agreeing_checks():
    tr = fake_tracker()
    vote(tr, [90, 90, 90])
    assert (tr.rotate, tr.rotation_locked) == (90, True)


def test_follows_the_phone_when_turned_after_locking():
    tr = fake_tracker(rotate=90, locked=True)
    vote(tr, [0, 0])
    assert tr.rotate == 90          # two checks are not enough
    vote(tr, [0])
    assert tr.rotate == 0           # three agreeing checks: switch


def test_a_check_without_an_upright_person_resets_the_count():
    tr = fake_tracker(rotate=90, locked=True)
    vote(tr, [0, 0, None, 0])
    assert tr.rotate == 90
