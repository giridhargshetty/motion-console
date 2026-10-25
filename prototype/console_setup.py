"""Console setup screens: network status at start-up, choose Wi-Fi, type the password.

Shown in the play area instead of the game. Every button works with a hand (hover), a mouse
(click) or arrow keys + Enter (remote). A real keyboard can also type the password directly.
Screens: status -> list -> password -> connecting -> status.
"""

import math
import time

import pygame

import theme
from ui import Button, Pointer

KEY_ROWS = {
    "lower": ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm-_."],
    "upper": ["1234567890", "QWERTYUIOP", "ASDFGHJKL\"", "ZXCVBNM-_."],
    "symbols": ["!@#$%^&*()", "+=[]{}<>/\\", "~`|;:,?'\"", "-_.@#"],
}
BACK_KEYS = (pygame.K_ESCAPE, pygame.K_AC_BACK)


class Setup:
    def __init__(self, cfg, net):
        self.cfg = cfg
        self.net = net
        self.auto_seconds = cfg["network"]["auto_start_seconds"]
        self.pointer = Pointer(cfg["menu"]["hover_seconds"])
        self.active = False
        self.screen = "status"
        self.ssid = None
        self.password = ""
        self.layout = "lower"
        self.show_password = False
        self.typed = False          # real keyboard in use on the password screen
        self.error = ""
        self.opened_at = 0.0
        self.next_refresh = 0.0
        self.hands_px = []
        self.buttons = []

    def open(self, screen="status"):
        self.active = True
        self.go(screen)
        self.opened_at = time.monotonic()
        self.pointer.interacted = False
        self.net.message = ""

    def go(self, screen):
        self.screen = screen
        self.pointer.reset()
        if screen == "status":
            self.net.refresh()
        elif screen == "list":
            self.net.scan()
        elif screen == "password":
            self.password, self.layout, self.show_password, self.typed = "", "lower", False, False

    # ---- layout: buttons in screen pixels, laid out inside the play area ----

    def make_buttons(self, rect):
        x, y, w, h = rect

        def box(x0, y0, x1, y1):  # fractions of the play area
            return (x + x0 * w, y + y0 * h, (x1 - x0) * w, (y1 - y0) * h)

        if self.screen == "status":
            return [Button(box(0.12, 0.56, 0.88, 0.68), "PLAY", "play", primary=True),
                    Button(box(0.12, 0.72, 0.88, 0.82), "CHOOSE WI-FI", "list")]
        if self.screen == "list":
            out = []
            for i, (ssid, signal, secured) in enumerate(self.net.networks[:6]):
                y0 = 0.14 + i * 0.1
                sub = f"signal {signal}%  -  " + ("password" if secured else "open")
                out.append(Button(box(0.06, y0, 0.94, y0 + 0.085), ssid, f"net:{i}", sub))
            out += [Button(box(0.06, 0.8, 0.48, 0.9), "SEARCH AGAIN", "rescan"),
                    Button(box(0.52, 0.8, 0.94, 0.9), "BACK", "back")]
            return out
        if self.screen == "password":
            out = []
            kw, top, kh = 0.092, 0.33, 0.075
            for r, row in enumerate(KEY_ROWS[self.layout]):
                x0 = 0.5 - len(row) * kw / 2
                for c, ch in enumerate(row):
                    xx, yy = x0 + c * kw, top + r * (kh + 0.01)
                    out.append(Button(box(xx + 0.004, yy, xx + kw - 0.004, yy + kh), ch, "key:" + ch))
            yy = top + 4 * (kh + 0.01)
            specials = [("SHIFT", "shift", 0.2), ("#+=", "symbols", 0.16), ("SPACE", "space", 0.28),
                        ("DEL", "delete", 0.16), ("SHOW" if not self.show_password else "HIDE", "show", 0.16)]
            xx = 0.02
            for label, action, kw2 in specials:
                out.append(Button(box(xx + 0.004, yy, xx + kw2 - 0.004, yy + kh), label, action))
                xx += kw2
            out += [Button(box(0.06, 0.84, 0.44, 0.93), "BACK", "back"),
                    Button(box(0.48, 0.84, 0.94, 0.93), "CONNECT", "connect", primary=True)]
            return out
        return []

    # ---- update ----

    def update(self, rect, hands_px, events, dt):
        """Returns "close" when the player should go on to the game."""
        self.hands_px = hands_px
        now = time.monotonic()
        if self.screen == "status" and now >= self.next_refresh:
            self.net.refresh()
            self.next_refresh = now + 5
        if self.screen == "connecting":
            if not self.net.busy:
                if self.net.message_ok:
                    self.go("status")
                else:
                    self.error = self.net.message
                    self.screen = "password"  # keep what was typed
            return None

        for e in events:
            if e.type != pygame.KEYDOWN:
                continue
            if e.key in BACK_KEYS:
                return self.back()
            if self.screen == "password":
                if e.key == pygame.K_BACKSPACE:
                    self.password = self.password[:-1]
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.typed:
                    return self.press("connect")
                elif e.unicode and e.unicode.isprintable() and e.key not in (pygame.K_UP, pygame.K_DOWN,
                                                                               pygame.K_LEFT, pygame.K_RIGHT):
                    self.password += e.unicode
                    self.typed = True

        self.buttons = self.make_buttons(rect)
        action = self.pointer.update(self.buttons, hands_px, events, dt,
                                     enter_presses=not (self.screen == "password" and self.typed))
        if action:
            return self.press(action)
        if (self.screen == "status" and self.net.online and not self.pointer.interacted
                and now - self.opened_at >= self.auto_seconds):
            return self.close()
        return None

    def back(self):
        if self.screen == "password":
            self.go("list")
        elif self.screen == "list":
            self.go("status")
        return None

    def close(self):
        self.active = False
        return "close"

    def press(self, action):
        if action == "play":
            return self.close()
        if action in ("list", "rescan"):
            self.go("list")
        elif action == "back":
            return self.back()
        elif action.startswith("net:"):
            ssid, _, secured = self.net.networks[int(action[4:])]
            self.ssid, self.error = ssid, ""
            if secured:
                self.go("password")
            else:
                self.net.connect(ssid, "")
                self.screen = "connecting"
        elif action.startswith("key:"):
            self.password += action[4:]
            if self.layout == "upper":
                self.layout = "lower"  # shift applies to one letter, like a phone keyboard
        elif action == "shift":
            self.layout = "lower" if self.layout == "upper" else "upper"
        elif action == "symbols":
            self.layout = "lower" if self.layout == "symbols" else "symbols"
        elif action == "space":
            self.password += " "
        elif action == "delete":
            self.password = self.password[:-1]
        elif action == "show":
            self.show_password = not self.show_password
        elif action == "connect" and self.password:
            self.net.connect(self.ssid, self.password)
            self.screen = "connecting"
        return None

    # ---- draw ----

    def text(self, screen, rect, msg, y, size, color=theme.CREAM):
        f = theme.font(rect.h * size)
        lines = theme.wrap(f, msg, rect.w * 0.9)
        for i, line in enumerate(lines):
            theme.text(screen, f, line, color, center=(rect.centerx, int(rect.y + rect.h * y) + i * f.get_height()))

    def draw(self, screen, rect):
        net, now = self.net, time.monotonic()
        if self.screen == "status":
            self.text(screen, rect, "NETWORK", 0.07, 0.07, theme.GOLD)
            wifi = net.ssid or ("not connected" if net.has_wifi else "no Wi-Fi adapter")
            rows = [("Cable", "connected" if net.wired else "not connected", net.wired),
                    ("Wi-Fi", wifi, net.ssid is not None),
                    ("Internet", "OK" if net.online else "no connection", net.online),
                    ("Remote access", {None: "not installed", True: "on", False: "off"}[net.tailscale],
                     net.tailscale is True)]
            f = theme.font(rect.h * 0.04, name="arial")
            for i, (label, value, good) in enumerate(rows):
                y = rect.y + rect.h * (0.19 + i * 0.065)
                theme.text(screen, f, label, theme.CREAM, midleft=(rect.x + rect.w * 0.08, y))
                theme.text(screen, f, value, (130, 240, 150) if good else (255, 140, 110),
                           midright=(rect.right - rect.w * 0.08, y))
            if net.message:
                self.text(screen, rect, net.message, 0.47, 0.035, (130, 240, 150) if net.message_ok else (255, 140, 110))
            if net.online and not self.pointer.interacted:
                left = max(0, math.ceil(self.auto_seconds - (now - self.opened_at)))
                self.text(screen, rect, f"Starting in {left}...", 0.88, 0.04)
            elif not net.online:
                self.text(screen, rect, "Hold a hand on CHOOSE WI-FI to connect", 0.88, 0.032)
        elif self.screen == "list":
            self.text(screen, rect, "CHOOSE WI-FI", 0.06, 0.06, theme.GOLD)
            if not net.networks:
                if net.busy:
                    msg = "Searching..."
                elif not net.has_wifi:
                    msg = ("This box has no Wi-Fi adapter. Use the network cable, "
                           "or plug in a USB Wi-Fi adapter and search again.")
                else:
                    msg = "No networks found"
                self.text(screen, rect, msg, 0.3, 0.04)
        elif self.screen == "password":
            self.text(screen, rect, f"Password for {self.ssid}", 0.07, 0.045, theme.GOLD)
            field = pygame.Rect(rect.x + rect.w * 0.06, rect.y + rect.h * 0.15, rect.w * 0.88, rect.h * 0.09)
            pygame.draw.rect(screen, (250, 245, 230), field, border_radius=8)
            pygame.draw.rect(screen, theme.GOLD, field, 3, border_radius=8)
            shown = self.password if self.show_password else "*" * len(self.password)
            cursor = "|" if int(now * 2) % 2 == 0 else " "
            f = theme.font(field.h * 0.6, name="consolas", bold=False)
            text = f.render(shown + cursor, True, theme.INK)
            screen.blit(text, text.get_rect(midright=(min(field.right - 10, field.x + 10 + text.get_width()), field.centery)))
            if self.error:
                self.text(screen, rect, self.error, 0.27, 0.032, (255, 140, 110))
        elif self.screen == "connecting":
            dots = "." * (1 + int(now * 2) % 3)
            self.text(screen, rect, f"Connecting to {self.ssid}{dots}", 0.42, 0.05, theme.GOLD)

        self.pointer.draw(screen, self.buttons, rect.h)
        for p in self.hands_px:
            pygame.draw.circle(screen, (255, 255, 255), p, max(8, int(rect.h * 0.025)), 3)
