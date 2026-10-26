"""Drawing and sound for Dress Up (rules in dressup.py): full screen, a magic mirror.

Each frame while wearing: the costume's scene, the pieces that hang behind the player (a cape), the
player cut out of the camera picture with the pose model's person mask, then the pieces in front,
each warped onto the body (dressup_fit.fit). Without a mask yet (the first frames, or if it's off
in the config) the camera picture shows as a window in the middle and only the front pieces draw.

The camera band keeps its own proportions (no stretching), so pieces land exactly on the body:
it's the play area's shape scaled to the screen height, centred, with the scene round it.
"""

import functools
import math

import cv2
import numpy as np
import pygame

import dressup_fit as df
import theme
from boxing_draw import GLOVE_BLUE

GOLD = (255, 205, 70)
EDGE = np.clip((np.arange(256) - 60) * 255 / 140, 0, 255).astype(np.uint8)  # mask -> alpha: a firmer outline


@functools.cache
def make_sounds():
    """Synthesised: a sparkly poof (costume change), a camera shutter, a twinkle (magic swing)."""
    try:
        sr, _, channels = pygame.mixer.get_init()
    except (TypeError, pygame.error):
        return {}
    rng = np.random.default_rng(3)

    def tone(freq, d, decay):
        t = np.arange(int(sr * d)) / sr
        return np.sin(2 * np.pi * freq * t) * np.exp(-t * decay) * np.minimum(1, t * 300)

    def snd(wave, vol):
        a = (np.clip(wave / (np.max(np.abs(wave)) or 1), -1, 1) * 32767 * vol).astype(np.int16)
        return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack([a, a]) if channels == 2 else a))

    notes = [784, 988, 1175, 1568, 1976]
    n = int(sr * 0.6)
    poof = np.zeros(n)
    for i, f in enumerate(notes):
        w = tone(f, 0.35, 9) + 0.3 * tone(f * 2, 0.35, 14)
        start = int(sr * 0.05 * i)
        poof[start:start + w.size] += w[:n - start]
    hiss = rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / sr * 7)
    poof += 0.25 * (hiss - np.convolve(hiss, np.ones(8) / 8, "same"))
    t = np.arange(int(sr * 0.12)) / sr
    click = rng.uniform(-1, 1, t.size) * np.exp(-t * 90)
    shutter = np.concatenate([click, np.zeros(int(sr * 0.05)), click * 0.7])
    twinkle = sum(tone(f, 0.25, 16) for f in (2093, 2637, 3136))
    return {"poof": snd(poof, 0.55), "shutter": snd(shutter, 0.7), "twinkle": snd(twinkle, 0.3)}


def pixel_format(screen):
    """Byte order matching the screen: blitting in the screen's own order is ~18x faster than
    making pygame swap channels on every blit (3.3 ms vs 0.2 ms for a 400x500 piece)."""
    return "BGRA" if screen.get_masks()[0] == 0xFF0000 else "RGBA"


def load_pixels(path, flip, fmt):
    """A picture as a 4-channel numpy array in fmt order (pygame reads the PNGs; no Pillow on the console)."""
    surf = pygame.image.load(path)
    if flip:
        surf = pygame.transform.flip(surf, True, False)
    w, h = surf.get_size()
    a = np.frombuffer(pygame.image.tobytes(surf, "RGBA"), np.uint8).reshape(h, w, 4)
    return np.ascontiguousarray(a[:, :, [2, 1, 0, 3]] if fmt == "BGRA" else a)


def warp(screen, img, M, fmt):
    """Draw a 4-channel picture placed by the 2x3 matrix M, warping only the area it covers."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = df.bbox(M, w, h)
    sw, sh = screen.get_size()
    X0, Y0, X1, Y1 = max(0, int(x0)), max(0, int(y0)), min(sw, int(math.ceil(x1))), min(sh, int(math.ceil(y1)))
    if X1 - X0 < 2 or Y1 - Y0 < 2 or (X1 - X0) * (Y1 - Y0) > sw * sh * 2:
        return
    M2 = M.copy()
    M2[:, 2] -= (X0, Y0)
    out = cv2.warpAffine(img, M2, (X1 - X0, Y1 - Y0), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    screen.blit(pygame.image.frombuffer(out.tobytes(), (X1 - X0, Y1 - Y0), fmt), (X0, Y0))


class DressUpRenderer:
    def __init__(self, base, cfg):
        self.base = base            # fruit_slice.Renderer: only its debug switch is used
        self.mirror = cfg["camera"]["mirror"]
        self.costumes = {}          # key -> costume.json with every view's picture loaded
        self.scenes = {}            # (key, size) -> scene surface
        self.previews = {}          # (key, height) -> preview surface
        self.person = None          # the player cut out (or the plain camera band), last fresh frame
        self.person_masked = False
        self.bg = None
        self.fmt = "RGBA"           # set to the screen's byte order on the first frame

    # ---------------------------------------------------------------- assets

    def costume(self, key):
        if key not in self.costumes:
            meta = df.load_costume(df.ASSETS / key, self.mirror)
            for piece in meta["pieces"]:
                for view in piece["views"]:
                    view["img"] = load_pixels(view["path"], view["flip"], self.fmt)
            self.costumes[key] = meta
        return self.costumes[key]

    def scene(self, key, size):
        if (key, size) not in self.scenes:
            surf = pygame.image.load(str(df.ASSETS / key / "scene.jpg")).convert()
            self.scenes[(key, size)] = pygame.transform.smoothscale(surf, size)
        return self.scenes[(key, size)]

    def preview(self, key, height):
        if (key, height) not in self.previews:
            surf = pygame.image.load(str(df.ASSETS / key / "preview.png")).convert_alpha()
            if self.mirror:
                surf = pygame.transform.flip(surf, True, False)
            w = max(1, int(surf.get_width() * height / surf.get_height()))
            self.previews[(key, height)] = pygame.transform.smoothscale(surf, (w, int(height)))
        return self.previews[(key, height)]

    # ---------------------------------------------------------------- frame

    def draw(self, screen, g, tracker, frame, fresh, view, fps):
        W, H = screen.get_size()
        fmt = pixel_format(screen)
        if fmt != self.fmt:
            self.fmt, self.costumes = fmt, {}
        if g.state == "pick" or not g.costumes:
            self.draw_pick(screen, g, W, H)
            return
        d = g.d
        band_w = int(view.aspect * H)
        x0 = (W - band_w) // 2

        def to_screen(x, y):  # keypoint (0..1 of the camera picture) -> screen pixels
            wx, wy = view.world(x, y)
            return x0 + wx * H, wy * H

        def to_px(x, y):      # world units (effects) -> screen pixels
            return int(x0 + x * H), int(y * H)

        meta = self.costume(g.key)
        if d["scene"]:
            screen.blit(self.scene(g.key, (W, H)), (0, 0))
        else:
            screen.fill((20, 18, 30))
        if not g.frozen and frame is not None and (fresh or self.person is None):
            self.cut_out(frame, tracker, view, band_w, H, d["person_mask"])
        kp, min_vis = g.kp, d["min_visibility"]
        ratio = df.head_ratio(kp, to_screen, min_vis)
        if self.person_masked:
            self.pieces(screen, meta, "behind", kp, to_screen, min_vis, ratio)
        if self.person is not None:
            screen.blit(self.person, (x0, 0))
            if not self.person_masked:
                pygame.draw.rect(screen, GOLD, pygame.Rect(x0, 0, band_w, H), 3)
        self.pieces(screen, meta, "front", kp, to_screen, min_vis, ratio)
        g.fx.draw_front(screen, to_px, H, lambda size, grow: theme.font(H / 12))
        if g.fx.flash > 0:  # the photo flash
            white = pygame.Surface((W, H))
            white.fill((255, 255, 255))
            white.set_alpha(int(255 * min(1.0, g.fx.flash)))
            screen.blit(white, (0, 0))
        self.draw_hud(screen, g, meta, tracker, W, H, fps)

    def cut_out(self, frame, tracker, view, w, h, use_mask):
        """The player from the newest camera picture: masked out of their room if the outline is
        there, else the whole picture."""
        bgr = cv2.resize(view.crop(frame), (w, h))
        mask = tracker.latest_mask()[1] if use_mask and hasattr(tracker, "latest_mask") else None
        if mask is not None:
            alpha = cv2.resize(view.crop(mask), (w, h), interpolation=cv2.INTER_LINEAR)
            alpha = cv2.LUT(alpha, EDGE)
            pixels = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA if self.fmt == "BGRA" else cv2.COLOR_BGR2RGBA)
            pixels[:, :, 3] = alpha
            self.person = pygame.image.frombuffer(pixels.tobytes(), (w, h), self.fmt)
            self.person_masked = True
        else:
            self.person = pygame.image.frombuffer(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes(), (w, h), "RGB")
            self.person_masked = False

    def pieces(self, screen, meta, layer, kp, to_screen, min_vis, ratio):
        for piece in meta["pieces"]:
            if piece.get("layer", "front") != layer:
                continue
            view = df.pick_view(piece["views"], ratio)
            M = df.fit(view["anchors"], kp, to_screen, piece.get("min_vis", min_vis), piece.get("rotate", 1.0),
                       view.get("scale_ref"))
            if M is not None:
                warp(screen, view["img"], M, self.fmt)

    # ---------------------------------------------------------------- screens

    def button(self, screen, box, frac, title):
        panel = pygame.Surface(box.inflate(16, 16).size, pygame.SRCALPHA)
        inner = pygame.Rect(8, 8, box.w, box.h)
        if frac > 0:
            pygame.draw.rect(panel, (255, 210, 90, 100), panel.get_rect(), border_radius=18)
        pygame.draw.rect(panel, (18, 14, 40, 210), inner, border_radius=14)
        fill = inner.copy()
        fill.h = int(inner.h * frac)
        fill.bottom = inner.bottom
        pygame.draw.rect(panel, (240, 190, 70, 120), fill, border_radius=14)
        screen.blit(panel, box.inflate(16, 16))
        pygame.draw.rect(screen, (255, 240, 200) if frac > 0 else (170, 130, 240), box, 4 if frac > 0 else 2,
                         border_radius=14)
        theme.text(screen, theme.font(box.h * 0.45), title, theme.CREAM, outline=2, center=box.center)

    @staticmethod
    def rect(zone, W, H):
        u0, v0, u1, v1 = zone
        return pygame.Rect(int(u0 * W), int(v0 * H), int((u1 - u0) * W), int((v1 - v0) * H))

    def draw_pick(self, screen, g, W, H):
        if self.bg is None or self.bg.get_size() != (W, H):
            self.bg = pygame.Surface((W, H))
            for y in range(H):
                k = y / H
                self.bg.fill((int(40 + 30 * k), int(14 + 10 * k), int(60 + 30 * k)), pygame.Rect(0, y, W, 1))
        screen.blit(self.bg, (0, 0))
        theme.text(screen, theme.font(H * 0.075), "DRESS UP", GOLD, outline=4, center=(W // 2, int(H * 0.085)))
        zones = g.zones()
        for i, key in enumerate(g.costumes):
            zone = f"c{i}"
            box = self.rect(zones[zone], W, H)
            frac = min(1.0, g.hover.get(zone, 0.0) / g.hover_needed(zone))
            focused = g.focus == i
            screen.blit(pygame.transform.smoothscale(self.scene(key, (W, H)), box.size), box)
            img = self.preview(key, box.h * 0.92)
            clip = screen.get_clip()
            screen.set_clip(box)
            screen.blit(img, img.get_rect(midbottom=(box.centerx, box.bottom + box.h * 0.02)))
            screen.set_clip(clip)
            label = pygame.Rect(box.x, box.bottom - box.h * 0.2, box.w, box.h * 0.2)
            shade = pygame.Surface(label.size, pygame.SRCALPHA)
            shade.fill((10, 8, 24, 190))
            screen.blit(shade, label)
            fill = box.copy()
            fill.h = int(box.h * frac)
            fill.bottom = box.bottom
            if frac > 0:
                glow = pygame.Surface(fill.size, pygame.SRCALPHA)
                glow.fill((240, 190, 70, 90))
                screen.blit(glow, fill)
            theme.text(screen, theme.font(label.h * 0.6), self.costume(key)["name"], GOLD, outline=2, center=label.center)
            pygame.draw.rect(screen, (255, 240, 200) if frac > 0 or focused else (150, 110, 220), box,
                             5 if frac > 0 or focused else 2, border_radius=12)
        if not g.costumes:
            theme.text(screen, theme.font(H * 0.045), "No costumes yet: run tools/blender/render_costume.py",
                       theme.CREAM, outline=2, center=(W // 2, H // 2))
        home = self.rect(zones["home"], W, H)
        self.button(screen, home, min(1.0, g.hover.get("home", 0.0) / g.hover_needed("home")), "HOME")
        holding = any(v > 0 for v in g.hover.values())
        theme.text(screen, theme.font(H * 0.038), "Keep holding..." if holding else "Raise a hand, point at a costume and hold",
                   theme.CREAM, outline=2, center=(W // 2, int(H * 0.925)))
        theme.text(screen, theme.font(H * 0.024, name="arial"), "Remote:  arrows move  |  OK picks  |  Back = home",
                   (190, 180, 210), outline=1, center=(W // 2, int(H * 0.97)))
        self.cursors(screen, g, W, H)

    def draw_hud(self, screen, g, meta, tracker, W, H, fps):
        zones = g.zones()
        for zone, title in (("costumes", "COSTUMES"), ("photo", "PHOTO")):
            self.button(screen, self.rect(zones[zone], W, H), min(1.0, g.hover.get(zone, 0.0) / g.hover_needed(zone)), title)
        since = g.t - g.changed_t
        if since < 1.8:  # the costume's name pops in after a change
            size = H * (0.09 + 0.03 * max(0.0, 1 - since / 0.25))
            theme.text(screen, theme.font(size), meta["name"], GOLD, outline=4, center=(W // 2, int(H * 0.2)))
        if g.photo_t is not None:
            left = g.d["photo_countdown"] - (g.t - g.photo_t)
            theme.text(screen, theme.font(H * 0.06), "Strike a pose!", theme.CREAM, outline=3, center=(W // 2, int(H * 0.2)))
            k = left - math.floor(left)
            theme.text(screen, theme.font(H * (0.2 + 0.1 * k)), str(max(1, math.ceil(left))), GOLD, outline=5,
                       center=(W // 2, H // 2))
        elif g.frozen:
            theme.text(screen, theme.font(H * 0.07), "Looking great!", GOLD, outline=4, center=(W // 2, int(H * 0.88)))
        if not getattr(tracker, "signal", True):
            theme.text(screen, theme.font(H * 0.055), "Connecting to the camera...", GOLD, outline=3, center=(W // 2, H // 2))
        elif g.kp is None:
            theme.text(screen, theme.font(H * 0.055), "Step in front of the camera!", theme.CREAM, outline=3,
                       center=(W // 2, int(H * 0.5)))
        self.cursors(screen, g, W, H)
        if self.base.show_debug:
            f = theme.font(max(11, H // 45), bold=False, name="consolas")
            theme.text(screen, f, f"fps {fps:4.1f}  pose {tracker.pose_ms:4.1f} ms  mask {'on' if self.person_masked else 'off'}",
                       (200, 190, 170), outline=1, bottomleft=(14, H - 10))

    @staticmethod
    def cursors(screen, g, W, H):
        r = int(H * 0.025)
        for u, v in g.lobby.pointers():
            pygame.draw.circle(screen, (20, 60, 140), (int(u * W), int(v * H)), r + 2)
            pygame.draw.circle(screen, GLOVE_BLUE, (int(u * W), int(v * H)), r)
