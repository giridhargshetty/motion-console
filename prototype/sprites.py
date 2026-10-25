"""Boxer sprite frames rendered by tools/blender/render_boxer.py from Mixamo characters:

    assets/boxers/<name>/<anim>/frame_000.png ...
    assets/boxers/<name>/meta.json   {"animations": {"<anim>": {"fps": 15, "frames": 12, "impact_frame": 6}}}

Animations: idle, jab, cross, hook, block, hit_head, hit_body, knockout, victory (any may be missing).
load() returns None when a boxer hasn't been rendered yet; the game then draws placeholder shapes.
"""

import functools
import json
from pathlib import Path

import pygame

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "boxers"


class SpriteSet:
    def __init__(self, folder):
        self.folder = folder
        meta = json.loads((folder / "meta.json").read_text())
        self.meta = meta.get("animations", meta)
        self._frames = {}   # anim -> [Surface]
        self._scaled = {}   # (anim, i, height) -> Surface

    def has(self, anim):
        return anim in self.meta and (self.folder / anim).is_dir()

    def frames(self, anim):
        if anim not in self._frames:
            files = sorted((self.folder / anim).glob("*.png")) if self.has(anim) else []
            self._frames[anim] = [pygame.image.load(str(f)).convert_alpha() for f in files]
        return self._frames[anim]

    def frame(self, anim, seconds, height, loop=True):
        """The frame `seconds` into `anim`, scaled to `height` px (cached). None if missing."""
        frames = self.frames(anim)
        if not frames:
            return None
        fps = self.meta.get(anim, {}).get("fps", 15)
        i = int(seconds * fps)
        i = i % len(frames) if loop else min(i, len(frames) - 1)
        key = (anim, i, int(height))
        if key not in self._scaled:
            src = frames[i]
            w = max(1, int(src.get_width() * height / src.get_height()))
            self._scaled[key] = pygame.transform.smoothscale(src, (w, int(height)))
        return self._scaled[key]


@functools.cache
def load(name):
    folder = ASSETS / name
    if not (folder / "meta.json").exists():
        return None
    try:
        return SpriteSet(folder)
    except (OSError, ValueError):
        return None
