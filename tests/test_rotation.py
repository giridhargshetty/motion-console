import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
from player import PoseTracker, is_upright, load_rotation, save_rotation  # noqa: E402


def body(points):
    """Landmark list with only the given points set: {index: (x, y)}; the rest sit mid-image."""
    lm = [types.SimpleNamespace(x=0.5, y=0.5, visibility=0.9) for _ in range(33)]
    for i, (x, y) in points.items():
        lm[i].x, lm[i].y = x, y
    return lm


# nose, shoulders, hips, knees as {index: (x, y)}
STANDING = {0: (0.5, 0.2), 11: (0.45, 0.3), 12: (0.55, 0.3), 23: (0.47, 0.55), 24: (0.53, 0.55),
            25: (0.47, 0.75), 26: (0.53, 0.75)}
# Seated on a sofa: upright torso, but thighs horizontal, so knees at about hip height.
SITTING = {0: (0.5, 0.2), 11: (0.45, 0.3), 12: (0.55, 0.3), 23: (0.47, 0.55), 24: (0.53, 0.55),
           25: (0.62, 0.58), 26: (0.68, 0.58)}
# Lying on its side, with a poor fit that still puts the head slightly above the hips.
SIDEWAYS = {0: (0.2, 0.48), 11: (0.32, 0.49), 12: (0.32, 0.5), 23: (0.6, 0.52), 24: (0.6, 0.53),
            25: (0.8, 0.54), 26: (0.8, 0.55)}
# Standing but tiny (far away in the background).
FAR = {0: (0.5, 0.40), 11: (0.49, 0.42), 12: (0.51, 0.42), 23: (0.495, 0.46), 24: (0.505, 0.46),
       25: (0.495, 0.5), 26: (0.505, 0.5)}


def test_standing_person_is_upright():
    assert is_upright(body(STANDING))


def test_sitting_person_is_not_used():
    assert not is_upright(body(SITTING))


def test_sideways_person_is_not_upright_even_with_head_above_hips():
    assert not is_upright(body(SIDEWAYS))


def test_tiny_far_person_is_not_used():
    assert not is_upright(body(FAR))


def test_hidden_knees_are_not_enough():
    lm = body(STANDING)
    lm[25].visibility = lm[26].visibility = 0.1
    assert not is_upright(lm)


def test_rotation_is_remembered(tmp_path):
    f = tmp_path / "rot.json"
    assert load_rotation(f) is None
    save_rotation(270, f)
    assert load_rotation(f) == 270
    f.write_text("not json")
    assert load_rotation(f) is None


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
