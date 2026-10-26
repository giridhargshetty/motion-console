"""The console's home screen, like a TV's: a grid of game tiles plus Settings, full screen.

Six tiles: the games that exist, then "coming soon" slots for future ones (add a game by adding
an entry to GAMES and handling its key in console.py). Pick by pointing with a raised hand and
holding (the same pointer mapping as the setup screens, so arms resting at your sides pick
nothing), or with a remote: arrows move, OK opens.
"""

import math
import time
from pathlib import Path

import pygame

import theme
from boxing_draw import GLOVE_BLUE, boxer_sprites

# (key, title, subtitle); None = an empty slot for a future game
GAMES = [("fruit", "FRUIT SLICE", "1 or 2 players"), ("boxing", "BOXING", "1 player"),
         ("dressup", "DRESS UP", "1 player"), None, None, None]
COLS = 3
SETTINGS = (0.8, 0.04, 0.96, 0.13)   # u0, v0, u1, v1 in 0..1 of the screen
GRID = (0.06, 0.2, 0.94, 0.86)
GAP = 0.03
GOLD = (255, 205, 70)


def tile_zones():
    """Pickable areas in 0..1 screen units: tile0..tile5 and settings."""
    u0, v0, u1, v1 = GRID
    rows = math.ceil(len(GAMES) / COLS)
    w = (u1 - u0 - GAP * (COLS - 1)) / COLS
    h = (v1 - v0 - GAP * (rows - 1)) / rows
    zones = {f"tile{i}": (u0 + (i % COLS) * (w + GAP), v0 + (i // COLS) * (h + GAP),
                          u0 + (i % COLS) * (w + GAP) + w, v0 + (i // COLS) * (h + GAP) + h)
             for i in range(len(GAMES))}
    zones["settings"] = SETTINGS
    return zones


class Home:
    """Hover / remote logic. update() returns what was picked: a game key, "settings", or None."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.zones = tile_zones()
        self.hover = dict.fromkeys(self.zones, 0.0)
        self.focus = "tile0"     # the remote's highlighted tile
        self.sounds = []
        self.nope = {}           # zone -> time a "coming soon" tile was tried (it wobbles)
        self.t = 0.0

    def needed(self, zone):
        m = self.cfg["menu"]
        return m["settings_hover_seconds"] if zone == "settings" else m["hover_seconds"]

    def update(self, pointers, dt):
        self.t += dt
        for zone, (u0, v0, u1, v1) in self.zones.items():
            inside = any(u0 <= u <= u1 and v0 <= v <= v1 for u, v in pointers)
            self.hover[zone] = self.hover[zone] + dt if inside else max(0.0, self.hover[zone] - 2 * dt)
            if inside:
                self.focus = zone
            if self.hover[zone] >= self.needed(zone):
                return self.pick(zone)
        return None

    def pick(self, zone):
        self.hover = dict.fromkeys(self.hover, 0.0)
        if zone == "settings":
            self.sounds.append("select")
            return "settings"
        game = GAMES[int(zone[4:])]
        if game is None:
            self.nope[zone] = self.t
            self.sounds.append("beep")
            return None
        self.sounds.append("select")
        return game[0]

    def press(self, key):
        """Remote: arrows move round the grid (Up from the top row reaches Settings), OK opens."""
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.pick(self.focus)
        if self.focus == "settings":
            if key == pygame.K_DOWN:
                self.focus = f"tile{COLS - 1}"
            return None
        i = int(self.focus[4:])
        if key == pygame.K_LEFT and i % COLS:
            i -= 1
        elif key == pygame.K_RIGHT and i % COLS < COLS - 1 and i + 1 < len(GAMES):
            i += 1
        elif key == pygame.K_UP:
            if i < COLS:
                self.focus = "settings"
                return None
            i -= COLS
        elif key == pygame.K_DOWN and i + COLS < len(GAMES):
            i += COLS
        self.focus = f"tile{i}"
        return None


class HomeRenderer:
    def __init__(self, base):
        self.base = base          # fruit_slice.Renderer: its fruit art for the Fruit Slice tile
        self.bg_key = None
        self.bg = None

    def background(self, size):
        if self.bg_key != size:
            w, h = size
            bg = pygame.Surface(size)
            for y in range(h):
                k = y / h
                bg.fill((int(12 + 10 * k), int(14 + 8 * k), int(30 + 22 * k)), pygame.Rect(0, y, w, 1))
            self.bg_key, self.bg = size, bg
        return self.bg

    def draw(self, screen, home, game, tracker):
        W, H = screen.get_size()
        screen.blit(self.background((W, H)), (0, 0))
        t = home.t
        for i in range(3):  # slow drifting glows: the screen feels alive while you choose
            x = W * (0.5 + 0.4 * math.sin(t * 0.13 + i * 2.1))
            y = H * (0.55 + 0.3 * math.cos(t * 0.11 + i * 1.7))
            glow = self.glow(int(H * 0.5), ((40, 30, 90), (20, 50, 90), (70, 25, 60))[i])
            screen.blit(glow, glow.get_rect(center=(x, y)), special_flags=pygame.BLEND_ADD)

        theme.text(screen, theme.font(H * 0.065), "MOTION CONSOLE", GOLD, outline=3, topleft=(W * 0.06, H * 0.045))
        theme.text(screen, theme.font(H * 0.05), time.strftime("%H:%M"), theme.CREAM, outline=2,
                   midright=(W * 0.77, H * 0.085))

        def rect(zone):
            u0, v0, u1, v1 = home.zones[zone]
            return pygame.Rect(int(u0 * W), int(v0 * H), int((u1 - u0) * W), int((v1 - v0) * H))

        for i, entry in enumerate(GAMES):
            zone = f"tile{i}"
            self.tile(screen, rect(zone), entry, home, zone, H)
        box = rect("settings")
        self.frame(screen, box, home, "settings")
        self.gear(screen, (box.x + box.h * 0.55, box.centery), box.h * 0.32, theme.CREAM)
        theme.text(screen, theme.font(box.h * 0.42), "SETTINGS", theme.CREAM, outline=2,
                   midleft=(box.x + box.h * 1.05, box.centery))

        no_signal = not getattr(tracker, "signal", True)
        if no_signal:
            msg = "Connecting to the camera..."
        elif any(v > 0 for v in home.hover.values()):
            msg = "Keep holding..."
        else:
            msg = "Raise a hand, point at a game and hold"
        theme.text(screen, theme.font(H * 0.04), msg, theme.CREAM, outline=2, center=(W // 2, int(H * 0.925)))
        theme.text(screen, theme.font(H * 0.024, name="arial"), "Remote:  arrows move  |  OK opens", (170, 165, 190),
                   outline=1, center=(W // 2, int(H * 0.97)))
        for u, v in game.pointers():  # where your hands point
            self.cursor(screen, (int(u * W), int(v * H)), H * 0.03)

    @staticmethod
    def glow(r, color):
        return _glow(r, color)

    def frame(self, screen, box, home, zone):
        """Tile body: dark glass, a glow while held or focused, filling from the bottom."""
        frac = min(1.0, home.hover[zone] / home.needed(zone))
        focused = home.focus == zone
        outer = box.inflate(24, 24)
        panel = pygame.Surface(outer.size, pygame.SRCALPHA)
        inner = box.move(-outer.x, -outer.y)
        if frac > 0 or focused:
            pygame.draw.rect(panel, (255, 210, 90, 70 if frac == 0 else 110), panel.get_rect(), border_radius=24)
        pygame.draw.rect(panel, (18, 16, 40, 225), inner, border_radius=18)
        fill = inner.copy()
        fill.h = int(inner.h * frac)
        fill.bottom = inner.bottom
        pygame.draw.rect(panel, (240, 190, 70, 90), fill, border_radius=18)
        screen.blit(panel, outer)
        color = (255, 240, 200) if frac > 0 or focused else (90, 80, 140)
        pygame.draw.rect(screen, color, box, 4 if frac > 0 or focused else 2, border_radius=18)

    def tile(self, screen, box, entry, home, zone, H):
        if entry is None:  # an empty slot: dashed outline, "coming soon"; wobbles if tried
            tried = home.t - home.nope.get(zone, -9)
            if tried < 0.4:
                box = box.move(int(math.sin(tried * 40) * 8 * (1 - tried / 0.4)), 0)
            focused = home.focus == zone or home.hover[zone] > 0
            color = (150, 140, 200) if focused else (70, 64, 110)
            self.dashed(screen, box, color)
            c = box.center
            arm = box.h * 0.1
            pygame.draw.line(screen, color, (c[0] - arm, c[1] - box.h * 0.08), (c[0] + arm, c[1] - box.h * 0.08), 5)
            pygame.draw.line(screen, color, (c[0], c[1] - box.h * 0.08 - arm), (c[0], c[1] - box.h * 0.08 + arm), 5)
            theme.text(screen, theme.font(box.h * 0.1), "COMING SOON", color, outline=0,
                       center=(c[0], int(box.y + box.h * 0.72)))
            return
        key, title, sub = entry
        self.frame(screen, box, home, zone)
        art = box.inflate(-16, -16)
        art.h = int(box.h * 0.66)
        clip = screen.get_clip()
        screen.set_clip(art)
        if key == "fruit":
            self.fruit_art(screen, art, home.t)
        elif key == "boxing":
            self.boxing_art(screen, art, home.t)
        elif key == "dressup":
            self.dressup_art(screen, art, home.t)
        screen.set_clip(clip)
        theme.text(screen, theme.font(box.h * 0.13), title, GOLD, outline=2,
                   center=(box.centerx, int(box.y + box.h * 0.79)))
        theme.text(screen, theme.font(box.h * 0.065, name="arial"), sub, theme.CREAM, outline=1,
                   center=(box.centerx, int(box.y + box.h * 0.9)))

    def fruit_art(self, screen, art, t):
        """Wood backdrop and a few fruits bobbing (the game's own fruit pictures)."""
        screen.blit(_wood(art.size), art)
        import fruits as fr
        kinds = [fr.TYPES[i % len(fr.TYPES)] for i in (9, 2, 5, 0)]
        for i, kind in enumerate(kinds):
            size = int(art.h * (0.21 if i == 0 else 0.14))  # radius
            surf = self.base.art.get(kind, size, "whole")
            x = art.x + art.w * (0.5 if i == 0 else (0.18, 0.82, 0.32)[i - 1])
            y = art.y + art.h * (0.5 if i == 0 else (0.35, 0.4, 0.78)[i - 1]) + math.sin(t * 2 + i) * art.h * 0.04
            screen.blit(surf, surf.get_rect(center=(x, y)))

    def boxing_art(self, screen, art, t):
        """Ring colours and the boxer's idle animation."""
        pygame.draw.rect(screen, (30, 24, 60), art)
        for i, color in enumerate(((225, 45, 50), (240, 240, 240), (50, 90, 230))):
            y = art.y + art.h * (0.45 + 0.12 * i)
            pygame.draw.line(screen, color, (art.x, y), (art.right, y), max(2, art.h // 50))
        frames = boxer_sprites({"sprite": "rookie"})
        img = frames and frames.frame("idle", t, art.h * 2.2)
        if img is not None:  # head to waist: the frame has empty space round the boxer
            screen.blit(img, img.get_rect(midtop=(art.centerx, art.y - img.get_height() * 0.19)))

    def dressup_art(self, screen, art, t):
        """Costume previews taking turns: one in front, the others peeking from the sides."""
        pygame.draw.rect(screen, (60, 26, 80), art)
        names = [n for n in ("knight", "royal", "viking", "wizard", "dark_knight", "gladiator", "archer", "pirate", "superhero", "zombie")
                 if (COSTUMES / n / "preview.png").exists()]
        if not names:
            return
        front = int(t / 2.5) % len(names)
        for i, dx in ((front - 1, -0.3), (front + 1, 0.3), (front, 0.0)):
            img = _preview(names[i % len(names)], int(art.h * (0.95 if dx == 0 else 0.75)))
            screen.blit(img, img.get_rect(midbottom=(art.centerx + art.w * dx, art.bottom + art.h * 0.03)))

    @staticmethod
    def dashed(screen, box, color, dash=16):
        for x0, y0, x1, y1 in ((box.left, box.top, box.right, box.top), (box.right, box.top, box.right, box.bottom),
                               (box.right, box.bottom, box.left, box.bottom), (box.left, box.bottom, box.left, box.top)):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / dash))
            for k in range(0, n, 2):
                a, b = k / n, min(1, (k + 1) / n)
                pygame.draw.line(screen, color, (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                                 (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b), 3)

    @staticmethod
    def gear(screen, center, r, color):
        cx, cy = center
        for k in range(8):
            a = k * math.pi / 4
            pygame.draw.line(screen, color, (cx + math.cos(a) * r * 0.6, cy + math.sin(a) * r * 0.6),
                             (cx + math.cos(a) * r * 1.05, cy + math.sin(a) * r * 1.05), max(3, int(r * 0.35)))
        pygame.draw.circle(screen, color, (cx, cy), int(r * 0.75))
        pygame.draw.circle(screen, (18, 16, 40), (cx, cy), int(r * 0.32))

    @staticmethod
    def cursor(screen, pos, r):
        """A small glove for each pointing hand."""
        x, y = pos
        r = int(r)
        pygame.draw.circle(screen, (20, 60, 140), (x, y), r + 2)
        pygame.draw.circle(screen, GLOVE_BLUE, (x, y), r)
        pygame.draw.ellipse(screen, (140, 190, 255), pygame.Rect(x - r * 0.45, y - r * 0.7, r * 0.55, r * 0.35))


_glows = {}


def _glow(r, color):
    key = (r, color)
    if key not in _glows:
        surf = pygame.Surface((r * 2, r * 2))
        for k in range(r, 0, -3):
            f = (1 - k / r) ** 2
            pygame.draw.circle(surf, tuple(int(c * f) for c in color), (r, r), k)
        _glows[key] = surf
    return _glows[key]


COSTUMES = Path(__file__).resolve().parent.parent / "assets" / "costumes"
_previews = {}


def _preview(name, height):
    key = (name, height)
    if key not in _previews:
        surf = pygame.image.load(str(COSTUMES / name / "preview.png")).convert_alpha()
        w = max(1, int(surf.get_width() * height / surf.get_height()))
        _previews[key] = pygame.transform.smoothscale(surf, (w, height))
    return _previews[key]


_woods = {}


def _wood(size):
    if size not in _woods:
        _woods[size] = theme.wood(size)
    return _woods[size]
