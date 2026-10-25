"""Fruit and bomb artwork, drawn with pygame shapes (no image files to licence).

Every fruit has two drawings: `whole` (flying) and `cut` (the face you see inside a half).
Art.get() renders them once per pixel size and caches the surface.
"""

import math
import random
from dataclasses import dataclass
from typing import Callable

import pygame


def lerp(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c[:3])


def ell(cx, cy, w, h):
    return pygame.Rect(round(cx - w / 2), round(cy - h / 2), round(w), round(h))


def shaded_ellipse(s, cx, cy, w, h, base, light, steps=12):
    """Fake 3D: a dark rim, then shrinking ellipses blending to the highlight toward the top-left."""
    pygame.draw.ellipse(s, shade(base, 0.6), ell(cx, cy, w, h))
    for i in range(steps):
        k = i / steps
        f = 0.94 * (1 - 0.8 * k)
        pygame.draw.ellipse(s, lerp(base, light, k ** 1.5),
                            ell(cx - w * 0.17 * k, cy - h * 0.17 * k, w * f, h * f))


def clip_to_ellipse(layer, rect):
    mask = pygame.Surface(layer.get_size(), pygame.SRCALPHA)
    pygame.draw.ellipse(mask, (255, 255, 255, 255), rect)
    layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)


def leaf(s, x, y, length, angle_deg, color=(70, 160, 50)):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    half = [(t / 8 * length, math.sin(t / 8 * math.pi) * length * 0.3) for t in range(9)]
    pts = half + [(px, -py) for px, py in reversed(half)]
    pts = [(x + px * ca - py * sa, y + px * sa + py * ca) for px, py in pts]
    pygame.draw.polygon(s, color, pts)
    pygame.draw.line(s, shade(color, 0.65), (x, y), pts[8], max(1, int(length / 12)))


def seeds_ring(s, cx, cy, radius, n, size, color, rx=1.0):
    for i in range(n):
        a = 2 * math.pi * i / n
        pygame.draw.ellipse(s, color, ell(cx + math.cos(a) * radius * rx, cy + math.sin(a) * radius,
                                          size * 0.7, size))


def segments(s, cx, cy, w, h, n, color, width):
    for i in range(n):
        a = 2 * math.pi * i / n
        pygame.draw.line(s, color, (cx, cy), (cx + math.cos(a) * w / 2, cy + math.sin(a) * h / 2), width)


# ---- fruits: each takes (surface, centre x, centre y, radius px) ----

def apple(s, x, y, r):
    shaded_ellipse(s, x, y + r * 0.04, 2 * r, 1.9 * r, (205, 25, 35), (255, 150, 150))
    pygame.draw.arc(s, (120, 10, 20), ell(x, y - r * 0.82, r * 0.7, r * 0.4), math.pi * 1.15,
                    math.pi * 1.85, max(2, r // 12))
    pygame.draw.line(s, (100, 60, 25), (x, y - r * 0.7), (x + r * 0.12, y - r * 1.2), max(2, r // 8))
    leaf(s, x + r * 0.12, y - r * 1.05, r * 0.55, -20)


def apple_cut(s, x, y, r):
    pygame.draw.ellipse(s, (205, 25, 35), ell(x, y, 2 * r, 1.9 * r))
    pygame.draw.ellipse(s, (255, 246, 215), ell(x, y, 1.84 * r, 1.74 * r))
    pygame.draw.ellipse(s, (240, 232, 185), ell(x, y, 0.7 * r, 0.9 * r))
    seeds_ring(s, x, y, r * 0.2, 5, r * 0.16, (90, 50, 20))


def orange(s, x, y, r):
    shaded_ellipse(s, x, y, 2 * r, 2 * r, (240, 125, 15), (255, 205, 120))
    rng = random.Random(7)
    for _ in range(int(r * 1.2)):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.85) * r
        pygame.draw.circle(s, (215, 105, 10), (x + math.cos(a) * d, y + math.sin(a) * d), max(1, r / 28))
    pygame.draw.circle(s, (90, 140, 40), (x, y - r * 0.9), r * 0.12)


def orange_cut(s, x, y, r):
    pygame.draw.circle(s, (240, 125, 15), (x, y), r)
    pygame.draw.circle(s, (255, 240, 220), (x, y), r * 0.9)
    pygame.draw.circle(s, (255, 160, 35), (x, y), r * 0.82)
    pygame.draw.circle(s, (255, 190, 80), (x, y), r * 0.55)
    segments(s, x, y, r * 1.64, r * 1.64, 10, (255, 235, 200), max(2, r // 14))
    pygame.draw.circle(s, (255, 240, 220), (x, y), r * 0.12)


def lemon(s, x, y, r):
    pygame.draw.ellipse(s, (215, 185, 20), ell(x - r * 0.95, y, r * 0.35, r * 0.3))
    pygame.draw.ellipse(s, (215, 185, 20), ell(x + r * 0.95, y, r * 0.35, r * 0.3))
    shaded_ellipse(s, x, y, 1.95 * r, 1.55 * r, (240, 210, 30), (255, 248, 160))


def lemon_cut(s, x, y, r):
    pygame.draw.ellipse(s, (240, 210, 30), ell(x, y, 1.95 * r, 1.55 * r))
    pygame.draw.ellipse(s, (255, 250, 225), ell(x, y, 1.78 * r, 1.4 * r))
    pygame.draw.ellipse(s, (250, 238, 120), ell(x, y, 1.62 * r, 1.26 * r))
    segments(s, x, y, 1.62 * r, 1.26 * r, 8, (255, 250, 220), max(2, r // 14))


def banana(s, x, y, r):
    outer, thick = 1.7 * r, 0.85 * r
    cx, cy = x, y - 1.3 * r  # centre of the curve, above the fruit
    a0, a1 = math.radians(40), math.radians(140)
    top, bottom = [], []
    for i in range(21):
        t = i / 20
        a = a0 + (a1 - a0) * t
        inner = outer - thick * (0.15 + 0.85 * math.sin(math.pi * t))
        bottom.append((cx + math.cos(a) * outer, cy + math.sin(a) * outer))
        top.append((cx + math.cos(a) * inner, cy + math.sin(a) * inner))
    pygame.draw.polygon(s, (205, 165, 20), bottom + top[::-1])
    mid = [((bx + tx) / 2, (by + ty) / 2) for (bx, by), (tx, ty) in zip(bottom, top)]
    light = [((m[0] + t[0]) / 2, (m[1] + t[1]) / 2) for m, t in zip(mid, top)]
    pygame.draw.polygon(s, (250, 215, 55), mid[2:-2] + top[2:-2][::-1])
    pygame.draw.lines(s, (255, 240, 140), False, light[3:-3], max(2, r // 9))
    pygame.draw.circle(s, (90, 60, 25), bottom[0], r * 0.09)
    pygame.draw.line(s, (120, 110, 40), top[-1], (top[-1][0] + r * 0.18, top[-1][1] - r * 0.22),
                     max(2, r // 7))


def banana_cut(s, x, y, r):
    pygame.draw.circle(s, (230, 190, 40), (x, y), r * 0.62)
    pygame.draw.circle(s, (252, 244, 205), (x, y), r * 0.54)
    for i in range(3):
        a = 2 * math.pi * i / 3 + 0.5
        pygame.draw.circle(s, (150, 120, 70), (x + math.cos(a) * r * 0.12, y + math.sin(a) * r * 0.12), r * 0.04)


def pineapple(s, x, y, r):
    for i, a in enumerate((-55, -32, -12, 8, 28, 50)):  # crown
        color = (55, 125, 45) if i % 2 else (80, 160, 60)
        leaf(s, x, y - r * 0.55, r * (0.85 if abs(a) < 20 else 0.65), a - 90, color)
    body = ell(x, y + r * 0.25, 1.5 * r, 1.75 * r)
    layer = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    shaded_ellipse(layer, body.centerx, body.centery, body.w, body.h, (210, 145, 30), (255, 215, 100))
    step = r * 0.32
    for k in range(-8, 9):
        off = k * step
        pygame.draw.line(layer, (150, 95, 20), (x + off - r * 2, y - r * 2), (x + off + r * 2, y + r * 2), 2)
        pygame.draw.line(layer, (150, 95, 20), (x + off + r * 2, y - r * 2), (x + off - r * 2, y + r * 2), 2)
    clip_to_ellipse(layer, body)
    s.blit(layer, (0, 0))


def pineapple_cut(s, x, y, r):
    pygame.draw.ellipse(s, (190, 125, 25), ell(x, y, 1.5 * r, 1.75 * r))
    pygame.draw.ellipse(s, (255, 228, 110), ell(x, y, 1.32 * r, 1.57 * r))
    segments(s, x, y, 1.2 * r, 1.45 * r, 12, (245, 210, 90), max(1, r // 18))
    pygame.draw.ellipse(s, (255, 245, 195), ell(x, y, 0.4 * r, 0.5 * r))


def watermelon(s, x, y, r):
    body = ell(x, y, 2 * r, 1.75 * r)
    layer = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    shaded_ellipse(layer, x, y, body.w, body.h, (45, 125, 45), (130, 200, 90))
    for k in range(-4, 5):
        pts = [(x + k * r * 0.3 + math.sin(j * 0.9 + k) * r * 0.06, y - r + j * r * 0.2) for j in range(11)]
        pygame.draw.lines(layer, (25, 80, 30), False, pts, max(3, int(r * 0.11)))
    clip_to_ellipse(layer, body)
    s.blit(layer, (0, 0))


def watermelon_cut(s, x, y, r):
    pygame.draw.ellipse(s, (40, 115, 40), ell(x, y, 2 * r, 1.75 * r))
    pygame.draw.ellipse(s, (205, 238, 175), ell(x, y, 1.82 * r, 1.58 * r))
    shaded_ellipse(s, x, y, 1.66 * r, 1.42 * r, (225, 40, 55), (255, 120, 120), steps=6)
    seeds_ring(s, x, y, r * 0.48, 9, r * 0.13, (30, 20, 20), rx=1.15)
    seeds_ring(s, x, y, r * 0.25, 5, r * 0.11, (30, 20, 20), rx=1.15)


def coconut(s, x, y, r):
    shaded_ellipse(s, x, y, 2 * r, 2 * r, (95, 60, 30), (160, 115, 65))
    rng = random.Random(3)
    for _ in range(int(r * 1.5)):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.9) * r
        px, py = x + math.cos(a) * d, y + math.sin(a) * d
        b = rng.uniform(0, math.pi)
        color = (70, 42, 20) if rng.random() < 0.6 else (175, 130, 80)
        pygame.draw.line(s, color, (px, py), (px + math.cos(b) * r * 0.15, py + math.sin(b) * r * 0.15), 1)
    for ex, ey in ((-0.18, -0.45), (0.18, -0.45), (0, -0.2)):
        pygame.draw.circle(s, (45, 28, 15), (x + ex * r, y + ey * r), r * 0.1)


def coconut_cut(s, x, y, r):
    pygame.draw.circle(s, (95, 60, 30), (x, y), r)
    pygame.draw.circle(s, (250, 250, 245), (x, y), r * 0.86)
    pygame.draw.circle(s, (215, 230, 238), (x, y), r * 0.6)


def strawberry_shape(x, y, r, k=1.0):
    pts = []
    for i in range(48):
        u = 2 * math.pi * i / 48
        w = 1 - 0.55 * ((1 - math.cos(u)) / 2) ** 1.4  # narrows toward the bottom tip
        pts.append((x + 0.88 * r * k * math.sin(u) * w, y + 0.05 * r - 0.95 * r * k * math.cos(u)))
    return pts


def strawberry(s, x, y, r):
    pygame.draw.polygon(s, (215, 25, 45), strawberry_shape(x, y, r))
    pygame.draw.ellipse(s, (250, 95, 105), ell(x - r * 0.3, y - r * 0.3, r * 0.45, r * 0.6))
    rng = random.Random(5)
    for row in range(5):
        yy = y - r * 0.55 + row * r * 0.3
        width = 0.7 * (1 - row / 6)
        for col in range(-2, 3):
            xx = x - r * 0.04 + col * r * 0.3 * width + rng.uniform(-2, 2)
            pygame.draw.ellipse(s, (250, 215, 90), ell(xx, yy, r * 0.07, r * 0.11))
    for a in (-150, -110, -70, -30, 10):
        leaf(s, x, y - r * 0.8, r * 0.45, a, (60, 150, 50))


def strawberry_cut(s, x, y, r):
    pygame.draw.polygon(s, (215, 25, 45), strawberry_shape(x, y, r))
    pygame.draw.polygon(s, (250, 140, 145), strawberry_shape(x, y + r * 0.05, r, 0.78))
    pygame.draw.polygon(s, (255, 225, 225), strawberry_shape(x, y + r * 0.1, r, 0.42))


def kiwi(s, x, y, r):
    shaded_ellipse(s, x, y, 2 * r, 1.7 * r, (120, 85, 45), (170, 135, 85))
    rng = random.Random(11)
    for _ in range(int(r * 2)):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.9)
        pygame.draw.circle(s, (95, 65, 35), (x + math.cos(a) * d * r, y + math.sin(a) * d * r * 0.85), 1)


def kiwi_cut(s, x, y, r):
    pygame.draw.ellipse(s, (120, 85, 45), ell(x, y, 2 * r, 1.7 * r))
    shaded_ellipse(s, x, y, 1.84 * r, 1.54 * r, (115, 185, 35), (185, 230, 100), steps=6)
    pygame.draw.ellipse(s, (240, 248, 215), ell(x, y, 0.55 * r, 0.42 * r))
    seeds_ring(s, x, y, r * 0.38, 22, r * 0.09, (25, 25, 15), rx=1.2)


def mango(s, x, y, r):
    shaded_ellipse(s, x, y, 1.7 * r, 2 * r, (245, 165, 35), (255, 228, 120))
    blush = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    pygame.draw.ellipse(blush, (225, 60, 50, 120), ell(x + r * 0.3, y - r * 0.35, r * 1.1, r * 1.1))
    clip_to_ellipse(blush, ell(x, y, 1.7 * r, 2 * r))
    s.blit(blush, (0, 0))
    pygame.draw.line(s, (100, 70, 30), (x, y - r * 0.95), (x - r * 0.05, y - r * 1.2), max(2, r // 9))
    leaf(s, x, y - r * 1.05, r * 0.5, -150, (60, 140, 50))


def mango_cut(s, x, y, r):
    pygame.draw.ellipse(s, (235, 140, 30), ell(x, y, 1.7 * r, 2 * r))
    pygame.draw.ellipse(s, (255, 195, 45), ell(x, y, 1.54 * r, 1.84 * r))
    pygame.draw.ellipse(s, (245, 235, 195), ell(x, y, 0.55 * r, 1.1 * r))


def bomb(s, x, y, r):
    pygame.draw.circle(s, (255, 60, 40), (x, y), r * 1.02, max(2, r // 10))  # red warning rim
    shaded_ellipse(s, x, y, 2 * r, 2 * r, (28, 28, 38), (125, 130, 155))
    cap = pygame.Rect(0, 0, r * 0.5, r * 0.32)
    cap.center = (x + r * 0.5, y - r * 0.82)
    pygame.draw.rect(s, (95, 95, 110), cap, border_radius=max(2, r // 10))
    fx, fy = bomb_fuse_tip(r)
    pts = [(x + r * 0.55 + (fx - r * 0.55) * t + math.sin(t * math.pi) * r * 0.18, y - r * 0.95 + (fy + r * 0.95) * t)
           for t in (i / 8 for i in range(9))]
    pygame.draw.lines(s, (170, 130, 80), False, pts, max(2, r // 9))
    # skull-ish face so kids know it's bad
    pygame.draw.circle(s, (235, 235, 240), (x - r * 0.22, y + r * 0.02), r * 0.17)
    pygame.draw.circle(s, (235, 235, 240), (x + r * 0.22, y + r * 0.02), r * 0.17)
    pygame.draw.circle(s, (20, 20, 25), (x - r * 0.22, y + r * 0.04), r * 0.08)
    pygame.draw.circle(s, (20, 20, 25), (x + r * 0.22, y + r * 0.04), r * 0.08)


def bomb_fuse_tip(r):
    """Fuse tip relative to the bomb centre, unrotated."""
    return r * 0.85, -r * 1.3


@dataclass(frozen=True)
class FruitType:
    name: str
    size: float     # radius relative to [game] fruit_radius
    points: int
    weight: float   # how often it appears
    juice: tuple
    whole: Callable
    cut: Callable


TYPES = [
    FruitType("apple", 0.9, 1, 1.2, (250, 240, 190), apple, apple_cut),
    FruitType("orange", 0.95, 1, 1.2, (255, 160, 30), orange, orange_cut),
    FruitType("banana", 1.0, 1, 1.0, (250, 235, 160), banana, banana_cut),
    FruitType("lemon", 0.85, 1, 0.8, (250, 240, 90), lemon, lemon_cut),
    FruitType("mango", 1.0, 1, 0.9, (255, 180, 30), mango, mango_cut),
    FruitType("kiwi", 0.8, 2, 0.8, (140, 205, 55), kiwi, kiwi_cut),
    FruitType("strawberry", 0.75, 2, 0.8, (235, 35, 55), strawberry, strawberry_cut),
    FruitType("coconut", 1.0, 2, 0.6, (245, 245, 240), coconut, coconut_cut),
    FruitType("pineapple", 1.15, 3, 0.5, (255, 220, 80), pineapple, pineapple_cut),
    FruitType("watermelon", 1.3, 3, 0.5, (235, 40, 60), watermelon, watermelon_cut),
]


class Art:
    """Renders fruit/bomb surfaces once per size and caches them."""

    def __init__(self):
        self._cache = {}

    def get(self, kind, r_px, part):
        """part: "whole" | "cut" (left half of the cut face) | "bomb"."""
        key = (kind.name if kind else "bomb", r_px, part)
        surf = self._cache.get(key)
        if surf is None:
            size = int(r_px * 2.9) + 4
            surf = pygame.Surface((size, size), pygame.SRCALPHA)
            c = size / 2
            if part == "bomb":
                bomb(surf, c, c, r_px)
            elif part == "whole":
                kind.whole(surf, c, c, r_px)
            else:
                kind.cut(surf, c, c, r_px)
                surf.fill((0, 0, 0, 0), pygame.Rect(int(c), 0, size, size))
            self._cache[key] = surf
        return surf
