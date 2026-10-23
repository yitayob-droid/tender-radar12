"""Build Stormfall's 3D assets in Blender and embed them in games/stormfall.html.

Run with Blender's Python module (pip install bpy) or Blender itself:
    python games/assets/build_assets.py
    blender -b -P games/assets/build_assets.py

Blender axes: Z is up and +Y is "forward". The glTF exporter converts to three.js
axes (Y up, forward = -Z). Character parts keep their joint as the object origin
so the game can rotate legs and arms around hips and shoulders.

Material names matter: the game recolours "Suit", "Skin", "GliderCloth", "Leaf"
and "Rarity" per character, tree or weapon, and makes "ChestWood" glow.
"""
import base64
import math
import os
import random
import re

import bpy  # must come first: it makes bmesh and mathutils importable
import bmesh
from mathutils import Vector, noise

HERE = os.path.dirname(os.path.abspath(__file__))
GLB = os.path.join(HERE, "stormfall.glb")
HTML = os.path.join(HERE, "..", "stormfall.html")

random.seed(11)
bpy.ops.wm.read_factory_settings(use_empty=True)

# ---------------------------------------------------------------- helpers
MATS = {}


def mat(name, hexcol, rough=0.85):
    """Colours are given as display (sRGB) hex; the game uses the factor as-is."""
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    r, g, b = ((hexcol >> 16) & 255) / 255, ((hexcol >> 8) & 255) / 255, (hexcol & 255) / 255
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
    bsdf.inputs["Roughness"].default_value = rough
    m.diffuse_color = (r, g, b, 1)
    MATS[name] = m
    return m


ADD = {
    "cube": bpy.ops.mesh.primitive_cube_add,
    "cyl": bpy.ops.mesh.primitive_cylinder_add,
    "cone": bpy.ops.mesh.primitive_cone_add,
    "ico": bpy.ops.mesh.primitive_ico_sphere_add,
    "uv": bpy.ops.mesh.primitive_uv_sphere_add,
    "torus": bpy.ops.mesh.primitive_torus_add,
}


def prim(kind, loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1), m=None, **kw):
    if kind == "cube":
        kw.setdefault("size", 1)
    ADD[kind](location=loc, rotation=rot, **kw)
    o = bpy.context.active_object
    o.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if m is not None:
        o.data.materials.append(m)
    return o


def activate(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def modify(o, kind, **props):
    activate(o)
    md = o.modifiers.new("m", kind)
    for k, v in props.items():
        setattr(md, k, v)
    bpy.ops.object.modifier_apply(modifier=md.name)
    return o


def bevel(o, w=0.02, seg=2):
    return modify(o, "BEVEL", width=w, segments=seg, limit_method="ANGLE")


def subsurf(o, lvl=1):
    return modify(o, "SUBSURF", levels=lvl, render_levels=lvl)


def shade(o, smooth):
    for p in o.data.polygons:
        p.use_smooth = smooth
    return o


def jitter(o, amt):
    for v in o.data.vertices:
        v.co += Vector([random.uniform(-amt, amt) for _ in range(3)])
    return o


def keep(o, fn):
    """Delete vertices whose world position fails fn."""
    mw = o.matrix_world
    bm = bmesh.new()
    bm.from_mesh(o.data)
    gone = [v for v in bm.verts if not fn(mw @ v.co)]
    bmesh.ops.delete(bm, geom=gone, context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    return o


def join(objs, name, origin=(0, 0, 0)):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    o = bpy.context.active_object
    o.name = o.data.name = name
    bpy.context.scene.cursor.location = origin
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    return o


def box(size, loc, m, rot=(0, 0, 0), bev=0.0, seg=2):
    o = prim("cube", loc=loc, rot=rot, scale=size, m=m)
    if bev:
        bevel(o, bev, seg)
    return o


def rod(r, length, loc, m, axis="z", verts=12):
    rot = {"z": (0, 0, 0), "y": (math.pi / 2, 0, 0), "x": (0, math.pi / 2, 0)}[axis]
    return prim("cyl", loc=loc, rot=rot, m=m, radius=r, depth=length, vertices=verts)


# ---------------------------------------------------------------- materials
SUIT = mat("Suit", 0xFF7A1A)
SKIN = mat("Skin", 0xF1C6A1)
PANTS = mat("Pants", 0x2B2E3B)
BOOT = mat("Boot", 0x1C1D24)
GLOVE = mat("Glove", 0x23252F)
ACCENT = mat("Accent", 0xFFD23F)
DARK = mat("Dark", 0x262833)
EYE = mat("Eye", 0x15161C)
WHITE = mat("EyeWhite", 0xF4F4F4)
CLOTH = mat("GliderCloth", 0xFF7A1A)
GUNBODY = mat("GunBody", 0x3A3F4A, 0.5)
GUNDARK = mat("GunDark", 0x1B1D23, 0.5)
WOOD = mat("Wood", 0x7A4D2A)
RARITY = mat("Rarity", 0xC3C9D1, 0.4)
LENS = mat("Lens", 0x6FD3FF, 0.2)
METAL = mat("PickHead", 0x9FB4C8, 0.3)
TRUNK = mat("Trunk", 0x7A5233)
LEAF = mat("Leaf", 0x3A9159)
ROCK = mat("Rock", 0x8B8F96)
CHESTWOOD = mat("ChestWood", 0xB8862B)
CHESTMETAL = mat("ChestMetal", 0x5A3F12, 0.4)
HULL = mat("Hull", 0x5A3FB0, 0.5)
STRIPE = mat("Stripe", 0xFFD23F)
GONDOLA = mat("Gondola", 0x2B2340)
WINDOW = mat("Window", 0x9FE3FF, 0.2)

# ---------------------------------------------------------------- character
# Feet at z=0, facing +Y, roughly 2.25 m tall. Skins are a base body plus
# accessories (Hat_*, Acc_*) the game mixes and recolours per skin.
HAIR = mat("Hair", 0x3B2A1E)
IRIS = mat("Iris", 0x4A7FC0)
MOUTH = mat("Mouth", 0x7A2E2E)
HATMAIN = mat("HatMain", 0xFF7A1A)
HATACC = mat("HatAccent", 0xFFD23F)
VISOR = mat("Visor", 0x2FE0C8, 0.1)
GLOW = mat("Glow", 0xFFC53A)
BUBBLE = mat("Bubble", 0xBFE8FF, 0.05)
SCARF = mat("Scarf", 0xD84A4A)
CAPE = mat("Cape", 0x8A1F2B)


def torso():
    t = box((0.64, 0.36, 0.66), (0, 0, 1.24), SUIT)
    for v in t.data.vertices:  # heroic V: broad chest and shoulders, narrow waist
        if v.co.z > 0:
            v.co.x *= 1.3
            v.co.y *= 1.12
        else:
            v.co.x *= 0.9
    bevel(t, 0.08, 3)
    shade(t, True)
    parts = [t]
    hips = bevel(box((0.56, 0.32, 0.2), (0, 0, 0.82), PANTS), 0.06, 3)
    parts.append(shade(hips, True))
    parts.append(bevel(box((0.6, 0.36, 0.08), (0, 0, 0.93), DARK), 0.025))  # belt
    parts.append(bevel(box((0.12, 0.03, 0.08), (0, 0.19, 0.93), ACCENT), 0.012))  # buckle
    parts.append(box((0.025, 0.02, 0.62), (0, 0.183, 1.26), ACCENT))  # zip
    parts.append(box((0.05, 0.03, 0.06), (0, 0.19, 1.52), ACCENT))  # zip pull
    for x in (-0.16, 0.16):
        parts.append(bevel(box((0.14, 0.025, 0.11), (x, 0.178, 1.07), DARK), 0.01))  # pockets
    parts.append(rod(0.075, 0.025, (0.15, 0.18, 1.4), ACCENT, "y", 16))  # chest badge
    collar = prim("cyl", loc=(0, 0, 1.6), m=SUIT, radius=0.17, depth=0.1, vertices=20)
    parts.append(shade(bevel(collar, 0.03, 2), True))
    return join(parts, "Torso")


def head():
    parts = [shade(rod(0.09, 0.14, (0, 0, 1.67), SKIN, "z", 14), True)]
    h = box((0.5, 0.48, 0.52), (0, 0, 1.93), SKIN)
    subsurf(h, 2)
    parts.append(shade(h, True))
    for x in (-0.092, 0.092):
        parts.append(shade(prim("uv", loc=(x, 0.2, 1.95), scale=(1, 0.7, 1.15), m=WHITE, radius=0.055, segments=14, ring_count=10), True))
        parts.append(shade(prim("uv", loc=(x, 0.232, 1.95), m=IRIS, radius=0.032, segments=12, ring_count=8), True))
        parts.append(shade(prim("uv", loc=(x, 0.252, 1.95), m=EYE, radius=0.017, segments=10, ring_count=6), True))
        parts.append(shade(prim("uv", loc=(x + (0.012 if x > 0 else -0.012), 0.262, 1.962), m=WHITE, radius=0.007, segments=6, ring_count=4), True))
        brow = box((0.1, 0.025, 0.024), (x, 0.222, 2.03), HAIR, rot=(0, -0.18 if x < 0 else 0.18, 0))
        parts.append(bevel(brow, 0.008))
        parts.append(shade(prim("uv", loc=(x * 2.65, 0, 1.93), scale=(0.6, 1, 1), m=SKIN, radius=0.07, segments=10, ring_count=8), True))  # ears
    parts.append(shade(prim("uv", loc=(0, 0.245, 1.89), scale=(0.8, 1, 1), m=SKIN, radius=0.035, segments=10, ring_count=8), True))  # nose
    mouth = box((0.11, 0.02, 0.025), (0, 0.232, 1.82), MOUTH)
    parts.append(bevel(mouth, 0.01))
    # short hair: a skull cap that leaves the forehead clear, plus a fringe
    hair = prim("uv", loc=(0, -0.01, 1.96), scale=(1.0, 1.03, 0.82), m=HAIR, radius=0.27, segments=20, ring_count=12)
    keep(hair, lambda c: c.z > 1.98 and not (c.y > 0.17 and c.z < 2.07))
    parts.append(shade(hair, True))
    for x in (-0.08, 0.0, 0.08):
        tuft = prim("cone", loc=(x, 0.17, 2.11), rot=(1.2, 0, x * 2), m=HAIR, radius1=0.06, radius2=0, depth=0.14, vertices=8)
        parts.append(shade(tuft, True))
    return join(parts, "Head")


def arm(side):
    x = 0.44 * side
    parts = [shade(prim("uv", loc=(x, 0, 1.56), m=SUIT, radius=0.15, segments=16, ring_count=10), True)]
    upper = prim("cone", loc=(x, 0, 1.38), m=SUIT, radius1=0.098, radius2=0.118, depth=0.4, vertices=16)
    parts.append(shade(upper, True))  # thicker at the shoulder, tapering to the elbow
    parts.append(shade(rod(0.1, 0.07, (x, 0, 1.17), ACCENT, "z", 14), True))  # cuff
    fore = prim("cone", loc=(x, 0, 1.02), m=SKIN, radius1=0.075, radius2=0.092, depth=0.28, vertices=14)
    parts.append(shade(fore, True))
    hand = box((0.15, 0.18, 0.18), (x, 0.01, 0.83), GLOVE)
    subsurf(hand, 2)
    parts.append(shade(hand, True))
    thumb = prim("uv", loc=(x - 0.07 * side, 0.06, 0.87), scale=(0.7, 0.7, 1.3), m=GLOVE, radius=0.04, segments=10, ring_count=6)
    parts.append(shade(thumb, True))
    return join(parts, "ArmL" if side < 0 else "ArmR", origin=(x, 0, 1.56))


def leg(side):
    x = 0.16 * side
    parts = [shade(prim("cone", loc=(x, 0, 0.62), m=PANTS, radius1=0.12, radius2=0.145, depth=0.42, vertices=14), True)]
    parts.append(shade(prim("cone", loc=(x, 0, 0.3), m=PANTS, radius1=0.11, radius2=0.125, depth=0.36, vertices=14), True))
    parts.append(shade(bevel(box((0.17, 0.07, 0.15), (x, 0.1, 0.45), ACCENT), 0.03, 2), True))  # knee pad
    parts.append(shade(bevel(box((0.22, 0.34, 0.17), (x, 0.05, 0.085), BOOT), 0.06, 3), True))
    parts.append(box((0.23, 0.36, 0.035), (x, 0.05, 0.017), DARK))  # sole
    for z in (0.12, 0.16):  # laces
        parts.append(box((0.1, 0.02, 0.015), (x, 0.205, z), WHITE))
    return join(parts, "LegL" if side < 0 else "LegR", origin=(x, 0, 0.8))


def accessories():
    # caps and hats sit over the hair; all are modelled in place on the body
    cap = prim("uv", loc=(0, -0.01, 2.04), scale=(1, 1, 0.72), m=HATMAIN, radius=0.29, segments=22, ring_count=12)
    keep(cap, lambda c: c.z > 2.02)
    join([shade(cap, True),
          bevel(box((0.4, 0.24, 0.035), (0, 0.25, 2.04), HATMAIN, rot=(-0.12, 0, 0)), 0.012),
          rod(0.04, 0.02, (0, 0, 2.25), HATACC, "z", 10)], "Hat_Cap")

    bean = prim("uv", loc=(0, 0, 2.0), scale=(1, 1, 0.95), m=HATMAIN, radius=0.295, segments=22, ring_count=12)
    keep(bean, lambda c: c.z > 1.985)
    join([shade(bean, True),
          shade(prim("cyl", loc=(0, 0, 2.02), m=HATACC, radius=0.3, depth=0.09, vertices=22), True),
          shade(prim("uv", loc=(0, 0, 2.31), m=HATACC, radius=0.085, segments=12, ring_count=8), True)], "Hat_Beanie")

    helm = prim("uv", loc=(0, 0, 1.97), scale=(1, 1.06, 0.98), m=HATMAIN, radius=0.335, segments=22, ring_count=14)
    keep(helm, lambda c: c.z > 1.9 and not (c.y > 0.15 and c.z < 2.08))
    visor = prim("uv", loc=(0, 0.005, 1.97), m=VISOR, radius=0.33, segments=22, ring_count=14)
    keep(visor, lambda c: c.y > 0.14 and 1.88 < c.z < 2.08)
    ears = [prim("cyl", loc=(s * 0.33, 0, 1.95), rot=(0, math.pi / 2, 0), m=HATACC, radius=0.095, depth=0.07, vertices=14) for s in (-1, 1)]
    join([shade(helm, True), shade(visor, True)] + [shade(e, True) for e in ears], "Hat_Helmet")

    spikes = []
    random.seed(21)
    for k in range(11):
        a = k / 11 * 2 * math.pi
        r = 0.12 if k % 2 else 0.18
        x, y = math.cos(a) * r, math.sin(a) * r - 0.03
        c = prim("cone", loc=(x, y, 2.17), rot=(-y * 2.2, x * 2.2, 0), m=HATMAIN, radius1=0.085, radius2=0, depth=random.uniform(0.26, 0.36), vertices=8)
        spikes.append(shade(c, True))
    spikes.append(shade(prim("uv", loc=(0, -0.01, 2.06), scale=(1, 1.02, 0.7), m=HATMAIN, radius=0.28, segments=18, ring_count=10), True))
    spikes.append(bevel(box((0.44, 0.04, 0.085), (0, 0.255, 1.96), VISOR), 0.02))  # shades
    join(spikes, "Hat_Spiky")

    k_main = shade(prim("cyl", loc=(0, 0, 1.98), m=HATMAIN, radius=0.3, depth=0.5, vertices=20), True)
    dome = prim("uv", loc=(0, 0, 2.23), m=HATMAIN, radius=0.3, segments=20, ring_count=12)
    keep(dome, lambda c: c.z >= 2.229)
    plume = [shade(prim("uv", loc=(0, -0.05 - i * 0.07, 2.52 - i * 0.05), scale=(0.35, 1, 1), m=HATACC, radius=0.11, segments=10, ring_count=6), True) for i in range(5)]
    join([k_main, shade(dome, True), box((0.36, 0.03, 0.045), (0, 0.3, 1.99), EYE), box((0.04, 0.03, 0.2), (0, 0.3, 1.9), EYE)] + plume, "Hat_Knight")

    pk = prim("uv", loc=(0, 0, 1.95), m=HATMAIN, radius=0.31, segments=32, ring_count=16)
    for v in pk.data.vertices:  # pumpkin ribs
        a = math.atan2(v.co.y, v.co.x)
        f = 1 + 0.07 * math.cos(8 * a)
        v.co.x *= 1.15 * f
        v.co.y *= 1.1 * f
        v.co.z *= 0.88
    face = [shade(pk, True), shade(rod(0.04, 0.16, (0, 0, 2.27), HATACC, "z", 8), True)]
    for x in (-0.11, 0.11):
        face.append(prism("eye", [(x - 0.06, 0.33, 1.97), (x + 0.06, 0.33, 1.97), (x, 0.33, 2.07)], (0, 1, 0), 0.04, GLOW))
    face.append(prism("mouth", [(-0.15, 0.33, 1.87), (-0.08, 0.33, 1.82), (0, 0.33, 1.86), (0.08, 0.33, 1.82), (0.15, 0.33, 1.87), (0, 0.33, 1.78)], (0, 1, 0), 0.04, GLOW))
    join(face, "Hat_Pumpkin")

    join([shade(prim("uv", loc=(0, 0, 1.95), m=BUBBLE, radius=0.37, segments=24, ring_count=14), True),
          shade(prim("cyl", loc=(0, 0, 1.64), m=HATACC, radius=0.3, depth=0.11, vertices=22), True),
          rod(0.012, 0.25, (0.2, -0.05, 2.36), HATACC, "z", 6),
          shade(prim("uv", loc=(0.2, -0.05, 2.49), m=GLOW, radius=0.03, segments=8, ring_count=6), True)], "Hat_Astro")

    band = shade(prim("cyl", loc=(0, 0, 2.04), m=HATMAIN, radius=0.268, depth=0.075, vertices=22), True)
    join([band, shade(prim("uv", loc=(0, -0.27, 2.04), m=HATMAIN, radius=0.05, segments=10, ring_count=6), True),
          box((0.06, 0.02, 0.24), (0.04, -0.29, 1.93), HATMAIN, rot=(0.25, 0.15, 0)),
          box((0.06, 0.02, 0.2), (-0.04, -0.29, 1.95), HATMAIN, rot=(0.3, -0.2, 0))], "Hat_Bandana")

    pack = shade(bevel(box((0.46, 0.2, 0.52), (0, -0.27, 1.25), DARK), 0.06, 3), True)
    straps = [box((0.06, 0.03, 0.5), (x, 0.185, 1.3), DARK) for x in (-0.16, 0.16)]
    join([pack, bevel(box((0.36, 0.06, 0.2), (0, -0.39, 1.14), ACCENT), 0.02),
          shade(rod(0.05, 0.4, (0, -0.27, 1.55), ACCENT, "x", 10), True)] + straps, "Acc_Pack")

    ADD["torus"](location=(0, 0, 1.62), major_radius=0.18, minor_radius=0.06)
    scarf = bpy.context.active_object
    scarf.data.materials.append(SCARF)
    join([shade(scarf, True), bevel(box((0.11, 0.04, 0.36), (0.1, 0.19, 1.44), SCARF, rot=(0.12, 0, 0.1)), 0.02)], "Acc_Scarf")

    plates = []
    for s in (-1, 1):
        pad = prim("uv", loc=(s * 0.45, 0, 1.6), scale=(1.15, 1.15, 0.7), m=HATMAIN, radius=0.17, segments=16, ring_count=10)
        keep(pad, lambda c: c.z > 1.55)
        plates.append(shade(pad, True))
    plates.append(shade(bevel(box((0.5, 0.06, 0.42), (0, 0.19, 1.3), HATMAIN), 0.05, 3), True))
    plates.append(rod(0.05, 0.02, (0, 0.225, 1.33), HATACC, "y", 12))
    join(plates, "Acc_Armor")

    join([bevel(box((0.64, 0.04, 1.15), (0, -0.25, 1.02), CAPE, rot=(0.12, 0, 0)), 0.02),
          box((0.66, 0.06, 0.06), (0, -0.2, 1.58), HATACC)], "Acc_Cape")

    tanks = []
    for x in (-0.11, 0.11):
        tanks.append(shade(rod(0.1, 0.55, (x, -0.28, 1.28), HATACC, "z", 14), True))
        tanks.append(shade(prim("uv", loc=(x, -0.28, 1.56), m=HATACC, radius=0.1, segments=12, ring_count=8), True))
    tanks.append(rod(0.025, 0.3, (0, -0.2, 1.62), DARK, "x", 8))
    join(tanks, "Acc_Tank")


def glider():
    canopy = prim("cyl", loc=(0, 0, 2.0), rot=(math.pi / 2, 0, 0), m=CLOTH, radius=1.7, depth=1.3, vertices=28)
    keep(canopy, lambda c: c.z > 2.0 + 1.7 * 0.55)
    modify(canopy, "SOLIDIFY", thickness=0.05)
    shade(canopy, True)
    parts = [canopy]
    for a in (-0.35, 0, 0.35):  # stripes across the wing
        s = prim("cyl", loc=(0, 0, 2.0), rot=(math.pi / 2, 0, 0), m=ACCENT, radius=1.73, depth=0.14, vertices=28)
        keep(s, lambda c: c.z > 2.0 + 1.73 * 0.55)
        s.location.y = a
        parts.append(shade(s, True))
    for sx in (-1, 1):
        for sy in (-0.5, 0.5):
            top = Vector((sx * 1.15, sy, 3.25))
            bot = Vector((sx * 0.44, 0.0, 1.0))
            mid = (top + bot) / 2
            d = top - bot
            line = rod(0.008, d.length, mid, DARK, "z", 4)
            line.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
            activate(line)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
            parts.append(line)
    return join(parts, "Glider")


LEATHER = mat("Leather", 0x5A3A22, 0.6)
STEEL = mat("Steel", 0xB9C6D2, 0.25)


PICKGLASS = mat("PickGlass", 0x5BC0FF, 0.1)
PICKDEEP = mat("PickGlassDeep", 0x2A78E0, 0.1)
PICKBLACK = mat("PickBlack", 0x1A1C22, 0.3)
PICKBLUE = mat("PickBlue", 0x3FA9FF, 0.3)


def bez(p0, p1, p2, t):
    return p0 * (1 - t) ** 2 + p1 * 2 * t * (1 - t) + p2 * t * t


def loft(name, n, m_ring, frame, mtls, pick_mat=None):
    """Loft a closed tube along a path in the YZ plane. frame(t) -> (centre, r_x, r_side) for t in 0..1;
    a zero radius collapses to a sharp point. pick_mat(face_centre) chooses a material index per face
    (used for the pixel pattern)."""
    cs = [frame(i / n) for i in range(n + 1)]
    bm = bmesh.new()
    rings = []
    for i, (c, rx, rn) in enumerate(cs):
        a = Vector(cs[max(i - 1, 0)][0])
        b2 = Vector(cs[min(i + 1, n)][0])
        tan = (b2 - a).normalized()
        nrm = Vector((0, -tan.z, tan.y)).normalized()
        c = Vector(c)
        rings.append([bm.verts.new(c + Vector((1, 0, 0)) * rx * math.cos(k / m_ring * 2 * math.pi) + nrm * rn * math.sin(k / m_ring * 2 * math.pi))
                      for k in range(m_ring)])
    for i in range(n):
        for k in range(m_ring):
            bm.faces.new((rings[i][k], rings[i][(k + 1) % m_ring], rings[i + 1][(k + 1) % m_ring], rings[i + 1][k]))
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if pick_mat:
        for f in bm.faces:
            f.material_index = pick_mat(f.calc_center_median())
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    for m in mtls:
        me.materials.append(m)
    return shade(o, True)


def pixels(weights, cell=0.042, seed=0):
    """Blocky digital camo: hash a grid cell to a material index."""
    total = sum(weights)

    def pick(c):
        h = (int(math.floor(c.y / cell)) * 73856093) ^ (int(math.floor(c.z / cell)) * 19349663) ^ (int(math.floor(c.x / cell)) * 83492791) ^ seed
        r = (h & 1023) / 1024 * total
        for i, w in enumerate(weights):
            if r < w:
                return i
            r -= w
        return len(weights) - 1
    return pick


def pickaxe_ice():
    """Digital-ice pickaxe: slim black shaft, translucent blue neck and hub with bolts, a long curved
    pixel-glass blade sweeping forward and down, and a short dark back spike. Head points along +Y
    (the character's forward) so the long blade leads the swing."""
    parts = []
    # pommel: glass cap with a dark ring
    parts.append(loft("Pommel", 6, 20, lambda t: ((0, 0, -0.37 + 0.075 * t), 0.037, 0.037), [PICKGLASS, PICKDEEP], pixels([3, 1], 0.03, 5)))
    parts.append(shade(rod(0.039, 0.02, (0, 0, -0.29), PICKBLACK, "z", 20), True))
    # shaft
    parts.append(shade(prim("cone", loc=(0, 0, 0.03), m=PICKBLACK, radius1=0.026, radius2=0.032, depth=0.64, vertices=20), True))
    random.seed(41)
    for z in (-0.2, -0.05, 0.12, 0.24):  # little pixel squares on the shaft
        a = random.uniform(0, 2 * math.pi)
        parts.append(box((0.018, 0.018, 0.026), (math.cos(a) * 0.029, math.sin(a) * 0.029, z), PICKBLUE, rot=(0, 0, a)))
    for z in (0.33, 0.37):
        parts.append(shade(rod(0.037, 0.022, (0, 0, z), PICKBLACK, "z", 20), True))
    # neck: stepped glass sleeve that flares toward the hub
    def neck(t):
        r = 0.04 if t < 0.45 else 0.044 + 0.016 * (t - 0.45) / 0.55
        return (0, 0, 0.38 + 0.25 * t), r, r
    parts.append(loft("Neck", 14, 24, neck, [PICKGLASS, PICKDEEP, PICKBLACK], pixels([6, 2, 1], 0.03, 7)))
    for z in (0.44, 0.54):  # bolts on both sides
        for sx in (-1, 1):
            parts.append(shade(rod(0.017, 0.014, (sx * 0.046, 0, z), PICKBLACK, "x", 14), True))
            for ang in (0.785, -0.785):
                parts.append(box((0.006, 0.026, 0.005), (sx * 0.054, 0, z), PICKGLASS, rot=(ang, 0, 0)))
    # hub with a dark button on top
    parts.append(loft("Hub", 8, 28, lambda t: ((0, 0, 0.62 + 0.16 * t), 0.068, 0.068), [PICKGLASS, PICKDEEP, PICKBLACK], pixels([5, 2, 1], 0.032, 9)))
    parts.append(shade(rod(0.072, 0.018, (0, 0, 0.635), PICKBLACK, "z", 28), True))
    btn = prim("uv", loc=(0, 0, 0.785), scale=(1, 1, 0.7), m=PICKBLACK, radius=0.036, segments=16, ring_count=10)
    parts.append(shade(btn, True))
    # long blade: forward and curving down to a fine point
    P0, P1, P2 = Vector((0, 0.05, 0.71)), Vector((0, 0.5, 0.75)), Vector((0, 0.62, 0.13))
    def blade(t):
        w = 0.078 * (1 - t) ** 0.7
        return bez(P0, P1, P2, t), 0.024 * (1 - t) + 0.003, w
    parts.append(loft("Blade", 36, 12, blade, [PICKGLASS, PICKDEEP, PICKBLACK], pixels([7, 2, 1], 0.045, 3)))
    # back spike: short, dark, angled up, with blue streaks
    Q0, Q1, Q2 = Vector((0, -0.05, 0.71)), Vector((0, -0.24, 0.72)), Vector((0, -0.37, 0.88))
    def spike(t):
        return bez(Q0, Q1, Q2, t), 0.02 * (1 - t) + 0.003, 0.062 * (1 - t) ** 0.8
    parts.append(loft("Spike", 20, 12, spike, [PICKBLACK, PICKBLUE], pixels([3, 1], 0.04, 11)))
    return join(parts, "Pickaxe_Ice")


def pickaxe():
    """Default: tapered ash handle with a knob, ribbed leather grip, steel collar and a curved head
    with a spike in front (+Y, leads the swing) and a broad chisel behind."""
    parts = [shade(prim("cone", loc=(0, 0, 0.2), m=WOOD, radius1=0.042, radius2=0.033, depth=1.04, vertices=20), True)]
    parts.append(shade(prim("uv", loc=(0, 0, -0.33), scale=(1, 1, 0.8), m=GUNDARK, radius=0.058, segments=16, ring_count=10), True))
    parts.append(shade(rod(0.047, 0.32, (0, 0, -0.13), LEATHER, "z", 20), True))
    for k in range(7):  # wrap ridges
        ADD["torus"](location=(0, 0, -0.27 + k * 0.045), major_radius=0.047, minor_radius=0.009, major_segments=20, minor_segments=6)
        t = bpy.context.active_object
        t.data.materials.append(LEATHER)
        parts.append(shade(t, True))
    collar = box((0.11, 0.13, 0.17), (0, 0, 0.7), GUNDARK)
    bevel(collar, 0.025, 3)
    parts.append(shade(collar, True))
    for sx in (-1, 1):
        parts.append(shade(prim("uv", loc=(sx * 0.058, 0, 0.7), m=STEEL, radius=0.018, segments=10, ring_count=6), True))
    parts.append(shade(prim("uv", loc=(0, 0, 0.79), scale=(1, 1, 0.5), m=STEEL, radius=0.045, segments=14, ring_count=8), True))

    def head(t):
        u = t * 2 - 1
        c = Vector((0, u * 0.5, 0.72 - 0.15 * u * u))
        if u >= 0:  # spike tapering to a point
            r = 0.058 * (1 - u) ** 0.85
            return c, r * 0.85, r
        w = 1 + u  # chisel: wide across, thin in the swing plane
        return c, 0.06 * (0.55 + 0.45 * w) + 0.035 * (1 - w), 0.058 * (0.3 + 0.7 * w)
    parts.append(loft("PickHead", 28, 14, head, [STEEL]))
    return join(parts, "Pickaxe")


GOLD = mat("Gold", 0xF4C430, 0.3)
GOLDDEEP = mat("GoldDeep", 0xC8920E, 0.35)
EMBLEM = mat("Emblem", 0x34343B, 0.5)


def slab(name, pts, thick, m, x=0.0, bev=0.01):
    """A bevelled slab from (y, z) outline points, facing the side (X)."""
    o = prism(name, [(x, y, z) for y, z in pts], (1, 0, 0), thick, m)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(o.data)
    bm.free()
    if bev:
        modify(o, "BEVEL", width=bev, segments=2, limit_method="ANGLE", angle_limit=math.radians(30), use_clamp_overlap=True)
    shade(o, True)
    modify(o, "EDGE_SPLIT", split_angle=math.radians(40), use_edge_angle=True, use_edge_sharp=False)
    return o


def pickaxe_gold():
    """Champion: gold staff with a clawed foot, a shield emblem with a dark lightning bolt, winged
    blades front and back, a top spike and a laurel wreath around the emblem."""
    cz = 0.8  # emblem centre
    parts = [shade(rod(0.027, 0.86, (0, 0, 0.1), GOLD, "z", 20), True)]
    for z in (-0.25, -0.05, 0.15, 0.36):  # bands down the staff
        parts.append(shade(rod(0.032, 0.025, (0, 0, z), GOLDDEEP, "z", 20), True))
    parts.append(shade(prim("cone", loc=(0, 0, -0.36), m=GOLDDEEP, radius1=0.022, radius2=0.04, depth=0.06, vertices=16), True))
    for k in range(3):  # claw foot
        a = k * 2 * math.pi / 3
        claw = prim("cone", loc=(math.cos(a) * 0.035, math.sin(a) * 0.035, -0.43), rot=(math.sin(a) * 0.6, -math.cos(a) * 0.6, 0),
                    m=GOLD, radius1=0.016, radius2=0.0, depth=0.11, vertices=10)
        parts.append(shade(claw, True))
    parts.append(shade(prim("cone", loc=(0, 0, 0.6), m=GOLDDEEP, radius1=0.03, radius2=0.05, depth=0.09, vertices=20), True))
    shield = [(-0.11, 0.14), (0.11, 0.14), (0.16, 0.05), (0.13, -0.08), (0, -0.19), (-0.13, -0.08), (-0.16, 0.05)]
    parts.append(slab("Shield", [(y, cz + z) for y, z in shield], 0.07, GOLD, bev=0.012))
    inner = [(y * 0.74, cz + z * 0.74 - 0.005) for y, z in shield]
    parts.append(slab("Inset", inner, 0.085, EMBLEM, bev=0.006))
    bolt = [(-0.06, 0.08), (0.05, 0.08), (0.0, 0.015), (0.055, 0.015), (-0.04, -0.1), (-0.005, -0.015), (-0.055, -0.015)]
    parts.append(slab("Bolt", [(y, cz + z) for y, z in bolt], 0.1, GOLD, bev=0.004))
    # winged blades, slightly swept up, with engraved grooves
    for s in (-1, 1):
        wing = [(s * 0.13, cz + 0.11), (s * 0.48, cz + 0.06), (s * 0.15, cz - 0.07)]
        parts.append(slab("Wing", wing, 0.045, GOLD, bev=0.01))
        for k in range(3):
            parts.append(box((0.05, 0.05, 0.012), (0, s * (0.2 + k * 0.07), cz + 0.05 - k * 0.012), GOLDDEEP, rot=(s * 0.2, 0, 0)))
    parts.append(slab("Top", [(-0.07, cz + 0.13), (0.07, cz + 0.13), (0.01, cz + 0.36)], 0.045, GOLD, bev=0.01))
    # laurel wreath: paired leaves round the lower part of the emblem
    R = 0.215
    for k in range(13):
        a = math.radians(205 + k * 10.8)
        y, z = math.cos(a) * R, cz - 0.02 + math.sin(a) * R
        for side in (-1, 1):
            off = 0.035 * side
            leaf = prim("uv", loc=(0, y + math.cos(a) * off, z + math.sin(a) * off), scale=(0.35, 1, 0.5), m=GOLD, radius=0.032, segments=10, ring_count=6)
            leaf.rotation_euler = (a + math.pi / 2 + side * 0.5, 0, 0)
            activate(leaf)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
            parts.append(shade(leaf, True))
    stem = prim("torus", loc=(0, 0, cz - 0.02), rot=(0, math.pi / 2, 0), m=GOLDDEEP, major_radius=R, minor_radius=0.008, major_segments=40, minor_segments=6)
    keep(stem, lambda c: c.z < cz + 0.04)
    parts.append(shade(stem, True))
    return join(parts, "Pickaxe_Gold")


# ---------------------------------------------------------------- weapons (barrel along +Y)
def gun(name, parts_fn):
    parts = parts_fn()
    return join(parts, name)


# ---------------------------------------------------------------- nature
LEAF2 = mat("Leaf2", 0x24563a)


def lumpy(o, amt, seed):
    off = Vector((seed * 3.1, seed * 1.7, seed * 2.3))
    for v in o.data.vertices:
        v.co *= 1 + amt * noise.noise(v.co * 1.6 + off)
    return o


def flat_bottom(o, cut):
    """Squash everything below a local height up to it, like the underside of a leaf clump."""
    for v in o.data.vertices:
        if v.co.z < cut:
            v.co.z = cut + (v.co.z - cut) * 0.25
    return o


def skirt(r, depth, z, rot, m_top, m_under, points=16, droop=0.5):
    """One drooping pine branch tier: a star-shaped cone with a concave dark underside."""
    c = prim("cone", loc=(0, 0, z + depth / 2), rot=(0, 0, rot), m=m_top, radius1=r, radius2=0.0, depth=depth,
             vertices=points, end_fill_type="TRIFAN")
    c.data.materials.append(m_under)
    bot = -depth / 2
    for v in c.data.vertices:
        if abs(v.co.z - bot) < 1e-4:
            if abs(v.co.x) < 1e-4 and abs(v.co.y) < 1e-4:
                v.co.z = bot + depth * 0.45  # pull the fan centre up: hollow underside
                continue
            ang = math.atan2(v.co.y, v.co.x)
            tip = int(round(ang / (2 * math.pi / points))) % 2 == 0
            k = random.uniform(1.12, 1.24) if tip else random.uniform(0.7, 0.8)
            v.co.x *= k
            v.co.y *= k
            v.co.z += -droop * random.uniform(0.8, 1.2) if tip else 0.12
    for poly in c.data.polygons:  # fan faces (all corners at or above the rim, centre raised) get the dark side
        zs = [c.data.vertices[i].co.z for i in poly.vertices]
        if max(zs) < bot + depth * 0.46 and len(poly.vertices) == 3 and any(abs(c.data.vertices[i].co.x) < 1e-4 and abs(c.data.vertices[i].co.y) < 1e-4 for i in poly.vertices):
            poly.material_index = 1
    return shade(jitter(c, 0.04), False)


def pine(name, seed):
    random.seed(seed)
    H = 7.8
    trunk = prim("cone", loc=(0, 0, H / 2), m=TRUNK, radius1=0.34, radius2=0.05, depth=H, vertices=10)
    parts = [shade(jitter(trunk, 0.015), True)]
    for k in range(5):  # root flare
        a = k * 2 * math.pi / 5 + 0.4
        parts.append(shade(prim("cone", loc=(math.cos(a) * 0.3, math.sin(a) * 0.3, 0.18), rot=(math.sin(a) * 1.0, -math.cos(a) * 1.0, 0),
                                m=TRUNK, radius1=0.17, radius2=0.02, depth=0.62, vertices=6), True))
    tiers = 8
    for i in range(tiers):
        f = i / (tiers - 1)
        r = 2.7 * (1 - f) ** 0.95 + 0.45
        z = 1.7 + f * 5.6 + random.uniform(-0.08, 0.08)
        depth = 2.0 - f * 0.9
        sk = skirt(r, depth, z, random.uniform(0, 6.3), LEAF, LEAF2, points=16 if i < 5 else 12, droop=0.55 - f * 0.25)
        sk.location.x += random.uniform(-0.07, 0.07)
        sk.location.y += random.uniform(-0.07, 0.07)
        parts.append(sk)
    parts.append(shade(prim("cone", loc=(0, 0, 7.9 + 0.6), m=LEAF, radius1=0.32, radius2=0.0, depth=1.3, vertices=8), False))
    return join(parts, name)


def clump(loc, radius, m, seed, sub=2, squash=0.78, amt=0.2):
    o = prim("ico", loc=(0, 0, 0), scale=(1, 1, squash), m=m, radius=radius, subdivisions=sub)
    lumpy(o, amt, seed)
    flat_bottom(o, -radius * squash * 0.62)
    o.location = loc
    return shade(o, False)


def round_tree(name, seed):
    random.seed(seed)
    parts = [shade(jitter(prim("cone", loc=(0, 0, 1.65), m=TRUNK, radius1=0.44, radius2=0.25, depth=3.3, vertices=10), 0.02), True)]
    for k in range(4):  # root flare
        a = k * math.pi / 2 + 0.3
        parts.append(shade(prim("cone", loc=(math.cos(a) * 0.36, math.sin(a) * 0.36, 0.2), rot=(math.sin(a) * 1.0, -math.cos(a) * 1.0, 0),
                                m=TRUNK, radius1=0.2, radius2=0.03, depth=0.7, vertices=6), True))
    crowns = []
    for k in range(4):  # limbs fanning out of the trunk
        a = k * math.pi / 2 + random.uniform(-0.35, 0.35)
        tilt = random.uniform(0.6, 0.9)
        L = random.uniform(1.7, 2.3)
        base = Vector((0, 0, random.uniform(2.6, 3.1)))
        d = Vector((math.cos(a) * math.sin(tilt), math.sin(a) * math.sin(tilt), math.cos(tilt)))
        limb = prim("cone", loc=base + d * L / 2, m=TRUNK, radius1=0.17, radius2=0.08, depth=L, vertices=8)
        limb.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
        activate(limb)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        parts.append(shade(limb, True))
        crowns.append(base + d * L + Vector((0, 0, 0.35)))
    crowns.append(Vector((0, 0, 5.9)))
    for i, cpos in enumerate(crowns):
        big = 1.95 if i == len(crowns) - 1 else random.uniform(1.55, 1.8)
        parts.append(clump(cpos, big, LEAF, seed * 13 + i, sub=3, squash=0.92))
        parts.append(clump(cpos + Vector((0, 0, -0.3)), big * 0.86, LEAF2, seed * 17 + i, sub=1, squash=0.9))  # shadowed core
        for j in range(3):  # small clumps break up the silhouette
            a = random.uniform(0, 2 * math.pi)
            off = Vector((math.cos(a) * big * 0.8, math.sin(a) * big * 0.8, random.uniform(0.0, 0.8)))
            parts.append(clump(cpos + off, random.uniform(0.75, 1.0), LEAF, seed * 31 + i * 5 + j, sub=2, amt=0.25, squash=0.95))
    return join(parts, name)


BIRCH = mat("Birch", 0xE9E5DB)
BIRCHMARK = mat("BirchMark", 0x2A2926)


def birch(name, seed):
    random.seed(seed)
    H = 6.8
    parts = [shade(prim("cone", loc=(0, 0, H / 2), m=BIRCH, radius1=0.24, radius2=0.08, depth=H, vertices=10), True)]
    for k in range(22):  # dark bark marks wrapped round the trunk
        z = random.uniform(0.3, H * 0.8)
        rr = 0.24 - (0.16 * z / H)
        a = random.uniform(0, 2 * math.pi)
        parts.append(box((0.03, random.uniform(0.12, 0.26), random.uniform(0.04, 0.09)), (math.cos(a) * rr, math.sin(a) * rr, z), BIRCHMARK, rot=(0, 0, a)))
    tops = []
    for k in range(3):
        a = k * 2 * math.pi / 3 + random.uniform(-0.4, 0.4)
        base = Vector((0, 0, random.uniform(3.4, 4.6)))
        d = Vector((math.cos(a) * 0.6, math.sin(a) * 0.6, 0.8)).normalized()
        L = random.uniform(1.2, 1.7)
        limb = prim("cone", loc=base + d * L / 2, m=BIRCH, radius1=0.08, radius2=0.03, depth=L, vertices=6)
        limb.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
        activate(limb)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        parts.append(shade(limb, True))
        tops.append(base + d * L)
    tops.append(Vector((0, 0, H - 0.2)))
    for i, t in enumerate(tops):  # tall, airy leaf clumps
        o = prim("ico", m=LEAF, radius=random.uniform(1.25, 1.5), subdivisions=2, scale=(0.9, 0.9, 1.3))
        lumpy(o, 0.22, seed * 7 + i)
        o.location = t + Vector((0, 0, 0.35))
        parts.append(shade(o, False))
        o = prim("ico", m=LEAF2, radius=1.05, subdivisions=1, scale=(0.9, 0.9, 1.3))
        o.location = t + Vector((0, 0, 0.1))
        parts.append(shade(o, False))
    return join(parts, name)


BERRY = mat("Berry", 0xD8324A)
FERN = mat("Fern", 0x4E9A3E)
GRASS = mat("Grass", 0x6DB043)


def bush(name, seed, berries=False):
    random.seed(seed)
    parts = [clump((0, 0, 0.62), 0.78, LEAF, seed * 3, squash=0.85)]
    n = 7
    for j in range(n):
        a = j / n * 2 * math.pi + random.uniform(-0.2, 0.2)
        r = random.uniform(0.55, 0.75)
        parts.append(clump((math.cos(a) * r, math.sin(a) * r, random.uniform(0.38, 0.55)), random.uniform(0.45, 0.62),
                           LEAF if j % 3 else LEAF2, seed * 7 + j, sub=2, squash=0.85, amt=0.25))
    if berries:
        for k in range(18):
            a = random.uniform(0, 2 * math.pi)
            el = random.uniform(0.15, 1.1)
            rr = 0.95
            loc = (math.cos(a) * math.cos(el) * rr, math.sin(a) * math.cos(el) * rr, 0.45 + math.sin(el) * 0.75)
            parts.append(shade(prim("ico", loc=loc, m=BERRY, radius=random.uniform(0.06, 0.09), subdivisions=1), True))
    return join(parts, name)


def blade_fan(name, count, length, width, mtl, spread, seed, curl=0.0):
    random.seed(seed)
    parts = []
    for k in range(count):
        a = k / count * 2 * math.pi + random.uniform(-0.25, 0.25)
        L = length * random.uniform(0.7, 1.15)
        tilt = spread * random.uniform(0.7, 1.2)
        b = prim("cone", loc=(0, 0, 0), m=mtl, radius1=width, radius2=0.0, depth=L, vertices=3, scale=(1, 0.35, 1))
        for v in b.data.vertices:  # stand the blade on the origin and arch it outward
            v.co.z += L / 2
            t = v.co.z / L
            v.co.x += curl * t * t * L
        b.rotation_euler = (0, tilt, a)
        activate(b)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        parts.append(shade(b, False))
    return join(parts, name)


def rock(name, seed):
    random.seed(seed)
    r = prim("ico", m=ROCK, radius=1.0, subdivisions=3)
    off = Vector([random.uniform(0, 50) for _ in range(3)])
    for v in r.data.vertices:  # weathered boulder: broad noise plus a few flattened faces
        n = noise.noise(v.co * 1.2 + off)
        v.co *= 1 + 0.24 * n
        for axis, cut in ((0, 0.78), (1, 0.82), (2, 0.7)):
            if v.co[axis] > cut:
                v.co[axis] = cut + (v.co[axis] - cut) * 0.3
        v.co.z = max(v.co.z, -0.35)
    return join([shade(r, True)], name)


# ---------------------------------------------------------------- props
def chest():
    base = bevel(box((1.2, 0.8, 0.6), (0, 0, 0.3), CHESTWOOD), 0.03)
    parts = [base]
    for x in (-0.42, 0.42):
        parts.append(box((0.09, 0.84, 0.62), (x, 0, 0.3), CHESTMETAL))
    parts.append(bevel(box((0.2, 0.05, 0.24), (0, 0.42, 0.48), SILO), 0.02))  # steel lock plate
    parts.append(rod(0.025, 0.03, (0, 0.448, 0.5), EYE, "y", 10))  # keyhole
    parts.append(box((0.018, 0.03, 0.05), (0, 0.448, 0.465), EYE))
    for x in (-0.42, 0.42):  # rivets down the bands
        for z in (0.1, 0.3, 0.5):
            parts.append(shade(prim("uv", loc=(x, 0.425, z), m=SILO, radius=0.022, segments=8, ring_count=6), True))
    for y in (-0.32, -0.12, 0.12):  # plank seams
        parts.append(box((1.21, 0.012, 0.6), (0, y + 0.1, 0.3), CHESTMETAL))
    body = join(parts, "Chest")
    lid = prim("cyl", loc=(0, 0, 0.6), rot=(0, math.pi / 2, 0), m=CHESTWOOD, radius=0.4, depth=1.2, vertices=16)
    keep(lid, lambda c: c.z >= 0.599)
    lp = [shade(lid, True)]
    for x in (-0.42, 0.42):
        b = prim("cyl", loc=(x, 0, 0.6), rot=(0, math.pi / 2, 0), m=CHESTMETAL, radius=0.42, depth=0.09, vertices=16)
        keep(b, lambda c: c.z >= 0.599)
        lp.append(shade(b, True))
    join(lp, "ChestLid", origin=(0, -0.4, 0.6))
    return body


def airship():
    hull = prim("uv", m=HULL, radius=1, segments=32, ring_count=16, scale=(11, 3.6, 3.6))
    shade(hull, True)
    parts = [hull]
    band = prim("uv", m=STRIPE, radius=1, segments=32, ring_count=16, scale=(11.06, 3.66, 3.66))
    keep(band, lambda c: abs(c.z) < 0.55)
    parts.append(shade(band, True))
    nose = prim("uv", loc=(10.6, 0, 0), m=STRIPE, radius=0.9, segments=16, ring_count=8)
    parts.append(shade(nose, True))
    for rot, loc in [((0, 0, 0), (-9.6, 0, 2.4)), ((0, 0, 0), (-9.6, 0, -2.4)),
                     ((math.pi / 2, 0, 0), (-9.6, 2.4, 0)), ((math.pi / 2, 0, 0), (-9.6, -2.4, 0))]:
        fin = box((3.0, 0.22, 2.4), loc, STRIPE, rot=rot, bev=0.08)
        parts.append(fin)
    g = shade(bevel(box((6.0, 2.3, 1.6), (0, 0, -4.2), GONDOLA), 0.25, 3), True)
    parts.append(g)
    for i in range(5):
        x = -2.2 + i * 1.1
        for y in (-1.16, 1.16):
            parts.append(box((0.7, 0.05, 0.6), (x, y, -4.1), WINDOW))
    for x in (-2, 2):
        parts.append(rod(0.12, 1.4, (x, 0, -3.0), GONDOLA, "z", 8))
    ship = join(parts, "Airship")
    prop = [prim("cone", loc=(-11.5, 0, 0), rot=(0, -math.pi / 2, 0), m=GONDOLA, radius1=0.45, radius2=0.1, depth=0.8, vertices=12)]
    for k in range(3):
        a = k * 2 * math.pi / 3
        prop.append(box((0.12, 0.5, 2.0), (-11.9, math.sin(a) * 1.0, math.cos(a) * 1.0), DARK, rot=(-a, 0, 0), bev=0.04))
    join(prop, "Prop", origin=(-11.9, 0, 0))
    return ship


# ---------------------------------------------------------------- town buildings and props
HOUSEWALL = mat("HouseWall", 0xE9DCC3)
ROOF = mat("Roof", 0xB34A3C)
TRIM = mat("Trim", 0xF5F1E6)
GLASS = mat("Glass", 0x8FD0F0, 0.1)
SHUTTER = mat("Shutter", 0x3F6E8C)
FLOOR = mat("Floor", 0x9C7650)
BRICK = mat("Brick", 0x8E4B3A)
STONE = mat("Stone", 0x9A9890)
MILLWALL = mat("MillWall", 0xEFE6D2)
MILLROOF = mat("MillRoof", 0x7A2E26)
SAIL = mat("Sail", 0xF2EDE0)
LIGHTRED = mat("LightRed", 0xD8413A)
LIGHTWHITE = mat("LightWhite", 0xF6F2EA)
LAMP = mat("Lamp", 0xFFE79A)
SILO = mat("SiloMetal", 0xB9BEC6, 0.4)
RUST = mat("Rust", 0x9A5A34)
TANK = mat("TankPaint", 0x3F8F8C)
CONTAINER = mat("ContainerPaint", 0xC8452F)
CRATE = mat("CrateWood", 0xB9894F)
CRATEEDGE = mat("CrateEdge", 0x7A5530)
BARREL = mat("Barrel", 0xB0442E)
FENCE = mat("FenceWood", 0x8A6440)
HAY = mat("Hay", 0xE2C26A)
DOCK = mat("DockWood", 0x8C6A48)
BOAT = mat("BoatPaint", 0x2F6FB0)


def prism(name, pts, depth_axis, depth, m):
    """Extrude a 2-D polygon (list of 3-D points on a plane) into a slab."""
    me = bpy.data.meshes.new(name)
    off = Vector(depth_axis) * depth
    verts = [Vector(p) - off / 2 for p in pts] + [Vector(p) + off / 2 for p in pts]
    n = len(pts)
    faces = [list(range(n))[::-1], list(range(n, 2 * n))]
    faces += [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(m)
    return o


def window(parts, center, normal, width=1.3, height=1.2):
    """Framed glass pane with shutters, on both faces of a 0.4 m wall."""
    cx, cy, cz = center
    along_x = abs(normal[1]) > 0.5  # wall runs along X when its normal is ±Y
    for side in (1, -1):
        off = 0.2 * side
        fx, fy = (cx, cy + normal[1] * off) if along_x else (cx + normal[0] * off, cy)
        sz = (width + 0.3, 0.12, height + 0.3) if along_x else (0.12, width + 0.3, height + 0.3)
        gz = (width, 0.06, height) if along_x else (0.06, width, height)
        parts.append(box(sz, (fx, fy, cz), TRIM))
        gx, gy = (fx, fy + normal[1] * side * 0.04) if along_x else (fx + normal[0] * side * 0.04, fy)
        parts.append(box(gz, (gx, gy, cz), GLASS))
        if side == 1:  # shutters and sill outside only
            for s in (-1, 1):
                d = s * (width / 2 + 0.38)
                pos = (fx + d, fy + normal[1] * 0.03, cz) if along_x else (fx + normal[0] * 0.03, fy + d, cz)
                ssz = (0.42, 0.06, height + 0.2) if along_x else (0.06, 0.42, height + 0.2)
                parts.append(box(ssz, pos, SHUTTER))
            sill = (width + 0.5, 0.25, 0.08) if along_x else (0.25, width + 0.5, 0.08)
            spos = (fx, fy + normal[1] * 0.1, cz - height / 2 - 0.18) if along_x else (fx + normal[0] * 0.1, fy, cz - height / 2 - 0.18)
            parts.append(box(sill, spos, TRIM))


def house():
    """12×12 m, walls 0.4 m thick and 4.4 m tall, doorway 2.8×3 m on the +Y side. Matches the game's
    collision boxes exactly. Each wall is its own object (HouseWall_F/B/R/L, front = door side) so the
    game can break walls one at a time; "House" is the frame: floor, corner posts, porch, roof, chimney."""
    W, T, H, h = 12.0, 0.4, 4.4, 6.0
    F, B, R, L, S = [], [], [], [], []
    B.append(box((W, T, H), (0, -h, H / 2), HOUSEWALL))
    R.append(box((T, W - T, H), (h, 0, H / 2), HOUSEWALL))
    L.append(box((T, W - T, H), (-h, 0, H / 2), HOUSEWALL))
    seg = h - 1.4
    for s_ in (-1, 1):
        F.append(box((seg, T, H), (s_ * (1.4 + seg / 2), h, H / 2), HOUSEWALL))
    F.append(box((2.8, T, H - 3), (0, h, 3 + (H - 3) / 2), HOUSEWALL))
    for x in (-h, h):  # corner posts
        for y in (-h, h):
            S.append(box((0.55, 0.55, H + 0.05), (x, y, H / 2), TRIM))
    for x in (-3, 3):
        window(B, (x, -h, 2.2), (0, -1, 0))
    for y in (-3, 3):
        window(R, (h, y, 2.2), (1, 0, 0))
        window(L, (-h, y, 2.2), (-1, 0, 0))
    for x in (-3.9, 3.9):
        window(F, (x, h, 2.2), (0, 1, 0), width=1.2)
    for s_ in (-1, 1):  # door frame
        F.append(box((0.2, 0.6, 3.05), (s_ * 1.5, h, 1.52), TRIM))
    F.append(box((3.2, 0.6, 0.25), (0, h, 3.1), TRIM))
    S.append(bevel(box((3.6, 1.3, 0.14), (0, h + 0.85, 0.07), STONE), 0.03))  # porch step
    S.append(box((W - T, W - T, 0.04), (0, 0, 0.02), FLOOR))
    rise, half = 2.6, h + 0.6
    ang = math.atan2(rise, half)
    length = math.hypot(half, rise)
    for s_ in (-1, 1):  # gabled roof, ridge along X
        S.append(box((W + 1.2, length, 0.26), (0, s_ * half / 2, H + rise / 2 + 0.13), ROOF, rot=(-s_ * ang, 0, 0)))
    S.append(box((W + 1.3, 0.45, 0.28), (0, 0, H + rise + 0.18), MILLROOF))  # ridge cap
    for x in (-h, h):  # gable ends
        S.append(prism("gable", [(x, -h, H), (x, h, H), (x, 0, H + rise)], (1, 0, 0), T, HOUSEWALL))
    S.append(box((1.0, 1.0, 2.6), (3.4, -2.2, H + 1.9), BRICK))  # chimney
    S.append(box((1.2, 1.2, 0.2), (3.4, -2.2, H + 3.25), STONE))
    for parts, n in ((F, "F"), (B, "B"), (R, "R"), (L, "L")):
        join(parts, "HouseWall_" + n)
    return join(S, "House")


def windmill():
    p = [prim("cyl", loc=(0, 0, 0.3), m=STONE, radius=3.0, depth=0.6, vertices=8)]
    tower = prim("cone", loc=(0, 0, 5.1), m=MILLWALL, radius1=2.6, radius2=1.7, depth=9.0, vertices=8)
    p.append(tower)
    p.append(prim("cone", loc=(0, 0, 10.7), m=MILLROOF, radius1=2.2, radius2=0.0, depth=2.4, vertices=8))
    p.append(box((1.3, 0.3, 2.2), (0, 2.5, 1.7), CRATEEDGE))  # door
    for z in (4.2, 7.0):
        p.append(box((0.8, 0.3, 0.9), (0, 2.0 if z > 5 else 2.25, z), GLASS))
    p.append(rod(0.4, 0.8, (0, 1.9, 8.4), DARK, "y"))  # axle housing
    join(p, "Windmill")
    b = [rod(0.42, 0.5, (0, 2.4, 8.4), DARK, "y", 12)]
    for k in range(4):
        a = k * math.pi / 2
        dx, dz = math.sin(a), math.cos(a)
        b.append(box((0.24, 0.16, 6.4), (dx * 3.3, 2.5, 8.4 + dz * 3.3), CRATEEDGE, rot=(0, a, 0)))
        sx, sz = math.cos(a) * 0.65, -math.sin(a) * 0.65
        b.append(box((1.1, 0.05, 4.8), (dx * 3.8 + sx, 2.55, 8.4 + dz * 3.8 + sz), SAIL, rot=(0, a, 0)))
    join(b, "MillBlades", origin=(0, 2.4, 8.4))


def lighthouse():
    p = [prim("cyl", loc=(0, 0, 0.5), m=STONE, radius=2.7, depth=1.0, vertices=16)]
    n, top = 5, 14.0
    for i in range(n):
        z0, z1 = 1.0 + (top - 1.0) * i / n, 1.0 + (top - 1.0) * (i + 1) / n
        r0, r1 = 2.2 - 0.8 * i / n, 2.2 - 0.8 * (i + 1) / n
        seg = prim("cone", loc=(0, 0, (z0 + z1) / 2), m=LIGHTRED if i % 2 == 0 else LIGHTWHITE,
                   radius1=r0, radius2=r1, depth=z1 - z0, vertices=20)
        p.append(shade(seg, True))
    p.append(prim("cyl", loc=(0, 0, top + 0.15), m=DARK, radius=2.0, depth=0.3, vertices=20))
    for k in range(12):
        a = k * math.pi / 6
        p.append(rod(0.04, 0.8, (math.cos(a) * 1.85, math.sin(a) * 1.85, top + 0.7), DARK, "z", 4))
    p.append(shade(prim("cyl", loc=(0, 0, top + 1.1), m=LAMP, radius=1.1, depth=1.6, vertices=16), True))
    p.append(shade(prim("cone", loc=(0, 0, top + 2.6), m=LIGHTRED, radius1=1.45, radius2=0.1, depth=1.4, vertices=16), True))
    p.append(box((1.1, 0.3, 2.0), (0, 2.15, 2.0), CRATEEDGE))
    return join(p, "Lighthouse")


def silo():
    p = [shade(prim("cyl", loc=(0, 0, 5.0), m=SILO, radius=2.4, depth=10.0, vertices=20), True)]
    dome = prim("uv", loc=(0, 0, 10.0), m=SILO, radius=2.4, segments=20, ring_count=10)
    keep(dome, lambda c: c.z >= 9.99)
    p.append(shade(dome, True))
    for z in (1.0, 4.0, 7.0, 9.6):
        p.append(shade(prim("cyl", loc=(0, 0, z), m=RUST, radius=2.46, depth=0.2, vertices=20), True))
    for s in (-0.25, 0.25):  # ladder
        p.append(box((0.06, 0.06, 10.0), (s, 2.5, 5.0), DARK))
    for z in range(1, 10):
        p.append(box((0.56, 0.05, 0.05), (0, 2.5, z), DARK))
    return join(p, "Silo")


def water_tower():
    p = []
    for x in (-1.8, 1.8):
        for y in (-1.8, 1.8):
            p.append(box((0.3, 0.3, 8.0), (x, y, 4.0), RUST))
    for z in (2.6, 5.4):
        for s in (-1.8, 1.8):
            p.append(box((3.9, 0.12, 0.12), (0, s, z), RUST))
            p.append(box((0.12, 3.9, 0.12), (s, 0, z), RUST))
    p.append(box((4.6, 4.6, 0.3), (0, 0, 8.1), DARK))
    p.append(shade(prim("cyl", loc=(0, 0, 9.8), m=TANK, radius=2.6, depth=3.2, vertices=20), True))
    p.append(shade(prim("cone", loc=(0, 0, 12.0), m=TANK, radius1=2.75, radius2=0.2, depth=1.3, vertices=20), True))
    return join(p, "WaterTower")


def container():
    L, Wd, Ht = 6.1, 2.45, 2.6
    p = [bevel(box((L, Wd, Ht), (0, 0, Ht / 2), CONTAINER), 0.04)]
    for i in range(15):
        x = -L / 2 + 0.3 + i * (L - 0.6) / 14
        for s in (-1, 1):
            p.append(box((0.1, 0.06, Ht - 0.3), (x, s * (Wd / 2 + 0.02), Ht / 2), CONTAINER))
    for s in (-1, 1):  # door bars at the end
        p.append(box((0.05, 0.06, Ht - 0.2), (L / 2 + 0.03, s * 0.35, Ht / 2), DARK))
        p.append(box((0.05, 0.06, Ht - 0.2), (L / 2 + 0.03, s * 0.9, Ht / 2), DARK))
    for z in (0.08, Ht - 0.08):
        p.append(box((L + 0.02, Wd + 0.02, 0.16), (0, 0, z), DARK))
    return join(p, "Container")


def crate():
    p = [box((1.1, 1.1, 1.1), (0, 0, 0.6), CRATE)]
    for a in (0, 1, 2):  # edge frame on all 12 edges
        for s1 in (-1, 1):
            for s2 in (-1, 1):
                if a == 0:
                    p.append(box((1.22, 0.14, 0.14), (0, s1 * 0.55, 0.6 + s2 * 0.55), CRATEEDGE))
                elif a == 1:
                    p.append(box((0.14, 1.22, 0.14), (s1 * 0.55, 0, 0.6 + s2 * 0.55), CRATEEDGE))
                else:
                    p.append(box((0.14, 0.14, 1.22), (s1 * 0.55, s2 * 0.55, 0.6), CRATEEDGE))
    for s in (-1, 1):  # diagonal braces on two faces
        p.append(box((1.45, 0.06, 0.12), (0, s * 0.57, 0.6), CRATEEDGE, rot=(0, 0.785, 0)))
    return join(p, "Crate")


def barrel():
    p = [shade(prim("cyl", loc=(0, 0, 0.55), m=BARREL, radius=0.45, depth=1.1, vertices=16), True)]
    for z in (0.2, 0.9):
        p.append(shade(prim("cyl", loc=(0, 0, z), m=DARK, radius=0.47, depth=0.07, vertices=16), True))
    p.append(prim("cyl", loc=(0, 0, 1.105), m=DARK, radius=0.4, depth=0.02, vertices=16))
    return join(p, "Barrel")


def fence():
    p = []
    for x in (-1.5, 0, 1.5):
        p.append(box((0.14, 0.14, 1.15), (x, 0, 0.575), FENCE))
    for z in (0.45, 0.9):
        p.append(box((3.1, 0.06, 0.13), (0, 0.05, z), FENCE))
    return join(p, "Fence")


def lamp_post():
    p = [rod(0.08, 3.6, (0, 0, 1.8), DARK, "z", 8), rod(0.2, 0.2, (0, 0, 0.1), DARK, "z", 8)]
    p.append(box((0.08, 0.7, 0.08), (0, 0.32, 3.55), DARK))
    p.append(box((0.32, 0.32, 0.42), (0, 0.65, 3.3), LAMP))
    p.append(box((0.4, 0.4, 0.06), (0, 0.65, 3.53), DARK))
    return join(p, "Lamp")


def hay_bale():
    return join([shade(prim("cyl", loc=(0, 0, 0.7), rot=(0, math.pi / 2, 0), m=HAY, radius=0.7, depth=1.3, vertices=16), True)], "HayBale")


def dock():
    """Pier along +Y: 3 m wide, 20 m long, deck top at z=0.5."""
    p = []
    for i in range(20):
        p.append(box((3.0, 0.9, 0.12), (0, i + 0.5, 0.44), DOCK))
    for y in range(0, 21, 4):
        for x in (-1.4, 1.4):
            p.append(rod(0.12, 2.2, (x, y, -0.6), CRATEEDGE, "z", 8))
    return join(p, "Dock")


def boat():
    hull = prim("uv", loc=(0, 0, 0.6), m=BOAT, radius=1, segments=16, ring_count=8, scale=(2.3, 0.95, 0.75))
    keep(hull, lambda c: c.z <= 0.62)
    modify(hull, "SOLIDIFY", thickness=0.06)
    shade(hull, True)
    p = [hull, box((0.25, 1.6, 0.08), (0.3, 0, 0.45), DOCK), box((0.25, 1.4, 0.08), (-0.8, 0, 0.45), DOCK)]
    return join(p, "Boat")


# ---------------------------------------------------------------- more weapons, items, nature
POTION = mat("Potion", 0x3FA9FF, 0.2)
CLOTHW = mat("Bandage", 0xF2EEE4)
REDX = mat("RedCross", 0xD83A3A)
PADBASE = mat("PadBase", 0x2B2E3B)
PADTOP = mat("PadTop", 0xFF8A1A)
WILLOW = mat("Willow", 0x6FA83A)
CLIFF = mat("Cliff", 0x9C9A92)
CLIFF2 = mat("CliffDark", 0x7E7B72)


def tube(r, y0, y1, m, z=0.0, x=0.0, v=18):
    """Smooth cylinder along Y with crisp end caps."""
    o = rod(r, abs(y1 - y0), (x, (y0 + y1) / 2, z), m, "y", v)
    shade(o, True)
    return modify(o, "EDGE_SPLIT", split_angle=math.radians(40), use_edge_angle=True, use_edge_sharp=False)


def cone_y(r0, r1, y0, y1, m, z=0.0, x=0.0, v=18):
    o = prim("cone", loc=(x, (y0 + y1) / 2, z), rot=(-math.pi / 2, 0, 0), m=m, radius1=r0, radius2=r1, depth=abs(y1 - y0), vertices=v)
    shade(o, True)
    return modify(o, "EDGE_SPLIT", split_angle=math.radians(40), use_edge_angle=True, use_edge_sharp=False)


def ring_y(r, minor, y, m, z=0.0):
    o = prim("torus", loc=(0, y, z), rot=(math.pi / 2, 0, 0), m=m, major_radius=r, minor_radius=minor, major_segments=24, minor_segments=6)
    return shade(o, True)


def guard(y0, y1, z0, z1, t=0.012, w=0.03):
    """U-shaped trigger guard below the receiver."""
    pts = [(y0, z0), (y0 + t, z0), (y0 + t, z1 + t), (y1 - t, z1 + t), (y1 - t, z0), (y1, z0), (y1, z1), (y0, z1)]
    return slab("guard", pts, w, GUNDARK, bev=0.003)


def railteeth(y0, y1, z, n, w=0.05):
    p = [box((w, y1 - y0, 0.016), (0, (y0 + y1) / 2, z), GUNDARK)]
    for k in range(n):
        p.append(box((w + 0.006, 0.012, 0.012), (0, y0 + 0.02 + k * (y1 - y0 - 0.04) / max(n - 1, 1), z + 0.012), GUNDARK))
    return p


def reddot(y, z):
    return [slab("dot", [(y - 0.06, z), (y + 0.06, z), (y + 0.05, z + 0.07), (y - 0.04, z + 0.07)], 0.05, GUNDARK, bev=0.006),
            tube(0.02, y + 0.045, y + 0.052, LENS, z=z + 0.04, v=16)]


def mag_curve(y0, z0, y1, z1, curve, rx=0.027, rn=0.048):
    P0, P2 = Vector((0, y0, z0)), Vector((0, y1, z1))
    P1 = (P0 + P2) / 2 + Vector((0, -curve, 0))
    return loft("mag", 10, 14, lambda t: (bez(P0, P1, P2, t), rx, rn), [GUNDARK])


def ar():
    p = [slab("rcv", [(-0.08, 0.02), (0.47, 0.02), (0.47, 0.105), (0.05, 0.105), (-0.02, 0.12), (-0.08, 0.12)], 0.085, GUNBODY)]
    p.append(slab("rstripe", [(0.0, 0.055), (0.4, 0.055), (0.4, 0.08), (0.0, 0.08)], 0.09, RARITY, bev=0.004))
    p.append(slab("lower", [(-0.06, -0.045), (0.27, -0.045), (0.25, 0.025), (-0.06, 0.025)], 0.075, GUNDARK))
    p.append(slab("hguard", [(0.47, -0.03), (0.84, -0.02), (0.86, 0.03), (0.84, 0.095), (0.47, 0.1)], 0.095, GUNDARK))
    for k in range(5):  # vent slats
        p.append(box((0.1, 0.035, 0.016), (0, 0.53 + k * 0.06, 0.055), GUNBODY))
    p.append(slab("hstripe", [(0.5, -0.012), (0.82, -0.008), (0.82, 0.014), (0.5, 0.014)], 0.1, RARITY, bev=0.004))
    p += railteeth(0.04, 0.8, 0.115, 16)
    p.append(tube(0.019, 0.84, 1.05, GUNDARK, z=0.035))
    p.append(box((0.05, 0.04, 0.05), (0, 0.9, 0.035), GUNBODY))  # gas block
    p.append(tube(0.031, 1.04, 1.12, GUNBODY, z=0.035))  # muzzle brake
    for y in (1.065, 1.095):
        p.append(box((0.07, 0.008, 0.02), (0, y, 0.035), GUNDARK))
    p += reddot(0.24, 0.135)
    p.append(slab("stock", [(-0.08, 0.11), (-0.36, 0.085), (-0.4, 0.07), (-0.41, -0.08), (-0.35, -0.1), (-0.25, -0.02), (-0.08, 0.0)], 0.07, GUNDARK))
    p.append(slab("butt", [(-0.43, 0.075), (-0.4, 0.075), (-0.4, -0.085), (-0.43, -0.085)], 0.075, GUNBODY, bev=0.006))
    p.append(box((0.072, 0.17, 0.025), (0, -0.22, 0.11), GUNBODY))  # cheek riser
    p.append(slab("grip", [(-0.03, -0.045), (0.045, -0.045), (0.015, -0.21), (-0.065, -0.2)], 0.065, GUNDARK))
    p.append(guard(0.05, 0.14, -0.045, -0.1))
    p.append(box((0.012, 0.012, 0.04), (0, 0.085, -0.065), STEEL, rot=(0.3, 0, 0)))
    p.append(mag_curve(0.17, -0.04, 0.25, -0.28, 0.05))
    p.append(box((0.06, 0.07, 0.02), (0, 0.25, -0.285), GUNBODY))
    p.append(box((0.03, 0.04, 0.02), (0.05, 0.12, 0.08), STEEL))  # charging handle
    return p


def smg():
    p = [slab("rcv", [(-0.06, 0.0), (0.3, 0.0), (0.3, 0.1), (0.02, 0.1), (-0.06, 0.085)], 0.08, GUNBODY)]
    p.append(slab("rstripe", [(0.0, 0.035), (0.27, 0.035), (0.27, 0.065), (0.0, 0.065)], 0.085, RARITY, bev=0.004))
    p += railteeth(0.02, 0.28, 0.105, 7, 0.045)
    p.append(box((0.03, 0.04, 0.05), (0, 0.06, 0.13), GUNDARK))  # rear sight
    p.append(box((0.02, 0.03, 0.05), (0, 0.27, 0.13), GUNDARK))
    p.append(tube(0.037, 0.3, 0.6, GUNDARK, z=0.05))  # suppressor
    for y in (0.33, 0.57):
        p.append(ring_y(0.038, 0.005, y, GUNBODY, z=0.05))
    p.append(slab("mag", [(0.12, 0.0), (0.18, 0.0), (0.17, -0.3), (0.11, -0.3)], 0.05, GUNDARK, bev=0.006))
    p.append(slab("grip", [(-0.02, 0.0), (0.045, 0.0), (0.015, -0.16), (-0.05, -0.15)], 0.06, GUNDARK))
    p.append(guard(0.04, 0.11, 0.0, -0.05))
    fg = prim("cyl", loc=(0, 0.25, -0.07), m=GUNDARK, radius=0.022, depth=0.12, vertices=14)
    p.append(shade(fg, True))
    for z in (-0.0, 0.07):  # folding stock
        p.append(box((0.018, 0.24, 0.018), (0.03, -0.17, z), GUNDARK))
    p.append(slab("butt", [(-0.3, 0.1), (-0.27, 0.1), (-0.27, -0.03), (-0.3, -0.03)], 0.06, GUNBODY, bev=0.006))
    return p


def shotgun():
    p = [slab("rcv", [(-0.05, -0.03), (0.22, -0.03), (0.22, 0.075), (0.0, 0.085), (-0.05, 0.065)], 0.085, GUNBODY)]
    p.append(slab("rstripe", [(-0.02, 0.025), (0.2, 0.025), (0.2, 0.05), (-0.02, 0.05)], 0.09, RARITY, bev=0.004))
    p.append(tube(0.027, 0.22, 0.87, GUNDARK, z=0.045))
    p.append(tube(0.022, 0.22, 0.78, GUNDARK, z=-0.012))
    p.append(box((0.03, 0.04, 0.09), (0, 0.78, 0.017), GUNBODY))  # barrel clamp
    p.append(tube(0.039, 0.36, 0.57, WOOD, z=-0.012))  # pump
    for k in range(5):
        p.append(ring_y(0.039, 0.005, 0.39 + k * 0.035, GUNDARK, z=-0.012))
    p.append(slab("stock", [(-0.05, 0.055), (-0.38, 0.0), (-0.41, -0.13), (-0.34, -0.155), (-0.12, -0.065), (-0.05, -0.03)], 0.07, WOOD))
    p.append(slab("pad", [(-0.43, 0.01), (-0.4, 0.0), (-0.43, -0.13), (-0.46, -0.12)], 0.072, GUNDARK, bev=0.005))
    p.append(guard(0.04, 0.13, -0.03, -0.085))
    p.append(shade(prim("uv", loc=(0, 0.855, 0.08), m=ACCENT, radius=0.009, segments=10, ring_count=6), True))  # bead
    for k in range(4):  # spare shells on the side
        p.append(rod(0.011, 0.055, (0.047, 0.02 + k * 0.035, 0.02), REDX, "z", 10))
    return p


def tactical():
    p = [slab("rcv", [(-0.07, -0.04), (0.3, -0.04), (0.3, 0.08), (0.22, 0.105), (-0.07, 0.105)], 0.1, GUNBODY)]
    p.append(slab("rstripe", [(-0.04, 0.03), (0.27, 0.03), (0.27, 0.06), (-0.04, 0.06)], 0.105, RARITY, bev=0.004))
    p.append(slab("shield", [(0.3, -0.005), (0.66, 0.005), (0.67, 0.05), (0.66, 0.095), (0.3, 0.105)], 0.1, GUNDARK))
    for k in range(6):
        p.append(box((0.106, 0.03, 0.02), (0, 0.34 + k * 0.05, 0.06), GUNBODY))
    p.append(tube(0.03, 0.3, 0.75, GUNDARK, z=0.035))
    p.append(cone_y(0.03, 0.05, 0.74, 0.8, GUNBODY, z=0.035))
    p.append(tube(0.024, 0.3, 0.62, GUNDARK, z=-0.03))
    p += reddot(0.08, 0.105)
    p.append(slab("grip", [(-0.04, -0.04), (0.035, -0.04), (0.005, -0.2), (-0.075, -0.19)], 0.066, GUNDARK))
    p.append(guard(0.04, 0.13, -0.04, -0.095))
    p.append(slab("stock", [(-0.07, 0.08), (-0.24, 0.05), (-0.26, -0.09), (-0.2, -0.1), (-0.07, -0.02)], 0.08, GUNDARK))
    p.append(slab("fore", [(0.36, -0.03), (0.44, -0.03), (0.43, -0.11), (0.37, -0.11)], 0.05, GUNDARK, bev=0.008))
    return p


def sniper():
    p = [slab("rcv", [(-0.06, 0.0), (0.42, 0.0), (0.42, 0.1), (-0.06, 0.1)], 0.085, GUNBODY)]
    p.append(slab("rstripe", [(0.0, 0.035), (0.4, 0.035), (0.4, 0.065), (0.0, 0.065)], 0.09, RARITY, bev=0.004))
    p.append(tube(0.022, 0.42, 1.19, GUNDARK, z=0.05))
    p.append(tube(0.033, 1.18, 1.3, GUNBODY, z=0.05))
    for y in (1.21, 1.24, 1.27):
        p.append(box((0.075, 0.008, 0.02), (0, y, 0.05), GUNDARK))
    # scope with bells, lenses, turrets and rings
    p.append(tube(0.034, 0.08, 0.44, GUNDARK, z=0.175))
    p.append(cone_y(0.046, 0.034, 0.0, 0.08, GUNDARK, z=0.175))
    p.append(cone_y(0.034, 0.056, 0.44, 0.54, GUNDARK, z=0.175))
    p.append(tube(0.052, 0.535, 0.545, LENS, z=0.175))
    p.append(tube(0.04, -0.002, 0.004, LENS, z=0.175))
    p.append(shade(prim("cyl", loc=(0, 0.26, 0.22), m=GUNBODY, radius=0.02, depth=0.04, vertices=14), True))
    p.append(shade(rod(0.02, 0.04, (0.045, 0.26, 0.175), GUNBODY, "x", 14), True))
    for y in (0.14, 0.38):
        p.append(box((0.05, 0.03, 0.07), (0, y, 0.13), GUNDARK))
        p.append(ring_y(0.037, 0.008, y, GUNBODY, z=0.175))
    p.append(shade(rod(0.012, 0.09, (0.065, 0.05, 0.06), STEEL, "x", 10), True))  # bolt
    p.append(shade(prim("uv", loc=(0.11, 0.05, 0.06), m=GUNDARK, radius=0.021, segments=12, ring_count=8), True))
    p.append(slab("stock", [(-0.06, 0.09), (-0.43, 0.075), (-0.45, -0.11), (-0.37, -0.125), (-0.13, -0.04), (-0.1, -0.17), (-0.03, -0.17), (0.0, -0.005)], 0.072, GUNDARK))
    p.append(box((0.074, 0.2, 0.03), (0, -0.25, 0.09), RARITY))  # cheek pad
    p.append(guard(0.04, 0.13, 0.0, -0.055))
    p.append(slab("mag", [(0.18, 0.0), (0.27, 0.0), (0.26, -0.07), (0.19, -0.07)], 0.05, GUNDARK, bev=0.006))
    for sx in (-1, 1):  # folded bipod
        p.append(rod(0.008, 0.26, (sx * 0.02, 0.68, 0.02), GUNDARK, "y", 8))
    return p


def pistol():
    p = [slab("slide", [(-0.04, 0.03), (0.29, 0.03), (0.29, 0.09), (-0.03, 0.09)], 0.065, GUNBODY)]
    for k in range(5):  # rear serrations
        p.append(box((0.068, 0.006, 0.045), (0, -0.02 + k * 0.014, 0.06), GUNDARK))
    p.append(slab("frame", [(-0.03, -0.02), (0.26, -0.02), (0.26, 0.03), (-0.03, 0.03)], 0.06, GUNDARK))
    p.append(slab("grip", [(-0.04, -0.02), (0.04, -0.02), (0.01, -0.19), (-0.07, -0.18)], 0.062, GUNDARK))
    p.append(slab("gpanel", [(-0.03, -0.04), (0.03, -0.04), (0.005, -0.165), (-0.055, -0.155)], 0.068, RARITY, bev=0.004))
    p.append(guard(0.03, 0.11, -0.02, -0.07))
    p.append(tube(0.012, 0.29, 0.305, GUNDARK, z=0.06))
    p.append(box((0.02, 0.015, 0.018), (0, 0.27, 0.098), GUNDARK))
    p.append(box((0.04, 0.015, 0.018), (0, -0.02, 0.098), GUNDARK))
    return p


def hunting():
    p = [slab("stock", [(-0.42, -0.1), (-0.4, 0.06), (-0.05, 0.06), (0.0, 0.0), (0.76, 0.0), (0.76, -0.04), (0.02, -0.06), (-0.06, -0.15),
                        (-0.14, -0.15), (-0.1, -0.06), (-0.33, -0.11)], 0.07, WOOD)]
    p.append(slab("pad", [(-0.44, -0.1), (-0.42, -0.1), (-0.4, 0.06), (-0.42, 0.06)], 0.072, GUNDARK, bev=0.004))
    p.append(tube(0.03, -0.02, 0.3, GUNBODY, z=0.035))
    p.append(tube(0.018, 0.3, 1.16, GUNDARK, z=0.035))
    for y in (0.5, 0.7):
        p.append(ring_y(0.022, 0.006, y, GOLD, z=0.02))
    p.append(box((0.016, 0.02, 0.04), (0, 1.13, 0.065), GUNDARK))
    p.append(box((0.03, 0.02, 0.03), (0, 0.32, 0.065), GUNDARK))
    p.append(shade(rod(0.011, 0.08, (0.05, 0.1, 0.035), STEEL, "x", 10), True))
    p.append(shade(prim("uv", loc=(0.09, 0.1, 0.035), m=GUNDARK, radius=0.017, segments=10, ring_count=6), True))
    p.append(guard(0.0, 0.09, -0.04, -0.09))
    p.append(slab("rstripe", [(-0.3, -0.02), (-0.08, -0.01), (-0.08, 0.02), (-0.3, 0.02)], 0.074, RARITY, bev=0.004))
    return p


def minigun():
    p = [tube(0.1, -0.15, 0.2, GUNBODY, v=24)]
    p.append(cone_y(0.07, 0.1, -0.22, -0.15, GUNDARK, v=24))
    p.append(ring_y(0.101, 0.012, 0.05, RARITY))
    p.append(ring_y(0.101, 0.012, 0.12, RARITY))
    for k in range(6):
        a = k * math.pi / 3
        p.append(tube(0.019, 0.2, 0.82, GUNDARK, z=math.sin(a) * 0.055, x=math.cos(a) * 0.055, v=12))
    for y in (0.3, 0.56, 0.79):
        p.append(tube(0.085, y - 0.015, y + 0.015, GUNBODY, v=24))
    p.append(slab("handle", [(-0.05, 0.1), (0.15, 0.1), (0.15, 0.19), (0.12, 0.19), (0.12, 0.13), (-0.02, 0.13), (-0.02, 0.19), (-0.05, 0.19)], 0.03, GUNDARK, bev=0.004))
    for sx in (-1, 1):
        p.append(shade(rod(0.02, 0.12, (sx * 0.08, -0.2, -0.04), GUNDARK, "z", 12), True))
    p.append(bevel(box((0.12, 0.2, 0.16), (-0.16, 0.0, -0.06), GUNDARK), 0.012))
    for k in range(6):  # ammo belt
        p.append(box((0.03, 0.02, 0.05), (-0.1 + k * 0.016, 0.05, -0.02 + k * 0.012), GOLD))
    return p


def rocket_launcher():
    p = [tube(0.075, -0.38, 0.86, GUNBODY, v=24)]
    p.append(cone_y(0.075, 0.1, 0.85, 0.95, GUNDARK, v=24))
    p.append(cone_y(0.095, 0.075, -0.46, -0.38, GUNDARK, v=24))
    for y in (-0.2, 0.3, 0.72):
        p.append(tube(0.081, y - 0.02, y + 0.02, GUNDARK, v=24))
    p.append(tube(0.077, 0.48, 0.6, RARITY, v=24))
    p.append(shade(prim("cone", loc=(0, 0.93, 0), rot=(-math.pi / 2, 0, 0), m=REDX, radius1=0.05, radius2=0.0, depth=0.1, vertices=16), True))
    p.append(slab("sight", [(0.18, 0.07), (0.34, 0.07), (0.32, 0.15), (0.2, 0.15)], 0.04, GUNDARK, x=0.06, bev=0.006))
    p.append(tube(0.018, 0.33, 0.34, LENS, z=0.12, x=0.06, v=12))
    p.append(slab("grip1", [(0.02, -0.06), (0.09, -0.06), (0.06, -0.2), (-0.01, -0.19)], 0.055, GUNDARK))
    p.append(slab("grip2", [(0.36, -0.06), (0.43, -0.06), (0.41, -0.18), (0.35, -0.17)], 0.055, GUNDARK))
    p.append(bevel(box((0.1, 0.22, 0.05), (0, -0.25, -0.09), GUNDARK), 0.015))  # shoulder pad
    return p


def rocket():
    p = [shade(rod(0.05, 0.4, (0, 0, 0), GUNBODY, "y", 12), True)]
    p.append(shade(prim("cone", loc=(0, 0.28, 0), rot=(-math.pi / 2, 0, 0), m=REDX, radius1=0.05, radius2=0.0, depth=0.18, vertices=12), True))
    for k in range(4):
        a = k * math.pi / 2
        p.append(box((0.01, 0.1, 0.07), (math.cos(a) * 0.06, -0.17, math.sin(a) * 0.06), GUNDARK, rot=(0, -a, 0)))
    return join(p, "Rocket")


def heals():
    # bandage roll
    join([shade(rod(0.12, 0.2, (0, 0, 0.12), CLOTHW, "x", 16), True), shade(rod(0.122, 0.06, (0, 0, 0.12), REDX, "x", 16), True),
          box((0.18, 0.16, 0.02), (0, 0.12, 0.02), CLOTHW, rot=(0.2, 0, 0))], "Heal_bandage")
    # mini shield: small corked bottle
    join([shade(prim("uv", loc=(0, 0, 0.12), scale=(1, 1, 1.1), m=POTION, radius=0.1, segments=14, ring_count=10), True),
          shade(rod(0.035, 0.08, (0, 0, 0.25), BUBBLE, "z", 10), True), shade(rod(0.032, 0.05, (0, 0, 0.3), WOOD, "z", 10), True)], "Heal_mini")
    # shield jar with a clamp lid
    jar = shade(rod(0.14, 0.26, (0, 0, 0.15), POTION, "z", 18), True)
    bevel(jar, 0.04, 3)
    join([jar, shade(rod(0.12, 0.05, (0, 0, 0.3), SILO, "z", 18), True), box((0.02, 0.3, 0.02), (0.13, 0, 0.27), SILO, rot=(0.6, 0, 0)),
          shade(rod(0.145, 0.03, (0, 0, 0.24), SILO, "z", 18), True)], "Heal_shield")
    # med kit: white case with a red cross and a handle
    join([bevel(box((0.46, 0.2, 0.32), (0, 0, 0.16), CLOTHW), 0.04, 2), box((0.26, 0.21, 0.07), (0, 0, 0.17), REDX),
          box((0.07, 0.21, 0.24), (0, 0, 0.17), REDX), box((0.2, 0.05, 0.04), (0, 0, 0.35), DARK)], "Heal_med")


BRASS = mat("Brass", 0xE0AE3C, 0.3)
BTIP = mat("BulletTip", 0xCDD2D8, 0.25)
COPPER = mat("Copper", 0xB9653A, 0.3)
SHELLRED = mat("ShellRed", 0xC8343A, 0.45)
OLIVE = mat("Olive", 0x8A9630, 0.5)
STRIPEO = mat("StripeOrange", 0xF06A1E)


def placed(parts, rz, loc):
    """Join parts built around the origin, then turn about Z and move them."""
    o = join(parts, "tmp")
    o.rotation_euler = (0, 0, rz)
    o.location = loc
    activate(o)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return o


def cartridge(r, length, tip, tip_len, round_nose):
    """A round lying along +Y with its base at y=0, resting on the ground."""
    z = r
    p = [shade(rod(r, length, (0, length / 2, z), BRASS, "y", 16), True)]
    p.append(shade(rod(r * 1.04, length * 0.06, (0, length * 0.08, z), DARK, "y", 16), True))  # extractor groove
    if round_nose:
        p.append(shade(prim("uv", loc=(0, length, z), scale=(1, tip_len / r, 1), m=tip, radius=r * 0.96, segments=16, ring_count=8), True))
    else:
        p.append(shade(prim("cone", loc=(0, length + tip_len / 2, z), rot=(-math.pi / 2, 0, 0), m=tip, radius1=r * 0.96, radius2=0.0, depth=tip_len, vertices=16), True))
    return p


def ammo():
    # light: a fan of short round-nosed pistol rounds
    join([placed(cartridge(0.04, 0.11, BTIP, 0.05, True), -a, (math.sin(a) * 0.2, math.cos(a) * 0.2 - 0.24, 0)) for a in (-0.9, -0.3, 0.3, 0.9)], "Ammo_light")
    # medium: three pointed copper-tipped rifle rounds side by side
    join([placed(cartridge(0.04, 0.2, COPPER, 0.11, False), 0, (x, -0.15, 0)) for x in (-0.1, 0, 0.1)], "Ammo_medium")
    # heavy: one long necked sniper round
    r = 0.055
    p = cartridge(r, 0.36, BTIP, 0.14, False)
    p[-1].location = (0, 0.36 + 0.16, r)
    activate(p[-1]); bpy.ops.object.transform_apply(location=True)
    p.append(shade(prim("cone", loc=(0, 0.39, r), rot=(-math.pi / 2, 0, 0), m=BRASS, radius1=r, radius2=r * 0.62, depth=0.06, vertices=16), True))
    join([placed(p, 0, (0, -0.26, 0))], "Ammo_heavy")
    # shells: two red hulls with steel bases
    def shell():
        R = 0.065
        return [shade(rod(R, 0.22, (0, 0.11 + 0.06, R), SHELLRED, "y", 18), True),
                shade(rod(R * 1.06, 0.07, (0, 0.035, R), BTIP, "y", 18), True),
                shade(rod(R * 1.12, 0.012, (0, 0.006, R), BTIP, "y", 18), True)]
    join([placed(shell(), -0.25, (-0.08, -0.14, 0)), placed(shell(), -0.25, (0.1, -0.1, 0))], "Ammo_shells")

    # rockets: olive warheads with a shark face and an orange band
    def warhead():
        R = 0.06
        q = [shade(rod(0.022, 0.36, (0, 0.18, R), OLIVE, "y", 10), True),
             shade(rod(0.026, 0.04, (0, 0.28, R), STRIPEO, "y", 10), True),
             shade(prim("cone", loc=(0, 0.02, R), rot=(math.pi / 2, 0, 0), m=OLIVE, radius1=0.035, radius2=0.02, depth=0.05, vertices=10), True),
             shade(prim("uv", loc=(0, 0.46, R), scale=(1, 1.7, 1), m=OLIVE, radius=R, segments=14, ring_count=8), True),
             shade(rod(0.02, 0.03, (0, 0.57, R), DARK, "y", 10), True)]
        for s in (-1, 1):
            q.append(shade(prim("uv", loc=(s * 0.03, 0.47, R * 1.75), scale=(1, 1.6, 0.4), m=WHITE, radius=0.016, segments=10, ring_count=6), True))
            q.append(shade(prim("uv", loc=(s * 0.03, 0.475, R * 1.85), scale=(1, 1, 0.4), m=EYE, radius=0.008, segments=8, ring_count=4), True))
        q.append(box((0.07, 0.02, 0.01), (0, 0.42, R * 1.82), WHITE))  # teeth
        return q
    join([placed(warhead(), a, (math.sin(a) * 0.05 + a * 0.08, -0.28, 0)) for a in (-0.35, 0, 0.35)], "Ammo_rockets")


def launch_pad():
    p = [bevel(box((1.6, 1.6, 0.16), (0, 0, 0.08), PADBASE), 0.04)]
    p.append(bevel(box((1.3, 1.3, 0.05), (0, 0, 0.18), PADTOP), 0.02))
    for k in range(4):  # arrows pointing outward... and up
        a = k * math.pi / 2
        p.append(prism("arrow", [(math.cos(a) * 0.3 - math.sin(a) * 0.12, math.sin(a) * 0.3 + math.cos(a) * 0.12, 0.21),
                                 (math.cos(a) * 0.3 + math.sin(a) * 0.12, math.sin(a) * 0.3 - math.cos(a) * 0.12, 0.21),
                                 (math.cos(a) * 0.5, math.sin(a) * 0.5, 0.21)], (0, 0, 1), 0.02, GLOW))
    p.append(rod(0.12, 0.03, (0, 0, 0.21), GLOW, "z", 16))
    return join(p, "LaunchPad")


def willow(name, seed):
    random.seed(seed)
    parts = [shade(rod(0.32, 3.4, (0, 0, 1.7), TRUNK, "z", 8), False)]
    parts.append(shade(jitter(prim("ico", loc=(0, 0, 4.4), scale=(1.5, 1.5, 0.9), m=WILLOW, radius=1.7, subdivisions=1), 0.12), False))
    # drooping fronds hanging all round the crown
    for k in range(18):
        a = k / 18 * 2 * math.pi + random.uniform(-0.1, 0.1)
        r = random.uniform(1.7, 2.4)
        length = random.uniform(2.2, 3.3)
        f = prim("cone", loc=(math.cos(a) * r, math.sin(a) * r, 4.3 - length / 2), rot=(math.pi, 0, 0), m=WILLOW,
                 radius1=random.uniform(0.35, 0.5), radius2=0.08, depth=length, vertices=6)
        parts.append(shade(jitter(f, 0.05), False))
    return join(parts, name)


def cliff(name, seed):
    random.seed(seed)
    c = prim("cube", loc=(0, 0, 2.5), scale=(4.0, 2.2, 5.0), m=CLIFF, size=1)
    modify(c, "SUBSURF", levels=2, render_levels=2, subdivision_type="SIMPLE")
    off = Vector([random.uniform(0, 40) for _ in range(3)])
    for v in c.data.vertices:  # weathered faces with horizontal strata
        n = noise.noise(v.co * 0.9 + off)
        v.co.x += n * 0.35
        v.co.y += n * 0.25 + 0.08 * math.sin(v.co.z * 3.1)
        v.co.z = max(v.co.z, 0.0)
    parts = [shade(c, False)]
    for z in (1.2, 2.6, 3.9):  # darker ledges
        parts.append(shade(jitter(box((4.1, 2.3, 0.18), (0, 0.02, z), CLIFF2), 0.05), False))
    parts.append(shade(jitter(box((4.1, 2.3, 0.3), (0, 0, 5.0), LEAF), 0.06), False))  # grassy top
    return join(parts, name)


# ---------------------------------------------------------------- lake props
REED = mat("Reed", 0x6F8F3A)
CATTAIL = mat("Cattail", 0x6B4223)
LILY = mat("Lily", 0x3F8F3A)
PETAL = mat("Petal", 0xF2A2C8)
PLANK = mat("Plank", 0x8A6440)


def reeds():
    random.seed(51)
    p = []
    for k in range(11):
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(0, 0.35)
        hgt = random.uniform(0.8, 1.4)
        tilt = (random.uniform(-0.15, 0.15), random.uniform(-0.15, 0.15), 0)
        stem = prim("cyl", loc=(math.cos(a) * r, math.sin(a) * r, hgt / 2), rot=tilt, m=REED, radius=0.014, depth=hgt, vertices=6)
        p.append(shade(stem, True))
        if k % 2 == 0:  # cattail head near the top
            top = Vector((math.cos(a) * r, math.sin(a) * r, 0)) + Vector((tilt[1] * hgt * 0.9, -tilt[0] * hgt * 0.9, hgt * 0.92))
            p.append(shade(prim("cyl", loc=top, rot=tilt, m=CATTAIL, radius=0.03, depth=0.16, vertices=10), True))
    for k in range(6):  # long blades
        a = k / 6 * 2 * math.pi
        b = prim("cone", loc=(0, 0, 0), m=REED, radius1=0.05, radius2=0.0, depth=1.0, vertices=3, scale=(1, 0.3, 1))
        for v in b.data.vertices:
            v.co.z += 0.5
            v.co.x += 0.25 * (v.co.z ** 2)
        b.rotation_euler = (0, 0.2, a)
        activate(b)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
        p.append(shade(b, False))
    return join(p, "Reeds")


def lily(name, flower):
    pts = [(math.cos(math.radians(a)) * 0.45, math.sin(math.radians(a)) * 0.45, 0.02) for a in range(25, 341, 15)] + [(0, 0, 0.02)]
    pad = prism("pad", pts, (0, 0, 1), 0.025, LILY)
    p = [shade(pad, False)]
    if flower:
        for k in range(7):
            a = k / 7 * 2 * math.pi
            pet = prim("uv", loc=(math.cos(a) * 0.06, math.sin(a) * 0.06, 0.08), scale=(1, 0.45, 0.35), m=PETAL, radius=0.07, segments=10, ring_count=6)
            pet.rotation_euler = (0, -0.6, a)
            activate(pet)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
            p.append(shade(pet, True))
        p.append(shade(prim("uv", loc=(0, 0, 0.1), m=ACCENT, radius=0.03, segments=8, ring_count=6), True))
    return join(p, name)


def campfire():
    random.seed(52)
    p = []
    for k in range(9):  # stone ring
        a = k / 9 * 2 * math.pi
        st = prim("ico", loc=(math.cos(a) * 0.55, math.sin(a) * 0.55, 0.08), scale=(1.2, 1, 0.8), m=STONE, radius=0.13, subdivisions=2)
        p.append(shade(jitter(st, 0.02), True))
    for k in range(3):  # crossed logs
        a = k / 3 * math.pi
        lg = prim("cyl", loc=(0, 0, 0.12), rot=(0, math.pi / 2 - 0.25, a), m=WOOD, radius=0.07, depth=0.8, vertices=10)
        p.append(shade(lg, True))
    for k, (hh, rr) in enumerate(((0.75, 0.2), (0.55, 0.14), (0.45, 0.12))):  # flames
        a = k * 2.1
        f = prim("cone", loc=(math.cos(a) * 0.08 * k, math.sin(a) * 0.08 * k, 0.2 + hh / 2), m=GLOW, radius1=rr, radius2=0.0, depth=hh, vertices=10)
        p.append(shade(jitter(f, 0.01), True))
    return join(p, "Campfire")


def shack():
    """4.2×3.6 m fishing shack, plank walls 0.2 m thick, 1.2 m doorway on +Y, lean-to roof."""
    W, D, H, T = 4.2, 3.6, 2.8, 0.2
    p = [box((W, T, H + 0.4), (0, -D / 2, (H + 0.4) / 2), PLANK)]
    for sx in (-1, 1):
        side = box((T, D, H + 0.2), (sx * W / 2, 0, (H + 0.2) / 2), PLANK)
        p.append(side)
        p.append(box((W / 2 - 0.6, T, H), (sx * (0.6 + (W / 2 - 0.6) / 2), D / 2, H / 2), PLANK))
    p.append(box((1.2, T, H - 2.1), (0, D / 2, 2.1 + (H - 2.1) / 2), PLANK))
    for k in range(6):  # plank seams
        z = 0.35 + k * 0.42
        p.append(box((W + 0.02, D + 0.02, 0.03), (0, 0, z), GUNDARK))
    p.append(box((W - T, D - T, 0.06), (0, 0, 0.03), FLOOR))
    roof = box((W + 0.6, D + 0.9, 0.16), (0, 0.1, H + 0.35), ROOF, rot=(0.12, 0, 0))
    p.append(roof)
    window(p, (1.0, -D / 2, 1.6), (0, -1, 0), width=0.8, height=0.6)
    return join(p, "Shack")


# ---------------------------------------------------------------- more skins: hats and accessories
def tube_path(name, n, m_ring, pts_fn, r_fn, mtl):
    """General tube through 3-D points with radius r_fn(t)."""
    cs = [pts_fn(i / n) for i in range(n + 1)]
    bm = bmesh.new()
    rings = []
    for i, c in enumerate(cs):
        tan = (Vector(cs[min(i + 1, n)]) - Vector(cs[max(i - 1, 0)])).normalized()
        ref = Vector((0, 1, 0)) if abs(tan.y) < 0.9 else Vector((1, 0, 0))
        s1 = tan.cross(ref).normalized()
        s2 = s1.cross(tan).normalized()
        r = r_fn(i / n)
        rings.append([bm.verts.new(Vector(c) + (s1 * math.cos(k / m_ring * 2 * math.pi) + s2 * math.sin(k / m_ring * 2 * math.pi)) * r) for k in range(m_ring)])
    for i in range(n):
        for k in range(m_ring):
            bm.faces.new((rings[i][k], rings[i][(k + 1) % m_ring], rings[i + 1][(k + 1) % m_ring], rings[i + 1][k]))
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    me.materials.append(mtl)
    return shade(o, True)


def accessories2():
    # hood: deep cowl that frames the face, with a point at the back and a drape on the shoulders
    hood = prim("uv", loc=(0, -0.02, 1.97), scale=(1.12, 1.15, 1.14), m=HATMAIN, radius=0.31, segments=26, ring_count=16)
    keep(hood, lambda c: not (c.y > 0.1 and c.z < 2.13) and c.z > 1.66)
    modify(hood, "SOLIDIFY", thickness=0.03)
    tip = prim("cone", loc=(0, -0.33, 2.02), rot=(-2.0, 0, 0), m=HATMAIN, radius1=0.14, radius2=0.0, depth=0.3, vertices=12)
    ADD["torus"](location=(0, 0, 1.64), major_radius=0.25, minor_radius=0.07, major_segments=24, minor_segments=8)
    drape = bpy.context.active_object
    drape.data.materials.append(HATMAIN)
    join([shade(hood, True), shade(tip, True), shade(drape, True)], "Hat_Hood")

    crown = prim("cyl", loc=(0, 0, 2.22), m=HATMAIN, radius=0.235, depth=0.28, vertices=28)
    for v in crown.data.vertices:  # pinched, dented crown
        if v.co.z > 0.1:
            v.co.z -= 0.05 * (1 - abs(v.co.x) / 0.235)
        v.co.y *= 0.88
    bevel(crown, 0.04, 3)
    brim = prim("cyl", loc=(0, 0, 2.09), m=HATMAIN, radius=0.52, depth=0.03, vertices=40)
    for v in brim.data.vertices:  # brim curled up at the sides
        v.co.z += 0.13 * (abs(v.co.x) / 0.52) ** 2.2
        v.co.y *= 0.9
    band = prim("cyl", loc=(0, 0, 2.13), m=HATACC, radius=0.238, depth=0.05, vertices=28)
    band.scale.y = 0.88
    join([shade(crown, True), shade(brim, True), shade(band, True)], "Hat_Cowboy")

    dome = prim("uv", loc=(0, 0, 2.06), scale=(1, 1, 0.8), m=HATMAIN, radius=0.28, segments=22, ring_count=12)
    keep(dome, lambda c: c.z > 2.05)
    tri = prim("cyl", loc=(0, 0, 2.08), m=HATMAIN, radius=0.44, depth=0.04, vertices=36)
    for v in tri.data.vertices:  # tricorn: brim turned up between three points
        a = math.atan2(v.co.y, v.co.x)
        rr = math.hypot(v.co.x, v.co.y) / 0.44
        v.co.z += 0.2 * rr ** 2 * (0.5 - 0.5 * math.cos(3 * (a - math.pi / 2)))
    skull = [shade(prim("uv", loc=(0, 0.35, 2.17), m=WHITE, radius=0.045, segments=12, ring_count=8), True)]
    for ang in (0.6, -0.6):
        skull.append(box((0.12, 0.02, 0.022), (0, 0.36, 2.12), WHITE, rot=(0, ang, 0)))
    join([shade(dome, True), shade(tri, True)] + skull, "Hat_Pirate")

    helm = prim("uv", loc=(0, 0, 1.98), scale=(1, 1.05, 1), m=HATMAIN, radius=0.32, segments=24, ring_count=14)
    keep(helm, lambda c: c.z > 1.96)
    band = shade(prim("cyl", loc=(0, 0, 1.99), m=HATMAIN, radius=0.325, depth=0.07, vertices=24), True)
    nose = bevel(box((0.05, 0.03, 0.2), (0, 0.33, 1.92), HATMAIN), 0.01)
    horns = []
    for sx in (-1, 1):
        P0, P1, P2 = Vector((sx * 0.27, 0, 2.08)), Vector((sx * 0.55, 0.02, 2.1)), Vector((sx * 0.56, 0.06, 2.45))
        horns.append(tube_path("horn", 16, 12, lambda t, P0=P0, P1=P1, P2=P2: bez(P0, P1, P2, t), lambda t: 0.075 * (1 - t) + 0.004, HATACC))
    join([shade(helm, True), band, nose] + horns, "Hat_Viking")

    cowl = prim("uv", loc=(0, 0, 1.95), scale=(1.06, 1.1, 1.08), m=HATMAIN, radius=0.29, segments=24, ring_count=16)
    keep(cowl, lambda c: c.z > 1.66 and not (c.y > 0.12 and 1.9 < c.z < 2.0))
    modify(cowl, "SOLIDIFY", thickness=0.02)
    ADD["torus"](location=(0, 0, 2.05), major_radius=0.3, minor_radius=0.028, major_segments=28, minor_segments=8)
    hb = bpy.context.active_object
    hb.data.materials.append(HATACC)
    tails = [box((0.05, 0.02, 0.3), (sx * 0.05, -0.32, 1.93), HATACC, rot=(0.5, sx * 0.25, 0)) for sx in (-1, 1)]
    join([shade(cowl, True), shade(hb, True)] + tails, "Hat_Ninja")

    shark = prim("uv", loc=(0, -0.04, 2.0), scale=(1.05, 1.25, 0.98), m=HATMAIN, radius=0.4, segments=28, ring_count=16)
    keep(shark, lambda c: not (c.y > 0.18 and 1.72 < c.z < 2.14) and c.z > 1.62)
    modify(shark, "SOLIDIFY", thickness=0.03)
    teeth = []
    for k in range(9):
        x = -0.22 + k * 0.055
        teeth.append(shade(prim("cone", loc=(x, 0.3, 2.1), rot=(math.pi, 0, 0), m=WHITE, radius1=0.026, radius2=0.0, depth=0.07, vertices=8), True))
        teeth.append(shade(prim("cone", loc=(x, 0.3, 1.76), m=WHITE, radius1=0.024, radius2=0.0, depth=0.06, vertices=8), True))
    fin = prism("fin", [(0, -0.2, 2.33), (0, 0.12, 2.33), (0, -0.28, 2.68)], (1, 0, 0), 0.06, HATMAIN)
    eyes = [shade(prim("uv", loc=(sx * 0.37, 0.12, 2.16), m=EYE, radius=0.05, segments=12, ring_count=8), True) for sx in (-1, 1)]
    join([shade(shark, True), shade(fin, False)] + teeth + eyes, "Hat_Shark")

    rhead = bevel(box((0.52, 0.46, 0.46), (0, 0, 1.95), HATMAIN), 0.07, 3)
    screen = bevel(box((0.42, 0.03, 0.26), (0, 0.23, 1.96), VISOR), 0.02)
    ears = [shade(rod(0.07, 0.06, (sx * 0.28, 0, 1.95), HATACC, "x", 16), True) for sx in (-1, 1)]
    ant = [rod(0.012, 0.22, (0.12, 0, 2.27), DARK, "z", 8), shade(prim("uv", loc=(0.12, 0, 2.39), m=GLOW, radius=0.035, segments=10, ring_count=6), True)]
    neck = shade(rod(0.1, 0.12, (0, 0, 1.68), DARK, "z", 16), True)
    join([shade(rhead, True), shade(screen, True), neck] + ears + ant, "Hat_Robot")

    cband = prim("cyl", loc=(0, 0, 2.14), m=HATMAIN, radius=0.275, depth=0.12, vertices=32, end_fill_type="NOTHING")
    modify(cband, "SOLIDIFY", thickness=0.03)
    pts = []
    for k in range(8):
        a = k / 8 * 2 * math.pi
        pts.append(shade(prim("cone", loc=(math.cos(a) * 0.275, math.sin(a) * 0.275, 2.27), m=HATMAIN, radius1=0.05, radius2=0.0, depth=0.16, vertices=10), True))
        pts.append(shade(prim("uv", loc=(math.cos(a) * 0.29, math.sin(a) * 0.29, 2.13), m=HATACC, radius=0.024, segments=10, ring_count=6), True))
    join([shade(cband, True)] + pts, "Hat_Crown")

    # katana across the back
    blade = tube_path("blade", 12, 8, lambda t: (0, 0, 0.3 + t * 0.75), lambda t: 0.018 * (1 - t ** 3) + 0.002, STEEL)
    blade.scale = (1, 0.35, 1)
    sword = [blade, shade(rod(0.022, 0.26, (0, 0, 0.15), DARK, "z", 12), True), shade(rod(0.06, 0.015, (0, 0, 0.29), ACCENT, "z", 16), True)]
    sw = join(sword, "tmp_sword")
    sw.rotation_euler = (0, 0.75, 0)
    sw.location = (-0.3, -0.24, 0.85)
    activate(sw)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    sw.name = sw.data.name = "Acc_Sword"

    feathers = []
    for sx in (-1, 1):
        for k in range(5):
            a = 0.25 + k * 0.22
            f = prim("uv", loc=(sx * (0.2 + 0.18 * k), -0.28, 1.45 + 0.12 * k - 0.04 * k * k), scale=(0.55, 0.08, 0.16), m=HATACC, radius=0.3, segments=12, ring_count=8)
            f.rotation_euler = (0, sx * a, 0)
            activate(f)
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
            feathers.append(shade(f, True))
    join(feathers, "Acc_Wings")


# ---------------------------------------------------------------- build all
torso(); head(); arm(-1); arm(1); leg(-1); leg(1); accessories(); accessories2(); glider(); pickaxe(); pickaxe_ice(); pickaxe_gold()
gun("Gun_ar", ar); gun("Gun_smg", smg); gun("Gun_shotgun", shotgun); gun("Gun_sniper", sniper); gun("Gun_pistol", pistol)
gun("Gun_tac", tactical); gun("Gun_hunting", hunting); gun("Gun_minigun", minigun); gun("Gun_rocket", rocket_launcher)
rocket(); heals(); ammo(); launch_pad(); willow("WillowA", 8); willow("WillowB", 9); cliff("CliffA", 10); cliff("CliffB", 11)
pine("PineA", 1); pine("PineB", 2); round_tree("RoundA", 3); round_tree("RoundB", 4); birch("BirchA", 14); birch("BirchB", 15)
bush("BushA", 12); bush("BushB", 13, berries=True); blade_fan("Fern", 9, 1.1, 0.16, FERN, 0.9, 16, curl=0.35); blade_fan("GrassTuft", 7, 0.55, 0.05, GRASS, 0.35, 17)
rock("RockA", 5); rock("RockB", 6); rock("RockC", 7)
chest(); airship()
house(); windmill(); lighthouse(); silo(); water_tower(); container()
crate(); barrel(); fence(); lamp_post(); hay_bale(); dock(); boat()
reeds(); lily("LilyPad", False); lily("LilyFlower", True); campfire(); shack()

# ---------------------------------------------------------------- ambient occlusion
# Bake soft contact shadows (creases, overhangs, where things meet the ground) into a
# per-corner colour attribute with Cycles. The game multiplies it into each colour.
NO_GROUND = ("Gun_", "Ammo_", "Rocket", "Heal_", "Pickaxe", "Glider", "Airship", "Prop", "MillBlades", "Boat", "ArmL", "ArmR", "Hat_", "Head")


def densify(o, max_edge=1.1, passes=3):
    """Split long edges on big flat faces so baked shading stays local to corners and
    creases instead of smearing across a whole wall (shading is stored per vertex)."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    for _ in range(passes):
        long_edges = [e for e in bm.edges if e.calc_length() > max_edge]
        if not long_edges:
            break
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=1, use_grid_fill=True)
    bm.to_mesh(o.data)
    bm.free()


DENSIFY = ("Cliff", "House", "Shack", "Windmill", "Lighthouse", "Silo", "WaterTower", "Container", "Chest", "Crate", "Dock", "Torso", "Rock")


def bake_ao(samples=48, distance=0.9):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.render.bake.target = "VERTEX_COLORS"
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.light_settings.distance = distance
    ADD["cube"](location=(0, 0, -0.05), size=1)
    ground = bpy.context.active_object
    ground.name = "_ground"
    ground.scale = (60, 60, 0.1)
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o is not ground]
    for o in meshes:
        o.hide_render = True
        if o.name.startswith(DENSIFY) and not o.get("dense"):
            densify(o)
    for o in meshes:
        o.hide_render = False
        ground.hide_render = o.name.startswith(NO_GROUND)
        attrs = o.data.color_attributes
        ao = attrs.get("AO") or attrs.new("AO", "BYTE_COLOR", "CORNER")
        attrs.active_color = ao
        activate(o)
        bpy.ops.object.bake(type="AO")
        o.hide_render = True
    bpy.data.objects.remove(ground)
    for o in meshes:
        o.hide_render = False


# ---------------------------------------------------------------- polish
# Clean, rounded look instead of hard low-poly facets: organic things are smooth-shaded all over;
# hard-surface things get a small bevel on every sharp edge and smooth shading split at 40 degrees,
# so flat faces stay crisp while corners catch a soft highlight.
SMOOTH_ALL = ("Pine", "Round", "Birch", "Bush", "Willow", "Rock", "Cliff")
FLAT = ("Fern", "GrassTuft")  # thin blades read better flat-shaded
SKIP = ("Torso", "Head", "ArmL", "ArmR", "LegL", "LegR", "Hat_", "Acc_", "Glider", "Pickaxe", "Gun_", "Reeds", "Lily", "Campfire", "_ground")


def polish():
    for o in [o for o in bpy.data.objects if o.type == "MESH"]:
        if o.name.startswith(SKIP) or o.name.startswith(FLAT):
            continue
        if o.name.startswith(SMOOTH_ALL):
            shade(o, True)
            continue
        if o.name.startswith(DENSIFY):  # split big faces first so the baked shading stays local
            densify(o, max_edge=2.2, passes=2)
            o["dense"] = 1
        size = max(o.dimensions)
        w = min(0.04, max(0.006, size * 0.005))
        shade(o, True)
        # hardened normals keep flat faces perfectly flat; only the rounded bevel strips shade softly
        modify(o, "BEVEL", width=w, segments=1 if size > 3 else 2, limit_method="ANGLE", angle_limit=math.radians(35),
               use_clamp_overlap=True, harden_normals=True)


polish()


bake_ao(samples=64, distance=0.7)

LEAFY = {"Leaf", "Leaf2", "Willow", "Fern", "Grass"}
TINTED = ("Pine", "Round", "Birch", "Bush", "Willow", "Fern", "GrassTuft")


def tint_foliage():
    """Fold sunlit-top / shaded-underside colour into the AO attribute of leaves: warm
    yellow-green where light hits, cool blue-green underneath, mottled with noise."""
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith(TINTED):
            continue
        me = o.data
        leafy = [i for i, m in enumerate(me.materials) if m and m.name.split(".")[0] in LEAFY]
        if not leafy:
            continue
        vs = [me.vertices[i].co for p in me.polygons if p.material_index in leafy for i in p.vertices]
        z0, z1 = min(v.z for v in vs), max(v.z for v in vs)
        rmax = max(math.hypot(v.x, v.y) for v in vs) or 1
        ao = me.color_attributes["AO"]
        for p in me.polygons:
            if p.material_index not in leafy:
                continue
            for li, vi in zip(p.loop_indices, p.vertices):
                co = me.vertices[vi].co
                h = (co.z - z0) / max(z1 - z0, 1e-3)
                rad = math.hypot(co.x, co.y) / rmax
                n = noise.noise(co * 1.3) * 0.08
                bright = min(1.0, 0.66 + 0.3 * h ** 0.8 + 0.12 * rad + n)
                warm = min(1.0, max(0.0, 0.75 * h + 0.35 * rad - 0.15 + n))
                tint = (0.86 + 0.14 * warm, 1.0, 1.0 - 0.24 * warm)
                c = ao.data[li].color
                a = 0.5 + 0.5 * c[0]
                ao.data[li].color = tuple(max(0.0, min(1.0, 2 * a * bright * t - 1)) for t in tint) + (1.0,)


tint_foliage()
bpy.ops.export_scene.gltf(filepath=GLB, export_format="GLB", export_apply=True, export_yup=True,
                          export_texcoords=False, export_normals=True, use_selection=False,
                          export_vertex_color="ACTIVE")
print("wrote", GLB, os.path.getsize(GLB), "bytes")

# ---------------------------------------------------------------- embed in the game page
with open(GLB, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
with open(HTML, encoding="utf-8") as f:
    page = f.read()
page, n = re.subn(r"/\*GLB_START\*/.*?/\*GLB_END\*/", lambda _: f'/*GLB_START*/"{b64}"/*GLB_END*/', page, flags=re.S)
if n:
    with open(HTML, "w", encoding="utf-8") as f:
        f.write(page)
    print("embedded into", os.path.normpath(HTML))
else:
    print("no GLB marker found in", HTML)
