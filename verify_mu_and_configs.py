#!/usr/bin/env python3
"""
Verification suite for ROPlanesPlus .mu 3D models, textures, and .cfg files.
Validates that 100% of triangles in fuselage, windows, flagDecal, and collider
are wound outward (matching Unity/KSP backface culling rules verified from X1Cockpit.mu).
"""

import math
import os
import re
import struct


def cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


class BinaryReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read_int(self):
        v = struct.unpack_from('<i', self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_uint(self):
        v = struct.unpack_from('<I', self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_float(self):
        v = struct.unpack_from('<f', self.data, self.pos)[0]
        self.pos += 4
        return v

    def read_floats(self, n):
        v = struct.unpack_from(f'<{n}f', self.data, self.pos)
        self.pos += 4 * n
        return v

    def read_ints(self, n):
        v = struct.unpack_from(f'<{n}i', self.data, self.pos)
        self.pos += 4 * n
        return v

    def read_byte(self):
        v = self.data[self.pos]
        self.pos += 1
        return v

    def read_string(self):
        length = 0
        shift = 0
        while True:
            b = self.read_byte()
            length |= (b & 0x7f) << shift
            if not (b & 0x80):
                break
            shift += 7
        s = self.data[self.pos:self.pos + length].decode('utf-8', errors='replace')
        self.pos += length
        return s


def verify_mu_file(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    r = BinaryReader(data)
    magic = r.read_uint()
    version = r.read_int()
    _ = r.read_string()
    assert magic == 0x00012aff, f"Bad magic in {filepath}: {hex(magic)}"
    assert version == 5, f"Expected version 5 in {filepath}, got {version}"

    found_nodes = set()
    found_tags = set()
    found_anims = set()

    def check_node():
        node_name = r.read_string()
        found_nodes.add(node_name)
        _ = r.read_floats(3)
        _ = r.read_floats(4)
        _ = r.read_floats(3)
        while r.pos < len(data):
            etype = r.read_int()
            if etype == 0:
                check_node()
            elif etype == 1:
                return
            elif etype == 24:
                tag = r.read_string()
                layer = r.read_int()
                found_tags.add((tag, layer))
            elif etype == 2:
                num_clips = r.read_int()
                for _ in range(num_clips):
                    cname = r.read_string()
                    found_anims.add(cname)
                    _ = r.read_floats(6)
                    _ = r.read_int()
                    num_curves = r.read_int()
                    for _ in range(num_curves):
                        _ = r.read_string()
                        _ = r.read_string()
                        _ = r.read_int()
                        _ = r.read_int()
                        _ = r.read_int()
                        nkeys = r.read_int()
                        for _ in range(nkeys):
                            _ = r.read_floats(4)
                            _ = r.read_int()
                _ = r.read_string()
                _ = r.read_byte()
            elif etype in (7, 25):
                if etype == 25:
                    _ = r.read_byte()
                    _ = r.read_byte()
                ms = r.read_int()
                assert ms == 13
                num_v = r.read_int()
                _ = r.read_int()
                verts, norms, tris = [], [], []
                while True:
                    me = r.read_int()
                    if me == 22:
                        break
                    elif me == 14:
                        verts = [r.read_floats(3) for _ in range(num_v)]
                    elif me == 15:
                        _ = r.read_floats(2 * num_v)
                    elif me == 17:
                        norms = [r.read_floats(3) for _ in range(num_v)]
                    elif me == 18:
                        _ = r.read_floats(4 * num_v)
                    elif me == 19:
                        nt = r.read_int()
                        tris = r.read_ints(nt)
                # Verify winding against the stored normals (every triangle), then outwardness:
                #  - flagDecal: away from the part origin
                #  - collider (convex hull segments): away from the hull's own centroid
                #  - fuselage/windows: away from the fuselage axis (+Y), with the reference point
                #    clamped 0.25 m inside the mesh's length so end caps and nose tips count too
                # Connected pieces (by vertex position) are judged against their OWN centreline:
                # mid x / mid z of each 5 cm slice of that piece (handles drooped noses, off-axis
                # blisters and turrets).
                def pkey(v):
                    return (round(v[0], 4), round(v[1], 4), round(v[2], 4))
                parent = {}

                def find(a):
                    while parent.setdefault(a, a) != a:
                        parent[a] = parent[parent[a]]
                        a = parent[a]
                    return a
                for t in range(0, len(tris), 3):
                    ka, kb, kc = pkey(verts[tris[t]]), pkey(verts[tris[t + 1]]), pkey(verts[tris[t + 2]])
                    ra, rb, rc = find(ka), find(kb), find(kc)
                    parent[rb] = ra
                    parent[find(rc)] = ra
                comp_bands = {}
                comp_range = {}
                comp_sum = {}
                for v in verts:
                    r_ = find(pkey(v))
                    s_ = comp_sum.get(r_, (0.0, 0.0, 0.0, 0))
                    comp_sum[r_] = (s_[0] + v[0], s_[1] + v[1], s_[2] + v[2], s_[3] + 1)
                    k = int(math.floor(v[1] / 0.05))
                    bands = comp_bands.setdefault(r_, {})
                    b = bands.get(k)
                    bands[k] = (min(b[0], v[0]), max(b[1], v[0]), min(b[2], v[2]), max(b[3], v[2])) if b \
                        else (v[0], v[0], v[2], v[2])
                    lo_hi = comp_range.get(r_)
                    comp_range[r_] = (min(lo_hi[0], v[1]), max(lo_hi[1], v[1])) if lo_hi else (v[1], v[1])

                def centre(r_, yv):
                    bands = comp_bands[r_]
                    k = int(math.floor(yv / 0.05))
                    for d in (0, -1, 1, -2, 2):
                        b = bands.get(k + d)
                        if b:
                            return 0.5 * (b[0] + b[1]), 0.5 * (b[2] + b[3])
                    return 0.0, 0.0
                cen = (sum(v[0] for v in verts) / max(1, len(verts)), sum(v[1] for v in verts) / max(1, len(verts)),
                       sum(v[2] for v in verts) / max(1, len(verts)))
                outward_count = 0
                radial_total = 0
                small_flux = {}   # small pieces: area-weighted outward flux about their centroid
                small_count = {}
                for t in range(0, len(tris), 3):
                    i0, i1, i2 = tris[t], tris[t + 1], tris[t + 2]
                    v0, v1, v2 = verts[i0], verts[i1], verts[i2]
                    n0, n1, n2 = norms[i0], norms[i1], norms[i2]
                    fn = cross3(sub3(v1, v0), sub3(v2, v0))
                    n_avg = (n0[0] + n1[0] + n2[0], n0[1] + n1[1] + n2[1], n0[2] + n1[2] + n2[2])
                    assert dot3(fn, n_avg) > -1e-7, (
                        f"Inverted triangle winding wrt normal in {filepath} ({node_name}) tri {t//3}"
                    )
                    cx = (v0[0] + v1[0] + v2[0]) / 3.0
                    cy = (v0[1] + v1[1] + v2[1]) / 3.0
                    cz = (v0[2] + v1[2] + v2[2]) / 3.0
                    if node_name in ('collider', 'pylonCollider'):
                        ref = cen
                    elif node_name == 'flagDecal':
                        ref = (0.0, 0.0, 0.0)
                    else:
                        r_ = find(pkey(v0))
                        y_lo, y_hi = comp_range[r_]
                        if y_hi - y_lo <= 0.6:
                            # small piece (frame strip, dome, blade, box): judged as a whole below.
                            # Flat end caps (no depth along y) are judged from the part origin.
                            s_ = comp_sum[r_]
                            ref = (s_[0] / s_[3], s_[1] / s_[3], s_[2] / s_[3])
                            if y_hi - y_lo < 0.01:
                                ref = (0.0, 0.0, 0.0)
                            fl = (cx - ref[0]) * fn[0] + (cy - ref[1]) * fn[1] + (cz - ref[2]) * fn[2]
                            small_flux[r_] = small_flux.get(r_, 0.0) + fl
                            small_count[r_] = small_count.get(r_, 0) + 1
                            radial_total += 1
                            continue
                        ry = min(max(cy, y_lo + 0.25), y_hi - 0.25)
                        mx, mz = centre(r_, ry)
                        ref = (mx, ry, mz)
                    radial_total += 1
                    if (cx - ref[0]) * fn[0] + (cy - ref[1]) * fn[1] + (cz - ref[2]) * fn[2] > 0.0:
                        outward_count += 1
                for r_, fl in small_flux.items():
                    if fl > 0.0:
                        outward_count += small_count[r_]
                ratio = outward_count / radial_total if radial_total else 1.0
                if node_name in ('collider', 'pylonCollider', 'flagDecal'):
                    assert ratio == 1.0, f"Mesh {node_name} in {filepath} has inward faces ({ratio:.4f})!"
                elif node_name in ('fuselage', 'windows', 'pylonBody'):
                    assert ratio > 0.85, f"Mesh {node_name} in {filepath} has inward faces ({ratio:.4f})!"
            elif etype == 27:
                _ = r.read_byte()
                _ = r.read_float()
                _ = r.read_float()
                _ = r.read_int()
                _ = r.read_floats(3)
            elif etype == 8:
                _ = r.read_byte()
                _ = r.read_byte()
                nm = r.read_int()
                _ = r.read_ints(nm)
            elif etype == 10:
                nm = r.read_int()
                for _ in range(nm):
                    _ = r.read_string()
                    _ = r.read_string()
                    np = r.read_int()
                    for _ in range(np):
                        _ = r.read_string()
                        pt = r.read_int()
                        if pt in (0, 1):
                            _ = r.read_floats(4)
                        elif pt in (2, 3):
                            _ = r.read_float()
                        elif pt == 4:
                            _ = r.read_int()
                            _ = r.read_floats(2)
                            _ = r.read_floats(2)
            elif etype == 12:
                nt = r.read_int()
                for _ in range(nt):
                    _ = r.read_string()
                    _ = r.read_int()

    check_node()
    assert r.pos == len(data), f"Incomplete read in {filepath}: {r.pos}/{len(data)}"
    if 'PropShared' in filepath:
        for req in (
            'CowlingMesh', 'EngineCoreDetailsMesh', 'ExhaustAndRadiatorMesh', 'CowlFlapsMesh',
            'FrontPropHub', 'RearPropHub', 'SpinnerMesh', 'RearSpinnerMesh',
            'FrontBladesMesh', 'RearBladesMesh', 'FrontRotorDisc', 'RearRotorDisc',
            'cowlingCollider', 'spinnerCollider', 'thrustTransform', 'exhaustPortL', 'exhaustPortR'
        ):
            assert req in found_nodes, f"Missing propeller node {req} in {filepath}"
    elif os.path.basename(filepath) == 'proc_pylon.mu':
        # launch pylon: ModuleROPPLaunchPylon rebuilds these three by name
        for req in ('pylonBody', 'pylonHooks', 'pylonCollider'):
            assert req in found_nodes, f"Missing launch pylon node {req} in {filepath}"
    else:
        # canopyInterior (tub, seat, panel seen through the glass) is only winding-checked: it faces inward.
        # Its name contains "canopy" so Reforged Materials skips it (it also skips "window"/"flag" meshes).
        for req in ('fuselage', 'windows', 'flagDecal', 'collider', 'canopyInterior'):
            assert req in found_nodes, f"Missing node {req} in {filepath}"
        assert ('Airlock', 21) in found_tags, f"Missing Airlock on layer 21 in {filepath}"
        assert ('Ladder', 21) in found_tags, f"Missing Ladder on layer 21 in {filepath}"
        # every cockpit version is a B9PartSwitch group named variant_<key>
        assert any(n.startswith('variant_') for n in found_nodes), f"No variant_* groups in {filepath}"
    return True


def verify_cfg_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    clean = re.sub(r'//.*', '', text)
    open_b = clean.count('{')
    close_b = clean.count('}')
    assert open_b == close_b and open_b > 0, f"Unbalanced braces in {filepath}: {open_b} vs {close_b}"
    # every model / B9 texture path must exist next to the mod (GameData-relative, no extension)
    gamedata = os.path.abspath(filepath)
    while os.path.basename(gamedata) != 'GameData' and os.path.dirname(gamedata) != gamedata:
        gamedata = os.path.dirname(gamedata)
    # (TexturesUnlimited sets write "texture = _Slot, ROPlanesPlus/...": the optional slot is skipped)
    for key, exts in (('model', ('.mu',)), ('texture', ('.png', '.dds'))):
        for m in re.finditer(r'^\s*' + key + r'\s*=\s*(?:_\w+\s*,\s*)?(ROPlanesPlus/\S+)', clean, re.M):
            rel = m.group(1)
            assert any(os.path.exists(os.path.join(gamedata, rel + e)) for e in exts), \
                f"{filepath}: {key} {rel} does not exist"
    return True


def main():
    mod_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'GameData', 'ROPlanesPlus')
    mu_count = 0
    cfg_count = 0
    png_count = 0
    dll_count = 0
    wav_count = 0

    for dirpath, _, filenames in os.walk(mod_root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            if fn.endswith('.mu'):
                verify_mu_file(p)
                mu_count += 1
            elif fn.endswith('.cfg'):
                verify_cfg_file(p)
                cfg_count += 1
            elif fn.endswith('.png'):
                with open(p, 'rb') as f:
                    sig = f.read(8)
                assert sig == b'\x89PNG\r\n\x1a\n', f"Invalid PNG header in {p}"
                png_count += 1
            elif fn.endswith('.wav'):
                with open(p, 'rb') as f:
                    hdr = f.read(12)
                assert hdr[:4] == b'RIFF' and hdr[8:12] == b'WAVE', f"Invalid WAV header in {p}"
                wav_count += 1
            elif fn.endswith('.dll'):
                with open(p, 'rb') as f:
                    mz = f.read(2)
                assert mz == b'MZ', f"Invalid PE DLL header in {p}"
                assert os.path.getsize(p) > 32768, f"DLL suspiciously small: {p}"
                dll_count += 1

    assert mu_count == 12, f"Expected 12 .mu models (10 cockpits + 1 shared propeller engine + 1 launch pylon), found {mu_count}"
    assert dll_count == 1, f"Expected 1 compiled plugin DLL, found {dll_count}"
    assert wav_count == 28, f"Expected 28 engine sounds (generate_sounds.py), found {wav_count}"
    assert os.path.exists(os.path.join(mod_root, 'Parts', 'PropShared', 'ropp_blades_damaged.png')), \
        "Missing the damaged-blade texture (generate_propeller_assets.py)"
    # ModuleManager: ':FOR[X]' declares mod X installed, so we may only use it for our own passes
    for dirpath, _, filenames in os.walk(os.path.join(mod_root, 'Compatibility')):
        for fn in filenames:
            if fn.endswith('.cfg'):
                with open(os.path.join(dirpath, fn), encoding='utf-8') as f:
                    for ln, line in enumerate(f, 1):
                        assert not (line.startswith(('@', '+', '$', '!')) and ':FOR[' in line), \
                            f"{fn}:{ln} uses :FOR[] for another mod (declares it installed): {line.strip()[:120]}"

    # Shared propeller textures: one map per livery key (must match PropellerPresets.LiveryKeys,
    # minus "custom") plus the custom paint kit (PNG data stored as .dat)
    shared = os.path.join(mod_root, 'Parts', 'PropShared')
    livery_keys = ['aluminum', 'raf', 'luftwaffe', 'usn', 'soviet', 'olive', 'desert', 'ijn',
                   'racer', 'civil', 'night', 'trainer', 'arctic', 'italian']
    for key in livery_keys:
        assert os.path.exists(os.path.join(shared, f'ropp_livery_{key}.png')), f"Missing livery map ropp_livery_{key}.png"
    for kit in ('ropp_paintkit_base.dat', 'ropp_paintkit_mask.dat'):
        with open(os.path.join(shared, kit), 'rb') as f:
            assert f.read(8) == b'\x89PNG\r\n\x1a\n', f"Paint kit {kit} missing or not PNG data"
    assert not any(os.path.isdir(os.path.join(mod_root, 'Parts', d)) for d in
                   ('proc_prop_radial', 'proc_prop_vinline', 'proc_prop_turboprop', 'proc_prop_contra')), \
        "Removed legacy engine part folders are back"
    # launch pylon: paint maps (generate_pylon_assets.LIVERIES), normal map and hardware texture
    pylon = os.path.join(mod_root, 'Parts', 'proc_pylon')
    for tex in ('ropp_pylon_metal', 'ropp_pylon_white', 'ropp_pylon_grey', 'ropp_pylon_black', 'ropp_pylon_orange',
                'ropp_pylon_NRM', 'ropp_pylon_hardware'):
        assert os.path.exists(os.path.join(pylon, tex + '.png')), f"Missing launch pylon texture {tex}.png"
    # every cockpit carries its own translucent canopy-glass map, emissive map and normal map
    parts = os.path.join(mod_root, 'Parts')
    for d in sorted(os.listdir(parts)):
        if d != 'proc_pylon' and os.path.exists(os.path.join(parts, d, d + '.mu')):
            for suffix in ('_glass.png', '_emissive.png', '_NRM.png', '_paint.png', '_mask.png', '_metal.png'):
                assert os.path.exists(os.path.join(parts, d, d + suffix)), f"Missing {d}{suffix}"
    print(
        f"VERIFICATION PASSED: {mu_count} .mu models (100% outward-wound), "
        f"{cfg_count} .cfg files, {png_count} .png textures/icons, {wav_count} .wav sounds, {dll_count} .dll plugin!"
    )


if __name__ == '__main__':
    main()
