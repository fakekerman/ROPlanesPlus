#!/usr/bin/env python3
"""
Generator for ROPlanesPlus Procedural Propeller Engine 3D base .mu models,
high-resolution textures (.png), and 3D software-rasterized preview icons.

Coordinate System (matching KSP Aircraft & ROPlanesPlus standard):
  +Y : Forward (Propeller / Spinner nose)
  -Y : Aft (Firewall mount node_stack_bottom)
  -Z : Dorsal / Up (Top of cowling)
  +Z : Ventral / Down (Chin scoop / Meredith radiator)
  +X : Starboard / Right
  -X : Port / Left
"""

import math
import os
import struct
import zlib
from array import array

from generate_models_and_textures import (
    MeshBuilder,
    MuWriter,
    add3,
    cross3,
    dot3,
    normalize3,
    smoothstep,
    sub3,
    write_png,
)


def clamp_byte(v):
    return max(0, min(255, int(round(v))))


def lerp(a, b, t):
    return a + (b - a) * t


# ==============================================================================
# 1. SHARED TEXTURE ATLAS (1024x1024 livery maps + normal map + emissive + blur disc)
# ==============================================================================
# UV layout (identical here and in Source/ROPlanesPlus/Geometry/PropellerMeshGenerator.cs):
#   V 0.00-0.45  cowling skin. U runs around the circumference with U=0/1 on TOP (dorsal, -Z)
#                and U=0.5 underneath; V runs aft (0.00) -> nose (0.45).
#   V 0.45-0.65  engine internals: U<0.50 finned cylinders (V = root -> head),
#                0.50-0.75 crankcase + chrome pushrods, >=0.75 radiator / intake grille.
#   V 0.65-0.80  exhaust stubs & tailpipes (V = base -> hot tip); the emissive glow band.
#   V 0.80-1.00  U<0.70 propeller blades (U = root -> tip, V = chord), U>=0.70 spinner
#                (V = base -> tip).
# All four propeller parts share these textures (Parts/PropShared); the plugin swaps the
# livery map at runtime.

# Order must match PropellerPresets.LiveryKeys (the 15th, "custom", is composited at runtime
# by CustomPaint.cs from the paint kit written below).
LIVERY_KEYS = ['aluminum', 'raf', 'luftwaffe', 'usn', 'soviet', 'olive', 'desert', 'ijn',
               'racer', 'civil', 'night', 'trainer', 'arctic', 'italian']

LIVERY_PALETTES = {
    'aluminum': {'weather': 0.55, 'gloss': 205},
    'raf': {'top_a': (56, 70, 45), 'top_b': (98, 102, 108), 'under': (146, 150, 152),
            'spinner': (188, 200, 166), 'weather': 1.0, 'gloss': 60},
    'luftwaffe': {'top_a': (72, 78, 83), 'top_b': (100, 98, 107), 'under': (150, 170, 182),
                  'yellow': (222, 178, 38), 'spinner': (40, 46, 38), 'weather': 1.0, 'gloss': 55},
    'usn': {'top_a': (32, 47, 76), 'top_b': (28, 42, 70), 'under': (28, 42, 70),
            'spinner': (30, 44, 72), 'weather': 0.8, 'gloss': 175},
    'soviet': {'top_a': (104, 118, 126), 'top_b': (62, 70, 77), 'under': (142, 172, 196),
               'spinner': (168, 34, 30), 'nose': (168, 34, 30), 'weather': 1.1, 'gloss': 70},
    'olive': {'top_a': (84, 82, 52), 'top_b': (112, 106, 80), 'under': (122, 124, 124),
              'spinner': (84, 82, 52), 'weather': 1.1, 'gloss': 40},
    'desert': {'top_a': (110, 86, 58), 'top_b': (178, 152, 104), 'under': (98, 140, 190),
               'spinner': (26, 26, 28), 'weather': 1.0, 'gloss': 45},
    'ijn': {'top_a': (30, 32, 34), 'under': (30, 32, 34), 'spinner': (160, 152, 120),
            'weather': 0.9, 'gloss': 120},
    'racer': {'top_a': (178, 28, 28), 'under': (178, 28, 28), 'spinner': (236, 236, 232),
              'weather': 0.3, 'gloss': 215},
    'civil': {'top_a': (234, 234, 230), 'under': (182, 188, 194), 'cheat': (30, 60, 140),
              'spinner': (196, 200, 206), 'weather': 0.35, 'gloss': 190},
    'night': {'top_a': (24, 24, 26), 'under': (24, 24, 26), 'spinner': (150, 30, 26),
              'weather': 0.9, 'gloss': 25},
    'trainer': {'top_a': (226, 178, 24), 'under': (226, 178, 24), 'spinner': (226, 178, 24),
                'weather': 0.6, 'gloss': 150},
    'arctic': {'top_a': (60, 74, 48), 'white': (230, 232, 228), 'under': (214, 216, 214),
               'spinner': (232, 232, 228), 'weather': 1.1, 'gloss': 35},
    'italian': {'top_a': (190, 160, 100), 'ring': (88, 96, 58), 'under': (150, 152, 154),
                'spinner': (236, 236, 232), 'weather': 1.0, 'gloss': 50},
}


def _hash01(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 1442695041) & 0xffffffff
    h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    return ((h ^ (h >> 16)) & 0xffff) / 65535.0


def periodic_fbm_grid(size, base_freq, octaves, seed, gain=0.5):
    """size x size fbm value noise that tiles seamlessly in both directions (0..1)."""
    grid = [0.0] * (size * size)
    amp = 1.0
    total = 0.0
    freq = base_freq
    for o in range(octaves):
        lat = [_hash01(i, j, seed + o * 101) for j in range(freq) for i in range(freq)]
        xs = []
        for x in range(size):
            fx = x * freq / float(size)
            ix = int(fx)
            tx = fx - ix
            xs.append((ix % freq, (ix + 1) % freq, tx * tx * (3.0 - 2.0 * tx)))
        for y in range(size):
            fy = y * freq / float(size)
            iy = int(fy)
            ty = fy - iy
            ty = ty * ty * (3.0 - 2.0 * ty)
            r0 = (iy % freq) * freq
            r1 = ((iy + 1) % freq) * freq
            row = y * size
            for x in range(size):
                ix0, ix1, tx = xs[x]
                a = lat[r0 + ix0]
                b = lat[r0 + ix1]
                c = lat[r1 + ix0]
                d = lat[r1 + ix1]
                top = a + (b - a) * tx
                bot = c + (d - c) * tx
                grid[row + x] += amp * (top + (bot - top) * ty)
        total += amp
        amp *= gain
        freq *= 2
    inv = 1.0 / total
    return [g * inv for g in grid]


def make_sampler(grid, size):
    def sample(u, v):
        fx = (u % 1.0) * size
        fy = (v % 1.0) * size
        ix = int(fx)
        iy = int(fy)
        tx = fx - ix
        ty = fy - iy
        ix0 = ix % size
        iy0 = iy % size
        ix1 = (ix + 1) % size
        iy1 = (iy + 1) % size
        a = grid[iy0 * size + ix0]
        b = grid[iy0 * size + ix1]
        c = grid[iy1 * size + ix0]
        d = grid[iy1 * size + ix1]
        t = a + (b - a) * tx
        return t + (c + (d - c) * tx - t) * ty
    return sample


def _mix(c0, c1, t):
    return (c0[0] + (c1[0] - c0[0]) * t, c0[1] + (c1[1] - c0[1]) * t, c0[2] + (c1[2] - c0[2]) * t)


def _gradient(stops, t):
    if t <= stops[0][0]:
        return stops[0][1]
    for k in range(1, len(stops)):
        if t <= stops[k][0]:
            t0, c0 = stops[k - 1]
            t1, c1 = stops[k]
            return _mix(c0, c1, (t - t0) / (t1 - t0))
    return stops[-1][1]


EXHAUST_HEAT_STOPS = [
    (0.00, (118, 116, 110)),
    (0.22, (152, 132, 84)),
    (0.40, (128, 76, 92)),
    (0.56, (72, 82, 122)),
    (0.74, (78, 68, 60)),
    (0.88, (40, 35, 32)),
    (1.00, (20, 18, 17)),
]


def generate_damaged_blade_texture(W=1024, H=1024):
    """Blades after a ground strike (ropp_blades_damaged.png, used only by the blade meshes, so
    only the blade strip V 0.80-1.00, U < 0.70 is painted): the same black paint, bare roots and
    yellow tips as the intact blades, flaked and scraped to bright bare metal towards the tips
    with chordwise abrasion streaks and dark gouges, battered edges and smears of soil and grass."""
    S = 256
    chip = make_sampler(periodic_fbm_grid(S, 10, 4, 71), S)
    grit = make_sampler(periodic_fbm_grid(S, 48, 3, 83), S)
    soil = make_sampler(periodic_fbm_grid(S, 6, 4, 97), S)
    kind = make_sampler(periodic_fbm_grid(S, 5, 3, 109), S)
    fine_spk = make_sampler(periodic_fbm_grid(S, 64, 2, 131), S)
    rgba = bytearray(4 * W * H)
    filler = bytes((96, 96, 98, 60)) * W
    for py in range(H):
        v = 1.0 - py / float(H - 1)
        row = 4 * W * py
        if v < 0.80:
            rgba[row:row + 4 * W] = filler
            continue
        vn = (v - 0.80) / 0.20
        edge = min(vn, 1.0 - vn)
        for px in range(W):
            u = px / float(W - 1)
            o = row + 4 * px
            if u >= 0.70:
                rgba[o:o + 4] = filler[:4]
                continue
            s = u / 0.70
            sheen = 10.0 * math.sin(vn * math.pi)
            rgb = (27 + sheen, 29 + sheen, 32 + sheen)
            gl = 70.0
            if s > 0.885:
                rgb = (232, 188, 30)
                gl = 120.0
            elif s < 0.14:
                c = 160 + 18 * grit(u, vn)
                rgb = (c, c + 4, c + 10)
                gl = 210.0
            dmg = max(0.0, min(1.0, (s - 0.55) / 0.45))
            dmg = dmg * dmg * (3.0 - 2.0 * dmg)
            # scuffs: small specks of paint knocked off (most of the paint stays on, like the real thing)
            if dmg > 0.0 and fine_spk(u * 6.0, vn * 4.0) > 0.93 - 0.15 * dmg:
                b = 150 + 40 * grit(u * 3.0, vn)
                rgb = (b, b + 1, b + 5)
                gl = 150.0
            elif chip(u * 2.0, vn * 0.6) > 0.80 - 0.10 * dmg:
                b = 148 + 40 * grit(u * 3.0, vn)
                rgb = (b, b + 1, b + 5)
                gl = 150.0
            # the very tip was ground off against the surface: bare, abraded metal along the chord
            st = grit(u * 9.0, vn * 0.45)
            if s > 0.90 and st > 0.62 - 1.2 * (s - 0.90):
                m = 182 + 60 * (st - 0.5)
                rgb = (m, m, m + 3)
                gl = 205.0
            elif st < 0.10 * dmg:
                rgb = (46, 42, 38)  # gouges
                gl = 35.0
            # nicked leading and trailing edges
            if edge < 0.045 and dmg > 0.2 and grit(u * 5.0, vn * 3.0) > 0.55:
                m = 170 + 50 * grit(u * 7.0, vn * 2.0)
                rgb = (m, m, m)
                gl = 180.0
            # a little soil and grass on the outer blade
            d = soil(u * 1.5, vn * 1.2)
            amt = max(0.0, min(0.6, (d - 0.66 + 0.15 * dmg) * 2.5)) * dmg
            if amt > 0.0:
                tint = (92, 72, 48) if kind(u * 3.0 + 0.5, vn * 2.0) > 0.48 else (64, 78, 38)
                rgb = _mix(rgb, tint, amt)
                gl = gl + (25.0 - gl) * amt
            rgba[o] = clamp_byte(rgb[0])
            rgba[o + 1] = clamp_byte(rgb[1])
            rgba[o + 2] = clamp_byte(rgb[2])
            rgba[o + 3] = clamp_byte(gl)
    return rgba


def generate_texture_set(W=1024, H=1024):
    """Returns ({livery: rgba}, nrm_rgba, emissive_rgba, ew, eh)."""
    print("   noise fields...")
    S = 256
    big = make_sampler(periodic_fbm_grid(S, 3, 5, 11), S)
    mid = make_sampler(periodic_fbm_grid(S, 12, 4, 23), S)
    fine = make_sampler(periodic_fbm_grid(S, 64, 2, 37), S)
    streak = make_sampler(periodic_fbm_grid(S, 24, 3, 51), S)

    N = W * H
    height = array('f', bytes(4 * N))
    base_rgb = bytearray(3 * N)
    base_gloss = bytearray(N)
    painted = bytearray(N)              # 1 = cowl skin, 2 = spinner
    p_top = array('f', bytes(4 * N))    # 0 top .. 1 bottom (cowl) / spinner spiral phase
    p_vn = array('f', bytes(4 * N))
    p_camo = array('f', bytes(4 * N))
    p_mottle = array('f', bytes(4 * N))
    p_chip = array('f', bytes(4 * N))
    p_soot = array('f', bytes(4 * N))
    p_oil = array('f', bytes(4 * N))
    p_tone = array('f', bytes(4 * N))

    seams_v = (0.22, 0.52, 0.78, 0.885)
    print("   base layers...")
    for py in range(H):
        v = 1.0 - py / float(H - 1)
        row = py * W
        for px in range(W):
            u = px / float(W - 1)
            i = row + px
            g_fine = fine(u, v)
            g_mid = mid(u, v)

            if v < 0.45:
                # ---------------- cowling skin ----------------
                vn = v / 0.45
                top = min(u, 1.0 - u) * 2.0
                du = abs(u * 8.0 - round(u * 8.0)) / 8.0 * W
                dv = min(abs(vn - s) for s in seams_v) * 0.45 * H
                d_seam = du if du < dv else dv
                h = (g_fine - 0.5) * 0.12
                if d_seam < 1.8:
                    h -= 0.9 * (1.0 - d_seam / 1.8)
                # Rivet rows 4 px either side of every seam
                if 3.0 < dv < 5.2:
                    rx = (px % 10) - 4.5
                    ry = dv - 4.1
                    r2 = rx * rx + ry * ry
                    if r2 < 2.4:
                        h += 0.45 * (1.0 - r2 / 2.4)
                if 3.0 < du < 5.2:
                    rx = (py % 10) - 4.5
                    ry = du - 4.1
                    r2 = rx * rx + ry * ry
                    if r2 < 2.4:
                        h += 0.45 * (1.0 - r2 / 2.4)
                # Dzus fasteners along the removable forward panels
                if abs(vn - 0.78) * 0.45 * H < 10.0 and 6.0 < dv < 10.0 and (px % 42) < 8:
                    fx = (px % 42) - 3.5
                    fy = dv - 8.0
                    rr = math.sqrt(fx * fx + fy * fy)
                    if 1.6 < rr < 3.2:
                        h -= 0.5
                # Cooling louvers on the flanks
                if 0.30 < vn < 0.46 and 0.34 < top < 0.62 and 6 < (px % 48) < 42:
                    ly = py % 10
                    h += (0.55 * ly / 6.0) if ly < 6 else -0.35
                height[i] = h

                # Exhaust soot streaks run aft from the stubs on both flanks
                soot = 0.0
                if vn < 0.70:
                    for ue in (0.28, 0.72):
                        w = 0.012 + 0.035 * (0.70 - vn)
                        dd = (u - ue) / w
                        if -3.0 < dd < 3.0:
                            st = max(0.0, streak(u * 6.0, v * 0.35) - 0.42) * 2.4
                            soot += math.exp(-dd * dd) * st * 0.55 * min(1.0, (0.72 - vn) * 4.0)
                # Thin oil streaks along the belly
                oil = 0.0
                db = (u - 0.5) / 0.035
                if -3.0 < db < 3.0 and vn < 0.85:
                    oil = math.exp(-db * db) * max(0.0, streak(u * 9.0 + 0.3, v * 0.5) - 0.5) * 1.2

                chip_noise = 0.7 * g_fine + 0.3 * g_mid
                thr = 0.85
                if vn > 0.86:
                    thr = 0.70
                elif d_seam < 3.0:
                    thr = 0.74
                elif top < 0.14 and vn < 0.45:
                    thr = 0.75
                chip = 0.0
                if chip_noise > thr:
                    chip = min(1.0, (chip_noise - thr) * 30.0)

                panel = int(u * 8.0) * 7 + sum(1 for s in seams_v if vn > s)
                painted[i] = 1
                p_top[i] = top
                p_vn[i] = vn
                p_camo[i] = big(u, v * 1.5)
                p_mottle[i] = g_mid
                p_chip[i] = chip
                p_soot[i] = min(1.0, soot)
                p_oil[i] = min(1.0, oil)
                p_tone[i] = _hash01(panel, 3, 99) * 2.0 - 1.0

            elif v < 0.65:
                vn2 = (v - 0.45) / 0.20
                if u < 0.50:
                    # Finned cylinders: dark steel barrel, cast aluminium head
                    f = (vn2 * 36.0) % 1.0
                    tri = 1.0 - abs(2.0 * f - 1.0)
                    height[i] = 1.3 * tri + (g_fine - 0.5) * 0.2
                    grime = 0.75 + 0.35 * g_mid
                    if vn2 < 0.62:
                        c = (52 + 34 * tri) * grime
                        rgb = (c, c * 1.02, c * 1.08)
                        gl = 85
                    else:
                        c = (128 + 48 * tri) * grime
                        rgb = (c, c * 1.01, c * 0.98)
                        gl = 120
                elif u < 0.75:
                    un2 = (u - 0.50) / 0.25
                    if un2 > 0.70:
                        c = 205 + 30 * math.cos((un2 - 0.70) / 0.30 * math.pi * 2.0)
                        rgb = (c, c, c + 6)
                        gl = 250
                        height[i] = 0.0
                    else:
                        n = (g_fine - 0.5) * 30.0 + (g_mid - 0.5) * 20.0
                        rgb = (92 + n, 96 + n, 100 + n)
                        gl = 105
                        height[i] = (g_fine - 0.5) * 0.6
                else:
                    # Hexagonal radiator / intake honeycomb
                    cs = 7.0
                    qx = px / cs
                    qy = py / (cs * 0.866)
                    ry_i = int(qy)
                    qx2 = qx + (0.5 if ry_i % 2 else 0.0)
                    fx = qx2 % 1.0 - 0.5
                    fy = qy % 1.0 - 0.5
                    edge = max(abs(fx) * 1.15, abs(fy) * 1.0 + abs(fx) * 0.5)
                    wall = 1.0 if edge > 0.40 else 0.0
                    height[i] = 0.9 * wall
                    c = 66 if wall else 18 + 10 * g_mid
                    rgb = (c, c * 0.98, c * 0.94)
                    gl = 70 if wall else 30
                base_rgb[3 * i] = clamp_byte(rgb[0])
                base_rgb[3 * i + 1] = clamp_byte(rgb[1])
                base_rgb[3 * i + 2] = clamp_byte(rgb[2])
                base_gloss[i] = gl

            elif v < 0.80:
                # Heat-tinted exhaust stubs: steel -> straw -> purple -> blue -> soot
                vn3 = (v - 0.65) / 0.15
                tint = _gradient(EXHAUST_HEAT_STOPS, min(1.0, vn3 + (g_mid - 0.5) * 0.12))
                lum = 0.3 * tint[0] + 0.59 * tint[1] + 0.11 * tint[2]
                tint = _mix(tint, (lum, lum, lum), 0.35)  # tone down the heat-tint saturation
                m = 0.82 + 0.3 * g_fine
                rgb = (tint[0] * m, tint[1] * m, tint[2] * m)
                h = (g_fine - 0.5) * 0.5
                if abs(vn3 - 0.08) < 0.02:
                    h += 0.8  # weld bead
                    rgb = (rgb[0] * 0.8, rgb[1] * 0.8, rgb[2] * 0.8)
                height[i] = h
                base_rgb[3 * i] = clamp_byte(rgb[0])
                base_rgb[3 * i + 1] = clamp_byte(rgb[1])
                base_rgb[3 * i + 2] = clamp_byte(rgb[2])
                base_gloss[i] = clamp_byte(150 - 120 * vn3)

            else:
                vn4 = (v - 0.80) / 0.20
                if u < 0.70:
                    # Propeller blade
                    s = u / 0.70
                    edge = min(vn4, 1.0 - vn4)
                    sheen = 10.0 * math.sin(vn4 * math.pi)
                    rgb = (27 + sheen, 29 + sheen, 32 + sheen)
                    gl = 70
                    h = 0.0
                    if edge < 0.045 and s > 0.30 and g_fine > 0.55:
                        e = 105 + 35 * g_mid
                        rgb = (e, e, e + 4)       # leading/trailing edge erosion
                        gl = 170
                    if s > 0.885:
                        rgb = (232, 188, 30) if g_fine < 0.8 else (120, 110, 60)
                        gl = 120
                    elif s < 0.14:
                        c = 160 + 18 * g_mid
                        rgb = (c, c + 4, c + 10)
                        gl = 210
                        if abs(s - 0.12) < 0.006:
                            h = -0.6
                    elif 0.425 < s < 0.465 and 0.44 < vn4 < 0.56:
                        rgb = (118, 104, 62)  # small maker's decal
                        gl = 90
                    height[i] = h
                    base_rgb[3 * i] = clamp_byte(rgb[0])
                    base_rgb[3 * i + 1] = clamp_byte(rgb[1])
                    base_rgb[3 * i + 2] = clamp_byte(rgb[2])
                    base_gloss[i] = gl
                else:
                    # Spinner (painted per livery)
                    un = (u - 0.70) / 0.30
                    painted[i] = 2
                    p_top[i] = (un + vn4 * 1.15) % 1.0
                    p_vn[i] = vn4
                    chip_noise = 0.62 * g_fine + 0.38 * g_mid
                    p_chip[i] = min(1.0, max(0.0, (chip_noise - (0.72 if vn4 > 0.85 else 0.86)) * 30.0))
                    p_mottle[i] = g_mid
                    height[i] = (g_fine - 0.5) * 0.08

    # ---------------- normal map from height ----------------
    print("   normal map...")
    nrm = bytearray(4 * N)
    k = 2.4
    for py in range(H):
        up = max(0, py - 1) * W
        dn = min(H - 1, py + 1) * W
        row = py * W
        for px in range(W):
            l = row + (px - 1) % W
            r = row + (px + 1) % W
            dx = (height[r] - height[l]) * 0.5 * k
            dy = (height[up + px] - height[dn + px]) * 0.5 * k
            inv = 1.0 / math.sqrt(dx * dx + dy * dy + 1.0)
            o = 4 * (row + px)
            nrm[o] = clamp_byte((-dx * inv * 0.5 + 0.5) * 255.0)
            nrm[o + 1] = clamp_byte((-dy * inv * 0.5 + 0.5) * 255.0)
            nrm[o + 2] = clamp_byte((inv * 0.5 + 0.5) * 255.0)
            nrm[o + 3] = 255

    # Median of the camo noise -> exact 50/50 split between the two disruptive colours
    camo_samples = sorted(p_camo[i] for i in range(0, N, 61) if painted[i] == 1)
    camo_thr = camo_samples[len(camo_samples) // 2]

    # ---------------- livery compositing ----------------
    liveries = {}
    metal_bare = (172, 176, 182)

    def spinner_colour(key, pal, vn, phase, mt):
        gl = pal['gloss']
        if key == 'aluminum' or key == 'civil':
            c = 196 + 20 * mt
            col, gl = (c, c + 3, c + 8), 235
            if key == 'aluminum' and vn > 0.86:
                col, gl = (176, 30, 28), 150
        elif key == 'luftwaffe':
            col = (226, 226, 220) if phase < 0.22 else pal['spinner']  # Spiralschnauze
        elif key == 'soviet':
            col = (226, 226, 222) if abs(vn - 0.45) < 0.035 else pal['spinner']
        elif key == 'racer':
            col = (178, 28, 28) if vn > 0.80 else pal['spinner']
        elif key == 'trainer':
            col = (24, 24, 26) if vn > 0.85 else pal['spinner']
        else:
            col = pal['spinner']
        return col, gl

    def cowl_colour(key, pal, u, vn, top, camo, tone, mt):
        gl = pal['gloss']
        nose = 0.885 < vn < 0.935
        if key == 'aluminum':
            c = 176 + 9 * tone + 14 * (mt - 0.5)
            col, gl = (c, c + 4, c + 10), int(200 + 30 * tone)
            if top < 0.13 and vn < 0.82:
                col, gl = (60, 64, 50), 50          # anti-glare panel
            if nose:
                col, gl = (176, 30, 28), 160         # nose band
            return col, gl, False
        if key == 'civil':
            if top < 0.52:
                col = pal['top_a']
            elif top < 0.58:
                col = pal['cheat']                   # cheat line
            else:
                c = 182 + 8 * tone + 12 * (mt - 0.5)
                col, gl = (c, c + 5, c + 11), 205    # polished belly
            if nose:
                c = 196 + 10 * mt
                col, gl = (c, c + 3, c + 8), 225
            return col, gl, True
        if key in ('ijn', 'night'):
            return pal['top_a'], gl, True
        if key == 'racer':
            col = pal['top_a']
            if top < 0.07:
                col = (236, 236, 232)                # racing stripe
            if 0.86 < vn < 0.935:
                checker = (int(u * 32) + int((vn - 0.86) / 0.075 * 3)) % 2
                col = (236, 236, 232) if checker else (24, 24, 26)
            return col, gl, True
        if key == 'trainer':
            if top < 0.13 and vn < 0.82:
                return (30, 30, 32), 40, True        # anti-glare panel
            return pal['top_a'], gl, True
        demarc = 0.56 + 0.05 * math.sin(vn * 9.0 + camo * 3.0)
        if key == 'arctic':
            if top < demarc:
                col = pal['white'] if mt < 0.64 else pal['top_a']   # white distemper over green
            else:
                col = pal['under']
            return col, gl, True
        if key == 'italian':
            if top < demarc:
                col = pal['ring'] if abs(mt - 0.5) < 0.022 else pal['top_a']   # "smoke rings"
            else:
                col = pal['under']
            return col, gl, True
        if key == 'olive':
            if top < demarc:
                col = _mix(pal['top_a'], pal['top_b'], min(1.0, max(0.0, (camo - camo_thr) * 2.5)))  # sun-faded OD
            else:
                col = pal['under']
            return col, gl, True
        # raf, luftwaffe, usn, soviet, desert
        if top < demarc:
            if key == 'usn':
                col = _mix(pal['top_b'], pal['top_a'], max(0.0, 1.0 - top / 0.5))
            else:
                edge = (camo - camo_thr) * 60.0      # hard-edged disruptive pattern
                t = 0.0 if edge < -0.5 else (1.0 if edge > 0.5 else edge + 0.5)
                col = _mix(pal['top_a'], pal['top_b'], t)
            if key == 'luftwaffe' and top > demarc - 0.18:
                col = pal['under'] if mt < 0.55 else (pal['top_b'] if mt < 0.66 else pal['top_a'])
        else:
            col = pal['under']
            if key == 'luftwaffe' and vn > 0.62 and top > 0.74:
                col = pal['yellow']
        if key == 'soviet' and vn > 0.885:
            col = pal['nose']
        return col, gl, True

    for key in LIVERY_KEYS:
        print(f"   livery {key}...")
        pal = LIVERY_PALETTES[key]
        weather = pal['weather']
        out = bytearray(4 * N)
        for i in range(N):
            kind = painted[i]
            o = 4 * i
            if kind == 0:
                out[o] = base_rgb[3 * i]
                out[o + 1] = base_rgb[3 * i + 1]
                out[o + 2] = base_rgb[3 * i + 2]
                out[o + 3] = base_gloss[i]
                continue
            vn = p_vn[i]
            mt = p_mottle[i]
            if kind == 2:
                col, gl = spinner_colour(key, pal, vn, p_top[i], mt)
                painted_surface = key not in ('aluminum', 'civil')
            else:
                u = (i % W) / float(W - 1)
                top = p_top[i]
                col, gl, painted_surface = cowl_colour(key, pal, u, vn, top, p_camo[i], p_tone[i], mt)
                if painted_surface:
                    shade = 1.0 + 0.035 * p_tone[i] + 0.10 * (mt - 0.5) * weather
                    col = (col[0] * shade, col[1] * shade, col[2] * shade)
                    if top < 0.3:
                        col = _mix(col, (205, 205, 200), (0.3 - top) / 0.3 * 0.06 * weather)  # sun fading
            if painted_surface:
                chip = p_chip[i] * weather
                if chip > 0.0:
                    col = _mix(col, metal_bare, min(1.0, chip))
                    gl = int(gl + (210 - gl) * min(1.0, chip))
            soot = p_soot[i] * weather
            if soot > 0.0:
                col = _mix(col, (22, 20, 19), min(0.85, soot))
                gl = int(gl * (1.0 - 0.7 * min(1.0, soot)))
            oil = p_oil[i] * weather
            if oil > 0.0:
                col = _mix(col, (48, 34, 20), min(0.7, oil))
                gl = int(gl + (150 - gl) * min(1.0, oil))
            out[o] = clamp_byte(col[0])
            out[o + 1] = clamp_byte(col[1])
            out[o + 2] = clamp_byte(col[2])
            out[o + 3] = clamp_byte(gl)
        liveries[key] = bytes(out)

    # ---------------- custom paint kit (composited at runtime by CustomPaint.cs) ----------------
    # base: unpainted texels = final colour + gloss; painted texels = grey shade (200 = clean paint)
    #       + gloss factor. mask (R): 0 unpainted, 85 cowling, 170 nose ring, 255 spinner.
    print("   custom paint kit...")
    kit_base = bytearray(4 * N)
    kit_mask = bytearray(4 * N)
    for i in range(N):
        kind = painted[i]
        o = 4 * i
        kit_mask[o + 3] = 255
        if kind == 0 or p_chip[i] > 0.5:
            if kind == 0:
                rgb = (base_rgb[3 * i], base_rgb[3 * i + 1], base_rgb[3 * i + 2])
                gl = base_gloss[i]
            else:
                rgb, gl = metal_bare, 210            # paint chipped down to the metal
            kit_base[o] = clamp_byte(rgb[0])
            kit_base[o + 1] = clamp_byte(rgb[1])
            kit_base[o + 2] = clamp_byte(rgb[2])
            kit_base[o + 3] = clamp_byte(gl)
            continue
        if kind == 2:
            shade = 1.0 + 0.06 * (p_mottle[i] - 0.5)
            soot = 0.0
            m = 255
        else:
            shade = 1.0 + 0.035 * p_tone[i] + 0.10 * (p_mottle[i] - 0.5)
            soot = min(1.0, p_soot[i])
            shade *= (1.0 - 0.85 * soot) * (1.0 - 0.5 * min(1.0, p_oil[i]))
            m = 170 if 0.885 < p_vn[i] < 0.935 else 85
        g = clamp_byte(200.0 * shade)
        kit_base[o] = g
        kit_base[o + 1] = g
        kit_base[o + 2] = g
        kit_base[o + 3] = clamp_byte(255.0 * (1.0 - 0.7 * soot))
        kit_mask[o] = m
        kit_mask[o + 1] = m
        kit_mask[o + 2] = m

    # ---------------- emissive (exhaust glow band only) ----------------
    ew, eh = 256, 256
    emis = bytearray(4 * ew * eh)
    for py in range(eh):
        v = 1.0 - py / float(eh - 1)
        for px in range(ew):
            o = 4 * (py * ew + px)
            emis[o + 3] = 255
            if 0.65 <= v < 0.80:
                vn3 = (v - 0.65) / 0.15
                glow = smoothstep(0.30, 0.95, vn3)
                emis[o] = clamp_byte(255 * glow)
                emis[o + 1] = clamp_byte(118 * glow ** 1.4)
                emis[o + 2] = clamp_byte(36 * glow ** 2.2)

    return liveries, bytes(nrm), bytes(emis), ew, eh, bytes(kit_base), bytes(kit_mask)


def generate_blur_disc_texture(tex_w=512, tex_h=512):
    """Soft motion-blurred propeller disc: dense near the root, transparent at the tip."""
    rgba = bytearray(tex_w * tex_h * 4)
    cx = 0.5 * (tex_w - 1)
    cy = 0.5 * (tex_h - 1)
    max_r = 0.5 * tex_w
    for py in range(tex_h):
        dy = py - cy
        for px in range(tex_w):
            dx = px - cx
            r = math.sqrt(dx * dx + dy * dy) / max_r
            idx = (py * tex_w + px) * 4
            if r > 0.995 or r < 0.10:
                continue
            theta = math.atan2(dy, dx)
            # Blade solidity falls with radius (chord * blades / circumference)
            solidity = 0.32 * (1.0 - 0.62 * r) / max(0.25, r)
            env = smoothstep(0.10, 0.20, r) * (1.0 - smoothstep(0.95, 0.995, r))
            ripple = 1.0 + 0.10 * math.cos(theta * 4.0) + 0.05 * math.cos(theta * 7.0 + 1.3)
            alpha = min(0.55, solidity) * env * ripple
            col = (30, 32, 36)
            if 0.885 <= r <= 0.965:
                t = math.sin((r - 0.885) / 0.08 * math.pi)
                col = _mix(col, (236, 192, 34), t)
                alpha = max(alpha, 0.22 * t * env)
            elif r < 0.17:
                col = (150, 154, 160)
            rgba[idx] = clamp_byte(col[0])
            rgba[idx + 1] = clamp_byte(col[1])
            rgba[idx + 2] = clamp_byte(col[2])
            rgba[idx + 3] = clamp_byte(alpha * 255.0)
    return bytes(rgba), tex_w, tex_h


# ==============================================================================
# 2. 3D PROCEDURAL PROPELLER MESH BUILDER (FOR .MU & PREVIEWS)
# ==============================================================================

def add_cylinder_segment(mb, p0, p1, r0, r1, u0, u1, v0, v1, segs=16, cap_start=False, cap_end=False):
    """Add a 3D frustum/cylinder along an arbitrary axis p0 -> p1 with outward normals."""
    axis = sub3(p1, p0)
    length = math.sqrt(dot3(axis, axis))
    if length < 1e-6:
        return
    fwd = normalize3(*axis)
    up_ref = (0.0, 0.0, -1.0) if abs(fwd[2]) < 0.9 else (1.0, 0.0, 0.0)
    right = normalize3(*cross3(up_ref, fwd))
    up = normalize3(*cross3(fwd, right))

    slope = (r0 - r1) / length
    ring0 = []
    ring1 = []
    for i in range(segs + 1):
        frac = i / float(segs)
        ang = frac * math.pi * 2.0
        ca, sa = math.cos(ang), math.sin(ang)
        r_dir = (
            right[0] * ca + up[0] * sa,
            right[1] * ca + up[1] * sa,
            right[2] * ca + up[2] * sa,
        )
        n_dir = normalize3(
            r_dir[0] + fwd[0] * slope,
            r_dir[1] + fwd[1] * slope,
            r_dir[2] + fwd[2] * slope,
        )
        v_p0 = (p0[0] + r_dir[0] * r0, p0[1] + r_dir[1] * r0, p0[2] + r_dir[2] * r0)
        v_p1 = (p1[0] + r_dir[0] * r1, p1[1] + r_dir[1] * r1, p1[2] + r_dir[2] * r1)
        u = lerp(u0, u1, frac)
        ring0.append(mb.add_vertex(v_p0, (u, v0), n_dir))
        ring1.append(mb.add_vertex(v_p1, (u, v1), n_dir))

    for i in range(segs):
        mb.add_quad(ring0[i], ring1[i], ring1[i + 1], ring0[i + 1], ensure_outward=True)

    if cap_start and r0 > 1e-4:
        n_start = (-fwd[0], -fwd[1], -fwd[2])
        c_idx = mb.add_vertex(p0, (0.5 * (u0 + u1), v0), n_start)
        cap_r = []
        for i in range(segs + 1):
            ang = (i / float(segs)) * math.pi * 2.0
            ca, sa = math.cos(ang), math.sin(ang)
            r_dir = (right[0] * ca + up[0] * sa, right[1] * ca + up[1] * sa, right[2] * ca + up[2] * sa)
            vp = (p0[0] + r_dir[0] * r0, p0[1] + r_dir[1] * r0, p0[2] + r_dir[2] * r0)
            cap_r.append(mb.add_vertex(vp, (0.5 * (u0 + u1), v0), n_start))
        for i in range(segs):
            mb.add_tri(c_idx, cap_r[i + 1], cap_r[i], ensure_outward=True)

    if cap_end and r1 > 1e-4:
        n_end = fwd
        c_idx = mb.add_vertex(p1, (0.5 * (u0 + u1), v1), n_end)
        cap_r = []
        for i in range(segs + 1):
            ang = (i / float(segs)) * math.pi * 2.0
            ca, sa = math.cos(ang), math.sin(ang)
            r_dir = (right[0] * ca + up[0] * sa, right[1] * ca + up[1] * sa, right[2] * ca + up[2] * sa)
            vp = (p1[0] + r_dir[0] * r1, p1[1] + r_dir[1] * r1, p1[2] + r_dir[2] * r1)
            cap_r.append(mb.add_vertex(vp, (0.5 * (u0 + u1), v1), n_end))
        for i in range(segs):
            mb.add_tri(c_idx, cap_r[i], cap_r[i + 1], ensure_outward=True)


def build_propeller_part_meshes(spec):
    """
    Build all meshes for a procedural propeller engine spec:
      - cowl_mesh: Main aerodynamic cowling
      - core_mesh: Radial cylinders / crankcase / internal intake details
      - exh_mesh: Exhaust stubs / turbine tailpipes & radiator scoops
      - flap_mesh: Articulated cowl flaps / radiator exit doors
      - spin_mesh: Forward spinner cone (in FrontPropHub local space)
      - fblade_mesh: Forward 3D twisted airfoil blades (in FrontPropHub local space)
      - fdisc_mesh: Forward motion-blur rotor disc (in FrontPropHub local space)
      - rspin_mesh: Rear coaxial spinner collar (in RearPropHub local space)
      - rblade_mesh: Rear contra-rotating blades (in RearPropHub local space)
      - rdisc_mesh: Rear motion-blur rotor disc (in RearPropHub local space)
      - cowl_col: Convex cowling collider
      - spin_col: Convex spinner collider
    """
    arch = spec['arch']  # 'Radial', 'VInline', 'Turboprop'
    cowl_d = spec['cowl_dia']
    cowl_l = spec['cowl_len']
    prop_d = spec['prop_dia']
    blades = spec['blades']
    contra = spec['contra']
    blade_style = spec.get('blade_style', 'Paddle')

    r_base = 0.5 * cowl_d
    half_l = 0.5 * cowl_l
    y_aft = -half_l
    y_fwd = half_l
    spin_l = max(0.32, min(0.85, cowl_d * 0.48))
    spin_r = r_base * (0.36 if arch == 'Radial' else (0.44 if arch == 'VInline' else 0.38))

    cowl_mb = MeshBuilder()
    core_mb = MeshBuilder()
    exh_mb = MeshBuilder()
    flap_mb = MeshBuilder()

    n_S = 36
    n_T = 48

    def cowl_profile(s, theta):
        """Return (x, y, z) on outer cowling for s in [0, 1] (aft->fwd), theta in [0, 2pi)."""
        y = lerp(y_aft, y_fwd, s)
        st = math.sin(theta)
        ct = math.cos(theta)

        if arch == 'Radial':
            # NACA cowling barrel with rounded front lip
            env = 1.0 + 0.06 * math.sin(s * math.pi)
            if s > 0.82:
                t_lip = (s - 0.82) / 0.18
                env *= lerp(1.0, 0.74, t_lip * t_lip)
            rx = r_base * env
            rz = r_base * env
            z_off = 0.0
        elif arch == 'VInline':
            # Streamlined V-12 cowling tapering smoothly to spinner_r at s=1
            taper = lerp(1.0, spin_r / r_base, s ** 1.35)
            # Upper V-bank shoulder bulges at theta ~ +-45 deg (ct > 0)
            v_bank = 0.0
            if ct > 0.15 and 0.10 < s < 0.85:
                v_bank = 0.12 * r_base * math.sin((s - 0.10) / 0.75 * math.pi) * (abs(st) * (ct ** 0.7))
            rx = r_base * taper + v_bank
            rz = r_base * (taper * 1.06) + v_bank * 0.6
            # Slight downward nose droop so spinner aligns cleanly
            z_off = 0.08 * r_base * (s ** 1.4)
        else:
            # Streamlined Turboprop cowling (T56 / NK-12 style)
            taper = lerp(0.94, max(spin_r * 1.18, r_base * 0.56) / r_base, s ** 1.15)
            bulb = 0.07 * math.sin(s * math.pi)
            rx = r_base * (taper + bulb)
            rz = r_base * (taper * 1.05 + bulb)
            z_off = -0.04 * r_base * s

        x = rx * st
        z = -rz * ct + z_off
        return (x, y, z)

    # Loft outer cowling
    grid = []
    eps_s = 1.0 / (n_S * 4.0)
    eps_t = (2.0 * math.pi) / (n_T * 4.0)
    for i in range(n_S + 1):
        s = i / float(n_S)
        row = []
        v_uv = lerp(0.02, 0.43, s)
        for j in range(n_T + 1):
            u_frac = j / float(n_T)
            theta = (u_frac * 2.0 * math.pi) % (2.0 * math.pi)
            pos = cowl_profile(s, theta)
            s_lo, s_hi = max(0.0, s - eps_s), min(1.0, s + eps_s)
            dp_ds = sub3(cowl_profile(s_hi, theta), cowl_profile(s_lo, theta))
            dp_dt = sub3(cowl_profile(s, (theta + eps_t) % (2.0 * math.pi)), cowl_profile(s, (theta - eps_t) % (2.0 * math.pi)))
            nrm = cross3(dp_dt, dp_ds)
            if pos[0] * nrm[0] + pos[2] * nrm[2] < 0.0:
                nrm = (-nrm[0], -nrm[1], -nrm[2])
            u_uv = 0.5 + 0.5 * math.sin(theta) if math.cos(theta) >= 0 else (1.0 - 0.5 * (0.5 + 0.5 * math.sin(theta)))
            row.append(cowl_mb.add_vertex(pos, (u_frac, v_uv), nrm))
        grid.append(row)

    for i in range(n_S):
        for j in range(n_T):
            cowl_mb.add_quad(grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1], ensure_outward=True)

    # Cap aft firewall at y_aft (normal 0, -1, 0)
    aft_center = cowl_mb.add_vertex((0.0, y_aft, 0.0), (0.62, 0.55), (0.0, -1.0, 0.0))
    aft_ring = []
    for j in range(n_T + 1):
        theta = (j / float(n_T)) * 2.0 * math.pi
        pos = cowl_profile(0.0, theta)
        aft_ring.append(cowl_mb.add_vertex(pos, (0.62, 0.55), (0.0, -1.0, 0.0)))
    for j in range(n_T):
        cowl_mb.add_tri(aft_center, aft_ring[j + 1], aft_ring[j], ensure_outward=True)

    # Cap forward cowl face
    fwd_center = cowl_mb.add_vertex((0.0, y_fwd - (0.16 * cowl_l if arch == 'Radial' else 0.0), 0.0), (0.88, 0.55), (0.0, 1.0, 0.0))
    fwd_ring = []
    for j in range(n_T + 1):
        theta = (j / float(n_T)) * 2.0 * math.pi
        pos = cowl_profile(1.0, theta)
        fwd_ring.append(cowl_mb.add_vertex(pos, (0.88, 0.55), (0.0, 1.0, 0.0)))
    for j in range(n_T):
        cowl_mb.add_tri(fwd_center, fwd_ring[j], fwd_ring[j + 1], ensure_outward=True)

    # Architecture-specific 3D details
    if arch == 'Radial':
        # 18-cylinder twin-row star inside the NACA throat + central crankcase dome
        add_cylinder_segment(
            core_mb,
            (0.0, y_fwd - 0.35 * cowl_l, 0.0),
            (0.0, y_fwd + 0.02 * cowl_l, 0.0),
            r_base * 0.42,
            spin_r * 0.92,
            0.52,
            0.68,
            0.47,
            0.63,
            segs=20,
            cap_end=True,
        )
        for row_idx in range(2):
            y_cyl = y_fwd - (0.14 + 0.16 * row_idx) * cowl_l
            n_cyl = 9
            for c_i in range(n_cyl):
                ang = (c_i + 0.5 * row_idx) * (2.0 * math.pi / n_cyl)
                dx, dz = math.sin(ang), -math.cos(ang)
                p_in = (dx * r_base * 0.34, y_cyl, dz * r_base * 0.34)
                p_out = (dx * r_base * 0.84, y_cyl, dz * r_base * 0.84)
                add_cylinder_segment(core_mb, p_in, p_out, r_base * 0.13, r_base * 0.145, 0.05, 0.45, 0.46, 0.64, segs=10, cap_end=True)
                # Twin pushrod tubes
                for side in (-1, 1):
                    tx, tz = math.cos(ang) * side * r_base * 0.045, math.sin(ang) * side * r_base * 0.045
                    pr0 = (dx * r_base * 0.35 + tx, y_cyl + 0.05 * cowl_l, dz * r_base * 0.35 + tz)
                    pr1 = (dx * r_base * 0.78 + tx, y_cyl + 0.02 * cowl_l, dz * r_base * 0.78 + tz)
                    add_cylinder_segment(core_mb, pr0, pr1, r_base * 0.016, r_base * 0.016, 0.68, 0.74, 0.48, 0.62, segs=6)

        # Ventral carburetor scoop & twin exhaust collector stubs
        add_cylinder_segment(
            exh_mb,
            (0.0, y_aft + 0.15 * cowl_l, r_base * 0.92),
            (0.0, y_fwd - 0.18 * cowl_l, r_base * 0.88),
            r_base * 0.18,
            r_base * 0.20,
            0.20,
            0.40,
            0.10,
            0.35,
            segs=12,
            cap_start=True,
            cap_end=True,
        )
        for side in (-1, 1):
            p0 = (side * r_base * 0.72, y_aft + 0.22 * cowl_l, r_base * 0.55)
            p1 = (side * r_base * 0.86, y_aft - 0.05 * cowl_l, r_base * 0.64)
            add_cylinder_segment(exh_mb, p0, p1, r_base * 0.09, r_base * 0.08, 0.10, 0.90, 0.66, 0.79, segs=10, cap_end=True)

        # Cowl flaps ring near aft edge
        add_cylinder_segment(
            flap_mb,
            (0.0, y_aft + 0.18 * cowl_l, 0.0),
            (0.0, y_aft + 0.03 * cowl_l, 0.0),
            r_base * 1.01,
            r_base * 1.06,
            0.0,
            1.0,
            0.04,
            0.12,
            segs=24,
        )

    elif arch == 'VInline':
        # 12 individual ejector exhaust stubs (6 port, 6 starboard)
        for side in (-1, 1):
            for k in range(6):
                frac = (k + 0.5) / 6.0
                y_st = lerp(y_aft + 0.18 * cowl_l, y_fwd - 0.22 * cowl_l, frac)
                r_loc = lerp(r_base * 0.86, spin_r * 1.35, frac)
                p0 = (side * r_loc * 0.88, y_st, -r_base * 0.18)
                p1 = (side * (r_loc * 1.12), y_st - 0.06 * cowl_l, -r_base * 0.16)
                add_cylinder_segment(exh_mb, p0, p1, r_base * 0.055, r_base * 0.048, 0.10, 0.90, 0.66, 0.79, segs=8, cap_end=True)

        # Ventral Meredith chin radiator bath
        add_cylinder_segment(
            core_mb,
            (0.0, y_aft + 0.12 * cowl_l, r_base * 0.86),
            (0.0, y_fwd - 0.28 * cowl_l, r_base * 0.72),
            r_base * 0.34,
            r_base * 0.30,
            0.15,
            0.45,
            0.08,
            0.36,
            segs=14,
            cap_start=True,
            cap_end=True,
        )
        # Radiator exit flap
        add_cylinder_segment(
            flap_mb,
            (0.0, y_aft + 0.15 * cowl_l, r_base * 0.90),
            (0.0, y_aft + 0.02 * cowl_l, r_base * 0.98),
            r_base * 0.28,
            r_base * 0.26,
            0.20,
            0.40,
            0.04,
            0.12,
            segs=10,
            cap_end=True,
        )
    else:
        # Turboprop: Deep chin scoop OR concentric intake + large twin/quad jet exhaust tailpipes
        add_cylinder_segment(
            core_mb,
            (0.0, y_aft + 0.25 * cowl_l, r_base * 0.68),
            (0.0, y_fwd - 0.06 * cowl_l, r_base * 0.58),
            r_base * 0.36,
            r_base * 0.38,
            0.76,
            0.98,
            0.46,
            0.64,
            segs=16,
            cap_start=True,
            cap_end=True,
        )
        for side in (-1, 1):
            p0 = (side * r_base * 0.68, y_aft + 0.35 * cowl_l, r_base * 0.25)
            p1 = (side * r_base * 0.92, y_aft + 0.04 * cowl_l, r_base * 0.36)
            add_cylinder_segment(exh_mb, p0, p1, r_base * 0.19, r_base * 0.17, 0.10, 0.90, 0.66, 0.79, segs=14, cap_end=True)
        add_cylinder_segment(
            flap_mb,
            (0.0, y_aft + 0.12 * cowl_l, 0.0),
            (0.0, y_aft + 0.02 * cowl_l, 0.0),
            r_base * 0.95,
            r_base * 0.92,
            0.0,
            1.0,
            0.04,
            0.10,
            segs=18,
        )

    # Helper to build spinner + 3D twisted airfoil blades in hub-local coordinates
    def build_hub_meshes(hub_spin_r, hub_spin_l, is_rear=False, sense=1.0):
        sp_mb = MeshBuilder()
        bl_mb = MeshBuilder()
        dc_mb = MeshBuilder()

        # Spinner cone (local Y from 0 to hub_spin_l)
        sp_segs = 28
        sp_stacks = 14
        sp_grid = []
        for i in range(sp_stacks + 1):
            t = i / float(sp_stacks)
            if is_rear:
                # Coaxial rear spinner collar ring
                y = lerp(-0.45 * hub_spin_l, 0.45 * hub_spin_l, t)
                r = lerp(hub_spin_r * 1.06, hub_spin_r * 0.96, t)
            else:
                y = t * hub_spin_l
                # Ogival fighter/turboprop spinner profile
                r = hub_spin_r * math.sqrt(max(0.0, 1.0 - (t ** 1.75)))
            v_uv = lerp(0.81, 0.99, t)
            row = []
            for j in range(sp_segs + 1):
                u_frac = j / float(sp_segs)
                ang = u_frac * 2.0 * math.pi
                st, ct = math.sin(ang), -math.cos(ang)
                pos = (r * st, y, r * ct)
                nrm = normalize3(st, 0.35 * t if not is_rear else 0.08, ct)
                row.append(sp_mb.add_vertex(pos, (lerp(0.71, 0.99, u_frac), v_uv), nrm))
            sp_grid.append(row)

        for i in range(sp_stacks):
            for j in range(sp_segs):
                sp_mb.add_quad(sp_grid[i][j], sp_grid[i + 1][j], sp_grid[i + 1][j + 1], sp_grid[i][j + 1], ensure_outward=True)

        # Base cap of spinner
        base_y = -0.45 * hub_spin_l if is_rear else 0.0
        base_c = sp_mb.add_vertex((0.0, base_y, 0.0), (0.85, 0.82), (0.0, -1.0, 0.0))
        base_r = []
        r0_cap = hub_spin_r * 1.06 if is_rear else hub_spin_r
        for j in range(sp_segs + 1):
            ang = (j / float(sp_segs)) * 2.0 * math.pi
            pos = (r0_cap * math.sin(ang), base_y, -r0_cap * math.cos(ang))
            base_r.append(sp_mb.add_vertex(pos, (0.85, 0.82), (0.0, -1.0, 0.0)))
        for j in range(sp_segs):
            sp_mb.add_tri(base_c, base_r[j + 1], base_r[j], ensure_outward=True)

        if is_rear:
            top_c = sp_mb.add_vertex((0.0, 0.45 * hub_spin_l, 0.0), (0.85, 0.98), (0.0, 1.0, 0.0))
            top_r = []
            for j in range(sp_segs + 1):
                ang = (j / float(sp_segs)) * 2.0 * math.pi
                pos = (hub_spin_r * 0.96 * math.sin(ang), 0.45 * hub_spin_l, -hub_spin_r * 0.96 * math.cos(ang))
                top_r.append(sp_mb.add_vertex(pos, (0.85, 0.98), (0.0, 1.0, 0.0)))
            for j in range(sp_segs):
                sp_mb.add_tri(top_c, top_r[j], top_r[j + 1], ensure_outward=True)

        # 3D Twisted Airfoil Propeller Blades
        prop_r = 0.5 * prop_d
        r_root = hub_spin_r * 0.82
        y_hub_plane = 0.0 if is_rear else 0.26 * hub_spin_l
        n_span = 10
        n_chord = 10

        for b_idx in range(blades):
            base_ang = (b_idx + (0.5 if is_rear else 0.0)) * (2.0 * math.pi / blades)
            rx_dir, rz_dir = math.sin(base_ang), -math.cos(base_ang)
            tx_dir, tz_dir = math.cos(base_ang) * sense, math.sin(base_ang) * sense

            b_grid = []
            for i_s in range(n_span + 1):
                s = i_s / float(n_span)
                r_curr = lerp(r_root, prop_r, s)
                # Blade chord & thickness distribution
                if blade_style == 'Scimitar':
                    chord = prop_r * (0.15 * math.sin(math.pi * (s ** 0.72)) + 0.045 * (1.0 - s))
                    sweep = prop_r * 0.11 * (s ** 2.2)
                elif blade_style == 'Paddle':
                    chord = prop_r * (0.165 * (0.35 + 0.65 * math.sin(math.pi * (s ** 0.65))))
                    sweep = 0.0
                else:
                    chord = prop_r * (0.14 * math.sin(math.pi * (s ** 0.80)) + 0.04 * (1.0 - s))
                    sweep = 0.0

                thick = chord * lerp(0.28, 0.06, s ** 0.65)
                # Geometric washout twist from root (42 deg) to tip (16 deg)
                twist_rad = math.radians(lerp(42.0, 16.0, s))
                cos_tw, sin_tw = math.cos(twist_rad), math.sin(twist_rad)

                u_uv = lerp(0.02, 0.69, s)
                row = []
                for j_c in range(n_chord + 1):
                    c_frac = j_c / float(n_chord)
                    ang_c = c_frac * 2.0 * math.pi
                    # Airfoil local coordinates: xc along chord [-0.5*chord, +0.5*chord], yc thickness
                    xc = 0.5 * chord * math.cos(ang_c) - sweep
                    yc = 0.5 * thick * math.sin(ang_c) * (0.85 + 0.15 * math.cos(ang_c * 0.5))
                    # Rotate by blade pitch/twist: tangentially + axially (+Y)
                    tang_off = xc * cos_tw - yc * sin_tw
                    axial_off = xc * sin_tw + yc * cos_tw

                    px = rx_dir * r_curr + tx_dir * tang_off
                    py = y_hub_plane + axial_off
                    pz = rz_dir * r_curr + tz_dir * tang_off

                    # Local airfoil outward normal
                    nx_loc = math.cos(ang_c) * 0.25
                    ny_loc = math.sin(ang_c)
                    n_tang = nx_loc * cos_tw - ny_loc * sin_tw
                    n_axial = nx_loc * sin_tw + ny_loc * cos_tw
                    n_rad = 0.15 if s > 0.92 else (-0.15 if s < 0.08 else 0.0)
                    nrm = normalize3(
                        rx_dir * n_rad + tx_dir * n_tang,
                        n_axial,
                        rz_dir * n_rad + tz_dir * n_tang,
                    )
                    v_uv = lerp(0.81, 0.99, 0.5 + 0.5 * math.cos(ang_c))
                    row.append(bl_mb.add_vertex((px, py, pz), (u_uv, v_uv), nrm))
                b_grid.append(row)

            for i_s in range(n_span):
                for j_c in range(n_chord):
                    bl_mb.add_quad(
                        b_grid[i_s][j_c],
                        b_grid[i_s + 1][j_c],
                        b_grid[i_s + 1][j_c + 1],
                        b_grid[i_s][j_c + 1],
                        ensure_outward=True,
                    )

            # Cap blade tip at s=1
            tip_pos = (rx_dir * prop_r - tx_dir * sweep, y_hub_plane, rz_dir * prop_r - tz_dir * sweep)
            tip_c = bl_mb.add_vertex(tip_pos, (0.68, 0.90), (rx_dir, 0.0, rz_dir))
            tip_ring = []
            for j_c in range(n_chord + 1):
                vp = bl_mb.verts[b_grid[n_span][j_c]]
                tip_ring.append(bl_mb.add_vertex(vp, (0.68, 0.90), (rx_dir, 0.0, rz_dir)))
            for j_c in range(n_chord):
                bl_mb.add_tri(tip_c, tip_ring[j_c], tip_ring[j_c + 1], ensure_outward=True)

        # Double-sided slightly biconvex rotor blur disc (in hub local space)
        disc_segs = 32
        for side_y, side_n in ((y_hub_plane + 0.012, (0.0, 1.0, 0.0)), (y_hub_plane - 0.012, (0.0, -1.0, 0.0))):
            c_idx = dc_mb.add_vertex((0.0, side_y + 0.004 * side_n[1], 0.0), (0.5, 0.5), side_n)
            ring = []
            for j in range(disc_segs + 1):
                ang = (j / float(disc_segs)) * 2.0 * math.pi
                st, ct = math.sin(ang), -math.cos(ang)
                pos = (prop_r * st, side_y, prop_r * ct)
                uv = (0.5 + 0.49 * st, 0.5 + 0.49 * ct)
                ring.append(dc_mb.add_vertex(pos, uv, side_n))
            for j in range(disc_segs):
                if side_n[1] > 0:
                    dc_mb.add_tri(c_idx, ring[j], ring[j + 1], ensure_outward=True)
                else:
                    dc_mb.add_tri(c_idx, ring[j + 1], ring[j], ensure_outward=True)

        return sp_mb.finalize(), bl_mb.finalize(), dc_mb.finalize()

    f_spin, f_blades, f_disc = build_hub_meshes(spin_r, spin_l, is_rear=False, sense=1.0)
    r_spin, r_blades, r_disc = build_hub_meshes(spin_r * 1.02, spin_l * 0.42, is_rear=True, sense=-1.0)

    # Convex Colliders for FAR Voxelization (Cowling + Spinner ONLY — never blades!)
    cowl_col_mb = MeshBuilder()
    add_cylinder_segment(
        cowl_col_mb,
        (0.0, y_aft, 0.0),
        (0.0, y_fwd, 0.0),
        r_base,
        r_base * (0.85 if arch == 'Radial' else 0.55),
        0.0,
        1.0,
        0.0,
        1.0,
        segs=16,
        cap_start=True,
        cap_end=True,
    )
    spin_col_mb = MeshBuilder()
    add_cylinder_segment(
        spin_col_mb,
        (0.0, y_fwd, 0.0),
        (0.0, y_fwd + spin_l, 0.0),
        spin_r,
        spin_r * 0.15,
        0.0,
        1.0,
        0.0,
        1.0,
        segs=12,
        cap_start=True,
        cap_end=True,
    )

    return {
        'cowl': cowl_mb.finalize(),
        'core': core_mb.finalize(),
        'exh': exh_mb.finalize(),
        'flap': flap_mb.finalize(),
        'f_spin': f_spin,
        'f_blades': f_blades,
        'f_disc': f_disc,
        'r_spin': r_spin,
        'r_blades': r_blades,
        'r_disc': r_disc,
        'cowl_col': cowl_col_mb.finalize(),
        'spin_col': spin_col_mb.finalize(),
        'hub_y': y_fwd + (0.18 * spin_l if contra else 0.0),
        'rear_hub_y': y_fwd - 0.06 * spin_l,
    }


def write_propeller_mu(filepath, spec, meshes):
    """Write a KSP .mu v5 binary file for a procedural propeller engine part."""
    w = MuWriter()
    w.write_uint(0x00012aff)
    w.write_int(5)
    w.write_string('propeller_engine')

    # Root: 'propeller_engine'
    w.write_transform('propeller_engine', (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    w.write_tag_and_layer('Untagged', 0)

    # 1. Child: 'CowlingGroup'
    w.write_int(0)
    w.write_transform('CowlingGroup', (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    w.write_tag_and_layer('Untagged', 0)

    for node_name, mesh_key in (
        ('CowlingMesh', 'cowl'),
        ('EngineCoreDetailsMesh', 'core'),
        ('ExhaustAndRadiatorMesh', 'exh'),
        ('CowlFlapsMesh', 'flap'),
    ):
        w.write_int(0)
        w.write_transform(node_name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        w.write_tag_and_layer('Untagged', 0)
        w.write_mesh_filter(*meshes[mesh_key])
        w.write_mesh_renderer([0], cast_shadows=True, receive_shadows=True)
        w.write_int(1)

    for col_name, col_key in (('cowlingCollider', 'cowl_col'), ('spinnerCollider', 'spin_col')):
        w.write_int(0)
        w.write_transform(col_name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
        w.write_tag_and_layer('Untagged', 0)
        w.write_mesh_collider2(*meshes[col_key], is_trigger=False, convex=True)
        w.write_int(1)

    w.write_int(1)  # End 'CowlingGroup'

    # 2. Child: 'FrontPropHub'
    hub_y = meshes['hub_y']
    w.write_int(0)
    w.write_transform('FrontPropHub', (0.0, hub_y, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    w.write_tag_and_layer('Untagged', 0)

    for node_name, mesh_key, mat_idx in (
        ('SpinnerMesh', 'f_spin', 0),
        ('FrontBladesMesh', 'f_blades', 0),
        ('FrontRotorDisc', 'f_disc', 1),
    ):
        w.write_int(0)
        # Hide FrontRotorDisc by default in static editor icon via tiny scale (C# restores in flight)
        sc = (0.0001, 0.0001, 0.0001) if node_name == 'FrontRotorDisc' else (1.0, 1.0, 1.0)
        w.write_transform(node_name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), sc)
        w.write_tag_and_layer('Untagged', 0)
        w.write_mesh_filter(*meshes[mesh_key])
        w.write_mesh_renderer([mat_idx], cast_shadows=(mat_idx == 0), receive_shadows=True)
        w.write_int(1)

    w.write_int(1)  # End 'FrontPropHub'

    # 3. Child: 'RearPropHub' (active when contra=True, scaled to 0.0001 when contra=False)
    rear_y = meshes['rear_hub_y']
    rear_sc = (1.0, 1.0, 1.0) if spec['contra'] else (0.0001, 0.0001, 0.0001)
    w.write_int(0)
    w.write_transform('RearPropHub', (0.0, rear_y, 0.0), (0.0, 0.0, 0.0, 1.0), rear_sc)
    w.write_tag_and_layer('Untagged', 0)

    for node_name, mesh_key, mat_idx in (
        ('RearSpinnerMesh', 'r_spin', 0),
        ('RearBladesMesh', 'r_blades', 0),
        ('RearRotorDisc', 'r_disc', 1),
    ):
        w.write_int(0)
        sc = (0.0001, 0.0001, 0.0001) if node_name == 'RearRotorDisc' else (1.0, 1.0, 1.0)
        w.write_transform(node_name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), sc)
        w.write_tag_and_layer('Untagged', 0)
        w.write_mesh_filter(*meshes[mesh_key])
        w.write_mesh_renderer([mat_idx], cast_shadows=(mat_idx == 0), receive_shadows=True)
        w.write_int(1)

    w.write_int(1)  # End 'RearPropHub'

    # 4. Child: 'thrustTransform' (local +Z points along (0, -1, 0) so thrust is along +Y)
    w.write_int(0)
    w.write_transform('thrustTransform', (0.0, hub_y, 0.0), (0.70710678, 0.0, 0.0, 0.70710678), (1.0, 1.0, 1.0))
    w.write_tag_and_layer('Untagged', 0)
    w.write_int(1)  # End 'thrustTransform'

    # 5. Exhaust FX anchors (repositioned per architecture by ModuleProceduralPropeller)
    r_base = 0.5 * spec['cowl_dia']
    y_ex = -0.5 * spec['cowl_len']
    for ex_name, side in (('exhaustPortL', -1.0), ('exhaustPortR', 1.0)):
        w.write_int(0)
        w.write_transform(ex_name, (side * r_base * 0.86, y_ex, r_base * 0.62), (0.70710678, 0.0, 0.0, 0.70710678), (1.0, 1.0, 1.0))
        w.write_tag_and_layer('Untagged', 0)
        w.write_int(1)

    # Materials (EntryType 10)
    w.write_int(10)
    w.write_int(2)

    # Mat 0: KSP/Emissive/Bumped Specular (livery map + shared normal map + exhaust glow map)
    w.write_string(f"{spec['id']}_mat")
    w.write_string('KSP/Emissive/Bumped Specular')
    w.write_int(12)
    for pname, rgba in [
        ('_Color', (1.0, 1.0, 1.0, 1.0)),
        ('_SpecColor', (0.68, 0.70, 0.74, 1.0)),
        ('_EmissiveColor', (0.0, 0.0, 0.0, 1.0)),
        ('_RimColor', (0.0, 0.0, 0.0, 0.0)),
        ('_TemperatureColor', (0.0, 0.0, 0.0, 0.0)),
        ('_BurnColor', (1.0, 1.0, 1.0, 1.0)),
    ]:
        w.write_string(pname)
        w.write_int(0)
        w.write_floats(rgba)
    for pname, val in [('_Shininess', 0.52), ('_Opacity', 1.0), ('_RimFalloff', 0.1)]:
        w.write_string(pname)
        w.write_int(3)
        w.write_float(val)
    for pname, tidx in [('_MainTex', 0), ('_Emissive', 1), ('_BumpMap', 3)]:
        w.write_string(pname)
        w.write_int(4)
        w.write_int(tidx)
        w.write_floats((1.0, 1.0))
        w.write_floats((0.0, 0.0))

    # Mat 1: KSP/Alpha/Translucent (Rotor Blur Disc)
    w.write_string(f"{spec['id']}_disc_mat")
    w.write_string('KSP/Alpha/Translucent')
    w.write_int(5)
    for pname, rgba in [
        ('_RimColor', (0.0, 0.0, 0.0, 0.0)),
        ('_TemperatureColor', (0.0, 0.0, 0.0, 0.0)),
        ('_BurnColor', (1.0, 1.0, 1.0, 1.0)),
    ]:
        w.write_string(pname)
        w.write_int(0)
        w.write_floats(rgba)
    w.write_string('_RimFalloff')
    w.write_int(3)
    w.write_float(0.1)
    w.write_string('_MainTex')
    w.write_int(4)
    w.write_int(2)
    w.write_floats((1.0, 1.0))
    w.write_floats((0.0, 0.0))

    # Textures block (EntryType 12): all live next to the .mu in Parts/PropShared
    w.write_int(12)
    w.write_int(4)
    w.write_string(f"ropp_livery_{spec['livery']}")
    w.write_int(0)
    w.write_string('ropp_emissive')
    w.write_int(0)
    w.write_string('ropp_disc')
    w.write_int(0)
    w.write_string('ropp_NRM')
    w.write_int(1)  # normal map

    # Close root transform
    w.write_int(1)

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(w.buf)


def render_propeller_icon(spec, meshes, main_rgba, tex_w, tex_h, img_w=256, img_h=256):
    """Render a 3/4 front-left view of the procedural propeller engine with blades & spinner."""
    fb = bytearray(img_w * img_h * 4)
    zbuf = [1e30] * (img_w * img_h)

    yaw = math.radians(136.0)
    pitch = math.radians(-20.0)
    cos_y, sin_y = math.cos(yaw), math.sin(yaw)
    cos_p, sin_p = math.cos(pitch), math.sin(pitch)

    def to_cam(pt):
        x, y, z = pt
        u = -z
        rx = x * cos_y + y * sin_y
        ry = -x * sin_y + y * cos_y
        cx = rx
        cy = u * cos_p - ry * sin_p
        cz = ry * cos_p + u * sin_p
        return (cx, cy, cz)

    def norm_to_cam(n):
        nx, ny, nz = n
        u = -nz
        rx = nx * cos_y + ny * sin_y
        ry = -nx * sin_y + ny * cos_y
        cx = rx
        cy = u * cos_p - ry * sin_p
        cz = ry * cos_p + u * sin_p
        return normalize3(cx, cy, cz)

    hub_y = meshes['hub_y']
    rear_y = meshes['rear_hub_y']

    def offset_mesh(m, dy):
        verts, uvs, norms, tangs, tris = m
        return ([(v[0], v[1] + dy, v[2]) for v in verts], uvs, norms, tangs, tris)

    draw_list = [
        meshes['cowl'],
        meshes['core'],
        meshes['exh'],
        meshes['flap'],
        offset_mesh(meshes['f_spin'], hub_y),
        offset_mesh(meshes['f_blades'], hub_y),
    ]
    if spec['contra']:
        draw_list.append(offset_mesh(meshes['r_spin'], rear_y))
        draw_list.append(offset_mesh(meshes['r_blades'], rear_y))

    all_verts = [v for m in draw_list for v in m[0]]
    cam_pts = [to_cam(v) for v in all_verts]
    min_x = min(p[0] for p in cam_pts)
    max_x = max(p[0] for p in cam_pts)
    min_y = min(p[1] for p in cam_pts)
    max_y = max(p[1] for p in cam_pts)
    span = max(max_x - min_x, max_y - min_y, 1e-3)
    scale = (0.86 * min(img_w, img_h)) / span
    mid_x = 0.5 * (min_x + max_x)
    mid_y = 0.5 * (min_y + max_y)

    light_dir = normalize3(-0.35, 0.65, -0.67)
    view_dir = (0.0, 0.0, -1.0)
    half_dir = normalize3(light_dir[0] + view_dir[0], light_dir[1] + view_dir[1], light_dir[2] + view_dir[2])

    for verts, uvs, norms, _, tris in draw_list:
        c_verts = [to_cam(v) for v in verts]
        c_norms = [norm_to_cam(n) for n in norms]
        s_verts = [
            (
                0.5 * img_w + (p[0] - mid_x) * scale,
                0.5 * img_h - (p[1] - mid_y) * scale,
                p[2],
            )
            for p in c_verts
        ]

        for t in range(0, len(tris), 3):
            i0, i1, i2 = tris[t], tris[t + 1], tris[t + 2]
            c0, c1, c2 = c_verts[i0], c_verts[i1], c_verts[i2]
            fn_cam_z = (c1[0] - c0[0]) * (c2[1] - c0[1]) - (c1[1] - c0[1]) * (c2[0] - c0[0])
            if fn_cam_z >= -1e-7:
                continue

            p0, p1, p2 = s_verts[i0], s_verts[i1], s_verts[i2]
            denom = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
            if abs(denom) < 1e-5:
                continue

            bx0 = max(0, int(math.floor(min(p0[0], p1[0], p2[0]))))
            bx1 = min(img_w - 1, int(math.ceil(max(p0[0], p1[0], p2[0]))))
            by0 = max(0, int(math.floor(min(p0[1], p1[1], p2[1]))))
            by1 = min(img_h - 1, int(math.ceil(max(p0[1], p1[1], p2[1]))))

            uv0, uv1, uv2 = uvs[i0], uvs[i1], uvs[i2]
            n0, n1, n2 = c_norms[i0], c_norms[i1], c_norms[i2]

            for py in range(by0, by1 + 1):
                sy = py + 0.5
                for px in range(bx0, bx1 + 1):
                    sx = px + 0.5
                    w0 = ((p1[1] - p2[1]) * (sx - p2[0]) + (p2[0] - p1[0]) * (sy - p2[1])) / denom
                    w1 = ((p2[1] - p0[1]) * (sx - p2[0]) + (p0[0] - p2[0]) * (sy - p2[1])) / denom
                    w2 = 1.0 - w0 - w1
                    if w0 >= -1e-4 and w1 >= -1e-4 and w2 >= -1e-4:
                        sz = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
                        pidx = py * img_w + px
                        if sz < zbuf[pidx]:
                            zbuf[pidx] = sz
                            u = max(0.0, min(1.0, w0 * uv0[0] + w1 * uv1[0] + w2 * uv2[0]))
                            v = max(0.0, min(1.0, w0 * uv0[1] + w1 * uv1[1] + w2 * uv2[1]))
                            tx = int(u * (tex_w - 1))
                            ty = int((1.0 - v) * (tex_h - 1))
                            tidx = (ty * tex_w + tx) * 4
                            tr = main_rgba[tidx]
                            tg = main_rgba[tidx + 1]
                            tb = main_rgba[tidx + 2]
                            spec_a = main_rgba[tidx + 3] / 255.0

                            nx, ny, nz = normalize3(
                                w0 * n0[0] + w1 * n1[0] + w2 * n2[0],
                                w0 * n0[1] + w1 * n1[1] + w2 * n2[1],
                                w0 * n0[2] + w1 * n1[2] + w2 * n2[2],
                            )
                            ndotl = max(0.0, nx * light_dir[0] + ny * light_dir[1] + nz * light_dir[2])
                            ndoth = max(0.0, nx * half_dir[0] + ny * half_dir[1] + nz * half_dir[2])
                            diff = 0.38 + 0.66 * ndotl
                            spec_pow = 24.0 if spec_a > 0.75 else 10.0
                            spec_hl = (ndoth ** spec_pow) * (spec_a * 0.72) * 255.0

                            fidx = pidx * 4
                            fb[fidx] = clamp_byte(tr * diff + spec_hl)
                            fb[fidx + 1] = clamp_byte(tg * diff + spec_hl)
                            fb[fidx + 2] = clamp_byte(tb * diff + spec_hl * 1.04)
                            fb[fidx + 3] = 255

    return bytes(fb)


PROPELLER_PART_SPECS = [
    # One procedural engine part. Its defaults mirror the cfg preset (R-2800-18W); the plugin
    # rebuilds the geometry at runtime, so this only shapes the editor icon and the prefab.
    {
        'id': 'proc_prop',
        'part_name': 'ROPlanes-ProcProp',
        'title': 'Procedural Propeller Engine (R-2800 default)',
        'arch': 'Radial',
        'contra': False,
        'cowl_dia': 1.34,
        'cowl_len': 1.55,
        'prop_dia': 4.01,
        'blades': 4,
        'blade_style': 'Paddle',
        'livery': 'usn',
    },
]

# Outputs of older layouts that must not ship any more
LEGACY_IDS = ['proc_prop_radial', 'proc_prop_vinline', 'proc_prop_turboprop', 'proc_prop_contra']
LEGACY_PART_NAMES = ['ROPlanes-ProcProp-Radial', 'ROPlanes-ProcProp-VInline',
                     'ROPlanes-ProcProp-Turboprop', 'ROPlanes-ProcProp-Contra']


def main():
    workspace_root = os.path.dirname(os.path.abspath(__file__))
    parts_root = os.path.join(workspace_root, 'GameData', 'ROPlanesPlus', 'Parts')
    shared_dir = os.path.join(parts_root, 'PropShared')
    thumbs_root = os.path.join(parts_root, '@thumbs')
    os.makedirs(shared_dir, exist_ok=True)
    os.makedirs(thumbs_root, exist_ok=True)

    print("Generating shared propeller textures (1024x1024)...")
    liveries, nrm_rgba, emis_rgba, ew, eh, kit_base, kit_mask = generate_texture_set(1024, 1024)
    for key in LIVERY_KEYS:
        write_png(os.path.join(shared_dir, f"ropp_livery_{key}.png"), 1024, 1024, liveries[key])
    write_png(os.path.join(shared_dir, 'ropp_NRM.png'), 1024, 1024, nrm_rgba)
    # Custom paint kit: PNG data with a .dat extension so KSP doesn't load it as a texture
    write_png(os.path.join(shared_dir, 'ropp_paintkit_base.dat'), 1024, 1024, kit_base)
    write_png(os.path.join(shared_dir, 'ropp_paintkit_mask.dat'), 1024, 1024, kit_mask)
    write_png(os.path.join(shared_dir, 'ropp_emissive.png'), ew, eh, emis_rgba)
    disc_rgba, dw, dh = generate_blur_disc_texture(512, 512)
    write_png(os.path.join(shared_dir, 'ropp_disc.png'), dw, dh, disc_rgba)
    print("Generating the damaged-blade texture (prop strikes)...")
    write_png(os.path.join(shared_dir, 'ropp_blades_damaged.png'), 1024, 1024, generate_damaged_blade_texture(1024, 1024))

    # Remove outputs of older layouts (per-part .mu/textures, per-type shared .mu, legacy icons)
    stale = []
    for lid in LEGACY_IDS:
        part_dir = os.path.join(parts_root, lid)
        stale += [os.path.join(part_dir, n) for n in ('model.mu', f"{lid}_main.png", f"{lid}_emissive.png", f"{lid}_disc.png")]
        stale.append(os.path.join(shared_dir, f"{lid}.mu"))
    stale += [os.path.join(thumbs_root, f"{n}_icon.png") for n in LEGACY_PART_NAMES]
    for sp in stale:
        if os.path.exists(sp):
            os.remove(sp)
            print(f"   removed stale {os.path.relpath(sp, workspace_root)}")

    cell_w, cell_h = 256, 256
    sheet_w, sheet_h = len(PROPELLER_PART_SPECS) * cell_w, cell_h
    sheet_buf = bytearray(sheet_w * sheet_h * 4)
    for i in range(0, len(sheet_buf), 4):
        sheet_buf[i:i + 4] = bytes((24, 28, 36, 255))

    for idx, spec in enumerate(PROPELLER_PART_SPECS):
        pid = spec['id']
        print(f"[{idx + 1}/{len(PROPELLER_PART_SPECS)}] {spec['part_name']}: {spec['title']}")
        meshes = build_propeller_part_meshes(spec)
        mu_path = os.path.join(shared_dir, f"{pid}.mu")
        write_propeller_mu(mu_path, spec, meshes)

        icon_rgba = render_propeller_icon(spec, meshes, liveries[spec['livery']], 1024, 1024, img_w=cell_w, img_h=cell_h)
        icon_path = os.path.join(thumbs_root, f"{spec['part_name']}_icon.png")
        write_png(icon_path, cell_w, cell_h, icon_rgba)

        for py in range(cell_h):
            for px in range(cell_w):
                s_idx = (py * cell_w + px) * 4
                if icon_rgba[s_idx + 3] > 0:
                    d_idx = (py * sheet_w + (idx * cell_w + px)) * 4
                    sheet_buf[d_idx:d_idx + 4] = icon_rgba[s_idx:s_idx + 4]
        print(f"   -> {os.path.relpath(mu_path, workspace_root)} ({os.path.getsize(mu_path):,} bytes)")

    preview_path = os.path.join(workspace_root, 'propellers_preview_sheet.png')
    write_png(preview_path, sheet_w, sheet_h, bytes(sheet_buf))
    print(f"Saved 3D propeller QA preview sheet to {preview_path}")


if __name__ == '__main__':
    main()
