using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>
    /// Exhaust effects built from Unity particle systems owned by the plugin (the stock
    /// fx_smokeTrail_light prefab was far too faint on a single propeller engine):
    ///   flames  - short flickering jets at every exhaust stub (local space), longer with power/WEP
    ///   smoke   - wispy trails left in the air (world space, registered with FloatingOrigin)
    ///   puff    - big smoke cloud + flame pops when a piston engine starts or coughs
    ///   sparks  - backfire flashes and prop-strike sparks
    /// </summary>
    public class EngineEffects
    {
        private static Texture2D _softTex;
        private static Material _additiveMat;
        private static Material _alphaMat;

        private Transform _portL;
        private Transform _portR;
        private readonly List<ParticleSystem> _flames = new List<ParticleSystem>();
        private readonly List<ParticleSystem> _worldSystems = new List<ParticleSystem>();
        private readonly List<GameObject> _objects = new List<GameObject>();
        private ParticleSystem _smokeL, _smokeR, _puffL, _puffR, _sparks;
        private bool _turboprop;
        private float _scale = 1f;
        private float _sinceStart = 999f;

        // ---------------------------------------------------------------- shared resources

        private static Texture2D SoftTexture()
        {
            if (_softTex != null)
                return _softTex;
            const int n = 64;
            _softTex = new Texture2D(n, n, TextureFormat.RGBA32, true);
            Color32[] px = new Color32[n * n];
            for (int y = 0; y < n; y++)
            {
                for (int x = 0; x < n; x++)
                {
                    float dx = (x + 0.5f) / n * 2f - 1f;
                    float dy = (y + 0.5f) / n * 2f - 1f;
                    float r = Mathf.Sqrt(dx * dx + dy * dy);
                    float a = Mathf.Clamp01(1f - r);
                    a = a * a * (3f - 2f * a);
                    px[y * n + x] = new Color32(255, 255, 255, (byte)(a * 255f));
                }
            }
            _softTex.SetPixels32(px);
            _softTex.Apply(true, true);
            _softTex.wrapMode = TextureWrapMode.Clamp;
            return _softTex;
        }

        private static Shader FindParticleShader(bool additive)
        {
            string[] names = additive
                ? new string[] { "KSP/Particles/Additive", "Legacy Shaders/Particles/Additive", "Particles/Additive", "Mobile/Particles/Additive" }
                : new string[] { "KSP/Particles/Alpha Blended", "Legacy Shaders/Particles/Alpha Blended", "Particles/Alpha Blended", "Mobile/Particles/Alpha Blended" };
            for (int i = 0; i < names.Length; i++)
            {
                Shader s = Shader.Find(names[i]);
                if (s != null)
                    return s;
            }
            // Shader.Find only sees shaders Unity knows by name; fall back to any loaded particle shader
            string want = additive ? "Additive" : "Alpha Blended";
            Shader[] all = Resources.FindObjectsOfTypeAll<Shader>();
            for (int i = 0; i < all.Length; i++)
            {
                string n = all[i].name;
                if (n.IndexOf("Particles", System.StringComparison.OrdinalIgnoreCase) >= 0 && n.EndsWith(want))
                    return all[i];
            }
            return null;
        }

        private static Material MakeMaterial(bool additive)
        {
            Shader s = FindParticleShader(additive);
            if (s == null)
            {
                Debug.LogWarning("[ROPlanesPlus] no particle shader found; exhaust effects disabled");
                return null;
            }
            Material m = new Material(s);
            m.mainTexture = SoftTexture();
            if (m.HasProperty("_TintColor"))
                m.SetColor("_TintColor", new Color(0.5f, 0.5f, 0.5f, 0.5f));
            Debug.Log("[ROPlanesPlus] exhaust effects use shader " + s.name);
            return m;
        }

        // ---------------------------------------------------------------- setup

        public void Init(Transform portL, Transform portR)
        {
            _portL = portL;
            _portR = portR;
            if (_additiveMat == null) _additiveMat = MakeMaterial(true);
            if (_alphaMat == null) _alphaMat = MakeMaterial(false);
            if (_additiveMat == null || _alphaMat == null || portL == null || portR == null)
                return;

            _smokeL = MakeSmoke(portL, "ROPP_SmokeL");
            _smokeR = MakeSmoke(portR, "ROPP_SmokeR");
            _puffL = MakePuff(portL, "ROPP_PuffL");
            _puffR = MakePuff(portR, "ROPP_PuffR");
            _sparks = MakeSparks(portR, "ROPP_Sparks");
            _dirt = MakeDirt(portR, "ROPP_StrikeDirt");
            _spray = MakeSpray(portR, "ROPP_StrikeSpray");
            _debris = MakeDebris(portR, "ROPP_StrikeDebris");
        }

        private ParticleSystem _dirt, _spray, _debris;
        private static Mesh _shardMesh;

        // A dust and sod cloud thrown up where the blades dig in
        private ParticleSystem MakeDirt(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _alphaMat, true, 160);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(1.8f, 3.6f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(3f, 11f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.4f, 1.6f);
            main.startColor = new ParticleSystem.MinMaxGradient(new Color(0.40f, 0.32f, 0.22f, 0.85f), new Color(0.28f, 0.25f, 0.18f, 0.9f));
            main.gravityModifier = 0.35f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Hemisphere;
            sh.radius = 0.3f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(0.42f, 0.34f, 0.24f), new Color(0.55f, 0.50f, 0.42f), 0.85f, 0f);
            ParticleSystem.SizeOverLifetimeModule sz = ps.sizeOverLifetime;
            sz.enabled = true;
            sz.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.EaseInOut(0f, 0.6f, 1f, 2.6f));
            return ps;
        }

        // A sheet of spray when the blades slap the water
        private ParticleSystem MakeSpray(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _alphaMat, true, 220);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(1.0f, 2.2f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(5f, 16f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.3f, 1.1f);
            main.startColor = new Color(0.88f, 0.92f, 0.96f, 0.7f);
            main.gravityModifier = 0.9f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Hemisphere;
            sh.radius = 0.4f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(0.95f, 0.97f, 1f), new Color(0.85f, 0.9f, 0.95f), 0.75f, 0f);
            ParticleSystem.SizeOverLifetimeModule sz = ps.sizeOverLifetime;
            sz.enabled = true;
            sz.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0.7f, 1f, 2.2f));
            return ps;
        }

        // Broken-off blade tips and chips, tumbling and bouncing off the ground
        private ParticleSystem MakeDebris(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _alphaMat, true, 40);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(4f, 7f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(8f, 26f);
            main.startSize3D = true;
            main.startSizeX = new ParticleSystem.MinMaxCurve(0.6f, 1.2f);
            main.startSizeY = new ParticleSystem.MinMaxCurve(0.6f, 1.2f);
            main.startSizeZ = new ParticleSystem.MinMaxCurve(0.4f, 1.6f);
            main.startRotation3D = true;
            main.startRotationX = new ParticleSystem.MinMaxCurve(0f, Mathf.PI * 2f);
            main.startRotationY = new ParticleSystem.MinMaxCurve(0f, Mathf.PI * 2f);
            main.startRotationZ = new ParticleSystem.MinMaxCurve(0f, Mathf.PI * 2f);
            main.startColor = new ParticleSystem.MinMaxGradient(new Color(0.12f, 0.12f, 0.13f, 1f), new Color(0.62f, 0.62f, 0.60f, 1f));
            main.gravityModifier = 1f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Sphere;
            sh.radius = 0.2f;
            ParticleSystem.RotationOverLifetimeModule rot = ps.rotationOverLifetime;
            rot.enabled = true;
            rot.separateAxes = true;
            rot.x = new ParticleSystem.MinMaxCurve(-12f, 12f);
            rot.y = new ParticleSystem.MinMaxCurve(-12f, 12f);
            rot.z = new ParticleSystem.MinMaxCurve(-12f, 12f);
            ParticleSystem.CollisionModule colm = ps.collision;
            colm.enabled = true;
            colm.type = ParticleSystemCollisionType.World;
            colm.mode = ParticleSystemCollisionMode.Collision3D;
            colm.collidesWith = (1 << 15) | (1 << 28);
            colm.bounce = new ParticleSystem.MinMaxCurve(0.25f, 0.45f);
            colm.dampen = new ParticleSystem.MinMaxCurve(0.35f, 0.6f);
            colm.lifetimeLoss = 0f;
            ParticleSystemRenderer r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Mesh;
            r.mesh = ShardMesh();
            return ps;
        }

        /// <summary>A small twisted sliver of blade (~25 x 7 x 1.5 cm at size 1).</summary>
        private static Mesh ShardMesh()
        {
            if (_shardMesh != null)
                return _shardMesh;
            Vector3[] v =
            {
                new Vector3(-0.035f, -0.008f, -0.12f), new Vector3(0.035f, -0.006f, -0.13f),
                new Vector3(0.03f, -0.007f, 0.11f), new Vector3(-0.02f, -0.008f, 0.13f),
                new Vector3(-0.035f, 0.008f, -0.12f), new Vector3(0.035f, 0.006f, -0.13f),
                new Vector3(0.03f, 0.009f, 0.11f), new Vector3(-0.02f, 0.007f, 0.13f)
            };
            int[] t = { 0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7 };
            _shardMesh = new Mesh();
            _shardMesh.name = "ROPP_BladeShard";
            _shardMesh.vertices = v;
            _shardMesh.triangles = t;
            _shardMesh.RecalculateNormals();
            _shardMesh.RecalculateBounds();
            return _shardMesh;
        }

        /// <summary>Lays out the flame emitters for the current engine (called after every rebuild).</summary>
        public void Configure(ModuleProceduralPropeller m)
        {
            if (_portL == null || _additiveMat == null)
                return;
            _turboprop = m.IsTurboprop;
            _scale = Mathf.Clamp(m.cowlDiameter / 1.3f, 0.5f, 1.8f);

            for (int i = 0; i < _flames.Count; i++)
                if (_flames[i] != null) Object.Destroy(_flames[i].gameObject);
            _flames.Clear();

            if (_turboprop)
                return; // turbine exhaust doesn't flame

            // V-12/X-24: a row of ejector stubs along each side; radials: the collector outlets
            Vector3[] pts = PropellerMeshGenerator.GetExhaustFlamePoints(m);
            for (int i = 0; i < pts.Length; i++)
            {
                Vector3 r = pts[i];
                Vector3 l = new Vector3(-r.x, r.y, r.z);
                _flames.Add(MakeFlame(_portL, InPortSpace(_portL, l)));
                _flames.Add(MakeFlame(_portR, InPortSpace(_portR, r)));
            }
        }

        // Ports are positioned in their parent's space (see PlaceExhaustTransforms)
        private static Vector3 InPortSpace(Transform port, Vector3 parentSpacePoint)
        {
            return Quaternion.Inverse(port.localRotation) * (parentSpacePoint - port.localPosition);
        }

        private GameObject Child(Transform parent, string name, Vector3 localPos)
        {
            GameObject go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPos;
            go.transform.localRotation = Quaternion.identity;
            _objects.Add(go);
            return go;
        }

        private static Gradient Fade(Color c0, Color c1, float a0, float a1)
        {
            Gradient g = new Gradient();
            g.SetKeys(
                new GradientColorKey[] { new GradientColorKey(c0, 0f), new GradientColorKey(c1, 1f) },
                new GradientAlphaKey[] { new GradientAlphaKey(a0, 0f), new GradientAlphaKey(a0, 0.3f), new GradientAlphaKey(a1, 1f) });
            return g;
        }

        private ParticleSystem MakeSystem(GameObject go, Material mat, bool world, int maxParticles)
        {
            ParticleSystem ps = go.AddComponent<ParticleSystem>();
            ps.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            ParticleSystem.MainModule main = ps.main;
            main.loop = true;
            main.playOnAwake = false;
            main.maxParticles = maxParticles;
            main.simulationSpace = world ? ParticleSystemSimulationSpace.World : ParticleSystemSimulationSpace.Local;
            main.scalingMode = ParticleSystemScalingMode.Local;
            ParticleSystem.EmissionModule em = ps.emission;
            em.rateOverTime = 0f;
            ParticleSystemRenderer r = go.GetComponent<ParticleSystemRenderer>();
            r.sharedMaterial = mat;
            r.renderMode = ParticleSystemRenderMode.Billboard;
            ps.Play();
            if (world)
            {
                FloatingOrigin.RegisterParticleSystem(ps);
                _worldSystems.Add(ps);
            }
            return ps;
        }

        private ParticleSystem MakeFlame(Transform port, Vector3 localPos)
        {
            GameObject go = Child(port, "ROPP_Flame", localPos);
            ParticleSystem ps = MakeSystem(go, _additiveMat, false, 80);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.05f, 0.09f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(3f, 6f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.10f * _scale, 0.18f * _scale);
            main.startColor = new Color(1f, 0.62f, 0.25f, 1f);
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Cone;
            sh.angle = 6f;
            sh.radius = 0.02f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(0.55f, 0.65f, 1f), new Color(1f, 0.45f, 0.15f), 0.9f, 0f);
            ParticleSystem.SizeOverLifetimeModule sz = ps.sizeOverLifetime;
            sz.enabled = true;
            sz.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0.7f, 1f, 1.4f));
            ParticleSystemRenderer r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Stretch;
            r.lengthScale = 2.2f;
            r.velocityScale = 0.04f;
            return ps;
        }

        private ParticleSystem MakeSmoke(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _alphaMat, true, 200);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(1.2f, 2.2f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(1.5f, 3.5f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.25f, 0.45f);
            main.startColor = new Color(0.55f, 0.55f, 0.55f, 0.35f);
            main.gravityModifier = -0.02f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Cone;
            sh.angle = 12f;
            sh.radius = 0.05f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(0.45f, 0.45f, 0.45f), new Color(0.75f, 0.75f, 0.75f), 0.55f, 0f);
            ParticleSystem.SizeOverLifetimeModule sz = ps.sizeOverLifetime;
            sz.enabled = true;
            sz.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Linear(0f, 0.6f, 1f, 3.5f));
            return ps;
        }

        private ParticleSystem MakePuff(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _alphaMat, true, 120);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(2.0f, 3.5f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(0.8f, 3.0f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.5f, 1.0f);
            main.startColor = new Color(0.62f, 0.62f, 0.64f, 0.8f);
            main.gravityModifier = -0.03f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Cone;
            sh.angle = 35f;
            sh.radius = 0.1f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(0.35f, 0.35f, 0.36f), new Color(0.82f, 0.82f, 0.84f), 0.75f, 0f);
            ParticleSystem.SizeOverLifetimeModule sz = ps.sizeOverLifetime;
            sz.enabled = true;
            sz.size = new ParticleSystem.MinMaxCurve(1f, AnimationCurve.EaseInOut(0f, 0.5f, 1f, 4.5f));
            return ps;
        }

        private ParticleSystem MakeSparks(Transform port, string name)
        {
            GameObject go = Child(port, name, Vector3.zero);
            ParticleSystem ps = MakeSystem(go, _additiveMat, true, 150);
            ParticleSystem.MainModule main = ps.main;
            main.startLifetime = new ParticleSystem.MinMaxCurve(0.25f, 0.7f);
            main.startSpeed = new ParticleSystem.MinMaxCurve(4f, 12f);
            main.startSize = new ParticleSystem.MinMaxCurve(0.04f, 0.10f);
            main.startColor = new Color(1f, 0.75f, 0.35f, 1f);
            main.gravityModifier = 1f;
            ParticleSystem.ShapeModule sh = ps.shape;
            sh.shapeType = ParticleSystemShapeType.Sphere;
            sh.radius = 0.1f;
            ParticleSystem.ColorOverLifetimeModule col = ps.colorOverLifetime;
            col.enabled = true;
            col.color = Fade(new Color(1f, 0.9f, 0.6f), new Color(1f, 0.35f, 0.1f), 1f, 0f);
            ParticleSystemRenderer r = go.GetComponent<ParticleSystemRenderer>();
            r.renderMode = ParticleSystemRenderMode.Stretch;
            r.lengthScale = 1f;
            r.velocityScale = 0.06f;
            return ps;
        }

        // ---------------------------------------------------------------- runtime

        private static void SetRate(ParticleSystem ps, float rate)
        {
            if (ps == null)
                return;
            ParticleSystem.EmissionModule em = ps.emission;
            em.rateOverTime = Mathf.Max(0f, rate);
        }

        /// <summary>Called every frame in flight.</summary>
        public void Tick(float dt, bool running, bool packed, float powerFrac, bool wep, float airspeed, float pressure)
        {
            if (_smokeL == null)
                return;
            _sinceStart += dt;
            bool active = running && !packed;
            float air = Mathf.Sqrt(Mathf.Clamp01(pressure));

            // Flames: brighter and longer with power; WEP adds a lot
            float flameRate = active ? (50f + 220f * powerFrac) * (wep ? 1.4f : 1f) : 0f;
            float flameSpeed = 2.5f + 5f * powerFrac * (wep ? 1.35f : 1f);
            for (int i = 0; i < _flames.Count; i++)
            {
                ParticleSystem f = _flames[i];
                if (f == null) continue;
                SetRate(f, flameRate);
                ParticleSystem.MainModule main = f.main;
                main.startSpeed = new ParticleSystem.MinMaxCurve(flameSpeed * 0.6f, flameSpeed);
            }

            // Smoke: heavy for the first ~20 s after a cold start, then a light haze that grows
            // with power and fades as airspeed sweeps it away; thin air carries less of it.
            float cold = 1f + 3f * Mathf.Clamp01(1f - _sinceStart / 20f);
            float slow = 1f - 0.6f * Mathf.Clamp01(airspeed / 120f);
            float smokeRate = 0f;
            if (active)
            {
                smokeRate = _turboprop
                    ? (2f + 6f * powerFrac) * air
                    : (4f + 14f * powerFrac) * cold * slow * air;
            }
            SetRate(_smokeL, smokeRate);
            SetRate(_smokeR, smokeRate);
            float size = _scale * (_turboprop ? 0.7f : 1f);
            SetSize(_smokeL, 0.25f * size, 0.45f * size);
            SetSize(_smokeR, 0.25f * size, 0.45f * size);
        }

        private static void SetSize(ParticleSystem ps, float min, float max)
        {
            ParticleSystem.MainModule main = ps.main;
            main.startSize = new ParticleSystem.MinMaxCurve(min, max);
        }

        /// <summary>Engine just started: big smoke cloud (pistons) and reset the cold-start smoke.</summary>
        public void StartBurst()
        {
            _sinceStart = 0f;
            if (_puffL == null || _turboprop)
                return;
            _puffL.Emit(18);
            _puffR.Emit(18);
            FlamePop(6);
        }

        /// <summary>A cough while a piston engine catches.</summary>
        public void Cough()
        {
            if (_puffL == null || _turboprop)
                return;
            _puffL.Emit(6);
            _puffR.Emit(6);
            FlamePop(4);
        }

        /// <summary>A misfire or afterfire pop: a short flash at the stubs.</summary>
        public void Pop()
        {
            if (_puffL == null || _turboprop)
                return;
            FlamePop(3);
        }

        /// <summary>Turbine light-off: a puff of unburnt fuel vapour and smoke from the exhausts.</summary>
        public void LightOff()
        {
            _sinceStart = 0f;
            if (_puffL == null)
                return;
            _puffL.Emit(7);
            _puffR.Emit(7);
        }

        public void Backfire()
        {
            if (_sparks == null)
                return;
            FlamePop(14);
            _sparks.Emit(30);
            if (_puffL != null)
            {
                _puffL.Emit(5);
                _puffR.Emit(5);
            }
        }

        /// <summary>
        /// Propeller hits the ground or water at the contact point: dirt and sod (or spray), tumbling
        /// blade fragments, sparks (lots on a runway) and a puff of smoke from the stopped engine.
        /// </summary>
        public void PropStrike(Vector3 hubWorld, Vector3 contactWorld, bool water, bool paved, int blades)
        {
            if (_sparks == null)
                return;
            Vector3 outward = contactWorld - hubWorld;
            if (outward.sqrMagnitude < 1e-4f)
                outward = Vector3.down;
            Quaternion look = Quaternion.LookRotation(-outward.normalized); // hemisphere opens away from the ground
            if (water)
            {
                EmitAt(_spray, contactWorld, look, 160);
                EmitAt(_debris, contactWorld, look, Mathf.Clamp(blades, 2, 8));
            }
            else
            {
                EmitAt(_dirt, contactWorld, look, paved ? 25 : 90);
                EmitAt(_debris, contactWorld, look, Mathf.Clamp(blades * 3, 6, 24));
                EmitAt(_sparks, contactWorld, look, paved ? 140 : 40);
            }
            if (_puffL != null && !_turboprop)
            {
                _puffL.Emit(4);
                _puffR.Emit(4);
            }
        }

        private static void EmitAt(ParticleSystem ps, Vector3 pos, Quaternion rot, int count)
        {
            if (ps == null || count <= 0)
                return;
            Transform t = ps.transform;
            Vector3 oldPos = t.position;
            Quaternion oldRot = t.rotation;
            t.position = pos;
            t.rotation = rot;
            ps.Emit(count);
            t.position = oldPos;
            t.rotation = oldRot;
        }

        private void FlamePop(int count)
        {
            for (int i = 0; i < _flames.Count; i++)
                if (_flames[i] != null) _flames[i].Emit(count);
        }

        public void Destroy()
        {
            for (int i = 0; i < _worldSystems.Count; i++)
                if (_worldSystems[i] != null) FloatingOrigin.UnregisterParticleSystem(_worldSystems[i]);
            _worldSystems.Clear();
            for (int i = 0; i < _objects.Count; i++)
                if (_objects[i] != null) Object.Destroy(_objects[i]);
            _objects.Clear();
            _flames.Clear();
        }
    }
}
