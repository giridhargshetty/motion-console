"""Boxing: first person, you against a computer boxer. Rules, opponent AI and gesture checks;
no drawing (see boxing_draw.py).

  select (pick a boxer) -> ready (both hands up) -> countdown -> fight -> result -> select ...

Your punches: a hand moving fast toward the boxer (or toward the camera, from MediaPipe's depth)
lands, unless the boxer is covering up. Your defence: when the boxer winds up (glove glows),
cover up with both gloves in front of your face, or dodge by leaning or ducking out of the way.
Land [boxing] hits_to_win punches to win; take hits_to_lose and you lose (the two health bars).

Tracking comes from the console's lobby (fruit_slice.Game): BLUE's keypoints, hands and torso.
The gesture checks are pure functions of keypoints, so they're unit-tested without a camera.
"""

import math
import random

import effects

NOSE, L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_HIP, R_HIP = 0, 11, 12, 15, 16, 23, 24
COUNTDOWN = 3
TARGET = (0.5, 0.33)   # boxer's head, as a fraction of (play-area width, height)
TARGET_REACH = 0.32    # punches ending within this many screen-heights of it count as aimed at the boxer


# ---------------------------------------------------------------- gestures (pure functions)

def torso_norm(kp, min_vis=0.5):
    """Shoulders-to-hips distance in image units (0..1), or None if not seen."""
    if kp is None or min(kp[i][2] for i in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)) < min_vis:
        return None
    sx, sy = (kp[L_SHOULDER][0] + kp[R_SHOULDER][0]) / 2, (kp[L_SHOULDER][1] + kp[R_SHOULDER][1]) / 2
    hx, hy = (kp[L_HIP][0] + kp[R_HIP][0]) / 2, (kp[L_HIP][1] + kp[R_HIP][1]) / 2
    return math.hypot(hx - sx, hy - sy) or None


def guarding(kp, min_vis=0.5):
    """Both gloves up in front of the face: wrists above the shoulders' level (a little slack for kids)
    and within about a torso-length of the nose sideways."""
    torso = torso_norm(kp, min_vis)
    if torso is None or min(kp[i][2] for i in (NOSE, L_WRIST, R_WRIST)) < min_vis:
        return False
    shoulder_y = (kp[L_SHOULDER][1] + kp[R_SHOULDER][1]) / 2
    return all(kp[w][1] < shoulder_y + 0.15 * torso and abs(kp[w][0] - kp[NOSE][0]) < 1.0 * torso
               for w in (L_WRIST, R_WRIST))


def head(kp):
    return (kp[NOSE][0], kp[NOSE][1]) if kp is not None else None


def dodged(head_then, head_now, torso, lean=0.5, duck=0.4):
    """Head moved out of the punch's path since the wind-up started: sideways (lean) or down (duck)."""
    if head_then is None or head_now is None or not torso:
        return False
    dx, dy = head_now[0] - head_then[0], head_now[1] - head_then[1]
    return abs(dx) > lean * torso or dy > duck * torso


def classify_punch(vx, vy, vz, speed_needed, forward_needed):
    """Hand velocity in torso-lengths/s: vx, vy on screen, vz toward the camera (positive = nearer).
    Returns "jab" (straight), "hook" (sideways swing) or None."""
    planar = math.hypot(vx, vy)
    if vz >= forward_needed and vz >= 0.5 * planar:
        return "jab"
    if planar >= speed_needed:
        return "hook" if abs(vx) > 1.5 * abs(vy) else "jab"
    return None


def aimed_at(pos, vel, target, reach):
    """A punch counts if it ends near the boxer, or is heading toward them."""
    dx, dy = target[0] - pos[0], target[1] - pos[1]
    if math.hypot(dx, dy) <= reach:
        return True
    return vel[0] * dx + vel[1] * dy > 0


# ---------------------------------------------------------------- the computer boxer

class Opponent:
    """idle -> (guard) -> windup -> punch -> recover -> idle; stunned when hit; ko / cheer at the end.
    update() returns "impact" at the moment a punch arrives: the game then checks your defence."""

    PUNCH_TIME = 0.3
    RECOVER = 0.8
    STUN = 0.5

    def __init__(self, spec, rng=None):
        self.spec = spec
        self.name = spec["name"]
        self.rng = rng or random.Random()
        self.state, self.t_state, self.t_end = "idle", 0.0, 0.0
        self.side = "left"         # which glove punches (as you see it)
        self.next_attack = 0.0
        self.next_guard_roll = 0.0
        self.immune_until = 0.0

    def start(self, t):
        self.go("idle", t)
        self.next_attack = t + self.rng.uniform(*self.spec["attack_every"])
        self.next_guard_roll = t + 1.0

    def go(self, state, t, duration=0.0):
        self.state, self.t_state, self.t_end = state, t, t + duration

    @property
    def open(self):
        """Exposed: a punch now is a counter (winding up, or recovering after a punch)."""
        return self.state in ("windup", "recover")

    def update(self, t):
        if self.state in ("ko", "cheer"):
            return None
        if self.state == "stunned" and t >= self.t_end and self.rng.random() < self.spec["guard_chance"] + 0.35:
            self.go("guard", t, self.rng.uniform(0.6, 1.2))  # hurt: covers up for a moment
        elif self.state in ("guard", "stunned", "recover") and t >= self.t_end:
            self.go("idle", t)  # an attack that came due meanwhile starts right away
        if self.state == "idle":
            if t >= self.next_attack:
                self.side = self.rng.choice(("left", "right"))
                self.go("windup", t, self.spec["windup"])
            elif t >= self.next_guard_roll:
                self.next_guard_roll = t + 1.0
                if self.rng.random() < self.spec["guard_chance"]:
                    self.go("guard", t, self.rng.uniform(0.8, 1.6))
        elif self.state == "windup" and t >= self.t_end:
            self.go("punch", t, self.PUNCH_TIME)
            return "impact"
        elif self.state == "punch" and t >= self.t_end:
            self.go("recover", t, self.RECOVER)
            self.next_attack = t + self.RECOVER + self.rng.uniform(*self.spec["attack_every"])
        return None

    def take_hit(self, t, immunity):
        """Stunned briefly; the attack schedule keeps running, so punching non-stop can't keep the
        boxer from fighting back (he may also cover up after the stun: see update)."""
        self.immune_until = t + immunity
        if self.state in ("windup", "punch"):
            return  # a counter scores, but he keeps coming: you still have to block or dodge
        self.go("stunned", t, self.STUN)
        self.next_attack = max(self.next_attack, t + self.STUN)


# ---------------------------------------------------------------- the game

class Boxing:
    def __init__(self, cfg, lobby, scores, save_scores, rng=None):
        self.cfg, self.b = cfg, cfg["boxing"]
        self.lobby = lobby
        self.scores, self.save_scores = scores, save_scores
        self.rng = rng or random.Random()
        self.boxers = self.b["boxers"]
        self.state, self.state_t, self.hold = "select", lobby.t, 0.0
        self.hover = {z: 0.0 for z in self.zones()}
        self.focus = 0  # the boxer picked last
        self.opponent = None
        self.landed = self.taken = 0
        self.won = False
        self.paused = False
        self.head_at_windup = None
        self.hand_prev = [None, None]  # per hand: (t, x, y, z) for velocities
        self.hand_next_punch = [0.0, 0.0]
        self.punch_glow = [0.0, 0.0]   # when each glove last punched (drawing grows it briefly)
        self.hurt_until = 0.0          # red flash after you're hit
        self.message, self.message_until, self.message_color = "", 0.0, (255, 255, 255)
        self.fx = effects.Effects()
        self.sounds = []
        self.done = False           # back to the home screen

    # ---- helpers ----

    @property
    def t(self):
        return self.lobby.t

    @property
    def me(self):
        return self.lobby.players[0]

    def goto(self, state):
        self.state, self.state_t, self.hold, self.paused = state, self.t, 0.0, False

    def zones(self):
        """Pickable areas in 0..1 of the screen, pointed at with a raised hand (lobby.pointers(), so
        arms resting at your sides pick nothing): a card per boxer, and HOME in the strip on top."""
        out = {f"boxer{i}": (0.04 + 0.32 * i, 0.2, 0.32 + 0.32 * i, 0.74) for i in range(len(self.boxers))}
        out["home"] = (0.04, 0.03, 0.3, 0.12)
        return out

    def hover_needed(self, zone):
        m = self.cfg["menu"]
        return m["settings_hover_seconds"] if zone == "home" else m["hover_seconds"]

    def wins(self, i):
        return self.scores.get(f"boxing_{self.boxers[i]['sprite']}", 0)

    def say(self, text, color=(255, 255, 255), seconds=0.9):
        self.message, self.message_until, self.message_color = text, self.t + seconds, color

    # ---- input ----

    def press(self, key):
        import pygame  # only the console's key codes; keeps the rules testable without a display
        if key in (pygame.K_ESCAPE, pygame.K_AC_BACK) and self.state in ("select", "ready", "result"):
            self.pick("home")  # Back: to the home screen
        elif self.state == "select":
            # One key per boxer, so the choice is visible straight away: Left / OK / Right.
            n = len(self.boxers)
            pick = {pygame.K_LEFT: 0, pygame.K_RETURN: min(1, n - 1), pygame.K_KP_ENTER: min(1, n - 1),
                    pygame.K_RIGHT: n - 1}.get(key)
            if pick is not None:
                self.pick(f"boxer{pick}")
            elif key == pygame.K_UP:
                self.pick("home")
        elif self.state in ("ready", "result") and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.state == "ready":
                self.goto("countdown")
                self.sounds.append("beep")
            elif self.t - self.state_t >= self.b["result_seconds"]:
                self.goto("select")

    def pick(self, zone):
        self.hover = dict.fromkeys(self.hover, 0.0)
        self.sounds.append("select")
        if zone == "home":
            self.done = True
        else:
            self.focus = int(zone[5:])
            self.opponent = Opponent(self.boxers[self.focus], self.rng)
            self.goto("ready")

    # ---- update ----

    def update(self, dt, fresh):
        getattr(self, "_" + self.state)(dt, fresh)
        self.fx.step(dt, self.cfg["game"]["gravity"])

    def _select(self, dt, fresh):
        pointers = self.lobby.pointers()
        for zone, (x0, y0, x1, y1) in self.zones().items():
            inside = any(x0 <= u <= x1 and y0 <= v <= y1 for u, v in pointers)
            self.hover[zone] = self.hover[zone] + dt if inside else max(0.0, self.hover[zone] - 2 * dt)
            if self.hover[zone] >= self.hover_needed(zone):
                return self.pick(zone)

    def _ready(self, dt, fresh):
        up = self.me.kp is not None and self.lobby.hands_up(self.me.kp)
        self.hold = self.hold + dt if up else 0.0
        if self.hold >= self.cfg["game"]["hands_up_seconds"]:
            self.goto("countdown")
            self.sounds.append("beep")

    def _countdown(self, dt, fresh):
        elapsed = self.t - self.state_t
        if int(elapsed + dt) > int(elapsed) and elapsed + dt < COUNTDOWN:
            self.sounds.append("beep")
        if elapsed >= COUNTDOWN:
            self.landed = self.taken = 0
            self.won = False
            self.hand_prev = [None, None]
            self.opponent.start(self.t)
            self.goto("fight")
            self.sounds += ["bell", "crowd_cheer"]
            self.say("FIGHT!", (120, 255, 140), 0.8)

    def _fight(self, dt, fresh):
        opp = self.opponent
        grace = self.cfg["game"].get("pause_after_seconds", 1.0)
        self.paused = self.t - self.me.last_seen > grace
        if self.paused:  # out of view: freeze the boxer's clock
            opp.t_end += dt
            opp.next_attack += dt
            opp.next_guard_roll += dt
            return
        if opp.update(self.t) == "impact":
            self.resolve_incoming()
        elif opp.state == "windup" and self.head_at_windup is None:
            self.head_at_windup = head(self.me.kp)
            self.sounds.append("warn")
        if self.state == "fight" and fresh:
            self.check_punches()

    def resolve_incoming(self):
        """The boxer's punch arrives: blocked, dodged, or you're hit."""
        kp, b = self.me.kp, self.b
        torso = torso_norm(kp)
        then, self.head_at_windup = self.head_at_windup, None
        if guarding(kp):
            self.say("BLOCKED!", (120, 220, 255))
            self.sounds.append("block")
        elif dodged(then, head(kp), torso, b["dodge_lean"], b["dodge_duck"]):
            self.say("DODGED!", (120, 255, 140))
            self.sounds.append("swish")
        else:
            self.taken += 1
            self.hurt_until = self.t + 0.35
            self.fx.shake = 0.03
            self.sounds += ["hit", "crowd_ooh"]
            if self.taken >= b["hits_to_lose"]:
                self.opponent.go("cheer", self.t)
                self.finish(won=False)
            else:
                self.say("OUCH!", (255, 110, 90))

    def check_punches(self):
        """Look for a punch in each hand since the last pose sample."""
        kp, b = self.me.kp, self.b
        torso = torso_norm(kp)
        a = self.lobby.aspect
        target = (TARGET[0] * a, TARGET[1])
        for i, (hand, wrist) in enumerate(zip(self.me.hands, (L_WRIST, R_WRIST))):
            if hand.pos is None or kp is None or not torso:
                self.hand_prev[i] = None
                continue
            z = kp[wrist][3] if len(kp[wrist]) > 3 else 0.0
            now = (hand.t, hand.pos[0], hand.pos[1], z)
            prev, self.hand_prev[i] = self.hand_prev[i], now
            if prev is None or now[0] <= prev[0] or self.t < self.hand_next_punch[i]:
                continue
            ddt = now[0] - prev[0]
            # Screen speeds are in screen-heights; per torso-length like slicing (torso in the same units).
            torso_h = self.me.torso or torso
            vx, vy = (now[1] - prev[1]) / ddt / torso_h, (now[2] - prev[2]) / ddt / torso_h
            vz = -(now[3] - prev[3]) / ddt / torso  # z shrinks as the hand comes toward the camera
            kind = classify_punch(vx, vy, vz, b["punch_speed"], b["punch_forward_speed"])
            if kind is None or not aimed_at(hand.pos, (vx, vy), target, TARGET_REACH):
                continue
            self.hand_next_punch[i] = self.t + b["punch_cooldown"]
            self.punch_glow[i] = self.t
            self.land_punch(kind, hand.pos)
            if self.state != "fight":
                return

    def land_punch(self, kind, pos):
        opp, b = self.opponent, self.b
        if self.t < opp.immune_until or opp.state in ("ko", "cheer"):
            return
        if opp.state == "guard":
            self.say("BLOCKED", (200, 200, 200), 0.6)
            self.sounds.append("block")
            return
        counter = opp.open
        self.landed += 1
        opp.take_hit(self.t, b["hit_immunity"])
        a = self.lobby.aspect
        self.fx.juice(TARGET[0] * a, TARGET[1], (255, 230, 120), 0, 0, 12)
        if self.landed >= b["hits_to_win"]:
            self.sounds.append("ko_punch")
            opp.go("ko", self.t)
            self.finish(won=True)
            return
        self.sounds.append(f"punch{random.randint(1, 3)}")  # not self.rng: that drives the boxer
        if counter:
            self.sounds.append("crowd_ooh")
        self.say("COUNTER!" if counter else ("HOOK!" if kind == "hook" else "POW!"),
                 (255, 220, 90) if counter else (255, 255, 255))

    def finish(self, won):
        self.won = won
        self.goto("result")
        self.sounds += ["bell_end", "crowd_roar" if won else "crowd_aww"]
        if won:
            key = f"boxing_{self.opponent.spec['sprite']}"
            self.scores[key] = self.scores.get(key, 0) + 1
            self.save_scores(self.scores)

    def _result(self, dt, fresh):
        since = self.t - self.state_t
        if self.won and since < 4.0 and int((since + dt) * 8) > int(since * 8):  # confetti, 8 bursts/s
            self.fx.confetti(random.uniform(0.05, 0.95) * self.lobby.aspect, -0.02, 10)
        if since < self.b["result_seconds"]:
            return
        up = self.me.kp is not None and self.lobby.hands_up(self.me.kp)
        self.hold = self.hold + dt if up else 0.0
        if self.hold >= self.cfg["game"]["hands_up_seconds"]:
            self.goto("select")
            self.sounds.append("select")
