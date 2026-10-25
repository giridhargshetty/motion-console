"""Dojo theme: wooden wall, bamboo frame around the camera picture, scroll side panels.

build_backdrop() paints everything that doesn't move once per window size; the game
draws the camera picture into the frame and the live text onto the panels.
"""

import functools

import numpy as np
import pygame

GOLD = (240, 195, 80)
CREAM = (255, 240, 205)
INK = (25, 14, 8)


# Windows font first, then what Ubuntu has (fonts-dejavu-core, installed by deploy/linux/setup.sh).
FALLBACKS = {
    "impact": "impact,dejavusanscondensed,dejavusans",
    "arial": "arial,dejavusans",
    "consolas": "consolas,dejavusansmono",
}


def font(size, bold=True, name="impact"):
    # Impact is already heavy; the Linux stand-in needs bold to look similar.
    bold = bold and (name != "impact" or "impact" not in pygame.font.get_fonts())
    return _font(max(10, int(size)), bold, FALLBACKS.get(name, name))


@functools.cache
def _font(size, bold, names):
    return pygame.font.SysFont(names, size, bold=bold)


def text(screen, f, msg, color=CREAM, outline=2, **anchor):
    """Text with a dark outline so it reads over the camera picture. anchor: center=, topleft=, ..."""
    front = f.render(msg, True, color)
    rect = front.get_rect(**{k: (int(v[0]), int(v[1])) for k, v in anchor.items()})
    if outline:
        back = f.render(msg, True, INK)
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (0, 2)):
            screen.blit(back, rect.move(dx * outline, dy * outline))
    screen.blit(front, rect)
    return rect


def wrap(f, msg, width):
    lines, line = [], ""
    for word in msg.split():
        trial = f"{line} {word}".strip()
        if f.size(trial)[0] <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def wood(size, seed=3):
    w, h = size
    rng = np.random.default_rng(seed)
    xs = np.arange(w)[:, None]
    ys = np.arange(h)[None, :]
    plank_w = max(40, w // 14)
    plank = xs // plank_w
    n = w // plank_w + 2
    tint = rng.uniform(0.82, 1.1, n)[plank]
    phase = rng.uniform(0, 6.3, n)[plank]
    grain = 0.88 + 0.12 * np.sin(ys * 0.035 + phase + 2.2 * np.sin(ys * 0.006 + xs * 0.045))
    shade = np.where(xs % plank_w < 3, 0.45, tint * grain)
    vignette = 1 - 0.45 * (((xs / w - 0.5) * 2) ** 2 + ((ys / h - 0.5) * 2) ** 2) / 2
    img = (shade * vignette)[..., None] * np.array([92, 56, 30])
    return pygame.surfarray.make_surface(img.clip(0, 255).astype(np.uint8))


def bamboo(surf, rect, horizontal):
    """One bamboo pole filling rect, with knuckle joints."""
    thick = rect.h if horizontal else rect.w
    length = rect.w if horizontal else rect.h
    for i in range(thick):
        k = abs(i / max(1, thick - 1) - 0.4) / 0.6  # light stripe a bit off-centre
        color = (int(215 - 120 * k), int(200 - 105 * k), int(95 - 55 * k))
        if horizontal:
            pygame.draw.line(surf, color, (rect.x, rect.y + i), (rect.right - 1, rect.y + i))
        else:
            pygame.draw.line(surf, color, (rect.x + i, rect.y), (rect.x + i, rect.bottom - 1))
    step = thick * 3.5
    pos = step * 0.6
    while pos < length - thick * 0.5:
        for off, color, width in ((0, (85, 70, 25), 3), (3, (235, 225, 150), 1)):
            if horizontal:
                x = rect.x + pos + off
                pygame.draw.line(surf, color, (x, rect.y + 1), (x, rect.bottom - 2), width)
            else:
                y = rect.y + pos + off
                pygame.draw.line(surf, color, (rect.x + 1, y), (rect.right - 2, y), width)
        pos += step


def scroll_panel(surf, rect):
    shadow = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, 120), shadow.get_rect(), border_radius=18)
    surf.blit(shadow, rect.move(6, 8))
    body = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(body, (30, 16, 10, 215), body.get_rect(), border_radius=18)
    surf.blit(body, rect)
    pygame.draw.rect(surf, GOLD, rect, 3, border_radius=18)
    pygame.draw.rect(surf, (150, 105, 40), rect.inflate(-14, -14), 1, border_radius=12)
    for y in (rect.y, rect.bottom):  # scroll rods
        rod = pygame.Rect(rect.x - 8, y - 7, rect.w + 16, 14)
        pygame.draw.rect(surf, (120, 40, 25), rod, border_radius=7)
        pygame.draw.rect(surf, GOLD, rod, 2, border_radius=7)


def frame_thickness(screen_h):
    return max(12, screen_h // 30)


def panels(screen_size, cam_rect):
    """Left and right panel rects beside the camera picture, or None where there's no room."""
    sw, sh = screen_size
    t = frame_thickness(sh)
    pad = max(16, sw // 60)
    out = []
    for x0, x1 in ((pad, cam_rect.x - t - pad), (cam_rect.right + t + pad, sw - pad)):
        # Minimum width relative to the screen, so the layout is the same on a 720p or 1080p TV.
        out.append(pygame.Rect(x0, cam_rect.y + 12, x1 - x0, cam_rect.h - 24) if x1 - x0 >= sw * 0.1 else None)
    return out


def build_backdrop(screen_size, cam_rect):
    surf = wood(screen_size)
    t = frame_thickness(screen_size[1])
    outer = cam_rect.inflate(2 * t, 2 * t)
    shadow = pygame.Surface((outer.w + 30, outer.h + 30), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, 140), shadow.get_rect(), border_radius=20)
    surf.blit(shadow, (outer.x - 6, outer.y - 2))
    bamboo(surf, pygame.Rect(outer.x, outer.y, outer.w, t), True)
    bamboo(surf, pygame.Rect(outer.x, cam_rect.bottom, outer.w, t), True)
    bamboo(surf, pygame.Rect(outer.x, outer.y, t, outer.h), False)
    bamboo(surf, pygame.Rect(cam_rect.right, outer.y, t, outer.h), False)
    for cx, cy in ((outer.x, outer.y), (outer.right - t, outer.y),
                   (outer.x, outer.bottom - t), (outer.right - t, outer.bottom - t)):
        knot = pygame.Rect(cx - 3, cy - 3, t + 6, t + 6)  # rope lashing at the corners
        pygame.draw.rect(surf, (150, 105, 55), knot, border_radius=4)
        for k in range(1, 4):
            pygame.draw.line(surf, (95, 60, 25), (knot.x + k * knot.w // 4, knot.y),
                             (knot.x, knot.y + k * knot.h // 4), 2)
            pygame.draw.line(surf, (95, 60, 25), (knot.right, knot.y + k * knot.h // 4),
                             (knot.x + k * knot.w // 4, knot.bottom), 2)
    pygame.draw.rect(surf, INK, cam_rect.inflate(4, 4), 2)
    for p in panels(screen_size, cam_rect):
        if p:
            scroll_panel(surf, p)
    return surf
