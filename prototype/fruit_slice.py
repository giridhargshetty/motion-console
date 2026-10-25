r"""Phase 1 prototype: Fruit Slice. Slice flying fruit with your hands over the live camera picture.

Run from the repo root:   .venv\Scripts\python prototype\fruit_slice.py

Flow (no keyboard needed):
  1. Calibrate: stand in the middle, whole body in view, hold still.
  2. Menu: hold a hand on CLASSIC (60 s, fruit only) or SURVIVAL (bombs end the game).
  3. Raise both hands above your head to start, then 3-2-1.
Keys (for the grown-up): R rotate camera  S skeleton  D debug line  F fullscreen  Esc quit
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
import player as pl  # noqa: E402
import theme  # noqa: E402
from pose_service.filters import OneEuroFilter  # noqa: E402

SCORES_FILE = HERE / "highscores.json"
OVER_COOLDOWN = 2.0
BOOM_SECONDS = 1.8
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

    def update(self, kp, t, aspect, cut_speed):
        self.segment = None
        if kp is None or kp[self.ids[0]][2] < self.min_vis:
            # Lost: forget the old position so reappearing doesn't count as a huge swipe.
            self.pos, self.t, self.speed = None, None, 0.0
            self.fx.reset()
            self.fy.reset()
        else:
            # Centre of wrist, pinky and index knuckles: a bit further out than the wrist.
            x = sum(kp[i][0] for i in self.ids) / 3 * aspect
            y = sum(kp[i][1] for i in self.ids) / 3
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


class Game:
    """All game state and rules; no drawing. States:
    calibrate -> menu -> ready -> countdown -> play -> (boom) -> over -> menu ..."""

    def __init__(self, cfg, scores):
        self.cfg = cfg
        self.g = cfg["game"]
        self.hands = [Hand(cfg, pl.L_WRIST, pl.L_PINKY, pl.L_INDEX),
                      Hand(cfg, pl.R_WRIST, pl.R_PINKY, pl.R_INDEX)]
        self.best = scores
        self.state, self.state_t, self.hold = "calibrate", 0.0, 0.0
        self.mode = None
        self.hover = {"classic": 0.0, "survival": 0.0}
        self.calib_ok, self.calib_msg = False, ""
        self.torso = None
        self.t = self.last_t = 0.0
        self.last_seen = 0.0
        self.aspect = 9 / 16
        self.rotation_locked = True  # mirrors tracker.rotation_locked, set by the main loop
        self.paused = False
        self.score = self.missed = 0
        self.new_best = False
        self.play_time = self.round_end = self.next_wave = 0.0
        self.cut_times = []
        self.fruits, self.bombs, self.pieces = [], [], []
        self.fx = effects.Effects()
        self.sounds = []
        self.scale = 720  # pixels per world unit, set by the renderer (for splat sizes)

    # ---- helpers ----

    def goto(self, state):
        self.state, self.state_t, self.hold, self.paused = state, self.t, 0.0, False

    def cut_speed(self):
        return self.cfg["slice"]["speed"] * (self.torso or DEFAULT_TORSO)

    def visible(self, kp, *ids):
        mv = self.cfg["pose"]["min_visibility"]
        return kp is not None and all(kp[i][2] >= mv for i in ids)

    def hands_up(self, kp):
        return (self.visible(kp, pl.NOSE, pl.L_WRIST, pl.R_WRIST)
                and kp[pl.L_WRIST][1] < kp[pl.NOSE][1] and kp[pl.R_WRIST][1] < kp[pl.NOSE][1])

    def torso_length(self, kp):
        if not self.visible(kp, pl.L_SHOULDER, pl.R_SHOULDER, pl.L_HIP, pl.R_HIP):
            return None
        a = self.aspect
        sx = (kp[pl.L_SHOULDER][0] + kp[pl.R_SHOULDER][0]) / 2 * a
        sy = (kp[pl.L_SHOULDER][1] + kp[pl.R_SHOULDER][1]) / 2
        hx = (kp[pl.L_HIP][0] + kp[pl.R_HIP][0]) / 2 * a
        hy = (kp[pl.L_HIP][1] + kp[pl.R_HIP][1]) / 2
        return math.hypot(sx - hx, sy - hy)

    def calib_check(self, kp):
        c = self.cfg["calibrate"]
        if kp is None:
            return False, "Stand in front of the camera"
        if not self.visible(kp, pl.NOSE, pl.L_SHOULDER, pl.R_SHOULDER, pl.L_HIP, pl.R_HIP):
            return False, "Step back so I can see your whole body"
        if c["need_knees"] and not self.visible(kp, pl.L_KNEE, pl.R_KNEE):
            return False, "Step back a little - I need to see your knees"
        torso = self.torso_length(kp)
        if torso > c["max_torso"]:
            return False, "Step back a little"
        if torso < c["min_torso"]:
            return False, "Come a bit closer"
        off = (kp[pl.L_HIP][0] + kp[pl.R_HIP][0]) / 2 - 0.5
        if abs(off) > c["center_tolerance"]:
            # Mirrored picture: if you appear right of centre, your left is the way to go.
            mirror = self.cfg["camera"]["mirror"]
            go_left = (off > 0) == mirror
            return False, "Step to your left  <<" if go_left else "Step to your right  >>"
        return True, "Perfect! Hold still..."

    def menu_zones(self):
        a = self.aspect
        return {"classic": (0.05 * a, 0.12, 0.47 * a, 0.44),
                "survival": (0.53 * a, 0.12, 0.95 * a, 0.44)}

    # ---- update ----

    def update(self, kp, fresh, t_pose, t, aspect):
        dt = 0.0 if not self.last_t else min(t - self.last_t, 0.05)
        self.t, self.last_t, self.aspect = t, t, aspect
        if fresh:
            for hand in self.hands:
                hand.update(kp, t_pose, aspect, self.cut_speed())
            torso = self.torso_length(kp)
            if torso:
                self.torso = torso if self.torso is None else self.torso * 0.9 + torso * 0.1
        if kp is not None:
            self.last_seen = t
        gone = t - self.last_seen

        getattr(self, "_" + self.state)(kp, fresh, dt, gone)

        if not self.paused:
            # Slow motion for the flying objects only: same arcs, just slower. Frame rate unchanged.
            self.step_bodies(dt * self.g["fruit_speed"])
        self.fx.step(dt, self.g["gravity"])

    def _calibrate(self, kp, fresh, dt, gone):
        if not self.rotation_locked:
            self.calib_ok, self.calib_msg, self.hold = False, "Finding you... stand in front of the camera", 0.0
            return
        self.calib_ok, self.calib_msg = self.calib_check(kp)
        self.hold = self.hold + dt if self.calib_ok else 0.0
        if self.hold >= self.cfg["calibrate"]["hold_seconds"]:
            self.goto("menu")
            self.sounds.append("ok")

    def _menu(self, kp, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        for mode, (x0, y0, x1, y1) in self.menu_zones().items():
            inside = any(h.pos and x0 <= h.pos[0] <= x1 and y0 <= h.pos[1] <= y1 for h in self.hands)
            self.hover[mode] = self.hover[mode] + dt if inside else max(0.0, self.hover[mode] - 2 * dt)
            if self.hover[mode] >= self.cfg["menu"]["hover_seconds"]:
                self.mode = mode
                self.hover = dict.fromkeys(self.hover, 0.0)
                self.goto("ready")
                self.sounds.append("select")
                return

    def _ready(self, kp, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        self.hold = self.hold + dt if self.hands_up(kp) else 0.0
        if self.hold >= self.g["hands_up_seconds"]:
            self.goto("countdown")
            self.sounds.append("beep")

    def _countdown(self, kp, fresh, dt, gone):
        n = self.g["countdown_seconds"]
        elapsed = self.t - self.state_t
        if int(elapsed + dt) > int(elapsed) and elapsed + dt < n:
            self.sounds.append("beep")
        if elapsed >= n:
            self.start_round()

    def start_round(self):
        self.goto("play")
        self.sounds.append("go")
        self.score = self.missed = 0
        self.new_best = False
        self.play_time = 0.0
        self.round_end = self.t + self.cfg["classic"]["round_seconds"]
        self.next_wave = self.t + 0.3
        self.cut_times = []
        self.fruits, self.bombs, self.pieces = [], [], []
        self.fx.popup(self.aspect / 2, 0.45, "GO!", (120, 255, 140), "huge", 0.7)

    def _play(self, kp, fresh, dt, gone):
        self.paused = kp is None
        if self.paused:  # stop the clock while the player is out of view
            self.round_end += dt
            self.next_wave += dt
            if gone > 3 * self.cfg["calibrate"]["lost_seconds"]:
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

    def _boom(self, kp, fresh, dt, gone):
        if self.t - self.state_t >= BOOM_SECONDS:
            self.game_over()

    def _over(self, kp, fresh, dt, gone):
        if gone > self.cfg["calibrate"]["lost_seconds"]:
            return self.goto("calibrate")
        can = self.t - self.state_t >= OVER_COOLDOWN
        self.hold = self.hold + dt if can and self.hands_up(kp) else 0.0
        if self.hold >= self.g["hands_up_seconds"]:
            self.goto("menu")
            self.sounds.append("select")

    def game_over(self):
        self.goto("over")
        self.sounds.append("over")
        if self.score > self.best[self.mode]:
            self.best[self.mode] = self.score
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
        for _ in range(random.randint(*count)):
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
        speed = self.cut_speed()
        for hand in self.hands:
            if hand.segment is None or hand.speed < speed:
                continue
            a, b = hand.segment
            for bomb in self.bombs:
                if seg_dist((bomb.x, bomb.y), a, b) <= bomb.r + s["hit_margin"] * 0.5:
                    return self.explode(bomb)
            hit = [f for f in self.fruits if seg_dist((f.x, f.y), a, b) <= f.r + s["hit_margin"]]
            if hit:
                self.fx.slash(a, b)
            for f in hit:
                self.cut(f, a, b)

    def cut(self, f, a, b):
        self.fruits.remove(f)
        self.score += f.kind.points
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
        self.fx.popup(f.x, f.y, f"+{f.kind.points}")
        self.sounds.append("slice")

        window = self.cfg["slice"]["combo_seconds"]
        self.cut_times = [ct for ct in self.cut_times if self.t - ct <= window] + [self.t]
        if len(self.cut_times) >= 3:
            self.score += 1
            self.fx.popup(self.aspect / 2, 0.25, f"COMBO x{len(self.cut_times)}!", (255, 120, 220), "big", 1.0)
            self.sounds.append("combo")

    def explode(self, bomb):
        self.bombs.remove(bomb)
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

def camera_rect(frame, screen):
    """Largest rectangle with the camera's aspect ratio that fits inside the bamboo frame."""
    sw, sh = screen.get_size()
    margin = theme.frame_thickness(sh) + max(10, sh // 50)
    fh, fw = frame.shape[:2] if frame is not None else (16, 9)
    s = min((sw - 2 * margin) / fw, (sh - 2 * margin) / fh)
    w, h = int(fw * s), int(fh * s)
    return pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)


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

    def draw(self, screen, game, tracker, frame, fresh, kp, fps):
        rect = camera_rect(frame, screen)
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
            rgb = cv2.cvtColor(cv2.resize(frame, rect.size), cv2.COLOR_BGR2RGB)
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
        if game.state not in ("play", "boom"):
            screen.blit(self.dim, rect)
        if self.show_skeleton or game.state == "calibrate":
            self.draw_skeleton(screen, kp, game.aspect, to_px)

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

    @staticmethod
    def blit_rotated(screen, surf, body, to_px):
        surf = pygame.transform.rotate(surf, body.angle)
        screen.blit(surf, surf.get_rect(center=to_px(body.x, body.y)))

    @staticmethod
    def draw_skeleton(screen, kp, aspect, to_px):
        if kp is None:
            return
        for a, b in pl.BONES:
            if kp[a][2] > 0.4 and kp[b][2] > 0.4:
                pygame.draw.line(screen, (120, 255, 170), to_px(kp[a][0] * aspect, kp[a][1]),
                                 to_px(kp[b][0] * aspect, kp[b][1]), 3)

    def draw_blades(self, game, to_layer, scale):
        """Glowing blade trail: wide faint glow under a thin bright core, tapering with age."""
        for hand in game.hands:
            pts = hand.trail
            for (p0, t0, fast), (p1, _, _) in zip(pts, pts[1:]):
                life = max(0.0, 1 - (game.t - t0) / hand.trail_seconds)
                w = max(2, int(scale * 0.03 * life))
                if fast:
                    pygame.draw.line(self.layer, (90, 200, 255, int(110 * life)), to_layer(*p0), to_layer(*p1), w * 3)
                    pygame.draw.line(self.layer, (240, 252, 255, int(255 * life)), to_layer(*p0), to_layer(*p1), w)
                else:
                    pygame.draw.line(self.layer, (255, 255, 255, int(90 * life)), to_layer(*p0), to_layer(*p1), w)
            if hand.pos is not None:
                pygame.draw.circle(self.layer, (255, 255, 255, 200), to_layer(*hand.pos), int(scale * 0.028), 3)

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
            self.silhouette(to_layer, a, scale, (*color, 210))
            if game.calib_ok:
                self.ring(to_layer(a / 2, 0.15), int(scale * 0.09),
                          game.hold / self.cfg["calibrate"]["hold_seconds"], (120, 255, 140))
            self.message(screen, rect, "Stand in the middle", 0.04, 0.06, theme.GOLD)
            self.message(screen, rect, game.calib_msg, 0.84, 0.05)
        elif st == "menu":
            for mode, (x0, y0, x1, y1) in game.menu_zones().items():
                box = pygame.Rect(to_layer(x0, y0), (int((x1 - x0) * scale), int((y1 - y0) * scale)))
                frac = game.hover[mode] / self.cfg["menu"]["hover_seconds"]
                pygame.draw.rect(self.layer, (20, 10, 5, 190), box, border_radius=16)
                fill = box.copy()
                fill.h = int(box.h * min(1.0, frac))
                fill.bottom = box.bottom
                pygame.draw.rect(self.layer, (240, 195, 80, 150), fill, border_radius=16)
                pygame.draw.rect(self.layer, (240, 195, 80, 255), box, 3, border_radius=16)
                icon = (self.art.get(fr.TYPES[9], int(scale * 0.06), "whole") if mode == "classic"
                        else self.art.get(None, int(scale * 0.055), "bomb"))
                self.layer.blit(icon, icon.get_rect(center=(box.centerx, box.y + box.h * 0.38)))
                cx = rect.x + box.centerx
                self.later.append(functools.partial(
                    theme.text, screen, theme.font(scale * 0.045), mode.upper(), theme.GOLD,
                    center=(cx, rect.y + box.y + int(box.h * 0.72))))
                sub = "60 seconds" if mode == "classic" else "watch out!"
                self.later.append(functools.partial(
                    theme.text, screen, theme.font(scale * 0.028, name="arial"), sub,
                    center=(cx, rect.y + box.y + int(box.h * 0.88))))
            self.message(screen, rect, "Hold your hand on a game to pick it", 0.58, 0.045)
        elif st == "ready":
            self.message(screen, rect, game.mode.upper(), 0.12, 0.08, theme.GOLD)
            self.message(screen, rect, "Raise both hands above your head to start!", 0.75, 0.05)
            for hand in game.hands:
                if hand.pos is not None:
                    self.ring(to_layer(*hand.pos), int(scale * 0.06), game.hold / self.cfg["game"]["hands_up_seconds"])
        elif st == "countdown":
            left = self.cfg["game"]["countdown_seconds"] - (game.t - game.state_t)
            k = left - math.floor(left)  # 1 -> 0 within each second
            f = theme.font(scale * (0.2 + 0.15 * k))
            self.later.append(functools.partial(
                theme.text, screen, f, str(max(1, math.ceil(left))), theme.GOLD, outline=4, center=rect.center))
        elif st == "play" and game.paused:
            self.message(screen, rect, "Paused - come back in front of the camera", 0.45, 0.055, theme.GOLD)
        elif st == "over":
            title = "BOOM!" if game.mode == "survival" else "TIME UP!"
            self.message(screen, rect, title, 0.14, 0.1, (255, 120, 90))
            self.message(screen, rect, f"Score {game.score}", 0.33, 0.08, theme.GOLD)
            if game.new_best and int(game.t * 3) % 2 == 0:
                self.message(screen, rect, "NEW BEST!", 0.46, 0.06, (120, 255, 140))
            if game.t - game.state_t >= OVER_COOLDOWN:
                self.message(screen, rect, "Raise both hands for the menu", 0.75, 0.05)
                for hand in game.hands:
                    if hand.pos is not None:
                        self.ring(to_layer(*hand.pos), int(scale * 0.06),
                                  game.hold / self.cfg["game"]["hands_up_seconds"])

    def silhouette(self, to_layer, a, scale, color):
        """Outline of a person in the middle of the picture: where to stand."""
        cx = a / 2
        w = max(3, int(scale * 0.01))
        pygame.draw.circle(self.layer, color, to_layer(cx, 0.15), int(scale * 0.06), w)
        body = [(cx - 0.11, 0.25), (cx + 0.11, 0.25), (cx + 0.08, 0.55), (cx - 0.08, 0.55)]
        pygame.draw.polygon(self.layer, color, [to_layer(*p) for p in body], w)
        for side in (-1, 1):
            pygame.draw.line(self.layer, color, to_layer(cx + side * 0.11, 0.26),
                             to_layer(cx + side * 0.17, 0.52), w)
            pygame.draw.line(self.layer, color, to_layer(cx + side * 0.06, 0.55),
                             to_layer(cx + side * 0.08, 0.93), w)

    def draw_panels(self, screen, game, tracker, rect, fps):
        left, right = theme.panels(screen.get_size(), rect)
        lh, rh = game.hands
        if left:
            y = left.y + 30
            for line in ("FRUIT", "SLICE"):
                r = theme.text(screen, theme.font(left.w * 0.24), line, theme.GOLD, outline=3,
                               midtop=(left.centerx, y))
                y = r.bottom - 4
            if game.mode:
                theme.text(screen, theme.font(left.w * 0.09), game.mode.upper(), midtop=(left.centerx, y + 12))
            theme.text(screen, theme.font(left.w * 0.08, name="arial"), "SCORE", midtop=(left.centerx, left.y + left.h * 0.56))
            theme.text(screen, theme.font(left.w * 0.26), str(game.score), theme.GOLD, outline=3,
                       midtop=(left.centerx, left.y + left.h * 0.61))
            if game.mode:
                theme.text(screen, theme.font(left.w * 0.07, name="arial"), f"BEST  {game.best[game.mode]}",
                           midtop=(left.centerx, left.y + left.h * 0.88))
        if right:
            if game.state in ("play", "boom", "over") and game.mode == "classic":
                label, value = "TIME", str(max(0, math.ceil(game.round_end - game.t)) if game.state == "play" else 0)
            elif game.mode == "survival" and game.state in ("play", "boom", "over"):
                secs = int(game.play_time)
                label, value = "SURVIVED", f"{secs // 60}:{secs % 60:02d}"
            else:
                label, value = "", ""
            if label:
                theme.text(screen, theme.font(right.w * 0.09, name="arial"), label, midtop=(right.centerx, right.y + 30))
                urgent = game.mode == "classic" and game.state == "play" and game.round_end - game.t <= 10
                theme.text(screen, theme.font(right.w * 0.3), value, (255, 110, 90) if urgent else theme.GOLD,
                           outline=3, midtop=(right.centerx, right.y + 30 + right.w * 0.12))
            if game.mode == "classic" and game.state in ("play", "over"):
                theme.text(screen, theme.font(right.w * 0.08, name="arial"), f"missed {game.missed}",
                           midtop=(right.centerx, right.y + right.h * 0.45))
            hint = {"calibrate": "Stand in the middle", "menu": "Pick a game", "ready": "Hands up!",
                    "countdown": "Get ready...", "play": "Slice!", "boom": "Ouch!", "over": "Well done!"}[game.state]
            theme.text(screen, theme.font(right.w * 0.11), hint, theme.CREAM, midtop=(right.centerx, right.y + right.h * 0.58))
            if self.show_debug:
                f = theme.font(max(11, right.w // 22), bold=False, name="consolas")
                lines = [f"fps {fps:4.1f}  pose {tracker.pose_ms:4.1f} ms",
                         f"hand L {lh.speed / (game.torso or DEFAULT_TORSO):3.1f}  R {rh.speed / (game.torso or DEFAULT_TORSO):3.1f}",
                         f"cut >= {self.cfg['slice']['speed']} torso/s",
                         f"torso {game.torso or 0:.2f}  rotate {tracker.rotate}"]
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
        pygame.mouse.set_visible(not fullscreen)
        return pygame.display.set_mode((0, 0) if fullscreen else windowed,
                                       pygame.FULLSCREEN if fullscreen else 0)

    screen = set_mode()
    tracker = pl.PoseTracker(cfg)
    game = Game(cfg, load_scores())
    renderer = Renderer(cfg)
    sounds = make_sounds()
    clock = pygame.time.Clock()
    last_seq = 0

    try:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_r:
                        tracker.cycle_rotation()
                    elif event.key == pygame.K_s:
                        renderer.show_skeleton = not renderer.show_skeleton
                    elif event.key == pygame.K_d:
                        renderer.show_debug = not renderer.show_debug
                    elif event.key == pygame.K_f:
                        fullscreen = not fullscreen
                        screen = set_mode()

            seq, frame, kp, t_pose = tracker.latest()
            fresh = seq != last_seq
            last_seq = seq
            rect = camera_rect(frame, screen)
            game.rotation_locked = tracker.rotation_locked
            game.update(kp, fresh, t_pose, time.perf_counter(), rect.w / rect.h)
            for name in game.sounds:
                if name in sounds:
                    sounds[name].play()
            game.sounds.clear()

            renderer.draw(screen, game, tracker, frame, fresh, kp, clock.get_fps())
            pygame.display.flip()
            clock.tick(60)
    finally:
        tracker.close()
        pygame.quit()


if __name__ == "__main__":
    main()
