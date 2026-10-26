"""Dress Up: a magic mirror. Pick a costume and it follows you as you move. No winning or losing,
just dressing up, posing and swinging a sword or a wand. Rules only; drawing is dressup_draw.py,
fitting the costume onto the body is dressup_fit.py.

  pick (choose a costume) -> wear (the mirror) -> pick ...      HOME / Back -> the home screen
While wearing: hold a hand on COSTUMES (top-left) to choose again, or on PHOTO (top-right) for
"strike a pose!": 3-2-1, a camera flash, and the picture holds still for a moment.
Remote: Left / Right = change costume, OK = photo, Up = costumes, Back = home.
"""

import math

import effects
from dressup_fit import Smoother

COLS = 3          # costumes per picker row; 4 once there are more than 9 (see cols)
SPARKLE_COLORS = ((255, 240, 150), (255, 170, 60), (150, 220, 255), (255, 150, 230))


class DressUp:
    def __init__(self, cfg, lobby, costumes, sparkly=()):
        self.cfg, self.d = cfg, cfg["dressup"]
        self.lobby = lobby
        self.costumes = list(costumes)   # costume keys with rendered art, in picker order
        self.sparkly = set(sparkly)      # costumes holding something that sparkles when swung
        self.current = 0
        self.state, self.state_t = "pick", lobby.t
        self.hover = {}
        self.focus = 0                   # the remote's highlighted costume on the picker
        self.kp = None                   # the player's smoothed keypoints
        self.smooth = Smoother(self.d["smooth_min_cutoff"], self.d["smooth_beta"])
        self.photo_t = None              # when "strike a pose" started counting down
        self.freeze_until = 0.0          # the photo holds still until then
        self.changed_t = -9.0            # when the costume last changed (the poof)
        self.next_twinkle = 0.0
        self.fx = effects.Effects()
        self.sounds = []
        self.done = False                # back to the home screen

    # ---- helpers ----

    @property
    def t(self):
        return self.lobby.t

    @property
    def me(self):
        return self.lobby.players[0]

    @property
    def key(self):
        return self.costumes[self.current] if self.costumes else None

    @property
    def cols(self):
        """Picker tiles per row: 3 (up to a 3x3 grid), 4 beyond that so tiles stay big."""
        return COLS if len(self.costumes) <= COLS * COLS else COLS + 1

    @property
    def frozen(self):
        return self.t < self.freeze_until

    def goto(self, state):
        self.state, self.state_t = state, self.t
        self.hover = dict.fromkeys(self.zones(), 0.0)

    def zones(self):
        """Pickable areas in 0..1 of the screen, pointed at with a raised hand (lobby.pointers())."""
        if self.state == "pick":
            u0, v0, u1, v1, gap = 0.06, 0.2, 0.94, 0.86, 0.03
            rows = max(1, math.ceil(len(self.costumes) / self.cols))
            w = (u1 - u0 - gap * (self.cols - 1)) / self.cols
            h = (v1 - v0 - gap * (rows - 1)) / rows
            out = {f"c{i}": (u0 + (i % self.cols) * (w + gap), v0 + (i // self.cols) * (h + gap),
                             u0 + (i % self.cols) * (w + gap) + w, v0 + (i // self.cols) * (h + gap) + h)
                   for i in range(len(self.costumes))}
            out["home"] = (0.04, 0.03, 0.3, 0.13)
            return out
        return {"costumes": (0.03, 0.03, 0.27, 0.13), "photo": (0.73, 0.03, 0.97, 0.13)}

    def hover_needed(self, zone):
        m = self.cfg["menu"]
        return m["settings_hover_seconds"] if zone in ("home", "costumes") else m["hover_seconds"]

    # ---- input ----

    def press(self, key):
        import pygame  # only the key codes; keeps the rules testable without a display
        n = len(self.costumes)
        if key in (pygame.K_ESCAPE, pygame.K_AC_BACK):
            self.pick("home")
        elif self.state == "pick" and n:
            if key == pygame.K_LEFT:
                self.focus = (self.focus - 1) % n
            elif key == pygame.K_RIGHT:
                self.focus = (self.focus + 1) % n
            elif key == pygame.K_UP:
                self.focus = (self.focus - self.cols) % n
            elif key == pygame.K_DOWN:
                self.focus = (self.focus + self.cols) % n
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.wear(self.focus)
        elif self.state == "wear":
            if key in (pygame.K_LEFT, pygame.K_RIGHT) and n:
                self.wear((self.current + (1 if key == pygame.K_RIGHT else -1)) % n)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.pick("photo")
            elif key == pygame.K_UP:
                self.pick("costumes")

    def pick(self, zone):
        self.sounds.append("select")
        if zone == "home":
            self.done = True
        elif zone == "costumes":
            self.focus = self.current
            self.goto("pick")
        elif zone == "photo":
            if self.photo_t is None and not self.frozen:
                self.photo_t = self.t
                self.sounds.append("beep")
        elif zone.startswith("c"):
            self.wear(int(zone[1:]))

    def wear(self, i):
        self.current = i
        self.changed_t = self.t
        self.goto("wear")
        self.sounds.append("poof")
        x, y = self.body_center()
        for color in SPARKLE_COLORS:  # the poof: a burst of sparkles where the player stands
            self.fx.juice(x, y, color, 0, 0, 10)

    def body_center(self):
        kp, view = self.kp, self.lobby.view
        if kp is None:
            return self.lobby.aspect / 2, 0.45
        sx = (kp[11][0] + kp[12][0] + kp[23][0] + kp[24][0]) / 4
        sy = (kp[11][1] + kp[12][1] + kp[23][1] + kp[24][1]) / 4
        return view.world(sx, sy)

    # ---- update ----

    def update(self, dt, fresh):
        if fresh and not self.frozen:
            self.kp = self.smooth(self.me.kp, self.t)
        pointers = self.lobby.pointers()
        for zone, (u0, v0, u1, v1) in self.zones().items():
            inside = any(u0 <= u <= u1 and v0 <= v <= v1 for u, v in pointers)
            self.hover[zone] = self.hover.get(zone, 0.0) + dt if inside else max(0.0, self.hover.get(zone, 0.0) - 2 * dt)
            if self.hover[zone] >= self.hover_needed(zone):
                self.hover[zone] = 0.0
                self.pick(zone)
                break
        if self.state == "wear":
            self.photo_step(dt)
            self.sparkles()
        self.fx.step(dt, self.cfg["game"]["gravity"] * 0.3)

    def photo_step(self, dt):
        if self.photo_t is None:
            return
        n = self.d["photo_countdown"]
        elapsed = self.t - self.photo_t
        if int(elapsed + dt) > int(elapsed) and elapsed + dt < n:
            self.sounds.append("beep")
        if elapsed >= n:
            self.photo_t = None
            self.freeze_until = self.t + self.d["photo_freeze"]
            self.fx.flash = 1.0
            self.sounds.append("shutter")

    def sparkles(self):
        """Something magic in hand (wand, sword, staff): swinging it leaves a trail of sparkles."""
        if self.key not in self.sparkly or self.frozen:
            return
        torso = self.me.torso or 0.25
        for hand in self.me.hands:
            if hand.pos is not None and hand.speed > self.d["sparkle_speed"] * torso:
                for _ in range(2):
                    self.fx.sparks(*hand.pos)
                if self.t >= self.next_twinkle:
                    self.next_twinkle = self.t + 0.35
                    self.sounds.append("twinkle")
