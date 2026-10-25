"""Who is who with up to two people in view: each person keeps their colour slot.

Pure functions (no camera, no pygame) so they can be unit-tested.
Slot 0 is BLUE, slot 1 is ORANGE. Each frame, people are matched to the slot whose person was
last seen nearest to them. Newcomers take a free slot on their side of the screen (left = blue),
and a lone newcomer when both slots are free is always blue.
"""

import itertools

COLORS = [  # (name, blade glow / text colour, blade core)
    ("BLUE", (80, 175, 255), (225, 242, 255)),
    ("ORANGE", (255, 150, 50), (255, 240, 215)),
]
DEFAULT_X = (0.3, 0.7)   # where a newcomer is expected for each slot (screen left / right)
NEW_COST = 0.35          # cost of putting someone in a slot that nobody has recently
FORGET_SECONDS = 2.0     # a slot forgets where its person was after this long unseen

L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 11, 12, 23, 24


def body_x(kp, min_vis=0.3):
    """Horizontal centre of a person (0..1): mid-hips, or mid-shoulders if the hips are hidden."""
    for a, b in ((L_HIP, R_HIP), (L_SHOULDER, R_SHOULDER)):
        if kp[a][2] >= min_vis and kp[b][2] >= min_vis:
            return (kp[a][0] + kp[b][0]) / 2
    return sum(p[0] for p in kp) / len(kp)


def assign(last_x, det_x):
    """last_x: per slot, where its person was last seen (0..1), or None if nobody recently.
    det_x: centre x of each detected person (at most len(last_x) of them).
    Returns the slot index for each detection."""
    if not det_x:
        return []
    if len(det_x) == 1 and all(x is None for x in last_x):
        return [0]  # a lone player is blue
    best, best_cost = None, None
    for slots in itertools.permutations(range(len(last_x)), len(det_x)):
        cost = 0.0
        for x, s in zip(det_x, slots):
            if last_x[s] is None:
                cost += NEW_COST + 0.5 * abs(x - DEFAULT_X[s])
            else:
                cost += abs(x - last_x[s])
        if best_cost is None or cost < best_cost:
            best, best_cost = list(slots), cost
    return best


def winner(scores, loser=None):
    """Index of the winning slot, -1 for a draw. A loser (e.g. hit a bomb) hands the win to the other."""
    if loser is not None:
        return 1 - loser
    if scores[0] == scores[1]:
        return -1
    return 0 if scores[0] > scores[1] else 1
