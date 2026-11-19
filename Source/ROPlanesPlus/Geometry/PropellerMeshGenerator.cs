using System;
using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    public class RuntimeMeshBuffer
    {
        public readonly List<Vector3> verts = new List<Vector3>(512);
        public readonly List<Vector2> uvs = new List<Vector2>(512);
        public readonly List<Vector3> normals = new List<Vector3>(512);
        public readonly List<int> tris = new List<int>(1024);

        public void Clear()
        {
            verts.Clear();
            uvs.Clear();
            normals.Clear();
            tris.Clear();
        }

        public int AddVertex(Vector3 pos, Vector2 uv, Vector3 normal)
        {
            int idx = verts.Count;
            verts.Add(pos);
            uvs.Add(uv);
            normals.Add(normal.sqrMagnitude > 1e-10f ? normal.normalized : Vector3.back);
            return idx;
        }

        public void AddTri(int i0, int i1, int i2)
        {
            if (i0 == i1 || i1 == i2 || i2 == i0)
                return;
            Vector3 v0 = verts[i0];
            Vector3 v1 = verts[i1];
            Vector3 v2 = verts[i2];
            Vector3 fn = Vector3.Cross(v1 - v0, v2 - v0);
            if (fn.sqrMagnitude < 1e-12f)
                return;
            Vector3 nSum = normals[i0] + normals[i1] + normals[i2];
            if (Vector3.Dot(fn, nSum) < 0f)
            {
                int tmp = i1;
                i1 = i2;
                i2 = tmp;
            }
            tris.Add(i0);
            tris.Add(i1);
            tris.Add(i2);
        }

        public void AddQuad(int i0, int i1, int i2, int i3)
        {
            AddTri(i0, i1, i2);
            AddTri(i0, i2, i3);
        }

        public void ApplyToMesh(Mesh target, string meshName)
        {
            if (target == null)
                return;

            target.Clear();
            target.name = meshName;
            target.SetVertices(verts);
            target.SetUVs(0, uvs);
            target.SetNormals(normals);
            target.SetTriangles(tris, 0, true);
            target.RecalculateBounds();
            if (verts.Count > 0)
                target.RecalculateTangents();
        }
    }

    public static class PropellerMeshGenerator
    {
        public static void AddFrustum(
            RuntimeMeshBuffer mb,
            Vector3 p0,
            Vector3 p1,
            float r0,
            float r1,
            float u0,
            float u1,
            float v0,
            float v1,
            int segs = 16,
            bool capStart = false,
            bool capEnd = false)
        {
            Vector3 axis = p1 - p0;
            float len = axis.magnitude;
            if (len < 1e-5f)
                return;

            Vector3 fwd = axis / len;
            Vector3 upRef = Mathf.Abs(fwd.z) < 0.9f ? Vector3.back : Vector3.right;
            Vector3 right = Vector3.Cross(upRef, fwd).normalized;
            Vector3 up = Vector3.Cross(fwd, right).normalized;

            float slope = (r0 - r1) / len;
            int baseIdx = mb.verts.Count;

            for (int i = 0; i <= segs; i++)
            {
                float frac = (float)i / segs;
                float ang = frac * Mathf.PI * 2f;
                float ca = Mathf.Cos(ang);
                float sa = Mathf.Sin(ang);
                Vector3 rDir = right * ca + up * sa;
                Vector3 nDir = (rDir + fwd * slope).normalized;
                float u = Mathf.Lerp(u0, u1, frac);

                mb.AddVertex(p0 + rDir * r0, new Vector2(u, v0), nDir);
                mb.AddVertex(p1 + rDir * r1, new Vector2(u, v1), nDir);
            }

            for (int i = 0; i < segs; i++)
            {
                int k0 = baseIdx + i * 2;
                int k1 = k0 + 1;
                int k2 = k0 + 3;
                int k3 = k0 + 2;
                mb.AddQuad(k0, k1, k2, k3);
            }

            if (capStart && r0 > 1e-4f)
            {
                Vector3 nStart = -fwd;
                float uMid = 0.5f * (u0 + u1);
                int cIdx = mb.AddVertex(p0, new Vector2(uMid, v0), nStart);
                int ringBase = mb.verts.Count;
                for (int i = 0; i <= segs; i++)
                {
                    float ang = ((float)i / segs) * Mathf.PI * 2f;
                    Vector3 rDir = right * Mathf.Cos(ang) + up * Mathf.Sin(ang);
                    mb.AddVertex(p0 + rDir * r0, new Vector2(uMid, v0), nStart);
                }
                for (int i = 0; i < segs; i++)
                    mb.AddTri(cIdx, ringBase + i + 1, ringBase + i);
            }

            if (capEnd && r1 > 1e-4f)
            {
                Vector3 nEnd = fwd;
                float uMid = 0.5f * (u0 + u1);
                int cIdx = mb.AddVertex(p1, new Vector2(uMid, v1), nEnd);
                int ringBase = mb.verts.Count;
                for (int i = 0; i <= segs; i++)
                {
                    float ang = ((float)i / segs) * Mathf.PI * 2f;
                    Vector3 rDir = right * Mathf.Cos(ang) + up * Mathf.Sin(ang);
                    mb.AddVertex(p1 + rDir * r1, new Vector2(uMid, v1), nEnd);
                }
                for (int i = 0; i < segs; i++)
                    mb.AddTri(cIdx, ringBase + i, ringBase + i + 1);
            }
        }

        private static Vector3 EvalCowlingProfile(
            EngineArchitecture arch,
            int subStyle,
            NacelleStyle nacelle,
            float rBase,
            float spinR,
            float yAft,
            float yFwd,
            float s,
            float theta)
        {
            float y = Mathf.Lerp(yAft, yFwd, s);
            float st = Mathf.Sin(theta);
            float ct = Mathf.Cos(theta);

            // If Nacelle extension is active, s in [0, nacelleFrac] is the rear nacelle body
            float nacelleFrac = 0f;
            if (nacelle == NacelleStyle.ShortWingNacelle)
                nacelleFrac = 0.25f;
            else if (nacelle == NacelleStyle.StreamlinedTankNacelle)
                nacelleFrac = 0.42f;

            float sEngine = s;
            float nacelleTaper = 1.0f;
            if (nacelleFrac > 0.01f)
            {
                if (s < nacelleFrac)
                {
                    float sn = s / nacelleFrac;
                    sEngine = 0.0f;
                    nacelleTaper = Mathf.Lerp(0.72f, 1.0f, Mathf.Pow(sn, 0.7f));
                }
                else
                {
                    sEngine = (s - nacelleFrac) / (1.0f - nacelleFrac);
                }
            }

            float rx = rBase;
            float rz = rBase;
            float zOff = 0f;

            if (arch == EngineArchitecture.Radial)
            {
                float barrelCrown = (subStyle == 2) ? 0.08f : 0.055f; // 4-Row Wasp Major has slightly stepped crown
                float env = (1.0f + barrelCrown * Mathf.Sin(sEngine * Mathf.PI)) * nacelleTaper;
                if (sEngine > 0.82f)
                {
                    float tLip = (sEngine - 0.82f) / 0.18f;
                    env *= Mathf.Lerp(1.0f, 0.74f, tLip * tLip);
                }
                rx = rBase * env;
                rz = rBase * env;
            }
            else if (arch == EngineArchitecture.VInline)
            {
                float taper = Mathf.Lerp(nacelleTaper, spinR / rBase, Mathf.Pow(sEngine, 1.35f));
                float vBank = 0f;
                if (subStyle == 0)
                {
                    // Upright V-12 (Merlin / Griffon): upper shoulder banks (ct > 0)
                    if (ct > 0.12f && sEngine > 0.08f && sEngine < 0.86f)
                        vBank = 0.13f * rBase * Mathf.Sin((sEngine - 0.08f) / 0.78f * Mathf.PI) * Mathf.Abs(st) * Mathf.Pow(ct, 0.65f);
                    zOff = 0.07f * rBase * Mathf.Pow(sEngine, 1.4f);
                }
                else if (subStyle == 1)
                {
                    // Inverted V-12 (DB 605 / Jumo 213): lower cheek banks (ct < 0)
                    if (ct < -0.12f && sEngine > 0.08f && sEngine < 0.86f)
                        vBank = 0.13f * rBase * Mathf.Sin((sEngine - 0.08f) / 0.78f * Mathf.PI) * Mathf.Abs(st) * Mathf.Pow(-ct, 0.65f);
                    zOff = -0.05f * rBase * Mathf.Pow(sEngine, 1.4f);
                }
                else
                {
                    // Coupled X-24 / V-24: wide 4-bank muscular profile
                    if (sEngine > 0.06f && sEngine < 0.88f)
                        vBank = 0.15f * rBase * Mathf.Sin((sEngine - 0.06f) / 0.82f * Mathf.PI) * Mathf.Abs(Mathf.Sin(2f * theta));
                    zOff = 0.0f;
                }
                rx = rBase * taper + vBank;
                rz = rBase * (taper * 1.05f) + vBank * 0.55f;
            }
            else
            {
                // Turboprop
                float endRatio = (subStyle == 2)
                    ? Mathf.Max(spinR * 1.05f, rBase * 0.44f) / rBase // Free-turbine PT6 slim nose
                    : Mathf.Max(spinR * 1.18f, rBase * 0.58f) / rBase;
                float taper = Mathf.Lerp(nacelleTaper * 0.95f, endRatio, Mathf.Pow(sEngine, 1.15f));
                float bulb = 0.065f * Mathf.Sin(sEngine * Mathf.PI);
                rx = rBase * (taper + bulb);
                rz = rBase * (taper * 1.05f + bulb);
                zOff = (subStyle == 0) ? (-0.04f * rBase * sEngine) : 0.0f;
            }

            return new Vector3(rx * st, y, -rz * ct + zOff);
        }

        public static void BuildAllProceduralMeshes(
            ModuleProceduralPropeller m,
            Mesh cowlMesh,
            Mesh coreMesh,
            Mesh exhMesh,
            Mesh flapMesh,
            Mesh fSpinMesh,
            Mesh fBladesMesh,
            Mesh fDiscMesh,
            Mesh rSpinMesh,
            Mesh rBladesMesh,
            Mesh rDiscMesh,
            Mesh cowlColMesh,
            Mesh spinColMesh,
            float collectivePitchDeltaDeg,
            float cowlFlapOpen01,
            out float outFrontHubY,
            out float outRearHubY,
            out float outAftNodeY,
            out float outFwdNodeY)
        {
            EngineArchitecture arch = (EngineArchitecture)Mathf.Clamp(m.architectureIndex, 0, 2);
            int subStyle = Mathf.Clamp(m.subStyleIndex, 0, 2);
            NacelleStyle nacelle = (NacelleStyle)Mathf.Clamp(m.nacelleIndex, 0, 2);
            BladePlanform planform = (BladePlanform)Mathf.Clamp(m.bladePlanformIndex, 0, 2);
            SpinnerStyle spinnerStyle = (SpinnerStyle)Mathf.Clamp(m.spinnerStyleIndex, 0, 3);

            float cowlD = Mathf.Clamp(m.cowlDiameter, 0.45f, 3.0f);
            float baseCowlL = Mathf.Clamp(m.cowlLength, 0.50f, 5.0f);
            float nacelleMult = (nacelle == NacelleStyle.StreamlinedTankNacelle) ? 1.55f :
                                ((nacelle == NacelleStyle.ShortWingNacelle) ? 1.25f : 1.0f);
            float totalCowlL = baseCowlL * nacelleMult;

            float propD = Mathf.Clamp(m.propDiameter, 1.10f, 6.50f);
            int blades = Mathf.Clamp(m.bladeCount, 2, 8);
            bool contra = m.isContraRotating;
            bool pusher = m.isPusher;

            float rBase = 0.5f * cowlD;
            float halfL = 0.5f * totalCowlL;
            float yAft = -halfL;
            float yFwd = halfL;

            float spinR;
            float spinL;
            ComputeSpinnerDims(arch, spinnerStyle, cowlD, out spinR, out spinL);

            RuntimeMeshBuffer cowlMb = new RuntimeMeshBuffer();
            RuntimeMeshBuffer coreMb = new RuntimeMeshBuffer();
            RuntimeMeshBuffer exhMb = new RuntimeMeshBuffer();
            RuntimeMeshBuffer flapMb = new RuntimeMeshBuffer();

            int nS = 32;
            int nT = 40;
            float epsS = 1.0f / (nS * 4.0f);
            float epsT = (Mathf.PI * 2f) / (nT * 4.0f);

            // 1. Loft Outer Cowling
            int[,] grid = new int[nS + 1, nT + 1];
            for (int i = 0; i <= nS; i++)
            {
                float s = (float)i / nS;
                float vUv = Mathf.Lerp(0.02f, 0.43f, s);
                for (int j = 0; j <= nT; j++)
                {
                    float uFrac = (float)j / nT;
                    float theta = uFrac * Mathf.PI * 2f;
                    Vector3 pos = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, s, theta);
                    Vector3 pS1 = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, Mathf.Min(1f, s + epsS), theta);
                    Vector3 pS0 = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, Mathf.Max(0f, s - epsS), theta);
                    Vector3 pT1 = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, s, theta + epsT);
                    Vector3 pT0 = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, s, theta - epsT);

                    Vector3 nrm = Vector3.Cross(pT1 - pT0, pS1 - pS0);
                    if (pos.x * nrm.x + pos.z * nrm.z < 0f)
                        nrm = -nrm;

                    grid[i, j] = cowlMb.AddVertex(pos, new Vector2(uFrac, vUv), nrm);
                }
            }

            for (int i = 0; i < nS; i++)
            {
                for (int j = 0; j < nT; j++)
                {
                    cowlMb.AddQuad(grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]);
                }
            }

            // Cap aft firewall & forward cowling face
            int aftCenter = cowlMb.AddVertex(new Vector3(0f, yAft, 0f), new Vector2(0.62f, 0.55f), Vector3.down);
            int aftRingStart = cowlMb.verts.Count;
            for (int j = 0; j <= nT; j++)
            {
                float theta = ((float)j / nT) * Mathf.PI * 2f;
                Vector3 pos = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, 0f, theta);
                cowlMb.AddVertex(pos, new Vector2(0.62f, 0.55f), Vector3.down);
            }
            for (int j = 0; j < nT; j++)
                cowlMb.AddTri(aftCenter, aftRingStart + j + 1, aftRingStart + j);

            float fwdCapY = yFwd - (arch == EngineArchitecture.Radial ? 0.14f * baseCowlL : 0f);
            int fwdCenter = cowlMb.AddVertex(new Vector3(0f, fwdCapY, 0f), new Vector2(0.88f, 0.55f), Vector3.up);
            int fwdRingStart = cowlMb.verts.Count;
            for (int j = 0; j <= nT; j++)
            {
                float theta = ((float)j / nT) * Mathf.PI * 2f;
                Vector3 pos = EvalCowlingProfile(arch, subStyle, nacelle, rBase, spinR, yAft, yFwd, 1f, theta);
                cowlMb.AddVertex(pos, new Vector2(0.88f, 0.55f), Vector3.up);
            }
            for (int j = 0; j < nT; j++)
                cowlMb.AddTri(fwdCenter, fwdRingStart + j, fwdRingStart + j + 1);

            // 2. Architecture-Specific Details (Cylinders, Intakes, Radiators, Exhausts, Cowl Flaps)
            float yEngStart = yFwd - baseCowlL;
            if (arch == EngineArchitecture.Radial)
            {
                // Crankcase dome inside NACA throat
                AddFrustum(
                    coreMb,
                    new Vector3(0f, yFwd - 0.38f * baseCowlL, 0f),
                    new Vector3(0f, yFwd + 0.02f * baseCowlL, 0f),
                    rBase * 0.42f,
                    spinR * 0.92f,
                    0.52f, 0.68f, 0.47f, 0.63f,
                    18, false, true);

                int rows = PropellerPhysicsEngine.CylinderRows((int)arch, subStyle);
                int cylPerRow = PropellerPhysicsEngine.CylindersPerRow(m);
                float cylScale = Mathf.Sqrt(9f / cylPerRow); // fewer, bigger-looking cylinders
                for (int rIdx = 0; rIdx < rows; rIdx++)
                {
                    float yCyl = yFwd - (0.12f + 0.13f * rIdx) * baseCowlL;
                    for (int cIdx = 0; cIdx < cylPerRow; cIdx++)
                    {
                        float ang = (cIdx + 0.35f * rIdx) * (Mathf.PI * 2f / cylPerRow);
                        float dx = Mathf.Sin(ang);
                        float dz = -Mathf.Cos(ang);
                        Vector3 pIn = new Vector3(dx * rBase * 0.34f, yCyl, dz * rBase * 0.34f);
                        Vector3 pOut = new Vector3(dx * rBase * 0.84f, yCyl, dz * rBase * 0.84f);
                        AddFrustum(coreMb, pIn, pOut, rBase * 0.125f * cylScale, rBase * 0.14f * cylScale, 0.05f, 0.45f, 0.46f, 0.64f, 10, false, true);

                        for (int side = -1; side <= 1; side += 2)
                        {
                            float tx = Mathf.Cos(ang) * side * rBase * 0.045f;
                            float tz = Mathf.Sin(ang) * side * rBase * 0.045f;
                            Vector3 pr0 = new Vector3(dx * rBase * 0.35f + tx, yCyl + 0.04f * baseCowlL, dz * rBase * 0.35f + tz);
                            Vector3 pr1 = new Vector3(dx * rBase * 0.78f + tx, yCyl + 0.015f * baseCowlL, dz * rBase * 0.78f + tz);
                            AddFrustum(coreMb, pr0, pr1, rBase * 0.016f, rBase * 0.016f, 0.68f, 0.74f, 0.48f, 0.62f, 6, false, false);
                        }
                    }
                }

                // Carburetor / oil cooler ventral scoop & collector exhaust stubs
                AddFrustum(
                    exhMb,
                    new Vector3(0f, yEngStart + 0.16f * baseCowlL, rBase * 0.90f),
                    new Vector3(0f, yFwd - 0.18f * baseCowlL, rBase * 0.86f),
                    rBase * 0.18f, rBase * 0.20f,
                    0.20f, 0.40f, 0.10f, 0.35f, 12, true, true);

                for (int side = -1; side <= 1; side += 2)
                {
                    Vector3 p0 = new Vector3(side * rBase * 0.72f, yEngStart + 0.22f * baseCowlL, rBase * 0.54f);
                    Vector3 p1 = new Vector3(side * rBase * 0.86f, yEngStart - 0.04f * baseCowlL, rBase * 0.62f);
                    AddFrustum(exhMb, p0, p1, rBase * 0.09f, rBase * 0.08f, 0.10f, 0.90f, 0.66f, 0.79f, 10, false, true);
                }

            }
            else if (arch == EngineArchitecture.VInline)
            {
                // Ejector exhaust stubs
                float zExhaust = (subStyle == 1) ? (rBase * 0.28f) : (-rBase * 0.18f);
                int rowsPerSide = (subStyle == 2) ? 2 : 1;
                int stubs = PropellerPhysicsEngine.CylindersPerRow(m); // one ejector stub per cylinder
                for (int side = -1; side <= 1; side += 2)
                {
                    for (int rRow = 0; rRow < rowsPerSide; rRow++)
                    {
                        float zRow = zExhaust + rRow * (rBase * 0.36f);
                        for (int k = 0; k < stubs; k++)
                        {
                            float frac = (k + 0.5f) / stubs;
                            float ySt = Mathf.Lerp(yEngStart + 0.18f * baseCowlL, yFwd - 0.20f * baseCowlL, frac);
                            float rLoc = Mathf.Lerp(rBase * 0.86f, spinR * 1.35f, frac);
                            Vector3 p0 = new Vector3(side * rLoc * 0.88f, ySt, zRow);
                            Vector3 p1 = new Vector3(side * rLoc * 1.12f, ySt - 0.06f * baseCowlL, zRow);
                            AddFrustum(exhMb, p0, p1, rBase * 0.055f, rBase * 0.048f, 0.10f, 0.90f, 0.66f, 0.79f, 8, false, true);
                        }
                    }
                }

                if (subStyle == 1)
                {
                    // Inverted V-12 (DB 605): Port-side supercharger ram-air horn intake + compact oil cooler
                    AddFrustum(
                        coreMb,
                        new Vector3(-rBase * 0.90f, yEngStart + 0.25f * baseCowlL, -rBase * 0.05f),
                        new Vector3(-rBase * 0.84f, yFwd - 0.35f * baseCowlL, -rBase * 0.05f),
                        rBase * 0.14f, rBase * 0.18f,
                        0.15f, 0.45f, 0.08f, 0.36f, 12, true, true);
                }

                // Ventral Meredith radiator bath & articulated exit flap
                AddFrustum(
                    coreMb,
                    new Vector3(0f, yEngStart + 0.12f * baseCowlL, rBase * 0.85f),
                    new Vector3(0f, yFwd - 0.28f * baseCowlL, rBase * 0.72f),
                    rBase * 0.32f, rBase * 0.28f,
                    0.15f, 0.45f, 0.08f, 0.36f, 14, true, true);
            }
            else
            {
                // Turboprop Details
                if (subStyle == 0)
                {
                    // Chin-Intake (Allison T56) + twin canted jet tailpipes
                    AddFrustum(
                        coreMb,
                        new Vector3(0f, yEngStart + 0.25f * baseCowlL, rBase * 0.66f),
                        new Vector3(0f, yFwd - 0.05f * baseCowlL, rBase * 0.56f),
                        rBase * 0.34f, rBase * 0.38f,
                        0.76f, 0.98f, 0.46f, 0.64f, 16, true, true);
                    for (int side = -1; side <= 1; side += 2)
                    {
                        Vector3 p0 = new Vector3(side * rBase * 0.68f, yEngStart + 0.35f * baseCowlL, rBase * 0.24f);
                        Vector3 p1 = new Vector3(side * rBase * 0.92f, yEngStart + 0.04f * baseCowlL, rBase * 0.34f);
                        AddFrustum(exhMb, p0, p1, rBase * 0.18f, rBase * 0.16f, 0.10f, 0.90f, 0.66f, 0.79f, 14, false, true);
                    }
                }
                else if (subStyle == 1)
                {
                    // Annular-Inlet (NK-12 / Double Mamba) + quad angled turbine exhaust stacks
                    AddFrustum(
                        coreMb,
                        new Vector3(0f, yFwd - 0.18f * baseCowlL, 0f),
                        new Vector3(0f, yFwd + 0.01f * baseCowlL, 0f),
                        rBase * 0.68f, rBase * 0.64f,
                        0.76f, 0.98f, 0.46f, 0.64f, 20, false, true);
                    for (int side = -1; side <= 1; side += 2)
                    {
                        for (int k = 0; k < 2; k++)
                        {
                            float yEx = yEngStart + (0.22f + 0.22f * k) * baseCowlL;
                            Vector3 p0 = new Vector3(side * rBase * 0.72f, yEx, (k == 0 ? 1f : -1f) * rBase * 0.22f);
                            Vector3 p1 = new Vector3(side * rBase * 0.98f, yEx - 0.12f * baseCowlL, (k == 0 ? 1f : -1f) * rBase * 0.28f);
                            AddFrustum(exhMb, p0, p1, rBase * 0.16f, rBase * 0.14f, 0.10f, 0.90f, 0.66f, 0.79f, 12, false, true);
                        }
                    }
                }
                else
                {
                    // Free-Turbine (PT6): forward twin mammal-ear exhaust stacks behind spinner
                    for (int side = -1; side <= 1; side += 2)
                    {
                        Vector3 p0 = new Vector3(side * spinR * 0.85f, yFwd - 0.14f * baseCowlL, 0f);
                        Vector3 p1 = new Vector3(side * (spinR * 1.45f), yFwd - 0.24f * baseCowlL, 0f);
                        AddFrustum(exhMb, p0, p1, rBase * 0.14f, rBase * 0.12f, 0.10f, 0.90f, 0.66f, 0.79f, 12, false, true);
                    }
                }

            }
            AddCowlFlaps(flapMb, arch, rBase, yEngStart, baseCowlL, cowlFlapOpen01);

            // If Pusher mode is enabled, mirror cowling/core/exhaust/flap along Y so propeller hub is at -Y (aft)
            if (pusher)
            {
                MirrorBufferY(cowlMb);
                MirrorBufferY(coreMb);
                MirrorBufferY(exhMb);
                MirrorBufferY(flapMb);
            }

            cowlMb.ApplyToMesh(cowlMesh, "ROPP_Cowling");
            coreMb.ApplyToMesh(coreMesh, "ROPP_CoreDetails");
            exhMb.ApplyToMesh(exhMesh, "ROPP_ExhaustRadiator");
            flapMb.ApplyToMesh(flapMesh, "ROPP_CowlFlaps");

            // 3. Build Hub Meshes (Spinner, Twisted Airfoil Blades, Blur Disc)
            int damage = DamageSeed(m);
            BuildHubSubMeshes(
                spinR, spinL, propD, blades, planform, spinnerStyle,
                false, FrontBladeSense(m), collectivePitchDeltaDeg, pusher,
                fSpinMesh, fBladesMesh, fDiscMesh, damage);

            BuildHubSubMeshes(
                spinR * 1.02f, spinL * 0.42f, propD, blades, planform, spinnerStyle,
                true, -FrontBladeSense(m), collectivePitchDeltaDeg, pusher,
                rSpinMesh, rBladesMesh, rDiscMesh, damage);

            // 4. Build Convex Colliders for FAR Voxelization
            RuntimeMeshBuffer cowlColMb = new RuntimeMeshBuffer();
            float rFrontCol = rBase * (arch == EngineArchitecture.Radial ? 0.85f : 0.55f);
            AddFrustum(
                cowlColMb,
                new Vector3(0f, yAft, 0f),
                new Vector3(0f, yFwd, 0f),
                pusher ? rFrontCol : rBase,
                pusher ? rBase : rFrontCol,
                0f, 1f, 0f, 1f, 16, true, true);
            cowlColMb.ApplyToMesh(cowlColMesh, "ROPP_CowlingCollider");

            RuntimeMeshBuffer spinColMb = new RuntimeMeshBuffer();
            Vector3 spStart = new Vector3(0f, pusher ? yAft : yFwd, 0f);
            Vector3 spEnd = new Vector3(0f, pusher ? (yAft - spinL) : (yFwd + spinL), 0f);
            AddFrustum(spinColMb, spStart, spEnd, spinR, spinR * 0.15f, 0f, 1f, 0f, 1f, 12, true, true);
            spinColMb.ApplyToMesh(spinColMesh, "ROPP_SpinnerCollider");

            if (!pusher)
            {
                outFrontHubY = yFwd + (contra ? 0.18f * spinL : 0.0f);
                outRearHubY = yFwd - 0.06f * spinL;
                outAftNodeY = yAft;
                outFwdNodeY = yFwd + spinL;
            }
            else
            {
                outFrontHubY = yAft - (contra ? 0.18f * spinL : 0.0f);
                outRearHubY = yAft + 0.06f * spinL;
                outAftNodeY = yAft - spinL;
                outFwdNodeY = yFwd;
            }
        }

        /// <summary>Cowl flaps (radials), radiator exit flap (inlines) or the fixed exhaust ring (turboprops).</summary>
        private static void AddCowlFlaps(RuntimeMeshBuffer flapMb, EngineArchitecture arch, float rBase, float yEngStart, float baseCowlL, float open01)
        {
            float open = Mathf.Clamp01(open01);
            if (arch == EngineArchitecture.Radial)
            {
                AddFrustum(flapMb,
                    new Vector3(0f, yEngStart + 0.18f * baseCowlL, 0f),
                    new Vector3(0f, yEngStart + 0.02f * baseCowlL, 0f),
                    rBase * 1.005f, rBase * (1.02f + 0.14f * open),
                    0.0f, 1.0f, 0.04f, 0.12f, 24, false, false);
            }
            else if (arch == EngineArchitecture.VInline)
            {
                AddFrustum(flapMb,
                    new Vector3(0f, yEngStart + 0.15f * baseCowlL, rBase * 0.88f),
                    new Vector3(0f, yEngStart + 0.01f * baseCowlL, rBase * (0.94f + 0.12f * open)),
                    rBase * 0.26f, rBase * 0.24f,
                    0.20f, 0.40f, 0.04f, 0.12f, 10, false, true);
            }
            else
            {
                AddFrustum(flapMb,
                    new Vector3(0f, yEngStart + 0.12f * baseCowlL, 0f),
                    new Vector3(0f, yEngStart + 0.02f * baseCowlL, 0f),
                    rBase * 0.95f, rBase * 0.92f,
                    0.0f, 1.0f, 0.04f, 0.10f, 18, false, false);
            }
        }

        /// <summary>Rebuilds only the cowl-flap mesh (flaps move in flight; the rest of the engine doesn't).</summary>
        public static void BuildFlapsOnly(ModuleProceduralPropeller m, Mesh flapMesh, float cowlFlapOpen01)
        {
            if (flapMesh == null)
                return;
            EngineArchitecture arch = (EngineArchitecture)Mathf.Clamp(m.architectureIndex, 0, 2);
            NacelleStyle nacelle = (NacelleStyle)Mathf.Clamp(m.nacelleIndex, 0, 2);
            float cowlD = Mathf.Clamp(m.cowlDiameter, 0.45f, 3.0f);
            float baseCowlL = Mathf.Clamp(m.cowlLength, 0.50f, 5.0f);
            float nacelleMult = (nacelle == NacelleStyle.StreamlinedTankNacelle) ? 1.55f :
                                ((nacelle == NacelleStyle.ShortWingNacelle) ? 1.25f : 1.0f);
            float yFwd = 0.5f * baseCowlL * nacelleMult;
            RuntimeMeshBuffer flapMb = new RuntimeMeshBuffer();
            AddCowlFlaps(flapMb, arch, 0.5f * cowlD, yFwd - baseCowlL, baseCowlL, cowlFlapOpen01);
            if (m.isPusher)
                MirrorBufferY(flapMb);
            flapMb.ApplyToMesh(flapMesh, "ROPP_CowlFlaps");
        }

        private static void ComputeSpinnerDims(EngineArchitecture arch, SpinnerStyle spinnerStyle, float cowlD, out float spinR, out float spinL)
        {
            float rBase = 0.5f * cowlD;
            spinL = Mathf.Clamp(cowlD * 0.48f, 0.28f, 0.90f);
            if (spinnerStyle == SpinnerStyle.ExposedHub)
                spinL *= 0.42f;
            spinR = rBase * (arch == EngineArchitecture.Radial ? 0.36f :
                            (arch == EngineArchitecture.VInline ? 0.44f : 0.38f));
        }

        /// <summary>
        /// Rebuilds only the blade meshes for a new collective pitch. Used in flight so throttle and
        /// governor changes don't regenerate the whole nacelle every frame.
        /// </summary>
        public static void BuildBladesOnly(ModuleProceduralPropeller m, Mesh fBladesMesh, Mesh rBladesMesh, float collectivePitchDeltaDeg)
        {
            EngineArchitecture arch = (EngineArchitecture)Mathf.Clamp(m.architectureIndex, 0, 2);
            SpinnerStyle spinnerStyle = (SpinnerStyle)Mathf.Clamp(m.spinnerStyleIndex, 0, 3);
            BladePlanform planform = (BladePlanform)Mathf.Clamp(m.bladePlanformIndex, 0, 2);
            float cowlD = Mathf.Clamp(m.cowlDiameter, 0.45f, 3.0f);
            float propD = Mathf.Clamp(m.propDiameter, 1.10f, 6.50f);
            int blades = Mathf.Clamp(m.bladeCount, 2, 8);
            float spinR;
            float spinL;
            ComputeSpinnerDims(arch, spinnerStyle, cowlD, out spinR, out spinL);

            int damage = DamageSeed(m);
            BuildHubSubMeshes(spinR, spinL, propD, blades, planform, spinnerStyle,
                false, FrontBladeSense(m), collectivePitchDeltaDeg, m.isPusher, null, fBladesMesh, null, damage);
            if (m.isContraRotating && rBladesMesh != null)
                BuildHubSubMeshes(spinR * 1.02f, spinL * 0.42f, propD, blades, planform, spinnerStyle,
                    true, -FrontBladeSense(m), collectivePitchDeltaDeg, m.isPusher, null, rBladesMesh, null, damage);
        }

        /// <summary>
        /// Handedness of the front blades. A blade is built with its leading edge forward on the
        /// +sense tangent side (scimitar tips swept the other way), so it must move towards
        /// +sense x (cos a, 0, sin a). The hub turns by SpinSign about +Y (Unity: positive =
        /// clockwise seen from in front), which moves a blade at angle a towards -SpinSign x that
        /// tangent: so sense = -SpinSign. The rear propeller of a contra pair is the mirror image.
        /// </summary>
        private static float FrontBladeSense(ModuleProceduralPropeller m)
        {
            return -m.SpinSign;
        }

        /// <summary>Test hook: receives each blade buffer before it goes into a Mesh (null in the game).</summary>
        public static Action<RuntimeMeshBuffer, bool> DebugBladeSink;

        /// <summary>Quaternion.AngleAxis in managed code (the Unity one is native-only).</summary>
        private static Quaternion AxisAngle(float degrees, Vector3 axis)
        {
            Vector3 a = axis.normalized;
            float h = 0.5f * degrees * Mathf.Deg2Rad;
            float sn = Mathf.Sin(h);
            return new Quaternion(a.x * sn, a.y * sn, a.z * sn, Mathf.Cos(h));
        }

        /// <summary>Seed of the broken-blade shapes (0 = intact).</summary>
        private static int DamageSeed(ModuleProceduralPropeller m)
        {
            if (!m.propDamaged)
                return 0;
            return m.propDamageSeed != 0 ? m.propDamageSeed : 1;
        }

        /// <summary>
        /// Positions (part space) and outward/aft directions of the left and right exhaust outlets,
        /// matching the stubs/tailpipes built in BuildAllProceduralMeshes. Used for smoke and puffs.
        /// </summary>
        public static void GetExhaustPorts(ModuleProceduralPropeller m, out Vector3 posL, out Vector3 dirL, out Vector3 posR, out Vector3 dirR)
        {
            EngineArchitecture arch = (EngineArchitecture)Mathf.Clamp(m.architectureIndex, 0, 2);
            int subStyle = Mathf.Clamp(m.subStyleIndex, 0, 2);
            NacelleStyle nacelle = (NacelleStyle)Mathf.Clamp(m.nacelleIndex, 0, 2);
            SpinnerStyle spinnerStyle = (SpinnerStyle)Mathf.Clamp(m.spinnerStyleIndex, 0, 3);
            float cowlD = Mathf.Clamp(m.cowlDiameter, 0.45f, 3.0f);
            float baseCowlL = Mathf.Clamp(m.cowlLength, 0.50f, 5.0f);
            float nacelleMult = (nacelle == NacelleStyle.StreamlinedTankNacelle) ? 1.55f :
                                ((nacelle == NacelleStyle.ShortWingNacelle) ? 1.25f : 1.0f);
            float halfL = 0.5f * baseCowlL * nacelleMult;
            float yFwd = halfL;
            float yEngStart = yFwd - baseCowlL;
            float rBase = 0.5f * cowlD;
            float spinR;
            float spinL;
            ComputeSpinnerDims(arch, spinnerStyle, cowlD, out spinR, out spinL);

            Vector3 p0;
            Vector3 p1;
            if (arch == EngineArchitecture.Radial)
            {
                p0 = new Vector3(rBase * 0.72f, yEngStart + 0.22f * baseCowlL, rBase * 0.54f);
                p1 = new Vector3(rBase * 0.86f, yEngStart - 0.04f * baseCowlL, rBase * 0.62f);
            }
            else if (arch == EngineArchitecture.VInline)
            {
                float zExhaust = (subStyle == 1) ? (rBase * 0.28f) : (-rBase * 0.18f);
                float ySt = Mathf.Lerp(yEngStart + 0.18f * baseCowlL, yFwd - 0.20f * baseCowlL, 0.5f);
                float rLoc = Mathf.Lerp(rBase * 0.86f, spinR * 1.35f, 0.5f);
                p0 = new Vector3(rLoc * 0.88f, ySt, zExhaust);
                p1 = new Vector3(rLoc * 1.12f, ySt - 0.06f * baseCowlL, zExhaust);
            }
            else if (subStyle == 0)
            {
                p0 = new Vector3(rBase * 0.68f, yEngStart + 0.35f * baseCowlL, rBase * 0.24f);
                p1 = new Vector3(rBase * 0.92f, yEngStart + 0.04f * baseCowlL, rBase * 0.34f);
            }
            else if (subStyle == 1)
            {
                p0 = new Vector3(rBase * 0.72f, yEngStart + 0.22f * baseCowlL, rBase * 0.22f);
                p1 = new Vector3(rBase * 0.98f, yEngStart + 0.10f * baseCowlL, rBase * 0.28f);
            }
            else
            {
                p0 = new Vector3(spinR * 0.85f, yFwd - 0.14f * baseCowlL, 0f);
                p1 = new Vector3(spinR * 1.45f, yFwd - 0.24f * baseCowlL, 0f);
            }

            Vector3 d = (p1 - p0).normalized;
            if (m.isPusher)
            {
                p1.y = -p1.y;
                d.y = -d.y;
            }
            posR = p1;
            dirR = d;
            posL = new Vector3(-p1.x, p1.y, p1.z);
            dirL = new Vector3(-d.x, d.y, d.z);
        }

        /// <summary>
        /// Starboard exhaust flame points (same space as GetExhaustPorts; mirror X for port side).
        /// V-12/X-24s get three points spread along the ejector stub row (which follows the cowl
        /// taper); radials and turboprops a single point at the outlet.
        /// </summary>
        public static Vector3[] GetExhaustFlamePoints(ModuleProceduralPropeller m)
        {
            Vector3 pL, dL, pR, dR;
            GetExhaustPorts(m, out pL, out dL, out pR, out dR);
            EngineArchitecture arch = (EngineArchitecture)Mathf.Clamp(m.architectureIndex, 0, 2);
            if (arch != EngineArchitecture.VInline)
                return new Vector3[] { pR };

            int subStyle = Mathf.Clamp(m.subStyleIndex, 0, 2);
            NacelleStyle nacelle = (NacelleStyle)Mathf.Clamp(m.nacelleIndex, 0, 2);
            SpinnerStyle spinnerStyle = (SpinnerStyle)Mathf.Clamp(m.spinnerStyleIndex, 0, 3);
            float cowlD = Mathf.Clamp(m.cowlDiameter, 0.45f, 3.0f);
            float baseCowlL = Mathf.Clamp(m.cowlLength, 0.50f, 5.0f);
            float nacelleMult = (nacelle == NacelleStyle.StreamlinedTankNacelle) ? 1.55f :
                                ((nacelle == NacelleStyle.ShortWingNacelle) ? 1.25f : 1.0f);
            float yFwd = 0.5f * baseCowlL * nacelleMult;
            float yEngStart = yFwd - baseCowlL;
            float rBase = 0.5f * cowlD;
            float spinR;
            float spinL;
            ComputeSpinnerDims(arch, spinnerStyle, cowlD, out spinR, out spinL);
            float zExhaust = (subStyle == 1) ? (rBase * 0.28f) : (-rBase * 0.18f);

            float[] ts = { 0.12f, 0.5f, 0.88f };
            Vector3[] pts = new Vector3[ts.Length];
            for (int i = 0; i < ts.Length; i++)
            {
                float y = Mathf.Lerp(yEngStart + 0.18f * baseCowlL, yFwd - 0.20f * baseCowlL, ts[i]) - 0.06f * baseCowlL;
                float r = Mathf.Lerp(rBase * 0.86f, spinR * 1.35f, ts[i]);
                pts[i] = new Vector3(r * 1.12f, m.isPusher ? -y : y, zExhaust);
            }
            return pts;
        }

        private static void BuildHubSubMeshes(
            float hubSpinR,
            float hubSpinL,
            float propD,
            int blades,
            BladePlanform planform,
            SpinnerStyle spinnerStyle,
            bool isRear,
            float sense,
            float collectivePitchDeltaDeg,
            bool pusher,
            Mesh spinMesh,
            Mesh bladesMesh,
            Mesh discMesh,
            int damageSeed)
        {
            RuntimeMeshBuffer spMb = new RuntimeMeshBuffer();
            RuntimeMeshBuffer blMb = new RuntimeMeshBuffer();
            RuntimeMeshBuffer dcMb = new RuntimeMeshBuffer();

            int spSegs = 24;
            int spStacks = 12;
            int[,] spGrid = new int[spStacks + 1, spSegs + 1];

            for (int i = 0; i <= spStacks; i++)
            {
                float t = (float)i / spStacks;
                float y;
                float r;
                if (isRear)
                {
                    y = Mathf.Lerp(-0.45f * hubSpinL, 0.45f * hubSpinL, t);
                    r = Mathf.Lerp(hubSpinR * 1.06f, hubSpinR * 0.96f, t);
                }
                else
                {
                    y = t * hubSpinL;
                    if (spinnerStyle == SpinnerStyle.RoundedDome || spinnerStyle == SpinnerStyle.ExposedHub)
                        r = hubSpinR * Mathf.Sqrt(Mathf.Max(0f, 1f - t * t));
                    else if (spinnerStyle == SpinnerStyle.HollowCannon)
                        r = Mathf.Lerp(hubSpinR, hubSpinR * 0.28f, Mathf.Pow(t, 1.35f));
                    else
                        r = hubSpinR * Mathf.Sqrt(Mathf.Max(0f, 1f - Mathf.Pow(t, 1.75f)));
                }

                float vUv = Mathf.Lerp(0.81f, 0.99f, t);
                for (int j = 0; j <= spSegs; j++)
                {
                    float uFrac = (float)j / spSegs;
                    float ang = uFrac * Mathf.PI * 2f;
                    float st = Mathf.Sin(ang);
                    float ct = -Mathf.Cos(ang);
                    Vector3 pos = new Vector3(r * st, y, r * ct);
                    Vector3 nrm = new Vector3(st, isRear ? 0.08f : 0.35f * t, ct).normalized;
                    spGrid[i, j] = spMb.AddVertex(pos, new Vector2(Mathf.Lerp(0.71f, 0.99f, uFrac), vUv), nrm);
                }
            }

            for (int i = 0; i < spStacks; i++)
            {
                for (int j = 0; j < spSegs; j++)
                {
                    spMb.AddQuad(spGrid[i, j], spGrid[i + 1, j], spGrid[i + 1, j + 1], spGrid[i, j + 1]);
                }
            }

            float baseY = isRear ? (-0.45f * hubSpinL) : 0f;
            float r0Cap = isRear ? (hubSpinR * 1.06f) : hubSpinR;
            int baseC = spMb.AddVertex(new Vector3(0f, baseY, 0f), new Vector2(0.85f, 0.82f), Vector3.down);
            int baseRing = spMb.verts.Count;
            for (int j = 0; j <= spSegs; j++)
            {
                float ang = ((float)j / spSegs) * Mathf.PI * 2f;
                spMb.AddVertex(new Vector3(r0Cap * Mathf.Sin(ang), baseY, -r0Cap * Mathf.Cos(ang)), new Vector2(0.85f, 0.82f), Vector3.down);
            }
            for (int j = 0; j < spSegs; j++)
                spMb.AddTri(baseC, baseRing + j + 1, baseRing + j);

            if (isRear || spinnerStyle == SpinnerStyle.HollowCannon)
            {
                float topY = isRear ? (0.45f * hubSpinL) : hubSpinL;
                float rTop = isRear ? (hubSpinR * 0.96f) : (hubSpinR * 0.28f);
                int topC = spMb.AddVertex(new Vector3(0f, topY, 0f), new Vector2(0.85f, 0.50f), Vector3.up);
                int topRing = spMb.verts.Count;
                for (int j = 0; j <= spSegs; j++)
                {
                    float ang = ((float)j / spSegs) * Mathf.PI * 2f;
                    spMb.AddVertex(new Vector3(rTop * Mathf.Sin(ang), topY, -rTop * Mathf.Cos(ang)), new Vector2(0.85f, 0.50f), Vector3.up);
                }
                for (int j = 0; j < spSegs; j++)
                    spMb.AddTri(topC, topRing + j, topRing + j + 1);
            }

            // 3D Twisted Airfoil Propeller Blades
            float propR = 0.5f * propD;
            float rRoot = hubSpinR * 0.80f;
            float yHubPlane = isRear ? 0f : (0.26f * hubSpinL);
            // A pusher's hub faces aft (spinner and disc are mirrored below), but its blades must
            // keep their handedness to push air aft while turning the same way, so they are only
            // moved to the mirrored hub plane, not mirrored themselves
            float bladeY = pusher ? -yHubPlane : yHubPlane;
            int nSpan = 9;
            int nChord = 10;

            for (int bIdx = 0; bIdx < blades; bIdx++)
            {
                float baseAng = (bIdx + (isRear ? 0.5f : 0f)) * (Mathf.PI * 2f / blades);
                float rxDir = Mathf.Sin(baseAng);
                float rzDir = -Mathf.Cos(baseAng);
                float txDir = Mathf.Cos(baseAng) * sense;
                float tzDir = Mathf.Sin(baseAng) * sense;

                // Ground-strike damage (damageSeed != 0). Aluminium blades fold about their flat,
                // weak axis (the chord line) at full width: most fold aft, some forward, either as a
                // sharp fold or as a curl that tightens towards the tip into a hook; some also lose
                // their tip with a torn edge. Built by walking along the span and rotating every
                // section with the bend, so the blade keeps its width and thickness as it folds.
                bool damaged = damageSeed != 0;
                int nS = damaged ? 30 : nSpan;
                float keep = 1f, bendStart = 1f, bendMax = 0f, fold = 0f, jag = 0f;
                System.Random drng = null;
                if (damaged)
                {
                    drng = new System.Random(damageSeed * 31 + bIdx * 7919 + (isRear ? 104729 : 0));
                    float dirSign = drng.NextDouble() < 0.78 ? 1f : -1f;          // aft / forward
                    bool torn = drng.NextDouble() < 0.25;
                    keep = torn ? 0.70f + 0.20f * (float)drng.NextDouble() : 1f;
                    bendStart = 0.35f + 0.30f * (float)drng.NextDouble();
                    bendMax = dirSign * (60f + 140f * (float)drng.NextDouble());   // degrees
                    fold = (float)drng.NextDouble();                               // 0 curl .. 1 sharp fold
                    jag = torn ? 0.035f : 0f;
                }
                Vector3 rHat = new Vector3(rxDir, 0f, rzDir);
                Vector3 tHat = new Vector3(txDir, 0f, tzDir);

                // Bend axis: the chord line where the bend starts, oriented so a positive bend folds the tip aft (-Y)
                Vector3 bendAxis = Vector3.up;
                if (damaged)
                {
                    float tw0 = (Mathf.Lerp(40.0f, 15.0f, bendStart) + collectivePitchDeltaDeg) * Mathf.Deg2Rad;
                    bendAxis = (tHat * Mathf.Cos(tw0) + Vector3.up * Mathf.Sin(tw0)).normalized;
                    if ((AxisAngle(10f, bendAxis) * rHat).y > 0f)
                        bendAxis = -bendAxis;
                }

                int[,] bGrid = new int[nS + 1, nChord + 1];
                float tipSweep = 0f;
                Vector3 prevC = Vector3.zero, prevP = Vector3.zero;
                float prevTheta = 0f;

                for (int iS = 0; iS <= nS; iS++)
                {
                    float s = (float)iS / nS;
                    float sEff = s * keep;
                    float rCurr = Mathf.Lerp(rRoot, propR, sEff);
                    float chord;
                    float sweep = 0f;

                    if (planform == BladePlanform.Scimitar)
                    {
                        chord = propR * (0.15f * Mathf.Sin(Mathf.PI * Mathf.Pow(sEff, 0.72f)) + 0.045f * (1f - sEff));
                        sweep = propR * 0.11f * Mathf.Pow(sEff, 2.2f);
                    }
                    else if (planform == BladePlanform.Paddle)
                    {
                        chord = propR * (0.165f * (0.35f + 0.65f * Mathf.Sin(Mathf.PI * Mathf.Pow(sEff, 0.65f))));
                    }
                    else
                    {
                        chord = propR * (0.14f * Mathf.Sin(Mathf.PI * Mathf.Pow(sEff, 0.80f)) + 0.04f * (1f - sEff));
                    }
                    if (iS == nS)
                        tipSweep = sweep;

                    float thick = chord * Mathf.Lerp(0.28f, 0.06f, Mathf.Pow(sEff, 0.65f));
                    float twistDeg = Mathf.Lerp(40.0f, 15.0f, sEff) + collectivePitchDeltaDeg;
                    float twistRad = twistDeg * Mathf.Deg2Rad;
                    float cosTw = Mathf.Cos(twistRad);
                    float sinTw = Mathf.Sin(twistRad);

                    // Bend angle along the span: a curl tightens towards the tip, a fold happens early
                    float theta = 0f;
                    if (damaged && sEff > bendStart && keep > bendStart)
                    {
                        float ub = Mathf.Clamp01((sEff - bendStart) / (keep - bendStart));
                        float curlT = ub * ub;
                        float foldT = 1f - Mathf.Pow(1f - ub, 6f);
                        theta = bendMax * Mathf.Lerp(curlT, foldT, fold);
                    }
                    Quaternion rot = AxisAngle(theta, bendAxis);

                    // Centre line: undamaged, then marched with the bend so the blade keeps its length
                    Vector3 c = rHat * rCurr + Vector3.up * bladeY;
                    Vector3 p = iS == 0 ? c : prevP + AxisAngle(0.5f * (theta + prevTheta), bendAxis) * (c - prevC);
                    prevC = c;
                    prevP = p;
                    prevTheta = theta;

                    float tear = 0f;
                    float uUv = Mathf.Lerp(0.02f, 0.69f, sEff);
                    for (int jC = 0; jC <= nChord; jC++)
                    {
                        float cFrac = (float)jC / nChord;
                        float angC = cFrac * Mathf.PI * 2f;
                        float xc = 0.5f * chord * Mathf.Cos(angC) - sweep;
                        float yc = 0.5f * thick * Mathf.Sin(angC) * (0.85f + 0.15f * Mathf.Cos(angC * 0.5f));

                        float tangOff = xc * cosTw - yc * sinTw;
                        float axialOff = xc * sinTw + yc * cosTw;
                        Vector3 local = tHat * tangOff + Vector3.up * axialOff;
                        if (drng != null && iS == nS && jag > 0f && jC < nChord)
                            tear = propR * jag * ((float)drng.NextDouble() * 2f - 1f); // torn edge
                        Vector3 pos = p + rot * (local + rHat * tear);

                        float nxLoc = Mathf.Cos(angC) * 0.25f;
                        float nyLoc = Mathf.Sin(angC);
                        float nTang = nxLoc * cosTw - nyLoc * sinTw;
                        float nAxial = nxLoc * sinTw + nyLoc * cosTw;
                        float nRad = (s > 0.92f) ? 0.15f : ((s < 0.08f) ? -0.15f : 0f);
                        Vector3 nrm = rot * (rHat * nRad + tHat * nTang + Vector3.up * nAxial).normalized;

                        float vUv = Mathf.Lerp(0.81f, 0.99f, 0.5f + 0.5f * Mathf.Cos(angC));
                        bGrid[iS, jC] = blMb.AddVertex(pos, new Vector2(uUv, vUv), nrm);
                    }
                }

                for (int iS = 0; iS < nS; iS++)
                {
                    for (int jC = 0; jC < nChord; jC++)
                    {
                        blMb.AddQuad(bGrid[iS, jC], bGrid[iS + 1, jC], bGrid[iS + 1, jC + 1], bGrid[iS, jC + 1]);
                    }
                }

                Vector3 tipPos = new Vector3(rxDir * propR - txDir * tipSweep, bladeY, rzDir * propR - tzDir * tipSweep);
                Vector3 tipNrm = new Vector3(rxDir, 0f, rzDir);
                if (damaged)
                {
                    // Close a bent or torn tip at the centre of its last section
                    Vector3 cEnd = Vector3.zero, cPrev = Vector3.zero;
                    for (int jC = 0; jC < nChord; jC++)
                    {
                        cEnd += blMb.verts[bGrid[nS, jC]];
                        cPrev += blMb.verts[bGrid[nS - 1, jC]];
                    }
                    tipPos = cEnd / nChord;
                    tipNrm = (tipPos - cPrev / nChord).normalized;
                }
                int tipC = blMb.AddVertex(tipPos, new Vector2(0.68f, 0.90f), tipNrm);
                int tipRing = blMb.verts.Count;
                for (int jC = 0; jC <= nChord; jC++)
                {
                    Vector3 vp = blMb.verts[bGrid[nS, jC]];
                    blMb.AddVertex(vp, new Vector2(0.68f, 0.90f), tipNrm);
                }
                for (int jC = 0; jC < nChord; jC++)
                    blMb.AddTri(tipC, tipRing + jC, tipRing + jC + 1);
            }

            // Rotor Blur Disc
            int discSegs = 28;
            for (int side = 0; side < 2; side++)
            {
                float ny = (side == 0) ? 1f : -1f;
                float sy = yHubPlane + 0.012f * ny;
                Vector3 sNrm = new Vector3(0f, ny, 0f);
                int cIdx = dcMb.AddVertex(new Vector3(0f, sy + 0.004f * ny, 0f), new Vector2(0.5f, 0.5f), sNrm);
                int rStart = dcMb.verts.Count;
                for (int j = 0; j <= discSegs; j++)
                {
                    float ang = ((float)j / discSegs) * Mathf.PI * 2f;
                    float st = Mathf.Sin(ang);
                    float ct = -Mathf.Cos(ang);
                    dcMb.AddVertex(
                        new Vector3(propR * st, sy, propR * ct),
                        new Vector2(0.5f + 0.49f * st, 0.5f + 0.49f * ct),
                        sNrm);
                }
                for (int j = 0; j < discSegs; j++)
                {
                    if (ny > 0f)
                        dcMb.AddTri(cIdx, rStart + j, rStart + j + 1);
                    else
                        dcMb.AddTri(cIdx, rStart + j + 1, rStart + j);
                }
            }

            if (pusher)
            {
                MirrorBufferY(spMb);
                MirrorBufferY(dcMb);
            }

            spMb.ApplyToMesh(spinMesh, isRear ? "ROPP_RearSpinner" : "ROPP_FrontSpinner");
            if (DebugBladeSink != null)
                DebugBladeSink(blMb, isRear);
            blMb.ApplyToMesh(bladesMesh, isRear ? "ROPP_RearBlades" : "ROPP_FrontBlades");
            dcMb.ApplyToMesh(discMesh, isRear ? "ROPP_RearDisc" : "ROPP_FrontDisc");
        }

        private static void MirrorBufferY(RuntimeMeshBuffer mb)
        {
            for (int i = 0; i < mb.verts.Count; i++)
            {
                Vector3 v = mb.verts[i];
                mb.verts[i] = new Vector3(v.x, -v.y, v.z);
                Vector3 n = mb.normals[i];
                mb.normals[i] = new Vector3(n.x, -n.y, n.z);
            }
            for (int t = 0; t < mb.tris.Count; t += 3)
            {
                int tmp = mb.tris[t + 1];
                mb.tris[t + 1] = mb.tris[t + 2];
                mb.tris[t + 2] = tmp;
            }
        }
    }
}
