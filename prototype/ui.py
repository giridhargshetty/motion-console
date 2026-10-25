"""Buttons for a box with no keyboard or mouse. Three ways to press one:
  - hand: hover over it for `dwell` seconds (the button fills up while you wait)
  - mouse: click it
  - arrow keys + Enter: works with USB air-mouse / TV-style remotes (their D-pad sends arrow keys)
"""

import pygame

import theme

ARROWS = {pygame.K_LEFT: (-1, 0), pygame.K_RIGHT: (1, 0), pygame.K_UP: (0, -1), pygame.K_DOWN: (0, 1)}
ENTER_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER)


class Button:
    def __init__(self, rect, label, action, sub="", primary=False):
        self.rect = pygame.Rect(rect)
        self.label, self.action, self.sub, self.primary = label, action, sub, primary


class Pointer:
    def __init__(self, dwell=1.0):
        self.dwell = dwell
        self.progress = {}      # action -> seconds a hand has hovered on it
        self.lockout = set()    # pressed by a hand: the hand must leave before it can press again
        self.focus = 0          # arrow-key focus (index into the button list)
        self.keys_used = False  # show the focus ring only once someone uses the arrows
        self.mouse_pos = None
        self.interacted = False

    def reset(self):
        self.progress.clear()
        self.lockout.clear()
        self.focus = 0

    def _move(self, buttons, dx, dy):
        here = buttons[self.focus].rect.center
        best, best_score = self.focus, None
        for i, b in enumerate(buttons):
            vx, vy = b.rect.centerx - here[0], b.rect.centery - here[1]
            along = vx * dx + vy * dy
            if i == self.focus or along <= 0:
                continue
            score = along + 2.5 * abs(vx * dy - vy * dx)  # prefer straight ahead over diagonal
            if best_score is None or score < best_score:
                best, best_score = i, score
        return best

    def update(self, buttons, hands_px, events, dt, enter_presses=True):
        """Returns the action of the button pressed this frame, or None.
        enter_presses=False lets the caller use Enter itself (e.g. typing on a real keyboard)."""
        if not buttons:
            return None
        self.focus = min(self.focus, len(buttons) - 1)
        for e in events:
            if e.type == pygame.MOUSEMOTION:
                self.mouse_pos = e.pos
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                self.mouse_pos, self.interacted = e.pos, True
                for b in buttons:
                    if b.rect.collidepoint(e.pos):
                        return b.action
            elif e.type == pygame.KEYDOWN:
                if e.key in ARROWS:
                    self.interacted = True
                    if self.keys_used:
                        self.focus = self._move(buttons, *ARROWS[e.key])
                    self.keys_used = True
                elif e.key in ENTER_KEYS and enter_presses:
                    self.interacted = self.keys_used = True
                    return buttons[self.focus].action

        hovered = {b.action for b in buttons for p in hands_px if b.rect.collidepoint(p)}
        self.lockout &= hovered
        for b in buttons:
            a = b.action
            if a in hovered and a not in self.lockout:
                self.progress[a] = self.progress.get(a, 0.0) + dt
                self.interacted = True
                if self.progress[a] >= self.dwell:
                    self.progress[a] = 0.0
                    self.lockout.add(a)
                    return a
            else:
                self.progress[a] = max(0.0, self.progress.get(a, 0.0) - 2 * dt)
        return None

    def draw(self, screen, buttons, scale):
        for i, b in enumerate(buttons):
            fill = theme.GOLD if b.primary else (45, 25, 14)
            if self.mouse_pos and b.rect.collidepoint(self.mouse_pos):
                fill = tuple(min(255, c + 35) for c in fill)
            pygame.draw.rect(screen, fill, b.rect, border_radius=10)
            frac = min(1.0, self.progress.get(b.action, 0.0) / self.dwell)
            if frac > 0:  # hand dwell: fills from the bottom
                bar = b.rect.copy()
                bar.h = int(b.rect.h * frac)
                bar.bottom = b.rect.bottom
                pygame.draw.rect(screen, (120, 230, 140), bar, border_radius=10)
            focused = self.keys_used and i == self.focus
            pygame.draw.rect(screen, theme.CREAM if focused else theme.GOLD, b.rect,
                             5 if focused else 2, border_radius=10)
            color = theme.INK if b.primary or frac > 0.5 else theme.CREAM
            size = min(b.rect.h * (0.42 if b.sub else 0.55), scale * 0.05)
            f = theme.font(size)
            while f.size(b.label)[0] > b.rect.w - 12 and size > b.rect.h * 0.3:  # shrink to fit first
                size *= 0.9
                f = theme.font(size)
            label = b.label
            while f.size(label)[0] > b.rect.w - 12 and len(label) > 3:  # then shorten long Wi-Fi names
                label = label[:-2] + "~"
            cy = b.rect.centery - (b.rect.h * 0.13 if b.sub else 0)
            text = f.render(label, True, color)
            screen.blit(text, text.get_rect(center=(b.rect.centerx, cy)))
            if b.sub:
                fs = theme.font(size * 0.6, name="arial")
                s = fs.render(b.sub, True, color)
                screen.blit(s, s.get_rect(center=(b.rect.centerx, b.rect.centery + b.rect.h * 0.25)))
