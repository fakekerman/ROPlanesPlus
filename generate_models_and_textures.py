#!/usr/bin/env python3
"""
Shared pure-Python library for the ROPlanesPlus asset generators: PNG writer, KSP .mu v5 writer,
mesh builder and math helpers (used by generate_propeller_assets.py and blender/build_cockpits.py).

Coordinate System (KSP Aircraft Fuselage/Cockpit Standard, verified from X1Cockpit.mu):
  +Y : Forward (Nose / node_stack_top)
  -Y : Aft / Rear (Tail / node_stack_bottom)
  -Z : Dorsal / Up (Canopy / Spine)
  +Z : Ventral / Down (Belly / Chin)
  +X : Starboard / Right
  -X : Port / Left

Winding & Normal Convention (verified from X1Cockpit.mu):
  - All exterior vertex normals point OUTWARD away from the fuselage centerline.
  - Every triangle (v0, v1, v2) is wound such that cross3(v1 - v0, v2 - v0)
    has a positive dot product with the outward normal (clockwise when viewed from outside
    in Unity's left-handed coordinate system).
"""

import math
import os
import struct
import zlib

# ==============================================================================
# 1. PNG WRITER (Pure Python RGBA PNG encoder)
# ==============================================================================

def write_png(filepath, width, height, rgba_bytes):
    """Write raw RGBA bytes (len = width * height * 4) to a PNG file."""
    assert len(rgba_bytes) == width * height * 4
    stride = width * 4
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # Filter type 0 (None)
        row_start = y * stride
        raw_rows.extend(rgba_bytes[row_start:row_start + stride])

    compressed = zlib.compress(bytes(raw_rows), level=6)

    def make_chunk(chunk_type, data):
        chunk = struct.pack('>I', len(data)) + chunk_type + data
        crc = zlib.crc32(chunk_type + data) & 0xffffffff
        return chunk + struct.pack('>I', crc)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    png_data = (
        b'\x89PNG\r\n\x1a\n'
        + make_chunk(b'IHDR', ihdr)
        + make_chunk(b'IDAT', compressed)
        + make_chunk(b'IEND', b'')
    )
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(png_data)


# ==============================================================================
# 2. KSP .MU v5 BINARY WRITER
# ==============================================================================

class MuWriter:
    def __init__(self):
        self.buf = bytearray()

    def write_int(self, v):
        self.buf.extend(struct.pack('<i', int(v)))

    def write_uint(self, v):
        self.buf.extend(struct.pack('<I', int(v)))

    def write_float(self, v):
        self.buf.extend(struct.pack('<f', float(v)))

    def write_floats(self, seq):
        self.buf.extend(struct.pack(f'<{len(seq)}f', *seq))

    def write_ints(self, seq):
        self.buf.extend(struct.pack(f'<{len(seq)}i', *seq))

    def write_byte(self, b):
        self.buf.append(int(b) & 0xff)

    def write_bool(self, b):
        self.buf.append(1 if b else 0)

    def write_string(self, s):
        encoded = s.encode('utf-8')
        length = len(encoded)
        while True:
            byte = length & 0x7f
            length >>= 7
            if length:
                self.buf.append(byte | 0x80)
            else:
                self.buf.append(byte)
                break
        self.buf.extend(encoded)

    def write_transform(self, name, pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0, 1.0), scale=(1.0, 1.0, 1.0)):
        self.write_string(name)
        self.write_floats(pos)
        self.write_floats(rot)
        self.write_floats(scale)

    def write_tag_and_layer(self, tag='Untagged', layer=0):
        self.write_int(24)  # TagAndLayer
        self.write_string(tag)
        self.write_int(layer)

    def write_mesh_data(self, verts, uvs, normals, tangents, tris):
        num_v = len(verts)
        assert len(uvs) == num_v
        assert len(normals) == num_v
        assert len(tangents) == num_v
        assert len(tris) % 3 == 0

        self.write_int(13)  # MeshStart
        self.write_int(num_v)
        self.write_int(1)   # submesh count = 1

        # MeshVerts (14)
        self.write_int(14)
        flat_v = [c for v in verts for c in v]
        self.write_floats(flat_v)

        # MeshUV (15)
        self.write_int(15)
        flat_uv = [c for uv in uvs for c in uv]
        self.write_floats(flat_uv)

        # MeshNormals (17)
        self.write_int(17)
        flat_n = [c for n in normals for c in n]
        self.write_floats(flat_n)

        # MeshTangents (18)
        self.write_int(18)
        flat_t = [c for t in tangents for c in t]
        self.write_floats(flat_t)

        # MeshTriangles (19)
        self.write_int(19)
        self.write_int(len(tris))
        self.write_ints(tris)

        # MeshEnd (22)
        self.write_int(22)

    def write_mesh_filter(self, verts, uvs, normals, tangents, tris):
        self.write_int(7)  # MeshFilter
        self.write_mesh_data(verts, uvs, normals, tangents, tris)

    def write_mesh_renderer(self, mat_indices, cast_shadows=True, receive_shadows=True):
        self.write_int(8)  # MeshRenderer
        self.write_bool(cast_shadows)
        self.write_bool(receive_shadows)
        self.write_int(len(mat_indices))
        self.write_ints(mat_indices)

    def write_mesh_collider2(self, verts, uvs, normals, tangents, tris, is_trigger=False, convex=True):
        self.write_int(25)  # MeshCollider2
        self.write_bool(is_trigger)
        self.write_bool(convex)
        self.write_mesh_data(verts, uvs, normals, tangents, tris)

    def write_capsule_collider2(self, radius, height, direction=1, center=(0.0, 0.0, 0.0), is_trigger=True):
        self.write_int(27)  # CapsuleCollider2
        self.write_bool(is_trigger)
        self.write_float(radius)
        self.write_float(height)
        self.write_int(direction)
        self.write_floats(center)

    def write_light_animation(self, clip_name='cockpitlight', targets=('fuselage', 'windows'), color=(1.0, 0.82, 0.55)):
        """Write an Animation component that toggles _EmissiveColor on the target meshes."""
        self.write_int(2)  # Animation
        self.write_int(1)  # 1 clip
        self.write_string(clip_name)
        self.write_floats((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))  # bounds center + extents
        self.write_int(0)  # wrapMode = Default (0)
        self.write_int(len(targets) * 3)  # 3 RGB curves per target
        channels = [('_EmissiveColor.r', color[0]), ('_EmissiveColor.g', color[1]), ('_EmissiveColor.b', color[2])]
        for path in targets:
            for prop_name, max_val in channels:
                self.write_string(path)
                self.write_string(prop_name)
                self.write_int(1)  # curve type = Material (1)
                self.write_int(8)  # preWrapMode = ClampForever (8)
                self.write_int(8)  # postWrapMode = ClampForever (8)
                self.write_int(2)  # 2 keys (t=0 -> 0, t=1 -> max_val)
                self.write_floats((0.0, 0.0, 0.0, max_val))
                self.write_int(0)
                self.write_floats((1.0, max_val, max_val, 0.0))
                self.write_int(0)
        self.write_string(clip_name)
        self.write_bool(False)  # autoPlay = False


# ==============================================================================
# 3. 3D GEOMETRY BUILDER & MESH UTILITIES
# ==============================================================================

def normalize3(vx, vy, vz):
    l = math.sqrt(vx * vx + vy * vy + vz * vz)
    if l < 1e-9:
        return (0.0, 0.0, -1.0)
    return (vx / l, vy / l, vz / l)

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

def add3(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.uvs = []
        self.normals = []
        self.tris = []

    def add_vertex(self, pos, uv, normal):
        idx = len(self.verts)
        self.verts.append((float(pos[0]), float(pos[1]), float(pos[2])))
        self.uvs.append((float(uv[0]), float(uv[1])))
        self.normals.append(normalize3(normal[0], normal[1], normal[2]))
        return idx

    def add_tri(self, i0, i1, i2, ensure_outward=True):
        if i0 == i1 or i1 == i2 or i2 == i0:
            return
        v0, v1, v2 = self.verts[i0], self.verts[i1], self.verts[i2]
        fn = cross3(sub3(v1, v0), sub3(v2, v0))
        fl = math.sqrt(dot3(fn, fn))
        if fl < 1e-10:
            return
        if ensure_outward:
            n_avg = add3(add3(self.normals[i0], self.normals[i1]), self.normals[i2])
            if dot3(n_avg, n_avg) > 1e-9 and dot3(fn, n_avg) < 0.0:
                i1, i2 = i2, i1
        self.tris.extend([i0, i1, i2])

    def add_quad(self, i0, i1, i2, i3, ensure_outward=True):
        self.add_tri(i0, i1, i2, ensure_outward=ensure_outward)
        self.add_tri(i0, i2, i3, ensure_outward=ensure_outward)

    def compute_tangents(self):
        tangents = []
        for nx, ny, nz in self.normals:
            up = (0.0, 1.0, 0.0) if abs(ny) < 0.9 else (1.0, 0.0, 0.0)
            tx, ty, tz = normalize3(*cross3(up, (nx, ny, nz)))
            tangents.append((tx, ty, tz, 1.0))
        return tangents

    def finalize(self):
        """
        Preserve the exact analytical/periodic vertex normals and verify that
        every triangle's cross product aligns positively with its vertex normals.
        """
        for t in range(0, len(self.tris), 3):
            i0, i1, i2 = self.tris[t], self.tris[t + 1], self.tris[t + 2]
            v0, v1, v2 = self.verts[i0], self.verts[i1], self.verts[i2]
            fn = cross3(sub3(v1, v0), sub3(v2, v0))
            n_sum = add3(add3(self.normals[i0], self.normals[i1]), self.normals[i2])
            if dot3(fn, n_sum) < 0.0:
                self.tris[t + 1], self.tris[t + 2] = i2, i1
        tangents = self.compute_tangents()
        return self.verts, self.uvs, self.normals, tangents, self.tris


# ==============================================================================
# 4. AIRCRAFT COCKPIT PARAMETRIC 3D LOFTING & CANOPY MASK FUNCTIONS
# ==============================================================================

def smoothstep(edge0, edge1, x):
    if abs(edge1 - edge0) < 1e-9:
        return 1.0 if x >= edge1 else 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

def window_bump(s, s0, s1, ramp=0.08):
    """Smooth raised profile between s0 and s1."""
    if s <= s0 or s >= s1:
        return 0.0
    up = smoothstep(s0, min(s1, s0 + ramp), s)
    dn = 1.0 - smoothstep(max(s0, s1 - ramp), s1, s)
    return up * dn

def band_mask(x, center, half_width, feather):
    """Smooth anti-aliased pulse of 1.0 inside [center - half_width, center + half_width]."""
    d = abs(x - center)
    return 1.0 - smoothstep( max(0.0, half_width - feather), half_width + feather, d )


# ==============================================================================
# The cockpits used to be generated here. They are now modelled, baked and painted in Blender:
# see generate_cockpits.py, blender/build_cockpits.py and cockpit_specs.py. This file remains the
# shared pure-Python library (PNG + .mu writers, mesh helpers) used by generate_propeller_assets.py
# and by the Blender cockpit builder.
# ==============================================================================


def main():
    print("Cockpits are built in Blender now: run  python generate_cockpits.py")
    print("This module is the shared library (write_png, MuWriter, MeshBuilder, math helpers).")


if __name__ == '__main__':
    main()