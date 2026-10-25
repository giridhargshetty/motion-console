"""Render a Mixamo boxer to 2D sprite frames for the boxing game.

Runs inside Blender, headless:

    blender -b -P tools/blender/render_boxer.py -- \
        --character assets/source/rookie/character.fbx \
        --anims assets/source/rookie/anims \
        --out assets/boxers/rookie [--size 512 --fps 15]

What it does:
  1. Imports the character FBX (Mixamo, "With Skin", T-pose).
  2. Adds rounded boxing gloves parented to the hand bones.
  3. Imports each animation FBX (Mixamo, "Without Skin", "In Place") and
     keeps only its action, then plays it on the character.
  4. Places a fixed camera where the player stands: in front of the
     character at chest height, looking at it.
  5. Renders every animation to transparent PNGs:
         <out>/<anim>/frame_000.png, frame_001.png, ...
  6. Writes <out>/meta.json (fps, frame count, loop flag, and for punches
     the impact frame plus where the fist is on screen at that frame).

Animation file names are mapped to canonical keys (see ANIM_RULES below):
idle, jab, cross, hook, block, hit_head, hit_body, knockout, victory.
Missing ones are skipped with a warning; unknown files are rendered under a
slug of their file name.

Works with Blender 4.2 and newer (including the 4.4+ "slotted actions" API).
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

CANONICAL = ["idle", "jab", "cross", "hook", "block",
             "hit_head", "hit_body", "knockout", "victory"]

# First matching rule wins, so specific words come before general ones
# ("Body Block" is a block, not a body hit; "Hook Punch" is a hook).
ANIM_RULES = [
    ("knockout", r"knock|\bko\b|dying|death|fall"),
    ("victory", r"victory|\bwin|celebrat|cheer"),
    ("block", r"block|guard|cover"),
    ("hit_head", r"head.?hit|hit.?head|face.?hit|head.?react"),
    ("hit_body", r"stomach|body.?hit|hit.?body|gut|kidney|body.?react"),
    ("hit_head", r"\bhit\b|reaction|react"),
    ("idle", r"idle|stance|bouncing"),
    ("jab", r"jab"),
    ("cross", r"cross|straight"),
    ("hook", r"hook"),
    ("uppercut", r"uppercut"),
    ("cross", r"punch"),
]
PUNCHES = {"jab", "cross", "hook", "uppercut"}
LOOPS = {"idle"}

OPPONENT_RED = (0.75, 0.04, 0.04)


# ---------------------------------------------------------------- arguments

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="render_boxer.py")
    p.add_argument("--character", required=True, help="Mixamo character FBX (With Skin)")
    p.add_argument("--anims", required=True, help="folder of Mixamo animation FBX files")
    p.add_argument("--out", required=True, help="output folder, e.g. assets/boxers/rookie")
    p.add_argument("--size", type=int, default=512, help="frame width and height in px")
    p.add_argument("--fps", type=float, default=15, help="output frames per second")
    p.add_argument("--src-fps", type=float, default=30, help="fps the FBX was downloaded at")
    p.add_argument("--framing", choices=["full", "upper"], default="full",
                   help="full = whole body (knockouts stay in frame); upper = waist up, bigger")
    p.add_argument("--glove-color", default="",
                   help="glove RGB as r,g,b in 0..1 (default: opponent red)")
    p.add_argument("--engine", choices=["eevee", "cycles", "workbench"], default="eevee")
    p.add_argument("--only", default="", help="comma-separated keys to render (default: all)")
    return p.parse_args(argv)


def canonical_key(stem):
    s = stem.lower().replace("_", " ").replace("-", " ")
    compact = s.replace(" ", "_")
    if compact in CANONICAL or compact == "uppercut":
        return compact
    for key, pattern in ANIM_RULES:
        if re.search(pattern, s):
            return key
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_") or "anim"


# -------------------------------------------------------------- scene setup

def reset_scene():
    """Empty the startup scene. (read_factory_settings re-registers add-ons and
    throws errors in headless Blender 5.x, so clear the data instead.)"""
    for blocks in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                   bpy.data.lights, bpy.data.armatures, bpy.data.actions, bpy.data.worlds):
        for block in list(blocks):
            blocks.remove(block)


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path))
    return [o for o in bpy.data.objects if o not in before]


def find_bone(arm, suffix):
    """Mixamo bones are 'mixamorig:LeftHand', sometimes 'mixamorig1:LeftHand'."""
    for b in arm.pose.bones:
        if b.name == suffix or b.name.split(":")[-1] == suffix:
            return b
    return None


def bone_prefix(names):
    for n in names:
        if ":" in n:
            return n.split(":")[0] + ":"
    return ""


def action_fcurves(action):
    """F-curves of an action under both the legacy and the slotted (4.4+) API."""
    if hasattr(action, "layers") and len(action.layers):
        curves = []
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    curves.extend(bag.fcurves)
        if curves:
            return curves
    return list(getattr(action, "fcurves", []))


def assign_action(obj, action):
    ad = obj.animation_data or obj.animation_data_create()
    ad.action = action
    if hasattr(ad, "action_slot") and ad.action_slot is None and len(action.slots):
        ad.action_slot = action.slots[0]


def load_character(path):
    objs = import_fbx(path)
    arms = [o for o in objs if o.type == "ARMATURE"]
    if not arms:
        sys.exit(f"No armature in {path}. Download the character 'With Skin'.")
    arm = arms[0]
    meshes = [o for o in objs if o.type == "MESH"]
    if arm.animation_data:
        arm.animation_data.action = None
    return arm, meshes


def load_action(path, char_prefix):
    """Import an animation FBX, keep only its action, delete the rest."""
    objs = import_fbx(path)
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    action = arm.animation_data.action if arm and arm.animation_data else None
    if action is not None:
        action.use_fake_user = True
        # A different rig prefix (mixamorig1: vs mixamorig:) would leave the
        # action driving bones that don't exist on the character.
        anim_prefix = bone_prefix(b.name for b in arm.pose.bones)
        if anim_prefix != char_prefix:
            for fc in action_fcurves(action):
                fc.data_path = fc.data_path.replace(f'"{anim_prefix}', f'"{char_prefix}', 1)
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return action


# ------------------------------------------------------------------ measure

def world_bbox(meshes):
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for m in meshes:
        ev = m.evaluated_get(deps)
        for c in ev.bound_box:
            w = ev.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def bone_world(arm, pbone, where="head"):
    return arm.matrix_world @ getattr(pbone, where)


def facing_direction(arm):
    """Horizontal unit vector the character faces, from foot -> toe."""
    dirs = []
    for side in ("Left", "Right"):
        foot, toe = find_bone(arm, f"{side}Foot"), find_bone(arm, f"{side}ToeBase")
        if foot and toe:
            d = bone_world(arm, toe) - bone_world(arm, foot)
            d.z = 0
            dirs.append(d)
    if dirs:
        d = sum(dirs, Vector())
        if d.length > 1e-6:
            return d.normalized()
    return Vector((0, -1, 0))  # Mixamo FBX imports facing -Y


# ------------------------------------------------------------------- gloves

def make_material(name, rgb, roughness=0.35):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:  # Blender < 5 starts materials without nodes
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1)
        bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*rgb, 1)
    return mat


def add_gloves(arm, height, rgb):
    glove_mat = make_material("Glove", rgb)
    cuff_mat = make_material("GloveCuff", (0.92, 0.92, 0.92), 0.6)
    r = 0.06 * height  # cartoon-big on purpose: the glove is what kids watch
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    gloves = []
    for side in ("Left", "Right"):
        hand = find_bone(arm, f"{side}Hand")
        if hand is None:
            print(f"WARNING: no {side}Hand bone, skipping that glove")
            continue
        middle = find_bone(arm, f"{side}HandMiddle1")
        head = bone_world(arm, hand)
        tip = bone_world(arm, middle) if middle else bone_world(arm, hand, "tail")
        along = tip - head
        if along.length < 1e-6:
            along = Vector((0, 0, -1))
        rot = (arm.matrix_world @ hand.matrix).to_quaternion().to_matrix().to_4x4()
        # Glove centre a little past the knuckles so it covers the fist.
        centre = head + along.normalized() * (r * 0.9)

        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
        glove = bpy.context.active_object
        glove.name = f"Glove{side}"
        glove.data.materials.append(glove_mat)
        bpy.ops.object.shade_smooth()
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=1, depth=1)
        cuff = bpy.context.active_object
        cuff.name = f"Cuff{side}"
        cuff.data.materials.append(cuff_mat)
        bpy.ops.object.shade_smooth()

        # Bone local Y runs along the hand; gloves are a bit longer than wide.
        # The cylinder's axis is Z, so tilt it onto the bone's Y.
        cuff_rot = Matrix.Rotation(math.radians(90), 4, "X")
        for obj, mat in (
            (glove, Matrix.Translation(centre) @ rot @ Matrix.Diagonal((r, r * 1.2, r * 1.05, 1))),
            (cuff, Matrix.Translation(head - along.normalized() * r * 0.25) @ rot @ cuff_rot
                   @ Matrix.Diagonal((r * 0.72, r * 0.72, r * 0.6, 1))),
        ):
            obj.parent = arm
            obj.parent_type = "BONE"
            obj.parent_bone = hand.name
            bpy.context.view_layer.update()
            obj.matrix_world = mat
        gloves += [glove, cuff]
    arm.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    return gloves


# ------------------------------------------------------- camera and lights

def setup_camera(lo, hi, forward, framing, size):
    height = hi.z - lo.z
    centre_xy = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, 0))
    cam_data = bpy.data.cameras.new("PlayerView")
    cam_data.lens = 50
    cam_data.sensor_fit = "VERTICAL"
    cam = bpy.data.objects.new("PlayerView", cam_data)
    bpy.context.scene.collection.objects.link(cam)

    eye_z = lo.z + 0.72 * height  # chest height: you are the other boxer
    if framing == "full":
        span = height * 1.5       # whole body, gloves raised overhead, knockout fall
        aim_z = lo.z + 0.6 * height
    else:
        span = height * 0.9       # waist up, still room for raised gloves
        aim_z = lo.z + 0.75 * height
    fov = 2 * math.atan(cam_data.sensor_height / (2 * cam_data.lens))
    dist = (span / 2) / math.tan(fov / 2)

    cam.location = centre_xy + forward * dist + Vector((0, 0, eye_z))
    target = centre_xy + Vector((0, 0, aim_z))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    cam_data.clip_start = 0.05
    cam_data.clip_end = dist * 10

    scene = bpy.context.scene
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    return cam


def setup_lights(lo, hi, forward):
    height = hi.z - lo.z
    mid = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z + height * 0.6))
    side = forward.cross(Vector((0, 0, 1))).normalized()

    def light(name, kind, energy, pos, size=1.0):
        data = bpy.data.lights.new(name, kind)
        data.energy = energy
        if kind == "AREA":
            data.size = size
        obj = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = pos
        obj.rotation_euler = (mid - pos).to_track_quat("-Z", "Y").to_euler()

    s = height  # light power scales with how big the import came in
    light("Key", "AREA", 120 * s * s, mid + (forward + side * 0.8) * 2.5 * s + Vector((0, 0, s)), 2 * s)
    light("Fill", "AREA", 40 * s * s, mid + (forward - side) * 2.5 * s, 2 * s)
    light("Rim", "AREA", 100 * s * s, mid - forward * 2.5 * s + Vector((0, 0, 1.2 * s)), s)

    world = bpy.data.worlds.new("World")
    if world.node_tree is None:
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background") if world.node_tree else None
    if bg:
        bg.inputs["Color"].default_value = (0.35, 0.35, 0.38, 1)
        bg.inputs["Strength"].default_value = 0.4
    bpy.context.scene.world = world


def setup_render(engine):
    scene = bpy.context.scene
    names = {
        "eevee": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
        "cycles": ["CYCLES"],
        "workbench": ["BLENDER_WORKBENCH"],
    }[engine]
    available = {e.identifier for e in
                 bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = next((n for n in names if n in available), "BLENDER_WORKBENCH")
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = 32
        scene.cycles.use_denoising = True
    elif scene.render.engine.startswith("BLENDER_EEVEE"):
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = 16
    elif scene.render.engine == "BLENDER_WORKBENCH":
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 100
    try:
        scene.view_settings.view_transform = "Standard"  # true colours, no AgX wash
    except TypeError:
        pass
    print(f"Render engine: {scene.render.engine}")


# ------------------------------------------------------------------- render

def to_pixels(scene, cam, world_pos, size):
    v = world_to_camera_view(scene, cam, world_pos)
    return [round(v.x * size, 1), round((1 - v.y) * size, 1)]


def sample_frames(action, src_fps, out_fps, loop):
    start, end = action.frame_range
    step = src_fps / out_fps
    frames = []
    f = start
    while f <= end + 1e-6:
        frames.append(f)
        f += step
    if loop and len(frames) > 2:
        frames.pop()  # Mixamo loops repeat the first pose at the end
    return frames


def set_frame(scene, f):
    scene.frame_set(int(math.floor(f)), subframe=f - math.floor(f))


def find_impact(scene, arm, frames, forward):
    """Frame (index) where a fist is furthest toward the camera."""
    hands = {side.lower(): find_bone(arm, f"{side}Hand") for side in ("Left", "Right")}
    hands = {k: b for k, b in hands.items() if b}
    if not hands:
        return None, None
    base = {}
    best = (-math.inf, None, None)
    for i, f in enumerate(frames):
        set_frame(scene, f)
        for side, b in hands.items():
            reach = bone_world(arm, b).dot(forward)
            base.setdefault(side, reach)
            gain = reach - base[side]
            if gain > best[0]:
                best = (gain, i, side)
    if best[1] is None or best[0] <= 1e-4:
        return None, None
    return best[1], best[2]


def render_anim(scene, cam, arm, action, key, out_dir, args, forward):
    assign_action(arm, action)
    loop = key in LOOPS
    frames = sample_frames(action, args.src_fps, args.fps, loop)
    anim_dir = out_dir / key
    anim_dir.mkdir(parents=True, exist_ok=True)
    for old in anim_dir.glob("frame_*.png"):
        old.unlink()

    fps = int(args.fps) if float(args.fps).is_integer() else args.fps
    info = {"fps": fps, "frames": len(frames), "loop": loop}
    if key in PUNCHES:
        idx, side = find_impact(scene, arm, frames, forward)
        if idx is None:
            idx, side = len(frames) // 2, None
            print(f"  {key}: no clear forward reach, impact = middle frame")
        info["impact_frame"] = idx
        if side:
            info["impact_hand"] = side
            set_frame(scene, frames[idx])
            hand = find_bone(arm, f"{side.capitalize()}Hand")
            info["impact_xy"] = to_pixels(scene, cam, bone_world(arm, hand), args.size)

    for i, f in enumerate(frames):
        set_frame(scene, f)
        scene.render.filepath = str(anim_dir / f"frame_{i:03d}.png")
        bpy.ops.render.render(write_still=True)
    print(f"  {key}: {len(frames)} frames")
    return info


def main():
    args = parse_args()
    char_path = Path(args.character).resolve()
    anim_dir = Path(args.anims).resolve()
    out_dir = Path(args.out).resolve()
    anim_files = sorted(p for p in anim_dir.iterdir() if p.suffix.lower() == ".fbx")
    if not anim_files:
        sys.exit(f"No .fbx files in {anim_dir}")
    only = {k.strip() for k in args.only.split(",") if k.strip()}

    reset_scene()
    scene = bpy.context.scene
    arm, meshes = load_character(char_path)
    prefix = bone_prefix(b.name for b in arm.pose.bones)

    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    lo, hi = world_bbox(meshes)
    forward = facing_direction(arm)
    arm.data.pose_position = "POSE"
    height = hi.z - lo.z
    print(f"Character height {height:.3f} (scene units), facing {tuple(round(c, 2) for c in forward)}")

    rgb = tuple(float(c) for c in args.glove_color.split(",")) if args.glove_color else OPPONENT_RED
    add_gloves(arm, height, rgb)
    cam = setup_camera(lo, hi, forward, args.framing, args.size)
    setup_lights(lo, hi, forward)
    setup_render(args.engine)

    actions = {}
    for path in anim_files:
        key = canonical_key(path.stem)
        if key in actions:
            n = 2
            while f"{key}_{n}" in actions:
                n += 1
            print(f"WARNING: {path.name} also maps to '{key}', saving as '{key}_{n}'")
            key = f"{key}_{n}"
        if only and key not in only:
            continue
        action = load_action(path, prefix)
        if action is None:
            print(f"WARNING: {path.name} has no animation, skipped")
            continue
        action.name = key
        actions[key] = action
        print(f"{path.name} -> {key}")

    missing = [k for k in CANONICAL if k not in actions and (not only or k in only)]
    if missing:
        print(f"WARNING: no animation for: {', '.join(missing)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if (only and meta_path.exists()) else {}
    meta.update({
        "version": 1,
        "name": out_dir.name,
        "size": [args.size, args.size],
        "framing": args.framing,
        "anchor": {
            "feet": to_pixels(scene, cam, Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)), args.size),
            "head": to_pixels(scene, cam, Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z)), args.size),
        },
    })
    anims = meta.setdefault("animations", {})
    for key, action in actions.items():
        anims[key] = render_anim(scene, cam, arm, action, key, out_dir, args, forward)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    total = sum(p.stat().st_size for p in out_dir.rglob("*.png"))
    print(f"Wrote {meta_path} and {sum(a['frames'] for a in anims.values())} frames, "
          f"{total / 1e6:.1f} MB total")


if __name__ == "__main__":
    main()
