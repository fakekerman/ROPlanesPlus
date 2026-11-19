#!/usr/bin/env python3
"""
Procedural Launch Pylon (ROPlanes-ProcPylon): default model, textures and editor icon.

The plugin (ModuleROPPLaunchPylon + PylonMeshGenerator.cs) rebuilds the meshes from the part's
shape fields at runtime; this script ports that geometry 1:1 for the prefab model and the icon.
Keep the two in step.

Part space: +Y forward, +Z down (towards the released aircraft), origin at the centre of the mount
face (z = 0); the hook face is at z = height.

Outputs (GameData/ROPlanesPlus/Parts/proc_pylon/):
  proc_pylon.mu                 pylonBody (mat 0), pylonHooks (mat 1), pylonCollider (convex)
  ropp_pylon_<livery>.png       tiling paint maps, 1 tile per metre, RGB + gloss in A
  ropp_pylon_NRM.png            tiling normal map (panel lines, rivets)
  ropp_pylon_hardware.png       hooks and sway braces (dark steel)
  ../@thumbs/ROPlanes-ProcPylon_icon.png
"""

import math
import os
import random

from generate_models_and_textures import MeshBuilder, MuWriter, write_png, normalize3

PART_ID = 'proc_pylon'
PART_NAME = 'ROPlanes-ProcPylon'
TILE = 1.0          # metres per texture tile (PylonMeshGenerator.TileMetres)
TEX = 512

# Default shape: must match the KSPField defaults in ModuleROPPLaunchPylon.cs
DEFAULT_SHAPE = dict(length=2.4, height=0.55, width=0.30, bottom_length=0.75, bottom_width=1.0,
                     sweep=0.12, profile=0, hooks=True)

# key, title, RGB, gloss (alpha), panel tone variation. Order = B9 subtype order (first = default);
# generate_configs.PYLON_LIVERIES reads this list.
LIVERIES = [
    ('metal', 'Natural Metal', (176, 181, 188), 205, 0.07),
    ('white', 'Gloss White', (234, 235, 231), 165, 0.025),
    ('grey', 'Light Grey', (158, 164, 168), 105, 0.03),
    ('black', 'Gloss Black', (30, 32, 35), 185, 0.05),
    ('orange', 'Test Orange', (226, 104, 30), 150, 0.03),
]


# ---------------------------------------------------------------------------------------------
# Geometry (port of PylonMeshGenerator.cs)
# ---------------------------------------------------------------------------------------------

def aerofoil_thickness(s):
    s = min(1.0, max(0.0, s))
    p = 0.2969 * math.sqrt(s) - 0.1260 * s - 0.3516 * s * s + 0.2843 * s ** 3 - 0.1036 * s ** 4
    return max(0.0, p / 0.1)


def outline(profile, yF, yA, half_w, res):
    chord = max(0.001, yF - yA)
    if profile == 2:
        return [[(half_w, yA), (half_w, yF)], [(half_w, yF), (-half_w, yF)],
                [(-half_w, yF), (-half_w, yA)], [(-half_w, yA), (half_w, yA)]]
    run = []
    if profile == 1:
        e = min(half_w, 0.5 * chord)
        for i in range(res + 1):
            th = math.pi * i / res
            run.append((half_w * math.cos(th), yF - e + e * math.sin(th)))
        for i in range(res + 1):
            th = math.pi + math.pi * i / res
            run.append((half_w * math.cos(th), yA + e + e * math.sin(th)))
        run.append(run[0])
        return [run]
    for i in range(res, -1, -1):
        s = 0.5 * (1.0 - math.cos(math.pi * i / res))
        run.append((half_w * aerofoil_thickness(s), yF - s * chord))
    for i in range(1, res + 1):
        s = 0.5 * (1.0 - math.cos(math.pi * i / res))
        run.append((-half_w * aerofoil_thickness(s), yF - s * chord))
    return [run]


def body_resolution(profile, collider):
    if profile == 2:
        return 1
    if profile == 1:
        return 3 if collider else 12
    return 6 if collider else 24


class Shape:
    def __init__(self, d):
        self.length, self.height, self.width = d['length'], d['height'], d['width']
        self.bl, self.bw, self.sweep = d['bottom_length'], d['bottom_width'], d['sweep']
        self.profile, self.hooks = d['profile'], d['hooks']
        self.top_front, self.top_aft = 0.5 * self.length, -0.5 * self.length
        self.bottom_length = self.length * self.bl
        self.bottom_centre = -self.sweep * self.length
        self.bottom_front = self.bottom_centre + 0.5 * self.bottom_length
        self.bottom_aft = self.bottom_centre - 0.5 * self.bottom_length
        self.top_hw = 0.5 * self.width
        self.bottom_hw = 0.5 * self.width * self.bw
        self.k = min(3.0, max(0.6, self.width / 0.3))


def bottom_half_width_at(sh, y):
    chord = max(0.001, sh.bottom_front - sh.bottom_aft)
    s = min(1.0, max(0.0, (sh.bottom_front - y) / chord))
    hw = sh.bottom_hw
    if sh.profile == 0:
        return hw * aerofoil_thickness(s)
    if sh.profile == 1:
        e = min(hw, 0.5 * chord)
        d = min(s * chord, (1.0 - s) * chord)
        if d >= e or e < 1e-4:
            return hw
        q = 1.0 - d / e
        return hw * math.sqrt(max(0.0, 1.0 - q * q))
    return hw


def hook_stations(sh):
    if sh.bottom_length < 0.8:
        return [sh.bottom_centre]
    return [sh.bottom_centre + 0.25 * sh.bottom_length, sh.bottom_centre - 0.25 * sh.bottom_length]


def _side_normal(along, down, p, yc):
    a = (along[0], along[1], 0.0)
    n = (a[1] * down[2] - a[2] * down[1], a[2] * down[0] - a[0] * down[2], a[0] * down[1] - a[1] * down[0])
    out = (p[0], p[1] - yc, 0.0)
    if n[0] * out[0] + n[1] * out[1] < 0.0:
        n = (-n[0], -n[1], -n[2])
    if n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 1e-12:
        return normalize3(*n)
    return normalize3(*out) if out[0] ** 2 + out[1] ** 2 > 1e-12 else (0.0, 1.0, 0.0)


def _run_length(run):
    return sum(math.dist(run[j], run[j - 1]) for j in range(1, len(run)))


def _flatten(runs):
    pts = []
    for run in runs:
        for p in run:
            if not pts or (pts[-1][0] - p[0]) ** 2 + (pts[-1][1] - p[1]) ** 2 > 1e-10:
                pts.append(p)
    if len(pts) > 1 and (pts[0][0] - pts[-1][0]) ** 2 + (pts[0][1] - pts[-1][1]) ** 2 < 1e-10:
        pts.pop()
    return pts


def section_area(profile, yF, yA, half_w):
    pts = _flatten(outline(profile, yF, yA, half_w, body_resolution(profile, False)))
    a = sum(pts[j][0] * pts[(j + 1) % len(pts)][1] - pts[(j + 1) % len(pts)][0] * pts[j][1] for j in range(len(pts)))
    return abs(0.5 * a)


# Mass model: ModuleROPPLaunchPylon.ComputeMass (baseMass + massPerVolume * volume + hooks)
MASS_BASE, MASS_PER_M3, MASS_HOOK = 0.008, 0.20, 0.004
COST_BASE, COST_PER_TON = 3.0, 60.0


def pylon_mass(d=None):
    sh = Shape(d or DEFAULT_SHAPE)
    vol = 0.5 * (section_area(sh.profile, sh.top_front, sh.top_aft, sh.top_hw) +
                 section_area(sh.profile, sh.bottom_front, sh.bottom_aft, sh.bottom_hw)) * sh.height
    m = MASS_BASE + MASS_PER_M3 * vol
    if sh.hooks:
        m += MASS_HOOK * len(hook_stations(sh)) * sh.k * sh.k
    return m


def build_body(sh, collider=False):
    mb = MeshBuilder()
    res = body_resolution(sh.profile, collider)
    h = max(0.01, sh.height)
    top = outline(sh.profile, sh.top_front, sh.top_aft, sh.top_hw, res)
    bot = outline(sh.profile, sh.bottom_front, sh.bottom_aft, sh.bottom_hw, res)
    yc_top = 0.5 * (sh.top_front + sh.top_aft)
    yc_bot = 0.5 * (sh.bottom_front + sh.bottom_aft)
    total_top = sum(_run_length(r) for r in top)
    total_bot = sum(_run_length(r) for r in bot)
    u_scale = 0.5 * (total_top + total_bot) / max(1e-4, total_top) / TILE
    u_scale_b = 0.5 * (total_top + total_bot) / max(1e-4, total_bot) / TILE
    arc_t = arc_b = 0.0
    for rt, rb in zip(top, bot):
        n = len(rt)
        closed = n > 2 and (rt[0][0] - rt[-1][0]) ** 2 + (rt[0][1] - rt[-1][1]) ** 2 < 1e-10
        it, ib = [], []
        for j in range(n):
            if j > 0:
                arc_t += math.dist(rt[j], rt[j - 1])
                arc_b += math.dist(rb[j], rb[j - 1])
            ja, jb = j - 1, j + 1
            if closed:
                if ja < 0:
                    ja = n - 2
                if jb > n - 1:
                    jb = 1
            else:
                ja, jb = max(ja, 0), min(jb, n - 1)
            pt = (rt[j][0], rt[j][1], 0.0)
            pb = (rb[j][0], rb[j][1], h)
            down = (pb[0] - pt[0], pb[1] - pt[1], pb[2] - pt[2])
            nt = _side_normal((rt[jb][0] - rt[ja][0], rt[jb][1] - rt[ja][1]), down, pt, yc_top)
            nb = _side_normal((rb[jb][0] - rb[ja][0], rb[jb][1] - rb[ja][1]), down, pb, yc_bot)
            it.append(mb.add_vertex(pt, (arc_t * u_scale, 0.0), nt))
            ib.append(mb.add_vertex(pb, (arc_b * u_scale_b, -h / TILE), nb))
        for j in range(n - 1):
            mb.add_quad(it[j], it[j + 1], ib[j + 1], ib[j])
    for pts, z, yc, nz in ((_flatten(top), 0.0, yc_top, -1.0), (_flatten(bot), h, yc_bot, 1.0)):
        nrm = (0.0, 0.0, nz)
        c = mb.add_vertex((0.0, yc, z), (yc / TILE, 0.5), nrm)
        idx = [mb.add_vertex((p[0], p[1], z), (p[1] / TILE, 0.5 + p[0] / TILE), nrm) for p in pts]
        for j in range(len(pts)):
            mb.add_tri(c, idx[j], idx[(j + 1) % len(pts)])
    return mb.finalize()


HW_UV = (0.5, 0.5)


def _face(mb, c, u, v, n):
    pts = [(c[0] - u[0] - v[0], c[1] - u[1] - v[1], c[2] - u[2] - v[2]),
           (c[0] + u[0] - v[0], c[1] + u[1] - v[1], c[2] + u[2] - v[2]),
           (c[0] + u[0] + v[0], c[1] + u[1] + v[1], c[2] + u[2] + v[2]),
           (c[0] - u[0] + v[0], c[1] - u[1] + v[1], c[2] - u[2] + v[2])]
    ids = [mb.add_vertex(p, HW_UV, n) for p in pts]
    mb.add_quad(*ids)


def _box(mb, c, he):
    ex, ey, ez = (he[0], 0.0, 0.0), (0.0, he[1], 0.0), (0.0, 0.0, he[2])

    def add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    _face(mb, add(c, ex), ey, ez, (1.0, 0.0, 0.0))
    _face(mb, sub(c, ex), ey, ez, (-1.0, 0.0, 0.0))
    _face(mb, add(c, ey), ex, ez, (0.0, 1.0, 0.0))
    _face(mb, sub(c, ey), ex, ez, (0.0, -1.0, 0.0))
    _face(mb, add(c, ez), ex, ey, (0.0, 0.0, 1.0))
    _face(mb, sub(c, ez), ex, ey, (0.0, 0.0, -1.0))


def _beam(mb, p0, p1, hw, hd):
    ax = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    ln = math.sqrt(sum(a * a for a in ax))
    if ln < 1e-5:
        return
    d = (ax[0] / ln, ax[1] / ln, ax[2] / ln)
    e1 = (d[1] * 0.0 - d[2] * 1.0, d[2] * 0.0 - d[0] * 0.0, d[0] * 1.0 - d[1] * 0.0)   # cross(d, +Y)
    e1 = normalize3(*e1) if sum(a * a for a in e1) > 1e-8 else (1.0, 0.0, 0.0)
    e2 = normalize3(d[1] * e1[2] - d[2] * e1[1], d[2] * e1[0] - d[0] * e1[2], d[0] * e1[1] - d[1] * e1[0])
    c = tuple(0.5 * (p0[i] + p1[i]) for i in range(3))
    a = tuple(d[i] * 0.5 * ln for i in range(3))
    b1 = tuple(e1[i] * hw for i in range(3))
    b2 = tuple(e2[i] * hd for i in range(3))
    neg = lambda v: (-v[0], -v[1], -v[2])
    add = lambda p, q: (p[0] + q[0], p[1] + q[1], p[2] + q[2])
    _face(mb, add(c, b1), a, b2, e1)
    _face(mb, add(c, neg(b1)), a, b2, neg(e1))
    _face(mb, add(c, b2), a, b1, e2)
    _face(mb, add(c, neg(b2)), a, b1, neg(e2))
    _face(mb, add(c, a), b1, b2, d)
    _face(mb, add(c, neg(a)), b1, b2, neg(d))


def build_hooks(sh):
    mb = MeshBuilder()
    if not sh.hooks:
        return mb.finalize()
    k, h = sh.k, sh.height
    for y in hook_stations(sh):
        _box(mb, (0.0, y, h + 0.035 * k), (0.012 * k, 0.03 * k, 0.035 * k))
        _box(mb, (0.0, y + 0.035 * k, h + 0.062 * k), (0.012 * k, 0.035 * k, 0.008 * k))
        hw = max(0.02 * k, bottom_half_width_at(sh, y))
        for side in (-1.0, 1.0):
            a = (side * 0.6 * hw, y, h)
            b = (side * (0.6 * hw + 0.11 * k), y, h + 0.06 * k)
            _beam(mb, a, b, 0.010 * k, 0.018 * k)
            _box(mb, (b[0], b[1], b[2] + 0.008 * k), (0.028 * k, 0.04 * k, 0.008 * k))
    return mb.finalize()


# ---------------------------------------------------------------------------------------------
# Textures (tiling, 1 tile = 1 m)
# ---------------------------------------------------------------------------------------------

def _wrap_dist(a, c, n):
    d = abs(a - c) % n
    return min(d, n - d)


def generate_textures():
    """Height field with panel lines (every 0.5 m along the chord, 1 m down) and rivet rows, panel
    tone variation and fine noise. Returns ({key: rgba}, nrm_rgba, hardware_rgba, hw_size)."""
    W = H = TEX
    rnd = random.Random(1947)
    panel_px = W // 2                     # 0.5 m panels across
    lines_x = [0, panel_px]
    lines_y = [0]
    rivet_pitch = 12                      # ~2.3 cm
    rivet_off = 7
    height = [0.0] * (W * H)
    tone = [0.0] * (W * H)
    panel_tone = {(i, 0): rnd.uniform(-1.0, 1.0) for i in range(2)}
    noise = [rnd.uniform(-1.0, 1.0) for _ in range(W * H)]
    for py in range(H):
        for px in range(W):
            hv = 0.0
            d_line = min([_wrap_dist(px, c, W) for c in lines_x] + [_wrap_dist(py, c, H) for c in lines_y])
            if d_line < 1.3:
                hv -= 1.0 - d_line / 1.3
            # rivet rows beside each panel line
            for c in lines_x:
                for off in (-rivet_off, rivet_off):
                    dx = _wrap_dist(px, (c + off) % W, W)
                    if dx < 3:
                        dy = _wrap_dist(py % rivet_pitch, rivet_pitch // 2, rivet_pitch)
                        r2 = dx * dx + dy * dy
                        if r2 < 4.5:
                            hv += 0.55 * (1.0 - r2 / 4.5)
            for c in lines_y:
                for off in (-rivet_off, rivet_off):
                    dy = _wrap_dist(py, (c + off) % H, H)
                    if dy < 3:
                        dx = _wrap_dist(px % rivet_pitch, rivet_pitch // 2, rivet_pitch)
                        r2 = dx * dx + dy * dy
                        if r2 < 4.5:
                            hv += 0.55 * (1.0 - r2 / 4.5)
            i = py * W + px
            height[i] = hv
            tone[i] = panel_tone[(px // panel_px, 0)]

    liveries = {}
    for key, _title, rgb, gloss, var in LIVERIES:
        buf = bytearray(4 * W * H)
        for i in range(W * H):
            hv = height[i]
            shade = 1.0 + var * tone[i] + 0.035 * noise[i]
            if key == 'metal':
                shade += 0.04 * noise[(i * 7) % (W * H)] * noise[(i // W) * W]   # faint brushing streaks
            if hv < 0.0:
                shade *= 1.0 + 0.45 * hv       # dark panel line
            elif hv > 0.0:
                shade *= 1.0 + 0.10 * hv       # light catches the rivet heads
            o = 4 * i
            for ch in range(3):
                buf[o + ch] = max(0, min(255, int(rgb[ch] * shade)))
            buf[o + 3] = max(0, min(255, int(gloss * (1.0 + 0.6 * min(0.0, hv)))))
        liveries[key] = bytes(buf)

    nrm = bytearray(4 * W * H)
    k = 2.0
    for py in range(H):
        up = ((py - 1) % H) * W
        dn = ((py + 1) % H) * W
        row = py * W
        for px in range(W):
            dx = (height[row + (px + 1) % W] - height[row + (px - 1) % W]) * 0.5 * k
            dy = (height[up + px] - height[dn + px]) * 0.5 * k
            inv = 1.0 / math.sqrt(dx * dx + dy * dy + 1.0)
            o = 4 * (row + px)
            nrm[o] = max(0, min(255, int((-dx * inv * 0.5 + 0.5) * 255.0)))
            nrm[o + 1] = max(0, min(255, int((-dy * inv * 0.5 + 0.5) * 255.0)))
            nrm[o + 2] = max(0, min(255, int((inv * 0.5 + 0.5) * 255.0)))
            nrm[o + 3] = 255

    hs = 64
    hw = bytearray(4 * hs * hs)
    for i in range(hs * hs):
        v = 58 + int(10 * rnd.uniform(-1.0, 1.0))
        hw[4 * i:4 * i + 4] = bytes((v, v + 2, v + 6, 120))
    return liveries, bytes(nrm), bytes(hw), hs


# ---------------------------------------------------------------------------------------------
# .mu writer
# ---------------------------------------------------------------------------------------------

def _write_material(w, name, tex_main, tex_bump, spec=(0.6, 0.62, 0.66, 1.0), shininess=0.45):
    w.write_string(name)
    w.write_string('KSP/Bumped Specular')
    w.write_int(10)
    for pname, rgba in (('_Color', (1.0, 1.0, 1.0, 1.0)), ('_SpecColor', spec), ('_RimColor', (0.0, 0.0, 0.0, 0.0)),
                        ('_TemperatureColor', (0.0, 0.0, 0.0, 0.0)), ('_BurnColor', (1.0, 1.0, 1.0, 1.0))):
        w.write_string(pname)
        w.write_int(0)
        w.write_floats(rgba)
    for pname, val in (('_Shininess', shininess), ('_Opacity', 1.0), ('_RimFalloff', 0.1)):
        w.write_string(pname)
        w.write_int(3)
        w.write_float(val)
    for pname, tidx in (('_MainTex', tex_main), ('_BumpMap', tex_bump)):
        w.write_string(pname)
        w.write_int(4)
        w.write_int(tidx)
        w.write_floats((1.0, 1.0))
        w.write_floats((0.0, 0.0))


def write_pylon_mu(path, body, hooks, collider, first_livery):
    w = MuWriter()
    w.write_uint(0x00012aff)
    w.write_int(5)
    w.write_string('launch_pylon')
    w.write_transform('launch_pylon')
    w.write_tag_and_layer('Untagged', 0)
    for name, mesh, mat in (('pylonBody', body, 0), ('pylonHooks', hooks, 1)):
        w.write_int(0)
        w.write_transform(name)
        w.write_tag_and_layer('Untagged', 0)
        w.write_mesh_filter(*mesh)
        w.write_mesh_renderer([mat], cast_shadows=True, receive_shadows=True)
        w.write_int(1)
    w.write_int(0)
    w.write_transform('pylonCollider')
    w.write_tag_and_layer('Untagged', 0)
    w.write_mesh_collider2(*collider, is_trigger=False, convex=True)
    w.write_int(1)

    w.write_int(10)
    w.write_int(2)
    _write_material(w, 'ropp_pylon_mat', 0, 1)
    _write_material(w, 'ropp_pylon_hw_mat', 2, 1, spec=(0.35, 0.35, 0.38, 1.0), shininess=0.3)
    w.write_int(12)
    w.write_int(3)
    for tname, ttype in ((f'ropp_pylon_{first_livery}', 0), ('ropp_pylon_NRM', 1), ('ropp_pylon_hardware', 0)):
        w.write_string(tname)
        w.write_int(ttype)
    w.write_int(1)   # close root
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(w.buf)


# ---------------------------------------------------------------------------------------------
# Icon (software rasteriser, 3/4 view from front-left and below)
# ---------------------------------------------------------------------------------------------

def render_icon(meshes, size=256):
    """meshes: [(mesh, rgba, tex_w, tex_h)]."""
    fb = bytearray(size * size * 4)
    zb = [1e30] * (size * size)
    yaw, pitch = math.radians(140.0), math.radians(-24.0)
    cy_, sy_ = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    def cam(p):
        x, y, z = p
        u = -z
        rx = x * cy_ + y * sy_
        ry = -x * sy_ + y * cy_
        return (rx, u * cp - ry * sp, ry * cp + u * sp)

    pts = [cam(v) for m in meshes for v in m[0][0]]
    mnx, mxx = min(p[0] for p in pts), max(p[0] for p in pts)
    mny, mxy = min(p[1] for p in pts), max(p[1] for p in pts)
    scale = 0.86 * size / max(mxx - mnx, mxy - mny, 1e-3)
    mx, my = 0.5 * (mnx + mxx), 0.5 * (mny + mxy)
    light = normalize3(-0.35, 0.65, -0.67)
    half = normalize3(light[0], light[1], light[2] - 1.0)
    for (verts, uvs, norms, _t, tris), tex, tw, th in meshes:
        cv = [cam(v) for v in verts]
        cn = [normalize3(*cam(n)) for n in norms]
        sv = [(0.5 * size + (p[0] - mx) * scale, 0.5 * size - (p[1] - my) * scale, p[2]) for p in cv]
        for t in range(0, len(tris), 3):
            i0, i1, i2 = tris[t], tris[t + 1], tris[t + 2]
            c0, c1, c2 = cv[i0], cv[i1], cv[i2]
            if (c1[0] - c0[0]) * (c2[1] - c0[1]) - (c1[1] - c0[1]) * (c2[0] - c0[0]) >= -1e-9:
                continue
            p0, p1, p2 = sv[i0], sv[i1], sv[i2]
            den = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
            if abs(den) < 1e-6:
                continue
            for py in range(max(0, int(min(p0[1], p1[1], p2[1]))), min(size - 1, int(max(p0[1], p1[1], p2[1])) + 1) + 1):
                for px in range(max(0, int(min(p0[0], p1[0], p2[0]))), min(size - 1, int(max(p0[0], p1[0], p2[0])) + 1) + 1):
                    sx, sy = px + 0.5, py + 0.5
                    w0 = ((p1[1] - p2[1]) * (sx - p2[0]) + (p2[0] - p1[0]) * (sy - p2[1])) / den
                    w1 = ((p2[1] - p0[1]) * (sx - p2[0]) + (p0[0] - p2[0]) * (sy - p2[1])) / den
                    w2 = 1.0 - w0 - w1
                    if w0 < -1e-4 or w1 < -1e-4 or w2 < -1e-4:
                        continue
                    z = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
                    pi = py * size + px
                    if z >= zb[pi]:
                        continue
                    zb[pi] = z
                    u = (w0 * uvs[i0][0] + w1 * uvs[i1][0] + w2 * uvs[i2][0]) % 1.0
                    v = (w0 * uvs[i0][1] + w1 * uvs[i1][1] + w2 * uvs[i2][1]) % 1.0
                    to = 4 * (int((1.0 - v) * (th - 1)) * tw + int(u * (tw - 1)))
                    n = normalize3(*[w0 * cn[i0][k] + w1 * cn[i1][k] + w2 * cn[i2][k] for k in range(3)])
                    ndl = max(0.0, sum(n[k] * light[k] for k in range(3)))
                    ndh = max(0.0, sum(n[k] * half[k] for k in range(3)))
                    diff = 0.40 + 0.66 * ndl
                    spec = (ndh ** 24) * (tex[to + 3] / 255.0) * 0.8 * 255.0
                    o = 4 * pi
                    for ch in range(3):
                        fb[o + ch] = max(0, min(255, int(tex[to + ch] * diff + spec)))
                    fb[o + 3] = 255
    return bytes(fb)


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    parts = os.path.join(root, 'GameData', 'ROPlanesPlus', 'Parts')
    pdir = os.path.join(parts, PART_ID)
    thumbs = os.path.join(parts, '@thumbs')
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(thumbs, exist_ok=True)

    print(f"Generating launch pylon textures ({TEX}x{TEX}, tiling)...")
    liveries, nrm, hw, hs = generate_textures()
    for key, *_ in LIVERIES:
        write_png(os.path.join(pdir, f'ropp_pylon_{key}.png'), TEX, TEX, liveries[key])
    write_png(os.path.join(pdir, 'ropp_pylon_NRM.png'), TEX, TEX, nrm)
    write_png(os.path.join(pdir, 'ropp_pylon_hardware.png'), hs, hs, hw)

    sh = Shape(DEFAULT_SHAPE)
    body, hooks, col = build_body(sh), build_hooks(sh), build_body(sh, collider=True)
    mu_path = os.path.join(pdir, f'{PART_ID}.mu')
    write_pylon_mu(mu_path, body, hooks, col, LIVERIES[0][0])
    print(f"   -> {os.path.relpath(mu_path, root)} ({os.path.getsize(mu_path):,} bytes; "
          f"{len(body[4]) // 3} body / {len(hooks[4]) // 3} hook / {len(col[4]) // 3} collider tris)")

    icon = render_icon([(body, liveries[LIVERIES[0][0]], TEX, TEX), (hooks, hw, hs, hs)])
    icon_path = os.path.join(thumbs, f'{PART_NAME}_icon.png')
    write_png(icon_path, 256, 256, icon)
    print(f"   -> {os.path.relpath(icon_path, root)}")


if __name__ == '__main__':
    main()
