"""Juice, splats, slash flashes, score popups, explosions and screen shake.

Positions are in world units (screen-heights); drawing takes to_px(x, y) and the
pixels-per-unit scale, like the rest of the game.
"""

import math
import random

import pygame


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "size", "color", "life", "age", "grav", "fade_to")

    def __init__(self, x, y, vx, vy, size, color, life, grav=1.0, fade_to=None):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.size, self.color, self.life, self.age = size, color, life, 0.0
        self.grav, self.fade_to = grav, fade_to


class Effects:
    def __init__(self):
        self.particles = []
        self.splats = []   # [x, y, surface, age, life]
        self.slashes = []  # [a, b, age]
        self.popups = []   # [x, y, text, color, size, age, life]
        self.rings = []    # [x, y, age, delay, color]
        self.shake = 0.0
        self.flash = 0.0
        self._splat_scale = None

    def clear(self):
        self.__init__()

    # ---- spawners ----

    def juice(self, x, y, color, dx, dy, n=18):
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(0.15, 0.9)
            self.particles.append(Particle(
                x, y, math.cos(a) * sp + dx * 0.4, math.sin(a) * sp + dy * 0.4 - 0.2,
                random.uniform(0.008, 0.02), color, random.uniform(0.35, 0.7)))

    def splat(self, x, y, color, r, scale):
        """A juice stain on the 'screen glass' that slowly fades."""
        r_px = max(6, int(r * scale * 1.2))
        size = r_px * 3
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size / 2
        for _ in range(9):
            a, d = random.uniform(0, 2 * math.pi), random.uniform(0, r_px * 0.8)
            pygame.draw.circle(surf, (*color, 150), (c + math.cos(a) * d, c + math.sin(a) * d),
                               random.uniform(0.25, 0.55) * r_px)
        for _ in range(6):  # drips
            a = random.uniform(0, 2 * math.pi)
            pygame.draw.circle(surf, (*color, 150), (c + math.cos(a) * r_px * 1.2, c + math.sin(a) * r_px * 1.2),
                               random.uniform(0.06, 0.14) * r_px)
        self.splats.append([x, y, surf, 0.0, 1.6])
        self.splats = self.splats[-12:]

    def slash(self, a, b):
        self.slashes.append([a, b, 0.0])

    def popup(self, x, y, text, color=(255, 255, 140), size="mid", life=0.8):
        self.popups.append([x, y, text, color, size, 0.0, life])

    def explosion(self, x, y):
        self.flash = 1.0
        self.shake = 0.05
        for delay in (0.0, 0.08, 0.18):
            self.rings.append([x, y, 0.0, delay, (255, 230, 150)])
        for _ in range(70):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(0.3, 1.6)
            fire = random.random() < 0.75
            self.particles.append(Particle(
                x, y, math.cos(a) * sp * (1 if fire else 0.4), math.sin(a) * sp * (1 if fire else 0.4),
                random.uniform(0.012, 0.035) if fire else random.uniform(0.012, 0.025),
                random.choice([(255, 230, 90), (255, 150, 40), (255, 80, 30)]) if fire else (60, 60, 65),
                random.uniform(0.4, 1.0) if fire else random.uniform(0.6, 1.1),
                grav=0.2 if fire else -0.15))

    def confetti(self, x, y, n=10):
        """Paper bits that flutter down slowly (a win)."""
        for _ in range(n):
            self.particles.append(Particle(
                x + random.uniform(-0.05, 0.05), y, random.uniform(-0.25, 0.25), random.uniform(0.0, 0.3),
                random.uniform(0.006, 0.012),
                random.choice([(255, 215, 60), (240, 70, 80), (80, 170, 255), (110, 230, 120), (255, 255, 255)]),
                random.uniform(2.0, 3.0), grav=0.12))

    def sparks(self, x, y):
        for _ in range(2):
            a = random.uniform(0, 2 * math.pi)
            sp = random.uniform(0.1, 0.4)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp - 0.2,
                                           random.uniform(0.004, 0.009),
                                           random.choice([(255, 240, 150), (255, 170, 50)]),
                                           random.uniform(0.15, 0.3), grav=0.3))

    # ---- update / draw ----

    def step(self, dt, gravity):
        for p in self.particles:
            p.vy += gravity * p.grav * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.age += dt
        self.particles = [p for p in self.particles if p.age < p.life]
        for lst in (self.splats, self.slashes, self.rings):
            for item in lst:
                item[3 if lst is self.splats else 2] += dt
        self.splats = [s for s in self.splats if s[3] < s[4]]
        self.slashes = [s for s in self.slashes if s[2] < 0.15]
        self.rings = [r for r in self.rings if r[2] < r[3] + 0.5]
        for p in self.popups:
            p[5] += dt
        self.popups = [p for p in self.popups if p[5] < p[6]]
        self.shake *= math.exp(-dt * 6)
        self.flash = max(0.0, self.flash - dt * 1.5)

    def shake_offset(self):
        if self.shake < 0.002:
            return 0.0, 0.0
        return random.uniform(-self.shake, self.shake), random.uniform(-self.shake, self.shake)

    def draw_back(self, screen, to_px):
        """Splats sit behind the fruit."""
        for x, y, surf, age, life in self.splats:
            surf.set_alpha(int(255 * (1 - age / life) ** 0.7))
            screen.blit(surf, surf.get_rect(center=to_px(x, y)))

    def draw_front(self, screen, to_px, scale, font):
        for p in self.particles:
            k = p.age / p.life
            size = p.size * scale * (1 - 0.6 * k) if p.grav >= 0 else p.size * scale * (1 + k)
            pygame.draw.circle(screen, p.color, to_px(p.x, p.y), max(1, int(size)))
        for x, y, age, delay, color in self.rings:
            k = (age - delay) / 0.5
            if k > 0:
                pygame.draw.circle(screen, color, to_px(x, y), int(scale * (0.05 + 0.5 * k)),
                                   max(1, int(scale * 0.03 * (1 - k))))
        for a, b, age in self.slashes:
            k = 1 - age / 0.15
            pygame.draw.line(screen, (255, 255, 255), to_px(*a), to_px(*b), max(1, int(scale * 0.012 * k)))
        for x, y, text, color, size, age, life in self.popups:
            k = age / life
            grow = min(1.0, age / 0.12)  # quick pop-in
            f = font(size, grow)
            surf = f.render(text, True, color)
            shadow = f.render(text, True, (0, 0, 0))
            alpha = int(255 * min(1.0, (1 - k) * 2.5))
            surf.set_alpha(alpha)
            shadow.set_alpha(alpha)
            cx, cy = to_px(x, y - 0.12 * k)
            screen.blit(shadow, shadow.get_rect(center=(cx + 3, cy + 3)))
            screen.blit(surf, surf.get_rect(center=(cx, cy)))
