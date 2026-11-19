using System;
using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>
    /// Shape of a procedural launch pylon. Part space: +Y forward, +Z down (towards the released
    /// aircraft), origin at the centre of the mount face (z = 0). The release (hook) face is at z = height.
    /// </summary>
    public struct PylonShape
    {
        public float length;          // chord at the mount face (m)
        public float height;          // mount face to hook face (m)
        public float width;           // maximum thickness at the mount face (m)
        public float bottomLengthFrac; // hook-face chord / mount-face chord
        public float bottomWidthFrac;  // hook-face thickness / mount-face thickness
        public float sweepFrac;        // hook-face centre moved aft, as a fraction of the mount chord
        public int profile;            // 0 aerofoil, 1 rounded, 2 box
        public bool hooks;

        public float TopFront { get { return 0.5f * length; } }
        public float TopAft { get { return -0.5f * length; } }
        public float BottomLength { get { return length * bottomLengthFrac; } }
        public float BottomCentreY { get { return -sweepFrac * length; } }
        public float BottomFront { get { return BottomCentreY + 0.5f * BottomLength; } }
        public float BottomAft { get { return BottomCentreY - 0.5f * BottomLength; } }
        public float TopHalfWidth { get { return 0.5f * width; } }
        public float BottomHalfWidth { get { return 0.5f * width * bottomWidthFrac; } }
        /// <summary>Size of the hooks and sway braces.</summary>
        public float HardwareScale { get { return Mathf.Clamp(width / 0.3f, 0.6f, 3f); } }
    }

    /// <summary>
    /// Meshes of the procedural launch pylon. generate_pylon_assets.py ports this code 1:1 for the
    /// default model and the editor icon; keep the two in step.
    /// </summary>
    public static class PylonMeshGenerator
    {
        public const float TileMetres = 1.0f;   // the pylon textures tile once per metre

        // Symmetric NACA 4-digit thickness, normalised to 1 at its maximum (s = 0.3), closed trailing edge
        public static float AerofoilThickness(float s)
        {
            s = Mathf.Clamp01(s);
            float p = 0.2969f * Mathf.Sqrt(s) - 0.1260f * s - 0.3516f * s * s + 0.2843f * s * s * s - 0.1036f * s * s * s * s;
            return Mathf.Max(0f, p / 0.1f);
        }

        /// <summary>
        /// Outline of one horizontal section as runs of (x, y) points. Inside a run the surface is smooth;
        /// between runs (box corners) and at run ends (aerofoil trailing edge) it has a hard edge. The
        /// point count depends only on profile and resolution, so sections at any height line up.
        /// </summary>
        public static List<List<Vector2>> Outline(int profile, float yF, float yA, float halfW, int res)
        {
            var runs = new List<List<Vector2>>();
            float chord = Mathf.Max(0.001f, yF - yA);
            if (profile == 2)
            {
                runs.Add(new List<Vector2> { new Vector2(halfW, yA), new Vector2(halfW, yF) });
                runs.Add(new List<Vector2> { new Vector2(halfW, yF), new Vector2(-halfW, yF) });
                runs.Add(new List<Vector2> { new Vector2(-halfW, yF), new Vector2(-halfW, yA) });
                runs.Add(new List<Vector2> { new Vector2(-halfW, yA), new Vector2(halfW, yA) });
                return runs;
            }
            var run = new List<Vector2>();
            if (profile == 1)
            {
                // stadium: semi-elliptic ends (half axes halfW across, e along the chord) joined by straight sides
                float e = Mathf.Min(halfW, 0.5f * chord);
                for (int i = 0; i <= res; i++)
                {
                    float th = Mathf.PI * i / res;
                    run.Add(new Vector2(halfW * Mathf.Cos(th), yF - e + e * Mathf.Sin(th)));
                }
                for (int i = 0; i <= res; i++)
                {
                    float th = Mathf.PI + Mathf.PI * i / res;
                    run.Add(new Vector2(halfW * Mathf.Cos(th), yA + e + e * Mathf.Sin(th)));
                }
                run.Add(run[0]);   // closed loop
                runs.Add(run);
                return runs;
            }
            // aerofoil: right side trailing edge -> leading edge, then left side back to the trailing edge
            for (int i = res; i >= 0; i--)
            {
                float s = 0.5f * (1f - Mathf.Cos(Mathf.PI * i / res));
                run.Add(new Vector2(halfW * AerofoilThickness(s), yF - s * chord));
            }
            for (int i = 1; i <= res; i++)
            {
                float s = 0.5f * (1f - Mathf.Cos(Mathf.PI * i / res));
                run.Add(new Vector2(-halfW * AerofoilThickness(s), yF - s * chord));
            }
            runs.Add(run);
            return runs;
        }

        /// <summary>Half thickness of the hook face at chord position y.</summary>
        public static float BottomHalfWidthAt(PylonShape sh, float y)
        {
            float chord = Mathf.Max(0.001f, sh.BottomFront - sh.BottomAft);
            float s = Mathf.Clamp01((sh.BottomFront - y) / chord);
            float hw = sh.BottomHalfWidth;
            if (sh.profile == 0)
                return hw * AerofoilThickness(s);
            if (sh.profile == 1)
            {
                float e = Mathf.Min(hw, 0.5f * chord);
                float d = Mathf.Min(s * chord, (1f - s) * chord);   // distance from the nearer end
                if (d >= e || e < 1e-4f)
                    return hw;
                float q = 1f - d / e;
                return hw * Mathf.Sqrt(Mathf.Max(0f, 1f - q * q));
            }
            return hw;
        }

        public static int BodyResolution(int profile, bool collider)
        {
            if (profile == 2)
                return 1;
            if (profile == 1)
                return collider ? 3 : 12;
            return collider ? 6 : 24;
        }

        /// <summary>Hook-face positions along the chord (one hook on short pylons, two otherwise).</summary>
        public static float[] HookStations(PylonShape sh)
        {
            float lb = sh.BottomLength;
            if (lb < 0.8f)
                return new[] { sh.BottomCentreY };
            return new[] { sh.BottomCentreY + 0.25f * lb, sh.BottomCentreY - 0.25f * lb };
        }

        public static void BuildBody(PylonShape sh, RuntimeMeshBuffer mb, bool collider)
        {
            mb.Clear();
            int res = BodyResolution(sh.profile, collider);
            float h = Mathf.Max(0.01f, sh.height);
            var top = Outline(sh.profile, sh.TopFront, sh.TopAft, sh.TopHalfWidth, res);
            var bot = Outline(sh.profile, sh.BottomFront, sh.BottomAft, sh.BottomHalfWidth, res);
            float ycTop = 0.5f * (sh.TopFront + sh.TopAft);
            float ycBot = 0.5f * (sh.BottomFront + sh.BottomAft);

            // ---- sides: ruled surface between the two outlines ----
            float totalTop = 0f, totalBot = 0f;
            for (int r = 0; r < top.Count; r++)
            {
                totalTop += RunLength(top[r]);
                totalBot += RunLength(bot[r]);
            }
            float uScale = 0.5f * (totalTop + totalBot) / Mathf.Max(1e-4f, totalTop) / TileMetres;
            float uScaleB = 0.5f * (totalTop + totalBot) / Mathf.Max(1e-4f, totalBot) / TileMetres;
            float arcTop = 0f, arcBot = 0f;
            for (int r = 0; r < top.Count; r++)
            {
                List<Vector2> rt = top[r], rb = bot[r];
                int n = rt.Count;
                bool closed = n > 2 && (rt[0] - rt[n - 1]).sqrMagnitude < 1e-10f;
                var it = new int[n];
                var ib = new int[n];
                for (int j = 0; j < n; j++)
                {
                    if (j > 0)
                    {
                        arcTop += (rt[j] - rt[j - 1]).magnitude;
                        arcBot += (rb[j] - rb[j - 1]).magnitude;
                    }
                    int ja = j - 1, jb = j + 1;
                    if (closed)
                    {
                        if (ja < 0) ja = n - 2;
                        if (jb > n - 1) jb = 1;
                    }
                    else
                    {
                        ja = Math.Max(ja, 0);
                        jb = Math.Min(jb, n - 1);
                    }
                    Vector3 pt = new Vector3(rt[j].x, rt[j].y, 0f);
                    Vector3 pb = new Vector3(rb[j].x, rb[j].y, h);
                    Vector3 down = pb - pt;
                    Vector3 nt = SideNormal(rt[jb] - rt[ja], down, pt, ycTop);
                    Vector3 nb = SideNormal(rb[jb] - rb[ja], down, pb, ycBot);
                    it[j] = mb.AddVertex(pt, new Vector2(arcTop * uScale, 0f), nt);
                    ib[j] = mb.AddVertex(pb, new Vector2(arcBot * uScaleB, -h / TileMetres), nb);
                }
                for (int j = 0; j < n - 1; j++)
                    mb.AddQuad(it[j], it[j + 1], ib[j + 1], ib[j]);
            }

            // ---- flat mount face (normal -Z) and hook face (normal +Z) ----
            AddCap(mb, Flatten(top), 0f, ycTop, -1f);
            AddCap(mb, Flatten(bot), h, ycBot, 1f);
        }

        private static float RunLength(List<Vector2> run)
        {
            float l = 0f;
            for (int j = 1; j < run.Count; j++)
                l += (run[j] - run[j - 1]).magnitude;
            return l;
        }

        private static Vector3 SideNormal(Vector2 along, Vector3 down, Vector3 p, float yc)
        {
            Vector3 n = Vector3.Cross(new Vector3(along.x, along.y, 0f), down);
            Vector3 outward = new Vector3(p.x, p.y - yc, 0f);
            if (Vector3.Dot(n, outward) < 0f)
                n = -n;
            return n.sqrMagnitude > 1e-12f ? n.normalized : (outward.sqrMagnitude > 1e-12f ? outward.normalized : Vector3.up);
        }

        private static List<Vector2> Flatten(List<List<Vector2>> runs)
        {
            var pts = new List<Vector2>();
            for (int r = 0; r < runs.Count; r++)
                for (int j = 0; j < runs[r].Count; j++)
                {
                    Vector2 p = runs[r][j];
                    if (pts.Count == 0 || (pts[pts.Count - 1] - p).sqrMagnitude > 1e-10f)
                        pts.Add(p);
                }
            if (pts.Count > 1 && (pts[0] - pts[pts.Count - 1]).sqrMagnitude < 1e-10f)
                pts.RemoveAt(pts.Count - 1);
            return pts;
        }

        private static void AddCap(RuntimeMeshBuffer mb, List<Vector2> pts, float z, float yc, float nz)
        {
            Vector3 n = new Vector3(0f, 0f, nz);
            int c = mb.AddVertex(new Vector3(0f, yc, z), CapUV(0f, yc), n);
            var idx = new int[pts.Count];
            for (int j = 0; j < pts.Count; j++)
                idx[j] = mb.AddVertex(new Vector3(pts[j].x, pts[j].y, z), CapUV(pts[j].x, pts[j].y), n);
            for (int j = 0; j < pts.Count; j++)
                mb.AddTri(c, idx[j], idx[(j + 1) % pts.Count]);
        }

        private static Vector2 CapUV(float x, float y)
        {
            return new Vector2(y / TileMetres, 0.5f + x / TileMetres);
        }

        /// <summary>Release hooks and sway braces under the hook face (cosmetic; empty when hidden).</summary>
        public static void BuildHooks(PylonShape sh, RuntimeMeshBuffer mb)
        {
            mb.Clear();
            if (!sh.hooks)
                return;
            float k = sh.HardwareScale;
            float h = sh.height;
            float[] stations = HookStations(sh);
            for (int i = 0; i < stations.Length; i++)
            {
                float y = stations[i];
                // hook: a plate hanging from the face with a forward toe (the aircraft's lug sits on it)
                AddBox(mb, new Vector3(0f, y, h + 0.035f * k), new Vector3(0.012f * k, 0.03f * k, 0.035f * k));
                AddBox(mb, new Vector3(0f, y + 0.035f * k, h + 0.062f * k), new Vector3(0.012f * k, 0.035f * k, 0.008f * k));
                // sway braces: an arm down and out to each side, ending in a pad that rests on the aircraft
                float hw = Mathf.Max(0.02f * k, BottomHalfWidthAt(sh, y));
                for (int side = -1; side <= 1; side += 2)
                {
                    Vector3 a = new Vector3(side * 0.6f * hw, y, h);
                    Vector3 b = new Vector3(side * (0.6f * hw + 0.11f * k), y, h + 0.06f * k);
                    AddBeam(mb, a, b, 0.010f * k, 0.018f * k);
                    AddBox(mb, b + new Vector3(0f, 0f, 0.008f * k), new Vector3(0.028f * k, 0.04f * k, 0.008f * k));
                }
            }
        }

        // Hardware sits on the plain part of the hardware texture
        private static readonly Vector2 HwUV = new Vector2(0.5f, 0.5f);

        private static void AddBox(RuntimeMeshBuffer mb, Vector3 c, Vector3 he)
        {
            Vector3 ex = new Vector3(he.x, 0f, 0f), ey = new Vector3(0f, he.y, 0f), ez = new Vector3(0f, 0f, he.z);
            AddFace(mb, c + ex, ey, ez, Vector3.right);
            AddFace(mb, c - ex, ey, ez, Vector3.left);
            AddFace(mb, c + ey, ex, ez, Vector3.up);
            AddFace(mb, c - ey, ex, ez, Vector3.down);
            AddFace(mb, c + ez, ex, ey, Vector3.forward);
            AddFace(mb, c - ez, ex, ey, Vector3.back);
        }

        private static void AddBeam(RuntimeMeshBuffer mb, Vector3 p0, Vector3 p1, float hw, float hd)
        {
            Vector3 axis = p1 - p0;
            float len = axis.magnitude;
            if (len < 1e-5f)
                return;
            Vector3 d = axis / len;
            Vector3 e1 = Vector3.Cross(d, Vector3.up);   // the beams lie in an x-z plane, so +Y is never parallel
            e1 = e1.sqrMagnitude > 1e-8f ? e1.normalized : Vector3.right;
            Vector3 e2 = Vector3.Cross(d, e1).normalized;
            Vector3 c = 0.5f * (p0 + p1);
            Vector3 a = d * (0.5f * len), b1 = e1 * hw, b2 = e2 * hd;
            AddFace(mb, c + b1, a, b2, e1);
            AddFace(mb, c - b1, a, b2, -e1);
            AddFace(mb, c + b2, a, b1, e2);
            AddFace(mb, c - b2, a, b1, -e2);
            AddFace(mb, c + a, b1, b2, d);
            AddFace(mb, c - a, b1, b2, -d);
        }

        private static void AddFace(RuntimeMeshBuffer mb, Vector3 c, Vector3 u, Vector3 v, Vector3 n)
        {
            int i0 = mb.AddVertex(c - u - v, HwUV, n);
            int i1 = mb.AddVertex(c + u - v, HwUV, n);
            int i2 = mb.AddVertex(c + u + v, HwUV, n);
            int i3 = mb.AddVertex(c - u + v, HwUV, n);
            mb.AddQuad(i0, i1, i2, i3);
        }

        /// <summary>Plan area of a section outline (shoelace), for the mass estimate.</summary>
        public static float SectionArea(int profile, float yF, float yA, float halfW)
        {
            List<Vector2> pts = Flatten(Outline(profile, yF, yA, halfW, BodyResolution(profile, false)));
            float a = 0f;
            for (int j = 0; j < pts.Count; j++)
            {
                Vector2 p = pts[j], q = pts[(j + 1) % pts.Count];
                a += p.x * q.y - q.x * p.y;
            }
            return Mathf.Abs(0.5f * a);
        }
    }
}
