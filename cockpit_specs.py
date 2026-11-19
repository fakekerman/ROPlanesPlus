#!/usr/bin/env python3
"""
Shared design data for the ROPlanes+ cockpits (pure Python, no Blender dependency).

Used by:
  blender/build_cockpits.py  - builds the models in Blender, bakes and paints the textures, writes .mu
  generate_configs.py        - writes the part .cfg files (nodes, B9PartSwitch variants and liveries)

Design coordinates (metres, Blender-style, right handed):
  y : forward. The REAR RING of every cockpit sits at y = 0 and is a true circle of a standard
      diameter (rear_dia), centred on the axis, so it mates with ordinary tanks and structures.
  z : up (canopy side).  x : starboard.
The part origin is placed at the pilot station (y = origin_y, on the axis). The exporter converts to
KSP part space: (x, y - origin_y, -z) with triangle winding reversed.

Fuselage cross sections are interpolated from keyframes K(y, w, ht, hb, ...):
  w  half width, ht height above the section centre, hb depth below it, zc centre height,
  nt / nb superellipse exponents of the upper / lower half (2 = ellipse, >2 boxier, <2 pointed),
  ch / cha optional lateral chine (extra half width, at angle cha degrees from the top).
A nose closure multiplies w/ht/hb by (1 - t^p)^q between nose_y0 and the tip.
Canopy bubbles are interpolated from C(y, wc, ztop, nc): half width at the sill, absolute top height
and shape exponent; the sill height is computed so the bubble always sinks into the fuselage.
"""

import math

# Standard mating diameters offered for rear rings and open fronts (RO tanks / structures)
STANDARD_DIAMETERS = (0.625, 0.9375, 1.25, 1.5, 1.875, 2.5, 3.0, 3.75)


def bulkhead_profile(dia):
    """KSP bulkhead profile name for a diameter."""
    table = ((0.70, 'size0'), (1.0, 'size0p5'), (1.30, 'size1'), (1.60, 'size1p2'), (2.0, 'size1p5'),
             (2.7, 'size2'), (3.2, 'size2p5'), (4.0, 'size3'))
    for limit, name in table:
        if dia <= limit:
            return name
    return 'size4'


def node_size(dia):
    if dia < 0.9:
        return 0
    if dia < 2.0:
        return 1
    if dia < 3.5:
        return 2
    return 3


# ----------------------------------------------------------------------------- keyframe helpers

def K(y, w, ht, hb=None, zc=0.0, nt=2.0, nb=None, ch=0.0, cha=90.0):
    return {'y': y, 'w': w, 'ht': ht, 'hb': ht if hb is None else hb, 'zc': zc,
            'nt': nt, 'nb': nt if nb is None else nb, 'ch': ch, 'cha': cha}


def C(y, wc, ztop, nc=2.4):
    return {'y': y, 'wc': wc, 'ztop': ztop, 'nc': nc}


def circle(y, r):
    return K(y, r, r, r)


def pchip(xs, ys):
    """Monotone cubic Hermite interpolant (Fritsch-Carlson). Returns f(x), clamped at the ends."""
    n = len(xs)
    if n == 1:
        return lambda x: ys[0]
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0] = d[0]
    m[-1] = d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0.0:
            m[i] = 0.0
        else:
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    if n > 2:
        # flat ends keep constant-section segments truly constant
        if abs(d[0]) < 1e-9:
            m[0] = 0.0
        if abs(d[-1]) < 1e-9:
            m[-1] = 0.0

    def f(x):
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        lo, hi = 0, n - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        t = (x - xs[lo]) / h[lo]
        t2, t3 = t * t, t * t * t
        return ((2 * t3 - 3 * t2 + 1) * ys[lo] + (t3 - 2 * t2 + t) * h[lo] * m[lo]
                + (-2 * t3 + 3 * t2) * ys[lo + 1] + (t3 - t2) * h[lo] * m[lo + 1])
    return f


class BodyProfile:
    """Fuselage loft: keyframed sections plus an optional nose closure."""

    FIELDS = ('w', 'ht', 'hb', 'zc', 'nt', 'nb', 'ch', 'cha')

    def __init__(self, keys, length, nose=None):
        keys = sorted(keys, key=lambda k: k['y'])
        self.keys = keys
        self.length = length
        self.nose = nose  # {'y0', 'p', 'q'} or None (blunt front ring)
        xs = [k['y'] for k in keys]
        self.f = {name: pchip(xs, [k[name] for k in keys]) for name in self.FIELDS}

    def closure(self, y):
        if not self.nose or y <= self.nose['y0']:
            return 1.0
        t = min(1.0, (y - self.nose['y0']) / (self.length - self.nose['y0']))
        p = self.nose.get('p', 2.0)
        q = self.nose.get('q', 0.5)
        return max(0.0, 1.0 - t ** p) ** q

    def section(self, y):
        s = {name: self.f[name](y) for name in self.FIELDS}
        c = self.closure(y)
        s['w'] *= c
        s['ht'] *= c
        s['hb'] *= c
        s['ch'] *= c
        return s

    def is_tip(self, y):
        return self.nose is not None and y >= self.length - 1e-6


def section_point(s, phi):
    """Point (x, z) on a section at angle phi (0 = top, +pi/2 = starboard, +-pi = bottom)."""
    sp, cp = math.sin(phi), math.cos(phi)
    if cp >= 0.0:
        n, hgt = s['nt'], s['ht']
    else:
        n, hgt = s['nb'], s['hb']
    e = 2.0 / max(0.5, n)
    x = s['w'] * math.copysign(abs(sp) ** e, sp)
    z = s['zc'] + hgt * math.copysign(abs(cp) ** e, cp)
    if s['ch'] > 1e-6:
        a = math.radians(s['cha'])
        x += math.copysign(s['ch'] * math.exp(-((abs(phi) - a) / 0.085) ** 2), sp)
    return x, z


def body_top_z_at(s, x):
    """Height of the upper fuselage surface at lateral offset x (clamped to the equator)."""
    w = max(1e-6, s['w'])
    if abs(x) >= w:
        return s['zc']
    sp = (abs(x) / w) ** (s['nt'] / 2.0)
    cp = math.sqrt(max(0.0, 1.0 - sp * sp))
    return s['zc'] + s['ht'] * cp ** (2.0 / max(0.5, s['nt']))


def phi_at_x(s, x):
    """Angle (0 = top) on the upper starboard half where the section reaches lateral offset x."""
    lo, hi = 0.0, math.pi / 2
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if section_point(s, mid)[0] < x:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def half_width_at_z(s, z):
    """Lateral half width of a section at height z (0 above the top / below the bottom)."""
    top = section_point(s, 0.0)[1]
    bot = section_point(s, math.pi)[1]
    if z >= top or z <= bot:
        return 0.0
    lo, hi = 0.0, math.pi
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if section_point(s, mid)[1] > z:
            lo = mid
        else:
            hi = mid
    return max(0.0, section_point(s, 0.5 * (lo + hi))[0])


class CanopyProfile:
    def __init__(self, keys, body):
        keys = sorted(keys, key=lambda k: k['y'])
        self.keys = keys
        self.body = body
        self.y0 = keys[0]['y']
        self.y1 = keys[-1]['y']
        xs = [k['y'] for k in keys]
        self.f = {name: pchip(xs, [k[name] for k in keys]) for name in ('wc', 'ztop', 'nc')}

    def section(self, y):
        wc = self.f['wc'](y)
        ztop = self.f['ztop'](y)
        nc = self.f['nc'](y)
        bs = self.body.section(y)
        zs = body_top_z_at(bs, wc) - 0.03
        return {'wc': wc, 'ztop': max(ztop, zs + 0.005), 'zs': zs, 'nc': nc}


def canopy_point(c, phi):
    """phi in [-pi/2, pi/2]: -pi/2 port sill, 0 top, +pi/2 starboard sill."""
    sp, cp = math.sin(phi), math.cos(phi)
    e = 2.0 / max(0.5, c['nc'])
    x = c['wc'] * math.copysign(abs(sp) ** e, sp)
    z = c['zs'] + (c['ztop'] - c['zs']) * max(0.0, cp) ** e
    return x, z


# ----------------------------------------------------------------------------- liveries
# Colours are sRGB hex. Pattern types: solid, camo (noise patches), splinter (angular patches),
# metal (natural aluminium with panel-to-panel variation). 'under' paints the lower surfaces with a
# soft wavy demarcation at 'split' (normal z). 'mottle' sprays small spots on the sides.

def L(key, title, top, under=None, pattern='solid', colors=None, split=-0.15, scale=1.0, mottle=None,
      antiglare=None, radome=None, frame=None, gloss=0.40, whitewash=False, belly=None, metal_frame=False,
      **extra):
    """extra: decals=[D(...)], lip (intake lip colour), lip_w, soot (exhaust stain strength, 0 = clean),
    fractions (colour shares for 'digital')."""
    lv = {'key': key, 'title': title, 'top': top, 'under': under, 'pattern': pattern,
          'colors': colors or [], 'split': split, 'scale': scale, 'mottle': mottle,
          'antiglare': antiglare, 'radome': radome, 'frame': frame, 'gloss': gloss,
          'whitewash': whitewash, 'belly': belly, 'metal_frame': metal_frame}
    lv.update(extra)
    return lv


def D(text, y, z, h, color, outline=None, side='both', outline_w=0.06, bold=1.0):
    """Painted marking projected sideways onto the fuselage: centre (y, z), height h (m, incl. 10 % margin)."""
    return {'text': text, 'y': y, 'z': z, 'h': h, 'color': color, 'outline': outline, 'side': side,
            'outline_w': outline_w, 'bold': bold}


# ----------------------------------------------------------------------------- the cockpits

COCKPITS = []

# --- Supermarine Spitfire ----------------------------------------------------------------------
R94 = 0.46875   # 0.9375 m ring radius (WWII single-seat fighters at their real ~0.9 m fuselage width)

# Spitfire Mk IX: the cockpit section runs from behind the razorback glazing to the firewall. Narrow,
# deep fuselage (0.92 m wide), Malcolm hood bulging over the sills, flat armoured windscreen, the
# fuel-tank decking ahead of it sloping down to the engine bearer ring.
_spit_body_hi = [
    circle(0.0, R94), circle(0.10, R94),
    K(0.45, 0.462, 0.545, 0.51, nt=1.7, nb=2.1),
    K(0.90, 0.458, 0.615, 0.54, nt=1.35, nb=2.1),     # razorback spine
    K(1.20, 0.458, 0.635, 0.555, nt=1.45, nb=2.1),
    K(1.40, 0.460, 0.53, 0.56, nt=2.8, nb=2.1),       # flat cockpit sills
    K(2.10, 0.462, 0.53, 0.56, nt=2.8, nb=2.1),
    K(2.48, 0.466, 0.535, 0.54, nt=2.2, nb=2.1),      # windscreen base
    K(3.05, R94, 0.49, 0.49, nt=2.0), circle(3.30, R94), circle(3.40, R94),
]
_spit_body_lo = [
    circle(0.0, R94), circle(0.10, R94),
    K(0.45, 0.462, 0.50, 0.51, nt=2.0, nb=2.1),
    K(0.90, 0.458, 0.515, 0.54, nt=2.3, nb=2.1),
    K(1.20, 0.458, 0.525, 0.555, nt=2.6, nb=2.1),
    K(1.40, 0.460, 0.53, 0.56, nt=2.8, nb=2.1),
    K(2.10, 0.462, 0.53, 0.56, nt=2.8, nb=2.1),
    K(2.48, 0.466, 0.535, 0.54, nt=2.2, nb=2.1),
    K(3.05, R94, 0.49, 0.49, nt=2.0), circle(3.30, R94), circle(3.40, R94),
]
_spit_windscreen = [C(2.16, 0.285, 0.845, 3.0), C(2.32, 0.25, 0.70, 3.6), C(2.48, 0.20, 0.555, 3.2)]
_spit_ws_frames = [('bow', 2.16, 0.050), ('rail', 34, 2.16, 2.45, 0.034), ('rail', -34, 2.16, 2.45, 0.034)]
COCKPITS.append({
    'id': 'spitfire', 'part_name': 'ROPlanes-Spitfire-Cockpit',
    'title': 'Supermarine Spitfire Cockpit',
    'length': 3.40, 'rear_dia': 0.9375, 'front_dia': 0.9375, 'origin_y': 1.75, 'tex': 2048,
    'body': _spit_body_hi, 'nose': None, 'segments': 72,
    'canopy': [C(1.06, 0.10, 0.665, 2.2), C(1.20, 0.20, 0.765, 2.4), C(1.35, 0.285, 0.85, 2.6),
               C(1.70, 0.31, 0.88, 2.8), C(2.06, 0.30, 0.87, 2.8)] + _spit_windscreen,
    'frames': _spit_ws_frames + [('bow', 1.36, 0.040), ('bow', 1.22, 0.034), ('rail', 0, 1.06, 1.28, 0.034),
                                 ('rail', 84, 1.36, 2.16, 0.03), ('rail', -84, 1.36, 2.16, 0.03)],
    'details': [('box', 2.18, 0.0, 0.875, 0.10, 0.05, 0.035, 'body')],  # rear-view mirror
    'pit': {'y0': 1.42, 'y1': 2.14, 'w': 0.24, 'floor': -0.40, 'seat_z': -0.07, 'panel_y': 2.16,
            'seat': 'ww2', 'sight': 'reflector', 'col': '#7D8A72', 'panel_col': '#1B1B1A',
            'seat_col': '#4A3324', 'accent': '#6E6750', 'dial_w': 0.22, 'dial_sp': 0.066},
    'exhaust': [(3.40, 0.13, 2.0, 0.10, 0.12)],
    'doors': [(1.48, 1.98, 0.08, 0.44, -1)],     # the port-side "crowbar" cockpit door
    'variants': [
        {'key': 'mk9', 'title': 'Mk IX (high back)', 'mass': 0.0, 'cost': 0,
         'desc': 'Razorback fuselage with the sliding Malcolm hood.',
         'extra': [('blade', 0.86, 0.10, 0.30, 'body')]},
        {'key': 'mk16', 'title': 'Mk XVI (low back, bubble canopy)', 'mass': 0.004, 'cost': 1,
         'desc': 'Cut-down rear fuselage with an all-round-vision bubble canopy.',
         'body': _spit_body_lo,
         'canopy': [C(0.62, 0.08, 0.535, 2.0), C(0.82, 0.19, 0.70, 2.2), C(1.08, 0.27, 0.83, 2.4),
                    C(1.40, 0.305, 0.88, 2.6), C(1.75, 0.315, 0.89, 2.7), C(2.06, 0.30, 0.875, 2.8)]
                   + _spit_windscreen,
         'frames': _spit_ws_frames + [('rail', 86, 1.06, 2.16, 0.03), ('rail', -86, 1.06, 2.16, 0.03)],
         'extra': [('blade', 0.45, 0.03, 0.34, 'body')]},
    ],
    'liveries': [
        L('raf', 'RAF Day Fighter', '#3F4A31', under='#8E9393', pattern='camo',
          colors=['#3F4A31', '#636A6B'], scale=1.0, split=-0.25, gloss=0.30),
        L('desert', 'Desert (Middle East)', '#A88C5E', under='#7393B8', pattern='camo',
          colors=['#A88C5E', '#5F4B33'], scale=1.0, split=-0.25, gloss=0.30),
        L('pru', 'Photo Recon Blue', '#4C6C86', gloss=0.35, soot=0.7),
    ],
    'glass': '#1E2629', 'glow': (0.70, 1.0, 0.62),
    'panel': {'frame_step': 0.40, 'stringers': 8, 'hatches': 3, 'rivets': True},
    'seats': [(0.0, 1.75)],
})

# --- Messerschmitt Bf 109 ----------------------------------------------------------------------
# G-6: angular, heavily framed hood and the "Beulen" gun-breech bulges on the cowling ahead of the
# windscreen; G-10/K-4: clear-view Erla hood and smaller, faired bulges. Narrow straight spine behind.
_109_ws = [C(2.18, 0.285, 0.855, 5.0), C(2.33, 0.255, 0.71, 4.5), C(2.50, 0.20, 0.56, 3.5)]
_109_ws_frames = [('bow', 2.18, 0.060), ('rail', 30, 2.18, 2.48, 0.040), ('rail', -30, 2.18, 2.48, 0.040)]
COCKPITS.append({
    'id': 'bf109', 'part_name': 'ROPlanes-Bf109-Cockpit',
    'title': 'Messerschmitt Bf 109 Cockpit',
    'length': 3.20, 'rear_dia': 0.9375, 'front_dia': 0.9375, 'origin_y': 1.65, 'tex': 2048,
    'body': [circle(0.0, R94), circle(0.10, R94),
             K(0.45, 0.458, 0.54, 0.51, nt=1.8, nb=2.1), K(1.05, 0.448, 0.60, 0.545, nt=1.6, nb=2.1),
             K(1.35, 0.450, 0.535, 0.555, nt=3.0, nb=2.1), K(2.15, 0.455, 0.535, 0.56, nt=3.0, nb=2.1),
             K(2.50, 0.460, 0.535, 0.545, nt=2.4, nb=2.1), K(3.00, R94, 0.49, 0.49, nt=2.0),
             circle(3.13, R94), circle(3.20, R94)],
    'nose': None, 'segments': 72,
    'canopy': [C(1.13, 0.14, 0.645, 2.8), C(1.25, 0.24, 0.75, 3.5), C(1.40, 0.28, 0.84, 4.5),
               C(1.80, 0.295, 0.87, 5.0)] + _109_ws,
    'frames': _109_ws_frames + [('bow', 1.40, 0.050), ('bow', 1.25, 0.040),
                                ('rail', 40, 1.40, 2.18, 0.036), ('rail', -40, 1.40, 2.18, 0.036),
                                ('rail', 72, 1.40, 2.18, 0.036), ('rail', -72, 1.40, 2.18, 0.036),
                                ('rail', 38, 1.15, 1.40, 0.034), ('rail', -38, 1.15, 1.40, 0.034)],
    'details': [('blade', 0.80, 0.08, 0.36, 'body')],                  # aerial mast
    'pit': {'y0': 1.43, 'y1': 2.15, 'w': 0.23, 'floor': -0.40, 'seat_z': -0.07, 'panel_y': 2.17,
            'seat': 'ww2', 'sight': 'reflector', 'col': '#3C3F40', 'panel_col': '#2A2C2D',
            'seat_col': '#34373A', 'accent': '#5E5847', 'dial_w': 0.21, 'dial_sp': 0.064},
    'exhaust': [(3.20, -0.08, 1.8, 0.10, 0.08)],
    'variants': [
        {'key': 'g6', 'title': 'G-6 (framed canopy)', 'mass': 0.0, 'cost': 0,
         'desc': 'Heavily framed hood with an armoured windscreen and the MG 131 "Beulen" bulges.',
         'extra': [('blister', 2.46, 3.12, 0.225, 0.105, 0.11, 'top', 'body', 'beule'),
                   ('blister', 2.46, 3.12, -0.225, 0.105, 0.11, 'top', 'body', 'beule')]},
        {'key': 'k4', 'title': 'G-10 / K-4 (Erla clear-view hood)', 'mass': -0.004, 'cost': 1,
         'desc': 'Clear-view Erla hood with far fewer frames and faired gun bulges.',
         'canopy': [C(1.13, 0.14, 0.645, 2.6), C(1.25, 0.24, 0.77, 3.0), C(1.40, 0.285, 0.86, 3.4),
                    C(1.80, 0.30, 0.89, 3.6), C(2.18, 0.285, 0.865, 4.2), C(2.33, 0.255, 0.71, 4.2),
                    C(2.50, 0.20, 0.56, 3.5)],
         'frames': _109_ws_frames + [('bow', 1.40, 0.050), ('rail', 86, 1.40, 2.18, 0.032),
                                     ('rail', -86, 1.40, 2.18, 0.032)],
         'extra': [('blister', 2.44, 3.14, 0.215, 0.085, 0.08, 'top', 'body', 'beule'),
                   ('blister', 2.44, 3.14, -0.215, 0.085, 0.08, 'top', 'body', 'beule')]},
    ],
    'liveries': [
        L('rlm74', 'RLM 74/75/76 Grey', '#3E4542', under='#A9B8C2', pattern='camo',
          colors=['#3E4542', '#5C5D66'], scale=0.9, split=0.30, mottle='#4A504C', gloss=0.28),
        L('trop', 'RLM 79/78 Tropical', '#B08A58', under='#8FAAC4', split=0.10, mottle='#6F6A3F', gloss=0.28),
        L('winter', 'Winter Whitewash', '#3E4542', under='#A9B8C2', pattern='camo',
          colors=['#3E4542', '#5C5D66'], scale=0.9, split=0.30, mottle='#4A504C', whitewash=True, gloss=0.22),
    ],
    'glass': '#1E2629', 'glow': (0.70, 1.0, 0.62),
    'panel': {'frame_step': 0.40, 'stringers': 8, 'hatches': 3, 'rivets': True},
    'seats': [(0.0, 1.65)],
})

# --- Messerschmitt Me 262 ----------------------------------------------------------------------
COCKPITS.append({
    'id': 'me262', 'part_name': 'ROPlanes-Me262-Cockpit',
    'title': 'Messerschmitt Me 262 Schwalbe Cockpit',
    'length': 4.70, 'rear_dia': 1.25, 'origin_y': 1.85, 'tex': 2048, 'split_y': 2.95,
    # triangular "shark" section: wide flat belly, sloping sides, narrow rounded spine
    'body': [circle(0.0, 0.625), circle(0.12, 0.625),
             K(0.50, 0.640, 0.74, 0.56, zc=-0.07, nt=1.6, nb=3.0),
             K(1.10, 0.660, 0.83, 0.50, zc=-0.15, nt=1.45, nb=3.6),
             K(1.80, 0.660, 0.84, 0.48, zc=-0.17, nt=1.45, nb=3.8),
             K(2.50, 0.640, 0.79, 0.46, zc=-0.17, nt=1.5, nb=3.6),
             K(2.95, 0.600, 0.73, 0.44, zc=-0.16, nt=1.55, nb=3.4),
             K(3.60, 0.520, 0.62, 0.40, zc=-0.14, nt=1.65, nb=3.0),
             K(4.20, 0.440, 0.50, 0.34, zc=-0.11, nt=1.8, nb=2.6),
             K(4.70, 0.380, 0.42, 0.30, zc=-0.09, nt=1.9, nb=2.3)],
    'nose': {'y0': 3.85, 'p': 2.0, 'q': 0.5}, 'segments': 80,
    'canopy': [C(0.95, 0.12, 0.72, 2.0), C(1.12, 0.25, 0.86, 2.3), C(1.45, 0.315, 0.96, 2.5),
               C(1.95, 0.325, 0.985, 2.5), C(2.30, 0.31, 0.95, 2.6), C(2.45, 0.285, 0.90, 2.9),
               C(2.62, 0.24, 0.76, 3.3), C(2.82, 0.16, 0.60, 2.8)],
    'frames': [('bow', 2.45, 0.05), ('rail', 38, 2.45, 2.79, 0.035), ('rail', -38, 2.45, 2.79, 0.035),
               ('bow', 1.55, 0.045), ('bow', 1.22, 0.04), ('rail', 0, 0.95, 1.22, 0.035),
               ('rail', 84, 1.55, 2.45, 0.03), ('rail', -84, 1.55, 2.45, 0.03)],
    'details': [('blade', 0.80, 0.10, 0.20, 'body')],
    'pit': {'y0': 1.60, 'y1': 2.40, 'w': 0.25, 'floor': -0.36, 'seat_z': 0.05, 'panel_y': 2.43,
            'seat': 'ww2', 'sight': 'reflector', 'col': '#3C3F40', 'panel_col': '#2A2C2D',
            'seat_col': '#34373A', 'accent': '#5E5847', 'dial_w': 0.24, 'dial_sp': 0.066},
    'gunports': [(4.28, 22, 0.035, 'nose'), (4.28, -22, 0.035, 'nose'), (4.36, 44, 0.035, 'nose'),
                 (4.36, -44, 0.035, 'nose')],
    'radome_y': None,
    'variants': [
        {'key': 'nose', 'title': 'A-1a cannon nose', 'nose': 'native', 'mass': 0.06, 'cost': 2,
         'desc': 'Nose bay with the ports of four MK 108 cannon.'},
        {'key': 'open', 'title': 'Open front (0.9375 m)', 'nose': 'adapter', 'front_dia': 0.9375,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 0.9375 m ring for your own nose or intake.'},
    ],
    'liveries': [
        L('rlm81', 'RLM 81/82 over 76', '#574A3B', under='#A9B8BE', pattern='camo',
          colors=['#574A3B', '#5D6C48'], scale=1.1, split=0.05, mottle='#5D6C48', gloss=0.28),
        L('rlm74', 'RLM 74/75 over 76', '#3E4542', under='#A9B8C2', pattern='camo',
          colors=['#3E4542', '#5C5D66'], scale=1.2, split=0.05, mottle='#4A504C', gloss=0.30),
        L('metal', 'Bare Metal (late war)', '#B9BCBC', pattern='metal', antiglare='#2E3326', gloss=0.55),
    ],
    'glass': '#1E2629', 'glow': (0.70, 1.0, 0.62),
    'panel': {'frame_step': 0.45, 'stringers': 8, 'hatches': 4, 'rivets': True},
    'seats': [(0.0, 1.85)],
})

# --- Mikoyan-Gurevich MiG-15 -------------------------------------------------------------------
COCKPITS.append({
    'id': 'mig15', 'part_name': 'ROPlanes-MiG15-Cockpit',
    'title': 'Mikoyan-Gurevich MiG-15bis Cockpit',
    # long round nose (about 2 m from the windscreen to the intake lip), teardrop canopy high on the
    # barrel, gun tray fairings under the nose
    'length': 4.85, 'rear_dia': 1.5, 'origin_y': 2.05, 'tex': 2048, 'split_y': 4.10,
    'body': [circle(0.0, 0.75), circle(0.12, 0.75),
             K(0.60, 0.745, 0.80, 0.745, nt=1.9), K(1.20, 0.735, 0.82, 0.74, nt=1.85),
             K(1.80, 0.72, 0.79, 0.73, nt=2.0), K(2.50, 0.70, 0.75, 0.71, nt=2.0),
             K(3.00, 0.67, 0.70, 0.68), K(3.60, 0.61, 0.625, 0.61), K(4.10, 0.555, 0.565, 0.555),
             K(4.55, 0.50, 0.505, 0.50), K(4.82, 0.475, 0.48, 0.475)],
    'nose': None, 'segments': 72,
    'intake': {'y_lip': 4.82, 'r_out': 0.475, 'r_in': 0.385, 'depth': 0.65, 'splitter': True},
    'canopy': [C(1.22, 0.12, 0.86, 2.0), C(1.42, 0.26, 1.02, 2.2), C(1.80, 0.325, 1.12, 2.4),
               C(2.25, 0.33, 1.13, 2.4), C(2.52, 0.31, 1.09, 2.5), C(2.68, 0.27, 0.99, 2.8),
               C(2.88, 0.18, 0.80, 2.6)],
    'frames': [('bow', 2.53, 0.05), ('rail', 40, 2.53, 2.85, 0.035), ('rail', -40, 2.53, 2.85, 0.035),
               ('bow', 1.48, 0.045), ('rail', 86, 1.48, 2.53, 0.03), ('rail', -86, 1.48, 2.53, 0.03)],
    'details': [('blade', 1.00, 0.20, 0.28, 'body'),
                ('blister', 2.70, 3.95, 0.34, 0.12, 0.10, 'bottom', 'body', 'gun'),     # N-37D
                ('blister', 2.80, 3.85, -0.32, 0.10, 0.085, 'bottom', 'body', 'gun')],  # 2x NR-23
    'pit': {'y0': 1.55, 'y1': 2.50, 'w': 0.26, 'floor': -0.36, 'seat_z': 0.04, 'panel_y': 2.53,
            'seat': 'ejection', 'recline': 10, 'headbox': 0.07, 'sight': 'reflector', 'col': '#6E7B74',
            'panel_col': '#202122', 'seat_col': '#3B3F3A', 'dial_w': 0.26},
    'gunports': [],
    'radome_y': None,
    'variants': [
        {'key': 'intake', 'title': 'Nose intake', 'nose': 'native', 'mass': 0.03, 'cost': 1,
         'desc': 'The real nose: round intake lip with the splitter that feeds the ducts around the cockpit.'},
        {'key': 'open', 'title': 'Open front (0.9375 m)', 'nose': 'adapter', 'front_dia': 0.9375,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 0.9375 m ring for your own intake or nose.'},
    ],
    'liveries': [
        L('metal', 'Natural Metal', '#BFC2C3', pattern='metal', antiglare='#3B3F2F', gloss=0.60,
          lip='#B3261E', lip_w=0.24),
        L('grey', 'Air Superiority Grey', '#8E959A', under='#A7AEB2', split=-0.3, gloss=0.40,
          lip='#B3261E', lip_w=0.18),
        L('pact', 'Warsaw Pact Camouflage', '#58603E', under='#9DB6C8', pattern='camo',
          colors=['#58603E', '#7A6646', '#3E4A30'], scale=1.2, gloss=0.32),
    ],
    'glass': '#1E2629', 'glow': (1.0, 0.82, 0.50),
    'panel': {'frame_step': 0.50, 'stringers': 8, 'hatches': 4, 'rivets': True},
    'seats': [(0.0, 2.05)],
})

# --- Lockheed F-104 Starfighter ----------------------------------------------------------------
COCKPITS.append({
    'id': 'f104', 'part_name': 'ROPlanes-F104-Cockpit',
    'title': 'Lockheed F-104G Starfighter Cockpit',
    'length': 6.60, 'rear_dia': 1.5, 'origin_y': 2.45, 'tex': 2048, 'split_y': 4.10,
    'body': [circle(0.0, 0.75), circle(0.12, 0.75),
             K(0.60, 0.72, 0.80, 0.72, nt=1.85), K(1.30, 0.69, 0.80, 0.70, nt=1.8),
             K(1.90, 0.66, 0.70, 0.68), K(2.60, 0.63, 0.66, 0.65), K(3.40, 0.59, 0.60, 0.61),
             K(4.10, 0.55, 0.55, 0.56), K(5.00, 0.50, 0.50, 0.51), K(6.60, 0.46, 0.46, 0.46)],
    'nose': {'y0': 4.10, 'p': 1.25, 'q': 1.0}, 'segments': 72,
    'canopy': [C(1.45, 0.14, 0.78, 2.0), C(1.72, 0.25, 0.98, 2.4), C(2.25, 0.295, 1.07, 2.6),
               C(2.90, 0.285, 1.05, 2.6), C(3.20, 0.255, 0.97, 2.8), C(3.45, 0.20, 0.82, 3.0),
               C(3.72, 0.13, 0.62, 2.6)],
    'frames': [('bow', 3.18, 0.05), ('bow', 2.55, 0.05), ('bow', 1.76, 0.05),
               ('rail', 36, 3.18, 3.62, 0.035), ('rail', -36, 3.18, 3.62, 0.035),
               ('rail', 86, 1.76, 3.18, 0.03), ('rail', -86, 1.76, 3.18, 0.03)],
    'details': [('pitot', 6.58, 8.20, 0.040, 0.016, 'nose'), ('blade', 0.80, 0.16, 0.22, 'body')],
    'pit': {'y0': 1.92, 'y1': 3.14, 'w': 0.21, 'floor': -0.40, 'seat_z': 0.04, 'panel_y': 3.17,
            'seat': 'ejection', 'recline': 12, 'headbox': 0.08, 'sight': 'reflector', 'col': '#5D6367',
            'panel_col': '#18191A', 'seat_col': '#3F4538', 'dial_w': 0.22},
    'gunports': [],
    'radome_y': 4.12,
    'variants': [
        {'key': 'nose', 'title': 'Radome and pitot boom', 'nose': 'native', 'mass': 0.12, 'cost': 3,
         'desc': 'Long needle radome (NASARR radar) with the pitot boom.'},
        {'key': 'open', 'title': 'Open front (0.9375 m)', 'nose': 'adapter', 'front_dia': 0.9375,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 0.9375 m ring for your own nose cone.'},
    ],
    'liveries': [
        L('metal', 'Natural Metal', '#C0C3C4', pattern='metal', antiglare='#202326', radome='#2A2C2E', gloss=0.60),
        L('nato', 'NATO Green/Grey', '#4C5A3E', under='#B9BDBD', pattern='camo',
          colors=['#4C5A3E', '#5D6466'], scale=1.6, split=-0.2, antiglare='#202326', radome='#3A3C3E', gloss=0.35),
        L('gull', 'Gull Grey', '#9DA2A3', under='#E7E7E2', split=-0.35, antiglare='#202326', radome='#E7E7E2', gloss=0.45),
    ],
    'glass': '#1E2629', 'glow': (1.0, 0.85, 0.58),
    'panel': {'frame_step': 0.50, 'stringers': 10, 'hatches': 6, 'rivets': False},
    'seats': [(0.0, 2.45)],
})

# --- McDonnell Douglas F-4 Phantom II ----------------------------------------------------------
_f4_body = [circle(0.0, 0.9375), circle(0.12, 0.9375),
            K(0.70, 0.860, 0.95, 0.90, nt=1.7, nb=2.2), K(1.60, 0.740, 0.92, 0.88, nt=1.6, nb=2.4),
            K(2.40, 0.680, 0.78, 0.86, nt=2.0, nb=2.5), K(3.60, 0.660, 0.74, 0.84, nt=2.1, nb=2.5),
            K(4.80, 0.640, 0.70, 0.80, nt=2.1, nb=2.4), K(5.50, 0.600, 0.62, 0.74, nt=2.1, nb=2.3),
            K(6.60, 0.520, 0.52, 0.62, zc=0.02), K(7.60, 0.470, 0.45, 0.53, zc=0.02),
            K(9.20, 0.420, 0.40, 0.46, zc=0.02)]
COCKPITS.append({
    'id': 'f4', 'part_name': 'ROPlanes-F4-Cockpit',
    'title': 'McDonnell Douglas F-4 Phantom II Cockpit',
    'length': 8.90, 'rear_dia': 1.875, 'origin_y': 3.40, 'tex': 2048, 'split_y': 5.50,
    'body': _f4_body,
    'nose': {'y0': 6.30, 'p': 1.7, 'q': 1.0}, 'segments': 80,
    'canopy': [C(1.65, 0.18, 0.90, 2.0), C(1.95, 0.30, 1.13, 2.4), C(2.40, 0.36, 1.23, 2.6),
               C(3.00, 0.36, 1.22, 2.6), C(3.40, 0.35, 1.18, 2.6), C(3.80, 0.36, 1.22, 2.6),
               C(4.40, 0.36, 1.21, 2.6), C(4.80, 0.33, 1.13, 2.8), C(5.10, 0.26, 0.90, 3.0),
               C(5.38, 0.15, 0.60, 2.5)],
    'frames': [('bow', 4.82, 0.055), ('bow', 3.55, 0.05), ('bow', 3.33, 0.09), ('bow', 2.05, 0.05),
               ('rail', 38, 4.82, 5.30, 0.04), ('rail', -38, 4.82, 5.30, 0.04),
               ('rail', 86, 2.05, 4.82, 0.03), ('rail', -86, 2.05, 4.82, 0.03)],
    'details': [('blade', 0.80, 0.14, 0.20, 'body')],
    'pit': {'y0': 2.15, 'y1': 4.78, 'w': 0.27, 'floor': -0.34, 'seat_z': 0.18,
            'panels': [(4.81, None), (3.40, None)], 'seat': 'ejection', 'recline': 14, 'sight': 'reflector',
            'col': '#5A5F63', 'panel_col': '#1B1C1D', 'seat_col': '#4A4F3A', 'dial_w': 0.30},
    'slime': [(3.95, 4.55, -0.20)],
    'gunports': [],
    'radome_y': 6.05,
    'variants': [
        {'key': 'e', 'title': 'F-4E gun nose', 'nose': 'native', 'mass': 0.30, 'cost': 4,
         'desc': 'Short radome (APQ-120) with the M61 gun fairing under the nose.',
         'length': 8.90, 'nose_y0': 6.30,
         'extra': [('blister', 5.70, 8.55, 0.0, 0.17, 0.15, 'bottom', 'body', 'gun')]},
        {'key': 'j', 'title': 'F-4J radar nose', 'nose': 'native', 'mass': 0.22, 'cost': 3,
         'desc': 'Long Navy radome (AWG-10) without the gun.', 'length': 9.20, 'nose_y0': 6.30},
        {'key': 'open', 'title': 'Open front (0.9375 m)', 'nose': 'adapter', 'front_dia': 0.9375,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 0.9375 m ring for your own nose cone.'},
    ],
    'liveries': [
        L('sea', 'Southeast Asia Camouflage', '#9C8858', under='#C9C9C2', pattern='camo',
          colors=['#9C8858', '#4E5A38', '#3B4232'], scale=1.3, split=-0.30, radome='#2B2D2B', gloss=0.30),
        L('hill', 'Hill Grey II', '#6A7277', under='#8E959A', pattern='camo',
          colors=['#6A7277', '#8E959A'], scale=1.6, split=-0.5, radome='#5E6569', antiglare='#3F4447', gloss=0.35),
        L('navy', 'Navy Gull Grey / White', '#9DA2A3', under='#ECECE7', split=-0.25,
          radome='#2B2D2B', antiglare='#2B2D2B', gloss=0.45),
        L('euro1', 'European One (wrap-around)', '#3D463A', pattern='camo',
          colors=['#3D463A', '#4D5559', '#454C47'], scale=1.4, radome='#3A3F3D', gloss=0.30),
    ],
    'glass': '#1E2629', 'glow': (0.95, 0.88, 0.62),
    'panel': {'frame_step': 0.55, 'stringers': 10, 'hatches': 8, 'rivets': False},
    'seats': [(0.0, 4.10), (0.0, 2.70)],
})

# --- Sukhoi Su-27 Flanker -----------------------------------------------------------------------
COCKPITS.append({
    'id': 'su27', 'part_name': 'ROPlanes-Su27-Cockpit',
    'title': 'Sukhoi Su-27S Flanker Cockpit',
    'length': 7.85, 'rear_dia': 1.875, 'origin_y': 3.30, 'tex': 2048, 'split_y': 5.10,
    'body': [circle(0.0, 0.9375), circle(0.12, 0.9375),
             K(0.80, 0.880, 1.05, 0.90, nt=1.6, nb=2.1), K(1.60, 0.780, 1.00, 0.86, nt=1.6, nb=2.2),
             K(2.30, 0.720, 0.80, 0.84, nt=2.0, nb=2.3, ch=0.03, cha=95),
             K(3.40, 0.690, 0.74, 0.82, nt=2.0, nb=2.3, ch=0.04, cha=95),
             K(4.50, 0.660, 0.69, 0.79, zc=-0.04, nt=2.0, nb=2.2, ch=0.045, cha=95),
             K(5.10, 0.640, 0.64, 0.74, zc=-0.08, ch=0.04, cha=95),
             K(6.20, 0.560, 0.55, 0.62, zc=-0.16, ch=0.02, cha=95),
             K(7.85, 0.470, 0.46, 0.52, zc=-0.28)],
    'nose': {'y0': 5.10, 'p': 1.75, 'q': 1.0}, 'segments': 96,
    'canopy': [C(1.90, 0.22, 0.96, 2.0), C(2.15, 0.33, 1.16, 2.3), C(2.70, 0.40, 1.27, 2.4),
               C(3.40, 0.40, 1.28, 2.4), C(3.90, 0.37, 1.22, 2.5), C(4.20, 0.33, 1.12, 2.6),
               C(4.50, 0.25, 0.92, 2.7), C(4.80, 0.14, 0.56, 2.5)],
    'frames': [('bow', 4.20, 0.055), ('bow', 2.12, 0.06), ('rail', 40, 4.20, 4.74, 0.04),
               ('rail', -40, 4.20, 4.74, 0.04)],
    'details': [('ball', 4.92, 0.13, 0.11, 'dome'), ('pitot', 7.83, 8.75, 0.035, 0.015, 'nose'),
                ('blade', 0.70, 0.12, 0.22, 'body')],
    'pit': {'y0': 2.25, 'y1': 4.15, 'w': 0.30, 'floor': -0.26, 'seat_z': 0.25, 'panel_y': 4.18,
            'seat': 'ejection', 'recline': 16, 'sight': 'hud', 'col': '#3E9C9A', 'panel_col': '#2F7F7D',
            'seat_col': '#4F5A52', 'dial_w': 0.30},
    'gunports': [],
    'radome_y': 5.12,
    'variants': [
        {'key': 'nose', 'title': 'Radome and pitot', 'nose': 'native', 'mass': 0.28, 'cost': 4,
         'desc': 'Drooped radome (N001 radar) with the nose pitot.'},
        {'key': 'open', 'title': 'Open front (1.25 m)', 'nose': 'adapter', 'front_dia': 1.25,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 1.25 m ring for your own nose cone.'},
    ],
    'liveries': [
        L('flanker', 'Flanker Blue-Grey', '#9FB1C1', under='#B8C7D2', pattern='camo',
          colors=['#9FB1C1', '#6E8697', '#3E5568'], scale=1.2, split=-0.45, radome='#D9DCD8', gloss=0.35),
        L('navy', 'Navy Grey', '#7D878F', under='#A3ACB2', split=-0.30, radome='#D9DCD8', gloss=0.40),
        L('modern', 'Modern Dark Grey', '#55606A', under='#6E7A84', split=-0.30, radome='#4A535B', gloss=0.35),
        L('ukraine', 'Ukrainian Digital', '#A9B9C6', under='#C3CFD8', pattern='digital',
          colors=['#C9D3DB', '#94B4D0', '#5F8AB2', '#3D5F86'], fractions=[0.30, 0.62, 0.86], scale=1.0,
          split=-0.65, radome='#C9CDD0', gloss=0.30),
    ],
    'glass': '#1E2629', 'glow': (0.55, 0.95, 0.85),
    'panel': {'frame_step': 0.55, 'stringers': 10, 'hatches': 8, 'rivets': False},
    'seats': [(0.0, 3.30)],
})

# --- General Dynamics F-16 ----------------------------------------------------------------------
COCKPITS.append({
    'id': 'f16', 'part_name': 'ROPlanes-F16-Cockpit',
    'title': 'General Dynamics F-16C Fighting Falcon Cockpit',
    'length': 6.95, 'rear_dia': 1.5, 'origin_y': 3.00, 'tex': 2048, 'split_y': 4.85,
    'body': [circle(0.0, 0.75), circle(0.12, 0.75),
             K(0.70, 0.745, 0.84, 0.745, nt=1.7), K(1.50, 0.720, 0.78, 0.735, nt=1.8, ch=0.03, cha=100),
             K(2.30, 0.690, 0.62, 0.740, nt=2.2, nb=2.4, ch=0.06, cha=100),
             K(3.40, 0.650, 0.56, 0.720, nt=2.2, nb=2.4, ch=0.08, cha=100),
             K(4.30, 0.580, 0.52, 0.660, zc=-0.02, nt=2.1, nb=2.3, ch=0.07, cha=100),
             K(4.85, 0.530, 0.49, 0.62, zc=-0.05, ch=0.06, cha=100),
             K(5.70, 0.470, 0.44, 0.54, zc=-0.10, ch=0.04, cha=100),
             K(6.95, 0.420, 0.40, 0.47, zc=-0.18, ch=0.02, cha=100)],
    'nose': {'y0': 4.85, 'p': 1.9, 'q': 1.0}, 'segments': 96,
    'canopy': [C(1.55, 0.20, 0.80, 2.0), C(1.80, 0.32, 1.02, 2.2), C(2.40, 0.40, 1.18, 2.3),
               C(3.10, 0.40, 1.19, 2.3), C(3.60, 0.37, 1.12, 2.35), C(4.00, 0.31, 0.98, 2.4),
               C(4.35, 0.22, 0.78, 2.4), C(4.66, 0.10, 0.42, 2.2)],
    'frames': [('bow', 1.97, 0.10), ('rail', 88, 1.97, 4.55, 0.03), ('rail', -88, 1.97, 4.55, 0.03)],
    'details': [('pitot', 6.93, 7.55, 0.030, 0.014, 'nose'), ('blade', 0.85, 0.12, 0.20, 'body')],
    'pit': {'y0': 2.12, 'y1': 3.90, 'w': 0.27, 'floor': -0.34, 'seat_z': 0.10, 'panel_y': 3.93,
            'seat': 'ejection', 'recline': 30, 'stick': 'side', 'sight': 'hud', 'col': '#5D6266',
            'panel_col': '#1B1C1E', 'seat_col': '#4B5040', 'dial_w': 0.26},
    'glass_alpha': (0.36, 0.56),
    'slime': [(3.35, 3.95, -0.05)],
    'gunports': [],
    'radome_y': 4.87,
    'variants': [
        {'key': 'nose', 'title': 'Radome and pitot', 'nose': 'native', 'mass': 0.18, 'cost': 4,
         'desc': 'Radome (APG-68 radar) with the nose pitot.'},
        {'key': 'open', 'title': 'Open front (0.9375 m)', 'nose': 'adapter', 'front_dia': 0.9375,
         'mass': 0.0, 'cost': 0, 'desc': 'Ends in a round 0.9375 m ring for your own nose cone.'},
    ],
    'liveries': [
        L('grey', 'Two-Tone Grey', '#7A8287', under='#A9B0B5', pattern='camo',
          colors=['#6F777D', '#8C949A'], scale=1.5, split=-0.40, radome='#8C949A', gloss=0.35),
        L('desert', 'Aggressor Desert', '#B49465', under='#C9B48E', pattern='camo',
          colors=['#B49465', '#8E6B44', '#6E5A3F'], scale=1.2, split=-0.45, radome='#B49465', gloss=0.30),
        L('blue', 'Aggressor Blue', '#4E6A86', under='#A8B8C6', pattern='camo',
          colors=['#4E6A86', '#8EA3B4', '#324A62'], scale=1.2, split=-0.45, radome='#8EA3B4', gloss=0.32),
    ],
    'glass': '#6E5A24', 'glow': (0.48, 1.0, 0.68),
    'panel': {'frame_step': 0.55, 'stringers': 10, 'hatches': 8, 'rivets': False},
    'seats': [(0.0, 3.00)],
})

# --- Boeing B-29 Superfortress ------------------------------------------------------------------
_b29_glazing = {'y0': 4.38, 'y1': 6.40, 'phi': 155,
                'frames_y': [4.40, 5.08, 5.66, 6.10],
                'frames_phi': [0, 26, -26, 54, -54, 84, -84, 116, -116, 150, -150],
                'frame_y_stop': 6.10, 'frame_w': 0.06}
COCKPITS.append({
    'id': 'b29', 'part_name': 'ROPlanes-B29-Cockpit',
    'title': 'Boeing B-29 Superfortress Cockpit',
    'length': 6.40, 'rear_dia': 3.0, 'origin_y': 5.00, 'tex': 2048, 'split_y': 4.30,
    'body': [circle(0.0, 1.5), circle(0.12, 1.5), K(2.0, 1.49, 1.49, 1.49), K(4.30, 1.46, 1.46, 1.47),
             K(6.40, 1.42, 1.42, 1.43)],
    'nose': {'y0': 4.30, 'p': 2.0, 'q': 0.5}, 'segments': 96,
    'canopy': None, 'frames': [],
    'details': [('ball', 3.60, 0.0, 0.28, 'glass_top'),
                ('turret', 2.40, 'top', 0.46), ('turret', 2.20, 'bottom', 0.46)],
    # glazed nose: pilots side by side, bombardier ahead of them in the greenhouse
    'pit': {'y0': 4.0, 'y1': 6.4, 'ly0': 3.95, 'ly1': 6.40, 'floor': -0.48,
            'panels': [(5.50, -0.02)], 'panel_w': 1.05, 'hood': 0.16, 'seat': 'bomber', 'stick': 'yoke',
            'seats': [(-0.52, 5.02, -0.08), (0.52, 5.02, -0.08), (0.0, 5.92, -0.14, {'stick': None})],
            'col': '#76845F', 'panel_col': '#1C1D1C', 'seat_col': '#5A5040', 'accent': '#6A5238',
            'dial_w': 0.95, 'dial_sp': 0.08, 'consoles': False},
    'gunports': [],
    'radome_y': None,
    'variants': [
        {'key': 'glazed', 'title': 'Glazed nose', 'nose': 'native', 'mass': 0.0, 'cost': 0,
         'desc': 'The famous greenhouse nose for the pilots and the bombardier.', 'glazing': [_b29_glazing]},
        {'key': 'solid', 'title': 'Solid nose (crew windows only)', 'nose': 'native', 'mass': 0.05, 'cost': 1,
         'desc': 'Metal nose with side windows for the pilots, for transport and tanker conversions.',
         'glazing': [{'y0': 5.00, 'y1': 5.80, 'phi_lo': 25, 'phi_hi': 78, 'frames_y': [5.0, 5.4, 5.8],
                      'frames_phi': [25, 51, 78], 'frame_y_stop': 5.8, 'frame_w': 0.06, 'sides': True}]},
    ],
    'liveries': [
        L('metal', 'Natural Metal', '#C3C6C7', pattern='metal', antiglare='#3D4229', gloss=0.65),
        L('od', 'Olive Drab / Neutral Grey', '#4B5320', under='#8A8D8F', split=-0.15, gloss=0.30),
        L('night', 'Korean War Night Black', '#C3C6C7', pattern='metal', belly='#16181A', split=0.05,
          antiglare='#3D4229', gloss=0.55),
    ],
    'glass': '#1E2629', 'glass_alpha': (0.14, 0.34), 'glow': (1.0, 0.86, 0.60),
    'panel': {'frame_step': 0.55, 'stringers': 16, 'hatches': 6, 'rivets': True},
    'seats': [(-0.45, 5.35), (0.45, 5.35)],
})

# --- Boeing B-52 Stratofortress -----------------------------------------------------------------
COCKPITS.append({
    'id': 'b52', 'part_name': 'ROPlanes-B52-Cockpit',
    'title': 'Boeing B-52 Stratofortress Cockpit',
    'length': 10.50, 'rear_dia': 3.0, 'origin_y': 6.90, 'tex': 2048,
    'body': [circle(0.0, 1.5), circle(0.12, 1.5),
             K(1.50, 1.450, 1.70, 1.55, nt=1.9, nb=2.3), K(3.50, 1.400, 1.82, 1.60, nt=2.0, nb=2.4),
             K(5.50, 1.380, 1.86, 1.60, nt=2.1, nb=2.4), K(6.40, 1.360, 1.86, 1.60, nt=2.2, nb=2.4),
             K(7.00, 1.320, 1.60, 1.58, zc=-0.06, nt=2.3, nb=2.4),
             K(7.50, 1.260, 1.18, 1.54, zc=-0.18, nt=2.2, nb=2.4),
             K(8.40, 1.140, 0.98, 1.40, zc=-0.32, nt=2.1, nb=2.3),
             K(9.40, 1.000, 0.86, 1.22, zc=-0.46), K(10.50, 0.860, 0.76, 1.02, zc=-0.60)],
    'nose': {'y0': 9.10, 'p': 2.0, 'q': 0.55}, 'segments': 112,
    'canopy': None, 'frames': [],
    # six-pane windscreen on the step, two side windows and the eyebrow windows on each side
    'glazing': [{'y0': 7.02, 'y1': 7.50, 'phi': 62, 'frames_y': [7.04, 7.48],
                 'frames_phi': [0, 21, -21, 42, -42, 62, -62], 'frame_y_stop': 7.50, 'frame_w': 0.08},
                {'y0': 6.34, 'y1': 6.98, 'sides': True, 'phi_lo': 52, 'phi_hi': 80,
                 'frames_y': [6.36, 6.66, 6.96], 'frames_phi': [52, 80], 'frame_y_stop': 6.98, 'frame_w': 0.08},
                {'y0': 6.62, 'y1': 6.96, 'sides': True, 'phi_lo': 16, 'phi_hi': 40,
                 'frames_y': [6.64, 6.94], 'frames_phi': [16, 28, 40], 'frame_y_stop': 6.96, 'frame_w': 0.07}],
    'details': [('blade', 3.0, 0.30, 0.40, 'body')],
    'pit': {'y0': 6.3, 'y1': 7.5, 'ly0': 6.00, 'ly1': 7.95, 'floor': 0.42,
            'panels': [(7.42, 0.98)], 'panel_w': 1.15, 'hood': 0.16, 'seat': 'bomber', 'stick': 'yoke',
            'seats': [(-0.58, 6.78, 0.82), (0.58, 6.78, 0.82)],
            'col': '#6B7075', 'panel_col': '#1E1F20', 'seat_col': '#3E4237', 'accent': '#3A3A36',
            'dial_w': 1.0, 'dial_sp': 0.08, 'consoles': False},
    'gunports': [],
    'radome_y': 9.25,
    'variants': [
        {'key': 'h', 'title': 'B-52H (EVS blisters)', 'mass': 0.15, 'cost': 3,
         'desc': 'Late nose with the two electro-optical viewing system turrets under the chin.',
         'extra': [('blister', 8.70, 9.55, 0.42, 0.22, 0.20, 'bottom', 'body', 'evs'),
                   ('blister', 8.70, 9.55, -0.42, 0.22, 0.20, 'bottom', 'body', 'evs')]},
        {'key': 'd', 'title': 'B-52D (smooth chin)', 'mass': 0.0, 'cost': 0,
         'desc': 'Early clean nose without the EVS blisters.'},
    ],
    'liveries': [
        L('gunship', 'Gunship Grey', '#6E7276', radome='#5C6064', antiglare='#3A3D40', gloss=0.35),
        L('siop', 'SIOP Camouflage', '#7F7454', under='#E6E6E0', pattern='camo',
          colors=['#7F7454', '#4F5A3A', '#3A432E'], scale=2.4, split=-0.15, radome='#3A3D40', gloss=0.32),
        L('sea', 'Southeast Asia (black belly)', '#9C8858', under='#16181A', pattern='camo',
          colors=['#9C8858', '#4E5A38', '#3B4232'], scale=2.4, split=-0.05, radome='#16181A', gloss=0.30),
    ],
    'glass': '#1E2629', 'glass_alpha': (0.18, 0.38), 'glow': (1.0, 0.86, 0.62),
    'panel': {'frame_step': 0.80, 'stringers': 18, 'hatches': 10, 'rivets': True},
    'seats': [(-0.50, 7.00), (0.50, 7.00)],
})


# Plain White is every cockpit's first (default) scheme: no markings, camouflage, anti-glare panel,
# coloured radome, intake lip or exhaust staining, so the recolouring mods (TexturesUnlimited, SimpleRepaint,
# Reforged Materials) start from a clean light base. The historical schemes stay selectable after it.
PLAIN_WHITE = '#EDEDEA'
for _c in COCKPITS:
    _c['liveries'].insert(0, L('white', 'Plain White', PLAIN_WHITE, gloss=0.45, clean=True))
    _c.pop('stencils', None)


# ----------------------------------------------------------------------------- derived helpers

def get(cid):
    for c in COCKPITS:
        if c['id'] == cid:
            return c
    raise KeyError(cid)


def variant_length(c, v):
    return v.get('length', c['length'])


def variant_body(c, v):
    """BodyProfile for a variant (full length, native nose)."""
    keys = v.get('body', c['body'])
    length = variant_length(c, v)
    nose = c.get('nose')
    if nose is not None:
        nose = dict(nose)
        if 'nose_y0' in v:
            nose['y0'] = v['nose_y0']
    return BodyProfile(keys, length, nose)


def adapter_geometry(c, v):
    """(y_split, adapter_length, circle_radius, circle_centre_z) for an 'adapter' variant."""
    body = variant_body(c, v)
    ys = c['split_y']
    s = body.section(ys)
    r = 0.5 * v['front_dia']
    zc = s['zc'] + 0.5 * (s['ht'] - s['hb'])
    length = max(0.16, 0.30 * r)
    return ys, length, r, zc


def front_node(c, v):
    """(y_design, z_design) of the top node for a variant."""
    if v.get('nose') == 'adapter':
        ys, length, r, zc = adapter_geometry(c, v)
        return ys + length, zc
    body = variant_body(c, v)
    y = variant_length(c, v)
    s = body.section(y)
    return y, s['zc']


def canopy_top_at(c, v, y):
    keys = v.get('canopy', c.get('canopy'))
    body = variant_body(c, v)
    s = body.section(y)
    top = s['zc'] + s['ht']
    if keys:
        cp = CanopyProfile(keys, body)
        if cp.y0 <= y <= cp.y1:
            top = max(top, cp.section(y)['ztop'])
    return top


def ksp_point(c, y, z, x=0.0):
    """Design point -> KSP part space (x, y, z) string-ready tuple."""
    return (round(x, 4), round(y - c['origin_y'], 4), round(-z, 4))
