"""Survival lives: each sliced bomb costs a life; the game ends only at zero."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))
import fruit_slice as fs  # noqa: E402


def survival_game(players=1, lives=5):
    cfg = fs.load_config()
    cfg["survival"]["lives"] = lives
    cfg["pose"]["max_players"] = 2
    g = fs.Game(cfg, {"classic": 0, "survival": 0})
    g.mode, g.n_players = "survival", players
    g.participants = list(range(players))
    g.t = 10.0
    g.start_round()
    return g


def bomb():
    return fs.Body(0.3, 0.5, 0, 0, 0.06)


def hit(g, p):
    b = bomb()
    g.bombs.append(b)
    return g.explode(b, p)


def test_one_bomb_costs_one_life_and_play_goes_on():
    g = survival_game()
    p = g.players[0]
    assert p.lives == 5
    assert hit(g, p) is False
    assert p.lives == 4 and g.state == "play"


def test_game_ends_on_the_last_life():
    g = survival_game(lives=5)
    p = g.players[0]
    for i in range(4):
        g.t += 2  # past the safe time
        hit(g, p)
    assert g.state == "play" and p.lives == 1
    g.t += 2
    assert hit(g, p) is True
    assert g.state == "boom" and g.loser == 0


def test_no_second_hit_during_safe_time():
    g = survival_game()
    p = g.players[0]
    hit(g, p)
    assert p.safe_until > g.t
    # check_cuts skips bombs while safe: simulate a blade crossing a bomb right away
    g.bombs.append(bomb())
    hand = p.hands[0]
    hand.segment, hand.speed = ((0.1, 0.5), (0.5, 0.5)), 99.0
    p.kp = None  # cut speed only needs the torso default
    g.check_cuts()
    assert p.lives == 4 and len(g.bombs) == 1


def test_two_players_each_have_lives_and_the_last_one_standing_wins():
    g = survival_game(players=2, lives=2)
    blue, orange = g.players
    hit(g, orange)
    assert g.state == "play" and orange.lives == 1 and blue.lives == 2
    g.t += 2
    hit(g, orange)
    assert g.state == "boom"
    g.game_over()
    assert g.winner == 0
