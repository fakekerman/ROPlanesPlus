using UnityEngine;

namespace ROPlanesPlus
{
    public enum EnginePhase
    {
        Off = 0,
        Cranking = 1,  // piston: starter turning the engine; turboprop: starter turning the gas generator
        Catching = 2,  // piston: cylinders start to fire; turboprop: lit, accelerating to ground idle
        Running = 3
    }

    /// <summary>
    /// Start-up and shut-down of one engine, shared by the flight module (which holds AJE's
    /// propeller at SeqPropRPM while the engine starts) and the Engine Workshop's sound preview.
    ///
    /// Piston: the starter spins up and engages with a clunk, cranks the propeller at 110-190
    /// engine rpm for a few seconds (longer when cold), then cylinders begin to fire one at a
    /// time (coughs, smoke; sometimes the engine stumbles before it picks up), the engine catches,
    /// flares past idle and settles. A cold engine runs rough for the first minutes.
    /// Turboprop: the starter turns the gas generator and (single shaft) the propeller, the
    /// igniters snap, fuel lights off at ~13 % and the engine accelerates to ground idle (~70 %)
    /// over 10-25 s depending on its size; starter and igniters cut out once it is self-sustaining.
    /// Shut down: friction and compression stop a piston engine within seconds; a turbine winds
    /// down for half a minute.
    /// </summary>
    public class EngineStartSequence
    {
        // Events raised by Tick, collected with TakeEvents()
        public const int EvStarterEngage = 1;
        public const int EvCough = 2;
        public const int EvCatch = 4;
        public const int EvLightOff = 8;
        public const int EvMisfire = 16;
        public const int EvShutdown = 32;
        public const int EvPropStopped = 64;

        private const float StarterSpinUp = 1.1f; // starter motor running up before it engages

        // ---- configuration (Configure) ----
        public bool Turboprop;
        public int Cylinders = 18;
        public float GearRatio = 0.5f;
        public float MaxPropRPM = 1300f;
        public float IdlePropRPM = 300f;
        public float CrankPropRPM = 60f;
        public float IdleN = 0.70f;
        private float _crankTime = 3f;
        private float _catchTime = 2f;

        // ---- state ----
        public EnginePhase Phase = EnginePhase.Off;
        public float PhaseTime;
        public float SeqPropRPM;     // propeller rpm the sequence commands while starting
        public float CoreN;          // turboprop gas-generator speed, 0..1.05
        public float Firing;         // fraction of cylinders firing / combustor lit
        public float Starter;        // starter motor speed, 0..1
        public bool StarterEngaged;  // starter turning the engine
        public bool Igniters;
        public float Warmth = 1f;    // 0 cold .. 1 at running temperature
        public float Roughness;      // misfires, 0..1

        private int _events;
        // Unique seeds: new System.Random() seeds from the clock, so sequences created in the same
        // millisecond (every engine of a vessel on load) would otherwise share their draws by accident
        private static readonly System.Random Seeder = new System.Random();
        private System.Random _rng = NewRng();

        /// <summary>
        /// Asked for a seed whenever a start begins (null in the Workshop preview). Engines of one
        /// vessel switched on together get the same seed, so they draw the same cranking time, catch,
        /// stumble and coughs and run through the start in step instead of each at its own time
        /// (several engines a few percent apart in rpm, each coughing on its own, were a mess of
        /// beating). Once running they draw independently again.
        /// </summary>
        public System.Func<int> StartSeed;

        private static System.Random NewRng()
        {
            lock (Seeder)
                return new System.Random(Seeder.Next());
        }
        private float _crankHold;
        private float _catchDur;
        private float _nextCough;
        private float _stumbleAt = -1f;
        private bool _caught;
        private bool _stopArmed;
        private float _lightN = 0.13f;
        private float _windmillRPM;  // air start: the airflow keeps the propeller turning at least this fast

        public bool Starting { get { return Phase == EnginePhase.Cranking || Phase == EnginePhase.Catching; } }

        public void Configure(ModuleProceduralPropeller m, PropellerPerformanceMetrics metrics)
        {
            Turboprop = m.IsTurboprop;
            Cylinders = Turboprop ? 0 : Mathf.Max(4, PropellerPhysicsEngine.CylinderCount(m));
            GearRatio = metrics.effectiveGearRatio > 0.05f ? metrics.effectiveGearRatio : 0.5f;
            MaxPropRPM = Mathf.Max(200f, metrics.maxPropRPM);
            float size = Mathf.Clamp01(Mathf.Log10(Mathf.Max(100f, metrics.shaftPowerHP) / 400f) / 1.6f);
            if (Turboprop)
            {
                IdleN = 0.70f;
                IdlePropRPM = IdleN * MaxPropRPM;
                CrankPropRPM = 0.13f * MaxPropRPM;
                _crankTime = 2.8f + 2.2f * size;  // to light-off
                _catchTime = 5.5f + 8f * size;    // light-off to ground idle: ~7 s (PT6) .. ~13 s (NK-12)
            }
            else
            {
                float idleEngine = m.architectureIndex == (int)EngineArchitecture.Radial ? 620f : 700f;
                float crankEngine = Mathf.Lerp(190f, 110f, size); // big engines crank slower
                IdlePropRPM = idleEngine * GearRatio;
                CrankPropRPM = crankEngine * GearRatio;
                _crankTime = 2.2f + 1.8f * size;
                _catchTime = 1.6f + 1.0f * size;
            }
        }

        /// <summary>The engine was already running (vessel loaded in flight).</summary>
        public void SetRunning(float propRPM)
        {
            Phase = EnginePhase.Running;
            PhaseTime = 30f;
            Firing = 1f;
            Starter = 0f;
            StarterEngaged = false;
            Igniters = false;
            Warmth = 1f;
            Roughness = 0f;
            _caught = true;
            SeqPropRPM = propRPM;
            CoreN = Turboprop ? Mathf.Max(IdleN, propRPM / MaxPropRPM) : 0f;
        }

        public int TakeEvents()
        {
            int e = _events;
            _events = 0;
            return e;
        }

        /// <summary>Propeller deceleration (rpm/s) from engine friction and compression once it is shut down.</summary>
        public float OffDecel(float propRPM)
        {
            return Turboprop ? 4f + 0.035f * propRPM : 45f + 0.35f * propRPM;
        }

        private float R(float a, float b)
        {
            return a + (float)_rng.NextDouble() * (b - a);
        }

        /// <summary>
        /// Advances the sequence. ignition = the engine is switched on (ignited, fuelled, not
        /// flamed out); liveRPM = the propeller rpm the physics currently reports.
        /// </summary>
        public void Tick(float dt, bool ignition, float liveRPM)
        {
            if (dt <= 0f)
                return;
            PhaseTime += dt;
            if (!ignition)
            {
                TickOff(dt, liveRPM);
                return;
            }
            switch (Phase)
            {
                case EnginePhase.Off:
                    // Judge windmilling by the rpm of the last tick with the engine off (TickOff keeps
                    // it in SeqPropRPM): AJE's engine module runs before ours in the part, so on the
                    // frame the engine is switched on with the throttle open AJE's own starter has
                    // already flung the propeller up to hundreds of rpm, which looked like an air start
                    // and skipped cranking (no starter sound, no coughs, instant light-off).
                    Begin(Mathf.Min(liveRPM, SeqPropRPM));
                    break;
                case EnginePhase.Cranking:
                    if (Turboprop) TurbineCrank(); else PistonCrank(dt);
                    break;
                case EnginePhase.Catching:
                    if (Turboprop) TurbineAccelerate(dt); else PistonCatch(dt);
                    break;
                default:
                    TickRunning(dt, liveRPM);
                    break;
            }
        }

        private void TickOff(float dt, float liveRPM)
        {
            if (Phase != EnginePhase.Off)
            {
                Phase = EnginePhase.Off;
                PhaseTime = 0f;
                _events |= EvShutdown;
                _stopArmed = !Turboprop && Mathf.Max(liveRPM, SeqPropRPM) > CrankPropRPM * 0.5f;
            }
            Starter = Mathf.MoveTowards(Starter, 0f, dt * 1.5f);
            StarterEngaged = false;
            Igniters = false;
            Firing = Mathf.MoveTowards(Firing, 0f, dt * (Turboprop ? 1.5f : 5f));
            Roughness = 0f;
            if (Turboprop)
                CoreN = Mathf.Max(Mathf.Max(0f, CoreN - (CoreN / 7f + 0.002f) * dt), Mathf.Clamp01(liveRPM / MaxPropRPM));
            SeqPropRPM = liveRPM;
            Warmth = Mathf.Max(0f, Warmth - dt / 900f);
            if (_stopArmed && liveRPM < 8f)
            {
                _stopArmed = false;
                _events |= EvPropStopped;
            }
        }

        private void Begin(float liveRPM)
        {
            if (StartSeed != null)
                _rng = new System.Random(StartSeed());
            Phase = EnginePhase.Cranking;
            PhaseTime = 0f;
            _caught = false;
            StarterEngaged = false;
            SeqPropRPM = liveRPM;
            float cold = 1f - Warmth;
            if (Turboprop)
            {
                CoreN = Mathf.Max(CoreN, Mathf.Clamp01(liveRPM / MaxPropRPM));
                _crankHold = _crankTime * R(0.9f, 1.15f);
                _catchDur = _catchTime * R(0.9f, 1.1f);
                _lightN = 0.13f;
                if (CoreN >= 0.25f)
                {
                    // windmilling in flight: lights straight away
                    Phase = EnginePhase.Catching;
                    _lightN = CoreN;
                    _catchDur *= 0.5f;
                    Igniters = true;
                    _events |= EvLightOff;
                }
                return;
            }
            _crankHold = _crankTime * R(0.75f, 1.3f) * Mathf.Lerp(0.55f, 1.25f, cold);
            _catchDur = _catchTime * R(0.85f, 1.25f) * Mathf.Lerp(0.7f, 1.15f, cold);
            _stumbleAt = R(0f, 1f) < 0.15f + 0.3f * cold ? R(0.3f, 0.6f) : -1f;
            _nextCough = R(0.05f, 0.25f);
            Firing = 0f;
            _windmillRPM = 0f;
            if (liveRPM >= CrankPropRPM * 1.8f)
            {
                // windmilling: the engine fires as soon as the ignition is on
                Phase = EnginePhase.Catching;
                _catchDur *= 0.45f;
                _stumbleAt = -1f;
                _windmillRPM = liveRPM;
            }
        }

        private void PistonCrank(float dt)
        {
            if (!StarterEngaged)
            {
                Starter = Mathf.MoveTowards(Starter, 1f, dt / StarterSpinUp);
                SeqPropRPM = Mathf.MoveTowards(SeqPropRPM, 0f, dt * 40f);
                if (PhaseTime >= StarterSpinUp)
                {
                    StarterEngaged = true;
                    _events |= EvStarterEngage;
                }
                return;
            }
            // Compression loads the starter (it slows down) while the propeller comes up to cranking speed
            Starter = Mathf.MoveTowards(Starter, 0.72f, dt * 0.8f);
            SeqPropRPM = Mathf.MoveTowards(SeqPropRPM, CrankPropRPM, CrankPropRPM / 0.7f * dt);
            if (PhaseTime >= StarterSpinUp + _crankHold)
            {
                Phase = EnginePhase.Catching;
                PhaseTime = 0f;
            }
        }

        private void PistonCatch(float dt)
        {
            float p = Mathf.Clamp01(PhaseTime / Mathf.Max(0.1f, _catchDur));
            float target = p * p * (3f - 2f * p);
            if (_stumbleAt > 0f && p > _stumbleAt && p < _stumbleAt + 0.25f)
                target *= 0.35f; // stumbles, then picks up again
            Firing = Mathf.MoveTowards(Firing, target, dt * 2.5f);

            // The starter keeps cranking until the engine runs on its own
            if (Firing > 0.65f)
                StarterEngaged = false;
            Starter = StarterEngaged ? Mathf.MoveTowards(Starter, 0.72f, dt) : Mathf.MoveTowards(Starter, 0f, dt * 1.2f);

            // Single cylinders firing: each one kicks the propeller; more often as more cylinders join in
            if (Firing < 0.9f)
            {
                _nextCough -= dt;
                if (_nextCough <= 0f)
                {
                    _events |= EvCough;
                    SeqPropRPM += CrankPropRPM * R(0.25f, 0.6f) * (1f - Firing);
                    _nextCough = Mathf.Lerp(0.45f, 0.08f, Firing) * R(0.6f, 1.4f);
                }
            }
            if (!_caught && Firing > 0.55f)
            {
                _caught = true;
                _events |= EvCatch;
            }

            // Propeller: starter speed, then a flare past idle as the engine takes over
            float floorRPM = Mathf.Max(StarterEngaged ? CrankPropRPM : 0f, _windmillRPM);
            float targetRPM = Mathf.Max(floorRPM, CrankPropRPM + (IdlePropRPM * 1.3f - CrankPropRPM) * Mathf.Pow(Firing, 1.5f));
            SeqPropRPM += (targetRPM - SeqPropRPM) * (1f - Mathf.Exp(-dt / 0.45f));
            Roughness = 1f - Firing;
            if (p >= 1f && Firing > 0.97f)
            {
                Phase = EnginePhase.Running;
                PhaseTime = 0f;
                _rng = NewRng(); // misfires of a running engine are its own
            }
        }

        private void TurbineCrank()
        {
            StarterEngaged = true;
            Starter = Mathf.Clamp01(PhaseTime / 0.8f);
            // The gas generator runs up on the starter alone, slowing as compressor load grows
            float k = Mathf.Clamp01(PhaseTime / Mathf.Max(0.1f, _crankHold));
            CoreN = Mathf.Max(CoreN, _lightN * (1f - Mathf.Exp(-3f * k)) / 0.9502f);
            Igniters = CoreN > 0.05f;
            SeqPropRPM = CoreN * MaxPropRPM;
            if (k >= 1f)
            {
                Phase = EnginePhase.Catching;
                PhaseTime = 0f;
                _lightN = CoreN;
                _events |= EvLightOff;
            }
        }

        private void TurbineAccelerate(float dt)
        {
            float p = Mathf.Clamp01(PhaseTime / Mathf.Max(0.1f, _catchDur));
            Firing = Mathf.MoveTowards(Firing, 1f, dt * 1.2f);
            // Combustion plus starter accelerate the core quickly at first, easing into idle
            float s = 1f - (1f - p) * (1f - p);
            CoreN = Mathf.Max(CoreN, _lightN + (IdleN - _lightN) * s);
            Igniters = CoreN < 0.45f;
            if (CoreN > 0.5f)
            {
                StarterEngaged = false; // starter cut-out: self-sustaining
                Starter = Mathf.MoveTowards(Starter, 0f, dt * 0.6f);
            }
            else
            {
                Starter = Mathf.MoveTowards(Starter, 1f, dt);
            }
            SeqPropRPM = CoreN * MaxPropRPM;
            Roughness = 0f;
            if (p >= 1f)
            {
                Phase = EnginePhase.Running;
                PhaseTime = 0f;
                _rng = NewRng();
            }
        }

        private void TickRunning(float dt, float liveRPM)
        {
            StarterEngaged = false;
            Igniters = false;
            Starter = Mathf.MoveTowards(Starter, 0f, dt * 0.8f);
            Firing = Mathf.MoveTowards(Firing, 1f, dt * 2f);
            Warmth = Mathf.Min(1f, Warmth + dt / (Turboprop ? 60f : 120f));
            SeqPropRPM = liveRPM;
            if (Turboprop)
            {
                float target = Mathf.Clamp(liveRPM / MaxPropRPM, IdleN, 1.05f);
                CoreN += (target - CoreN) * (1f - Mathf.Exp(-dt / 1.2f));
                Roughness = 0f;
                return;
            }
            // A cold engine misfires, mostly at low rpm; it also runs unevenly just after catching
            float rpmFrac = Mathf.Clamp01(liveRPM / MaxPropRPM);
            float early = Mathf.Clamp01(1f - PhaseTime / 6f);
            Roughness = Mathf.Clamp01(0.7f * Mathf.Pow(1f - Warmth, 1.5f) * (1f - 0.8f * rpmFrac) + 0.5f * early);
            if (Roughness > 0.08f && (float)_rng.NextDouble() < 1.4f * Roughness * dt)
                _events |= EvMisfire;
        }
    }
}
