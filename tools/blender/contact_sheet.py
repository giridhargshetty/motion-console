"""Make one PNG grid of a boxer's rendered frames, for a quick visual check.

    .venv\\Scripts\\python tools/blender/contact_sheet.py assets/boxers/rookie
    -> logs/rookie_contact.png  (one row per animation; logs/ is git-ignored)

Impact frames from meta.json get a yellow border. Needs Pillow.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

BG = (40, 40, 48)
CHECK = (56, 56, 66)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("boxer_dir", help="e.g. assets/boxers/rookie")
    p.add_argument("--thumb", type=int, default=128, help="thumbnail size in px")
    p.add_argument("--out", help="output PNG (default: logs/<name>_contact.png)")
    args = p.parse_args()

    root = Path(args.boxer_dir)
    meta_path = root / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    anims = meta.get("animations", {})
    rows = [(d.name, sorted(d.glob("frame_*.png")))
            for d in sorted(root.iterdir()) if d.is_dir()]
    rows = [(name, frames) for name, frames in rows if frames]
    if not rows:
        raise SystemExit(f"No frame_*.png folders in {root}")

    t, label_w = args.thumb, 110
    cols = max(len(f) for _, f in rows)
    sheet = Image.new("RGB", (label_w + cols * t, len(rows) * t), BG)
    draw = ImageDraw.Draw(sheet)
    for r, (name, frames) in enumerate(rows):
        y = r * t
        impact = anims.get(name, {}).get("impact_frame")
        draw.text((6, y + t // 2 - 6), f"{name} ({len(frames)})", fill=(230, 230, 230))
        for c, path in enumerate(frames):
            x = label_w + c * t
            # Checkerboard so transparent areas read as transparent.
            for cy in range(0, t, 16):
                for cx in range((cy // 16) % 2 * 16, t, 32):
                    draw.rectangle([x + cx, y + cy, x + cx + 15, y + cy + 15], fill=CHECK)
            img = Image.open(path).convert("RGBA")
            img.thumbnail((t, t))
            sheet.paste(img, (x + (t - img.width) // 2, y + (t - img.height) // 2), img)
            if c == impact:
                draw.rectangle([x, y, x + t - 1, y + t - 1], outline=(255, 210, 0), width=3)

    out = Path(args.out) if args.out else Path("logs") / f"{root.name}_contact.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"Wrote {out} ({len(rows)} animations, {sum(len(f) for _, f in rows)} frames)")


if __name__ == "__main__":
    main()
