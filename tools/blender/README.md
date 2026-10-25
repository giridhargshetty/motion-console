# Boxer sprites: Mixamo → Blender → PNG frames

The boxing game shows the computer opponent as 2D picture frames. We make those
frames from free 3D characters and animations on Adobe Mixamo, and let Blender
(free) turn them into pictures automatically. You download files once; a script
does the rest.

What you end up with, per character:

```
assets/boxers/rookie/
├── meta.json              # fps, frame counts, punch impact frames
├── idle/frame_000.png ... # transparent PNGs, 512 × 512
├── jab/frame_000.png ...
└── ...
```

The game picks these up automatically. Until they exist it uses placeholder art.

---

## 1. Install Blender (once)

Open **PowerShell** and run:

```powershell
winget install -e --id BlenderFoundation.Blender
```

Close and reopen PowerShell afterwards. Check it works:

```powershell
blender --version
```

If that says "not recognised", use the full path instead of `blender` in the
commands below, e.g. `& "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"`
(the version number in the folder name may differ).

## 2. Make a free Adobe account (once)

Go to <https://www.mixamo.com> and sign in, or click **Sign up** to make a free
Adobe account. No payment needed.

## 3. Download from Mixamo

We want **3 opponents of different builds**, one per difficulty:

| Difficulty | Folder name | Pick a character that looks… |
| --- | --- | --- |
| Rookie | `rookie` | slim or young, friendly |
| Contender | `contender` | average build |
| Champ | `champ` | big and muscular |

Any Mixamo character works (e.g. browse the **Characters** tab and pick by look).
Do steps 3a and 3b for each of the three.

### 3a. The character

1. **Characters** tab → click a character.
2. Click **Download** and set:
   - Format: **FBX Binary (.fbx)**
   - Pose: **T-pose**
3. Save it as `character.fbx` in `assets/source/<folder name>/`
   (e.g. `assets/source/rookie/character.fbx`).

### 3b. The animations

Keep the same character selected (so the animations fit its skeleton). For each
animation below: **Animations** tab → search the name → click it → tick
**In Place** if the box is shown → **Download** with these settings:

- Format: **FBX Binary (.fbx)**
- Skin: **Without Skin**
- Frames per second: **30**
- Keyframe Reduction: **none**

Save into `assets/source/<folder name>/anims/`. The file name tells the script
what the animation is, so keep a name containing the word in the right-hand
column (the Mixamo default names already do), or simply rename the file to the key,
e.g. `jab.fbx`.

| Search Mixamo for | Becomes key | Words the script looks for |
| --- | --- | --- |
| Bouncing Fight Idle | `idle` | idle, stance, bouncing |
| Lead Jab | `jab` | jab |
| Cross Punch | `cross` | cross, straight, punch |
| Hook Punch | `hook` | hook |
| Body Block *or* Center Block | `block` | block, guard, cover |
| Head Hit | `hit_head` | head hit, hit, reaction |
| Stomach Hit | `hit_body` | stomach, body hit, gut, kidney |
| Knocked Out | `knockout` | knock, ko, dying, death, fall |
| Victory | `victory` | victory, win, celebrate, cheer |

Missing animations are fine; the script warns and the game falls back to
placeholder art for those. An Uppercut is accepted too (key `uppercut`). Files
with other names are still rendered, under their own name.

When you're done a folder looks like:

```
assets/source/rookie/
├── character.fbx
└── anims/
    ├── Bouncing Fight Idle.fbx
    ├── Lead Jab.fbx
    ├── Cross Punch.fbx
    └── ...
```

`assets/source/` is git-ignored: the raw Mixamo files stay on this PC.

## 4. Render

From the repo folder (`play tv`), in PowerShell:

```powershell
blender -b -P tools/blender/render_boxer.py -- --character assets/source/rookie/character.fbx --anims assets/source/rookie/anims --out assets/boxers/rookie
```

Repeat with `contender` and `champ`. Each character takes a few minutes. Options
(put them after the `--`):

| Option | Default | Meaning |
| --- | --- | --- |
| `--size 512` | 512 | Frame width and height in pixels |
| `--fps 15` | 15 | Frames per second of output (fewer = smaller files) |
| `--src-fps 30` | 30 | The fps you picked on Mixamo |
| `--framing full` | full | `full` = whole body (knockout stays in shot); `upper` = waist up, bigger |
| `--glove-color 0.1,0.2,0.8` | red | Glove colour as red,green,blue from 0 to 1 |
| `--engine eevee` | eevee | `cycles` (slower, works without a GPU) or `workbench` (flat, fastest) |
| `--only jab,hook` | all | Re-render just these; the rest of meta.json is kept |

Blender 5.2 prints a red `ImportError ... remote_library` traceback when it
starts. That's Blender's own bug and harmless; ignore it.

It prints which file became which key, warns about missing ones, and ends with
the total size. Aim for roughly **5–7 MB per character** because the frames are
committed to git; if it's bigger, use `--fps 12`.

### Check the result

Make one picture with every frame on it (impact frames get a yellow border):

```powershell
.venv\Scripts\python tools/blender/contact_sheet.py assets/boxers/rookie
```

Open `logs/rookie_contact.png` (the `logs/` folder isn't committed). The
opponent should face you, gloves red, nothing cut off at the edges.

## What the script does

1. Imports the character and measures its height and which way it faces.
2. Adds rounded boxing gloves (sphere + white cuff) that follow the hand bones.
3. Imports each animation file, keeps only its motion, and plays it on the
   character.
4. Puts the camera where you, the player, stand: in front, at chest height,
   looking at the opponent. The camera never moves, so all animations line up.
5. Renders each animation to transparent PNGs.
6. Writes `meta.json`.

## meta.json

```json
{
  "version": 1,
  "name": "rookie",
  "size": [512, 512],
  "framing": "full",
  "anchor": {"feet": [256.0, 470.2], "head": [256.0, 61.5]},
  "animations": {
    "idle":  {"fps": 15, "frames": 20, "loop": true},
    "jab":   {"fps": 15, "frames": 14, "loop": false,
              "impact_frame": 6, "impact_hand": "left", "impact_xy": [301.4, 188.0]},
    "block": {"fps": 15, "frames": 18, "loop": false}
  }
}
```

- Each animation's frames are `<key>/frame_000.png` … `frame_<frames-1>.png`.
- `loop`: `true` only for `idle` (its repeated last frame is dropped so it loops
  cleanly).
- `impact_frame` (punches only: jab, cross, hook, uppercut): index of the frame where a
  fist is furthest toward the camera, which is the moment the punch lands. Falls back to the
  middle frame if no forward reach is found (then there's no `impact_hand` / `impact_xy`).
- `impact_hand`: `left` or `right`, from the character's point of view.
- `impact_xy`, `anchor`: pixel positions in the frame (origin top-left) of the
  fist at impact, and of the character's feet and head top in the rest pose.

## Licence

Mixamo characters and animations are royalty-free to use in your own projects,
including commercial ones. You may **not** redistribute the raw Mixamo files
(the `.fbx` downloads). That's why `assets/source/` is git-ignored and only the
rendered PNGs in `assets/boxers/` are committed.
