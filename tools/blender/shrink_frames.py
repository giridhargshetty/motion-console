"""Shrink rendered boxer frames to 256-colour PNGs (about 6x smaller, no visible change).

    .venv\\Scripts\\python tools/blender/shrink_frames.py assets/boxers/rookie

Run after render_boxer.py, before committing. Safe to run twice. Needs Pillow.
"""

import argparse
from pathlib import Path

from PIL import Image


def main():
    p = argparse.ArgumentParser()
    p.add_argument("boxer_dir", help="e.g. assets/boxers/rookie")
    args = p.parse_args()

    files = sorted(Path(args.boxer_dir).rglob("frame_*.png"))
    if not files:
        raise SystemExit(f"No frame_*.png under {args.boxer_dir}")
    before = after = 0
    for f in files:
        before += f.stat().st_size
        img = Image.open(f)
        if img.mode == "RGBA":  # already-shrunk frames are mode "P"
            img = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
            img.save(f, optimize=True)
        after += f.stat().st_size
    print(f"{len(files)} frames: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
