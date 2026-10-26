# Assets

| Folder | In git | What |
| --- | --- | --- |
| `boxers/<name>/` | yes | Boxing opponents: rendered frames + `meta.json` (from `tools/blender/render_boxer.py`) |
| `costumes/<name>/` | yes | Dress Up costumes: rendered pieces, `costume.json`, `preview.png`, `scene.jpg` (from `tools/blender/render_costume.py`) |
| `models/quaternius/` | yes | The 3D models the costumes use (OBJ + MTL), CC0 by Quaternius. Only the ones in use, so a clean checkout can re-render |
| `source/` | **no** (git-ignored) | Raw downloads, kept on this PC only |

## source/ (raw downloads)

| Folder | Licence | Contents | Used for |
| --- | --- | --- | --- |
| `rookie/` | Mixamo (use in projects, don't redistribute) | Mixamo character + boxing animations | Boxing: Rookie |
| `quaternius_rpg_items/` | CC0 | Ultimate RPG Items: 106 items (weapons, armour, crowns, potions, books, ...) as FBX/OBJ/Blend + icon PNGs | Dress Up pieces |
| `quaternius_knight/` | CC0 | Knight Pack: 3 helmets, shoulder pads, sword, katana, short sword, club, knight character | Dress Up pieces |
| `kenney_characters_retro/`, `kenney_characters_survivors/` | CC0 | One rigged character with human / zombie / survivor skins; idle, run, jump animations | Not used yet: a good fit for the planned endless-runner game |
| `_zips/` | | The original zip files | |

Use the **OBJ** files from the Quaternius packs: their FBX files import into Blender with fully
transparent materials. Don't open the `.blend` files from downloads (they can contain scripts).

To use another model in a costume: copy its `.obj` + `.mtl` into `models/quaternius/` and add it
to a costume in `tools/blender/render_costume.py` with `model(...)` (see the knight for examples).
