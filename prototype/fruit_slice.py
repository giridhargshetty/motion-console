r"""Phase 1 prototype: Fruit Slice. Slice flying fruit with your hands over the live camera picture.

Run from the repo root:   .venv\Scripts\python prototype\fruit_slice.py

Flow (no keyboard needed):
  1. Calibrate: stand in the middle, whole body in view, hold still.
  2. Menu: hold a hand on CLASSIC (60 s, fruit only) or SURVIVAL (bombs end the game).
  3. Raise both hands above your head to start, then 3-2-1.
Keys (for the grown-up): R rotate camera  S skeleton  D debug line  F fullscreen  Ctrl+Q quit
Remote (D-pad): Left/Right pick a game, Down opens Wi-Fi/settings, OK = start. Esc/Back = back.
Settings: prototype/config.toml

Throwaway prototype for game feel (CLAUDE.md Phase 1). Our own code and art; ideas only
from FPTU_Ninja_Fruit_VR (no licence, so nothing copied).

World units: y runs 0..1 down the camera picture, x runs 0..aspect, so sizes and speeds
are in screen-heights whatever the window size.
"""

import functools
import json
import math
import random
import sys
import time
import tomllib
from pathlib import Path

import cv2
import numpy as np
import pygame

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]  # prototype modules + pose_service

import effects  # noqa: E402
import fruits as fr  # noqa: E402
import players  # noqa: E402
import player as pl  # noqa: E402
import theme  # noqa: E402
from console_setup import Setup  # noqa: E402
from network import Network  # noqa: E402
from pose_service.filters import OneEuroFilter  # noqa: E402

SCORES_FILE = HERE / "highscores.json"
OVER_COOLDOWN = 2.0
BOOM_SECONDS = 1.8
STOP_CONSOLE = 10  # exit code for Ctrl+Q: the console launcher stops instead of restarting the game
DEFAULT_TORSO = 0.22  # used until the player's torso has been measured


def seg_dist(p, a, b):
    """Distance from point p to segment a-b."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    k = 0.0 if len2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return math.hypot(px - (ax + k * dx), py - (ay + k * dy))


def load_scores():
    try:
        return {**{"classic": 0, "survival": 0}, **json.loads(SCORES_FILE.read_text())}
    except (OSError, ValueError):
        return {"classic": 0, "survival": 0}


class Hand:
    """One hand: smoothed position, speed and the recent blade trail."""

    def __init__(self, cfg, wrist, pinky, index):
        self.ids = (wrist, pinky, index)
        self.min_vis = cfg["pose"]["min_visibility"]
        self.trail_seconds = cfg["slice"]["trail_seconds"]
        sm = cfg["smoothing"]
        self.fx = OneEuroFilter(sm["min_cutoff"], sm["beta"])
        self.fy = OneEuroFilter(sm["min_cutoff"], sm["beta"])
        self.pos = None
        self.t = None
        self.speed = 0.0
        self.segment = None   # (from, to) moved since the last pose sample
        self.trail = []       # (pos, t, fast)

    def update(self, kp, t, view, cut_speed):
        self.segment = None
        if kp is None or kp[self.ids[0]][2] < self.min_vis:
            # Lost: forget the old position so reappearing doesn't count as a huge swipe.
            self.pos, self.t, self.speed = None, None, 0.0
            self.fx.reset()
            self.fy.reset()
        else:
            # Centre of wrist, pinky and index knuckles: a bit further out than the wrist.
            x, y = view.world(sum(kp[i][0] for i in self.ids) / 3, sum(kp[i][1] for i in self.ids) / 3)
            pos = (self.fx(x, t), self.fy(y, t))
            if self.pos is not None and t > self.t:
                self.speed = math.dist(pos, self.pos) / (t - self.t)
                self.segment = (self.pos, pos)
            self.pos, self.t = pos, t
            self.trail.append((pos, t, self.speed >= cut_speed))
        self.trail = [p for p in self.trail if t - p[1] <= self.trail_seconds]


class Body:
    """Anything that flies: fruit, bombs, fruit halves."""

    def __init__(self, x, y, vx, vy, r, kind=None, **extra):
        self.x, self.y, self.vx, self.vy, self.r, self.kind = x, y, vx, vy, r, kind
        self.angle = random.uniform(0, 360)
        self.spin = random.uniform(-200, 200)  # degrees per second
        self.age = 0.0
        self.__dict__.update(extra)

    def step(self, dt, gravity):
        self.vy += gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.angle += self.spin * dt
        self.age += dt


class Player:
    """One person: colour, hands, body size and score. Slot 0 = BLUE, slot 1 = ORANGE."""

    def __init__(self, cfg, idx):
        self.idx = idx
        self.name, self.glow, self.core = players.COLORS[idx]
        self.hands = [Hand(cfg, pl.L_WRIST, pl.L_PINKY, pl.L_INDEX),
                      Hand(cfg, pl.R_WRIST, pl.R_PINKY, pl.R_INDEX)]
        self.kp = None              # keypoints in the newest frame, None when not in view
        self.last_seen = -1e9
        self.last_x = None
        self.torso = None
        self.score = 0
        self.cut_times = []


class Game:
    """All game state and rules; no drawing. States:
    calibrate -> players (how many?) -> menu -> ready -> countdown -> play -> (boom) -> over -> menu ...
    1 player: BLUE, and the tracker looks for one person only. 2 players: BLUE (left) vs ORANGE (right)."""

    def __init__(self, cfg, scores):
        self.cfg = cfg
        self.g = cfg["game"]
        self.players = [Player(cfg, 0), Player(cfg, 1)][:max(1, cfg["pose"].get("max_players", 1))]
        self.participants = [0]  # slots taking part in the current / last round
        self.n_players = 1       # chosen on the "How many players?" screen
        self.best = scores
        self.state, self.state_t, self.hold = "calibrate", 0.0, 0.0
        self.mode = None
        self.hover = {"classic": 0.0, "survival": 0.0, "players": 0.0, "settings": 0.0, "one": 0.0, "two": 0.0}
        self.want_settings = False
        self.calib_ok, self.calib_msg = False, ""
        self.t = self.last_t = 0.0
        self.view = View()
        self.aspect = self.view.aspect
        self.rotation_locked = True  # mirrors tracker.rotation_locked, set by the main loop
        self.paused = False
        self.missed = 0
        self.new_best = False
        self.winner = self.loser = None
        self.play_time = self.round_end = self.next_wave = 0.0
        self.fruits, self.bombs, self.pieces = [], [], []
        self.fx = effects.Effects()
        self.sounds = []
        self.scale = 720  # pixels per world unit, set by the renderer (for splat sizes)

    # ---- who is playing ----

    @property
    def present(self):
        return [p for p in self.players if p.kp is not None]

    @property
    def active(self):
        return [self.players[i] for i in self.participants]

    @property
    def two_player(self):
        return len(self.participants) == 2

    @property
    def hands(self):
        return [h for p in self.players for h in p.hands]

    @property
    def score(self):
        return self.players[0].score

    @property
    def torso(self):
        return self.players[0].torso

    @property
    def last_seen(self):
        return max(p.last_seen for p in self.players)

    # ---- helpers ----

    def goto(self, state):
        self.state, self.state_t, self.hold, self.paused = state, self.t, 0.0, False

    def cut_speed(self, p):
        return self.cfg["slice"]["speed"] * (p.torso or DEFAULT_TORSO)

    def visible(self, kp, *ids):
        mv = self.cfg["pose"]["min_visibility"]
        return kp is not None and all(kp[i][2] >= mv for i in ids)

    def hands_up(self, kp):
        return (self.visible(kp, pl.NOSE, pl.L_WRIST, pl.R_WRIST)
                and kp[pl.L_WRIST][1] < kp[pl.NOSE][1] and kp[pl.R_WRIST][1] < kp[pl.NOSE][1])

    def torso_length(self, kp):
        if not self.visible(kp, pl.L_SHOULDER, pl.R_SHOULDER, pl.L_HIP, pl.R_HIP):
            return None
        sx, sy = self.view.world((kp[pl.L_SHOULDER][0] + kp[pl.R_SHOULDER][0]) / 2,
                                 (kp[pl.L_SHOULDER][1] + kp[pl.R_SHOULDER][1]) / 2)
        hx, hy = self.view.world((kp[pl.L_HIP][0] + kp[pl.R_HIP][0]) / 2,
                                 (kp[pl.L_HIP][1] + kp[pl.R_HIP][1]) / 2)
        return math.hypot(sx - hx, sy - hy)

    def calib_body(self, kp):
        """Whole body in view at a good distance (not where they stand left/right)."""
        c = self.cfg["calibrate"]
        if not self.visible(kp, pl.NOSE, pl.L_SHOULDER, pl.R_SHOULDER, pl.L_HIP, pl.R_HIP):
            return False, "step back so I can see your whole body"
        if c["need_knees"] and not self.visible(kp, pl.L_KNEE, pl.R_KNEE):
            return False, "step back a little - I need to see your knees"
        torso = self.torso_length(kp)
        if torso > c["max_torso"]:
            return False, "step back a little"
        if torso < c["min_torso"]:
            return False, "come a bit closer"
        return True, ""

    def calib_check(self, kp):
        c = self.cfg["calibrate"]
        if kp is None:
            return False, "Stand in front of the camera"
        ok, msg = self.calib_body(kp)
        if not ok:
            return False, msg[0].upper() + msg[1:]
        off = (kp[pl.L_HIP][0] + kp[pl.R_HIP][0]) / 2 - 0.5
        if abs(off) > c["center_tolerance"]:
            # Mirrored picture: if you appear right of centre, your left is the way to go.
            mirror = self.cfg["camera"]["mirror"]
            go_left = (off > 0) == mirror
            return False, "Step to your left  <<" if go_left else "Step to your right  >>"
        return True, "Perfect! Hold still..."

    def calib_two(self, present):
        for p in present:
            ok, msg = self.calib_body(p.kp)
            if not ok:
                return False, f"{p.name}: {msg}"
        return True, "Two players! Hold still..."

    def menu_zones(self):
        a = self.aspect
        # The strip above head height (change players, Wi-Fi): grown-ups reach it, resting arms never do.
        return {"classic": (0.05 * a, 0.14, 0.47 * a, 0.46),
                "survival": (0.53 * a, 0.14, 0.95 * a, 0.46),
                "players": (0.05 * a, 0.015, 0.47 * a, 0.09),
                "settings": (0.53 * a, 0.015, 0.95 * a, 0.09)}

    def player_zones(self):
        a = self.aspect
        return {"one": (0.05 * a, 0.14, 0.47 * a, 0.46), "two": (0.53 * a, 0.14, 0.95 * a, 0.46)}

    def hover_needed(self, zone):
        m = self.cfg["menu"]
        return m["settings_hover_seconds"] if zone in ("players", "settings") else m["hover_seconds"]

    @property
    def want_people(self):
        """How many people the tracker should look for: both while choosing, then the chosen number."""
        return 2 if self.state in ("calibrate", "players") else self.n_players

    @property
    def solo(self):
        return self.n_players == 1 and self.state not in ("calibrate", "players")

    # ---- update ----

    def pointers(self):
        """Hands as pointers for the setup screens, as (u, v) in 0..1 of the play area.

        Kinect-style: a box in front of the shoulders (two torso-lengths wide, from about head top
        to chest) maps to the whole play area, so every button is reachable with a raised arm,
        and arms hanging at rest are below the box and point at nothing."""
        out = []
        for p in self.present:
            kp, torso = p.kp, p.torso
            if not torso or not self.visible(kp, pl.L_SHOULDER, pl.R_SHOULDER):
                continue
            sx, sy = self.view.world((kp[pl.L_SHOULDER][0] + kp[pl.R_SHOULDER][0]) / 2,
                                     (kp[pl.L_SHOULDER][1] + kp[pl.R_SHOULDER][1]) / 2)
            for hand in p.hands:
                if hand.pos is None:
                    continue
                u = (hand.pos[0] - (sx - torso)) / (2 * torso)
                v = (hand.pos[1] - (sy - 0.9 * torso)) / (1.5 * torso)
                if -0.1 <= u <= 1.1 and -0.15 <= v <= 1.0:
                    out.append((min(max(u, 0.0), 1.0), min(max(v, 0.0), 1.0)))
        return out

    def track(self, people, fresh, t_pose, t, view):
        """Match people to colour slots and follow their hands and body size
        (also used while a setup screen is showing)."""
        dt = 0.0 if not self.last_t else min(t - self.last_t, 0.05)
        self.t, self.last_t, self.view, self.aspect = t, t, view, view.aspect
        if not fresh:
            return dt
        # People far in the background (small torso) aren't players.
        far = self.cfg["calibrate"]["min_torso"] * 0.75
        people = [kp for kp in people if (self.torso_length(kp) or far) >= far][:len(self.players)]
        recent = [p.last_x if t - p.last_seen <= players.FORGET_SECONDS else None for p in self.players]
        if self.solo:  # one player: whoever is in view is BLUE
            people, slots = people[:1], [0] * min(1, len(people))
        else:
            slots = players.assign(recent, [players.body_x(kp) for kp in people])
        found = dict(zip(slots, people))
        for p in self.players:
            p.kp = found.get(p.idx)
            for hand in p.hands:
                hand.update(p.kp, t_pose, view, self.cut_speed(p))
            if p.kp is not None:
                p.last_seen, p.last_x = t, players.body_x(p.kp)
                torso = self.torso_length(p.kp)
                if torso:
                    p.torso = torso if p.torso is None else p.torso * 0.9 + torso * 0.1
        return dt

    def press(self, key):
        """Remote / keyboard shortcuts so the menus also work with a D-pad remote."""
        if self.state == "players":
            n = {pygame.K_LEFT: 1, pygame.K_RIGHT: 2}.get(key)
            if n:
                self.choose_players(n)
        elif self.state == "menu":
            choice = {pygame.K_LEFT: "classic", pygame.K_RIGHT: "survival",
                      pygame.K_UP: "players", pygame.K_DOWN: "settings"}.get(key)
            if choice:
                self.select(choice)
        elif self.state in ("ready", "over") and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.state == "ready":
                self.participants = list(range(self.n_players))
                self.goto("countdown")
                self.sounds.append("beep")
            elif self.t - self.state_t >= OVER_COOLDOWN:
                self.goto("menu")
                self.sounds.append("select")

    def update(self, people, fresh, t_pose, t, view):
        dt = self.track(people, fresh, t_pose, t, view)
        gone = t - self.last_seen  # how long nobody at all has been in view

        getattr(self, "_" + self.state)(fresh, dt, gone)

        if not self.paused:
            # Slow motion for the flying objects only: same arcs, just slower. Frame rate unchanged.
            self.step_bodies(dt * self.g["fruit_speed"])
        self.fx.step(dt, self.g["gravity"])

    def _calibrate(self, fresh, dt, gone):
        if not self.rotation_locked:
            self.calib_ok, self.calib_msg, self.hold = False, "Finding you... stand in front of the camera", 0.0
            return
        present = self.present
        if len(present) == 2:
            self.calib_ok, self.calib_msg = self.calib_two(present)
        else:
            self.calib_ok, self.calib_msg = self.calib_check(present[0].kp if present else None)
        self.hold = self.hold + dt if self.calib_ok else 0.0
        if self.hold >= self.cfg["calibrate"]["hold_seconds"]:
            self.goto("players")
            self.sounds.append("ok")

    def _players(self, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        if len(self.players) < 2:  # max_players = 1 in the config: nothing to choose
            return self.choose_players(1)
        for zone, (x0, y0, x1, y1) in self.player_zones().items():
            inside = any(h.pos and x0 <= h.pos[0] <= x1 and y0 <= h.pos[1] <= y1 for h in self.hands)
            self.hover[zone] = self.hover[zone] + dt if inside else max(0.0, self.hover[zone] - 2 * dt)
            if self.hover[zone] >= self.hover_needed(zone):
                return self.choose_players(1 if zone == "one" else 2)

    def choose_players(self, n):
        self.n_players = n
        self.hover = dict.fromkeys(self.hover, 0.0)
        self.sounds.append("select")
        self.goto("menu")

    def _menu(self, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        for mode, (x0, y0, x1, y1) in self.menu_zones().items():
            inside = any(h.pos and x0 <= h.pos[0] <= x1 and y0 <= h.pos[1] <= y1 for h in self.hands)
            self.hover[mode] = self.hover[mode] + dt if inside else max(0.0, self.hover[mode] - 2 * dt)
            if self.hover[mode] >= self.hover_needed(mode):
                return self.select(mode)

    def select(self, choice):
        self.hover = dict.fromkeys(self.hover, 0.0)
        self.sounds.append("select")
        if choice == "settings":
            self.want_settings = True  # the main loop opens the setup screens
        elif choice == "players":
            self.goto("players")
        else:
            self.mode = choice
            self.goto("ready")

    def _ready(self, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        needed = self.players[:self.n_players]  # BLUE, or BLUE and ORANGE
        all_up = all(p.kp is not None and self.hands_up(p.kp) for p in needed)
        self.hold = self.hold + dt if all_up else 0.0
        if self.hold >= self.g["hands_up_seconds"]:
            self.participants = [p.idx for p in needed]
            self.goto("countdown")
            self.sounds.append("beep")

    def _countdown(self, fresh, dt, gone):
        n = self.g["countdown_seconds"]
        elapsed = self.t - self.state_t
        if int(elapsed + dt) > int(elapsed) and elapsed + dt < n:
            self.sounds.append("beep")
        if elapsed >= n:
            self.start_round()

    def start_round(self):
        self.goto("play")
        self.sounds.append("go")
        for p in self.players:
            p.score, p.cut_times = 0, []
        self.missed = 0
        self.new_best = False
        self.winner = self.loser = None
        self.play_time = 0.0
        self.round_end = self.t + self.cfg["classic"]["round_seconds"]
        self.next_wave = self.t + 0.3
        self.fruits, self.bombs, self.pieces = [], [], []
        self.fx.popup(self.aspect / 2, 0.45, "GO!", (120, 255, 140), "huge", 0.7)

    def _play(self, fresh, dt, gone):
        # Tracking drops a person for a frame now and then (more often with two): only pause
        # when a player has really been gone for a moment.
        grace = self.g.get("pause_after_seconds", 1.0)
        missing = [p for p in self.active if self.t - p.last_seen > grace]
        self.paused = bool(missing)
        if self.paused:  # stop the clock while a player is out of view
            self.round_end += dt
            self.next_wave += dt
            if max(self.t - p.last_seen for p in missing) > 3 * self.cfg["calibrate"]["lost_seconds"]:
                self.paused = False
                self.goto("calibrate")
            return
        self.play_time += dt
        if self.t >= self.next_wave:
            self.spawn_wave()
        if self.mode == "classic" and self.t >= self.round_end:
            return self.game_over()
        if fresh:
            self.check_cuts()
        for b in self.bombs:
            ca, sa = math.cos(math.radians(b.angle)), math.sin(math.radians(b.angle))
            fx, fy = fr.bomb_fuse_tip(b.r)
            self.fx.sparks(b.x + fx * ca + fy * sa, b.y - fx * sa + fy * ca)

    def _boom(self, fresh, dt, gone):
        if self.t - self.state_t >= BOOM_SECONDS:
            self.game_over()

    def _over(self, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        can = self.t - self.state_t >= OVER_COOLDOWN
        anyone_up = any(self.hands_up(p.kp) for p in self.present)
        self.hold = self.hold + dt if can and anyone_up else 0.0
        if self.hold >= self.g["hands_up_seconds"]:
            self.goto("menu")
            self.sounds.append("select")

    def game_over(self):
        self.goto("over")
        self.sounds.append("over")
        if self.two_player:
            self.winner = players.winner([p.score for p in self.players], self.loser)
        top = max(p.score for p in self.active)
        if top > self.best[self.mode]:
            self.best[self.mode] = top
            self.new_best = True
            try:
                SCORES_FILE.write_text(json.dumps(self.best))
            except OSError:
                pass

    # ---- world ----

    def spawn_wave(self):
        g = self.g
        if self.mode == "survival":
            s = self.cfg["survival"]
            k = min(1.0, self.play_time / s["ramp_seconds"])
            every = s["spawn_every_start"] + (s["spawn_every_min"] - s["spawn_every_start"]) * k
            bomb_p = s["bomb_chance_start"] + (s["bomb_chance_max"] - s["bomb_chance_start"]) * k
            count = s["fruits_per_wave"]
        else:
            c = self.cfg["classic"]
            every, bomb_p, count = c["spawn_every"], 0.0, c["fruits_per_wave"]
        self.next_wave = self.t + every
        weights = [k.weight for k in fr.TYPES]
        extra = 1 if self.two_player else 0  # a little more fruit to share between two
        for _ in range(random.randint(count[0], count[1] + extra)):
            is_bomb = random.random() < bomb_p
            kind = None if is_bomb else random.choices(fr.TYPES, weights)[0]
            r = g["fruit_radius"] * (0.95 if is_bomb else kind.size)
            x = random.uniform(r, self.aspect - r)
            vy = -random.uniform(*g["launch_speed"])
            flight = 2 * -vy / g["gravity"]
            target = random.uniform(0.3, 0.7) * self.aspect  # drift toward the middle
            body = Body(x, 1 + r, (target - x) / flight, vy, r, kind)
            if is_bomb:
                body.spin = random.uniform(-60, 60)
                self.bombs.append(body)
            else:
                self.fruits.append(body)

    def step_bodies(self, dt):
        gravity = self.g["gravity"]
        for b in self.fruits + self.bombs + self.pieces:
            b.step(dt, gravity)
        fallen = [f for f in self.fruits if f.vy > 0 and f.y - f.r > 1]
        for f in fallen:
            self.fruits.remove(f)
            self.missed += self.state == "play"
        self.bombs = [b for b in self.bombs if not (b.vy > 0 and b.y - b.r > 1)]
        self.pieces = [p for p in self.pieces if p.age < 1.6 and p.y - p.r < 1.3]

    def check_cuts(self):
        s = self.cfg["slice"]
        for p in self.active:
            speed = self.cut_speed(p)
            for hand in p.hands:
                if hand.segment is None or hand.speed < speed:
                    continue
                a, b = hand.segment
                for bomb in self.bombs:
                    if seg_dist((bomb.x, bomb.y), a, b) <= bomb.r + s["hit_margin"] * 0.5:
                        return self.explode(bomb, p)
                hit = [f for f in self.fruits if seg_dist((f.x, f.y), a, b) <= f.r + s["hit_margin"]]
                if hit:
                    self.fx.slash(a, b)
                for f in hit:
                    self.cut(f, a, b, p)

    def cut(self, f, a, b, p):
        self.fruits.remove(f)
        p.score += f.kind.points
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n  # halves fly apart across the cut line
        cut_deg = math.degrees(math.atan2(-dy, dx))
        for side in (1, -1):
            self.pieces.append(Body(f.x, f.y, f.vx + side * nx * 0.45, f.vy + side * ny * 0.45 - 0.15,
                                    f.r, f.kind, side=side))
            self.pieces[-1].angle = cut_deg + 90
            self.pieces[-1].spin = side * random.uniform(90, 200)
        self.fx.juice(f.x, f.y, f.kind.juice, dx / n, dy / n)
        self.fx.splat(f.x, f.y, f.kind.juice, f.r, self.scale)
        self.fx.popup(f.x, f.y, f"+{f.kind.points}", p.glow if self.two_player else (255, 255, 140))
        self.sounds.append("slice")

        window = self.cfg["slice"]["combo_seconds"]
        p.cut_times = [ct for ct in p.cut_times if self.t - ct <= window] + [self.t]
        if len(p.cut_times) >= 3:
            p.score += 1
            who = f"{p.name} " if self.two_player else ""
            self.fx.popup(self.aspect / 2, 0.25, f"{who}COMBO x{len(p.cut_times)}!",
                          p.glow if self.two_player else (255, 120, 220), "big", 1.0)
            self.sounds.append("combo")

    def explode(self, bomb, p):
        self.bombs.remove(bomb)
        self.loser = p.idx
        self.fx.explosion(bomb.x, bomb.y)
        self.sounds.append("boom")
        self.goto("boom")


# ---------------------------------------------------------------- sound

def make_sounds():
    """Synthesised sound effects; the game runs silently if audio is unavailable."""
    try:
        sr, _, channels = pygame.mixer.get_init()
    except (TypeError, pygame.error):
        return {}
    rng = np.random.default_rng(1)

    def secs(d):
        return np.arange(int(sr * d)) / sr

    def tone(freq, d, decay=8.0):
        t = secs(d)
        return np.sin(2 * np.pi * freq * t) * np.exp(-t * decay) * np.minimum(1, t * 200)

    def snd(wave, vol=0.6):
        a = (np.clip(wave, -1, 1) * 32767 * vol).astype(np.int16)
        if channels == 2:
            a = np.column_stack([a, a])
        return pygame.sndarray.make_sound(np.ascontiguousarray(a))

    t = secs(0.2)
    swish = rng.uniform(-1, 1, t.size) * np.exp(-t * 20) * np.sin(np.pi * t / t[-1])
    splat = np.convolve(rng.uniform(-1, 1, t.size), np.ones(12) / 4, "same") * np.exp(-t * 30)
    tb = secs(1.4)
    rumble = np.convolve(rng.uniform(-1, 1, tb.size), np.ones(40) / 8, "same")
    boom = (rumble + np.sin(2 * np.pi * 50 * tb)) * np.exp(-tb * 2.5)
    return {
        "slice": snd(swish * 0.8 + splat * 0.6),
        "boom": snd(boom, 0.9),
        "beep": snd(tone(660, 0.15, 12)),
        "go": snd(np.concatenate([tone(660, 0.1, 10), tone(990, 0.35, 5)])),
        "select": snd(np.concatenate([tone(523, 0.08, 10), tone(784, 0.2, 8)])),
        "ok": snd(np.concatenate([tone(587, 0.08, 10), tone(740, 0.08, 10), tone(880, 0.25, 6)])),
        "combo": snd(np.concatenate([tone(f, 0.07, 12) for f in (784, 988, 1175, 1568)])),
        "over": snd(np.concatenate([tone(f, 0.18, 6) for f in (523, 440, 349)])),
    }


# ---------------------------------------------------------------- drawing

class View:
    """Which part of the camera picture the play area shows, and how keypoints (0..1 of the whole
    picture) map to world units (y 0..1 down the play area, x 0..aspect across it).

    A play area wider than the (portrait) picture shows a band of it: the full width, with a little
    trimmed off the top and more off the bottom (feet matter least). Pose still runs on the
    whole picture, so nothing is lost for tracking."""

    def __init__(self, x0=0.0, y0=0.0, w=1.0, h=1.0, aspect=9 / 16):
        self.x0, self.y0, self.w, self.h, self.aspect = x0, y0, w, h, aspect

    @classmethod
    def fit(cls, frame_aspect, play_aspect, top_share):
        if not play_aspect or abs(play_aspect - frame_aspect) < 1e-3:
            return cls(aspect=frame_aspect)
        if play_aspect > frame_aspect:  # wider than the picture: keep width, trim height
            h = frame_aspect / play_aspect
            return cls(y0=(1 - h) * top_share, h=h, aspect=play_aspect)
        w = play_aspect / frame_aspect  # narrower: keep height, trim the sides evenly
        return cls(x0=(1 - w) / 2, w=w, aspect=play_aspect)

    def world(self, x, y):
        return (x - self.x0) / self.w * self.aspect, (y - self.y0) / self.h

    def crop(self, frame):
        fh, fw = frame.shape[:2]
        return frame[int(self.y0 * fh):int((self.y0 + self.h) * fh), int(self.x0 * fw):int((self.x0 + self.w) * fw)]


def layout(frame, screen, cfg):
    """Play-area rectangle (largest that fits inside the bamboo frame) and its View."""
    g = cfg["game"]
    sw, sh = screen.get_size()
    margin = theme.frame_thickness(sh) + max(10, sh // 50)
    fh, fw = frame.shape[:2] if frame is not None else (16, 9)
    # Portrait camera: widen to at least play_aspect. Landscape camera (two players): keep nearly
    # the full width, but at most max_play_aspect so the side panels (scores) still fit.
    frame_aspect = fw / fh
    target = min(max(frame_aspect, g.get("play_aspect", 0) or frame_aspect), g.get("max_play_aspect", 99))
    view = View.fit(frame_aspect, target, g.get("crop_top_share", 0.4))
    s = min((sw - 2 * margin) / view.aspect, sh - 2 * margin)
    w, h = int(view.aspect * s), int(s)
    return pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h), view


class Renderer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.art = fr.Art()
        self.backdrop_key = None
        self.backdrop = None
        self.layer = None
        self.dim = None
        self.cam_surf = None
        self.show_skeleton = False
        self.show_debug = True
        self.later = []  # in-picture text, drawn after the alpha layer
        self.no_signal = False
        self.camera_status = ""

    def popup_font(self, size, grow):
        h = self.rect.h
        base = {"mid": h / 14, "big": h / 10, "huge": h / 5}[size]
        return theme.font(int(base * (0.5 + 0.5 * grow)))

    def draw(self, screen, game, tracker, frame, fresh, people, fps, rect, view, overlay=None):
        """overlay: a setup screen (Wi-Fi etc.) drawn in the play area instead of the game."""
        self.rect = rect
        key = (screen.get_size(), tuple(rect))
        if key != self.backdrop_key:
            self.backdrop_key = key
            self.backdrop = theme.build_backdrop(screen.get_size(), rect)
            self.layer = pygame.Surface(rect.size, pygame.SRCALPHA)
            self.dim = pygame.Surface(rect.size, pygame.SRCALPHA)
            self.dim.fill((0, 0, 0, 110))
            self.cam_surf = None
        screen.blit(self.backdrop, (0, 0))
        self.no_signal = not getattr(tracker, "signal", True)
        camera = getattr(tracker, "camera", None)
        self.camera_status = camera.status if camera is not None and camera.connected is False else "no picture yet"
        if self.no_signal:
            self.cam_surf = None
            screen.fill((10, 8, 6), rect)
        if frame is not None and (fresh or self.cam_surf is None):
            rgb = cv2.cvtColor(cv2.resize(view.crop(frame), rect.size), cv2.COLOR_BGR2RGB)
            self.cam_surf = pygame.image.frombuffer(rgb.tobytes(), rect.size, "RGB")
        if self.cam_surf is not None:
            screen.blit(self.cam_surf, rect)

        scale = rect.h
        game.scale = scale
        sx, sy = game.fx.shake_offset()

        def to_px(x, y):
            return int(rect.x + (x + sx) * scale), int(rect.y + (y + sy) * scale)

        def to_layer(x, y):
            return int(x * scale), int(y * scale)

        screen.set_clip(rect)
        if overlay is not None:
            screen.blit(self.dim, rect)
            screen.blit(self.dim, rect)  # twice: setup text needs a darker picture behind it
            overlay.draw(screen, rect)
            screen.set_clip(None)
            self.draw_panels(screen, game, tracker, rect, fps, hint="Settings")
            return
        if game.state not in ("play", "boom"):
            screen.blit(self.dim, rect)
        if self.show_skeleton or game.state == "calibrate":
            for p in game.players:
                self.draw_skeleton(screen, p.kp, view, to_px, p.glow if len(game.present) > 1 else (120, 255, 170))

        game.fx.draw_back(screen, to_px)
        for p in game.pieces:
            surf = self.art.get(p.kind, max(4, int(p.r * scale)), "cut")
            if p.side < 0:
                surf = pygame.transform.flip(surf, True, False)
            self.blit_rotated(screen, surf, p, to_px)
        for f in game.fruits:
            self.blit_rotated(screen, self.art.get(f.kind, max(4, int(f.r * scale)), "whole"), f, to_px)
        for b in game.bombs:
            pulse = 0.5 + 0.5 * math.sin(game.t * 12)
            pygame.draw.circle(screen, (255, 40 + int(60 * pulse), 30), to_px(b.x, b.y),
                               int(b.r * scale * (1.15 + 0.1 * pulse)), max(2, int(scale * 0.006)))
            self.blit_rotated(screen, self.art.get(None, max(4, int(b.r * scale)), "bomb"), b, to_px)
        game.fx.draw_front(screen, to_px, scale, self.popup_font)

        self.layer.fill((0, 0, 0, 0))
        self.draw_blades(game, to_layer, scale)
        self.draw_state(screen, game, rect, to_px, to_layer, scale)
        screen.blit(self.layer, rect)
        for draw_text in self.later:  # text goes on top of the layer's boxes and rings
            draw_text()
        self.later.clear()
        if game.fx.flash > 0:
            white = pygame.Surface(rect.size)
            white.fill((255, 250, 235))
            white.set_alpha(int(255 * min(1.0, game.fx.flash)))
            screen.blit(white, rect)
        screen.set_clip(None)

        self.draw_panels(screen, game, tracker, rect, fps)
        if theme.panels(screen.get_size(), rect)[0] is None:
            self.draw_corner_scores(screen, game, rect)

    @staticmethod
    def draw_corner_scores(screen, game, rect):
        """Scores in the play area's top corners, for screens too narrow for the side panels."""
        if game.state not in ("countdown", "play", "boom", "over"):
            return
        f = theme.font(rect.h * 0.06)
        b = game.players[0]
        if game.two_player:
            o = game.players[1]
            theme.text(screen, f, f"{b.name} {b.score}", b.glow, topleft=(rect.x + 14, rect.y + 10))
            theme.text(screen, f, f"{o.name} {o.score}", o.glow, topright=(rect.right - 14, rect.y + 10))
        else:
            theme.text(screen, f, f"SCORE {b.score}", theme.GOLD, topleft=(rect.x + 14, rect.y + 10))

    @staticmethod
    def blit_rotated(screen, surf, body, to_px):
        surf = pygame.transform.rotate(surf, body.angle)
        screen.blit(surf, surf.get_rect(center=to_px(body.x, body.y)))

    @staticmethod
    def draw_skeleton(screen, kp, view, to_px, color):
        if kp is None:
            return
        for a, b in pl.BONES:
            if kp[a][2] > 0.4 and kp[b][2] > 0.4:
                pygame.draw.line(screen, color, to_px(*view.world(kp[a][0], kp[a][1])),
                                 to_px(*view.world(kp[b][0], kp[b][1])), 3)

    def draw_blades(self, game, to_layer, scale):
        """Glowing blade trail: wide faint glow under a thin bright core, tapering with age.
        Each player's blade has their colour once two are in view."""
        two = len(game.present) > 1 or game.two_player
        for p, hand in ((p, h) for p in game.players for h in p.hands):
            glow, core = (p.glow, p.core) if two else ((90, 200, 255), (240, 252, 255))
            pts = hand.trail
            for (p0, t0, fast), (p1, _, _) in zip(pts, pts[1:]):
                life = max(0.0, 1 - (game.t - t0) / hand.trail_seconds)
                w = max(2, int(scale * 0.03 * life))
                if fast:
                    pygame.draw.line(self.layer, (*glow, int(110 * life)), to_layer(*p0), to_layer(*p1), w * 3)
                    pygame.draw.line(self.layer, (*core, int(255 * life)), to_layer(*p0), to_layer(*p1), w)
                else:
                    pygame.draw.line(self.layer, (255, 255, 255, int(90 * life)), to_layer(*p0), to_layer(*p1), w)
            if hand.pos is not None:
                pygame.draw.circle(self.layer, (*(glow if two else (255, 255, 255)), 220),
                                   to_layer(*hand.pos), int(scale * 0.028), 4 if two else 3)

    def zone_box(self, game, zone, area, to_layer, scale):
        """A hover box like the menu's, filling up while a hand is held on it."""
        x0, y0, x1, y1 = area
        box = pygame.Rect(to_layer(x0, y0), (int((x1 - x0) * scale), int((y1 - y0) * scale)))
        frac = game.hover[zone] / game.hover_needed(zone)
        pygame.draw.rect(self.layer, (20, 10, 5, 190), box, border_radius=16)
        fill = box.copy()
        fill.h = int(box.h * min(1.0, frac))
        fill.bottom = box.bottom
        pygame.draw.rect(self.layer, (240, 195, 80, 150), fill, border_radius=16)
        pygame.draw.rect(self.layer, (240, 195, 80, 255), box, 3, border_radius=16)
        return box

    def person_icon(self, cx, cy, size, color):
        pygame.draw.circle(self.layer, (*color, 255), (cx, cy - size * 0.55), size * 0.28)
        body = pygame.Rect(0, 0, size * 0.7, size * 0.75)
        body.midtop = (cx, cy - size * 0.2)
        pygame.draw.rect(self.layer, (*color, 255), body, border_radius=int(size * 0.3))

    def ring(self, center, radius, frac, color=(255, 215, 80), width=8):
        box = pygame.Rect(0, 0, 2 * radius, 2 * radius)
        box.center = center
        pygame.draw.circle(self.layer, (0, 0, 0, 120), center, radius, width)
        if frac > 0:
            pygame.draw.arc(self.layer, color, box, math.pi / 2, math.pi / 2 + min(1.0, frac) * 2 * math.pi, width)

    def message(self, screen, rect, msg, y, size, color=theme.CREAM):
        f = theme.font(rect.h * size)
        for i, line in enumerate(theme.wrap(f, msg, rect.w * 0.9)):
            self.later.append(functools.partial(
                theme.text, screen, f, line, color,
                center=(rect.centerx, int(rect.y + rect.h * y) + i * f.get_height())))

    def draw_state(self, screen, game, rect, to_px, to_layer, scale):
        st, a = game.state, game.aspect
        if self.no_signal:
            dots = "." * (1 + int(game.t * 2) % 3)
            self.message(screen, rect, f"Connecting to the camera{dots}", 0.4, 0.055, theme.GOLD)
            self.message(screen, rect, "Plug in the phone and open DroidCam", 0.55, 0.04)
            self.message(screen, rect, f"({self.camera_status})", 0.68, 0.03, (200, 190, 170))
            return
        if st == "calibrate":
            color = ((120, 255, 140) if game.calib_ok else (255, 200, 80)) if game.rotation_locked else (220, 220, 220)
            two = len(game.present) > 1
            spots = (0.28 * a, 0.72 * a) if two else (a / 2,)
            for cx in spots:
                self.silhouette(to_layer, cx, scale, (*color, 210), 0.75 if two else 1.0)
                if game.calib_ok:
                    self.ring(to_layer(cx, 0.15), int(scale * 0.09),
                              game.hold / self.cfg["calibrate"]["hold_seconds"], (120, 255, 140))
            self.message(screen, rect, "Stand side by side" if two else "Stand in the middle", 0.04, 0.06, theme.GOLD)
            self.message(screen, rect, game.calib_msg, 0.84, 0.05)
        elif st == "players":
            for zone, (x0, y0, x1, y1) in game.player_zones().items():
                box = self.zone_box(game, zone, (x0, y0, x1, y1), to_layer, scale)
                two = zone == "two"
                icons = [(0.38, game.players[0].glow), (0.62, game.players[-1].glow)] if two else [(0.5, game.players[0].glow)]
                for fx, color in icons:
                    self.person_icon(box.x + box.w * fx, box.y + box.h * 0.4, box.h * 0.22, color)
                self.later.append(functools.partial(
                    theme.text, screen, theme.font(scale * 0.045), "2 PLAYERS" if two else "1 PLAYER", theme.GOLD,
                    center=(rect.x + box.centerx, rect.y + box.y + int(box.h * 0.8))))
            self.message(screen, rect, "How many players?", 0.04, 0.06, theme.GOLD)
            self.message(screen, rect, "Hold your hand on one", 0.6, 0.045)
        elif st == "menu":
            for mode, (x0, y0, x1, y1) in game.menu_zones().items():
                box = pygame.Rect(to_layer(x0, y0), (int((x1 - x0) * scale), int((y1 - y0) * scale)))
                frac = game.hover[mode] / game.hover_needed(mode)
                pygame.draw.rect(self.layer, (20, 10, 5, 190), box, border_radius=16)
                fill = box.copy()
                fill.h = int(box.h * min(1.0, frac))
                fill.bottom = box.bottom
                pygame.draw.rect(self.layer, (240, 195, 80, 150), fill, border_radius=16)
                pygame.draw.rect(self.layer, (240, 195, 80, 255), box, 3, border_radius=16)
                cx = rect.x + box.centerx
                if mode in ("players", "settings"):
                    label = f"PLAYERS: {game.n_players}" if mode == "players" else "WI-FI / SETTINGS"
                    self.later.append(functools.partial(
                        theme.text, screen, theme.font(scale * 0.028), label, theme.CREAM,
                        center=(cx, rect.y + box.centery)))
                    continue
                icon = (self.art.get(fr.TYPES[9], int(scale * 0.06), "whole") if mode == "classic"
                        else self.art.get(None, int(scale * 0.055), "bomb"))
                self.layer.blit(icon, icon.get_rect(center=(box.centerx, box.y + box.h * 0.38)))
                self.later.append(functools.partial(
                    theme.text, screen, theme.font(scale * 0.045), mode.upper(), theme.GOLD,
                    center=(cx, rect.y + box.y + int(box.h * 0.72))))
                sub = "60 seconds" if mode == "classic" else "watch out!"
                self.later.append(functools.partial(
                    theme.text, screen, theme.font(scale * 0.028, name="arial"), sub,
                    center=(cx, rect.y + box.y + int(box.h * 0.88))))
            self.message(screen, rect, "Hold your hand on a game to pick it", 0.68, 0.045)
        elif st == "ready":
            self.message(screen, rect, game.mode.upper(), 0.12, 0.08, theme.GOLD)
            two = game.n_players == 2
            if two and len(game.present) < 2:
                msg = "Waiting for a second player..."
            else:
                msg = "Both players: raise both hands to start!" if two else "Raise both hands above your head to start!"
            self.message(screen, rect, msg, 0.75, 0.05)
            for p in game.present:
                for hand in p.hands:
                    if hand.pos is not None:
                        self.ring(to_layer(*hand.pos), int(scale * 0.06),
                                  game.hold / self.cfg["game"]["hands_up_seconds"], p.glow if two else (255, 215, 80))
        elif st == "countdown":
            left = self.cfg["game"]["countdown_seconds"] - (game.t - game.state_t)
            k = left - math.floor(left)  # 1 -> 0 within each second
            f = theme.font(scale * (0.2 + 0.15 * k))
            self.later.append(functools.partial(
                theme.text, screen, f, str(max(1, math.ceil(left))), theme.GOLD, outline=4, center=rect.center))
        elif st == "play" and game.paused:
            self.message(screen, rect, "Paused - come back in front of the camera", 0.45, 0.055, theme.GOLD)
        if st in ("play", "boom") and game.two_player:
            if game.mode == "classic":
                secs_left = max(0, math.ceil(game.round_end - game.t))
                clock, color = str(secs_left), ((255, 110, 90) if secs_left <= 10 else theme.CREAM)
            else:
                secs = int(game.play_time)
                clock, color = f"{secs // 60}:{secs % 60:02d}", theme.CREAM
            self.message(screen, rect, clock, 0.05, 0.06, color)
        elif st == "over":
            if game.two_player:
                if game.winner == -1:
                    title, color = "DRAW!", theme.GOLD
                else:
                    w = game.players[game.winner]
                    title, color = f"{w.name} WINS!", w.glow
                self.message(screen, rect, title, 0.12, 0.09, color)
                if game.loser is not None:
                    self.message(screen, rect, f"{game.players[game.loser].name} hit a bomb", 0.24, 0.045,
                                 (255, 120, 90))
                b, o = game.players
                self.message(screen, rect, f"{b.score}  :  {o.score}", 0.34, 0.09, theme.CREAM)
            else:
                title = "BOOM!" if game.mode == "survival" else "TIME UP!"
                self.message(screen, rect, title, 0.14, 0.1, (255, 120, 90))
                self.message(screen, rect, f"Score {game.score}", 0.33, 0.08, theme.GOLD)
            if game.new_best and int(game.t * 3) % 2 == 0:
                self.message(screen, rect, "NEW BEST!", 0.46, 0.06, (120, 255, 140))
            if game.t - game.state_t >= OVER_COOLDOWN:
                self.message(screen, rect, "Raise both hands for the menu", 0.75, 0.05)
                for p in game.present:
                    for hand in p.hands:
                        if hand.pos is not None:
                            self.ring(to_layer(*hand.pos), int(scale * 0.06),
                                      game.hold / self.cfg["game"]["hands_up_seconds"])

    def silhouette(self, to_layer, cx, scale, color, k=1.0):
        """Outline of a person centred at cx: where to stand (k narrows it for two players)."""
        w = max(3, int(scale * 0.01))
        pygame.draw.circle(self.layer, color, to_layer(cx, 0.15), int(scale * 0.06 * k), w)
        body = [(cx - 0.11 * k, 0.25), (cx + 0.11 * k, 0.25), (cx + 0.08 * k, 0.55), (cx - 0.08 * k, 0.55)]
        pygame.draw.polygon(self.layer, color, [to_layer(*p) for p in body], w)
        for side in (-1, 1):
            pygame.draw.line(self.layer, color, to_layer(cx + side * 0.11 * k, 0.26),
                             to_layer(cx + side * 0.17 * k, 0.52), w)
            pygame.draw.line(self.layer, color, to_layer(cx + side * 0.06 * k, 0.55),
                             to_layer(cx + side * 0.08 * k, 0.93), w)

    def draw_panels(self, screen, game, tracker, rect, fps, hint=None):
        left, right = theme.panels(screen.get_size(), rect)
        lh, rh = game.players[0].hands
        versus = game.two_player and game.state in ("countdown", "play", "boom", "over")
        if left:
            y = left.y + 30
            for line in ("FRUIT", "SLICE"):
                r = theme.text(screen, theme.font(left.w * 0.24), line, theme.GOLD, outline=3,
                               midtop=(left.centerx, y))
                y = r.bottom - 4
            if game.mode:
                theme.text(screen, theme.font(left.w * 0.09), game.mode.upper(), midtop=(left.centerx, y + 12))
            label, color = (game.players[0].name, game.players[0].glow) if versus else ("SCORE", theme.GOLD)
            theme.text(screen, theme.font(left.w * 0.08, name="arial"), label, color if versus else theme.CREAM,
                       midtop=(left.centerx, left.y + left.h * 0.56))
            theme.text(screen, theme.font(left.w * 0.26), str(game.score), color, outline=3,
                       midtop=(left.centerx, left.y + left.h * 0.61))
            if game.mode:
                theme.text(screen, theme.font(left.w * 0.07, name="arial"), f"BEST  {game.best[game.mode]}",
                           midtop=(left.centerx, left.y + left.h * 0.88))
        if right:
            if versus:
                o = game.players[1]
                label, value = o.name, str(o.score)
            elif game.state in ("play", "boom", "over") and game.mode == "classic":
                label, value = "TIME", str(max(0, math.ceil(game.round_end - game.t)) if game.state == "play" else 0)
            elif game.mode == "survival" and game.state in ("play", "boom", "over"):
                secs = int(game.play_time)
                label, value = "SURVIVED", f"{secs // 60}:{secs % 60:02d}"
            else:
                label, value = "", ""
            if label:
                urgent = not versus and game.mode == "classic" and game.state == "play" and game.round_end - game.t <= 10
                color = game.players[1].glow if versus else ((255, 110, 90) if urgent else theme.GOLD)
                theme.text(screen, theme.font(right.w * 0.09, name="arial"), label, color if versus else theme.CREAM,
                           midtop=(right.centerx, right.y + 30))
                theme.text(screen, theme.font(right.w * 0.3), value, color,
                           outline=3, midtop=(right.centerx, right.y + 30 + right.w * 0.12))
            if not versus and game.mode == "classic" and game.state in ("play", "over"):
                theme.text(screen, theme.font(right.w * 0.08, name="arial"), f"missed {game.missed}",
                           midtop=(right.centerx, right.y + right.h * 0.45))
            hint = hint or {"calibrate": "Stand in the middle", "players": "How many?",
                            "menu": "Pick a game", "ready": "Hands up!",
                            "countdown": "Get ready...", "play": "Slice!", "boom": "Ouch!",
                            "over": "Well done!"}[game.state]
            theme.text(screen, theme.font(right.w * 0.11), hint, theme.CREAM, midtop=(right.centerx, right.y + right.h * 0.58))
            if self.show_debug:
                f = theme.font(max(11, right.w // 22), bold=False, name="consolas")
                lines = [f"fps {fps:4.1f}  pose {tracker.pose_ms:4.1f} ms",
                         f"hand L {lh.speed / (game.torso or DEFAULT_TORSO):3.1f}  R {rh.speed / (game.torso or DEFAULT_TORSO):3.1f}",
                         f"cut >= {self.cfg['slice']['speed']} torso/s",
                         f"torso {game.torso or 0:.2f}  rotate {tracker.rotate}",
                         f"people {len(game.present)}"]
                for i, line in enumerate(lines):
                    theme.text(screen, f, line, (200, 190, 170), outline=1,
                               bottomleft=(right.x + 14, right.bottom - 14 - (len(lines) - 1 - i) * f.get_height()))


# ---------------------------------------------------------------- main loop

def merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config():
    """config.toml, then config.local.toml (not in git) for per-machine settings such as
    fullscreen on the console or a different camera index."""
    def read(path):  # utf-8-sig: Windows PowerShell writes a byte-order mark that TOML rejects
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))

    cfg = read(HERE / "config.toml")
    local = HERE / "config.local.toml"
    if local.exists():
        merge(cfg, read(local))
    return cfg


def keep_display_awake():
    """Stop Windows blanking the TV or sleeping while the game runs (no system setting changed)."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)


def main():
    cfg = load_config()
    g = cfg["game"]

    pygame.mixer.pre_init(22050, -16, 2, 256)  # small buffer = less sound delay
    pygame.init()
    pygame.display.set_caption("Fruit Slice (prototype)")
    windowed = (g["window_width"], g["window_height"])
    fullscreen = g["fullscreen"]
    keep_display_awake()

    def set_mode():
        # Always draw at window size (720p); SCALED lets the GPU scale it to a full screen.
        # Drawing at the screen's own size costs a lot of CPU on a 4K TV and starves pose tracking.
        pygame.mouse.set_visible(not fullscreen)
        return pygame.display.set_mode(windowed, pygame.SCALED | (pygame.FULLSCREEN if fullscreen else 0))

    screen = set_mode()
    tracker = pl.PoseTracker(cfg)
    game = Game(cfg, load_scores())
    renderer = Renderer(cfg)
    net = Network(cfg["network"]["backend"])
    setup = Setup(cfg, net)
    if net.available and cfg["network"]["show_at_startup"]:
        setup.open()
    sounds = make_sounds()
    clock = pygame.time.Clock()
    last_seq = 0
    perf_log = HERE.parent / "logs" / "perf.log"  # read remotely to check the box keeps up
    next_perf = time.perf_counter() + 30

    try:
        running = True
        stop_console = False
        while running:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type != pygame.KEYDOWN:
                    continue
                # Quit is Ctrl+Q only: a remote's Back button sends Esc, which must not end the console.
                elif event.key == pygame.K_q and event.mod & pygame.KMOD_CTRL:
                    running, stop_console = False, True
                elif setup.active:
                    continue  # the setup screens use the keys themselves (typing a password)
                elif event.key == pygame.K_r:
                    tracker.cycle_rotation()
                elif event.key == pygame.K_s:
                    renderer.show_skeleton = not renderer.show_skeleton
                elif event.key == pygame.K_d:
                    renderer.show_debug = not renderer.show_debug
                elif event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    pygame.display.toggle_fullscreen()  # same 720p drawing size, so no new window
                    pygame.mouse.set_visible(not fullscreen)
                else:
                    game.press(event.key)

            seq, frame, people, t_pose = tracker.latest()
            fresh = seq != last_seq
            last_seq = seq
            rect, view = layout(frame, screen, cfg)
            game.rotation_locked = tracker.rotation_locked
            tracker.want_people = game.want_people
            now = time.perf_counter()
            if setup.active:
                dt = game.track(people, fresh, t_pose, now, view)
                hands_px = [(int(rect.x + u * rect.w), int(rect.y + v * rect.h)) for u, v in game.pointers()]
                setup.update(rect, hands_px, events, dt)
            else:
                game.update(people, fresh, t_pose, now, view)
                if game.want_settings:
                    game.want_settings = False
                    if net.available:
                        setup.open()
            for name in game.sounds:
                if name in sounds:
                    sounds[name].play()
            game.sounds.clear()

            # Full screen hides the mouse pointer during play; show it on the setup screens,
            # where a plugged-in mouse is one of the ways to press buttons.
            if fullscreen and pygame.mouse.get_visible() != setup.active:
                pygame.mouse.set_visible(setup.active)
            renderer.draw(screen, game, tracker, frame, fresh, people, clock.get_fps(), rect, view,
                          overlay=setup if setup.active else None)
            pygame.display.flip()
            if now >= next_perf:
                next_perf = now + 30
                try:
                    perf_log.parent.mkdir(exist_ok=True)
                    with open(perf_log, "a") as f:
                        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} fps {clock.get_fps():.1f} "
                                f"pose_ms {tracker.pose_ms:.1f} people {len(game.present)} state {game.state} "
                                f"players {len(game.participants)}\n")
                except OSError:
                    pass
            clock.tick(60)
    finally:
        tracker.close()
        pygame.quit()
    # Any other ending (an update stopping the game, a crash, a stop signal that SDL turns into a
    # normal quit) returns 0 and the console launcher simply starts the game again.
    return STOP_CONSOLE if stop_console else 0


if __name__ == "__main__":
    sys.exit(main())
