using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>What the engine is doing, as far as its sound is concerned.</summary>
    public struct EngineSoundInput
    {
        public EnginePhase phase;
        public float engineRPM;      // crankshaft rpm (piston)
        public float propRPM;
        public float coreN;          // turboprop gas-generator speed, 0..1.05
        public float firing;         // fraction of cylinders firing / combustor lit
        public float starter;        // starter motor speed, 0..1
        public bool starterEngaged;  // starter turning the engine (compression chugs)
        public bool igniters;
        public float load;           // power being made, fraction of rated
        public float tipMach;        // helical blade-tip Mach number
        public float boost;          // how hard the supercharger / turbo works, 0..1
        public float boostPitch;     // impeller speed vs. the reference (blower gear, turbo speed)
        public float roughness;      // misfires, 0..1
        public float pressure;       // ambient pressure / sea level
        public bool feathered;
        public bool reversed;
        public bool wep;
        public float windSpeed;      // airspeed for the airflow layer (0 = this engine doesn't play it)
    }

    /// <summary>
    /// Layered engine sound driven by the live engine state (not the stock EFFECTS system):
    ///   piston  - exhaust loops recorded at 800 / 1600 / 2600 rpm, crossfaded and pitched by real
    ///             crankshaft rpm; louder and brighter with power, darker and burbling (overrun
    ///             crackle, afterfire pops) when the throttle is closed at high rpm; misfire dips
    ///             while cold; supercharger or turbo whine that follows boost and blower gear;
    ///             compression chugs and starter whine while cranking
    ///   turbine - compressor whine pitched by gas-generator speed, combustion roar by power,
    ///             igniter snaps and starter whine during the start, light-off whoomp
    ///   prop    - blade-passage thrum (loudness from blade-tip Mach and blade loading), a
    ///             transonic rasp when the tips approach Mach 1, separate blade swishes when the
    ///             propeller turns slowly
    /// In flight the mix also depends on where you hear it from: propeller loudest in its plane,
    /// exhaust beside and behind, whine ahead, turbine roar behind; distance muffles the highs,
    /// the cockpit muffles everything, thin air makes it quieter, and engines of other vessels
    /// get a Doppler shift. Clips come from generate_sounds.py: the engine, turbine, propeller and
    /// wind loops are real recordings (process_recordings.py time-warps each so its firing frequency
    /// sits on the reference below, i.e. "equivalent rpm" playback gives the recorded engine its
    /// own pitch), the start-up layers and one-shots are synthesized.
    /// </summary>
    public class PropellerAudio
    {
        private const string SoundPath = "ROPlanesPlus/Sounds/";
        // Reference speeds of the loops (keep in sync with generate_sounds.py)
        private const float IdleRef = 800f;
        private const float MidRef = 1600f;
        private const float HighRef = 2600f;
        private const float RadialRefCylinders = 18f;  // radial_* loops: 18 cylinders
        private const float InlineRefCylinders = 12f;  // vinline_* loops: V-12
        private const float WindRefSpeed = 120f;       // m/s
        private const float CrankRefHz = 20f;
        private const float SuperRefRPM = 2600f;
        private const float PropRefBPF = 80f;
        private const float SwishRefBPF = 8f;
        private const float HalfPi = Mathf.PI * 0.5f;

        private class Layer
        {
            public AudioSource src;
            public AudioLowPassFilter lpf;
            public float vol;
            // Where a copy of this loop may start relative to the same loop on another engine of the
            // vessel: 0 = anywhere (as far from the others as possible); n = only at multiples of
            // 1/n of the clip (loops whose tone wavers periodically: copies out of step would beat)
            public int alignDivisions;
        }

        // Every engine sound in flight, so the engines of one vessel can keep in step with each other
        private static readonly List<PropellerAudio> Instances = new List<PropellerAudio>();
        private static readonly List<float> PeerPositions = new List<float>();

        private GameObject _root;
        private Part _part;
        private bool _preview;
        private bool _paused;

        private Layer _eIdle, _eMid, _eMidOff, _eHigh, _eHighOff, _crank, _starter, _super;
        private Layer _tWhine, _tRoar, _igniter;
        private Layer _pMain, _pRasp, _pSwish, _wind;
        private Layer[] _all;
        private AudioSource[] _shots;
        private AudioLowPassFilter[] _shotLpf;
        private int _nextShot;

        private AudioClip _coughClip, _popClip, _backfireClip, _engageClip, _stopClip, _strikeClip, _strikeWaterClip, _lightClip;

        private bool _turboprop;
        private int _bladesTotal = 4;
        private int _cylinders = 18;
        private float _refCylinders = RadialRefCylinders;
        private float _maxEngineRPM = 2700f;
        private bool _supercharged;

        // Slow random variation so the sound never sits perfectly still (real engines don't)
        private float _driftGain, _driftGainTarget, _driftPitch, _driftPitchTarget, _driftProp, _driftPropTarget, _driftTimer;

        private float _load, _loadSlow, _overrun;
        private float _doppler = 1f;
        private float _dip, _dipTime, _dipDepth, _wobble;
        private float _afterfire;
        private int _pops;
        private int _shutdownPops;
        private float _shutdownTimer;
        private float _master;
        private float _cutoff = 22000f;

        private static AudioListener _listener;
        private static float _listenerCheck;

        // ================================================================ setup

        /// <summary>3D sound on an engine part in flight.</summary>
        public void Init(Part part)
        {
            _part = part;
            Build(part.transform, false);
            Instances.Add(this);
        }

        /// <summary>2D sound for the Engine Workshop's "Listen" preview.</summary>
        public void InitPreview(Transform parent)
        {
            Build(parent, true);
        }

        private void Build(Transform parent, bool preview)
        {
            _preview = preview;
            _master = GameSettings.SHIP_VOLUME;
            _root = new GameObject("ROPP_EngineAudio");
            _root.transform.SetParent(parent, false);
            _root.transform.localPosition = Vector3.zero;

            _eIdle = MakeLayer("idle", null);
            _eMid = MakeLayer("mid", null);
            _eMidOff = MakeLayer("midOff", null);
            _eHigh = MakeLayer("high", null);
            _eHighOff = MakeLayer("highOff", null);
            _wind = MakeLayer("wind", "wind");
            _crank = MakeLayer("crank", "piston_crank");  // chugs only: compressions of different engines interleave
            _starter = MakeLayer("starter", "starter_whine");
            _super = MakeLayer("blower", "supercharger_whine");
            _super.alignDivisions = 1;                                             // one slow vibrato per loop
            _tWhine = MakeLayer("whine", "turbine_whine");
            _tRoar = MakeLayer("roar", "turbine_roar");
            _igniter = MakeLayer("igniter", "turbine_igniter");
            _pMain = MakeLayer("prop", "prop_loop");
            _pRasp = MakeLayer("rasp", "prop_rasp");
            _pSwish = MakeLayer("swish", "prop_swish");
            _all = new Layer[] { _eIdle, _eMid, _eMidOff, _eHigh, _eHighOff, _crank, _starter, _super, _tWhine, _tRoar, _igniter, _pMain, _pRasp, _pSwish, _wind };

            _shots = new AudioSource[4];
            _shotLpf = new AudioLowPassFilter[4];
            for (int i = 0; i < _shots.Length; i++)
            {
                GameObject go = new GameObject("ROPP_Shot" + i);
                go.transform.SetParent(_root.transform, false);
                _shots[i] = MakeSource(go, false);
                _shots[i].priority = 80;
                _shotLpf[i] = go.AddComponent<AudioLowPassFilter>();
                _shotLpf[i].cutoffFrequency = 22000f;
            }
            // The strike gets its own source: highest priority, heard from further away, and no
            // later pop can steal it from the round-robin pool
            GameObject sgo = new GameObject("ROPP_Strike");
            sgo.transform.SetParent(_root.transform, false);
            _strikeSrc = MakeSource(sgo, false);
            _strikeSrc.priority = 0;
            _strikeSrc.minDistance = 30f;

            _coughClip = Clip("piston_cough");
            _popClip = Clip("exhaust_pop");
            _backfireClip = Clip("backfire");
            _engageClip = Clip("starter_engage");
            _stopClip = Clip("prop_stop");
            _strikeClip = Clip("prop_strike");
            _strikeWaterClip = Clip("prop_strike_water");
            _lightClip = Clip("turbine_lightoff");
        }

        private Layer MakeLayer(string name, string clip)
        {
            GameObject go = new GameObject("ROPP_" + name);
            go.transform.SetParent(_root.transform, false);
            Layer l = new Layer();
            l.src = MakeSource(go, true);
            l.lpf = go.AddComponent<AudioLowPassFilter>();
            l.lpf.cutoffFrequency = 22000f;
            if (clip != null)
                l.src.clip = Clip(clip);
            return l;
        }

        private AudioSource MakeSource(GameObject go, bool loop)
        {
            AudioSource s = go.AddComponent<AudioSource>();
            s.playOnAwake = false;
            s.loop = loop;
            s.spatialBlend = _preview ? 0f : 1f;
            s.rolloffMode = AudioRolloffMode.Logarithmic;
            s.minDistance = 8f;
            s.maxDistance = 3000f;
            s.dopplerLevel = 0f; // floating origin / Krakensbane break Unity's doppler; done by hand below
            s.volume = 0f;
            s.priority = 64;
            return s;
        }

        private static AudioClip Clip(string name)
        {
            if (GameDatabase.Instance == null)
                return null;
            return GameDatabase.Instance.GetAudioClip(SoundPath + name);
        }

        private void SetClip(Layer l, string name)
        {
            AudioClip c = Clip(name);
            if (c == null || l.src.clip == c)
                return;
            bool playing = l.src.isPlaying;
            l.src.clip = c;
            if (playing)
                StartLoop(l);
        }

        /// <summary>
        /// Starts a loop at a point that keeps it apart from the same loop on this vessel's other
        /// engines. The engines of a vessel play at the same pitch (same rpm, shared drift), so their
        /// offsets stay as set here: copies only milliseconds apart would comb-filter into a hollow,
        /// phasing sound, so a free loop starts as far from the others as possible; loops whose tone
        /// wavers periodically start on that period's grid, in step with the others.
        /// </summary>
        private void StartLoop(Layer l)
        {
            AudioSource s = l.src;
            s.Play();
            if (s.clip == null || s.clip.samples <= 1)
                return;
            int n = s.clip.samples;
            float pos = Random.value;
            CollectPeerPositions(s.clip);
            if (PeerPositions.Count > 0)
            {
                bool grid = l.alignDivisions > 0;
                int candidates = grid ? Mathf.Min(l.alignDivisions, 64) : 24;
                float bestGap = -1f;
                for (int k = 0; k < candidates; k++)
                {
                    float c = grid
                        ? Mathf.Repeat(PeerPositions[0] + (float)Random.Range(0, l.alignDivisions) / l.alignDivisions, 1f)
                        : Random.value;
                    float gap = 1f;
                    for (int j = 0; j < PeerPositions.Count; j++)
                    {
                        float d = Mathf.Abs(c - PeerPositions[j]);
                        gap = Mathf.Min(gap, Mathf.Min(d, 1f - d));
                    }
                    if (gap > bestGap)
                    {
                        bestGap = gap;
                        pos = c;
                    }
                }
            }
            s.timeSamples = Mathf.Clamp((int)(pos * n), 0, n - 1);
        }

        /// <summary>Playback positions (0..1) of this clip on the other engines of the same vessel.</summary>
        private void CollectPeerPositions(AudioClip clip)
        {
            PeerPositions.Clear();
            if (_preview || _part == null || _part.vessel == null)
                return;
            for (int i = 0; i < Instances.Count; i++)
            {
                PropellerAudio o = Instances[i];
                if (o == this || o._all == null || o._part == null || o._part.vessel != _part.vessel)
                    continue;
                for (int j = 0; j < o._all.Length; j++)
                {
                    AudioSource os = o._all[j].src;
                    if (os != null && os.clip == clip && os.isPlaying)
                        PeerPositions.Add((float)os.timeSamples / clip.samples);
                }
            }
        }

        /// <summary>
        /// The engine whose slow pitch drift and rough-running wobble every engine of the vessel
        /// shares. Engines at the same rpm with their own random detuning (up to +-2.5 % while cold)
        /// beat against each other: the harmonics of identical loops a few percent apart buzz.
        /// </summary>
        private PropellerAudio PitchLeader()
        {
            if (_preview || _part == null || _part.vessel == null)
                return this;
            for (int i = 0; i < Instances.Count; i++)
            {
                PropellerAudio o = Instances[i];
                if (o._root != null && o._part != null && o._part.vessel == _part.vessel)
                    return o;
            }
            return this;
        }

        /// <summary>Picks the clips for this engine (called after every rebuild).</summary>
        public void Configure(ModuleProceduralPropeller m, PropellerPerformanceMetrics metrics)
        {
            if (_root == null)
                return;
            _turboprop = m.IsTurboprop;
            _bladesTotal = m.isContraRotating ? m.bladeCount * 2 : m.bladeCount;
            _cylinders = _turboprop ? 0 : Mathf.Max(4, PropellerPhysicsEngine.CylinderCount(m));
            _maxEngineRPM = metrics.aje != null && metrics.aje.maxRPM > 100.0 ? (float)metrics.aje.maxRPM : Mathf.Max(1500f, m.maxEngineRPM);
            _supercharged = !_turboprop && m.aspirationIndex != (int)AspirationType.NaturallyAspirated;
            bool radial = m.architectureIndex == (int)EngineArchitecture.Radial;
            _refCylinders = radial ? RadialRefCylinders : InlineRefCylinders;
            string family = radial ? "radial" : "vinline";
            SetClip(_eIdle, family + "_idle");
            SetClip(_eMid, family + "_mid");
            SetClip(_eMidOff, family + "_mid_off");
            SetClip(_eHigh, family + "_high");
            SetClip(_eHighOff, family + "_high_off");

            // Bigger engines carry further
            float size = Mathf.Clamp01(Mathf.Log10(Mathf.Max(100f, metrics.shaftPowerHP) / 400f) / 1.6f);
            float minDist = 6f + 8f * size;
            for (int i = 0; i < _all.Length; i++)
                _all[i].src.minDistance = minDist;
            for (int i = 0; i < _shots.Length; i++)
                _shots[i].minDistance = minDist;
        }

        // ================================================================ events

        public void OnSequenceEvents(int ev)
        {
            if ((ev & EngineStartSequence.EvStarterEngage) != 0)
                PlayShot(_engageClip, 0.75f, Random.Range(0.95f, 1.05f));
            if ((ev & EngineStartSequence.EvCough) != 0)
                PlayShot(_coughClip, Random.Range(0.65f, 1f), Random.Range(0.85f, 1.15f));
            if ((ev & EngineStartSequence.EvLightOff) != 0)
                PlayShot(_lightClip, 0.9f, Random.Range(0.95f, 1.05f));
            if ((ev & EngineStartSequence.EvMisfire) != 0)
                PlayShot(_popClip, Random.Range(0.3f, 0.6f), Random.Range(0.9f, 1.2f));
            if ((ev & EngineStartSequence.EvShutdown) != 0 && !_turboprop)
            {
                // the last few cylinders fire raggedly as the mixture is cut
                _shutdownPops = Random.Range(1, 4);
                _shutdownTimer = Random.Range(0.05f, 0.15f);
            }
            if ((ev & EngineStartSequence.EvPropStopped) != 0)
                PlayShot(_stopClip, 0.7f, Random.Range(0.9f, 1.1f));
        }

        public void Backfire()
        {
            PlayShot(_backfireClip, 1f, Random.Range(0.92f, 1.08f));
        }

        public string StrikeClipName(bool water)
        {
            AudioClip c = water ? _strikeWaterClip : _strikeClip;
            return c != null ? c.name + " (" + c.length.ToString("F1") + " s)" : "MISSING";
        }

        /// <summary>The engine stops dead: everything that turns falls silent at once, then the crash.</summary>
        public void PropStrike(bool water)
        {
            if (_all != null)
            {
                for (int i = 0; i < _all.Length; i++)
                {
                    if (_all[i] == _wind)
                        continue;
                    _all[i].vol = 0f;
                    _all[i].src.volume = 0f;
                    _all[i].src.Stop();
                }
            }
            _shutdownPops = 0;
            _afterfire = 0f;
            _overrun = 0f;
            AudioClip clip = water ? _strikeWaterClip : _strikeClip;
            if (_strikeSrc == null || clip == null || _paused)
                return;
            _strikeSrc.Stop();
            _strikeSrc.clip = clip;
            _strikeSrc.pitch = Random.Range(0.94f, 1.06f);
            _strikeSrc.volume = Mathf.Clamp01(Mathf.Max(_master, 0.5f * GameSettings.SHIP_VOLUME));
            _strikeSrc.Play();
        }

        private AudioSource _strikeSrc;

        /// <summary>Afterfire pops played since the last call (the module flashes the exhaust flames).</summary>
        public int TakePops()
        {
            int p = _pops;
            _pops = 0;
            return p;
        }

        private void PlayShot(AudioClip clip, float vol, float pitch)
        {
            if (_shots == null || clip == null || _paused)
                return;
            int i = _nextShot;
            _nextShot = (_nextShot + 1) % _shots.Length;
            AudioSource s = _shots[i];
            s.Stop();
            s.clip = clip;
            s.pitch = Mathf.Clamp(pitch * _doppler, 0.1f, 3f);
            s.volume = Mathf.Clamp01(vol * _master);
            _shotLpf[i].cutoffFrequency = _cutoff;
            // Engines started together cough, clunk and pop in the same frame: four copies of a
            // cough in the same instant stack into one loud bang (2x the peak), so each engine of
            // the vessel plays its one-shots a few hundredths of a second after the one before it
            int slot = Mathf.Min(VesselSlot(), 6);
            float delay = slot * 0.07f + Random.Range(0f, 0.04f);
            if (delay > 0.001f)
                s.PlayDelayed(delay);
            else
                s.Play();
        }

        /// <summary>
        /// Unity plays only a limited number of voices at once. The first engine of each vessel keeps
        /// a high priority; the others drop below Unity's default (128), so on a craft with many
        /// engines Unity silences some of our identical engine copies first, not other sounds.
        /// </summary>
        private void UpdatePriority(bool lead)
        {
            int state = _preview || lead ? 1 : 2;
            if (state == _priorityState || _all == null)
                return;
            _priorityState = state;
            int loopPri = state == 1 ? 64 : 160;
            int shotPri = state == 1 ? 80 : 170;
            for (int i = 0; i < _all.Length; i++)
                if (_all[i].src != null) _all[i].src.priority = loopPri;
            for (int i = 0; i < _shots.Length; i++)
                if (_shots[i] != null) _shots[i].priority = shotPri;
        }

        private int _priorityState;

        /// <summary>Position of this engine among the vessel's engine sounds (0 = the first).</summary>
        private int VesselSlot()
        {
            if (_preview || _part == null || _part.vessel == null)
                return 0;
            int slot = 0;
            for (int i = 0; i < Instances.Count; i++)
            {
                PropellerAudio o = Instances[i];
                if (o == this)
                    return slot;
                if (o._root != null && o._part != null && o._part.vessel == _part.vessel)
                    slot++;
            }
            return slot;
        }

        public void SetPaused(bool paused)
        {
            _paused = paused;
            if (_all == null)
                return;
            for (int i = 0; i < _all.Length; i++)
                Pause(_all[i].src, paused);
            for (int i = 0; i < _shots.Length; i++)
                Pause(_shots[i], paused);
            Pause(_strikeSrc, paused);
        }

        private static void Pause(AudioSource s, bool paused)
        {
            if (s == null) return;
            if (paused) s.Pause();
            else s.UnPause();
        }

        /// <summary>Silences everything at once (preview stopped).</summary>
        public void StopAll()
        {
            if (_all == null)
                return;
            for (int i = 0; i < _all.Length; i++)
            {
                _all[i].vol = 0f;
                _all[i].src.volume = 0f;
                _all[i].src.Stop();
            }
            for (int i = 0; i < _shots.Length; i++)
                _shots[i].Stop();
            if (_strikeSrc != null)
                _strikeSrc.Stop();
            _shutdownPops = 0;
            _afterfire = 0f;
            _overrun = 0f;
            _load = _loadSlow = 0f;
        }

        public void Destroy()
        {
            Instances.Remove(this);
            if (_root != null)
                Object.Destroy(_root);
            _root = null;
            _all = null;
            _shots = null;
        }

        // ================================================================ mixing

        public void Tick(float dt, EngineSoundInput s)
        {
            if (_root == null || _paused || dt <= 0f)
                return;

            bool iva = false;
            bool rails = false;
            float cosA = 0.3f;   // preview: standing a little ahead of the wing, to one side
            float dist = 12f;
            float dopplerTarget = 1f;
            if (!_preview)
            {
                rails = TimeWarp.CurrentRate > 1f && TimeWarp.WarpMode == TimeWarp.Modes.HIGH;
                iva = CameraManager.Instance != null &&
                      (CameraManager.Instance.currentCameraMode == CameraManager.CameraMode.IVA ||
                       CameraManager.Instance.currentCameraMode == CameraManager.CameraMode.Internal);
                Geometry(out cosA, out dist, out dopplerTarget);
            }
            _doppler += (dopplerTarget - _doppler) * (1f - Mathf.Exp(-dt / 0.15f));

            // Directivity
            float side = Mathf.Sqrt(Mathf.Max(0f, 1f - cosA * cosA));
            float behind = Mathf.Max(0f, -cosA);
            float ahead = Mathf.Max(0f, cosA);
            float wProp = 0.62f + 0.38f * side + 0.15f * behind;
            float wExh = 0.72f + 0.22f * side + 0.22f * behind;
            float wFront = 0.55f + 0.55f * ahead;
            float wRear = 0.60f + 0.50f * behind;
            if (iva)
            {
                wProp = 0.85f;
                wExh = 1f;
                wFront = 0.7f;
                wRear = 0.8f;
            }

            _master = GameSettings.SHIP_VOLUME * Mathf.Sqrt(Mathf.Clamp01(s.pressure)) * (iva ? 0.7f : 1f) * (_preview ? 0.85f : 1f);
            if (rails)
                _master = 0f;
            // Air absorbs the highs of a distant engine; the cockpit muffles everything
            _cutoff = iva ? 2400f : Mathf.Clamp(22000f * Mathf.Exp(-dist / 700f), 1200f, 22000f);

            _load += (Mathf.Clamp01(s.load) - _load) * (1f - Mathf.Exp(-dt / 0.2f));
            _loadSlow += (_load - _loadSlow) * (1f - Mathf.Exp(-dt / 1.2f));
            UpdateMisfire(dt, s.roughness);
            UpdateDrift(dt);
            // One pitch drift and wobble for the whole vessel (gain drift and misfire dips stay per engine)
            PropellerAudio leader = PitchLeader();
            if (leader != this)
            {
                _driftPitch = leader._driftPitch;
                _wobble = leader._wobble;
            }
            UpdatePriority(leader == this);

            // Airflow over the airframe (one engine per vessel plays it); loudest in the cockpit
            float v = Mathf.Max(0f, s.windSpeed);
            // (0.75: the recorded wind loop sits 3 dB below the old synthesized one to keep its peaks clean)
            float wind = 0.75f * Mathf.Pow(Mathf.Clamp01(v / 220f), 1.4f) * (iva ? 1.4f : 1f);
            Set(_wind, wind, Mathf.Clamp(0.55f + 0.45f * v / WindRefSpeed, 0.5f, 1.9f), 22000f, dt, 1f, 2f);

            if (_turboprop)
            {
                TickTurbine(dt, s, wFront, wRear);
                SilencePiston(dt);
            }
            else
            {
                TickPiston(dt, s, wExh, wFront);
                SilenceTurbine(dt);
            }
            Set(_starter, Mathf.Pow(Mathf.Clamp01(s.starter), 0.6f) * 0.42f, (0.3f + 0.75f * s.starter) * _doppler, 22000f, dt, 1f, 8f);
            TickProp(dt, s, wProp);
            TickShutdownPops(dt);

            for (int i = 0; i < _shots.Length; i++)
                if (_shots[i].isPlaying)
                    _shotLpf[i].cutoffFrequency = _cutoff;
        }

        private void TickPiston(float dt, EngineSoundInput s, float wExh, float wFront)
        {
            float rpm = Mathf.Max(0f, s.engineRPM);
            // The loops were made with 18 (radial) / 12 (V-12) cylinders. What the ear hears as the
            // engine's pitch is the firing frequency, so other cylinder counts play them at the
            // "equivalent" rpm: a 9-cylinder sounds an octave deeper, an X-24 an octave higher.
            float eq = rpm * _cylinders / _refCylinders;
            float a = Smooth(950f, 1350f, eq);
            float b = Smooth(1950f, 2350f, eq);
            float wI = Mathf.Cos(a * HalfPi);
            float wM = Mathf.Sin(a * HalfPi) * Mathf.Cos(b * HalfPi);
            float wH = Mathf.Sin(a * HalfPi) * Mathf.Sin(b * HalfPi);
            float rpmFrac = Mathf.Clamp01(rpm / _maxEngineRPM);

            // Overrun: throttle closed with the propeller still turning the engine fast
            float overTarget = s.phase == EnginePhase.Running ? Smooth(0.42f, 0.75f, rpmFrac) * Mathf.Clamp01(1f - _load * 3f) : 0f;
            _overrun += (overTarget - _overrun) * (1f - Mathf.Exp(-dt / 0.3f));

            // On-load (hard, bright firing) vs off-load (soft, uneven, crackling) recordings
            float on = Smooth(0.10f, 0.60f, _load + (s.wep ? 0.2f : 0f));
            float wOn = Mathf.Sin(on * HalfPi);
            float wOff = Mathf.Cos(on * HalfPi);

            float fire = Mathf.Pow(Mathf.Clamp01(s.firing), 0.7f);
            float eng = fire * (0.72f + 0.28f * _load) * (0.75f + 0.25f * rpmFrac) * (s.wep ? 1.12f : 1f) * (1f + _driftGain) * wExh;
            float bright = Mathf.Lerp(5000f, 22000f, Mathf.Clamp01(0.3f + 0.7f * _load + (s.wep ? 0.1f : 0f)));
            float pitchMul = (1f + 0.025f * s.roughness * _wobble + _driftPitch) * _doppler;
            float dipMul = 1f - _dip;
            Set(_eIdle, eng * wI, eq / IdleRef * pitchMul, bright, dt, dipMul);
            Set(_eMid, eng * wM * wOn, eq / MidRef * pitchMul, bright, dt, dipMul);
            Set(_eMidOff, eng * wM * wOff, eq / MidRef * pitchMul, 22000f, dt, dipMul);
            Set(_eHigh, eng * wH * wOn, eq / HighRef * pitchMul, bright, dt, dipMul);
            Set(_eHighOff, eng * wH * wOff, eq / HighRef * pitchMul, 22000f, dt, dipMul);

            // Starter turning the engine: a chug on every compression stroke
            float crank = s.starterEngaged ? 0.85f * (1f - 0.8f * Mathf.Clamp01(s.firing)) : 0f;
            float strokesHz = rpm * _cylinders * 0.5f / 60f;
            Set(_crank, crank, strokesHz / CrankRefHz * _doppler, 22000f, dt, 1f, 8f);

            // Supercharger / turbo whine
            float blower = _supercharged ? s.boost * fire * (0.25f + 0.75f * _load) * 0.30f * wFront : 0f;
            Set(_super, blower, rpm / SuperRefRPM * Mathf.Max(0.3f, s.boostPitch) * _doppler, 22000f, dt, 1f);

            // Afterfire: chop the throttle at high rpm and the exhaust pops and crackles for a while
            if (s.phase == EnginePhase.Running && rpmFrac > 0.55f && _loadSlow - _load > 0.22f && _afterfire <= 0f)
                _afterfire = 2.5f;
            if (_afterfire > 0f)
                _afterfire -= dt;
            float popRate = (_afterfire > 0f ? 5f * _afterfire / 2.5f : 0f) + 0.6f * _overrun;
            if (popRate > 0f && Random.value < popRate * dt)
            {
                PlayShot(_popClip, Random.Range(0.35f, 0.85f), Random.Range(0.85f, 1.2f));
                _pops++;
            }
        }

        private void TickTurbine(float dt, EngineSoundInput s, float wFront, float wRear)
        {
            float n = Mathf.Clamp(s.coreN, 0f, 1.1f);
            // The compressor is audible from the first turns on the starter, rising in pitch with N
            float whine = Mathf.Pow(Mathf.Clamp01(n), 0.75f) * (0.6f + 0.4f * _load) * 0.85f * wFront * (1f + _driftGain);
            Set(_tWhine, whine, Mathf.Max(0.08f, n) * (1f + _driftPitch) * _doppler, 22000f, dt, 1f, 8f);
            // Once lit the combustor roars at once (it doesn't wait for power)
            float fire = Mathf.Pow(Mathf.Clamp01(s.firing), 0.6f);
            float roar = fire * (0.45f + 0.55f * Mathf.Pow(_load, 0.8f)) * (0.55f + 0.45f * Mathf.Clamp01(n)) * 0.85f * wRear * (s.reversed ? 1.15f : 1f);
            Set(_tRoar, roar, (0.70f + 0.35f * n) * _doppler, Mathf.Lerp(6000f, 22000f, 0.35f + 0.65f * _load), dt, 1f, 8f);
            Set(_igniter, s.igniters ? 0.45f : 0f, 1f, 22000f, dt, 1f, 20f);
        }

        private void TickProp(float dt, EngineSoundInput s, float wProp)
        {
            float bpf = _bladesTotal * Mathf.Max(0f, s.propRPM) / 60f;
            float tip = s.tipMach;
            float loud = Mathf.Pow(Mathf.Clamp01((tip - 0.12f) / 0.55f), 1.4f);
            float bite = s.feathered ? 0.08f : (0.30f + 0.70f * _load) * (s.reversed ? 1.3f : 1f);
            float pitch = Mathf.Clamp(bpf / PropRefBPF, 0.25f, 3f) * _doppler;
            // The piston loops are recordings of whole aircraft and already carry their propeller,
            // so the separate propeller layer only fills in for them. Turboprops get most of it:
            // the recorded blade slaps are peakier than the old synthesized loop, and in an offline
            // replica of this mixer 0.8 cost 0.25 dB of loudness but brought clipping at full ship
            // volume back to the old level (raising it instead added loudness only in tenths of a
            // dB and several times the clipping).
            float propMix = _turboprop ? 0.8f : 0.5f;
            Set(_pMain, loud * bite * 0.80f * propMix * wProp * (1f + _driftProp), pitch, 22000f, dt, 1f);
            float rasp = Smooth(0.80f, 1.02f, tip) * (s.feathered ? 0.1f : 0.35f + 0.65f * _load) * 0.65f * wProp;
            Set(_pRasp, rasp, pitch, 22000f, dt, 1f);
            // Turning slowly you hear every blade go past
            float swish = Smooth(0.7f, 3f, bpf) * (1f - Smooth(14f, 34f, bpf)) * 0.55f * wProp;
            Set(_pSwish, swish, Mathf.Clamp(bpf / SwishRefBPF, 0.1f, 3f) * _doppler, 22000f, dt, 1f);
        }

        private void SilencePiston(float dt)
        {
            Set(_eIdle, 0f, 1f, 22000f, dt, 1f);
            Set(_eMid, 0f, 1f, 22000f, dt, 1f);
            Set(_eHigh, 0f, 1f, 22000f, dt, 1f);
            Set(_eMidOff, 0f, 1f, 22000f, dt, 1f);
            Set(_eHighOff, 0f, 1f, 22000f, dt, 1f);
            Set(_crank, 0f, 1f, 22000f, dt, 1f);
            Set(_super, 0f, 1f, 22000f, dt, 1f);
        }

        private void SilenceTurbine(float dt)
        {
            Set(_tWhine, 0f, 1f, 22000f, dt, 1f);
            Set(_tRoar, 0f, 1f, 22000f, dt, 1f);
            Set(_igniter, 0f, 1f, 22000f, dt, 1f);
        }

        private void TickShutdownPops(float dt)
        {
            if (_shutdownPops <= 0)
                return;
            _shutdownTimer -= dt;
            if (_shutdownTimer > 0f)
                return;
            _shutdownPops--;
            _shutdownTimer = Random.Range(0.12f, 0.35f);
            PlayShot(Random.value < 0.5f ? _popClip : _coughClip, Random.Range(0.25f, 0.5f), Random.Range(0.8f, 1.05f));
            _pops++;
        }

        private void UpdateDrift(float dt)
        {
            _driftTimer -= dt;
            if (_driftTimer <= 0f)
            {
                _driftTimer = Random.Range(0.3f, 1.2f);
                _driftGainTarget = Random.Range(-0.06f, 0.06f);
                _driftPitchTarget = Random.Range(-0.003f, 0.003f);
                _driftPropTarget = Random.Range(-0.05f, 0.05f);
            }
            float k = 1f - Mathf.Exp(-dt / 0.5f);
            _driftGain += (_driftGainTarget - _driftGain) * k;
            _driftPitch += (_driftPitchTarget - _driftPitch) * k;
            _driftProp += (_driftPropTarget - _driftProp) * k;
        }

        private void UpdateMisfire(float dt, float roughness)
        {
            _wobble = Mathf.Clamp(_wobble + (Random.value - 0.5f) * dt * 12f, -1f, 1f);
            if (_dipTime > 0f)
            {
                _dipTime -= dt;
                _dip = _dipDepth;
                return;
            }
            _dip = 0f;
            if (roughness > 0.02f && Random.value < roughness * 6f * dt)
            {
                _dipTime = Random.Range(0.025f, 0.08f);
                _dipDepth = Random.Range(0.35f, 0.75f) * Mathf.Clamp01(roughness * 1.5f);
            }
        }

        /// <summary>
        /// Smoothly moves a layer to its target volume and sets pitch and brightness.
        /// instantMul is applied after smoothing (misfire dips must not be smoothed away).
        /// </summary>
        private void Set(Layer l, float target, float pitch, float bright, float dt, float instantMul, float rate = 5f)
        {
            if (l == null || l.src == null || l.src.clip == null)
                return;
            l.vol = Mathf.MoveTowards(l.vol, Mathf.Max(0f, target), dt * rate);
            float v = l.vol * instantMul * _master;
            if (v > 0.0005f)
            {
                l.src.pitch = Mathf.Clamp(pitch, 0.03f, 3f);
                l.src.volume = Mathf.Clamp01(v);
                if (l.lpf != null)
                    l.lpf.cutoffFrequency = Mathf.Min(bright, _cutoff);
                if (!l.src.isPlaying)
                    StartLoop(l);
            }
            else if (l.src.isPlaying)
            {
                l.src.volume = 0f;
                l.src.Stop();
            }
        }

        private static float Smooth(float edge0, float edge1, float x)
        {
            float t = Mathf.Clamp01((x - edge0) / (edge1 - edge0));
            return t * t * (3f - 2f * t);
        }

        private void Geometry(out float cosA, out float dist, out float doppler)
        {
            cosA = 0.3f;
            dist = 12f;
            doppler = 1f;
            if (_part == null)
                return;
            Transform lt = ListenerTransform();
            if (lt == null)
                return;
            Vector3 d = lt.position - _root.transform.position;
            dist = d.magnitude;
            if (dist < 0.01f)
                return;
            Vector3 dir = d / dist;
            cosA = Vector3.Dot(_part.transform.up, dir);
            // The camera rides with the active vessel; other vessels' engines get a Doppler shift
            Vessel v = _part.vessel;
            Vessel active = FlightGlobals.ActiveVessel;
            if (v != null && active != null && v != active)
            {
                Vector3 rel = (Vector3)(v.obt_velocity - active.obt_velocity);
                float closing = Vector3.Dot(rel, dir);
                doppler = Mathf.Clamp(340f / Mathf.Max(60f, 340f - closing), 0.6f, 1.6f);
            }
        }

        private static Transform ListenerTransform()
        {
            if ((_listener == null || !_listener.isActiveAndEnabled) && Time.unscaledTime >= _listenerCheck)
            {
                _listenerCheck = Time.unscaledTime + 2f;
                _listener = Object.FindObjectOfType<AudioListener>();
            }
            if (_listener != null && _listener.isActiveAndEnabled)
                return _listener.transform;
            return FlightCamera.fetch != null ? FlightCamera.fetch.transform : null;
        }
    }
}
