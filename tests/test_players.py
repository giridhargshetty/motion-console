import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
from players import assign, body_x, winner  # noqa: E402


def test_lone_player_is_blue_wherever_they_stand():
    assert assign([None, None], [0.85]) == [0]
    assert assign([None, None], [0.15]) == [0]


def test_two_newcomers_left_is_blue_right_is_orange():
    assert assign([None, None], [0.7, 0.3]) == [1, 0]


def test_players_keep_colours_while_moving():
    assert assign([0.3, 0.7], [0.68, 0.35]) == [1, 0]  # detections come in any order


def test_players_keep_colours_when_crossing_slowly():
    # Blue walks right past the middle, orange is still on the right: nearest last position wins.
    assert assign([0.48, 0.75], [0.53, 0.76]) == [0, 1]


def test_second_player_joining_takes_the_free_slot():
    assert assign([0.5, None], [0.52, 0.8]) == [0, 1]
    assert assign([0.5, None], [0.2, 0.49]) == [1, 0]  # blue stays blue even if the newcomer is left


def test_body_x_uses_hips_then_shoulders():
    kp = [[0.0, 0.0, 0.0] for _ in range(33)]
    kp[11], kp[12] = [0.4, 0.3, 0.9], [0.6, 0.3, 0.9]
    assert abs(body_x(kp) - 0.5) < 1e-9          # hips hidden: shoulders
    kp[23], kp[24] = [0.2, 0.6, 0.9], [0.4, 0.6, 0.9]
    assert abs(body_x(kp) - 0.3) < 1e-9          # hips visible: hips


def test_winner():
    assert winner([10, 7]) == 0
    assert winner([3, 9]) == 1
    assert winner([5, 5]) == -1
    assert winner([20, 2], loser=0) == 1          # sliced a bomb: the other player wins
