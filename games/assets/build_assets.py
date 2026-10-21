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
# Feet at z=0, facing +Y, roughly 2.25 m tall to the top of the cap.


def torso():
    t = box((0.6, 0.34, 0.66), (0, 0, 1.24), SUIT)
    for v in t.data.vertices:  # broaden the shoulders
        if v.co.z > 0:
            v.co.x *= 1.16
            v.co.y *= 1.05
    bevel(t, 0.07, 3)
    shade(t, True)
    parts = [t]
    parts.append(bevel(box((0.56, 0.32, 0.2), (0, 0, 0.82), PANTS), 0.05, 2))  # hips
    parts.append(bevel(box((0.64, 0.38, 0.09), (0, 0, 0.92), DARK), 0.02))  # belt
    parts.append(bevel(box((0.12, 0.03, 0.08), (0, 0.2, 0.92), ACCENT), 0.01))  # buckle
    parts.append(rod(0.075, 0.025, (0.13, 0.18, 1.38), ACCENT, "y", 16))  # chest badge
    pack = bevel(box((0.46, 0.2, 0.52), (0, -0.27, 1.25), DARK), 0.06, 3)
    parts.append(shade(pack, True))
    parts.append(bevel(box((0.36, 0.06, 0.2), (0, -0.39, 1.14), ACCENT), 0.02))  # pack pocket
    for x in (-0.16, 0.16):  # straps
        parts.append(box((0.06, 0.03, 0.5), (x, 0.185, 1.3), DARK))
    parts.append(rod(0.15, 0.08, (0, 0, 1.6), DARK, "z", 16))  # collar
    return join(parts, "Torso")


def head():
    parts = [rod(0.09, 0.14, (0, 0, 1.67), SKIN, "z", 12)]
    h = box((0.5, 0.48, 0.52), (0, 0, 1.93), SKIN)
    subsurf(h, 2)
    parts.append(shade(h, True))
    for x in (-0.095, 0.095):
        parts.append(shade(prim("uv", loc=(x, 0.205, 1.95), m=WHITE, radius=0.05, segments=12, ring_count=8), True))
        parts.append(shade(prim("uv", loc=(x, 0.24, 1.95), m=EYE, radius=0.028, segments=10, ring_count=6), True))
        parts.append(box((0.09, 0.02, 0.022), (x, 0.225, 2.02), DARK, rot=(0, -0.15 if x < 0 else 0.15, 0)))  # brows
        parts.append(shade(prim("uv", loc=(x * 2.6, 0, 1.93), m=SKIN, radius=0.06, segments=10, ring_count=6), True))  # ears
    parts.append(box((0.1, 0.02, 0.02), (0, 0.235, 1.83), DARK))  # mouth
    cap = prim("uv", loc=(0, -0.01, 2.04), scale=(1, 1, 0.72), m=SUIT, radius=0.285, segments=20, ring_count=10)
    keep(cap, lambda c: c.z > 2.02)
    parts.append(shade(cap, True))
    parts.append(bevel(box((0.4, 0.22, 0.035), (0, 0.24, 2.04), SUIT, rot=(-0.12, 0, 0)), 0.012))  # brim
    parts.append(rod(0.04, 0.02, (0, 0, 2.245), ACCENT, "z", 10))  # button on top
    return join(parts, "Head")


def arm(side):
    x = 0.44 * side
    parts = [shade(prim("uv", loc=(x, 0, 1.56), m=SUIT, radius=0.13, segments=14, ring_count=8), True)]
    parts.append(shade(rod(0.092, 0.38, (x, 0, 1.38), SUIT, "z", 12), True))
    parts.append(shade(rod(0.08, 0.06, (x, 0, 1.18), ACCENT, "z", 12), True))  # cuff
    parts.append(shade(rod(0.075, 0.28, (x, 0, 1.02), SKIN, "z", 12), True))
    hand = box((0.14, 0.15, 0.15), (x, 0.01, 0.84), GLOVE)
    subsurf(hand, 1)
    parts.append(shade(hand, True))
    return join(parts, "ArmL" if side < 0 else "ArmR", origin=(x, 0, 1.56))


def leg(side):
    x = 0.16 * side
    parts = [shade(rod(0.13, 0.42, (x, 0, 0.62), PANTS, "z", 12), True)]
    parts.append(shade(rod(0.115, 0.36, (x, 0, 0.3), PANTS, "z", 12), True))
    parts.append(bevel(box((0.17, 0.06, 0.14), (x, 0.1, 0.45), DARK), 0.02))  # knee pad
    parts.append(shade(bevel(box((0.22, 0.34, 0.16), (x, 0.05, 0.08), BOOT), 0.05, 3), True))
    parts.append(box((0.23, 0.35, 0.03), (x, 0.05, 0.015), DARK))  # sole
    return join(parts, "LegL" if side < 0 else "LegR", origin=(x, 0, 0.8))


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


def pickaxe():
    parts = [shade(rod(0.035, 1.0, (0, 0, 0.2), WOOD, "z", 10), True)]
    parts.append(shade(rod(0.045, 0.22, (0, 0, -0.18), ACCENT, "z", 10), True))  # grip wrap
    parts.append(bevel(box((0.12, 0.12, 0.14), (0, 0, 0.7), GUNDARK), 0.02))  # collar
    for sx in (-1, 1):
        blade = prim("cone", loc=(sx * 0.27, 0, 0.66), rot=(0, sx * math.radians(100), 0), m=METAL,
                     radius1=0.07, radius2=0.0, depth=0.46, vertices=8)
        parts.append(blade)
    return join(parts, "Pickaxe")


# ---------------------------------------------------------------- weapons (barrel along +Y)
def gun(name, parts_fn):
    parts = parts_fn()
    return join(parts, name)


def ar():
    p = [bevel(box((0.09, 0.5, 0.13), (0, 0.22, 0), GUNBODY), 0.012)]
    p.append(bevel(box((0.075, 0.3, 0.12), (0, -0.17, -0.02), GUNDARK), 0.015))  # stock
    p.append(bevel(box((0.09, 0.05, 0.15), (0, -0.33, -0.03), GUNBODY), 0.01))  # butt
    p.append(bevel(box((0.1, 0.32, 0.1), (0, 0.62, -0.005), GUNDARK), 0.012))  # handguard
    p.append(rod(0.022, 0.34, (0, 0.94, 0.01), GUNDARK, "y"))
    p.append(rod(0.032, 0.08, (0, 1.1, 0.01), GUNBODY, "y"))  # muzzle brake
    p.append(box((0.05, 0.22, 0.04), (0, 0.24, 0.085), GUNDARK))  # rail
    p.append(rod(0.032, 0.16, (0, 0.25, 0.13), GUNDARK, "y"))  # scope tube
    p.append(rod(0.036, 0.01, (0, 0.33, 0.13), LENS, "y"))
    p.append(box((0.06, 0.08, 0.24), (0, 0.33, -0.16), GUNDARK, rot=(0.25, 0, 0)))  # magazine
    p.append(box((0.06, 0.07, 0.16), (0, 0.05, -0.12), GUNDARK, rot=(-0.3, 0, 0)))  # grip
    p.append(box((0.096, 0.3, 0.03), (0, 0.22, 0.04), RARITY))
    return p


def smg():
    p = [bevel(box((0.085, 0.36, 0.12), (0, 0.15, 0), GUNBODY), 0.012)]
    p.append(rod(0.034, 0.2, (0, 0.43, 0.01), GUNDARK, "y"))  # shroud
    p.append(rod(0.018, 0.1, (0, 0.58, 0.01), GUNDARK, "y"))
    p.append(box((0.05, 0.07, 0.28), (0, 0.13, -0.19), GUNDARK))  # mag
    p.append(box((0.055, 0.06, 0.14), (0, -0.01, -0.11), GUNDARK, rot=(-0.25, 0, 0)))
    for z in (-0.03, 0.04):  # wire stock
        p.append(box((0.02, 0.22, 0.02), (0, -0.13, z), GUNDARK))
    p.append(box((0.02, 0.02, 0.1), (0, -0.24, 0.005), GUNDARK))
    p.append(box((0.03, 0.04, 0.04), (0, 0.3, 0.075), GUNDARK))  # sight
    p.append(box((0.09, 0.22, 0.03), (0, 0.15, 0.04), RARITY))
    return p


def shotgun():
    p = [bevel(box((0.09, 0.32, 0.12), (0, 0.1, 0), GUNBODY), 0.012)]
    p.append(rod(0.028, 0.6, (0, 0.55, 0.025), GUNDARK, "y"))
    p.append(rod(0.024, 0.48, (0, 0.5, -0.035), GUNDARK, "y"))  # magazine tube
    p.append(bevel(box((0.085, 0.2, 0.085), (0, 0.42, -0.04), WOOD), 0.02))  # pump
    stock = bevel(box((0.07, 0.34, 0.12), (0, -0.2, -0.04), WOOD, rot=(0.12, 0, 0)), 0.02)
    p.append(stock)
    p.append(box((0.055, 0.06, 0.13), (0, -0.02, -0.11), WOOD, rot=(-0.3, 0, 0)))
    p.append(box((0.02, 0.03, 0.03), (0, 0.84, 0.06), ACCENT))  # bead sight
    p.append(box((0.095, 0.18, 0.03), (0, 0.1, 0.045), RARITY))
    return p


def sniper():
    p = [bevel(box((0.09, 0.46, 0.12), (0, 0.2, 0), GUNBODY), 0.012)]
    p.append(rod(0.022, 0.78, (0, 0.82, 0.01), GUNDARK, "y"))
    p.append(rod(0.03, 0.1, (0, 1.23, 0.01), GUNBODY, "y"))
    p.append(rod(0.042, 0.4, (0, 0.24, 0.13), GUNDARK, "y"))  # scope
    p.append(rod(0.052, 0.07, (0, 0.46, 0.13), GUNDARK, "y"))
    p.append(rod(0.05, 0.012, (0, 0.5, 0.13), LENS, "y"))
    for y in (0.14, 0.34):
        p.append(box((0.03, 0.03, 0.06), (0, y, 0.08), GUNDARK))
    p.append(rod(0.015, 0.08, (0.07, 0.05, 0.02), GUNDARK, "x"))  # bolt
    p.append(shade(prim("uv", loc=(0.11, 0.05, 0.02), m=GUNDARK, radius=0.022, segments=8, ring_count=6), True))
    p.append(bevel(box((0.075, 0.38, 0.13), (0, -0.23, -0.03), WOOD), 0.02))
    p.append(box((0.055, 0.06, 0.14), (0, 0.0, -0.11), WOOD, rot=(-0.3, 0, 0)))
    p.append(box((0.05, 0.06, 0.08), (0, 0.24, -0.09), GUNDARK))
    p.append(box((0.096, 0.3, 0.03), (0, 0.2, 0.04), RARITY))
    return p


def pistol():
    p = [bevel(box((0.07, 0.3, 0.08), (0, 0.12, 0.035), GUNBODY), 0.01)]
    p.append(box((0.065, 0.24, 0.05), (0, 0.1, -0.03), GUNDARK))
    p.append(bevel(box((0.06, 0.085, 0.17), (0, 0.0, -0.11), GUNDARK, rot=(-0.25, 0, 0)), 0.01))
    p.append(rod(0.014, 0.04, (0, 0.28, 0.035), GUNDARK, "y"))
    p.append(box((0.02, 0.02, 0.02), (0, 0.25, 0.085), ACCENT))
    p.append(box((0.072, 0.12, 0.025), (0, 0.12, 0.065), RARITY))
    return p


# ---------------------------------------------------------------- nature
def pine(name, seed):
    random.seed(seed)
    parts = [shade(rod(0.24, 2.2, (0, 0, 1.1), TRUNK, "z", 8), False)]
    tiers = [(1.9, 2.6, 1.5), (1.5, 2.2, 2.9), (1.05, 1.8, 4.2), (0.6, 1.3, 5.3)]
    for r, d, z in tiers:
        c = prim("cone", loc=(0, 0, z + d / 2), rot=(0, 0, random.uniform(0, 6.3)), m=LEAF,
                 radius1=r * random.uniform(0.92, 1.08), radius2=0, depth=d, vertices=9)
        jitter(c, 0.1)
        parts.append(shade(c, False))
    return join(parts, name)


def round_tree(name, seed):
    random.seed(seed)
    trunk = shade(rod(0.26, 3.2, (0, 0, 1.6), TRUNK, "z", 8), False)
    parts = [trunk]
    branch = rod(0.1, 1.0, (0.3, 0, 2.8), TRUNK, "z", 6)
    branch.rotation_euler = (0, 0.7, 0)
    activate(branch)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    parts.append(shade(branch, False))
    for loc, r in [((0, 0, 4.0), 1.55), ((0.95, 0.3, 3.5), 1.1), ((-0.85, -0.4, 3.6), 1.05), ((0.1, -0.7, 4.7), 1.0),
                   ((-0.3, 0.8, 4.5), 0.9)]:
        b = prim("ico", loc=loc, m=LEAF, radius=r * random.uniform(0.9, 1.1), subdivisions=1)
        jitter(b, 0.13)
        parts.append(shade(b, False))
    return join(parts, name)


def rock(name, seed):
    random.seed(seed)
    r = prim("ico", m=ROCK, radius=1.0, subdivisions=2)
    off = Vector([random.uniform(0, 50) for _ in range(3)])
    for v in r.data.vertices:
        n = noise.noise(v.co * 1.4 + off)
        v.co *= 1 + 0.28 * n
        v.co.z = max(v.co.z, -0.35)
    jitter(r, 0.05)
    modify(r, "DECIMATE", ratio=0.55)
    return join([shade(r, False)], name)


# ---------------------------------------------------------------- props
def chest():
    base = bevel(box((1.2, 0.8, 0.6), (0, 0, 0.3), CHESTWOOD), 0.03)
    parts = [base]
    for x in (-0.42, 0.42):
        parts.append(box((0.09, 0.84, 0.62), (x, 0, 0.3), CHESTMETAL))
    parts.append(bevel(box((0.16, 0.05, 0.2), (0, 0.42, 0.5), ACCENT), 0.015))  # lock plate
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
    """12×12 m, walls 0.4 m thick and 4.4 m tall, doorway 2.8×3 m on the +Y side.
    Matches the game's collision boxes exactly."""
    W, T, H, h = 12.0, 0.4, 4.4, 6.0
    p = [box((W, T, H), (0, -h, H / 2), HOUSEWALL),
         box((T, W - T, H), (h, 0, H / 2), HOUSEWALL),
         box((T, W - T, H), (-h, 0, H / 2), HOUSEWALL)]
    seg = h - 1.4
    for s in (-1, 1):
        p.append(box((seg, T, H), (s * (1.4 + seg / 2), h, H / 2), HOUSEWALL))
    p.append(box((2.8, T, H - 3), (0, h, 3 + (H - 3) / 2), HOUSEWALL))
    for x in (-h, h):  # corner posts
        for y in (-h, h):
            p.append(box((0.55, 0.55, H + 0.05), (x, y, H / 2), TRIM))
    for x in (-3, 3):
        window(p, (x, -h, 2.2), (0, -1, 0))
    for y in (-3, 3):
        window(p, (h, y, 2.2), (1, 0, 0))
        window(p, (-h, y, 2.2), (-1, 0, 0))
    for x in (-3.9, 3.9):
        window(p, (x, h, 2.2), (0, 1, 0), width=1.2)
    for s in (-1, 1):  # door frame
        p.append(box((0.2, 0.6, 3.05), (s * 1.5, h, 1.52), TRIM))
    p.append(box((3.2, 0.6, 0.25), (0, h, 3.1), TRIM))
    p.append(bevel(box((3.6, 1.3, 0.14), (0, h + 0.85, 0.07), STONE), 0.03))  # porch step
    p.append(box((W - T, W - T, 0.04), (0, 0, 0.02), FLOOR))
    # gabled roof, ridge along X
    rise, half = 2.6, h + 0.6
    ang = math.atan2(rise, half)
    length = math.hypot(half, rise)
    for s in (-1, 1):
        # tilt each slab so its outer (eave) edge is low and its inner edge meets the ridge
        slab = box((W + 1.2, length, 0.26), (0, s * half / 2, H + rise / 2 + 0.13), ROOF, rot=(-s * ang, 0, 0))
        p.append(slab)
    p.append(box((W + 1.3, 0.45, 0.28), (0, 0, H + rise + 0.18), MILLROOF))  # ridge cap
    for x in (-h, h):  # gable ends
        p.append(prism("gable", [(x, -h, H), (x, h, H), (x, 0, H + rise)], (1, 0, 0), T, HOUSEWALL))
    p.append(box((1.0, 1.0, 2.6), (3.4, -2.2, H + 1.9), BRICK))  # chimney
    p.append(box((1.2, 1.2, 0.2), (3.4, -2.2, H + 3.25), STONE))
    return join(p, "House")


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


# ---------------------------------------------------------------- build all
torso(); head(); arm(-1); arm(1); leg(-1); leg(1); glider(); pickaxe()
gun("Gun_ar", ar); gun("Gun_smg", smg); gun("Gun_shotgun", shotgun); gun("Gun_sniper", sniper); gun("Gun_pistol", pistol)
pine("PineA", 1); pine("PineB", 2); round_tree("RoundA", 3); round_tree("RoundB", 4)
rock("RockA", 5); rock("RockB", 6); rock("RockC", 7)
chest(); airship()
house(); windmill(); lighthouse(); silo(); water_tower(); container()
crate(); barrel(); fence(); lamp_post(); hay_bale(); dock(); boat()

bpy.ops.export_scene.gltf(filepath=GLB, export_format="GLB", export_apply=True, export_yup=True,
                          export_texcoords=False, export_normals=True, use_selection=False)
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
