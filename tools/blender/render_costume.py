"""Render the Dress Up costumes: built in 3D from simple shapes, saved as 2D pieces with anchors.

Runs inside Blender, headless:

    blender -b -P tools/blender/render_costume.py -- --out assets/costumes [--only knight,wizard] [--size 320]

Every costume is modelled around one reference body (a child facing the camera, arms a little out).
Each piece (helmet, armour, sword, ...) is rendered front-on with an orthographic camera to a
transparent PNG, and its anchors (the body points it hangs on, like the ears or the shoulders) are
projected into that PNG's pixels. The game (prototype/dressup_fit.py) maps those anchors onto the
player's live keypoints, so pieces size and turn with whoever is playing:
  2 anchors: head pieces (ears), forearm pieces and props (elbow -> wrist), boots (knee -> ankle)
  3 anchors: torso pieces and capes (both shoulders + the middle of the hips)
Head pieces are also rendered turned 35 degrees each way. Each costume also gets preview.png (all
pieces on a grey mannequin, for the picker) and scene.jpg (its backdrop, 1280x720).

Output: assets/costumes/<name>/{costume.json, <piece>.png, preview.png, scene.jpg}
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

# Reference body in metres: facing -Y (toward the camera), the character's left is +X.
J = {"head": (0, 0, 1.05), "nose": (0, -0.095, 1.035), "l_eye": (0.035, -0.085, 1.06), "r_eye": (-0.035, -0.085, 1.06),
     "l_ear": (0.09, 0, 1.045), "r_ear": (-0.09, 0, 1.045), "neck": (0, 0, 0.93),
     "l_shoulder": (0.14, 0, 0.89), "r_shoulder": (-0.14, 0, 0.89), "l_elbow": (0.19, 0, 0.7), "r_elbow": (-0.19, 0, 0.7),
     "l_wrist": (0.22, 0, 0.53), "r_wrist": (-0.22, 0, 0.53), "l_index": (0.235, -0.01, 0.46), "r_index": (-0.235, -0.01, 0.46),
     "l_hip": (0.085, 0, 0.6), "r_hip": (-0.085, 0, 0.6), "mid_hip": (0, 0, 0.6),
     "l_knee": (0.09, 0, 0.33), "r_knee": (-0.09, 0, 0.33), "l_ankle": (0.09, 0, 0.07), "r_ankle": (-0.09, 0, 0.07),
     "l_foot": (0.1, -0.11, 0.02), "r_foot": (-0.1, -0.11, 0.02)}
J = {k: Vector(v) for k, v in J.items()}
HEAD = J["head"]
YAW = 35  # degrees, for the turned head views
SIDES = (("l", 1), ("r", -1))


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="render_costume.py")
    p.add_argument("--out", required=True, help="output folder, e.g. assets/costumes")
    p.add_argument("--only", default="", help="comma-separated costumes (default: all)")
    p.add_argument("--size", type=int, default=320, help="longest side of a piece picture, px")
    p.add_argument("--no-scenes", action="store_true", help="skip the backdrops (faster while tuning)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- building blocks

def clear(keep_lights=True):
    for o in list(bpy.data.objects):
        if o.type != "CAMERA" and not (keep_lights and o.type == "LIGHT"):
            bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        if not m.users:
            bpy.data.meshes.remove(m)


def mat(name, rgb, metal=0.0, rough=0.5, emit=0.0, alpha=1.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Metallic"].default_value = metal
    b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emit
    if alpha < 1:
        b.inputs["Alpha"].default_value = alpha
        if hasattr(m, "surface_render_method"):
            m.surface_render_method = "BLENDED"
        elif hasattr(m, "blend_method"):
            m.blend_method = "BLEND"
    m.diffuse_color = (*rgb, alpha)
    return m


def finish(o, material, smooth=True, bevel=0.0):
    o.data.materials.append(material)
    if smooth:
        for poly in o.data.polygons:
            poly.use_smooth = True
    if bevel:
        mod = o.modifiers.new("Bevel", "BEVEL")
        mod.width, mod.segments = bevel, 3
    return o


def sphere(center, r, material, scale=(1, 1, 1), segs=32):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segs, ring_count=segs // 2, radius=r, location=center)
    o = bpy.context.active_object
    o.scale = scale
    return finish(o, material)


def box(center, size, material, bevel=0.006, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center, rotation=rot)
    o = bpy.context.active_object
    o.scale = size
    return finish(o, material, smooth=False, bevel=bevel)


def tube(a, b, r1, r2, material, verts=32):
    """A cone / cylinder from point a (radius r1) to point b (radius r2)."""
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=(b - a).length, location=(a + b) / 2)
    o = bpy.context.active_object
    o.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
    return finish(o, material)


def ring(center, major, minor, material, rot=(0, 0, 0), scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, location=center, rotation=rot,
                                     major_segments=48, minor_segments=12)
    o = bpy.context.active_object
    o.scale = scale
    return finish(o, material)


def flat(points, center, depth, material, scale=1.0, rot=None):
    """A flat shape (points in the X/Z plane, facing the camera) extruded `depth` along Y."""
    mesh = bpy.data.meshes.new("flat")
    bm = bmesh.new()
    vs = [bm.verts.new((x * scale, 0, z * scale)) for x, z in points]
    face = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    for v in [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]:
        v.co.y += depth
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    o = bpy.data.objects.new("flat", mesh)
    bpy.context.scene.collection.objects.link(o)
    o.location = Vector(center) - Vector((0, depth / 2, 0))
    if rot is not None:
        o.rotation_euler = rot
    return finish(o, material, smooth=False, bevel=min(0.004, depth / 3))


def shell(center, r, material, scale=(1, 1, 1), keep=lambda co: True, thick=0.01):
    """Part of a sphere (vertices where keep(world co) is true), given a thickness."""
    o = sphere(center, r, material, scale, segs=48)
    bpy.context.view_layer.update()  # so matrix_world includes the scale
    bm = bmesh.new()
    bm.from_mesh(o.data)
    world = o.matrix_world
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not keep(world @ v.co)], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    mod = o.modifiers.new("Solid", "SOLIDIFY")
    mod.thickness = thick
    return o


def star(n=5, outer=1.0, inner=0.45):
    return [((outer if i % 2 == 0 else inner) * math.sin(math.pi * i / n),
             (outer if i % 2 == 0 else inner) * math.cos(math.pi * i / n)) for i in range(2 * n)]


def along(a, b, t):
    return Vector(a).lerp(Vector(b), t)


def hand(side):
    return (J[f"{side}_wrist"] + J[f"{side}_index"]) / 2


def forearm_dir(side):
    return (J[f"{side}_wrist"] - J[f"{side}_elbow"]).normalized()


# ---------------------------------------------------------------- shared piece shapes

def torso_shell(material, flare=1.0, bottom=0.57, top=0.9, depth=0.1, width=0.16):
    """Chest-to-hips body piece, front half (the camera only sees the front)."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=1, depth=1, location=(0, 0, (bottom + top) / 2))
    o = bpy.context.active_object
    o.scale = (width, depth, top - bottom)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for v in bm.verts:  # taper: wider at the chest, flare at the bottom
        k = v.co.z + 0.5
        v.co.x *= 0.88 + 0.12 * k if flare == 1.0 else flare + (1 - flare) * k
    bm.to_mesh(o.data)
    bm.free()
    return finish(o, material, bevel=0.01)


def robe(material, top=0.9, bottom=0.3, r_top=0.16, r_bottom=0.3):
    return tube((0, 0.0, bottom), (0, 0.0, top), r_bottom, r_top, material, verts=48)


def boot(side, material, top=0.3, sole=None, r=0.05, cuff=None):
    s = dict(SIDES)[side]
    knee, ankle = J[f"{side}_knee"], J[f"{side}_ankle"]
    parts = [tube((ankle.x, 0, 0.05), (along(ankle, knee, (top - 0.07) / 0.26).x, 0, top), r, r * 1.08, material),
             box((ankle.x + 0.005 * s, -0.06, 0.035), (0.09, 0.17, 0.07), sole or material, bevel=0.02)]
    if cuff:
        parts.append(ring((along(ankle, knee, (top - 0.07) / 0.26).x, 0, top), r * 1.15, 0.018, cuff))
    return parts


def glove(side, material, cuff=None, r=0.045):
    h, w, e = hand(side), J[f"{side}_wrist"], J[f"{side}_elbow"]
    parts = [sphere(h, r, material, scale=(1, 0.9, 1.15))]
    parts.append(tube(w, along(w, e, 0.22), r * 0.8, r * 1.0, cuff or material))
    return parts


def held_rod(side, length, r, material, back=0.06):
    """A rod held in the fist, carrying on along the forearm past the hand."""
    h, d = hand(side), forearm_dir(side)
    return tube(h - d * back, h + d * length, r, r, material, verts=16), h + d * length, d


# ---------------------------------------------------------------- costumes
# Each piece: (name, builder, anchors, options). Builders make objects in the scene.

def knight():
    steel = mat("steel", (0.5, 0.52, 0.57), metal=0.9, rough=0.42)
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.35)
    red = mat("red", (0.75, 0.05, 0.06), rough=0.6)
    blue = mat("blue", (0.08, 0.2, 0.7), rough=0.4)
    brown = mat("brown", (0.3, 0.16, 0.06), rough=0.7)

    def helmet():
        # dome above the brow, plus cheek guards at the sides: the face stays open (no inside of the
        # back showing through, since the piece is drawn over the player)
        opening = lambda co: co.z > HEAD.z + 0.035 or (abs(co.x) > 0.075 and co.y < 0.03 and co.z > HEAD.z - 0.09)  # noqa: E731
        return [shell(HEAD + Vector((0, 0.005, 0.01)), 0.118, steel, scale=(1, 1.05, 1.1), keep=opening, thick=0.012),
                box(HEAD + Vector((0, -0.122, -0.005)), (0.018, 0.012, 0.085), steel, bevel=0.004),
                ring(HEAD + Vector((0, 0.005, 0.045)), 0.119, 0.009, gold, scale=(1, 1.05, 1))]

    def plume():
        return [sphere(HEAD + Vector((0, 0.03, 0.17)), 0.05, red, scale=(0.45, 1.5, 1.1)),
                tube(HEAD + Vector((0, 0.02, 0.12)), HEAD + Vector((0, 0.02, 0.14)), 0.02, 0.012, gold)]

    def armour():
        parts = [torso_shell(steel), ring((0, 0, 0.6), 1, 0.012, gold, scale=(0.15, 0.095, 1)),
                 box((0, -0.1, 0.6), (0.3, 0.02, 0.04), brown, bevel=0.005),
                 flat(star(), (0, -0.105, 0.76), 0.01, gold, scale=0.05)]
        for side, s in SIDES:
            parts.append(sphere(J[f"{side}_shoulder"] + Vector((0.02 * s, 0, 0.015)), 0.072, steel, scale=(1.1, 1, 0.8)))
        return parts

    def shield():
        c = along(J["l_elbow"], J["l_wrist"], 0.5) + Vector((0.04, -0.09, 0))
        kite = [(-0.1, 0.13), (0.1, 0.13), (0.1, 0.0), (0, -0.17), (-0.1, 0.0)]
        return [flat(kite, c + Vector((0, 0.012, 0)), 0.015, gold, scale=1.09),
                flat(kite, c, 0.02, blue),
                box(c + Vector((0, -0.012, -0.01)), (0.022, 0.006, 0.22), gold, bevel=0.002),
                box(c + Vector((0, -0.012, 0.04)), (0.16, 0.006, 0.022), gold, bevel=0.002)]

    def sword():
        blade, tip, d = held_rod("r", 0.5, 0.012, steel, back=0.0)
        blade.scale = (2.2, 0.5, 1)
        h = hand("r")
        across = Vector((d.z, 0, -d.x))
        return [blade, tube(h - across * 0.08, h + across * 0.08, 0.012, 0.012, gold, 16),
                tube(h - d * 0.09, h + d * 0.01, 0.016, 0.016, brown, 16), sphere(h - d * 0.1, 0.022, gold)]

    pieces = [("plume", plume, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3, "bob": HEAD + Vector((0, 0.02, 0.125))}),
              ("helmet", helmet, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("armour", armour, ["l_shoulder", "r_shoulder", "mid_hip"], {}),
              ("shield", shield, ["l_elbow", "l_wrist"], {}),
              ("sword", sword, ["r_elbow", "r_wrist"], {"sparkle": True})]
    for side, _ in SIDES:
        pieces += [(f"{side}_gauntlet", lambda side=side: glove(side, steel, cuff=steel), [f"{side}_elbow", f"{side}_wrist"], {}),
                   (f"{side}_boot", lambda side=side: boot(side, steel, top=0.22, cuff=gold), [f"{side}_knee", f"{side}_ankle"], {})]
    return "KNIGHT", pieces, castle


def superhero():
    red = mat("hero_red", (0.85, 0.06, 0.08), rough=0.35)
    blue = mat("hero_blue", (0.06, 0.15, 0.6), rough=0.35)
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.3)
    white = mat("white", (0.95, 0.95, 0.95), rough=0.4)

    def mask():
        eyes = [J["l_eye"], J["r_eye"]]
        keep = lambda co: (abs(co.z - J["l_eye"].z) < 0.028 and co.y < -0.035  # noqa: E731
                           and all((co - e).xz.length > 0.02 for e in eyes))
        return [shell(HEAD, 0.108, blue, keep=keep, thick=0.006)]

    def suit():
        bolt = [(-0.3, 1.0), (0.45, 1.0), (0.05, 0.25), (0.5, 0.25), (-0.35, -1.0), (-0.05, -0.05), (-0.45, -0.05)]
        parts = [torso_shell(blue), ring((0, 0, 0.61), 1, 0.014, gold, scale=(0.15, 0.095, 1)),
                 flat([(math.sin(a) * 0.075, math.cos(a) * 0.075) for a in [i * math.pi / 16 for i in range(32)]],
                      (0, -0.1, 0.77), 0.01, white),
                 flat(bolt, (0, -0.108, 0.77), 0.012, red, scale=0.06)]
        for side, s in SIDES:
            parts.append(sphere(J[f"{side}_shoulder"] + Vector((0.015 * s, 0, 0)), 0.06, blue, scale=(1, 1, 0.8)))
        return parts

    def cape():
        mesh = bpy.data.meshes.new("cape")
        bm = bmesh.new()
        rows, cols = 14, 16
        grid = []
        for i in range(rows + 1):
            k = i / rows
            z = 0.9 - k * 0.62
            half = 0.17 + k * 0.17
            grid.append([bm.verts.new(((j / cols * 2 - 1) * half, 0.07 + 0.025 * k * math.sin(j / cols * math.pi * 6), z))
                         for j in range(cols + 1)])
        for i in range(rows):
            for j in range(cols):
                bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
        bm.to_mesh(mesh)
        bm.free()
        o = bpy.data.objects.new("cape", mesh)
        bpy.context.scene.collection.objects.link(o)
        o.modifiers.new("Solid", "SOLIDIFY").thickness = 0.008
        return [finish(o, red), ring((0, 0.04, 0.9), 1, 0.02, red, scale=(0.16, 0.08, 1))]

    pieces = [("mask", mask, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("cape", cape, ["l_shoulder", "r_shoulder", "mid_hip"],
               {"layer": "behind", "swing": {"from": "l_shoulder", "sway": 0.05}}),
              ("suit", suit, ["l_shoulder", "r_shoulder", "mid_hip"], {})]
    for side, _ in SIDES:
        pieces += [(f"{side}_glove", lambda side=side: glove(side, red), [f"{side}_elbow", f"{side}_wrist"], {}),
                   (f"{side}_boot", lambda side=side: boot(side, red, top=0.3, cuff=gold), [f"{side}_knee", f"{side}_ankle"], {})]
    return "SUPERHERO", pieces, city


def astronaut():
    white = mat("suit_white", (0.92, 0.92, 0.9), rough=0.55)
    orange = mat("orange", (1.0, 0.45, 0.05), rough=0.5)
    grey = mat("grey", (0.35, 0.36, 0.4), rough=0.5)
    glass = mat("glass", (0.7, 0.85, 1.0), rough=0.05, alpha=0.22)
    lights = [mat(f"led{i}", c, emit=4.0) for i, c in enumerate(((1, 0.1, 0.1), (0.1, 1, 0.2), (0.2, 0.5, 1)))]

    def helmet():
        return [sphere(HEAD + Vector((0, -0.005, 0.0)), 0.165, glass, segs=48),
                ring(HEAD + Vector((0, 0, -0.135)), 0.12, 0.028, white),
                box(HEAD + Vector((0.15, 0.0, 0.05)), (0.03, 0.05, 0.05), white, bevel=0.008),
                sphere(HEAD + Vector((0.168, -0.02, 0.06)), 0.012, lights[1])]

    def suit():
        parts = [torso_shell(white, width=0.18, depth=0.11), ring((0, 0, 0.6), 1, 0.016, orange, scale=(0.17, 0.105, 1)),
                 box((0, -0.115, 0.76), (0.13, 0.025, 0.09), grey, bevel=0.01)]
        for i, led in enumerate(lights):
            parts.append(sphere((-0.04 + 0.04 * i, -0.13, 0.78), 0.012, led))
        parts.append(box((0.1, -0.1, 0.84), (0.05, 0.01, 0.035), mat("flag", (0.1, 0.2, 0.75)), bevel=0.003))
        for side, s in SIDES:
            parts.append(sphere(J[f"{side}_shoulder"] + Vector((0.02 * s, 0, 0)), 0.068, white, scale=(1, 1, 0.85)))
        return parts

    def sleeve(a, b):
        return lambda: [tube(J[a], J[b], 0.058, 0.052, white), ring(J[b], 0.052, 0.012, orange,
                                                                    rot=(J[b] - J[a]).to_track_quat("Z", "Y").to_euler())]

    pieces = [("helmet", helmet, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("suit", suit, ["l_shoulder", "r_shoulder", "mid_hip"], {})]
    for side, _ in SIDES:
        pieces += [(f"{side}_upper", sleeve(f"{side}_shoulder", f"{side}_elbow"), [f"{side}_shoulder", f"{side}_elbow"], {}),
                   (f"{side}_lower", sleeve(f"{side}_elbow", f"{side}_wrist"), [f"{side}_elbow", f"{side}_wrist"], {}),
                   (f"{side}_glove", lambda side=side: glove(side, white, cuff=orange, r=0.05), [f"{side}_elbow", f"{side}_wrist"], {}),
                   (f"{side}_boot", lambda side=side: boot(side, white, top=0.22, sole=grey, r=0.06, cuff=orange),
                    [f"{side}_knee", f"{side}_ankle"], {})]
    return "ASTRONAUT", pieces, space


def pirate():
    black = mat("black", (0.04, 0.04, 0.05), rough=0.6)
    red = mat("coat_red", (0.6, 0.04, 0.06), rough=0.6)
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.3)
    white = mat("white", (0.95, 0.95, 0.95), rough=0.4)
    brown = mat("leather", (0.32, 0.17, 0.06), rough=0.6)
    steel = mat("steel", (0.5, 0.52, 0.57), metal=0.9, rough=0.42)

    def hat():
        top = HEAD + Vector((0, 0, 0.075))
        parts = [tube(top, top + Vector((0, 0, 0.1)), 0.1, 0.085, black),
                 sphere(top + Vector((0, 0, 0.012)), 0.17, black, scale=(1.3, 0.85, 0.12)),
                 ring(top + Vector((0, 0, 0.02)), 1, 0.008, gold, scale=(0.215, 0.14, 1)),
                 sphere(top + Vector((0, -0.088, 0.055)), 0.022, white, scale=(1, 0.5, 1))]
        for dx in (-0.008, 0.008):
            parts.append(sphere(top + Vector((dx, -0.1, 0.058)), 0.005, black))
        eye = J["r_eye"]
        parts.append(tube(eye + Vector((0, -0.012, 0)), eye + Vector((0, -0.004, 0)), 0.024, 0.024, black))
        parts.append(box(HEAD + Vector((0, -0.086, 0.04)), (0.19, 0.004, 0.006), black, bevel=0.001, rot=(0, -0.45, 0)))
        return parts

    def coat():
        parts = [robe(red, top=0.9, bottom=0.36, r_top=0.165, r_bottom=0.23),
                 box((0, -0.15, 0.68), (0.07, 0.04, 0.42), white, bevel=0.01),
                 box((0, -0.19, 0.6), (0.34, 0.03, 0.045), black, bevel=0.005),
                 box((0, -0.207, 0.6), (0.05, 0.01, 0.05), gold, bevel=0.004)]
        for side, s in SIDES:
            for i in range(4):
                parts.append(sphere((0.05 * s, -0.175, 0.82 - i * 0.07), 0.009, gold))
            parts.append(box(J[f"{side}_shoulder"] + Vector((0.02 * s, -0.02, 0.02)), (0.08, 0.06, 0.02), gold, bevel=0.006))
        return parts

    def cutlass():
        blade, tip, d = held_rod("r", 0.38, 0.011, steel, back=0.0)
        blade.scale = (2.5, 0.5, 1)
        bend = blade.modifiers.new("Bend", "SIMPLE_DEFORM")
        bend.deform_method, bend.angle = "BEND", math.radians(25)
        h = hand("r")
        return [blade, ring(h, 0.04, 0.007, gold, rot=d.to_track_quat("Y", "Z").to_euler()),
                tube(h - d * 0.08, h, 0.015, 0.015, brown, 16)]

    pieces = [("hat", hat, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("coat", coat, ["l_shoulder", "r_shoulder", "mid_hip"], {"swing": {"from": "mid_hip", "sway": 0.01}}),
              ("cutlass", cutlass, ["r_elbow", "r_wrist"], {"sparkle": True})]
    for side, _ in SIDES:
        pieces.append((f"{side}_boot", lambda side=side: boot(side, black, top=0.3, cuff=brown), [f"{side}_knee", f"{side}_ankle"], {}))
    return "PIRATE", pieces, ship


def royal():
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.25)
    purple = mat("purple", (0.42, 0.08, 0.6), rough=0.45)
    fur = mat("fur", (0.97, 0.96, 0.92), rough=0.9)
    gems = [mat(f"gem{i}", c, emit=1.5, rough=0.1) for i, c in enumerate(((1, 0.1, 0.25), (0.2, 0.5, 1), (0.2, 1, 0.4)))]
    starlight = mat("starlight", (1.0, 0.85, 0.3), metal=0.5, emit=2.0)

    def crown():
        base = HEAD + Vector((0, 0, 0.085))
        parts = [tube(base, base + Vector((0, 0, 0.045)), 0.092, 0.095, gold)]
        for i in range(7):
            a = math.pi * (0.2 + 0.6 * i / 6)
            p = base + Vector((math.cos(a) * 0.093, -math.sin(a) * 0.093, 0.045))
            parts.append(tube(p, p + Vector((0, 0, 0.05)), 0.016, 0.0, gold, 12))
            parts.append(sphere(p + Vector((0, -0.006, 0.054)), 0.009, gold))
            if i % 2 == 0:
                parts.append(sphere(base + Vector((math.cos(a) * 0.097, -math.sin(a) * 0.097, 0.022)), 0.011, gems[i // 2 % 3]))
        return parts

    def gown():
        parts = [robe(purple, top=0.9, bottom=0.28, r_top=0.165, r_bottom=0.32),
                 ring((0, 0, 0.9), 1, 0.04, fur, scale=(0.17, 0.11, 1)),
                 ring((0, 0, 0.6), 1, 0.012, gold, scale=(0.2, 0.15, 1)),
                 sphere((0, -0.13, 0.78), 0.03, gold, scale=(1, 0.4, 1)), sphere((0, -0.143, 0.78), 0.013, gems[0])]
        for side, s in SIDES:
            parts.append(box((0.03 * s, -0.2, 0.55), (0.04, 0.03, 0.55), fur, bevel=0.012,
                             rot=(math.radians(-10), math.radians(9 * s), 0)))
        return parts

    def wand():
        rod, tip, d = held_rod("r", 0.25, 0.008, gold, back=0.04)
        return [rod, flat(star(), tip + d * 0.05, 0.015, starlight, scale=0.055)]

    pieces = [("crown", crown, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("gown", gown, ["l_shoulder", "r_shoulder", "mid_hip"],
               {"swing": {"from": "mid_hip", "sway": 0.012, "flare": True}}),
              ("wand", wand, ["r_elbow", "r_wrist"], {"sparkle": True})]
    return "ROYAL", pieces, ballroom


def wizard():
    blue = mat("wiz_blue", (0.12, 0.12, 0.55), rough=0.6)
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.3)
    beard = mat("beard", (0.95, 0.95, 0.95), rough=0.95)
    wood = mat("wood", (0.35, 0.2, 0.08), rough=0.8)
    orb = mat("orb", (0.4, 0.8, 1.0), emit=5.0, alpha=0.85)

    brim = HEAD + Vector((0, 0, 0.07))

    def hat_top():
        parts = [tube(brim, brim + Vector((0, 0.02, 0.34)), 0.13, 0.0, blue, 48)]
        for i, (x, z) in enumerate(((-0.05, 0.08), (0.04, 0.15), (-0.01, 0.23))):
            parts.append(flat(star(), brim + Vector((x, -0.11 + z * 0.33, z)), 0.006, gold, scale=0.022 - 0.004 * i))
        return parts

    def hat():
        parts = [sphere(brim, 0.21, blue, scale=(1, 1, 0.07)),
                 ring(brim + Vector((0, 0, 0.02)), 0.128, 0.012, gold)]
        chin = HEAD + Vector((0, -0.075, -0.05))
        parts.append(tube(chin, chin + Vector((0, -0.01, -0.2)), 0.075, 0.0, beard))
        for side, s in SIDES:
            parts.append(sphere(HEAD + Vector((0.03 * s, -0.093, -0.03)), 0.025, beard, scale=(1.4, 0.7, 0.6)))
        return parts

    def robe_piece():
        moon = [(math.cos(a), math.sin(a)) for a in [math.pi * (0.25 + 1.5 * i / 20) for i in range(21)]]
        moon += [(0.35 + 0.7 * math.cos(a), 0.7 * math.sin(a)) for a in [math.pi * (1.65 - 1.3 * i / 20) for i in range(21)]]
        return [robe(blue, top=0.9, bottom=0.28, r_top=0.165, r_bottom=0.3),
                ring((0, 0, 0.62), 1, 0.012, gold, scale=(0.2, 0.15, 1)),
                flat(moon, (0.05, -0.17, 0.76), 0.008, gold, scale=0.045),
                flat(star(), (-0.06, -0.19, 0.5), 0.008, gold, scale=0.03),
                flat(star(), (0.08, -0.22, 0.42), 0.008, gold, scale=0.025)]

    def staff():
        h = hand("r")
        return [tube(h + Vector((0, 0, -0.5)), h + Vector((0, 0, 0.42)), 0.016, 0.019, wood, 16),
                sphere(h + Vector((0, 0, 0.47)), 0.05, orb),
                ring(h + Vector((0, 0, 0.42)), 0.03, 0.008, gold)]

    pieces = [("hat_top", hat_top, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3, "bob": brim + Vector((0, 0, 0.03))}),
              ("hat", hat, ["l_ear", "r_ear"], {"yaw": True, "min_vis": 0.3}),
              ("robe", robe_piece, ["l_shoulder", "r_shoulder", "mid_hip"],
               {"swing": {"from": "mid_hip", "sway": 0.012, "flare": True}}),
              ("staff", staff, ["r_elbow", "r_wrist"], {"rotate": 0.0, "sparkle": True})]
    return "WIZARD", pieces, forest


COSTUMES = {"knight": knight, "superhero": superhero, "astronaut": astronaut, "pirate": pirate,
            "royal": royal, "wizard": wizard}


# ---------------------------------------------------------------- scenes (backdrops)

def sky(top, bottom, strength=1.0):
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    if world.node_tree is None:
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    coord, mapping = nt.nodes.new("ShaderNodeTexCoord"), nt.nodes.new("ShaderNodeMapping")
    grad, ramp = nt.nodes.new("ShaderNodeSeparateXYZ"), nt.nodes.new("ShaderNodeValToRGB")
    bg, out = nt.nodes.new("ShaderNodeBackground"), nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    nt.links.new(mapping.outputs["Vector"], grad.inputs["Vector"])
    nt.links.new(grad.outputs["Z"], ramp.inputs["Fac"])
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.45, 0.75
    ramp.color_ramp.elements[0].color = (*bottom, 1)
    ramp.color_ramp.elements[1].color = (*top, 1)
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = strength
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bpy.context.scene.world = world


def sun(direction, energy=3.0, color=(1, 1, 1)):
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy, data.color = energy, color
    o = bpy.data.objects.new("Sun", data)
    bpy.context.scene.collection.objects.link(o)
    o.rotation_euler = Vector(direction).to_track_quat("-Z", "Y").to_euler()


def point(loc, energy, color, radius=0.5):
    data = bpy.data.lights.new("Point", "POINT")
    data.energy, data.color, data.shadow_soft_size = energy, color, radius
    o = bpy.data.objects.new("Point", data)
    bpy.context.scene.collection.objects.link(o)
    o.location = loc


def ground(color, size=80, z=0.0, rough=0.8):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, size / 2 - 6, z))
    return finish(bpy.context.active_object, mat(f"ground{color}", color, rough=rough), smooth=False)


def stars(n, spread, z0, z1, y, rng):
    m = mat("star", (1, 1, 0.95), emit=8)
    for _ in range(n):
        sphere((rng.uniform(-spread, spread), y, rng.uniform(z0, z1)), rng.uniform(0.02, 0.05), m, segs=8)


def castle(rng):
    sky((0.25, 0.5, 0.95), (0.75, 0.88, 1.0))
    sun((-0.4, 1, -0.6), 2.2, (1, 0.96, 0.88))
    ground((0.2, 0.55, 0.15))
    stone, roof = mat("stone", (0.55, 0.53, 0.5), rough=0.9), mat("roof", (0.7, 0.12, 0.1), rough=0.6)
    box((0, 14, 2.2), (30, 1.5, 4.4), stone, bevel=0)
    for i in range(-15, 16):
        box((i * 1.0, 14, 4.65), (0.55, 1.5, 0.5), stone, bevel=0)
    for x in (-9, 9, -3.5, 3.5):
        tall = 7 if abs(x) > 5 else 5.5
        tube((x, 13, 0), (x, 13, tall), 1.4, 1.4, stone, 24)
        tube((x, 13, tall), (x, 13, tall + 2.6), 1.7, 0.0, roof, 24)
        box((x + 0.4, 12.9, tall + 3.0), (0.8, 0.05, 0.45), mat("flagc", (0.1, 0.25, 0.8)), bevel=0)
        tube((x, 13, tall + 2.4), (x, 13, tall + 3.3), 0.04, 0.04, stone, 8)
    box((0, 13.2, 1.3), (2.4, 0.4, 2.6), mat("door", (0.3, 0.17, 0.07)), bevel=0)
    cloud = mat("cloud", (1, 1, 1), rough=1)
    for cx, cz in ((-10, 9.5), (6, 10.5), (12, 8.5)):
        for k in range(5):
            sphere((cx + k * 0.9, 18, cz + rng.uniform(-0.3, 0.3)), rng.uniform(0.8, 1.3), cloud, segs=16)


def city(rng):
    sky((0.03, 0.04, 0.15), (0.2, 0.15, 0.4))
    sun((0.3, 1, -0.5), 0.6, (0.6, 0.6, 1.0))
    stars(150, 25, 6, 16, 30, rng)
    sphere((9, 29, 12), 1.6, mat("moon", (1, 0.97, 0.85), emit=3), segs=24)
    ground((0.12, 0.12, 0.16))
    win = [mat(f"win{i}", c, emit=4) for i, c in enumerate(((1, 0.85, 0.45), (0.6, 0.85, 1.0)))]
    for i in range(22):
        x = -16 + i * 1.5 + rng.uniform(-0.2, 0.2)
        h, w, y = rng.uniform(3, 11), rng.uniform(1.0, 1.4), rng.uniform(10, 16)
        box((x, y, h / 2), (w, 1.2, h), mat(f"bld{i % 3}", (0.08 + 0.03 * (i % 3), 0.08, 0.14)), bevel=0)
        for wz in range(1, int(h / 0.7)):
            for wx in (-0.25, 0.25):
                if rng.random() < 0.55:
                    box((x + wx * w, y - 0.61, wz * 0.7), (0.18, 0.02, 0.28), win[rng.random() < 0.3], bevel=0)


def space(rng):
    sky((0, 0, 0.02), (0.02, 0.01, 0.06), 0.3)
    sun((-0.6, 1, -0.3), 4.0)
    stars(400, 30, 0.5, 18, 35, rng)
    rock = mat("moonrock", (0.5, 0.5, 0.52), rough=1)
    ground((0.45, 0.45, 0.47))
    for _ in range(14):
        x, y = rng.uniform(-8, 8), rng.uniform(1, 9)
        ring((x, y, 0.02), rng.uniform(0.3, 0.9), 0.08, rock, scale=(1, 0.6, 0.4))
    planet = mat("earth", (0.15, 0.4, 0.9), emit=0.4, rough=0.6)
    sphere((-7, 28, 10), 3.0, planet, segs=32)
    land = mat("land", (0.2, 0.7, 0.25), rough=0.8)
    for _ in range(6):
        sphere((-7 + rng.uniform(-2, 2), 26.5, 10 + rng.uniform(-2, 2)), rng.uniform(0.6, 1.1), land, scale=(1, 0.3, 0.7), segs=16)
    sphere((10, 30, 7), 1.6, mat("ringed", (0.9, 0.6, 0.3), rough=0.6), segs=32)
    ring((10, 30, 7), 2.6, 0.25, mat("rings", (0.85, 0.75, 0.55), rough=0.6), rot=(1.2, 0.3, 0), scale=(1, 1, 0.1))


def ship(rng):
    sky((0.35, 0.6, 0.95), (0.95, 0.85, 0.7))
    sun((0.5, 1, -0.35), 3.2, (1, 0.9, 0.75))
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 90, -0.6))
    finish(bpy.context.active_object, mat("sea", (0.05, 0.3, 0.55), rough=0.15), smooth=False)
    plank = [mat(f"plank{i}", (0.42 + 0.05 * i, 0.26 + 0.03 * i, 0.12), rough=0.8) for i in range(3)]
    for i in range(30):
        box((i * 0.5 - 7.5, 4, 0), (0.48, 14, 0.1), plank[i % 3], bevel=0.01)
    for x in range(-8, 9):
        tube((x, 7, 0), (x, 7, 1.0), 0.06, 0.06, plank[1], 12)
    box((0, 7, 1.0), (17, 0.15, 0.12), plank[2], bevel=0.02)
    tube((4.5, 9, 0), (4.5, 9, 12), 0.25, 0.18, plank[0], 16)
    sail = mat("sail", (0.96, 0.93, 0.85), rough=0.9)
    box((4.5, 8.6, 7.5), (5.5, 0.08, 5.5), sail, bevel=0.1)
    box((4.5, 8.7, 12.2), (1.2, 0.05, 0.8), mat("jolly", (0.05, 0.05, 0.05)), bevel=0)
    cloud = mat("cloud", (1, 1, 1), rough=1)
    for cx in (-10, -3, 12):
        for k in range(4):
            sphere((cx + k * 1.1, 40, 9 + rng.uniform(-0.4, 0.4)), rng.uniform(1.0, 1.6), cloud, segs=16)


def ballroom(rng):
    sky((0.45, 0.2, 0.4), (0.6, 0.3, 0.45), 0.6)
    sun((0, 1, -0.7), 1.2, (1, 0.9, 0.85))
    ground((0.85, 0.75, 0.6), rough=0.25)
    box((0, 0.5, 0.01), (2.6, 14, 0.02), mat("carpet", (0.7, 0.05, 0.1), rough=0.9), bevel=0)
    wall = mat("wall", (0.75, 0.55, 0.75), rough=0.7)
    box((0, 12, 5), (30, 0.5, 10), wall, bevel=0)
    gold = mat("gold", (1.0, 0.72, 0.2), metal=1.0, rough=0.25)
    marble = mat("marble", (0.95, 0.93, 0.9), rough=0.3)
    for x in (-8, -4.5, 4.5, 8):
        tube((x, 10, 0), (x, 10, 8), 0.45, 0.45, marble, 24)
        box((x, 10, 8.1), (1.2, 1.2, 0.3), gold, bevel=0.02)
    window = mat("window", (0.6, 0.75, 1.0), emit=1.5)
    for x in (-6.2, 0, 6.2):
        box((x, 11.7, 4.5), (1.6, 0.1, 3.2), window, bevel=0)
        sphere((x, 11.7, 6.1), 0.8, window, scale=(1, 0.06, 1), segs=24)
    ring((0, 6, 8), 1.2, 0.06, gold)
    glow = mat("candle", (1, 0.85, 0.5), emit=6)
    for i in range(10):
        a = i / 10 * math.tau
        sphere((math.cos(a) * 1.2, 6 + math.sin(a) * 1.2, 8.15), 0.09, glow, segs=12)
    point((0, 6, 7.5), 400, (1, 0.85, 0.6), 1.0)


def forest(rng):
    sky((0.05, 0.03, 0.2), (0.3, 0.15, 0.4), 0.8)
    sun((0.2, 1, -0.6), 0.8, (0.6, 0.6, 1.0))
    stars(120, 25, 7, 16, 30, rng)
    sphere((-8, 28, 12), 1.5, mat("moon", (1, 0.97, 0.85), emit=3), segs=24)
    ground((0.08, 0.2, 0.12))
    trunk = mat("trunk", (0.25, 0.14, 0.06), rough=0.9)
    leaves = [mat(f"leaf{i}", (0.05, 0.25 + 0.08 * i, 0.15), rough=0.8) for i in range(3)]
    for i in range(18):
        x, y = rng.uniform(-14, 14), rng.uniform(6, 18)
        if abs(x) < 2.5 and y < 9:
            continue
        h = rng.uniform(3, 6)
        tube((x, y, 0), (x, y, h * 0.3), 0.25, 0.2, trunk, 12)
        for k in range(3):
            tube((x, y, h * (0.25 + 0.22 * k)), (x, y, h * (0.62 + 0.22 * k)), 1.4 - 0.35 * k, 0.0, leaves[k], 16)
    cap = [mat(f"cap{i}", c, emit=3) for i, c in enumerate(((0.3, 0.9, 1.0), (1.0, 0.4, 0.9)))]
    for _ in range(14):
        x, y = rng.uniform(-6, 6), rng.uniform(1, 6)
        tube((x, y, 0), (x, y, 0.25), 0.05, 0.05, mat("stem", (0.9, 0.9, 0.8)), 8)
        sphere((x, y, 0.27), 0.16, cap[rng.random() < 0.5], scale=(1, 1, 0.55), segs=16)
    fly = mat("firefly", (1, 1, 0.5), emit=10)
    for _ in range(40):
        sphere((rng.uniform(-8, 8), rng.uniform(2, 10), rng.uniform(0.5, 4)), 0.04, fly, segs=8)


# ---------------------------------------------------------------- rendering

def setup_render():
    scene = bpy.context.scene
    engines = {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    scene.render.engine = next(e for e in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH") if e in engines)
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 16
    scene.view_settings.view_transform = "Standard"
    cam = bpy.data.objects.get("Cam") or bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    if cam.name not in scene.collection.objects:
        scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def studio():
    """Lights for the pieces: soft key from the front-left, fill, a little rim; plain grey world."""
    clear(keep_lights=False)
    world = bpy.data.worlds.get("Studio") or bpy.data.worlds.new("Studio")
    if world.node_tree is None:
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.55, 0.55, 0.6, 1)
    bg.inputs["Strength"].default_value = 0.6
    bpy.context.scene.world = world
    for name, energy, loc in (("Key", 110, (-1.2, -2.5, 2.4)), ("Fill", 45, (1.6, -2.2, 1.0)), ("Rim", 80, (0, 2.5, 2.0))):
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.size = energy, 1.5
        o = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector((0, 0, 0.7)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()


def bounds(objs):
    deps = bpy.context.evaluated_depsgraph_get()
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for o in objs:
        ev = o.evaluated_get(deps)
        for c in ev.bound_box:
            w = ev.matrix_world @ Vector(c)
            lo, hi = Vector(map(min, lo, w)), Vector(map(max, hi, w))
    return lo, hi


def front_camera(cam, objs, size, margin=1.08):
    """Orthographic camera looking at the objects from the front, framing them tightly."""
    bpy.context.view_layer.update()
    lo, hi = bounds(objs)
    w, h = (hi.x - lo.x) * margin, (hi.z - lo.z) * margin
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(w, h)
    cam.location = ((lo.x + hi.x) / 2, lo.y - 3, (lo.z + hi.z) / 2)
    cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.clip_end = 20
    scene = bpy.context.scene
    scene.render.resolution_x = max(8, round(size * w / max(w, h)))
    scene.render.resolution_y = max(8, round(size * h / max(w, h)))
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.compression = 100


def px(cam, p):
    scene = bpy.context.scene
    v = world_to_camera_view(scene, cam, Vector(p))
    return [round(v.x * scene.render.resolution_x, 1), round((1 - v.y) * scene.render.resolution_y, 1)]


def render_to(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def turn(objs, degrees):
    """Turn a head piece about the head's vertical axis (yaw); returns the matching transform."""
    rot = Matrix.Translation(HEAD) @ Matrix.Rotation(math.radians(degrees), 4, "Z") @ Matrix.Translation(-HEAD)
    for o in objs:
        o.matrix_world = rot @ o.matrix_world
    return rot


def render_costume(key, out, size, cam, scenes):
    title, pieces, scene_fn = COSTUMES[key]()
    folder = out / key
    folder.mkdir(parents=True, exist_ok=True)
    meta = {"version": 1, "name": title, "scene": "scene.jpg", "pieces": []}
    for name, build, anchors, opts in pieces:
        views = []
        for degrees in ((0, YAW, -YAW) if opts.get("yaw") else (0,)):
            studio()
            objs = [o for o in _flatten(build()) if o is not None]
            rot = turn(objs, degrees) if degrees else Matrix.Identity(4)
            front_camera(cam, objs, size)
            suffix = "" if not degrees else ("_a" if degrees > 0 else "_b")
            file = f"{name}{suffix}.png"
            render_to(folder / file)
            pts = {a: px(cam, rot @ J[a] if a in ("l_ear", "r_ear", "nose", "l_eye", "r_eye") else J[a]) for a in anchors}
            view = {"file": file, "size": [bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y],
                    "anchors": pts}
            if opts.get("yaw"):
                nose, l, r = px(cam, rot @ J["nose"]), px(cam, rot @ J["l_ear"]), px(cam, rot @ J["r_ear"])
                sl, sr = px(cam, J["l_shoulder"]), px(cam, J["r_shoulder"])
                view["ratio"] = round((nose[0] - (l[0] + r[0]) / 2) / math.dist(sl, sr), 3)
                view["scale_ref"] = {"l_shoulder": sl, "r_shoulder": sr}  # steadies the size (ears wobble)
            if "bob" in opts:    # wobbles about this point (its base)
                view["pivot"] = px(cam, rot @ opts["bob"])
            if "swing" in opts:  # rows below this swing and trail behind the body
                view["swing_y"] = px(cam, J[opts["swing"]["from"]])[1]
            views.append(view)
        piece = {"name": name, "layer": opts.get("layer", "front"), "views": views}
        for k in ("min_vis", "rotate", "sparkle"):
            if k in opts:
                piece[k] = opts[k]
        if "bob" in opts:
            piece["bob"] = True
        if "swing" in opts:
            piece["swing"] = {k: v for k, v in opts["swing"].items() if k != "from"}
        meta["pieces"].append(piece)
        print(f"  {key}/{name}: {len(views)} view(s)")
    render_preview(pieces, folder, cam)
    if scenes:
        render_scene(scene_fn, folder / "scene.jpg", cam)
    (folder / "costume.json").write_text(json.dumps(meta, indent=1) + "\n")
    # behind pieces first, so the game can draw in file order
    return title


def _flatten(items):
    for i in items:
        if isinstance(i, (list, tuple)):
            yield from _flatten(i)
        else:
            yield i


def mannequin():
    skin = mat("mannequin", (0.62, 0.66, 0.74), rough=0.6)
    parts = [sphere(HEAD, 0.095, skin, scale=(0.92, 1, 1.08)), tube(J["neck"] - Vector((0, 0, 0.05)), J["neck"], 0.04, 0.04, skin),
             torso_shell(skin, width=0.14, depth=0.085, bottom=0.55, top=0.9)]
    for side, _ in SIDES:
        parts += [tube(J[f"{side}_shoulder"], J[f"{side}_elbow"], 0.04, 0.035, skin),
                  tube(J[f"{side}_elbow"], J[f"{side}_wrist"], 0.034, 0.03, skin),
                  sphere(hand(side), 0.035, skin), tube(J[f"{side}_hip"], J[f"{side}_knee"], 0.055, 0.045, skin),
                  tube(J[f"{side}_knee"], J[f"{side}_ankle"], 0.044, 0.035, skin),
                  box(J[f"{side}_ankle"] + Vector((0, -0.04, -0.035)), (0.07, 0.13, 0.05), skin, bevel=0.015)]
    return parts


def render_preview(pieces, folder, cam):
    studio()
    objs = mannequin()
    for _, build, _, _ in pieces:
        objs += [o for o in _flatten(build()) if o is not None]
    front_camera(cam, objs, 384, margin=1.05)
    render_to(folder / "preview.png")


def render_scene(scene_fn, path, cam):
    clear(keep_lights=False)
    scene_fn(random.Random(4))
    cam.data.type = "PERSP"
    cam.data.lens = 22
    cam.data.clip_end = 300
    cam.location = (0, -6, 1.4)
    cam.rotation_euler = (math.radians(92), 0, 0)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.quality = 85
    render_to(path)


def main():
    args = parse_args()
    out = Path(args.out).resolve()
    keys = [k.strip() for k in args.only.split(",") if k.strip()] or list(COSTUMES)
    clear(keep_lights=False)
    cam = setup_render()
    for key in keys:
        print(f"{key}:")
        render_costume(key, out, args.size, cam, not args.no_scenes)
    total = sum(p.stat().st_size for k in keys for p in (out / k).iterdir())
    print(f"Wrote {len(keys)} costume(s) to {out}, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
