"""
ROPlanes+ cockpit builder - runs INSIDE Blender (background mode):

    blender -b --factory-startup --python blender/build_cockpits.py -- [cockpit ids] [--no-preview]

(or simply `python generate_cockpits.py`, which finds Blender and runs this).

For every cockpit in cockpit_specs.COCKPITS it:
  1. builds the fuselage, canopy, frames, glazing, nose variants and details as Blender meshes
     (clean lofted quads from the spec's cross sections; real dimensions, circular rear ring),
  2. unwraps them (own skin UVs for lofts, smart projection for small parts) and packs one atlas,
  3. bakes position / normal / class / ambient occlusion maps with Cycles,
  4. paints the liveries, normal map (panel lines, hatches, rivets) and emissive map with numpy,
  5. writes GameData/ROPlanesPlus/Parts/<id>/<id>.mu with the mod's own MuWriter
     (variant groups for B9PartSwitch, convex colliders, airlock/ladder triggers, flag decal),
  6. renders the part icon (@thumbs) and a preview contact sheet (cockpits_preview_sheet.png).
"""

import math
import os
import random
import sys
import time
import zlib

import bpy
import bmesh
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import cockpit_specs as CS  # noqa: E402
from generate_models_and_textures import MuWriter  # noqa: E402

PARTS_DIR = os.path.join(ROOT, 'GameData', 'ROPlanesPlus', 'Parts')
THUMBS_DIR = os.path.join(PARTS_DIR, '@thumbs')
PREVIEW_DIR = os.path.join(ROOT, 'build', 'cockpit_previews')

# Surface classes (baked into the class map)
CL_BODY, CL_GLASS, CL_FRAME, CL_METAL, CL_INTAKE, CL_CAP, CL_DARK = 1, 2, 3, 4, 5, 6, 7
CL_INTERIOR, CL_PANEL, CL_SEAT, CL_DOME, CL_ACCENT = 8, 9, 10, 11, 12
CLASS_UV_SCALE = {CL_BODY: 1.0, CL_GLASS: 0.45, CL_FRAME: 0.8, CL_METAL: 0.6, CL_INTAKE: 0.4,
                  CL_CAP: 0.30, CL_DARK: 0.30, CL_INTERIOR: 0.45, CL_PANEL: 1.6, CL_SEAT: 0.8,
                  CL_DOME: 0.45, CL_ACCENT: 0.6}
CLASS_NAMES = {'body': CL_BODY, 'glass': CL_GLASS, 'glass_top': CL_DOME, 'dome': CL_DOME, 'frame': CL_FRAME,
               'metal': CL_METAL, 'intake': CL_INTAKE, 'cap': CL_CAP, 'dark': CL_DARK, 'nose': CL_METAL,
               'interior': CL_INTERIOR, 'seat': CL_SEAT, 'accent': CL_ACCENT}
GLASS_CLASSES = (CL_GLASS, CL_DOME)                            # -> 'windows' (translucent glass material)
INTERIOR_CLASSES = (CL_INTERIOR, CL_PANEL, CL_SEAT, CL_ACCENT)  # -> 'canopyInterior' (seen through the glass)


def log(*a):
    print('[cockpits]', *a, flush=True)


# =============================================================================== small math

def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_norm(a):
    l = math.sqrt(v_dot(a, a))
    if l < 1e-12:
        return (0.0, 0.0, 1.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def smooth01(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def hexcol(h):
    h = h.lstrip('#')
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float32) / 255.0


# =============================================================================== piece builder

class Piece:
    """A mesh under construction: verts, faces (vertex index tuples) and per-corner UVs."""

    def __init__(self, name, cls, variant=None, smooth=True, own_uv=True):
        self.name = name
        self.cls = cls
        self.variant = variant      # None = common to all variants
        self.smooth = smooth
        self.own_uv = own_uv
        self.v = []
        self.f = []
        self.uv = []

    def vert(self, p):
        self.v.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self.v) - 1

    def face(self, idx, uvs=None, out=None):
        idx = list(idx)
        if uvs is None:
            uvs = [(0.0, 0.0)] * len(idx)
        uvs = list(uvs)
        if out is not None:
            n = (0.0, 0.0, 0.0)
            for i in range(len(idx)):
                a = self.v[idx[i]]
                b = self.v[idx[(i + 1) % len(idx)]]
                n = v_add(n, v_cross(a, b))
            if v_dot(n, out) < 0.0:
                idx.reverse()
                uvs.reverse()
        if len(set(idx)) < 3:
            return
        self.f.append(tuple(idx))
        self.uv.append(uvs)

    def empty(self):
        return not self.f


def grid_faces(piece, rows, uvrows, reverse=False, tip=None, tip_uv=None):
    """rows: list of vertex-index lists (equal length), along +y, each ordered by increasing phi.
    The quad order [r_i j, r_i j+1, r_i+1 j+1, r_i+1 j] faces outward for that convention."""
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        ua, ub = uvrows[i], uvrows[i + 1]
        for j in range(len(a) - 1):
            idx = [a[j], a[j + 1], b[j + 1], b[j]]
            uvs = [ua[j], ua[j + 1], ub[j + 1], ub[j]]
            if reverse:
                idx.reverse()
                uvs.reverse()
            piece.face(idx, uvs)
    if tip is not None:
        a, ua = rows[-1], uvrows[-1]
        for j in range(len(a) - 1):
            idx = [a[j], a[j + 1], tip]
            uvs = [ua[j], ua[j + 1], tip_uv]
            if reverse:
                idx.reverse()
                uvs.reverse()
            piece.face(idx, uvs)


def arc_uvs(points, centre_index):
    """u = signed arc length from the centre point along a ring, v filled in by the caller."""
    n = len(points)
    u = [0.0] * n
    for j in range(centre_index + 1, n):
        u[j] = u[j - 1] + math.dist(points[j], points[j - 1])
    for j in range(centre_index - 1, -1, -1):
        u[j] = u[j + 1] - math.dist(points[j], points[j + 1])
    return u


# =============================================================================== surfaces

class BodySurf:
    def __init__(self, prof):
        self.prof = prof

    def point(self, y, phi):
        s = self.prof.section(y)
        x, z = CS.section_point(s, phi)
        return (x, y, z)

    def normal(self, y, phi):
        e = 1e-3
        ya = min(y, self.prof.length - 2 * e)
        pp = self.point(ya, phi + e)
        pm = self.point(ya, phi - e)
        py = self.point(ya + e, phi)
        pn = self.point(ya - e, phi)
        n = v_norm(v_cross(v_sub(pp, pm), v_sub(py, pn)))
        return n

    def top_z(self, y, x=0.0):
        return CS.body_top_z_at(self.prof.section(y), x)

    def bottom_z(self, y, x=0.0):
        s = self.prof.section(y)
        w = max(1e-6, s['w'])
        if abs(x) >= w:
            return s['zc']
        sp = (abs(x) / w) ** (s['nb'] / 2.0)
        cp = math.sqrt(max(0.0, 1.0 - sp * sp))
        return s['zc'] - s['hb'] * cp ** (2.0 / max(0.5, s['nb']))


class CanopySurf:
    def __init__(self, cprof):
        self.cp = cprof

    def point(self, y, phi):
        c = self.cp.section(y)
        x, z = CS.canopy_point(c, phi)
        return (x, y, z)

    def normal(self, y, phi):
        e = 1e-3
        pp = self.point(y, min(math.pi / 2, phi + e))
        pm = self.point(y, max(-math.pi / 2, phi - e))
        py = self.point(y + e, phi)
        pn = self.point(y - e, phi)
        return v_norm(v_cross(v_sub(pp, pm), v_sub(py, pn)))


def phi_samples(n, chine_deg=None):
    """Symmetric samples on [-pi, pi] (0 = top) with extra density around +-chine angle."""
    half = n // 2
    if chine_deg is None:
        pos = [math.pi * k / half for k in range(half + 1)]
    else:
        a = math.radians(chine_deg)
        fine = 4096
        dens = []
        for k in range(fine + 1):
            p = math.pi * k / fine
            dens.append(1.0 + 3.5 * math.exp(-((p - a) / 0.11) ** 2))
        cum = [0.0]
        for k in range(1, fine + 1):
            cum.append(cum[-1] + 0.5 * (dens[k] + dens[k - 1]))
        total = cum[-1]
        pos = [0.0]
        j = 0
        for k in range(1, half):
            target = total * k / half
            while cum[j + 1] < target:
                j += 1
            t = (target - cum[j]) / (cum[j + 1] - cum[j])
            pos.append(math.pi * (j + t) / fine)
        pos.append(math.pi)
    return [-p for p in reversed(pos[1:])] + pos


def stations(prof, ya, yb, ds):
    ys = set()
    y_n0 = prof.nose['y0'] if prof.nose else 1e9
    L = prof.length
    lo, hi = ya, min(yb, y_n0)
    if hi > lo:
        n = max(1, int(math.ceil((hi - lo) / ds)))
        for k in range(n + 1):
            ys.add(round(lo + (hi - lo) * k / n, 6))
    lo, hi = max(ya, y_n0), min(yb, L)
    if hi > lo + 1e-6:
        a0 = math.asin(max(0.0, min(1.0, (lo - y_n0) / (L - y_n0))))
        a1 = math.asin(max(0.0, min(1.0, (hi - y_n0) / (L - y_n0))))
        n = max(10, int((hi - lo) / ds * 1.6))
        for k in range(n + 1):
            a = a0 + (a1 - a0) * k / n
            ys.add(round(y_n0 + (L - y_n0) * math.sin(a), 6))
    ys.add(round(ya, 6))
    ys.add(round(yb, 6))
    return sorted(y for y in ys if ya - 1e-9 <= y <= yb + 1e-9)


def build_surface_loft(piece, surf, ys, phis, offset=0.0, tip_at_end=False, reverse=False, tip_y=None):
    """Loft a parametric surface over ys x phis (phis ascending). Optional pole at the end."""
    rows, uvrows = [], []
    ci = min(range(len(phis)), key=lambda k: abs(phis[k]))
    last = len(ys) - 1 if tip_at_end else len(ys)
    for i in range(last):
        y = ys[i]
        pts = []
        for p in phis:
            q = surf.point(y, p)
            if offset:
                q = v_add(q, v_mul(surf.normal(y, p), offset))
            pts.append(q)
        u = arc_uvs(pts, ci)
        rows.append([piece.vert(q) for q in pts])
        uvrows.append([(u[j], y) for j in range(len(pts))])
    tip = tip_uv = None
    if tip_at_end:
        yt = ys[-1] if tip_y is None else tip_y
        q = surf.point(yt, 0.0)
        if offset:
            q = (q[0], q[1] + offset, q[2])
        tip = piece.vert(q)
        tip_uv = (0.0, yt)
    grid_faces(piece, rows, uvrows, reverse=reverse, tip=tip, tip_uv=tip_uv)
    return rows


def build_body_loft(piece, surf, ys, phis, cuts, tip_at_end=False, offset=0.0, inward=False):
    """Like build_surface_loft, but leaves out the quads inside the openings.
    cuts: (y0, y1, phi_lo, phi_hi) with the boundaries present in ys / phis.
    offset moves the surface along its normal; inward=True flips the faces (cockpit liner)."""
    rows, uvrows = [], []
    ci = min(range(len(phis)), key=lambda k: abs(phis[k]))
    last = len(ys) - 1 if tip_at_end else len(ys)
    for i in range(last):
        pts = [surf.point(ys[i], p) for p in phis]
        if offset:
            pts = [v_add(q, v_mul(surf.normal(ys[i], p), offset)) for q, p in zip(pts, phis)]
        u = arc_uvs(pts, ci)
        rows.append([piece.vert(q) for q in pts])
        uvrows.append([(u[j], ys[i]) for j in range(len(pts))])
    eps = 1e-6

    def inside(ya, yb, pa, pb):
        for y0, y1, lo, hi in cuts:
            if ya >= y0 - eps and yb <= y1 + eps and pa >= lo - eps and pb <= hi + eps:
                return True
        return False

    def emit(idx, uvs):
        if inward:
            idx, uvs = idx[::-1], uvs[::-1]
        piece.face(idx, uvs)
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        ua, ub = uvrows[i], uvrows[i + 1]
        for j in range(len(a) - 1):
            if inside(ys[i], ys[i + 1], phis[j], phis[j + 1]):
                continue
            emit([a[j], a[j + 1], b[j + 1], b[j]], [ua[j], ua[j + 1], ub[j + 1], ub[j]])
    if tip_at_end:
        yt = ys[-1]
        q = surf.point(yt, 0.0)
        tip = piece.vert((q[0], q[1] + offset, q[2]))
        a, ua = rows[-1], uvrows[-1]
        for j in range(len(a) - 1):
            if inside(ys[len(rows) - 1], yt, phis[j], phis[j + 1]):
                continue
            emit([a[j], a[j + 1], tip], [ua[j], ua[j + 1], (0.0, yt)])
    return rows


def opening_rims(piece, surf, ys, cuts, depth, length):
    """Closes the gap between a body opening and the liner below it (lip facing into the opening)."""
    def pair(y, p):
        q = surf.point(y, p)
        return q, v_add(q, v_mul(surf.normal(y, p), -depth))
    for y0, y1, lo, hi in cuts:
        yy = [y for y in ys if y0 - 1e-6 <= y <= y1 + 1e-6]
        ym = 0.5 * (y0 + y1)
        mid = surf.point(ym, 0.5 * (lo + hi))
        for p in (lo, hi):
            out = v_sub(mid, surf.point(ym, p))
            for ya, yb in zip(yy, yy[1:]):
                (a0, a1), (b0, b1) = pair(ya, p), pair(yb, p)
                q = [a0, b0, b1, a1]
                piece.face([piece.vert(v) for v in q], [(ya, 0.0), (yb, 0.0), (yb, depth), (ya, depth)], out=out)
        ph = lin(lo, hi, max(4, int((hi - lo) / 0.06)))
        for y, out in ((y0, (0.0, 1.0, 0.0)), (y1, (0.0, -1.0, 0.0))):
            if y >= length - 1e-3:
                continue
            for pa, pb in zip(ph, ph[1:]):
                (a0, a1), (b0, b1) = pair(y, pa), pair(y, pb)
                q = [a0, b0, b1, a1]
                piece.face([piece.vert(v) for v in q], [(pa, 0.0), (pb, 0.0), (pb, depth), (pa, depth)], out=out)


def merge_phis(phis, extra):
    """Insert exact boundary angles into a symmetric phi list (dropping samples too close to them)."""
    if not extra:
        return list(phis)
    step = min(b - a for a, b in zip(phis, phis[1:]))
    keep = [p for p in phis if all(abs(p - e) > 0.45 * step for e in extra) or abs(abs(p) - math.pi) < 1e-9]
    out = sorted(set(round(p, 9) for p in keep + list(extra)))
    return out


def ring_cap(piece, pts, centre, out):
    c = piece.vert(centre)
    idx = [piece.vert(p) for p in pts]
    n = len(idx)
    for j in range(n - 1):
        a, b = pts[j], pts[j + 1]
        piece.face([c, idx[j], idx[j + 1]],
                   [(centre[0], centre[2]), (a[0], a[2]), (b[0], b[2])], out=out)


def strip_on_surface(piece, surf, ys, phis_fn, t, walls=True):
    """Raised strip: top surface offset by t over a (y, phi) patch + side walls.
    phis_fn(y) -> ascending list of phi across the strip."""
    rows_top, rows_base, uvt = [], [], []
    for y in ys:
        ph = phis_fn(y)
        base = [surf.point(y, p) for p in ph]
        top = [v_add(b, v_mul(surf.normal(y, p), t)) for b, p in zip(base, ph)]
        rows_base.append(base)
        rows_top.append([piece.vert(q) for q in top])
        u = arc_uvs(top, len(top) // 2)
        uvt.append([(u[j], y) for j in range(len(top))])
    grid_faces(piece, rows_top, uvt)
    if not walls:
        return

    def wall(top_idx, base_pts, out):
        bidx = [piece.vert(p) for p in base_pts]
        for j in range(len(top_idx) - 1):
            piece.face([bidx[j], bidx[j + 1], top_idx[j + 1], top_idx[j]],
                       [(j * 0.02, 0.0), ((j + 1) * 0.02, 0.0), ((j + 1) * 0.02, t), (j * 0.02, t)], out=out)

    # walls along the first and last rows (y edges) and along the phi edges
    n0 = v_sub(surf.point(ys[0] - 0.01, phis_fn(ys[0])[len(phis_fn(ys[0])) // 2]), surf.point(ys[0], phis_fn(ys[0])[len(phis_fn(ys[0])) // 2]))
    n1 = v_sub(surf.point(ys[-1] + 0.01, phis_fn(ys[-1])[len(phis_fn(ys[-1])) // 2]), surf.point(ys[-1], phis_fn(ys[-1])[len(phis_fn(ys[-1])) // 2]))
    wall(rows_top[0], rows_base[0], n0)
    wall(rows_top[-1], rows_base[-1], n1)
    for side in (0, -1):
        top_idx = [r[side] for r in rows_top]
        base_pts = [r[side] for r in rows_base]
        ym = ys[len(ys) // 2]
        ph = phis_fn(ym)
        dirv = v_sub(surf.point(ym, ph[side]), surf.point(ym, ph[len(ph) // 2]))
        bidx = [piece.vert(p) for p in base_pts]
        for i in range(len(top_idx) - 1):
            piece.face([bidx[i], bidx[i + 1], top_idx[i + 1], top_idx[i]],
                       [(i * 0.02, 0.0), ((i + 1) * 0.02, 0.0), ((i + 1) * 0.02, t), (i * 0.02, t)], out=dirv)


def lin(a, b, n):
    return [a + (b - a) * k / (n - 1) for k in range(n)]


def glazing_ranges(g):
    """phi ranges (radians, ascending) covered by a glazing patch."""
    if g.get('sides'):
        return [(-math.radians(g['phi_hi']), -math.radians(g['phi_lo'])),
                (math.radians(g['phi_lo']), math.radians(g['phi_hi']))]
    a = math.radians(g['phi'])
    return [(-a, a)]


# =============================================================================== detail builders

def add_box(piece, centre, size):
    cx, cy, cz = centre
    sx, sy, sz = (s * 0.5 for s in size)
    corners = {}
    for dx in (-1, 1):
        for dy in (-1, 1):
            for dz in (-1, 1):
                corners[(dx, dy, dz)] = (cx + dx * sx, cy + dy * sy, cz + dz * sz)
    faces = [((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
             ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
             ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
             ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
             ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
             ((0, 0, -1), [(-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)])]
    for out, ks in faces:
        idx = [piece.vert(corners[k]) for k in ks]
        piece.face(idx, [(0, 0), (1, 0), (1, 1), (0, 1)], out=out)


def add_obox(piece, centre, ax, ay, az, hx, hy, hz):
    """Oriented box: centre, three orthonormal axes and half sizes along them."""
    def corner(sx, sy, sz):
        return v_add(centre, v_add(v_mul(ax, sx * hx), v_add(v_mul(ay, sy * hy), v_mul(az, sz * hz))))
    quads = [(ax, [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
             (v_mul(ax, -1), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
             (ay, [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
             (v_mul(ay, -1), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
             (az, [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
             (v_mul(az, -1), [(-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)])]
    for out, ks in quads:
        idx = [piece.vert(corner(*k)) for k in ks]
        piece.face(idx, [(0, 0), (1, 0), (1, 1), (0, 1)], out=out)


def tilt_axes(deg):
    """Axes for a plate leaning back by deg (top toward -y): (x, up-along-plate, plate normal toward +y)."""
    a = math.radians(deg)
    up = (0.0, -math.sin(a), math.cos(a))
    nrm = (0.0, math.cos(a), math.sin(a))
    return (1.0, 0.0, 0.0), up, nrm


def add_prism(piece, poly_yz, x0, x1):
    """Extrude a (y, z) polygon between x0 and x1 (thin fins, blades)."""
    n = len(poly_yz)
    a = [piece.vert((x0, y, z)) for y, z in poly_yz]
    b = [piece.vert((x1, y, z)) for y, z in poly_yz]
    piece.face(a, [(y, z) for y, z in poly_yz], out=(-1, 0, 0))
    piece.face(b, [(y, z) for y, z in poly_yz], out=(1, 0, 0))
    cy = sum(p[0] for p in poly_yz) / n
    cz = sum(p[1] for p in poly_yz) / n
    for k in range(n):
        k2 = (k + 1) % n
        mid = ((poly_yz[k][0] + poly_yz[k2][0]) * 0.5 - cy, (poly_yz[k][1] + poly_yz[k2][1]) * 0.5 - cz)
        piece.face([a[k], a[k2], b[k2], b[k]], [(0, 0), (1, 0), (1, 0.02), (0, 0.02)], out=(0.0, mid[0], mid[1]))


def add_tube(piece, y0, y1, r0, r1, x, z, sides=12, tip=True):
    rows, uvrows = [], []
    nseg = 6
    for i in range(nseg + 1):
        t = i / nseg
        y = y0 + (y1 - y0) * t
        r = r0 + (r1 - r0) * t
        pts = []
        for j in range(sides + 1):
            p = -math.pi + 2 * math.pi * j / sides
            pts.append((x + r * math.sin(p), y, z + r * math.cos(p)))
        rows.append([piece.vert(q) for q in pts])
        uvrows.append([(r * (-math.pi + 2 * math.pi * j / sides), y) for j in range(sides + 1)])
    tipi = piece.vert((x, y1 + r1 * 3.0, z)) if tip else None
    grid_faces(piece, rows, uvrows, tip=tipi, tip_uv=(0.0, y1 + r1 * 3.0))


def add_ellipsoid(piece, centre, rx, ry, rz, nu=16, nv=10):
    cx, cy, cz = centre
    rows, uvrows = [], []
    # parametrise along y (from back pole to front pole) so grid_faces' convention holds
    for i in range(1, nv):
        a = -math.pi / 2 + math.pi * i / nv
        y = cy + ry * math.sin(a)
        rr = math.cos(a)
        pts = []
        for j in range(nu + 1):
            p = -math.pi + 2 * math.pi * j / nu
            pts.append((cx + rx * rr * math.sin(p), y, cz + rz * rr * math.cos(p)))
        rows.append([piece.vert(q) for q in pts])
        uvrows.append([(p_ / nu * 2 * math.pi * max(rx, rz), y) for p_ in range(nu + 1)])
    tip = piece.vert((cx, cy + ry, cz))
    grid_faces(piece, rows, uvrows, tip=tip, tip_uv=(0.0, cy + ry))
    back = piece.vert((cx, cy - ry, cz))
    first = rows[0]
    for j in range(nu):
        piece.face([back, first[j + 1], first[j]], [(0, cy - ry), uvrows[0][j + 1], uvrows[0][j]],
                   out=(0, -1, 0))


def add_blister(piece, bs, y0, y1, x, rw, rh, side, peak=0.5):
    """Elongated fairing on the top or bottom of the body, sunk 30 % into it.
    peak: where along its length (0 = rear) it is fattest (teardrop bulges: < 0.5)."""
    rows, uvrows = [], []
    n = 18
    sides = 16
    kexp = math.log(0.5) / math.log(min(0.95, max(0.05, peak)))
    for i in range(n + 1):
        t = i / n
        y = y0 + (y1 - y0) * t
        g = max(0.04, math.sin(math.pi * t ** kexp) ** 0.55)
        if side == 'bottom':
            zb = bs.bottom_z(y, x)
            zc = zb + 0.30 * rh * g
            sgn = -1.0
        else:
            zb = bs.top_z(y, x)
            zc = zb - 0.30 * rh * g
            sgn = 1.0
        pts = []
        for j in range(sides + 1):
            p = -math.pi + 2 * math.pi * j / sides
            pts.append((x + rw * g * math.sin(p), y, zc + rh * g * math.cos(p) * (1.0 if sgn > 0 else 1.0)))
        rows.append([piece.vert(q) for q in pts])
        u = arc_uvs(pts, sides // 2)
        uvrows.append([(u[j], y) for j in range(sides + 1)])
    grid_faces(piece, rows, uvrows)
    for rr, out in ((rows[0], (0, -1, 0)), (rows[-1], (0, 1, 0))):
        pts = [piece.v[k] for k in rr]
        cen = (sum(p[0] for p in pts) / len(pts), pts[0][1], sum(p[2] for p in pts) / len(pts))
        ring_cap(piece, pts, cen, out)


# =============================================================================== cockpit geometry

class Build:
    def __init__(self, c):
        self.c = c
        self.pieces = []
        self.variants = c['variants']
        self.vkeys = [v['key'] for v in self.variants]
        self.ds = 0.045 if c['rear_dia'] < 2.5 else 0.07
        self.common_prof = CS.BodyProfile(c['body'], c['length'], c.get('nose'))
        chines = [k['cha'] for k in c['body'] if k['ch'] > 0]
        self.phis = phi_samples(c.get('segments', 80), chines[0] if chines else None)

    def piece(self, name, cls, variant=None, smooth=True, own_uv=True):
        p = Piece(name, cls, variant, smooth, own_uv)
        self.pieces.append(p)
        return p

    def per_variant(self, key):
        return any(key in v for v in self.variants)

    # ---------------------------------------------------------------------------------------
    def build(self):
        c = self.c
        split = c.get('split_y')
        body_per_variant = self.per_variant('body')

        # 1. Fuselage (with the cockpit opening / glazed areas left open)
        if body_per_variant:
            for v in self.variants:
                prof = CS.variant_body(c, v)
                self.body_section(prof, 0.0, split or prof.length, v['key'], 'body_' + v['key'])
        else:
            self.body_section(self.common_prof, 0.0, split or c['length'], None, 'body')

        # 1b. Cockpit interior seen through the glass
        if c.get('pit'):
            if body_per_variant:
                for v in self.variants:
                    self.compartment(CS.variant_body(c, v), c['pit'], v['key'])
            else:
                self.compartment(self.common_prof, c['pit'], None)
        # rear bulkhead and (prop cockpits) front ring cap
        self.cap_ring(self.common_prof, 0.0, (0, -1, 0), None, 'rear_cap')
        if c.get('front_dia') and not split:
            self.cap_ring(self.common_prof, c['length'], (0, 1, 0), None, 'front_cap')

        # 2. Noses
        if split:
            for v in self.variants:
                prof = CS.variant_body(c, v)
                kind = v.get('nose')
                if kind == 'adapter':
                    self.adapter(prof, v)
                elif c.get('intake'):
                    self.intake_nose(prof, v)
                else:
                    self.body_section(prof, split, prof.length, v['key'], 'nose_' + v['key'])

        # 3. Canopy + frames
        if c.get('canopy') or self.per_variant('canopy'):
            if self.per_variant('canopy') or self.per_variant('frames') or body_per_variant:
                for v in self.variants:
                    self.canopy(CS.variant_body(c, v), v.get('canopy', c['canopy']),
                                v.get('frames', c.get('frames', [])), v['key'])
            else:
                self.canopy(self.common_prof, c['canopy'], c.get('frames', []), None)

        # 4. Glazing patches
        for g in c.get('glazing', []):
            self.glazing(self.common_prof, g, None)
        for v in self.variants:
            for g in v.get('glazing', []):
                self.glazing(CS.variant_body(c, v), g, v['key'])

        # 5. Details
        for d in c.get('details', []):
            self.detail(d)
        for v in self.variants:
            for d in v.get('extra', []):
                self.detail(d, v['key'])
        self.pieces = [p for p in self.pieces if not p.empty()]
        return self.pieces

    # ---------------------------------------------------------------------------------------
    def openings(self, prof, variant):
        """Openings (y0, y1, phi_lo, phi_hi) in a body piece: the cockpit pit under the canopy and
        every glazed area (common ones, plus the variant's own for variant pieces)."""
        c = self.c
        cuts = []
        pit = c.get('pit')
        globs = list(c.get('glazing', []))
        if variant is not None:
            globs += next(v for v in self.variants if v['key'] == variant).get('glazing', [])
        if pit and pit.get('w'):
            a = CS.phi_at_x(prof.section(0.5 * (pit['y0'] + pit['y1'])), pit['w'])
            cuts.append((pit['y0'], pit['y1'], -a, a))
        for g in globs:
            for lo, hi in glazing_ranges(g):
                cuts.append((g['y0'], min(g['y1'], prof.length), lo, hi))
        return cuts

    def body_section(self, prof, ya, yb, variant, name):
        p = self.piece(name, CL_BODY, variant)
        ys = stations(prof, ya, yb, self.ds)
        tip = prof.nose is not None and yb >= prof.length - 1e-6
        cuts = []
        for y0, y1, lo, hi in self.openings(prof, variant):
            y0, y1 = max(y0, ya), min(y1, yb)
            if y1 - y0 > 0.02:
                cuts.append((y0, y1, lo, hi))
        if not cuts:
            build_surface_loft(p, BodySurf(prof), ys, self.phis, tip_at_end=tip)
            return
        bounds = sorted({round(y, 6) for cut in cuts for y in cut[:2]})
        ys = sorted({y for y in ys if all(abs(y - b) > 0.006 for b in bounds)} | set(bounds))
        phis = merge_phis(self.phis, [a for cut in cuts for a in cut[2:]])
        build_body_loft(p, BodySurf(prof), ys, phis, cuts, tip_at_end=tip)

    # ---------------------------------------------------------------------------------------
    def compartment(self, prof, pit, variant):
        """Cockpit interior: inward liner with bulkheads, floor, instrument panel with glareshield,
        gunsight / HUD, seats, stick or yokes and side consoles."""
        c = self.c
        tag = variant or 'common'
        bs = BodySurf(prof)
        y0 = pit.get('ly0', pit['y0'] - 0.08)
        y1 = min(prof.length, pit.get('ly1', pit['y1'] + 0.08))
        tip = prof.nose is not None and y1 >= prof.length - 1e-6
        liner = self.piece('liner_' + tag, CL_INTERIOR, variant)
        ys = stations(prof, y0, y1, max(0.05, self.ds * 1.4))
        cuts = []
        for cy0, cy1, lo, hi in self.openings(prof, variant):
            cy0, cy1 = max(cy0, y0), min(cy1, y1)
            if cy1 - cy0 > 0.02:
                cuts.append((cy0, cy1, lo, hi))
        bounds = sorted({round(y, 6) for cut in cuts for y in cut[:2]})
        ys = sorted({y for y in ys if all(abs(y - b) > 0.006 for b in bounds)} | set(bounds))
        phis = merge_phis(phi_samples(48), [a for cut in cuts for a in cut[2:]])
        depth = 0.02
        rows = build_body_loft(liner, bs, ys, phis, cuts, tip_at_end=tip, offset=-depth, inward=True)
        rim = self.piece('rim_' + tag, CL_INTERIOR, variant, smooth=False, own_uv=False)
        opening_rims(rim, bs, sorted(set(stations(prof, y0, y1, self.ds)) | set(bounds)), cuts, depth, prof.length)
        caps = self.piece('bulkheads_' + tag, CL_INTERIOR, variant, smooth=False)
        r0 = [liner.v[k] for k in rows[0]]
        ring_cap(caps, r0, (0.0, y0, sum(q[2] for q in r0) / len(r0)), (0, 1, 0))
        if not tip:
            r1 = [liner.v[k] for k in rows[-1]]
            ring_cap(caps, r1, (0.0, y1, sum(q[2] for q in r1) / len(r1)), (0, -1, 0))

        # floor (two-sided: the underside shows through lower glazing)
        zf = pit['floor']
        fl = self.piece('floor_' + tag, CL_INTERIOR, variant, smooth=False)
        strip = []
        for y in lin(y0 + 0.01, y1 - 0.01, max(4, int((y1 - y0) / 0.08))):
            hw = CS.half_width_at_z(prof.section(y), zf) - 0.035
            if hw < 0.03:
                if strip:
                    break
                continue
            strip.append((y, hw))
        for (ya, ha), (yb, hb) in zip(strip, strip[1:]):
            q = [(-ha, ya, zf), (ha, ya, zf), (hb, yb, zf), (-hb, yb, zf)]
            idx = [fl.vert(p) for p in q]
            fl.face(idx, [(p[0], p[1]) for p in q], out=(0, 0, 1))
            idx = [fl.vert(p) for p in q]
            fl.face(idx, [(p[0] + 20.0, p[1]) for p in q], out=(0, 0, -1))

        # instrument panel(s) + glareshield
        panels = pit.get('panels') or ([(pit['panel_y'], pit.get('panel_top'))] if pit.get('panel_y') else [])
        for k, (py, ztop) in enumerate(panels):
            s = prof.section(py)
            if ztop is None:
                a = CS.phi_at_x(prof.section(0.5 * (pit['y0'] + pit['y1'])), pit['w'])
                ztop = CS.section_point(s, a)[1] - 0.05
            pn = self.piece(f'panel_{tag}_{k}', CL_PANEL, variant, smooth=False)
            pz0 = pit.get('panel_bottom', zf)
            pw = pit.get('panel_w', 9.0)
            levels = lin(pz0, ztop, 7)
            for za, zb in zip(levels, levels[1:]):
                ha = min(pw, max(0.03, CS.half_width_at_z(s, za) - 0.035))
                hb = min(pw, max(0.03, CS.half_width_at_z(s, zb) - 0.035))
                q = [(-ha, py, za), (ha, py, za), (hb, py, zb), (-hb, py, zb)]
                pn.face([pn.vert(p) for p in q], [(p[0] + 3.0 * k, p[2]) for p in q], out=(0, -1, 0))
            hood = self.piece(f'hood_{tag}_{k}', CL_INTERIOR, variant)
            hw = min(pw, max(0.05, CS.half_width_at_z(s, ztop) - 0.035))
            depth = pit.get('hood', 0.12)
            bump = pit.get('hood_h', 0.05)
            xs = lin(-hw, hw, 13)
            hy = lin(py - depth, py + 0.05, 4)

            def hz(x):
                return ztop + bump * math.sqrt(max(0.0, 1.0 - (x / hw) ** 2))
            for ya, yb in zip(hy, hy[1:]):
                for xa, xb in zip(xs, xs[1:]):
                    q = [(xa, ya, hz(xa)), (xb, ya, hz(xb)), (xb, yb, hz(xb)), (xa, yb, hz(xa))]
                    hood.face([hood.vert(p) for p in q], [(p[0], p[1]) for p in q], out=(0, 0, 1))
            yl = py - depth
            for xa, xb in zip(xs, xs[1:]):
                q = [(xa, yl, ztop - 0.035), (xb, yl, ztop - 0.035), (xb, yl, hz(xb)), (xa, yl, hz(xa))]
                hood.face([hood.vert(p) for p in q], [(p[0], p[2] + 5.0) for p in q], out=(0, -1, 0))
            if k == 0:
                self.sight(pit.get('sight'), py - depth, ztop + bump, variant, tag)

        # seats, sticks, consoles (a seat entry may carry its own overrides as a 4th element)
        seats = pit.get('seats') or [(sx, sy, pit['seat_z']) for sx, sy in c['seats']]
        for k, st in enumerate(seats):
            sp = dict(pit, **st[3]) if len(st) > 3 else pit
            self.seat(prof, sp, st[0], st[1], st[2], zf, variant, f'{tag}_{k}')

    def sight(self, kind, yr, zt, variant, tag):
        if not kind:
            return
        box = self.piece('sightbox_' + tag, CL_SEAT, variant, smooth=False, own_uv=False)
        gl = self.piece('sightglass_' + tag, CL_GLASS, variant, smooth=False, own_uv=False)
        if kind == 'reflector':
            add_box(box, (0.0, yr + 0.06, zt + 0.035), (0.075, 0.11, 0.07))
            ax, up, nr = tilt_axes(38)
            add_obox(gl, v_add((0.0, yr + 0.05, zt + 0.07), v_mul(up, 0.05)), ax, up, nr, 0.045, 0.05, 0.003)
        else:  # head-up display: frame + two combiner plates
            add_box(box, (0.0, yr + 0.07, zt + 0.03), (0.17, 0.13, 0.06))
            ax, up, nr = tilt_axes(22)
            for dz, dy in ((0.0, 0.0), (0.004, -0.03)):
                add_obox(gl, v_add((0.0, yr + 0.04 + dy, zt + 0.06 + dz), v_mul(up, 0.08)), ax, up, nr,
                         0.075, 0.08, 0.0025)
            for sx in (-0.08, 0.08):
                add_obox(box, v_add((sx, yr + 0.04, zt + 0.06), v_mul(up, 0.08)), ax, up, nr, 0.006, 0.085, 0.012)

    def seat(self, prof, pit, x, y, zp, zf, variant, tag):
        style = pit.get('seat', 'ww2')
        if style is None:
            return
        sp = self.piece('seat_' + tag, CL_SEAT, variant, smooth=False, own_uv=False)
        acc = self.piece('seatacc_' + tag, CL_ACCENT, variant, smooth=False, own_uv=False)
        recline = pit.get('recline', 14 if style == 'ejection' else 10)
        ax, up, nr = tilt_axes(recline)
        hwid = 0.25 if style == 'ejection' else 0.22
        add_box(sp, (x, y + 0.03, zp - 0.05), (2 * hwid, 0.44, 0.10))
        if zp - 0.10 - zf > 0.03:
            add_box(sp, (x, y + 0.0, 0.5 * (zf + zp - 0.10)), (2 * hwid - 0.10, 0.34, zp - 0.10 - zf))
        base = (x, y - 0.19, zp - 0.04)
        hb = {'ejection': 0.72, 'ww2': 0.58, 'bomber': 0.62}.get(style, 0.6)
        tb = 0.12 if style == 'ejection' else 0.06
        add_obox(sp, v_add(base, v_add(v_mul(up, hb / 2), v_mul(nr, -tb / 2))), ax, up, nr, hwid, hb / 2, tb / 2)
        top = v_add(base, v_mul(up, hb))
        if style == 'ejection':
            hbx = pit.get('headbox', 0.13)
            add_obox(sp, v_add(top, v_add(v_mul(up, hbx), v_mul(nr, -0.09))), ax, up, nr, 0.17, hbx, 0.11)
            top = v_add(top, v_mul(up, 2 * hbx - 0.26))
            for sx in (-1, 1):
                add_obox(sp, v_add(v_add(base, (sx * (hwid + 0.02), 0, 0)), v_add(v_mul(up, hb * 0.55), v_mul(nr, -0.07))),
                         ax, up, nr, 0.02, hb * 0.55, 0.05)
            # firing handle (yellow/black) between the knees, ejection-handle loop on the headbox
            add_box(acc, (x, y + 0.27, zp - 0.02), (0.10, 0.03, 0.06))
            add_obox(acc, v_add(top, v_add(v_mul(up, 0.27), v_mul(nr, 0.0))), ax, up, nr, 0.10, 0.012, 0.02)
        elif style == 'ww2':
            # head armour plate
            add_obox(sp, v_add(top, v_add(v_mul(up, 0.17), v_mul(nr, -0.03))), ax, up, nr, 0.17, 0.15, 0.015)
            add_box(acc, (x, y - 0.02, zp + 0.005), (2 * hwid - 0.06, 0.34, 0.02))   # seat cushion
        else:
            add_obox(sp, v_add(top, v_add(v_mul(up, 0.10), v_mul(nr, -0.04))), ax, up, nr, 0.14, 0.10, 0.05)
            for sx in (-1, 1):
                add_box(sp, (x + sx * (hwid + 0.03), y - 0.02, zp + 0.13), (0.05, 0.36, 0.05))
        # control stick / yoke
        stick = pit.get('stick', 'stick')
        if stick == 'stick':
            sy = y + 0.40
            add_box(acc if style == 'ejection' else sp, (x, sy, 0.5 * (zf + zp + 0.32)), (0.03, 0.03, zp + 0.32 - zf))
            add_box(sp, (x, sy, zp + 0.36), (0.05, 0.05, 0.10))
        elif stick == 'side':
            add_box(sp, (x + 0.33, y + 0.18, zp + 0.18), (0.04, 0.05, 0.10))
        elif stick == 'yoke':
            sy = y + 0.48
            add_box(sp, (x, sy, 0.5 * (zf + zp + 0.40)), (0.06, 0.06, zp + 0.40 - zf))
            add_box(sp, (x, sy - 0.04, zp + 0.42), (0.32, 0.03, 0.04))
            for sx in (-0.15, 0.15):
                add_box(sp, (x + sx, sy - 0.04, zp + 0.47), (0.03, 0.03, 0.12))
        # side consoles where there is room
        if pit.get('consoles', True):
            zt = zp + 0.10
            for sgn in (-1, 1):
                hw = min(CS.half_width_at_z(prof.section(yy), zz) for yy in (y - 0.27, y, y + 0.43)
                         for zz in (zf, 0.5 * (zf + zt), zt)) - 0.04
                inner = abs(x) + hwid + 0.06 if sgn * x >= 0 else None
                if inner is None or hw - inner < 0.07:
                    continue
                xc = sgn * 0.5 * (inner + hw)
                add_box(sp, (xc, y + 0.08, 0.5 * (zf + zt)), (hw - inner, 0.70, zt - zf))

    def ring_points(self, prof, y, phis=None, offset=0.0):
        bs = BodySurf(prof)
        out = []
        for ph in (phis or self.phis):
            q = bs.point(y, ph)
            out.append(q)
        return out

    def cap_ring(self, prof, y, out, variant, name):
        p = self.piece(name, CL_CAP, variant, smooth=False)
        pts = self.ring_points(prof, y)
        s = prof.section(y)
        ring_cap(p, pts, (0.0, y, s['zc'] + 0.5 * (s['ht'] - s['hb'])), out)

    def adapter(self, prof, v):
        ys0, length, r, zc = CS.adapter_geometry(self.c, v)
        p = self.piece('adapter_' + v['key'], CL_BODY, v['key'])
        bs = BodySurf(prof)

        class AdSurf:
            def point(s_, y, phi):
                t = smooth01((y - ys0) / length)
                a = bs.point(ys0, phi)
                b = (r * math.sin(phi), y, zc + r * math.cos(phi))
                return (a[0] + (b[0] - a[0]) * t, y, a[2] + (b[2] - a[2]) * t)

            def normal(s_, y, phi):
                return (0, 0, 1)

        ys = lin(ys0, ys0 + length, 8)
        build_surface_loft(p, AdSurf(), ys, self.phis)
        cap = self.piece('front_cap_' + v['key'], CL_CAP, v['key'], smooth=False)
        pts = [(r * math.sin(ph), ys0 + length, zc + r * math.cos(ph)) for ph in self.phis]
        ring_cap(cap, pts, (0.0, ys0 + length, zc), (0, 1, 0))

    def intake_nose(self, prof, v):
        c = self.c
        it = c['intake']
        split = c['split_y']
        key = v['key']
        y_lip = it['y_lip']
        self.body_section(prof, split, y_lip, key, 'nose_' + key)
        s = prof.section(y_lip)
        zc0 = s['zc']
        bs = BodySurf(prof)
        r_out, r_in = it['r_out'], it['r_in']
        r_mid, r_lip = 0.5 * (r_out + r_in), 0.5 * (r_out - r_in)
        lip = self.piece('lip_' + key, CL_BODY, key)
        duct = self.piece('duct_' + key, CL_INTAKE, key)

        def lip_point(beta, phi):
            q = bs.point(y_lip, phi)
            rad = r_mid + r_lip * math.cos(beta)
            k = rad / r_out
            return (q[0] * k, y_lip + 0.85 * r_lip * math.sin(beta), zc0 + (q[2] - zc0) * k)

        betas = lin(0.0, math.pi, 10)
        rows, uvr = [], []
        for b in betas:
            pts = [lip_point(b, ph) for ph in self.phis]
            u = arc_uvs(pts, len(pts) // 2)
            rows.append([lip.vert(q) for q in pts])
            uvr.append([(u[j], b * r_lip) for j in range(len(pts))])
        grid_faces(lip, rows, uvr)
        # duct: continues backwards from the inner lip edge, faces the axis
        rows, uvr = [], []
        for k, yy in enumerate(lin(y_lip, y_lip - it['depth'], 8)):
            pts = []
            for ph in self.phis:
                q = lip_point(math.pi, ph)
                pts.append((q[0], yy, q[2]))
            u = arc_uvs(pts, len(pts) // 2)
            rows.append([duct.vert(q) for q in pts])
            uvr.append([(u[j], -yy) for j in range(len(pts))])
        grid_faces(duct, rows, uvr)
        back = self.piece('ductcap_' + key, CL_DARK, key, smooth=False)
        yb = y_lip - it['depth']
        pts = [(lip_point(math.pi, ph)[0], yb, lip_point(math.pi, ph)[2]) for ph in self.phis]
        ring_cap(back, pts, (0.0, yb, zc0), (0, 1, 0))
        if it.get('splitter'):
            sp = self.piece('splitter_' + key, CL_INTAKE, key, smooth=False, own_uv=False)
            h = r_in * 0.98
            add_box(sp, (0.0, y_lip - 0.25, zc0), (0.035, 0.50, 2 * h))

    def canopy(self, prof, ckeys, frames, variant):
        cprof = CS.CanopyProfile(ckeys, prof)
        cs = CanopySurf(cprof)
        tag = variant or 'common'
        glass = self.piece('canopy_' + tag, CL_GLASS, variant)
        ys = lin(cprof.y0, cprof.y1, max(12, int((cprof.y1 - cprof.y0) / 0.03)))
        phis = lin(-math.pi / 2, math.pi / 2, 49)
        build_surface_loft(glass, cs, ys, phis)
        fr = self.piece('frames_' + tag, CL_FRAME, variant, smooth=False, own_uv=False)
        t = 0.011
        for f in frames:
            if f[0] == 'bow':
                _, yb, w = f
                y0, y1 = max(cprof.y0, yb - w / 2), min(cprof.y1, yb + w / 2)
                if y1 - y0 < 0.005:
                    continue
                strip_on_surface(fr, cs, [y0, 0.5 * (y0 + y1), y1], lambda y: lin(-math.pi / 2, math.pi / 2, 41), t)
            elif f[0] == 'rail':
                _, deg, y0, y1, w = f
                y0, y1 = max(cprof.y0, y0), min(cprof.y1, y1)
                if y1 - y0 < 0.01:
                    continue
                a = math.radians(deg)

                def phis_fn(y, a=a, w=w):
                    e = 1e-3
                    dl = math.dist(cs.point(y, a + e), cs.point(y, a - e)) / (2 * e)
                    d = min(0.5, (w / 2) / max(1e-3, dl))
                    lo, hi = max(-math.pi / 2, a - d), min(math.pi / 2, a + d)
                    return lin(lo, hi, 3)
                strip_on_surface(fr, cs, lin(y0, y1, max(3, int((y1 - y0) / 0.03))), phis_fn, t)

    def glazing(self, prof, g, variant):
        bs = BodySurf(prof)
        tag = variant or 'common'
        glass = self.piece('glazing_' + tag, CL_GLASS, variant)
        fr = self.piece('glazing_frames_' + tag, CL_FRAME, variant, smooth=False, own_uv=False)
        y0 = g['y0']
        y1 = min(g['y1'], prof.length)
        tip = prof.nose is not None and y1 >= prof.length - 1e-6
        ys = [y for y in stations(prof, y0, y1, 0.04)]
        ranges = glazing_ranges(g)
        for lo, hi in ranges:
            ph = lin(lo, hi, max(8, int((hi - lo) / (2 * math.pi) * len(self.phis))))
            build_surface_loft(glass, bs, ys, ph, offset=0.004, tip_at_end=tip and not g.get('sides'))
        w = g.get('frame_w', 0.06)
        t = 0.013
        ystop = min(g.get('frame_y_stop', y1), prof.length - 0.02)
        for yb in g.get('frames_y', []):
            if yb > prof.length - 0.03:
                continue
            for lo, hi in ranges:
                strip_on_surface(fr, bs, [yb - w / 2, yb, yb + w / 2],
                                 lambda y, lo=lo, hi=hi: lin(lo, hi, max(6, int((hi - lo) / 0.05))), t)
        fphi = list(g.get('frames_phi', []))
        if g.get('sides'):
            fphi = sorted(set(fphi) | {-d for d in fphi})
        for deg in fphi:
            a = math.radians(deg)
            if not any(lo - 1e-6 <= a <= hi + 1e-6 for lo, hi in ranges):
                continue

            def phis_fn(y, a=a):
                e = 1e-3
                dl = math.dist(bs.point(y, a + e), bs.point(y, a - e)) / (2 * e)
                d = min(0.3, (w / 2) / max(1e-3, dl))
                return lin(a - d, a + d, 3)
            yy = lin(y0, ystop, max(4, int((ystop - y0) / 0.04)))
            strip_on_surface(fr, bs, yy, phis_fn, t)

    def detail(self, d, variant=None):
        c = self.c
        kind = d[0]
        prof = self.common_prof
        if variant is not None:
            prof = CS.variant_body(c, next(v for v in self.variants if v['key'] == variant))
        bs = BodySurf(prof)
        if kind == 'box':
            _, y, x, z, sx, sy, sz, cls = d
            p = self.piece('box', CLASS_NAMES[cls], variant, smooth=False, own_uv=False)
            add_box(p, (x, y, z), (sx, sy, sz))
        elif kind == 'blade':
            _, y, chord, h, cls = d
            p = self.piece('blade', CLASS_NAMES[cls], variant, smooth=False, own_uv=False)
            zb = bs.top_z(y) - 0.03
            sweep = 0.45 * h
            poly = [(y + chord / 2, zb), (y - chord / 2, zb), (y - chord / 2 - sweep, zb + h + 0.03),
                    (y - chord / 2 - sweep + 0.45 * chord, zb + h + 0.03)]
            add_prism(p, poly, -0.007, 0.007)
        elif kind == 'pitot':
            _, y0, y1, r0, r1, region = d
            boom = y1 - y0
            if region == 'nose' and c.get('split_y'):
                for v in self.variants:
                    if v.get('nose') != 'native':
                        continue
                    vp = CS.variant_body(c, v)
                    p = self.piece('pitot_' + v['key'], CL_METAL, v['key'], own_uv=False)
                    z = vp.section(vp.length)['zc']
                    add_tube(p, vp.length - 0.06, vp.length + boom, r0, r1, 0.0, z)
            else:
                p = self.piece('pitot', CL_METAL, variant, own_uv=False)
                z = prof.section(prof.length)['zc']
                add_tube(p, y0 - 0.06, y1, r0, r1, 0.0, z)
        elif kind == 'ball':
            _, y, x, r, cls = d
            p = self.piece('ball', CLASS_NAMES[cls], variant, own_uv=False)
            zt = bs.top_z(y, x)
            add_ellipsoid(p, (x, y, zt + 0.25 * r), r, r, r)
        elif kind == 'turret':
            _, y, side, r = d
            dome = self.piece('turret', CL_BODY, variant, own_uv=False)
            if side == 'top':
                zs = bs.top_z(y)
                zc = zs - 0.25 * r
            else:
                zs = bs.bottom_z(y)
                zc = zs + 0.25 * r
            add_ellipsoid(dome, (0.0, y, zc), r, r, r * 0.72)
            guns = self.piece('turret_guns', CL_METAL, variant, smooth=True, own_uv=False)
            zg = zc + (0.32 * r if side == 'top' else -0.32 * r)
            for gx in (-0.13, 0.13):
                add_tube(guns, y + 0.2 * r, y + r + 0.95, 0.035, 0.028, gx, zg, sides=8, tip=False)
        elif kind == 'blister':
            _, y0, y1, x, rw, rh, side, cls, tag = d
            p = self.piece('blister', CLASS_NAMES[cls], variant)
            add_blister(p, bs, y0, y1, x, rw, rh, side, peak={'beule': 0.30, 'gun': 0.40}.get(tag, 0.5))


# =============================================================================== Blender objects

def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    if os.environ.get('ROPP_THREADS'):   # leave cores free for other programs
        sc.render.threads_mode = 'FIXED'
        sc.render.threads = max(1, int(os.environ['ROPP_THREADS']))
    try:
        sc.view_settings.view_transform = 'Standard'
    except Exception:
        pass
    world = bpy.data.worlds.new('World')
    sc.world = world
    return sc


def make_object(piece, vindex):
    me = bpy.data.meshes.new(piece.name)
    me.from_pydata(piece.v, [], piece.f)
    me.update()
    uvl = me.uv_layers.new(name='UVMap')
    flat = []
    for uvs in piece.uv:
        for u, v in uvs:
            flat.extend((u, v))
    uvl.data.foreach_set('uv', flat)
    if piece.smooth:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(38))
    else:
        me.shade_flat()
    attr = me.color_attributes.new('cls', 'FLOAT_COLOR', 'POINT')
    col = np.tile(np.array([piece.cls / 16.0, vindex / 16.0, 1.0, 1.0], dtype=np.float32), len(me.vertices))
    attr.data.foreach_set('color', col)
    ob = bpy.data.objects.new(piece.name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob['cls'] = piece.cls
    ob['variant'] = piece.variant or ''
    return ob


def select_only(objs, active=None):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objs[0] if objs else None)


def unwrap_and_pack(objs, pieces):
    # smart projection for pieces without their own UVs
    smart = [o for o, p in zip(objs, pieces) if not p.own_uv]
    if smart:
        select_only(smart)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode='OBJECT')
    select_only(objs)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.average_islands_scale()
    bpy.ops.object.mode_set(mode='OBJECT')
    # texel priority per surface class
    for o in objs:
        s = CLASS_UV_SCALE.get(o['cls'], 1.0)
        if abs(s - 1.0) < 1e-6:
            continue
        uv = np.empty(len(o.data.loops) * 2, dtype=np.float32)
        o.data.uv_layers.active.data.foreach_get('uv', uv)
        uv *= s
        o.data.uv_layers.active.data.foreach_set('uv', uv)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    try:
        bpy.ops.uv.pack_islands(rotate=True, margin=0.0035, shape_method='CONCAVE')
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=True, margin=0.0035)
    bpy.ops.object.mode_set(mode='OBJECT')


# =============================================================================== baking

def bake_maps(objs, variants_of, vkeys, tex, ao_dist):
    sc = bpy.context.scene
    sc.render.bake.margin_type = 'EXTEND'
    imgs = {}
    for name in ('cov', 'cls', 'pos', 'nrm', 'ao'):
        imgs[name] = bpy.data.images.new('bk_' + name, tex, tex, alpha=True, float_buffer=True)
        imgs[name].colorspace_settings.name = 'Non-Color'
    mat = bpy.data.materials.new('BAKE')
    nt = mat.node_tree if mat.node_tree else None
    if nt is None:
        mat.use_nodes = True
        nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    em = nt.nodes.new('ShaderNodeEmission')
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    attr = nt.nodes.new('ShaderNodeAttribute')
    attr.attribute_name = 'cls'
    timg = nt.nodes.new('ShaderNodeTexImage')
    nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
    nt.nodes.active = timg
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)

    def link(src):
        for l in list(em.inputs['Color'].links):
            nt.links.remove(l)
        nt.links.new(src, em.inputs['Color'])

    def bake(kind, img, margin, clear, sel):
        timg.image = img
        select_only(sel)
        try:
            bpy.ops.object.bake(type=kind, margin=margin, use_clear=clear, margin_type='EXTEND')
        except TypeError:
            bpy.ops.object.bake(type=kind, margin=margin, use_clear=clear)

    sc.cycles.samples = 1
    zero = np.zeros(tex * tex * 4, dtype=np.float32)
    imgs['cov'].pixels.foreach_set(zero)
    link(attr.outputs['Color'])
    bake('EMIT', imgs['cov'], 0, False, objs)
    bake('EMIT', imgs['cls'], 16, True, objs)
    link(geo.outputs['Position'])
    bake('EMIT', imgs['pos'], 16, True, objs)
    link(geo.outputs['Normal'])
    bake('EMIT', imgs['nrm'], 16, True, objs)

    sc.cycles.samples = 24
    sc.world.light_settings.distance = ao_dist
    first = True
    for vk in vkeys:
        # glass is see-through: it neither occludes nor needs AO (it has its own texture)
        visible = [o for o in objs if o['variant'] in ('', vk) and o['cls'] not in GLASS_CLASSES]
        for o in objs:
            o.hide_render = o not in visible
        targets = visible if first else [o for o in visible if o['variant'] == vk]
        if targets:
            bake('AO', imgs['ao'], 16, first, targets)
            first = False
    for o in objs:
        o.hide_render = False

    arrs = {}
    for k, img in imgs.items():
        a = np.empty(tex * tex * 4, dtype=np.float32)
        img.pixels.foreach_get(a)
        arrs[k] = a.reshape(tex, tex, 4)
    return arrs


# =============================================================================== noise (numpy)

def _hash(ix, iy, iz, seed):
    h = (ix.astype(np.uint32) * np.uint32(73856093)) ^ (iy.astype(np.uint32) * np.uint32(19349663)) \
        ^ (iz.astype(np.uint32) * np.uint32(83492791)) ^ np.uint32((seed * 2654435761) & 0xffffffff)
    h ^= h >> np.uint32(13)
    h *= np.uint32(0x5bd1e995)
    h ^= h >> np.uint32(15)
    return (h & np.uint32(0xffffff)).astype(np.float32) / float(0xffffff)


def value_noise(P, seed):
    f = np.floor(P)
    t = P - f
    t = t * t * (3.0 - 2.0 * t)
    i = f.astype(np.int64)
    ix, iy, iz = i[..., 0], i[..., 1], i[..., 2]
    tx, ty, tz = t[..., 0], t[..., 1], t[..., 2]
    out = 0.0
    for dx in (0, 1):
        wx = tx if dx else 1.0 - tx
        for dy in (0, 1):
            wy = ty if dy else 1.0 - ty
            for dz in (0, 1):
                wz = tz if dz else 1.0 - tz
                out = out + wx * wy * wz * _hash(ix + dx, iy + dy, iz + dz, seed)
    return out


def fbm(P, freq, seed, octaves=3, stretch=(1.0, 1.0, 1.0)):
    Q = P * np.array(stretch, dtype=np.float32) * freq
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * value_noise(Q, seed + 17 * o)
        norm += amp
        amp *= 0.5
        Q = Q * 2.03
    return total / norm


_TEXT_CACHE = {}
DECAL_FONTS = (r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\Arialbd.ttf',
               '/Library/Fonts/Arial Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')


def text_mask(text, bold=1.0, px=128):
    """Anti-aliased coverage mask (rows top->bottom) of a text string; height = cap height + 10 % margin."""
    key = (text, bold, px)
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    cu = bpy.data.curves.new('decal_txt', 'FONT')
    cu.body = text
    for fp in DECAL_FONTS:
        if os.path.exists(fp):
            cu.font = bpy.data.fonts.load(fp, check_existing=True)
            break
    ob = bpy.data.objects.new('decal_txt', cu)
    bpy.context.scene.collection.objects.link(ob)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    co = np.array([v.co[:2] for v in me.vertices], dtype=np.float64)
    tris = np.array([t.vertices[:] for t in me.loop_triangles], dtype=np.int64)
    ev.to_mesh_clear()
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    x0, y0 = co.min(axis=0)
    x1, y1 = co.max(axis=0)
    hgt = y1 - y0
    pad = 0.10 * hgt
    ss = 3  # supersampling
    H = px * ss
    scale = H / (hgt + 2 * pad)
    W = int(math.ceil((x1 - x0 + 2 * pad) * scale))
    mask = np.zeros((H, W), dtype=np.float32)
    P = (co - [x0 - pad, y0 - pad]) * scale
    P[:, 1] = H - P[:, 1]
    for t in tris:
        a, b, c = P[t[0]], P[t[1]], P[t[2]]
        lo = np.floor(np.minimum(np.minimum(a, b), c)).astype(int)
        hi = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        lo = np.maximum(lo, 0)
        hi = np.minimum(hi, [W, H])
        if hi[0] <= lo[0] or hi[1] <= lo[1]:
            continue
        gx, gy = np.meshgrid(np.arange(lo[0], hi[0]) + 0.5, np.arange(lo[1], hi[1]) + 0.5)
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
        ins = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        mask[lo[1]:hi[1], lo[0]:hi[0]] = np.maximum(mask[lo[1]:hi[1], lo[0]:hi[0]], ins)
    if bold > 1.0:
        mask = dilate(mask, int(round((bold - 1.0) * 0.04 * H)))
    W2 = W // ss
    mask = mask[:px * ss, :W2 * ss].reshape(px, ss, W2, ss).mean(axis=(1, 3))
    _TEXT_CACHE[key] = mask
    return mask


def dilate(mask, r):
    if r <= 0:
        return mask
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            out = np.maximum(out, np.roll(np.roll(mask, dy, 0), dx, 1))
    return out


def sstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# =============================================================================== texture painting

class Painter:
    def __init__(self, c, maps, tex):
        self.c = c
        self.tex = tex
        self.cov = maps['cov'][..., 2] > 0.5
        self.cls = np.rint(maps['cls'][..., 0] * 16.0).astype(np.int32)
        self.P = maps['pos'][..., :3].astype(np.float32)
        N = maps['nrm'][..., :3]
        self.N = (N / np.maximum(1e-6, np.linalg.norm(N, axis=-1, keepdims=True))).astype(np.float32)
        ao = np.clip(maps['ao'][..., 0], 0.0, 1.0)
        for _ in range(2):  # light blur: hides bake noise, islands are padded by the bake margin
            ao = (ao + np.roll(ao, 1, 0) + np.roll(ao, -1, 0) + np.roll(ao, 1, 1) + np.roll(ao, -1, 1)) / 5.0
        self.AO = ao
        prof = CS.BodyProfile(c['body'], max(v.get('length', c['length']) for v in c['variants']) + 0.01,
                              None)
        ys = np.linspace(-0.1, prof.length + 2.0, 600)
        self.zc_tab = (ys, np.array([prof.section(float(y))['zc'] for y in ys], dtype=np.float32))
        self.rng = random.Random(zlib.crc32(c['id'].encode()))
        self.prepare_geometry()

    # ---------------------------------------------------------------------------------------
    def prepare_geometry(self):
        c, P = self.c, self.P
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        zc = np.interp(y, *self.zc_tab).astype(np.float32)
        self.phi = np.arctan2(x, z - zc)
        self.r = np.sqrt(x * x + (z - zc) ** 2)
        self.s = self.phi * np.maximum(0.2, self.r)
        body = (self.cls == CL_BODY) | (self.cls == CL_FRAME)
        self.body = body
        pn = c['panel']
        L = max(v.get('length', c['length']) for v in c['variants'])
        rnd = self.rng
        # frame stations
        fy = []
        yy = pn['frame_step'] * 0.6
        stop = c.get('radome_y') or L
        while yy < stop - 0.1:
            fy.append(yy)
            yy += pn['frame_step'] * (0.85 + 0.3 * rnd.random())
        if c.get('radome_y'):
            fy.append(c['radome_y'])
        if c.get('split_y'):
            fy.append(c['split_y'])
        fy = np.array(sorted(fy), dtype=np.float32)
        self.frame_y = fy
        idx = np.clip(np.searchsorted(fy, y), 1, len(fy) - 1)
        dy = np.minimum(np.abs(y - fy[idx - 1]), np.abs(y - fy[idx]))
        n_str = pn['stringers']
        step = 2 * math.pi / n_str
        dphi = np.abs(((self.phi + step / 2) % step) - step / 2)
        ds_ = dphi * np.maximum(0.2, self.r)
        w = 0.0035 if c['rear_dia'] < 2.5 else 0.005
        # longitudinal seams only every other frame bay, so panels read as staggered skins, not a grid
        bay = np.floor(np.interp(y, fy, np.arange(len(fy)))).astype(np.int64)
        stag = (((bay + np.floor((self.phi + math.pi) / step).astype(np.int64)) % 2) == 0)
        groove = np.maximum(np.exp(-(dy / w) ** 2), np.where(stag, np.exp(-(ds_ / w) ** 2) * 0.7, 0.0))
        # hatches (mirrored left/right)
        hatch = np.zeros_like(y)
        for _ in range(pn['hatches']):
            hy = 0.25 + rnd.random() * (min(stop, L) - 0.7)
            hp = math.radians(45 + rnd.random() * 80)
            hh = 0.12 + 0.18 * rnd.random()
            hw = 0.10 + 0.14 * rnd.random()
            for sgn in (1, -1):
                du = np.abs(y - hy) - hh
                dv = np.abs(self.phi * np.maximum(0.2, self.r) - sgn * hp * np.maximum(0.2, self.r)) - hw
                d = np.abs(np.maximum(du, dv))
                inside = (du < 0.02) & (dv < 0.02)
                hatch = np.maximum(hatch, np.where(inside, np.exp(-(d / w) ** 2), 0.0))
        # explicit doors / access hatches on the fuselage sides: (y0, y1, z0, z1, side) side = -1 port, +1 stbd, 0 both
        for y0d, y1d, z0d, z1d, sd in c.get('doors', []):
            for sgn in ((-1, 1) if sd == 0 else (sd,)):
                du = np.abs(y - 0.5 * (y0d + y1d)) - 0.5 * (y1d - y0d)
                dv = np.abs(z - 0.5 * (z0d + z1d)) - 0.5 * (z1d - z0d)
                d = np.abs(np.maximum(du, dv))
                ok = (du < 0.02) & (dv < 0.02) & (np.sign(x) == sgn) & (np.abs(self.N[..., 0]) > 0.2)
                hatch = np.maximum(hatch, np.where(ok, np.exp(-(d / w) ** 2), 0.0))
        rad = np.zeros_like(y, dtype=bool)
        if c.get('radome_y'):
            rad = y > c['radome_y'] + 0.01
        self.radome = rad & body
        line = np.maximum(groove, hatch)
        line = np.where(rad, np.exp(-((y - (c.get('radome_y') or 0)) / w) ** 2), line)
        line = np.where(body, line, 0.0)
        self.line = line.astype(np.float32)
        rivet = np.zeros_like(y)
        if pn.get('rivets'):
            sp = 0.034
            rr = 0.0042
            idxr = np.clip(np.searchsorted(fy, y), 1, len(fy) - 1)
            dfy = np.minimum(np.abs(np.abs(y - fy[idxr - 1]) - 0.014), np.abs(np.abs(y - fy[idxr]) - 0.014))
            sm = np.abs(((self.s + sp / 2) % sp) - sp / 2)
            rivet = np.exp(-(dfy ** 2 + sm ** 2) / rr ** 2)
            rivet = np.where(body & ~rad, rivet, 0.0)
        self.rivet = rivet.astype(np.float32)
        self.height = (-0.0010 * self.line + 0.00035 * self.rivet).astype(np.float32)

    # ---------------------------------------------------------------------------------------
    def normal_map(self):
        h = self.height
        P = self.P
        dPu = np.gradient(P, axis=1)
        dPv = np.gradient(P, axis=0)
        su = np.maximum(1e-5, np.linalg.norm(dPu, axis=-1))
        sv = np.maximum(1e-5, np.linalg.norm(dPv, axis=-1))
        gx = np.gradient(h, axis=1) / su
        gy = np.gradient(h, axis=0) / sv
        valid = (su < 0.05) & (sv < 0.05)
        gx = np.where(valid, np.clip(gx, -1.5, 1.5), 0.0)
        gy = np.where(valid, np.clip(gy, -1.5, 1.5), 0.0)
        n = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        out = np.empty(h.shape + (4,), dtype=np.float32)
        out[..., :3] = n * 0.5 + 0.5
        out[..., 3] = 1.0
        return out

    # ---------------------------------------------------------------------------------------
    def windscreen_y(self):
        c = self.c
        if c.get('canopy'):
            return c['canopy'][-1]['y']
        gl = c.get('glazing') or c['variants'][0].get('glazing')
        if gl:
            return gl[0]['y1']  # front edge of the windows
        return c['length']

    def livery(self, lv):
        c, P, N = self.c, self.P, self.N
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        H, W = y.shape
        seed = zlib.crc32((c['id'] + lv['key']).encode()) % 9973
        top = hexcol(lv['top'])
        col = np.empty((H, W, 3), dtype=np.float32)
        col[:] = top
        pat = lv['pattern']
        if pat == 'camo' and lv['colors']:
            n = fbm(P, 0.9 / lv['scale'], seed, octaves=3)
            cols = [hexcol(h) for h in lv['colors']]
            sel = n[self.body]
            qs = np.quantile(sel, [k / len(cols) for k in range(1, len(cols))]) if sel.size else []
            col[:] = cols[0]
            for k, q in enumerate(qs):
                m = sstep(q - 0.004, q + 0.004, n)[..., None]
                col = col * (1 - m) + cols[k + 1] * m
        elif pat == 'splinter' and lv['colors']:
            rnd = random.Random(seed)
            acc = np.zeros_like(y)
            for _ in range(3):
                d = np.array([rnd.uniform(-1, 1), rnd.uniform(-0.6, 0.6), rnd.uniform(-1, 1)], dtype=np.float32)
                d /= np.linalg.norm(d)
                acc = acc + np.floor(np.tensordot(P, d, axes=([-1], [0])) * (2.4 / lv['scale']) + rnd.random())
            par = (acc.astype(np.int64) % 2).astype(np.float32)[..., None]
            col = hexcol(lv['colors'][0]) * (1 - par) + hexcol(lv['colors'][1]) * par
        elif pat == 'digital' and lv['colors']:
            # pixelated camouflage: noise sampled on a coarse voxel grid, hard-edged colour bands
            cell = 0.10 * lv['scale']
            Q = ((np.floor(P / cell) + 0.5) * cell).astype(np.float32)
            n = 0.75 * fbm(Q, 0.55 / lv['scale'], seed, octaves=3) + 0.25 * fbm(Q, 2.0 / lv['scale'], seed + 5, octaves=2)
            cols = [hexcol(h) for h in lv['colors']]
            sel = n[self.body]
            fr = lv.get('fractions') or [k / len(cols) for k in range(1, len(cols))]
            qs = np.quantile(sel, fr) if sel.size else []
            col[:] = cols[0]
            for k, q in enumerate(qs):
                col = np.where((n > q)[..., None], cols[k + 1], col)
        elif pat == 'metal':
            fs = c['panel']['frame_step']
            pid_y = np.floor(y / fs).astype(np.int64)
            pid_p = np.floor((self.phi + math.pi) / (2 * math.pi / c['panel']['stringers'])).astype(np.int64)
            tint = 0.958 + 0.065 * _hash(pid_y, pid_p, np.zeros_like(pid_y), seed)
            brush = fbm(P, 3.0, seed + 5, octaves=2, stretch=(6.0, 0.25, 6.0))
            col = col * (tint * (0.97 + 0.06 * brush))[..., None]

        wob = (fbm(P, 1.4, seed + 3, octaves=2) - 0.5) * 0.22
        upness = N[..., 2] + wob
        if lv['under']:
            m = sstep(lv['split'] - 0.03, lv['split'] + 0.03, upness)[..., None]
            col = col * m + hexcol(lv['under']) * (1 - m)
        if lv['belly']:
            m = sstep(lv['split'] - 0.02, lv['split'] + 0.02, upness)[..., None]
            col = col * m + hexcol(lv['belly']) * (1 - m)
        if lv['mottle']:
            side = sstep(0.25, 0.55, np.abs(N[..., 0])) * sstep(-0.45, -0.15, N[..., 2]) * (1.0 - sstep(0.55, 0.8, N[..., 2]))
            mn = fbm(P, 12.0, seed + 9, octaves=2)
            m = (sstep(0.50, 0.66, mn) * side * 0.85)[..., None]   # soft-edged dapple
            col = col * (1 - m) + hexcol(lv['mottle']) * m
        if lv['whitewash']:
            wn = fbm(P, 2.4, seed + 11, octaves=3)
            streak = fbm(P, 4.0, seed + 12, octaves=2, stretch=(1.0, 0.15, 4.0))
            m = (sstep(0.30, 0.55, wn + 0.25 * streak) * sstep(-0.5, -0.2, N[..., 2]) * 0.92)[..., None]
            col = col * (1 - m) + np.array([0.90, 0.90, 0.87], dtype=np.float32) * m
        # anti-glare panel ahead of the windscreen
        if lv['antiglare']:
            yw = self.windscreen_y()
            ag_len = 1.1 if c['rear_dia'] < 2.5 else 1.6
            t = np.clip((y - yw + 0.05) / ag_len, 0, 1)
            hw = (0.22 if c['rear_dia'] < 2.5 else 0.55) * (1.0 - 0.35 * t)
            m = ((y > yw - 0.05) & (y < yw + ag_len) & (np.abs(x) < hw) & (N[..., 2] > 0.35)
                 & (self.cls == CL_BODY)).astype(np.float32)
            col = np.where(m[..., None] > 0, hexcol(lv['antiglare']), col)
        if lv['radome'] and c.get('radome_y'):
            col = np.where(self.radome[..., None], hexcol(lv['radome']), col)
        if lv['frame']:
            col = np.where((self.cls == CL_FRAME)[..., None], hexcol(lv['frame']), col)

        # gun ports
        for gy, gdeg, gr, _region in c.get('gunports', []):
            a = math.radians(gdeg)
            d = np.sqrt((y - gy) ** 2 + ((self.phi - a) * np.maximum(0.2, self.r)) ** 2)
            core = d < gr
            ring = (d >= gr) & (d < gr * 1.6)
            col = np.where((core & self.body)[..., None], np.array([0.05, 0.05, 0.05], np.float32), col)
            col = np.where((ring & self.body)[..., None], np.array([0.42, 0.43, 0.44], np.float32), col)

        # formation ("slime") lights
        slime = np.zeros_like(y, dtype=bool)
        for y0, y1, zl in c.get('slime', []):
            slime |= (y > y0) & (y < y1) & (np.abs(z - zl) < 0.035) & (np.abs(N[..., 0]) > 0.55) & self.body
        col = np.where(slime[..., None], np.array([0.66, 0.70, 0.58], np.float32), col)
        self.slime = slime

        # intake lip colour (MiG-15 red nose)
        if lv.get('lip') and c.get('intake'):
            ylip = c['intake']['y_lip']
            m = ((y > ylip - lv.get('lip_w', 0.22)) & self.body)
            col = np.where(m[..., None], hexcol(lv['lip']), col)
        # exhaust and gun soot streaks, then painted markings
        col = self.soot(col, lv, seed)
        col = self.decals(col, lv)

        # other surface classes
        cls = self.cls
        glass = hexcol(c['glass'])
        col = np.where((cls == CL_GLASS)[..., None], glass, col)
        col = np.where((cls == CL_DOME)[..., None], glass * 0.4, col)
        col = np.where((cls == CL_METAL)[..., None], np.array([0.56, 0.57, 0.58], np.float32), col)
        col = np.where((cls == CL_INTAKE)[..., None], np.array([0.62, 0.64, 0.65], np.float32), col)
        col = np.where((cls == CL_CAP)[..., None], np.array([0.30, 0.32, 0.33], np.float32), col)
        col = np.where((cls == CL_DARK)[..., None], np.array([0.05, 0.05, 0.055], np.float32), col)
        col = self.interior(col, seed)

        # weathering, panel lines, ambient occlusion
        grime = fbm(P, 2.2, seed + 21, octaves=3, stretch=(1.0, 0.18, 1.0))
        paint = self.body | (cls == CL_METAL)
        col = np.where(paint[..., None], col * (0.95 + 0.08 * grime)[..., None], col)
        col = col * (1.0 - (0.26 if c['panel'].get('rivets') else 0.18) * self.line)[..., None]
        col = col * (1.0 + 0.10 * self.rivet)[..., None]
        ao = self.AO
        aof = np.where(cls == CL_GLASS, 0.55 + 0.45 * ao, 0.28 + 0.72 * ao ** 0.8)
        col = col * aof[..., None]

        gloss = np.full(y.shape, lv['gloss'], dtype=np.float32)
        gloss = gloss * (0.85 + 0.25 * grime) * (0.55 + 0.45 * ao)
        gloss = np.where(self.radome, np.minimum(1.0, gloss + 0.12), gloss)
        gloss = np.where((cls == CL_GLASS) | (cls == CL_DOME), 0.96, gloss)
        gloss = np.where(cls == CL_METAL, 0.75, gloss)
        gloss = np.where(cls == CL_INTAKE, 0.25, gloss)
        gloss = np.where((cls == CL_CAP) | (cls == CL_DARK), 0.15, gloss)
        gloss = np.where(cls == CL_INTERIOR, 0.12, gloss)
        gloss = np.where(cls == CL_PANEL, 0.30, gloss)
        gloss = np.where(cls == CL_SEAT, 0.18, gloss)
        gloss = np.where(cls == CL_ACCENT, 0.35, gloss)
        gloss = gloss * (1.0 - 0.6 * self.line)
        gloss = gloss * (1.0 - 0.7 * getattr(self, 'soot_mask', 0.0))   # soot is matt

        out = np.empty((H, W, 4), dtype=np.float32)
        out[..., :3] = np.clip(col, 0, 1)
        out[..., 3] = np.clip(gloss, 0, 1)
        return out

    # ---------------------------------------------------------------------------------------
    def soot(self, col, lv, seed):
        """Exhaust staining streaming back along the sides, gun-port smoke."""
        c, P, N = self.c, self.P, self.N
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        if lv.get('clean'):
            return col
        streak = fbm(P, 6.0, seed + 41, octaves=2, stretch=(1.0, 0.08, 1.0))
        dirt = np.zeros_like(y)
        wash = np.zeros_like(y)     # 0 = black soot at the stubs, 1 = pale grey-brown lead wash further back
        for ex in c.get('exhaust', []):
            y0, z0, length, width, droop = ex
            t = np.clip((y0 - y) / length, 0.0, 1.0)
            zc = z0 - droop * t
            w = width * (0.7 + 1.8 * t)
            side = sstep(0.15, 0.45, np.abs(N[..., 0]))
            m = np.exp(-((z - zc) / w) ** 2) * (1.0 - t) ** 0.6 * (y < y0) * side
            m = np.clip(m * (0.80 + 0.70 * streak), 0.0, 1.0)
            wash = np.where(m > dirt, sstep(0.05, 0.55, t), wash)
            dirt = np.maximum(dirt, m)
        for gy, gdeg, gr, _region in c.get('gunports', []):
            a = math.radians(gdeg)
            dy = gy - y
            ds = (self.phi - a) * np.maximum(0.2, self.r)
            m = np.exp(-(ds / (gr * (1.5 + 3.0 * np.clip(dy, 0, 1)))) ** 2) * sstep(-0.02, 0.02, dy) * np.exp(-np.clip(dy, 0, 9) / 0.6)
            dirt = np.maximum(dirt, 0.8 * m)
        dirt = np.where(self.body, dirt * lv.get('soot', 1.0), 0.0)
        self.soot_mask = dirt
        dark = np.array([0.06, 0.055, 0.05], dtype=np.float32)
        pale = np.array([0.36, 0.34, 0.31], dtype=np.float32)
        soot = dark * (1.0 - wash[..., None]) + pale * wash[..., None]
        return col * (1.0 - 0.85 * dirt[..., None]) + soot * (0.85 * dirt[..., None])

    def decals(self, col, lv):
        """Painted markings (numbers, lettering, bands) projected sideways onto the fuselage."""
        P, N = self.P, self.N
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        for d in lv.get('decals', []) + self.c.get('stencils', []):
            mask = text_mask(d['text'], d.get('bold', 1.0))
            mh, mw = mask.shape
            h = d['h']
            wdt = h * mw / mh
            for sgn in ((-1, 1) if d.get('side', 'both') == 'both' else ((-1,) if d['side'] == 'port' else (1,))):
                sel = self.body & (np.sign(x) == sgn) & (np.abs(N[..., 0]) > 0.25)
                u = (y - d['y']) * (1.0 if sgn > 0 else -1.0) / wdt + 0.5
                v = (z - d['z']) / h + 0.5
                ok = sel & (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
                if not ok.any():
                    continue
                iu = np.clip((u * mw).astype(np.int64), 0, mw - 1)
                iv = np.clip(((1.0 - v) * mh).astype(np.int64), 0, mh - 1)
                val = np.where(ok, mask[iv, iu], 0.0)
                if d.get('outline'):
                    om = dilate(mask, max(1, int(mh * d.get('outline_w', 0.06))))
                    oval = np.where(ok, om[iv, iu], 0.0)
                    col = col * (1 - oval[..., None]) + hexcol(d['outline']) * oval[..., None]
                col = col * (1 - val[..., None]) + hexcol(d['color']) * val[..., None]
        return col

    def interior(self, col, seed):
        """Cockpit tub, seat, instrument panel (dials) and accents."""
        c, P, N = self.c, self.P, self.N
        cls = self.cls
        pit = c.get('pit') or {}
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        icol = hexcol(pit.get('col', '#4E5A4C'))
        grime = fbm(P, 7.0, seed + 51, octaves=2)
        col = np.where((cls == CL_INTERIOR)[..., None], icol * (0.85 + 0.25 * grime)[..., None], col)
        col = np.where((cls == CL_SEAT)[..., None], hexcol(pit.get('seat_col', '#2B2B2A')) * (0.85 + 0.3 * grime)[..., None], col)
        acc = hexcol(pit.get('accent', '#5A3A22'))
        if pit.get('seat') == 'ejection':
            stripe = ((np.floor((x + y + z) / 0.018).astype(np.int64) % 2) == 0)[..., None]
            acc_col = np.where(stripe, np.array([0.85, 0.65, 0.05], np.float32), np.array([0.05, 0.05, 0.05], np.float32))
            col = np.where((cls == CL_ACCENT)[..., None], acc_col, col)
        else:
            col = np.where((cls == CL_ACCENT)[..., None], acc * (0.8 + 0.4 * grime)[..., None], col)
        pm = cls == CL_PANEL
        self.dial = np.zeros_like(y)
        if pm.any():
            pcol = hexcol(pit.get('panel_col', '#1C1D1E'))
            face, ring, needle = self.dials(pm)
            pc = np.empty_like(col)
            pc[:] = pcol
            pc = pc * (1 - face[..., None]) + np.array([0.025, 0.025, 0.028], np.float32) * face[..., None]
            pc = pc * (1 - ring[..., None]) + np.array([0.62, 0.62, 0.60], np.float32) * ring[..., None]
            pc = pc * (1 - needle[..., None]) + np.array([0.92, 0.92, 0.88], np.float32) * needle[..., None]
            col = np.where(pm[..., None], pc, col)
            self.dial = np.where(pm, np.clip(face * 0.35 + needle + ring * 0.4, 0, 1), 0.0)
        return col

    def dials(self, pm_all):
        """Instrument dials on each panel face: grid in (x, z) from the panel top down."""
        pit = self.c.get('pit') or {}
        y = self.P[..., 1]
        panels = pit.get('panels') or [(pit.get('panel_y'), None)]
        face = np.zeros_like(y)
        ring = np.zeros_like(y)
        needle = np.zeros_like(y)
        for py, _ in panels:
            pm = pm_all & (np.abs(y - py) < 0.03) if py is not None else pm_all
            if pm.any():
                f, r, n = self.dials_one(pm)
                face, ring, needle = np.maximum(face, f), np.maximum(ring, r), np.maximum(needle, n)
        return face, ring, needle

    def dials_one(self, pm):
        P = self.P
        x, z = P[..., 0], P[..., 2]
        zt = float(z[pm].max())
        zb = float(z[pm].min())
        hw = float(np.abs(x[pm]).max())
        pit = self.c.get('pit') or {}
        sp = pit.get('dial_sp', 0.072)
        rd = sp * 0.38
        z0 = zt - sp * 0.75
        ix = np.round(x / sp)
        iz = np.round((z0 - z) / sp)
        cx = ix * sp
        cz = z0 - iz * sp
        d = np.sqrt((x - cx) ** 2 + (z - cz) ** 2)
        rows = max(1, int((zt - zb - 0.06) / sp * 0.55))
        inside = pm & (iz >= 0) & (iz < rows) & (np.abs(cx) < min(hw - 0.05, pit.get('dial_w', 0.34)))
        face = (inside & (d < rd)).astype(np.float32)
        ring = (inside & (d >= rd * 0.80) & (d < rd)).astype(np.float32)
        ang = _hash(ix.astype(np.int64) + 50, iz.astype(np.int64) + 50, np.zeros_like(ix, dtype=np.int64), 7) * 2 * math.pi
        ux, uz = np.sin(ang), np.cos(ang)
        rx, rz = x - cx, z - cz
        along = rx * ux + rz * uz
        perp = np.abs(rx * uz - rz * ux)
        needle = (inside & (along > 0) & (along < rd * 0.75) & (perp < rd * 0.07)).astype(np.float32)
        return face, ring, needle

    def recolour_maps(self, first):
        """TexturesUnlimited recolouring set, from the first livery's finished RGBA (`first`):
        paint base (greyscale where recolourable, normalised so clean paint = 0.5 = _DiffuseNorm; real colours
        elsewhere), mask (R upper surfaces, G lower surfaces, B detail: frames, anti-glare, radome, intake lip)
        and metal map at half resolution (R metallic, A smoothness; 0.5 where recolourable = TU norms)."""
        c, P, N = self.c, self.P, self.N
        x, y, z = P[..., 0], P[..., 1], P[..., 2]
        cls = self.cls
        lv = c['liveries'][0]
        grime = fbm(P, 2.2, 1234, octaves=3, stretch=(1.0, 0.18, 1.0))
        ao = self.AO
        shade = (0.95 + 0.08 * grime) * (1.0 - (0.26 if c['panel'].get('rivets') else 0.18) * self.line) \
            * (1.0 + 0.10 * self.rivet) * (0.28 + 0.72 * ao ** 0.8)
        body = self.body
        detail = (cls == CL_FRAME) | self.radome
        if c.get('canopy') or c.get('glazing') or any(v.get('glazing') for v in c['variants']):
            yw = self.windscreen_y()
            ag_len = 1.1 if c['rear_dia'] < 2.5 else 1.6
            t = np.clip((y - yw + 0.05) / ag_len, 0, 1)
            hw = (0.22 if c['rear_dia'] < 2.5 else 0.55) * (1.0 - 0.35 * t)
            detail |= (y > yw - 0.05) & (y < yw + ag_len) & (np.abs(x) < hw) & (N[..., 2] > 0.35) & (cls == CL_BODY)
        if c.get('intake'):
            detail |= (y > c['intake']['y_lip'] - 0.22)
        detail &= body
        split = lv['split'] if (lv['under'] or lv['belly']) else -0.25
        wob = (fbm(P, 1.4, 77, octaves=2) - 0.5) * 0.22
        up = sstep(split - 0.03, split + 0.03, N[..., 2] + wob)
        rest = body & ~detail
        mask = np.zeros(P.shape[:2] + (4,), dtype=np.float32)
        mask[..., 0] = np.where(rest, up, 0.0)
        mask[..., 1] = np.where(rest, 1.0 - up, 0.0)
        mask[..., 2] = detail.astype(np.float32)
        mask[..., 3] = 1.0
        med = float(np.median(shade[body])) if body.any() else 1.0
        grey = np.clip(0.5 * shade / max(0.05, med), 0.0, 1.0)
        base = np.empty(P.shape[:2] + (4,), dtype=np.float32)
        base[..., :3] = np.where(body[..., None], grey[..., None], first[..., :3])
        base[..., 3] = 1.0
        metal = np.zeros(P.shape[:2] + (4,), dtype=np.float32)
        metallic = np.where(cls == CL_METAL, 0.7, np.where(cls == CL_INTAKE, 0.5, 0.0))
        metal[..., 0] = np.where(body, 0.5, metallic)
        metal[..., 1] = metal[..., 0]
        metal[..., 2] = metal[..., 0]
        metal[..., 3] = np.where(body, 0.5 * (1.0 - 0.6 * self.line), first[..., 3])
        H, W = metal.shape[:2]
        half = lambda a: a.reshape(H // 2, 2, W // 2, 2, 4).mean(axis=(1, 3))  # noqa: E731
        return base, half(mask), half(metal)

    def glass_map(self):
        """Canopy glass texture (half resolution): RGB tint, A opacity (KSP/Alpha/Translucent Specular)."""
        c, N, P = self.c, self.N, self.P
        cls = self.cls
        tint = hexcol(c['glass'])
        up = np.clip(N[..., 2], 0.0, 1.0)
        streak = fbm(P, 3.0, 77, octaves=2, stretch=(1.0, 0.4, 1.0))
        sky = np.array([0.55, 0.62, 0.70], dtype=np.float32)
        refl = (sstep(0.25, 1.0, up) * (0.75 + 0.25 * streak))[..., None]
        rgb = tint * (1 - 0.55 * refl) + sky * (0.55 * refl)
        a0, a1 = c.get('glass_alpha', (0.22, 0.42))
        alpha = a0 + (a1 - a0) * refl[..., 0] + 0.05 * (streak - 0.5)
        dome = cls == CL_DOME
        rgb = np.where(dome[..., None], tint * 0.35 + sky * 0.25 * refl, rgb)
        alpha = np.where(dome, 0.82 + 0.1 * refl[..., 0], alpha)
        gl = (cls == CL_GLASS) | dome
        out = np.zeros(P.shape[:2] + (4,), dtype=np.float32)
        out[..., :3] = np.where(gl[..., None], rgb, 0.0)
        out[..., 3] = np.where(gl, np.clip(alpha, 0.05, 0.95), 0.0)
        H, W = out.shape[:2]
        return out.reshape(H // 2, 2, W // 2, 2, 4).mean(axis=(1, 3))

    def emissive(self):
        c, N, P = self.c, self.N, self.P
        glow = np.array(c['glow'], dtype=np.float32)
        e = np.zeros(P.shape[:2] + (3,), dtype=np.float32)
        dial = getattr(self, 'dial', None)
        if dial is not None:
            e = e + glow * dial[..., None]
        # faint wash of instrument light on the cockpit tub and seat
        wash = np.isin(self.cls, (CL_INTERIOR, CL_SEAT, CL_ACCENT)) * 0.10
        e = e + glow * wash[..., None]
        if getattr(self, 'slime', None) is not None:
            e = np.where(self.slime[..., None], np.array([0.45, 1.0, 0.55], np.float32), e)
        H, W = e.shape[:2]
        small = e.reshape(H // 2, 2, W // 2, 2, 3).mean(axis=(1, 3))
        out = np.ones((H // 2, W // 2, 4), dtype=np.float32)
        out[..., :3] = small
        return out


def save_png(arr, path):
    H, W = arr.shape[:2]
    img = bpy.data.images.new(os.path.basename(path), W, H, alpha=True, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


# =============================================================================== .mu export

def mesh_arrays(objs, origin_y):
    """Join objects -> KSP-space arrays (verts, normals, uvs, tangents, tris)."""
    V, Nn, U, T = [], [], [], []
    base = 0
    for o in objs:
        me = o.data
        me.calc_loop_triangles()
        nl = len(me.loops)
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3)
        lv = np.empty(nl, dtype=np.int64)
        me.loops.foreach_get('vertex_index', lv)
        cn = np.empty(nl * 3, dtype=np.float64)
        me.corner_normals.foreach_get('vector', cn)
        cn = cn.reshape(-1, 3)
        uv = np.empty(nl * 2, dtype=np.float64)
        me.uv_layers.active.data.foreach_get('uv', uv)
        uv = uv.reshape(-1, 2)
        tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get('loops', tl)
        key = np.concatenate([lv[:, None].astype(np.float64), np.round(cn, 4), np.round(uv, 5)], axis=1)
        uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inv = inv.ravel()
        V.append(co[lv[first]])
        Nn.append(cn[first])
        U.append(uv[first])
        T.append(inv[tl].reshape(-1, 3) + base)
        base += len(first)
    V = np.concatenate(V)
    Nn = np.concatenate(Nn)
    U = np.concatenate(U)
    T = np.concatenate(T)
    # design -> KSP: (x, y - origin, -z); reflection => reverse winding
    V = np.stack([V[:, 0], V[:, 1] - origin_y, -V[:, 2]], axis=1)
    Nn = np.stack([Nn[:, 0], Nn[:, 1], -Nn[:, 2]], axis=1)
    T = T[:, ::-1].copy()
    tang = tangents(V, Nn, U, T)
    return V, Nn, U, tang, T


def tangents(V, Nn, U, T):
    v0, v1, v2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    w0, w1, w2 = U[T[:, 0]], U[T[:, 1]], U[T[:, 2]]
    e1, e2 = v1 - v0, v2 - v0
    d1, d2 = w1 - w0, w2 - w0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-12, 1e-12, r)
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]
    tan1 = np.zeros_like(V)
    tan2 = np.zeros_like(V)
    for k in range(3):
        np.add.at(tan1, T[:, k], sdir)
        np.add.at(tan2, T[:, k], tdir)
    t = tan1 - Nn * np.sum(Nn * tan1, axis=1, keepdims=True)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.cross(Nn, np.array([0.0, 1.0, 0.0]))
    t = np.where(ln > 1e-9, t / np.maximum(ln, 1e-12), fallback)
    w = np.where(np.sum(np.cross(Nn, t) * tan2, axis=1) < 0.0, -1.0, 1.0)
    return np.concatenate([t, w[:, None]], axis=1)


def convex_collider(points, origin_y):
    bm = bmesh.new()
    for p in points:
        bm.verts.new(p)
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:])
    for g in res.get('geom_interior', []):
        if isinstance(g, bmesh.types.BMVert):
            bm.verts.remove(g)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table()
    cen = np.mean([v.co[:] for v in bm.verts], axis=0)
    V, Nn, T = [], [], []
    for f in bm.faces:
        pts = [np.array(v.co[:]) for v in f.verts]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        if np.dot(n, np.mean(pts, axis=0) - cen) < 0:
            pts = pts[::-1]
            n = -n
        n = n / max(1e-12, np.linalg.norm(n))
        b = len(V)
        V.extend(pts)
        Nn.extend([n] * 3)
        T.append([b, b + 1, b + 2])
    bm.free()
    V = np.array(V)
    Nn = np.array(Nn)
    T = np.array(T, dtype=np.int64)
    V = np.stack([V[:, 0], V[:, 1] - origin_y, -V[:, 2]], axis=1)
    Nn = np.stack([Nn[:, 0], Nn[:, 1], -Nn[:, 2]], axis=1)
    T = T[:, ::-1].copy()
    U = np.zeros((len(V), 2))
    tang = np.concatenate([np.cross(Nn, [0.0, 1.0, 0.0]) + 1e-6, np.ones((len(V), 1))], axis=1)
    return V, Nn, U, tang, T


def collider_points(c, v, ya, yb):
    prof = CS.variant_body(c, v)
    pts = []
    yb_body = yb
    if v.get('nose') == 'adapter':
        ys0, length, r, zc = CS.adapter_geometry(c, v)
        yb_body = min(yb, ys0)
    for y in lin(ya, max(ya + 0.01, yb_body), 4):
        y = min(y, prof.length)
        s = prof.section(y)
        for k in range(16):
            ph = -math.pi + 2 * math.pi * k / 16
            x, z = CS.section_point(s, ph)
            pts.append((x, y, z))
    if v.get('nose') == 'adapter':
        ys0, length, r, zc = CS.adapter_geometry(c, v)
        if yb > ys0:
            for k in range(16):
                ph = -math.pi + 2 * math.pi * k / 16
                pts.append((r * math.sin(ph), ys0 + length, zc + r * math.cos(ph)))
    ck = v.get('canopy', c.get('canopy'))
    if ck:
        cp = CS.CanopyProfile(ck, prof)
        for y in lin(max(ya, cp.y0), min(yb, cp.y1), 4):
            if y < cp.y0 or y > cp.y1:
                continue
            cs = cp.section(y)
            for k in range(7):
                ph = -math.pi / 2 + math.pi * k / 6
                x, z = CS.canopy_point(cs, ph)
                pts.append((x, y, z))
    # dedupe near-identical points (pole tips)
    out = []
    seen = set()
    for p in pts:
        k = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def variant_total_length(c, v):
    if v.get('nose') == 'adapter':
        ys0, length, r, zc = CS.adapter_geometry(c, v)
        return ys0 + length
    return CS.variant_length(c, v)


def write_mu(c, objs, path):
    oy = c['origin_y']
    vkeys = [v['key'] for v in c['variants']]
    tex_names = [f"{c['id']}_{c['liveries'][0]['key']}", f"{c['id']}_emissive", f"{c['id']}_NRM",
                 f"{c['id']}_glass"]

    def group(variant, glass):
        return [o for o in objs if o['variant'] == variant and ((o['cls'] in GLASS_CLASSES) == glass)
                and o['cls'] not in (CL_INTAKE, CL_DARK) + INTERIOR_CLASSES]

    def interior_group(variant):
        return [o for o in objs if o['variant'] == variant and o['cls'] in INTERIOR_CLASSES]

    def duct_group(variant):
        # intake duct / splitter / duct back: inward-facing by design, kept out of 'fuselage'
        return [o for o in objs if o['variant'] == variant and o['cls'] in (CL_INTAKE, CL_DARK)]

    w = MuWriter()
    w.write_uint(0x00012aff)
    w.write_int(5)
    w.write_string('cockpit')

    def mesh_node(name, gobjs, mat=0):
        w.write_int(0)
        w.write_transform(name)
        w.write_tag_and_layer('Untagged', 0)
        V, Nn, U, Tg, T = mesh_arrays(gobjs, oy)
        w.write_mesh_filter(V.tolist(), U.tolist(), Nn.tolist(), Tg.tolist(), T.ravel().tolist())
        w.write_mesh_renderer([mat])

    # root
    w.write_transform('cockpit')
    w.write_tag_and_layer('Untagged', 0)

    common_body = group('', False)
    common_glass = group('', True)
    assert not duct_group(''), 'intake parts must belong to a version'
    s0 = CS.BodyProfile(c['body'], c['length'], c.get('nose')).section(oy)
    if common_body:
        mesh_node('fuselage', common_body)
        # EVA airlock + ladder triggers on the port side next to the pilot
        for name, tag, r, h, dx in (('airlock', 'Airlock', 0.38, 0.80, 0.10), ('ladder', 'Ladder', 0.26, 0.95, 0.14)):
            w.write_int(0)
            w.write_transform(name, (-(s0['w'] + dx), 0.0, -(s0['zc'] + 0.15)))
            w.write_tag_and_layer(tag, 21)
            w.write_capsule_collider2(radius=r, height=h, direction=1, center=(0.0, 0.0, 0.0), is_trigger=True)
            w.write_int(1)
        w.write_int(1)
    if common_glass:
        mesh_node('windows', common_glass, mat=2)
        w.write_int(1)
    if interior_group(''):
        mesh_node('canopyInterior', interior_group(''), mat=3)
        w.write_int(1)
    if c.get('intake'):
        # ModuleResourceIntake reads the transform's +Z: rotate it to point forward (+Y)
        it = c['intake']
        zc_lip = CS.BodyProfile(c['body'], c['length'], c.get('nose')).section(it['y_lip'])['zc']
        w.write_int(0)
        w.write_transform('intakeTransform', (0.0, it['y_lip'] - oy, -zc_lip), (-0.70710678, 0.0, 0.0, 0.70710678))
        w.write_tag_and_layer('Untagged', 0)
        w.write_int(1)

    # flag decal on the port side of the rear fuselage
    fy = 0.42 if c['rear_dia'] < 2.5 else 1.1
    fw, fh = (0.46, 0.29) if c['rear_dia'] < 2.5 else (1.10, 0.69)
    sf = CS.BodyProfile(c['body'], c['length'], c.get('nose')).section(fy)
    fx = -(sf['w'] + 0.006)
    fz = sf['zc'] + 0.12 * sf['ht']
    quad = [(fx, fy - fw / 2, fz - fh / 2), (fx, fy + fw / 2, fz - fh / 2), (fx, fy + fw / 2, fz + fh / 2), (fx, fy - fw / 2, fz + fh / 2)]
    qv = [(p[0], p[1] - oy, -p[2]) for p in quad]
    # face -x: verifier convention cross(v1-v0, v2-v0) . n > 0 with n = (-1, 0, 0)
    tri = [0, 2, 1, 0, 3, 2]
    a, b, cc = np.array(qv[0]), np.array(qv[2]), np.array(qv[1])
    if np.dot(np.cross(b - a, cc - a), [-1, 0, 0]) < 0:
        tri = [0, 1, 2, 0, 2, 3]
    w.write_int(0)
    w.write_transform('flagDecal')
    w.write_tag_and_layer('Untagged', 0)
    w.write_mesh_filter(qv, [(1, 0), (0, 0), (0, 1), (1, 1)], [(-1.0, 0.0, 0.0)] * 4,
                        [(0.0, -1.0, 0.0, 1.0)] * 4, tri)
    w.write_mesh_renderer([1])
    w.write_int(1)

    # variant groups (toggled by B9PartSwitch): own meshes + convex colliders
    for v in c['variants']:
        vk = v['key']
        w.write_int(0)
        w.write_transform('variant_' + vk)
        w.write_tag_and_layer('Untagged', 0)
        vb = group(vk, False)
        vg = group(vk, True)
        if vb:
            mesh_node('fuselage', vb)
            w.write_int(1)
        if vg:
            mesh_node('windows', vg, mat=2)
            w.write_int(1)
        vi = interior_group(vk)
        if vi:
            mesh_node('canopyInterior', vi, mat=3)
            w.write_int(1)
        vd = duct_group(vk)
        if vd:
            mesh_node('intakeDuct', vd)
            w.write_int(1)
        Lv = variant_total_length(c, v)
        nseg = max(1, min(4, int(round(Lv / 2.2))))
        for k in range(nseg):
            ya = Lv * k / nseg - (0.05 if k else 0.0)
            yb = Lv * (k + 1) / nseg
            pts = collider_points(c, v, max(0.0, ya), yb)
            V, Nn, U, Tg, T = convex_collider(pts, oy)
            w.write_int(0)
            w.write_transform('collider')
            w.write_tag_and_layer('Untagged', 0)
            w.write_mesh_collider2(V.tolist(), U.tolist(), Nn.tolist(), Tg.tolist(), T.ravel().tolist(),
                                   is_trigger=False, convex=True)
            w.write_int(1)
        w.write_int(1)

    # materials: 0 = fuselage skin, 1 = flag decal, 2 = canopy glass (translucent, own texture so the
    # B9 paint switch, which swaps textures named after the first livery, leaves it alone), 3 = cockpit
    # interior (same textures as the skin, but its own material so colour mods that tint materials
    # (SimpleRepaint's B9 _Color, Reforged Materials) paint the skin without tinting the cockpit tub)
    w.write_int(10)
    w.write_int(4)

    def opaque_material(name):
        w.write_string(name)
        w.write_string('KSP/Emissive/Bumped Specular')
        w.write_int(12)
        for pname, rgba in (('_Color', (1, 1, 1, 1)), ('_SpecColor', (0.72, 0.73, 0.75, 1.0)),
                            ('_EmissiveColor', (0, 0, 0, 1)), ('_RimColor', (0, 0, 0, 0)),
                            ('_TemperatureColor', (0, 0, 0, 0)), ('_BurnColor', (1, 1, 1, 1))):
            w.write_string(pname)
            w.write_int(0)
            w.write_floats(rgba)
        for pname, val in (('_Shininess', 0.55), ('_Opacity', 1.0), ('_RimFalloff', 0.1)):
            w.write_string(pname)
            w.write_int(3)
            w.write_float(val)
        for pname, tidx in (('_MainTex', 0), ('_Emissive', 1), ('_BumpMap', 2)):
            w.write_string(pname)
            w.write_int(4)
            w.write_int(tidx)
            w.write_floats((1.0, 1.0))
            w.write_floats((0.0, 0.0))
    opaque_material(f"{c['id']}_mat")
    w.write_string(f"{c['id']}_flag_mat")
    w.write_string('KSP/Alpha/Translucent')
    w.write_int(5)
    for pname, rgba in (('_RimColor', (0, 0, 0, 0)), ('_TemperatureColor', (0, 0, 0, 0)), ('_BurnColor', (1, 1, 1, 1))):
        w.write_string(pname)
        w.write_int(0)
        w.write_floats(rgba)
    w.write_string('_RimFalloff')
    w.write_int(3)
    w.write_float(0.1)
    w.write_string('_MainTex')
    w.write_int(4)
    w.write_int(0)
    w.write_floats((1.0, 1.0))
    w.write_floats((0.0, 0.0))
    w.write_string(f"{c['id']}_glass_mat")
    w.write_string('KSP/Alpha/Translucent Specular')
    w.write_int(9)
    for pname, rgba in (('_Color', (1, 1, 1, 1)), ('_SpecColor', (0.95, 0.96, 0.98, 1.0)),
                        ('_RimColor', (0, 0, 0, 0)), ('_TemperatureColor', (0, 0, 0, 0)),
                        ('_BurnColor', (1, 1, 1, 1))):
        w.write_string(pname)
        w.write_int(0)
        w.write_floats(rgba)
    for pname, val in (('_Shininess', 0.92), ('_Opacity', 1.0), ('_RimFalloff', 0.1)):
        w.write_string(pname)
        w.write_int(3)
        w.write_float(val)
    w.write_string('_MainTex')
    w.write_int(4)
    w.write_int(3)
    w.write_floats((1.0, 1.0))
    w.write_floats((0.0, 0.0))
    opaque_material(f"{c['id']}_interior_mat")
    # textures
    w.write_int(12)
    w.write_int(4)
    w.write_string(tex_names[0])
    w.write_int(0)
    w.write_string(tex_names[1])
    w.write_int(0)
    w.write_string(tex_names[2])
    w.write_int(1)
    w.write_string(tex_names[3])
    w.write_int(0)
    w.write_int(1)  # close root
    with open(path, 'wb') as f:
        f.write(w.buf)


# =============================================================================== rendering

def glass_render_material(glass_path):
    m = bpy.data.materials.new('PREVIEW_GLASS')
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    ti = nt.nodes.new('ShaderNodeTexImage')
    ti.image = bpy.data.images.load(glass_path, check_existing=True)
    ti.image.alpha_mode = 'CHANNEL_PACKED'
    nt.links.new(ti.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(ti.outputs['Alpha'], b.inputs['Alpha'])
    b.inputs['Roughness'].default_value = 0.04
    nt.links.new(b.outputs['BSDF'], out.inputs['Surface'])
    for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
        try:
            setattr(m, attr, val)
        except Exception:
            pass
    return m


def setup_render_material(objs, livery_path, nrm_path, glass_path=None):
    mat = bpy.data.materials.new('PREVIEW')
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    ti = nt.nodes.new('ShaderNodeTexImage')
    ti.image = bpy.data.images.load(livery_path, check_existing=True)
    ti.image.alpha_mode = 'CHANNEL_PACKED'
    tn = nt.nodes.new('ShaderNodeTexImage')
    tn.image = bpy.data.images.load(nrm_path, check_existing=True)
    tn.image.colorspace_settings.name = 'Non-Color'
    nm = nt.nodes.new('ShaderNodeNormalMap')
    rough = nt.nodes.new('ShaderNodeMath')
    rough.operation = 'MULTIPLY_ADD'
    rough.inputs[1].default_value = -0.62
    rough.inputs[2].default_value = 0.78
    nt.links.new(ti.outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(ti.outputs['Alpha'], rough.inputs[0])
    nt.links.new(rough.outputs[0], bsdf.inputs['Roughness'])
    nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
    nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    gmat = glass_render_material(glass_path) if glass_path else mat
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(gmat if o['cls'] in GLASS_CLASSES else mat)
    return mat, ti


def setup_stage():
    sc = bpy.context.scene
    world = sc.world
    if world.node_tree is None:
        world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg is None:
        bg = world.node_tree.nodes.new('ShaderNodeBackground')
        outn = world.node_tree.nodes.new('ShaderNodeOutputWorld')
        world.node_tree.links.new(bg.outputs[0], outn.inputs[0])
    bg.inputs[0].default_value = (0.55, 0.62, 0.72, 1.0)
    bg.inputs[1].default_value = 0.85
    sun_data = bpy.data.lights.new('sun', 'SUN')
    sun_data.energy = 3.2
    sun_data.angle = math.radians(6)
    sun = bpy.data.objects.new('sun', sun_data)
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(40), math.radians(-25), math.radians(-35))
    cam_data = bpy.data.cameras.new('cam')
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new('cam', cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    sc.render.film_transparent = True
    sc.cycles.samples = 24
    try:
        sc.cycles.use_denoising = True
    except Exception:
        pass
    return cam


def frame_camera(cam, objs, direction=(-0.95, 1.0, 0.62), margin=1.08, size=(640, 400)):
    import mathutils
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size
    pts = []
    for o in objs:
        if o.hide_render:
            continue
        for corner in o.bound_box:
            pts.append(mathutils.Vector(corner))
    cen = sum(pts, mathutils.Vector()) / len(pts)
    d = mathutils.Vector(direction).normalized()
    cam.location = cen + d * 40.0
    cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()
    right = (-d).cross(mathutils.Vector((0, 0, 1))).normalized()
    up = right.cross(-d).normalized()
    xs = [(p - cen).dot(right) for p in pts]
    ys = [(p - cen).dot(up) for p in pts]
    aspect = sc.render.resolution_x / sc.render.resolution_y
    wdt = (max(xs) - min(xs))
    hgt = (max(ys) - min(ys))
    cam.data.ortho_scale = max(wdt, hgt * aspect) * margin
    cam.data.shift_x = ((max(xs) + min(xs)) / 2) / cam.data.ortho_scale
    cam.data.shift_y = ((max(ys) + min(ys)) / 2) / cam.data.ortho_scale


def render_to(path, w, h):
    sc = bpy.context.scene
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def show_variant(objs, vk):
    for o in objs:
        o.hide_render = o['variant'] not in ('', vk)


# =============================================================================== quick shape previews

QUICK_COLS = {CL_BODY: (0.60, 0.62, 0.64), CL_FRAME: (0.22, 0.24, 0.25), CL_METAL: (0.55, 0.56, 0.57),
              CL_INTAKE: (0.5, 0.5, 0.5), CL_CAP: (0.25, 0.26, 0.27), CL_DARK: (0.03, 0.03, 0.03),
              CL_INTERIOR: (0.30, 0.34, 0.30), CL_PANEL: (0.03, 0.03, 0.035), CL_SEAT: (0.12, 0.10, 0.08),
              CL_ACCENT: (0.85, 0.65, 0.05)}


def node_mat(name, rgb, alpha=1.0, rough=0.45):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Alpha'].default_value = alpha
    nt.links.new(b.outputs['BSDF'], out.inputs['Surface'])
    if alpha < 1.0:
        for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
            try:
                setattr(m, attr, val)
            except Exception:
                pass
    return m


def aim_camera(cam, objs, d, size, margin=1.06, ref_up=(0.0, 0.0, 1.0)):
    import mathutils
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = size
    pts = [o.matrix_world @ mathutils.Vector(cn) for o in objs if not o.hide_render for cn in o.bound_box]
    cen = sum(pts, mathutils.Vector()) / len(pts)
    d = mathutils.Vector(d).normalized()
    u = mathutils.Vector(ref_up)
    if abs(d.dot(u)) > 0.98:
        u = mathutils.Vector((-1.0, 0.0, 0.0))
    right = (-d).cross(u).normalized()
    up = right.cross(-d).normalized()
    rot = mathutils.Matrix((right, up, d)).transposed().to_4x4()
    cam.matrix_world = mathutils.Matrix.Translation(cen + d * 60.0) @ rot
    xs = [(p - cen).dot(right) for p in pts]
    ys = [(p - cen).dot(up) for p in pts]
    aspect = size[0] / size[1]
    cam.data.ortho_scale = max(max(xs) - min(xs), (max(ys) - min(ys)) * aspect) * margin
    cam.data.shift_x = ((max(xs) + min(xs)) / 2) / cam.data.ortho_scale
    cam.data.shift_y = ((max(ys) + min(ys)) / 2) / cam.data.ortho_scale
    cam.data.clip_end = 200.0


def set_fast_engine():
    sc = bpy.context.scene
    engines = ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT') if os.environ.get('ROPP_QUICK_ENGINE') != 'CYCLES' else ()
    for eng in engines:
        try:
            sc.render.engine = eng
            return eng
        except TypeError:
            continue
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 12
    return 'CYCLES'


def quick_preview(c, objs):
    """Shape check without baking: 4 views per version (side, top, front 3/4, cockpit close-up)."""
    mats = {}
    for o in objs:
        cl = o['cls']
        if cl not in mats:
            if cl in GLASS_CLASSES:
                mats[cl] = node_mat(f'q{cl}', (0.02, 0.025, 0.03), alpha=0.35 if cl == CL_GLASS else 0.85, rough=0.04)
            else:
                mats[cl] = node_mat(f'q{cl}', QUICK_COLS.get(cl, (0.6, 0.6, 0.6)))
        o.data.materials.clear()
        o.data.materials.append(mats[cl])
    cam = setup_stage()
    eng = set_fast_engine()
    bpy.context.scene.view_settings.exposure = -1.3
    log(f'   quick preview with {eng}')
    qdir = os.path.join(ROOT, 'build', 'quick')
    os.makedirs(qdir, exist_ok=True)
    cell = (800, 450)
    for v in c['variants']:
        show_variant(objs, v['key'])
        shots = []
        vis = [o for o in objs if not o.hide_render]
        focus = [o for o in vis if o['cls'] in GLASS_CLASSES + INTERIOR_CLASSES or o['cls'] == CL_FRAME]
        for k, (d, sel, mg) in enumerate((((-1.0, 0.0, 0.0), vis, 1.04), ((0.0, 0.0, 1.0), vis, 1.04),
                                          ((-0.9, 1.0, 0.55), vis, 1.04), ((-0.55, -0.35, 0.9), focus or vis, 1.25))):
            aim_camera(cam, sel, d, cell, margin=mg)
            pth = os.path.join(qdir, f"_{c['id']}_{k}.png")
            render_to(pth, *cell)
            shots.append(pth)
        contact_sheet([shots[:2], shots[2:]], os.path.join(qdir, f"{c['id']}__{v['key']}.png"), cell=cell)
        for p in shots:
            os.remove(p)


# =============================================================================== main

def clean_part_dir(pdir, c):
    keep = {f"{c['id']}.cfg"}
    for fn in os.listdir(pdir):
        if fn in keep:
            continue
        if fn.endswith(('.mu', '.png', '.dds')):
            os.remove(os.path.join(pdir, fn))


def build_cockpit(c, preview=True):
    t0 = time.time()
    log(f"=== {c['id']}: building geometry")
    clear_scene()
    b = Build(c)
    pieces = b.build()
    vindex = {None: 0}
    for k, v in enumerate(c['variants']):
        vindex[v['key']] = k + 1
    objs = [make_object(p, vindex[p.variant]) for p in pieces]
    ntris = sum(len(o.data.polygons) for o in objs)
    log(f"   {len(objs)} pieces, {ntris} faces ({time.time() - t0:.1f}s)")
    unwrap_and_pack(objs, pieces)
    log(f"   unwrapped ({time.time() - t0:.1f}s)")
    tex = c['tex']
    maps = bake_maps(objs, None, [v['key'] for v in c['variants']], tex, 0.6 if c['rear_dia'] < 2.5 else 1.4)
    log(f"   baked ({time.time() - t0:.1f}s)")
    pdir = os.path.join(PARTS_DIR, c['id'])
    os.makedirs(pdir, exist_ok=True)
    clean_part_dir(pdir, c)
    painter = Painter(c, maps, tex)
    save_png(painter.normal_map(), os.path.join(pdir, f"{c['id']}_NRM.png"))
    livery_paths = []
    first = None
    for lv in c['liveries']:
        arr = painter.livery(lv)
        if first is None:
            first = arr
        pth = os.path.join(pdir, f"{c['id']}_{lv['key']}.png")
        save_png(arr, pth)
        livery_paths.append(pth)
        log(f"   livery {lv['key']} ({time.time() - t0:.1f}s)")
    # TexturesUnlimited recolouring maps (used only when TU is installed, see generate_configs.py)
    for suffix, arr in zip(('paint', 'mask', 'metal'), painter.recolour_maps(first)):
        save_png(arr, os.path.join(pdir, f"{c['id']}_{suffix}.png"))
    save_png(painter.emissive(), os.path.join(pdir, f"{c['id']}_emissive.png"))
    glass_path = os.path.join(pdir, f"{c['id']}_glass.png")
    save_png(painter.glass_map(), glass_path)
    write_mu(c, objs, os.path.join(pdir, f"{c['id']}.mu"))
    log(f"   wrote {c['id']}.mu ({time.time() - t0:.1f}s)")

    # icon + previews
    cam = setup_stage()
    mat, ti = setup_render_material(objs, livery_paths[0], os.path.join(pdir, f"{c['id']}_NRM.png"), glass_path)
    show_variant(objs, c['variants'][0]['key'])
    frame_camera(cam, objs, size=(256, 256))
    os.makedirs(THUMBS_DIR, exist_ok=True)
    render_to(os.path.join(THUMBS_DIR, f"{c['part_name']}_icon.png"), 256, 256)
    shots = []
    if preview:
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        for v in c['variants']:
            show_variant(objs, v['key'])
            frame_camera(cam, objs, margin=1.04)
            pth = os.path.join(PREVIEW_DIR, f"{c['id']}__v_{v['key']}.png")
            render_to(pth, 640, 400)
            shots.append(pth)
        show_variant(objs, c['variants'][0]['key'])
        for k, lv in enumerate(c['liveries'][1:], start=1):
            ti.image = bpy.data.images.load(livery_paths[k], check_existing=True)
            ti.image.alpha_mode = 'CHANNEL_PACKED'
            frame_camera(cam, objs, direction=(0.95, 0.9, 0.5), margin=1.04)
            pth = os.path.join(PREVIEW_DIR, f"{c['id']}__l_{lv['key']}.png")
            render_to(pth, 640, 400)
            shots.append(pth)
    log(f"=== {c['id']} done in {time.time() - t0:.1f}s")
    return shots


def contact_sheet(rows, path, cell=(640, 400)):
    cw, ch = cell
    ncol = max(len(r) for r in rows)
    H, W = ch * len(rows), cw * ncol
    sheet = np.zeros((H, W, 4), dtype=np.float32)
    sheet[..., :3] = (0.16, 0.17, 0.19)
    sheet[..., 3] = 1.0
    for ri, row in enumerate(rows):
        for ci, pth in enumerate(row):
            img = bpy.data.images.load(pth)
            a = np.empty(cw * ch * 4, dtype=np.float32)
            img.pixels.foreach_get(a)
            a = a.reshape(ch, cw, 4)
            y0 = H - (ri + 1) * ch
            x0 = ci * cw
            al = a[..., 3:4]
            sheet[y0:y0 + ch, x0:x0 + cw, :3] = a[..., :3] * al + sheet[y0:y0 + ch, x0:x0 + cw, :3] * (1 - al)
            bpy.data.images.remove(img)
    out = bpy.data.images.new('sheet', W, H, alpha=True, float_buffer=False)
    out.pixels.foreach_set(sheet.ravel())
    out.filepath_raw = path
    out.file_format = 'PNG'
    out.save()


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    preview = '--no-preview' not in argv
    ids = [a for a in argv if not a.startswith('--')]
    todo = [c for c in CS.COCKPITS if not ids or c['id'] in ids]
    t0 = time.time()
    if '--quick' in argv:
        for c in todo:
            clear_scene()
            pieces = Build(c).build()
            vindex = {None: 0}
            for k, v in enumerate(c['variants']):
                vindex[v['key']] = k + 1
            objs = [make_object(p, vindex[p.variant]) for p in pieces]
            log(f"{c['id']}: {len(objs)} pieces, {sum(len(o.data.polygons) for o in objs)} faces")
            quick_preview(c, objs)
        log(f"QUICK DONE in {time.time() - t0:.0f}s")
        return
    for c in todo:
        build_cockpit(c, preview)
    if preview:
        # sheet of every cockpit's latest renders (versions first, then the other paint schemes)
        rows = []
        for c in CS.COCKPITS:
            row = [os.path.join(PREVIEW_DIR, f"{c['id']}__v_{v['key']}.png") for v in c['variants']]
            row += [os.path.join(PREVIEW_DIR, f"{c['id']}__l_{lv['key']}.png") for lv in c['liveries'][1:]]
            row = [p for p in row if os.path.exists(p)]
            if row:
                rows.append(row)
        contact_sheet(rows, os.path.join(ROOT, 'cockpits_preview_sheet.png'))
    log(f"ALL DONE: {len(todo)} cockpits in {time.time() - t0:.0f}s")


if __name__ == '__main__':
    main()
