"""Wi-Fi and remote-access (Tailscale) status for the console's setup screens.

Uses NetworkManager's nmcli on the Linux kiosk. Where nmcli is missing (the Windows dev
laptop) `available` is False and the Wi-Fi screens are skipped; backend = "fake" simulates
networks so the screens can be tried anywhere. Slow work (scan, connect) runs on a thread;
the screens poll `busy`, `networks`, `ssid`, `online`, `tailscale` and `message`.
"""

import json
import shutil
import subprocess
import threading
import time


def run(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def split_terse(line):
    """Split one line of `nmcli -t` output: fields joined by ':', with ':' inside a field as '\\:'."""
    fields, cur, escaped = [], "", False
    for ch in line:
        if escaped:
            cur += ch
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append(cur)
            cur = ""
        else:
            cur += ch
    fields.append(cur)
    return fields


def parse_wifi_list(text):
    """nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY output -> (networks sorted by signal, ssid in use).
    networks: [(ssid, signal 0..100, secured)], one entry per name (strongest)."""
    best, in_use = {}, None
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) < 4 or not f[1]:
            continue  # hidden networks have no name
        ssid, signal, secured = f[1], int(f[2] or 0), f[3] not in ("", "--")
        if f[0].strip() == "*":
            in_use = ssid
        if ssid not in best or signal > best[ssid][1]:
            best[ssid] = (ssid, signal, secured)
    return sorted(best.values(), key=lambda n: -n[1]), in_use


def friendly_error(stderr):
    s = stderr.lower()
    if "secrets were required" in s or "password" in s or "802-1x" in s:
        return "Wrong password? Try again."
    if "no network with ssid" in s:
        return "That network is out of range now."
    if "not authorized" in s:
        return "Not allowed to change Wi-Fi (run deploy/linux/setup.sh again)."
    return "Couldn't connect. " + stderr.strip().splitlines()[-1][:80] if stderr.strip() else "Couldn't connect."


class Network:
    def __init__(self, backend="auto"):
        if backend == "auto":
            backend = "nmcli" if shutil.which("nmcli") else "none"
        self.backend = backend
        self.available = backend in ("nmcli", "fake")
        self.networks = []
        self.ssid = None
        self.online = False
        self.tailscale = None  # None = not installed, else True/False (connected)
        self.busy = False
        self.message = ""
        self.message_ok = True
        self._fake = {"ssid": "HomeWiFi", "nets": [("HomeWiFi", 82, True), ("Neighbour 5G", 61, True),
                                                   ("CafeGuest", 40, False), ("Office:2", 23, True)]}

    def _start(self, fn, *args):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                fn(*args)
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def refresh(self):
        self._start(self._refresh)

    def scan(self):
        self._start(self._scan)

    def connect(self, ssid, password):
        self._start(self._connect, ssid, password)

    # ---- work (background thread) ----

    def _refresh(self):
        if self.backend == "fake":
            self.ssid, self.online = self._fake["ssid"], self._fake["ssid"] is not None
        elif self.backend == "nmcli":
            _, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "no"])
            _, self.ssid = parse_wifi_list(out)
            _, out, _ = run(["nmcli", "networking", "connectivity", "check"])
            self.online = out.strip() == "full"
        self.tailscale = self._tailscale_up()

    def _tailscale_up(self):
        if self.backend == "fake":
            return self.online
        if not shutil.which("tailscale"):
            return None
        code, out, _ = run(["tailscale", "status", "--json"], timeout=5)
        try:
            return code == 0 and json.loads(out).get("BackendState") == "Running"
        except ValueError:
            return False

    def _scan(self):
        if self.backend == "fake":
            time.sleep(1.0)
            self.networks = list(self._fake["nets"])
        elif self.backend == "nmcli":
            _, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "--rescan", "yes"],
                            timeout=30)
            self.networks, self.ssid = parse_wifi_list(out)

    def _connect(self, ssid, password):
        if self.backend == "fake":
            time.sleep(1.5)
            secured = next((n[2] for n in self._fake["nets"] if n[0] == ssid), True)
            ok = not secured or len(password) >= 8
            if ok:
                self._fake["ssid"] = ssid
            err = "" if ok else "Error: Secrets were required, but not provided."
        else:
            args = ["nmcli", "dev", "wifi", "connect", ssid]
            if password:
                args += ["password", password]
            code, _, err = run(args, timeout=45)
            ok = code == 0
        self.message, self.message_ok = (f"Connected to {ssid}", True) if ok else (friendly_error(err), False)
        self._refresh()
