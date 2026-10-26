"""Drawing and sound for the boxing game (rules in boxing.py): first person, full screen, in an arena.

Its own look, not Fruit Slice's frame: the whole screen is a live arena (a crowd that bobs and gets
louder when punches land, camera flashes, sweeping spotlights), fighting-game health bars across the
top, the boxer in the ring, your gloves in the foreground and your camera picture small in a corner.
The boxer is a sprite animation rendered by tools/blender/render_boxer.py (assets/boxers/<sprite>/);
boxers not rendered yet borrow another's.

World units are the lobby's (x 0..aspect, y 0..1). They're stretched to fill the screen, so the
picker boxes the hands hover over line up with what's drawn.
"""

import functools
import math
import random

import numpy as np
import pygame

import player as pl
import sprites
import theme

GLOVE_BLUE = (40, 110, 230)
WARN = (255, 200, 60)
GOLD = (255, 205, 70)
FEET = 0.9           # boxer's feet, as a fraction of a sprite frame's height (render_boxer's framing)
FLOOR = 0.93         # where the boxer stands, as a fraction of the screen height
LEVELS = ("EASY", "MEDIUM", "HARD")


def boxer_sprites(spec):
    """Sprite frames for this boxer; one that isn't rendered yet borrows the first rendered boxer's."""
    frames = sprites.load(spec["sprite"])
    if frames is None:
        for meta in sorted(sprites.ASSETS.glob("*/meta.json")):
            frames = sprites.load(meta.parent.name)
            if frames is not None:
                break
    return frames


# ---------------------------------------------------------------- sound

@functools.cache
def make_sounds():
    """Synthesised arena sounds: crowd murmur (looped), cheers, ooh/aww, punches, bells.
    Empty if audio is unavailable (the game then runs silent)."""
    try:
        sr, _, channels = pygame.mixer.get_init()
    except (TypeError, pygame.error):
        return {}
    pygame.mixer.set_num_channels(16)  # cheers, bells and punches overlap
    rng = np.random.default_rng(7)

    def secs(d):
        return np.arange(int(sr * d)) / sr

    def noise(n):
        return rng.uniform(-1, 1, n)

    def lowpass(x, k):
        return np.convolve(x, np.ones(k) / k, "same")

    def band(n, lo_k, hi_k):  # hi_k > lo_k: crude band-pass from two moving averages
        x = noise(n)
        return lowpass(x, lo_k) - lowpass(x, hi_k)

    def env(n, attack, release):
        t = np.arange(n) / sr
        return np.minimum(1, t / max(attack, 1e-3)) * np.minimum(1, (t[-1] - t) / max(release, 1e-3))

    def norm(x, peak=1.0):
        m = np.max(np.abs(x)) or 1.0
        return x / m * peak

    def voices(d, count, f_lo, f_hi, glide, start_spread, dur_range, vowel=(1.0, 0.45, 0.2)):
        """Many people shouting: harmonic tones that glide in pitch, wobble, swell and fade."""
        out = np.zeros(int(sr * d))
        for _ in range(count):
            t0 = rng.uniform(0, start_spread)
            dur = min(rng.uniform(*dur_range), d - t0)
            n = int(sr * dur)
            if n < sr // 20:
                continue
            t = np.arange(n) / sr
            f0 = rng.uniform(f_lo, f_hi)
            # pitch: rise a little, then glide by `glide` (negative = falls, like "ooh" / "aww")
            curve = f0 * (1 + 0.08 * np.sin(np.pi * np.minimum(1, t / (dur * 0.3)))
                          + glide * np.clip((t - dur * 0.3) / (dur * 0.7), 0, 1))
            curve *= 1 + 0.015 * np.sin(2 * np.pi * rng.uniform(4, 7) * t)
            phase = 2 * np.pi * np.cumsum(curve) / sr
            wave = sum(a * np.sin((k + 1) * phase) for k, a in enumerate(vowel))
            i0 = int(sr * t0)
            out[i0:i0 + n] += wave * env(n, dur * 0.25, dur * 0.5) * rng.uniform(0.5, 1.0)
        return out

    def applause(d, rate):
        n = int(sr * d)
        clicks = (rng.random(n) < rate / sr).astype(float) * rng.uniform(0.3, 1.0, n)
        kernel = noise(int(sr * 0.012)) * np.exp(-np.arange(int(sr * 0.012)) / (sr * 0.003))
        return np.convolve(clicks, kernel, "same")

    def snd(wave, vol=0.6):
        a = (np.clip(wave, -1, 1) * 32767 * vol).astype(np.int16)
        if channels == 2:
            a = np.column_stack([a, a])
        return pygame.sndarray.make_sound(np.ascontiguousarray(a))

    # crowd murmur: band noise with a slow swell, loop-crossfaded so it repeats without a seam
    d, xf = 6.0, 1.0
    n, nx = int(sr * d), int(sr * xf)
    t = np.arange(n + nx) / sr
    swell = 0.75 + 0.15 * np.sin(2 * np.pi * 0.23 * t) + 0.1 * np.sin(2 * np.pi * 0.61 * t + 1)
    bed = norm(band(n + nx, 4, 40)) * swell + 0.35 * norm(voices(d + xf, 40, 140, 260, 0.0, d + xf, (0.3, 0.8)))
    fade = np.linspace(0, 1, nx)
    loop = bed[:n].copy()
    loop[:nx] = bed[:nx] * fade + bed[n:n + nx] * (1 - fade)

    def cheer(d, count, rate):
        n = int(sr * d)
        roar = norm(band(n, 3, 30)) * env(n, 0.25, d * 0.6)
        yell = norm(voices(d, count, 330, 720, 0.25, d * 0.35, (0.6, 1.6)))
        whistle = norm(voices(d, 4, 1700, 2500, 0.3, d * 0.5, (0.3, 0.7), vowel=(1.0,)))
        return norm(roar * 0.6 + yell * 0.8 + whistle * 0.25 + 0.5 * norm(applause(d, rate)) * env(n, 0.1, d * 0.5))

    def punch(freq, crack):
        t = secs(0.18)
        body = (lowpass(noise(t.size), 20) * 3 + np.sin(2 * np.pi * freq * t)) * np.exp(-t * 26)
        slap = noise(t.size) * np.exp(-t * 180) * crack
        return norm(body + slap)

    tb = secs(0.45)
    ding = (np.sin(2 * np.pi * 880 * tb) + 0.5 * np.sin(2 * np.pi * 2210 * tb)) * np.exp(-tb * 7)
    tk = secs(0.6)
    ko = norm((lowpass(noise(tk.size), 40) * 4 + np.sin(2 * np.pi * 55 * tk)) * np.exp(-tk * 7)
              + noise(tk.size) * np.exp(-tk * 120) * 0.8)
    tw = secs(0.32)
    warn = np.concatenate([np.sin(2 * np.pi * f * tw[:tw.size // 2]) * np.exp(-tw[:tw.size // 2] * 10)
                           for f in (740, 990)])
    oo = voices(1.1, 30, 170, 300, -0.18, 0.15, (0.6, 0.95), vowel=(1.0, 0.25))
    aw = voices(1.8, 30, 260, 420, -0.35, 0.25, (1.0, 1.5), vowel=(1.0, 0.5, 0.3))
    return {
        "crowd_loop": snd(norm(loop), 1.0),            # volume is set by the renderer
        "crowd_cheer": snd(cheer(2.2, 30, 250), 0.55),
        "crowd_roar": snd(cheer(4.5, 60, 600), 0.8),
        "crowd_ooh": snd(norm(oo + 0.3 * norm(band(oo.size, 4, 40)) * env(oo.size, 0.2, 0.6)), 0.5),
        "crowd_aww": snd(norm(aw + 0.3 * norm(band(aw.size, 4, 40)) * env(aw.size, 0.3, 1.0)), 0.55),
        "punch1": snd(punch(85, 0.5), 0.9),
        "punch2": snd(punch(100, 0.8), 0.9),
        "punch3": snd(punch(72, 0.3), 0.9),
        "ko_punch": snd(ko, 1.0),
        "bell_end": snd(np.concatenate([ding, ding, ding]), 0.7),
        "warn": snd(warn, 0.45),
    }


# ---------------------------------------------------------------- the arena

class Arena:
    """Full-screen arena. Everything still is drawn once per screen size; each frame only moves
    pre-drawn pieces: crowd rows bob, flashes pop, two spotlights sweep."""

    ROWS = 3

    def __init__(self, size):
        self.size = w, h = size
        rng = random.Random(11)
        self.back = self._backdrop(w, h)
        self.ring = self._ring(w, h)
        self.rows = []  # (chunks, y, amplitude): each row is cut into chunks that bob separately
        for r in range(self.ROWS):
            k = r / (self.ROWS - 1)
            row_h = int(h * (0.07 + 0.05 * k))
            surf = pygame.Surface((w, row_h * 2), pygame.SRCALPHA)
            head_r = row_h * 0.28
            x = rng.uniform(-head_r, head_r)
            while x < w + head_r:
                shade = int(28 + 30 * k + rng.uniform(-8, 12))
                shirt = rng.choice([(70, 40, 40), (40, 50, 80), (50, 60, 45), (75, 65, 40), (60, 40, 70)])
                shirt = tuple(int(c * (0.45 + 0.35 * k)) for c in shirt)
                cy = row_h * 0.75 + rng.uniform(-row_h * 0.12, row_h * 0.12)
                body = pygame.Rect(0, 0, head_r * 2.6, row_h * 1.3)
                body.midtop = (x, cy + head_r * 0.7)
                pygame.draw.ellipse(surf, (*shirt, 255), body)
                pygame.draw.circle(surf, (shade, shade - 6, shade - 2, 255), (x, cy), head_r)
                if rng.random() < 0.18:  # an arm up
                    pygame.draw.line(surf, (*shirt, 255), (x + head_r, cy + head_r),
                                     (x + head_r * 1.6, cy - head_r * 1.8), max(2, int(head_r * 0.6)))
                x += head_r * rng.uniform(2.0, 2.7)
            chunks = []
            n = 6
            for i in range(n):
                part = pygame.Rect(i * w // n, 0, w // n + 1, row_h * 2)
                chunks.append((surf.subsurface(part).copy(), part.x, rng.uniform(0, 6.28), rng.uniform(5, 8)))
            self.rows.append((chunks, int(h * (0.25 + 0.09 * r)), h * (0.004 + 0.004 * k)))
        self.spot = self._spot(int(w * 0.34), int(h * 0.95))
        self.flash = self._flash(max(8, h // 22))
        self.flash_small = pygame.transform.smoothscale(self.flash, (self.flash.get_width() * 3 // 5,) * 2)
        self.shadow = pygame.Surface((int(h * 0.32), int(h * 0.05)), pygame.SRCALPHA)
        pygame.draw.ellipse(self.shadow, (0, 0, 20, 110), self.shadow.get_rect())
        self.flashes = []  # [x, y, age]
        self.rng = rng

    @staticmethod
    def _backdrop(w, h):
        surf = pygame.Surface((w, h))
        for y in range(h):
            k = y / h
            surf.fill((int(10 + 22 * k), int(8 + 12 * k), int(24 + 26 * k)), pygame.Rect(0, y, w, 1))
        # big screen over the ring: a dark board with a soft glow
        board = pygame.Rect(0, 0, w * 0.32, h * 0.1)
        board.midtop = (w / 2, h * 0.13)
        glow = pygame.Surface((board.w + 60, board.h + 60), pygame.SRCALPHA)
        pygame.draw.rect(glow, (90, 60, 200, 50), glow.get_rect(), border_radius=30)
        surf.blit(glow, glow.get_rect(center=board.center))
        pygame.draw.rect(surf, (14, 12, 30), board, border_radius=10)
        pygame.draw.rect(surf, (120, 90, 220), board, 2, border_radius=10)
        theme.text(surf, theme.font(board.h * 0.55), "MOTION BOXING", (190, 170, 255), outline=0,
                   center=board.center)
        return surf

    @staticmethod
    def _ring(w, h):
        """Ropes, posts and canvas: drawn over the crowd, under the boxer."""
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        top = int(h * 0.7)
        pts = [(w * 0.08, top), (w * 0.92, top), (w * 1.1, h), (-w * 0.1, h)]
        pygame.draw.polygon(surf, (40, 70, 150, 255), pts)
        logo = pygame.Rect(0, 0, w * 0.5, (h - top) * 0.55)
        logo.center = (w / 2, top + (h - top) * 0.55)
        pygame.draw.ellipse(surf, (55, 95, 185, 255), logo)
        pygame.draw.ellipse(surf, (120, 160, 230, 255), logo, 3)
        pygame.draw.line(surf, (235, 235, 245, 255), pts[0], pts[1], 3)
        posts = (int(w * 0.08), int(w * 0.92))
        for i, color in enumerate(((225, 45, 50), (240, 240, 240), (50, 90, 230))):
            y = int(h * (0.46 + 0.075 * i))
            pygame.draw.line(surf, (*color, 255), (posts[0], y), (posts[1], y), max(3, h // 110))
        for x in posts:
            pygame.draw.rect(surf, (210, 210, 220, 255), pygame.Rect(x - h // 70, int(h * 0.42), h // 35, top - int(h * 0.42)),
                             border_radius=4)
            pygame.draw.rect(surf, (200, 40, 40, 255), pygame.Rect(x - h // 55, int(h * 0.42), h // 27, h // 30),
                             border_radius=4)
        return surf

    @staticmethod
    def _spot(w, h):
        """A light cone, pre-multiplied on black for additive blending."""
        surf = pygame.Surface((w, h))
        for y in range(0, h, 2):
            k = y / h
            half = w * (0.06 + 0.44 * k)
            c = int(38 * (1 - k * 0.6))
            pygame.draw.line(surf, (c, c, int(c * 0.85)), (w / 2 - half, y), (w / 2 + half, y), 2)
        return surf

    @staticmethod
    def _flash(r):
        surf = pygame.Surface((r * 4, r * 4))
        c = r * 2
        for k in range(r, 0, -1):
            v = int(255 * (1 - k / r) ** 1.5)
            pygame.draw.circle(surf, (v, v, v), (c, c), k)
        pygame.draw.line(surf, (150, 150, 150), (0, c), (r * 4, c), 1)
        pygame.draw.line(surf, (150, 150, 150), (c, 0), (c, r * 4), 1)
        return surf

    def draw(self, screen, t, dt, excitement):
        w, h = self.size
        screen.blit(self.back, (0, 0))
        for chunks, y, amp in self.rows:  # crowd: bob faster and higher when excited
            for surf, x, phase, speed in chunks:
                bob = abs(math.sin(t * speed * (0.5 + 0.7 * excitement) + phase)) * amp * (1 + 3 * excitement)
                screen.blit(surf, (x, y - bob))
        if self.rng.random() < dt * (1.5 + 10 * excitement):  # camera flashes in the crowd
            self.flashes.append([self.rng.uniform(0, w), self.rng.uniform(h * 0.2, h * 0.45), 0.0])
        for f in self.flashes:
            f[2] += dt
            k = 1 - f[2] / 0.15
            if k > 0:
                surf = self.flash if k > 0.5 else self.flash_small
                screen.blit(surf, surf.get_rect(center=(f[0], f[1])), special_flags=pygame.BLEND_ADD)
        self.flashes = [f for f in self.flashes if f[2] < 0.15]
        for i, side in enumerate((-1, 1)):  # two spotlights sweeping across the ring
            x = w * (0.5 + side * (0.18 + 0.14 * math.sin(t * 0.45 + i * 2.1)))
            screen.blit(self.spot, self.spot.get_rect(midtop=(x, -h * 0.02)), special_flags=pygame.BLEND_ADD)
        screen.blit(self.ring, (0, 0))


# ---------------------------------------------------------------- renderer

class BoxingRenderer:
    def __init__(self, base):
        self.base = base            # fruit_slice.Renderer: only its skeleton / debug switches are used
        self.arena = None
        self.pip = None
        self.health = [1.0, 1.0]    # shown health (you, boxer), moving toward the real value
        self.chip = [1.0, 1.0]      # the white "just lost" part, which drains more slowly
        self.excitement = 0.0
        self._seen = (0, 0)         # (landed, taken) last frame: a change excites the crowd
        self._t = None
        self.crowd = None           # the crowd murmur's channel while boxing is on

    # ---------------------------------------------------------------- audio

    def update_audio(self, g):
        loop = make_sounds().get("crowd_loop")
        if loop is None:
            return
        if self.crowd is None:
            self.crowd = loop.play(loops=-1, fade_ms=800)
        if self.crowd is not None:
            vol = g.b.get("crowd_volume", 0.35)
            self.crowd.set_volume(vol * (1.0 if g.state in ("fight", "result") else 0.55) * (0.8 + 0.6 * self.excitement))

    def stop_audio(self):
        if self.crowd is not None:
            self.crowd.fadeout(600)
            self.crowd = None

    # ---------------------------------------------------------------- frame

    def draw(self, screen, g, tracker, frame, fresh, rect, view, fps):
        """Draws the whole screen (rect, the shared play area, isn't used: boxing is full screen)."""
        W, H = screen.get_size()
        if self.arena is None or self.arena.size != (W, H):
            self.arena = Arena((W, H))
        dt = 0.0 if self._t is None else min(0.1, g.t - self._t)
        self._t = g.t
        self.track_mood(g, dt)
        self.update_audio(g)

        a = g.lobby.aspect
        kx = W / a
        sx, sy = g.fx.shake_offset()

        def to_px(x, y):  # world -> screen, stretched to fill it
            return int((x + sx) * kx), int((y + sy) * H)

        self.arena.draw(screen, g.t, dt, self.excitement)
        opp = g.opponent
        if opp is not None and g.state != "select":
            self.draw_boxer(screen, W // 2 + int(sx * kx), int((FLOOR + sy) * H), H, opp, g.t)
        g.fx.draw_back(screen, to_px)
        g.fx.draw_front(screen, to_px, H, lambda size, grow: theme.font(H / 12 * (0.5 + 0.5 * grow)))

        no_signal = not getattr(tracker, "signal", True)
        if g.state == "select":
            self.draw_select(screen, g, to_px, W, H)
        elif not no_signal:
            for i, hand in enumerate(g.me.hands):  # your gloves, in the foreground
                if hand.pos is None:
                    continue
                punched = g.t - g.punch_glow[i]
                grow = 1.0 + 0.45 * max(0.0, 1 - punched / 0.25)
                self.glove(screen, to_px(*hand.pos), H * 0.085 * grow, GLOVE_BLUE)
        if g.t < g.hurt_until:  # you got hit: red flash
            red = pygame.Surface((W, H))
            red.fill((255, 30, 30))
            red.set_alpha(int(130 * (g.hurt_until - g.t) / 0.35))
            screen.blit(red, (0, 0))
        if g.state != "select":
            self.draw_hud(screen, g, W, H)
        if g.state != "select":  # on the picker it would cover a fighter; the gloves show your hands
            self.draw_pip(screen, g, frame, fresh, view, W, H)
        self.draw_text(screen, g, tracker, no_signal, W, H, fps)

    def track_mood(self, g, dt):
        """Crowd excitement and the health bars' smooth movement."""
        seen = (g.landed, g.taken)
        if seen != self._seen:
            self.excitement = 1.0 if seen > self._seen else self.excitement
            self._seen = seen
        if g.state == "result" and g.won:
            self.excitement = 1.0
        self.excitement = max(0.15 if g.state == "fight" else 0.05, self.excitement - dt * 0.5)
        b = g.b
        fighting = g.state in ("fight", "result")
        target = [1 - g.taken / b["hits_to_lose"], 1 - g.landed / b["hits_to_win"]] if fighting else [1.0, 1.0]
        for i in (0, 1):
            self.health[i] += (target[i] - self.health[i]) * min(1.0, dt * 14)
            self.chip[i] = target[i] if target[i] > self.chip[i] else max(target[i], self.chip[i] - dt * 0.25)

    # ---------------------------------------------------------------- pieces

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

    def draw_boxer(self, surf, cx, floor_y, H, opp, t):
        """The boxer's sprite animation standing on floor_y, with a shadow on the canvas."""
        frames = boxer_sprites(opp.spec)
        if frames is None:
            return
        since = t - opp.t_state
        anim = {"idle": "idle", "guard": "block", "windup": "idle", "punch": "jab" if opp.side == "left" else "cross",
                "recover": "idle", "stunned": "hit_head", "ko": "knockout", "cheer": "victory"}[opp.state]
        if not frames.has(anim):
            anim = "idle"
        img = frames.frame(anim, since, H * 0.98, loop=opp.state in ("idle", "guard", "windup", "recover"))
        if img is None:
            return
        surf.blit(self.arena.shadow, self.arena.shadow.get_rect(center=(cx, floor_y)))
        r = img.get_rect(midtop=(cx, floor_y - img.get_height() * FEET))
        if opp.state == "windup":  # the warning: a pulsing glow behind the boxer
            pulse = 0.5 + 0.5 * math.sin(t * 18)
            glow = pygame.Rect(0, 0, r.w * 0.55, r.h * 0.75)
            glow.midbottom = (cx, floor_y)
            pygame.draw.ellipse(surf, (int(120 + 100 * pulse), int(80 + 60 * pulse), 10), glow)
        surf.blit(img, r)

    def draw_hud(self, screen, g, W, H):
        """Fighting-game health bars: you on the left, the boxer on the right, draining outward."""
        bar_w, bar_h, top = W * 0.39, max(14, int(H * 0.045)), int(H * 0.035)
        names = ("YOU", g.opponent.name if g.opponent else "")
        for i, side in enumerate((-1, 1)):
            outer = pygame.Rect(0, top, int(bar_w), bar_h)
            if side < 0:
                outer.left = int(W * 0.03)
            else:
                outer.right = int(W * 0.97)
            pygame.draw.rect(screen, (10, 8, 16), outer.inflate(8, 8), border_radius=6)
            pygame.draw.rect(screen, (120, 20, 25), outer)  # lost health shows red
            for frac, color in ((self.chip[i], (255, 245, 230)), (self.health[i], None)):
                part = outer.copy()
                part.w = int(outer.w * max(0.0, frac))
                if side > 0:
                    part.right = outer.right
                if color is None:  # health: green to yellow to red as it drops; flashes when low
                    h = self.health[i]
                    color = (int(255 * min(1, 2 - 2 * h)), int(255 * min(1, 2 * h)), 40)
                    if h < 0.25 and int(g.t * 6) % 2:
                        color = (255, 255, 255)
                    pygame.draw.rect(screen, color, part)
                    shine = part.copy()
                    shine.h = max(2, part.h // 3)
                    pygame.draw.rect(screen, tuple(min(255, c + 70) for c in color), shine)
                else:
                    pygame.draw.rect(screen, color, part)
            pygame.draw.rect(screen, GOLD, outer.inflate(8, 8), 3, border_radius=6)
            f = theme.font(H * 0.045)
            anchor = {"topleft": (outer.left, outer.bottom + 8)} if side < 0 else {"topright": (outer.right, outer.bottom + 8)}
            theme.text(screen, f, names[i], (130, 200, 255) if side < 0 else (255, 120, 110), outline=2, **anchor)
        badge = (W // 2, top + bar_h // 2)  # the VS / KO badge between the bars
        r = int(H * 0.055)
        ko = g.state == "result"
        pygame.draw.circle(screen, (150, 20, 20) if ko else (25, 20, 45), badge, r)
        pygame.draw.circle(screen, GOLD, badge, r, 3)
        theme.text(screen, theme.font(r * 0.95), "KO" if ko else "VS", GOLD, outline=2, center=badge)

    def draw_select(self, screen, g, to_px, W, H):
        """Choose your fighter: one card per boxer with its idle animation, plus GAMES / WI-FI."""
        zones = g.zones()
        for i, spec in enumerate(g.boxers):
            box = self.zone_rect(zones[f"boxer{i}"], to_px)
            frac = min(1.0, g.hover[f"boxer{i}"] / g.hover_needed(f"boxer{i}"))
            self.card(screen, box, frac)
            frames = boxer_sprites(spec)
            img = frames and frames.frame("idle", g.t + i * 0.37, box.h * 1.05)
            if img is not None:
                clip = screen.get_clip()
                screen.set_clip(box.inflate(-8, -8))
                screen.blit(img, img.get_rect(midtop=(box.centerx, box.bottom - box.h * 0.2 - img.get_height() * FEET)))
                screen.set_clip(clip)
            label = pygame.Rect(box.x, box.bottom - box.h * 0.22, box.w, box.h * 0.22)
            pygame.draw.rect(screen, (12, 10, 22), label.inflate(-8, -6), border_radius=10)
            theme.text(screen, theme.font(box.h * 0.085), spec["name"], GOLD, outline=2,
                       center=(box.centerx, label.y + label.h * 0.36))
            level = LEVELS[min(i, 2)]
            theme.text(screen, theme.font(box.h * 0.045, name="arial"), f"{level}   wins {g.wins(i)}", theme.CREAM,
                       outline=1, center=(box.centerx, label.y + label.h * 0.75))
        for zone, title in (("games", "GAMES"), ("settings", "WI-FI")):
            box = self.zone_rect(zones[zone], to_px)
            self.card(screen, box, min(1.0, g.hover[zone] / g.hover_needed(zone)))
            theme.text(screen, theme.font(box.h * 0.5), title, theme.CREAM, outline=2, center=box.center)
        for hand in g.lobby.hands:  # small gloves show where your hands point
            if hand.pos is not None:
                self.glove(screen, to_px(*hand.pos), H * 0.035, GLOVE_BLUE)

    @staticmethod
    def zone_rect(zone, to_px):
        x0, y0, x1, y1 = zone
        (px0, py0), (px1, py1) = to_px(x0, y0), to_px(x1, y1)
        return pygame.Rect(px0, py0, px1 - px0, py1 - py0)

    def card(self, screen, box, frac):
        """A dark glass panel; glows while a hand holds it and fills from the bottom."""
        outer = box.inflate(20, 20)
        panel = pygame.Surface(outer.size, pygame.SRCALPHA)
        inner = box.move(-outer.x, -outer.y)
        if frac > 0:
            pygame.draw.rect(panel, (255, 210, 90, 90), panel.get_rect(), border_radius=20)
        pygame.draw.rect(panel, (14, 10, 30, 200), inner, border_radius=14)
        fill = inner.copy()
        fill.h = int(inner.h * frac)
        fill.bottom = inner.bottom
        pygame.draw.rect(panel, (240, 190, 70, 110), fill, border_radius=14)
        screen.blit(panel, outer)
        pygame.draw.rect(screen, (255, 240, 200) if frac > 0 else (150, 110, 230), box, 4 if frac > 0 else 2,
                         border_radius=14)

    def draw_pip(self, screen, g, frame, fresh, view, W, H):
        """Your camera picture, small, bottom-right, with your skeleton."""
        if frame is None:
            return
        pw = int(W * 0.17)
        ph = int(pw / view.aspect)
        if fresh or self.pip is None or self.pip.get_size() != (pw, ph):
            import cv2
            rgb = cv2.cvtColor(cv2.resize(view.crop(frame), (pw, ph)), cv2.COLOR_BGR2RGB)
            self.pip = pygame.image.frombuffer(rgb.tobytes(), (pw, ph), "RGB")
        box = self.pip.get_rect(bottomright=(W - 14, H - 14))
        screen.blit(self.pip, box)
        kp = g.me.kp
        if kp is not None:
            for i, j in pl.BONES:
                if kp[i][2] > 0.4 and kp[j][2] > 0.4:
                    pts = [view.world(kp[k][0], kp[k][1]) for k in (i, j)]
                    pts = [(box.x + px / view.aspect * pw, box.y + py * ph) for px, py in pts]
                    pygame.draw.line(screen, (120, 255, 170), *pts, 2)
        pygame.draw.rect(screen, GOLD, box, 2, border_radius=6)

    def hold_ring(self, screen, center, radius, frac):
        box = pygame.Rect(0, 0, 2 * radius, 2 * radius)
        box.center = center
        pygame.draw.circle(screen, (0, 0, 0), center, radius, 8)
        if frac > 0:
            pygame.draw.arc(screen, GOLD, box, math.pi / 2, math.pi / 2 + min(1.0, frac) * 2 * math.pi, 8)

    def draw_text(self, screen, g, tracker, no_signal, W, H, fps):
        st = g.state

        def say(msg, y, size, color=theme.CREAM, outline=3):
            theme.text(screen, theme.font(H * size), msg, color, outline=outline, center=(W // 2, int(H * y)))

        if no_signal:
            camera = getattr(tracker, "camera", None)
            status = camera.status if camera is not None and camera.connected is False else "no picture yet"
            say("Connecting to the camera...", 0.45, 0.06, GOLD)
            say(f"({status})", 0.55, 0.035, (200, 190, 170), 2)
        elif st == "select":
            say("CHOOSE YOUR FIGHTER", 0.135, 0.07, GOLD, 4)
            holding = any(v > 0 for v in g.hover.values())
            say("Keep holding..." if holding else "Hold a hand on a fighter", 0.77, 0.045,
                GOLD if holding else theme.CREAM)
            say("Remote:  Left / OK / Right = fighter  |  Up = games  |  Down = Wi-Fi", 0.84, 0.028, (200, 190, 170), 2)
        elif st == "ready":
            say(g.opponent.name, 0.3, 0.1, GOLD, 4)
            say(LEVELS[min(g.focus, 2)], 0.39, 0.04, theme.CREAM, 2)
            tips = ("PUNCH fast at the boxer", "GLOWING = cover your face", "or LEAN / DUCK away")
            f = theme.font(H * 0.034)
            for i, tip in enumerate(tips):
                pill = pygame.Rect(0, 0, f.size(tip)[0] + H * 0.04, f.get_height() * 1.5)
                pill.center = (int(W * (0.15 + 0.27 * i)), int(H * 0.9))  # clear of the camera picture
                pygame.draw.rect(screen, (14, 10, 30), pill, border_radius=pill.h // 2)
                pygame.draw.rect(screen, (150, 110, 230), pill, 2, border_radius=pill.h // 2)
                theme.text(screen, f, tip, theme.CREAM, outline=1, center=pill.center)
            say("Raise both hands to start!", 0.47, 0.055, GOLD)
            for hand in g.me.hands:
                if hand.pos is not None:
                    px = (int(hand.pos[0] / g.lobby.aspect * W), int(hand.pos[1] * H))
                    self.hold_ring(screen, px, int(H * 0.06), g.hold / g.cfg["game"]["hands_up_seconds"])
        elif st == "countdown":
            left = 3 - (g.t - g.state_t)
            say("ROUND 1", 0.3, 0.07, theme.CREAM)
            k = left - math.floor(left)
            theme.text(screen, theme.font(H * (0.2 + 0.12 * k)), str(max(1, math.ceil(left))), GOLD, outline=5,
                       center=(W // 2, H // 2))
        elif st == "fight":
            if g.paused:
                say("Paused - come back in front of the camera", 0.5, 0.05, GOLD)
            elif g.opponent.state == "windup":
                say("!", 0.22, 0.12, WARN, 4)
                say("Block or dodge!", 0.86, 0.05, WARN)
            if g.t < g.message_until:
                say(g.message, 0.45, 0.1, g.message_color, 4)
        elif st == "result":
            since = g.t - g.state_t
            pop = 1 + 0.25 * max(0.0, 1 - since / 0.3)  # slams in, then settles
            if g.won:
                size = round(0.24 * pop * (1 + 0.03 * math.sin(g.t * 6)), 2)
                say("K.O.!", 0.33, size, GOLD, 6)
                say("YOU WIN!", 0.5, 0.08, (120, 255, 140), 4)
            else:
                say("K.O.", 0.33, round(0.2 * pop, 2), (255, 90, 80), 6)
                say(f"{g.opponent.name} wins this time", 0.5, 0.055, theme.CREAM)
            if since >= g.b["result_seconds"]:
                say("Raise both hands to continue", 0.86, 0.045)
                for hand in g.me.hands:
                    if hand.pos is not None:
                        px = (int(hand.pos[0] / g.lobby.aspect * W), int(hand.pos[1] * H))
                        self.hold_ring(screen, px, int(H * 0.06), g.hold / g.cfg["game"]["hands_up_seconds"])
        if self.base.show_debug:
            f = theme.font(max(11, H // 45), bold=False, name="consolas")
            opp = g.opponent.state if g.opponent else "-"
            theme.text(screen, f, f"fps {fps:4.1f}  pose {tracker.pose_ms:4.1f} ms  boxer {opp}  "
                                  f"landed {g.landed}  taken {g.taken}", (200, 190, 170), outline=1,
                       bottomleft=(14, H - 10))
