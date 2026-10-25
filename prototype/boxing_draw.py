"""Drawing for the boxing game (rules in boxing.py): first person in a boxing ring.

The boxer faces you in the middle; your gloves follow your real hands in the foreground; your
camera picture is a small window in the corner. The boxer is a sprite animation once
tools/blender/render_boxer.py has rendered it (assets/boxers/<sprite>/), otherwise drawn shapes.
Uses the Fruit Slice renderer for the backdrop, side panels' frame, hover boxes and fonts.
"""

import functools
import math
import random

import pygame

import player as pl
import sprites
import theme

GLOVE_BLUE = (40, 110, 230)
GLOVE_RED = (210, 35, 40)
WARN = (255, 200, 60)


class BoxingRenderer:
    def __init__(self, base):
        self.base = base            # fruit_slice.Renderer: backdrop, layer, choice_box, hearts, fonts
        self._ring_key = None
        self._ring = None
        self._pip = None

    # ---------------------------------------------------------------- scene

    def ring(self, size):
        """Arena backdrop for the play area: dark crowd, spotlight, ropes, canvas (cached per size)."""
        if self._ring_key == size:
            return self._ring
        w, h = size
        surf = pygame.Surface(size)
        for y in range(h):  # dark arena, lighter toward the ring
            k = y / h
            surf.fill((int(18 + 30 * k), int(16 + 22 * k), int(28 + 20 * k)), pygame.Rect(0, y, w, 1))
        rng = random.Random(5)
        for _ in range(int(w * h / 900)):  # crowd: dim heads in the dark
            x, y = rng.uniform(0, w), rng.uniform(0, h * 0.42)
            c = rng.randint(30, 70)
            pygame.draw.circle(surf, (c, c - 5, c + 5), (x, y), rng.uniform(2, 5))
        spot = pygame.Surface(size, pygame.SRCALPHA)
        pygame.draw.ellipse(spot, (255, 240, 210, 40), pygame.Rect(w * 0.1, h * 0.05, w * 0.8, h * 0.9))
        surf.blit(spot, (0, 0))
        floor = pygame.Rect(0, int(h * 0.74), w, h - int(h * 0.74))
        pygame.draw.rect(surf, (55, 75, 140), floor)  # canvas
        pygame.draw.line(surf, (230, 230, 240), floor.topleft, floor.topright, 3)
        for i, color in enumerate(((220, 40, 40), (240, 240, 240), (40, 80, 220))):
            yy = int(h * (0.5 + 0.08 * i))
            pygame.draw.line(surf, color, (0, yy), (w, yy), max(3, h // 120))
        for x in (int(w * 0.04), int(w * 0.96)):  # corner posts
            pygame.draw.rect(surf, (200, 200, 210), pygame.Rect(x - 6, int(h * 0.45), 12, int(h * 0.32)))
        self._ring_key, self._ring = size, surf
        return surf

    def glove(self, surf, center, radius, color, shine=True):
        """A boxing glove seen from the front: round fist, thumb bump, white cuff."""
        cx, cy = center
        r = max(4, int(radius))
        cuff = pygame.Rect(0, 0, int(r * 1.3), int(r * 0.55))
        cuff.midtop = (cx, cy + int(r * 0.65))
        pygame.draw.rect(surf, (240, 240, 235), cuff, border_radius=max(2, r // 5))
        pygame.draw.circle(surf, tuple(int(c * 0.7) for c in color), (cx, cy), r)
        pygame.draw.circle(surf, color, (cx - r * 0.05, cy - r * 0.05), int(r * 0.92))
        pygame.draw.ellipse(surf, tuple(int(c * 0.85) for c in color),
                            pygame.Rect(cx - r * 1.05, cy - r * 0.15, r * 0.6, r * 0.8))
        if shine:
            pygame.draw.ellipse(surf, tuple(min(255, c + 90) for c in color),
                                pygame.Rect(cx - r * 0.45, cy - r * 0.7, r * 0.55, r * 0.35))

    def draw_boxer_shapes(self, surf, cx, base_y, s, opp, t):
        """Placeholder boxer (until sprites exist), sized by s (pixels per screen-height)."""
        spec = opp.spec
        skin, shirt = tuple(spec["skin"]), tuple(spec["shirt"])
        st, since = opp.state, t - opp.t_state
        bob = math.sin(t * 3.0) * s * 0.008
        tilt = 0.0
        drop = 0.0
        if st == "stunned":
            tilt = math.sin(since * 25) * 0.04 * s
        if st == "ko":
            drop = min(1.0, since / 0.8) * s * 0.35
        head = (cx + tilt, base_y - s * 0.62 + bob + drop)
        hr = s * 0.085
        shoulders_y = head[1] + hr * 1.3
        sw = s * 0.17
        # body
        torso = [(cx - sw, shoulders_y), (cx + sw, shoulders_y),
                 (cx + sw * 0.75, base_y + drop), (cx - sw * 0.75, base_y + drop)]
        pygame.draw.polygon(surf, skin, torso)
        trunks = pygame.Rect(0, 0, sw * 1.6, s * 0.12)
        trunks.midtop = (cx, base_y - s * 0.1 + drop)
        pygame.draw.rect(surf, shirt, trunks, border_radius=int(s * 0.02))
        pygame.draw.circle(surf, skin, head, hr)
        # face
        eye_y = head[1] - hr * 0.1
        dazed = st in ("stunned", "ko")
        for dx in (-0.35, 0.35):
            ex = head[0] + dx * hr
            if dazed:
                pygame.draw.line(surf, (30, 20, 20), (ex - 4, eye_y - 4), (ex + 4, eye_y + 4), 3)
                pygame.draw.line(surf, (30, 20, 20), (ex - 4, eye_y + 4), (ex + 4, eye_y - 4), 3)
            else:
                pygame.draw.circle(surf, (30, 20, 20), (ex, eye_y), max(2, hr * 0.12))
        brow = 6 if st in ("windup", "punch") else 2
        for dx in (-0.35, 0.35):
            pygame.draw.line(surf, (40, 25, 20), (head[0] + (dx - 0.18) * hr, eye_y - hr * 0.3 - (brow if dx < 0 else 0)),
                             (head[0] + (dx + 0.18) * hr, eye_y - hr * 0.3 - (0 if dx < 0 else brow)), 3)
        mouth = pygame.Rect(0, 0, hr * 0.5, hr * 0.18)
        mouth.center = (head[0], head[1] + hr * 0.45)
        pygame.draw.rect(surf, (120, 40, 40), mouth, border_radius=3)
        if st == "stunned":  # stars
            for k in range(3):
                a = since * 6 + k * 2.1
                pygame.draw.circle(surf, (255, 230, 80), (head[0] + math.cos(a) * hr * 1.4,
                                                          head[1] - hr * 1.2 + math.sin(a) * hr * 0.3), hr * 0.15)
        # gloves: position by state (as you see them: "left" is on your left)
        rest = {"left": (cx - sw * 0.75, shoulders_y + s * 0.09), "right": (cx + sw * 0.75, shoulders_y + s * 0.09)}
        gr = {"left": s * 0.06, "right": s * 0.06}
        pos = dict(rest)
        if st == "guard":
            pos = {"left": (cx - hr * 0.55, head[1] + hr * 0.3), "right": (cx + hr * 0.55, head[1] + hr * 0.3)}
            gr = {"left": s * 0.07, "right": s * 0.07}
        elif st == "cheer":
            pos = {"left": (cx - sw * 0.9, head[1] - hr * 1.6), "right": (cx + sw * 0.9, head[1] - hr * 1.6)}
        elif st in ("windup", "punch", "recover"):
            side = opp.side
            sign = -1 if side == "left" else 1
            if st == "windup":
                pull = min(1.0, since / max(0.01, opp.spec["windup"] * 0.5))
                pos[side] = (cx + sign * sw * (0.8 + 0.4 * pull), shoulders_y - s * 0.02 * pull)
                gr[side] = s * 0.055
            elif st == "punch":
                k = min(1.0, since / (opp.PUNCH_TIME * 0.5))
                pos[side] = (cx + sign * s * 0.02, head[1] + hr * (1.5 + 1.0 * k))
                gr[side] = s * (0.07 + 0.14 * k)  # coming at you
            else:
                pos[side] = (cx + sign * sw * 0.6, shoulders_y + s * 0.06)
        for side in ("left", "right"):
            shoulder = (cx + (-1 if side == "left" else 1) * sw * 0.9, shoulders_y + s * 0.02)
            pygame.draw.line(surf, skin, shoulder, pos[side], max(4, int(s * 0.045)))
        for side in ("left", "right"):
            if st == "windup" and side == opp.side:  # the warning: pulsing glow round the punching glove
                pulse = 0.5 + 0.5 * math.sin(t * 18)
                pygame.draw.circle(surf, WARN, pos[side], gr[side] * (1.5 + 0.3 * pulse), max(3, int(s * 0.008)))
            self.glove(surf, (int(pos[side][0]), int(pos[side][1])), gr[side], GLOVE_RED)
        return head, hr

    def draw_boxer(self, surf, cx, base_y, s, opp, t):
        """The boxer: sprite frames if rendered, else shapes. Returns the head position and radius."""
        frames = sprites.load(opp.spec["sprite"])
        if frames is not None:
            since = t - opp.t_state
            anim = {"idle": "idle", "guard": "block", "windup": "idle", "punch": "jab" if opp.side == "left" else "cross",
                    "recover": "idle", "stunned": "hit_head", "ko": "knockout", "cheer": "victory"}[opp.state]
            if not frames.has(anim):
                anim = "idle"
            img = frames.frame(anim, since, s * 0.95, loop=opp.state in ("idle", "guard", "windup", "recover"))
            if img is not None:
                r = img.get_rect(midbottom=(cx, base_y + s * 0.05))
                surf.blit(img, r)
                head = (cx, r.y + r.h * 0.12)
                if opp.state == "windup":
                    pulse = 0.5 + 0.5 * math.sin(t * 18)
                    pygame.draw.rect(surf, WARN, r.inflate(10, 10), max(3, int(3 + 4 * pulse)), border_radius=12)
                return head, s * 0.08
        return self.draw_boxer_shapes(surf, cx, base_y, s, opp, t)

    # ---------------------------------------------------------------- frame

    def draw(self, screen, g, tracker, frame, fresh, rect, view, fps):
        base = self.base
        base.prepare(screen, tracker, frame, fresh, rect, view)
        s = rect.h
        sx, sy = g.fx.shake_offset()

        def to_px(x, y):
            return int(rect.x + (x + sx) * s), int(rect.y + (y + sy) * s)

        def to_layer(x, y):
            return int(x * s), int(y * s)

        screen.set_clip(rect)
        screen.blit(self.ring(rect.size), rect.move(int(sx * s), int(sy * s)))
        a = g.lobby.aspect
        opp = g.opponent
        if opp is not None and g.state != "select":
            self.draw_boxer(screen, rect.x + int((a / 2 + sx) * s), rect.y + int((0.78 + sy) * s), s, opp, g.t)
        g.fx.draw_back(screen, to_px)
        g.fx.draw_front(screen, to_px, s, base.popup_font)

        # your gloves, in the foreground, following your hands; a punch makes them jump bigger
        if g.state != "select":
            for i, hand in enumerate(g.me.hands):
                if hand.pos is None:
                    continue
                punched = g.t - g.punch_glow[i]
                grow = 1.0 + 0.45 * max(0.0, 1 - punched / 0.25)
                self.glove(screen, to_px(*hand.pos), s * 0.075 * grow, GLOVE_BLUE)

        if g.t < g.hurt_until:  # you got hit: red flash
            red = pygame.Surface(rect.size, pygame.SRCALPHA)
            red.fill((255, 30, 30, int(140 * (g.hurt_until - g.t) / 0.35)))
            screen.blit(red, rect)
        self.draw_pip(screen, rect, base, g)

        base.layer.fill((0, 0, 0, 0))
        self.draw_state(screen, g, rect, to_layer, s)
        screen.blit(base.layer, rect)
        for draw_text in base.later:
            draw_text()
        base.later.clear()
        screen.set_clip(None)
        self.draw_panels(screen, g, tracker, rect, fps)

    def draw_pip(self, screen, rect, base, g):
        """Your camera picture, small, in the bottom-right corner (with your skeleton)."""
        if base.cam_surf is None:
            return
        w = int(rect.w * 0.3)
        h = int(w * rect.h / rect.w)
        pip = pygame.transform.smoothscale(base.cam_surf, (w, h))
        box = pip.get_rect(bottomright=(rect.right - 10, rect.bottom - 10))
        screen.blit(pip, box)
        kp = g.me.kp
        if kp is not None:
            v = g.lobby.view
            for i, j in pl.BONES:
                if kp[i][2] > 0.4 and kp[j][2] > 0.4:
                    p = [v.world(kp[k][0], kp[k][1]) for k in (i, j)]
                    pts = [(box.x + px / v.aspect * w, box.y + py * h) for px, py in p]
                    pygame.draw.line(screen, (120, 255, 170), *pts, 2)
        pygame.draw.rect(screen, theme.GOLD, box, 2, border_radius=6)

    def draw_state(self, screen, g, rect, to_layer, s):
        base, st = self.base, g.state
        if base.no_signal:
            base.message(screen, rect, "Connecting to the camera...", 0.4, 0.055, theme.GOLD)
            base.message(screen, rect, f"({base.camera_status})", 0.52, 0.03, (200, 190, 170))
            return
        if st == "select":
            zones = g.zones()
            for i, spec in enumerate(g.boxers):
                def face(cx, cy, size, spec=spec):
                    pygame.draw.circle(base.layer, (*spec["skin"], 255), (cx, cy), size * 0.42)
                    for dx in (-0.15, 0.15):
                        pygame.draw.circle(base.layer, (30, 20, 20, 255), (cx + dx * size, cy - size * 0.05),
                                           max(2, size * 0.05))
                    band = pygame.Rect(0, 0, size * 0.8, size * 0.14)
                    band.center = (cx, cy - size * 0.28)
                    pygame.draw.rect(base.layer, (*spec["shirt"], 255), band, border_radius=4)
                level = ("easy", "medium", "hard")[min(i, 2)]
                base.choice_box(screen, rect, g, f"boxer{i}", zones[f"boxer{i}"], to_layer, s, spec["name"],
                                [level, f"wins {g.wins(i)}"], face)
            base.choice_box(screen, rect, g, "games", zones["games"], to_layer, s, "GAMES",
                            icon=base.grid_icon, compact=True)
            base.choice_box(screen, rect, g, "settings", zones["settings"], to_layer, s, "WI-FI",
                            icon=base.wifi_icon, compact=True)
            holding = any(g.hover[z] > 0 for z in zones)
            base.message(screen, rect, "Keep holding..." if holding else "Pick your opponent", 0.55, 0.045,
                         theme.GOLD if holding else theme.CREAM)
            base.message(screen, rect, "Remote:  Left / OK / Right = boxer  |  Up = games  |  Down = Wi-Fi",
                         0.63, 0.026, (200, 190, 170))
        elif st == "ready":
            base.message(screen, rect, f"vs {g.opponent.name}", 0.06, 0.07, theme.GOLD)
            base.message(screen, rect, "Raise both hands to start!", 0.88, 0.05)
            for hand in g.me.hands:
                if hand.pos is not None:
                    base.ring(to_layer(*hand.pos), int(s * 0.06), g.hold / g.cfg["game"]["hands_up_seconds"])
        elif st == "countdown":
            left = 3 - (g.t - g.state_t)
            f = theme.font(s * (0.2 + 0.15 * (left - math.floor(left))))
            base.later.append(functools.partial(theme.text, screen, f, str(max(1, math.ceil(left))), theme.GOLD,
                                                outline=4, center=rect.center))
        elif st == "fight":
            if g.paused:
                base.message(screen, rect, "Paused - come back in front of the camera", 0.45, 0.05, theme.GOLD)
            elif g.opponent.state == "windup":
                base.message(screen, rect, "!", 0.08, 0.1, WARN)
                base.message(screen, rect, "Block or dodge!", 0.9, 0.04, WARN)
            if g.t < g.message_until:
                base.message(screen, rect, g.message, 0.42, 0.09, g.message_color)
        elif st == "result":
            if g.won:
                base.message(screen, rect, "YOU WIN!", 0.18, 0.1, (120, 255, 140))
                base.message(screen, rect, f"{g.opponent.name} is knocked out", 0.3, 0.04)
            else:
                base.message(screen, rect, "KNOCKED OUT!", 0.18, 0.1, (255, 110, 90))
                base.message(screen, rect, f"{g.opponent.name} wins this time", 0.3, 0.04)
            if g.t - g.state_t >= g.b["result_seconds"]:
                base.message(screen, rect, "Raise both hands to continue", 0.9, 0.045)
                for hand in g.me.hands:
                    if hand.pos is not None:
                        base.ring(to_layer(*hand.pos), int(s * 0.06), g.hold / g.cfg["game"]["hands_up_seconds"])

    def draw_panels(self, screen, g, tracker, rect, fps):
        base = self.base
        left, right = theme.panels(screen.get_size(), rect)
        b = g.b
        fighting = g.state in ("ready", "countdown", "fight", "result") and g.opponent is not None
        if left:
            y = left.y + 30
            r = theme.text(screen, theme.font(left.w * 0.22), "BOXING", theme.GOLD, outline=3, midtop=(left.centerx, y))
            if fighting:
                theme.text(screen, theme.font(left.w * 0.11), "YOU", (120, 190, 255),
                           midtop=(left.centerx, left.y + left.h * 0.45))
                lives = b["hits_to_lose"]
                base.draw_hearts(screen, left.centerx, left.y + left.h * 0.58, lives - g.taken, lives,
                                 min(left.w / (lives * 1.5), left.w * 0.12))
            else:
                theme.text(screen, theme.font(left.w * 0.09, name="arial"), "WINS", theme.CREAM,
                           midtop=(left.centerx, r.bottom + left.h * 0.15))
                for i, spec in enumerate(g.boxers):
                    theme.text(screen, theme.font(left.w * 0.1), f"{spec['name'].title()}  {g.wins(i)}", theme.GOLD,
                               midtop=(left.centerx, r.bottom + left.h * (0.25 + 0.09 * i)))
        if right:
            if fighting:
                theme.text(screen, theme.font(right.w * 0.11), g.opponent.name, (255, 120, 110), outline=2,
                           midtop=(right.centerx, right.y + right.h * 0.45))
                n = b["hits_to_win"]
                base.draw_hearts(screen, right.centerx, right.y + right.h * 0.58, n - g.landed, n,
                                 min(right.w / (n * 1.5), right.w * 0.12))
            else:
                theme.text(screen, theme.font(right.w * 0.11), "HOW TO BOX", theme.GOLD, outline=2,
                           midtop=(right.centerx, right.y + 30))
                steps = ["Punch fast toward the boxer", "When a glove glows: cover your face with both gloves",
                         "...or lean / duck out of the way", f"Land {b['hits_to_win']} punches to win!"]
                f = theme.font(right.w * 0.075, name="arial")
                y = right.y + 30 + right.w * 0.2
                for i, step in enumerate(steps, 1):
                    for line in theme.wrap(f, f"{i}. {step}", right.w * 0.82):
                        theme.text(screen, f, line, theme.CREAM, outline=1, topleft=(right.x + right.w * 0.09, y))
                        y += f.get_height()
                    y += f.get_height() * 0.5
            if base.show_debug:
                f = theme.font(max(11, right.w // 22), bold=False, name="consolas")
                opp = g.opponent.state if g.opponent else "-"
                lines = [f"fps {fps:4.1f}  pose {tracker.pose_ms:4.1f} ms", f"boxer {opp}",
                         f"landed {g.landed}  taken {g.taken}"]
                for i, line in enumerate(lines):
                    theme.text(screen, f, line, (200, 190, 170), outline=1,
                               bottomleft=(right.x + 14, right.bottom - 14 - (len(lines) - 1 - i) * f.get_height()))
