using System;
using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    public class ModuleProceduralPropeller : PartModule, IPartMassModifier, IPartCostModifier, IPartSizeModifier
    {
        private const float BlurStartRPM = 170f;   // prop RPM where the blur disc starts fading in
        private const float BlurFullRPM = 430f;    // prop RPM where the disc is fully visible
        private const float BladePitchRef = 21.25f; // mesh twist at 75 % radius with zero collective
        private const string LiveryPath = "ROPlanesPlus/Parts/PropShared/ropp_livery_";

        // ==================== FAR Transform Exception Fields ====================
        // Referenced by FARPartModuleTransformExceptions so FAR never voxelizes spinning parts
        [KSPField] public string frontHubTransformName = "FrontPropHub";
        [KSPField] public string rearHubTransformName = "RearPropHub";
        [KSPField] public string frontBladesTransformName = "FrontBladesMesh";
        [KSPField] public string rearBladesTransformName = "RearBladesMesh";
        [KSPField] public string frontDiscTransformName = "FrontRotorDisc";
        [KSPField] public string rearDiscTransformName = "RearRotorDisc";

        // ==================== Design (persisted; edited in the Engine Workshop window) ====================

        [KSPField(isPersistant = true)] public string selectedPreset = "R2800";
        [KSPField(isPersistant = true)] public string liveryName = "US Navy Sea Blue";
        [KSPField(isPersistant = true)] public string architectureName = "Radial";
        [KSPField(isPersistant = true)] public string subStyleName = "A";
        [KSPField(isPersistant = true)] public float shaftPowerHP = 2100f;
        [KSPField(isPersistant = true)] public string aspirationName = "1-Stage 2-Speed";
        [KSPField(isPersistant = true)] public float criticalAltitudeKm = 7.9f;
        [KSPField(isPersistant = true)] public float maxEngineRPM = 2800f;
        [KSPField(isPersistant = true)] public float propDiameter = 4.01f;
        [KSPField(isPersistant = true)] public float bladeCountFloat = 4f;
        [KSPField(isPersistant = true)] public bool isContraRotating = false;
        [KSPField(isPersistant = true)] public string bladePlanformName = "Wide Paddle";
        [KSPField(isPersistant = true)] public string spinnerStyleName = "Rounded Dome";
        [KSPField(isPersistant = true)] public float cowlDiameter = 1.34f;
        [KSPField(isPersistant = true)] public float cowlLength = 1.55f;
        [KSPField(isPersistant = true)] public string nacelleName = "Firewall Mount";
        [KSPField(isPersistant = true)] public bool isPusher = false;
        [KSPField(isPersistant = true)] public bool autoCowl = true;      // size the cowling to fit the engine
        [KSPField(isPersistant = true)] public bool propStrikes = true;   // propeller breaks if it hits the ground
        [KSPField(isPersistant = true)] public bool autoFeather = true;   // turboprops feather when the engine stops
        [KSPField(isPersistant = true)] public bool propTorque = false;   // reaction torque on the airframe (AJE applies none)
        [KSPField(isPersistant = true)] public string paintCowl = "B21E20";     // Custom Paint colours
        [KSPField(isPersistant = true)] public string paintNose = "ECECE8";
        [KSPField(isPersistant = true)] public string paintSpinner = "ECECE8";
        [KSPField(isPersistant = true)] public int paintFinish = 1;              // 0 matt, 1 satin, 2 gloss
        [KSPField(isPersistant = true)] public int cylindersPerRow = 0;          // per radial row / inline bank; 0 = layout default
        [KSPField(isPersistant = true)] public float cylinderLitres = 0f;        // custom pistons: swept volume per cylinder; 0 = from power
        [KSPField(isPersistant = true)] public int cowlFit = 1;                  // 0 tight, 1 standard, 2 roomy
        [KSPField(isPersistant = true)] public float boostInHg = 0f;             // custom pistons: manifold pressure; 0 = supercharger default
        [KSPField(isPersistant = true)] public int propRotation = 0;             // 0 clockwise, 1 counter-clockwise, seen from behind looking forward
        [KSPField(isPersistant = true)] public bool handedPair = false;          // symmetry: engines on the other side turn the other way

        // Kept for craft/config compatibility; always derived from the architecture.
        [KSPField(isPersistant = true)]
        public bool isTurboprop = false;

        public static readonly string[] DesignFieldNames = new string[]
        {
            "selectedPreset", "liveryName", "architectureName", "subStyleName", "shaftPowerHP",
            "aspirationName", "criticalAltitudeKm", "maxEngineRPM", "propDiameter", "bladeCountFloat",
            "isContraRotating", "bladePlanformName", "spinnerStyleName", "cowlDiameter", "cowlLength",
            "nacelleName", "isPusher", "autoCowl", "propStrikes", "autoFeather",
            "paintCowl", "paintNose", "paintSpinner", "paintFinish",
            "cylindersPerRow", "cylinderLitres", "cowlFit", "boostInHg", "propTorque",
            "propRotation", "handedPair"
        };

        /// <summary>
        /// Way the (front) propeller turns about the part's +Y (forward) axis, in Unity's rotation
        /// sense, where a positive angle is clockwise seen from in front. Clockwise seen from behind
        /// (the pilot's view, propRotation 0) is therefore -1. The rear propeller of a contra pair
        /// turns the other way; the blades are built to match (PropellerMeshGenerator).
        /// </summary>
        public float SpinSign
        {
            get { return propRotation == 1 ? 1f : -1f; }
        }

        // ==================== Part menu ====================

        [KSPField(guiActiveEditor = true, guiActive = false, guiName = "Engine")]
        public string engineNameDisplay = "-";

        [KSPField(guiActiveEditor = true, guiActive = false, guiName = "Spec")]
        public string specDisplay = "-";

        [KSPField(guiActive = true, guiActiveEditor = false, guiName = "Power")]
        public string powerDisplay = "-";

        [KSPField(guiActive = true, guiActiveEditor = false, guiName = "Propeller")]
        public string propDisplay = "-";

        [KSPField(isPersistant = true)] public float cowlFlapPercent = 20f;
        [KSPField(isPersistant = true)] public bool wepEngaged = false;
        [KSPField(isPersistant = true)] public float wepRemainingSec = 300f;
        [KSPField(isPersistant = true)] public bool isFeathered = false;
        [KSPField(isPersistant = true)] public bool isReversed = false;
        [KSPField(isPersistant = true)] public bool propDamaged = false;
        [KSPField(isPersistant = true)] public int propDamageSeed = 0;      // shape of the broken blades
        [KSPField(isPersistant = true)] public bool autoFeathered = false;

        // ==================== Index helpers ====================

        public int architectureIndex
        {
            get { return PropellerPresets.ParseArchitecture(architectureName); }
            set { architectureName = PropellerPresets.ArchitectureOptions[Mathf.Clamp(value, 0, 2)]; }
        }

        public int subStyleIndex
        {
            get { return PropellerPresets.ParseSubStyle(subStyleName); }
            set { subStyleName = PropellerPresets.SubStyleOptions[Mathf.Clamp(value, 0, 2)]; }
        }

        public int bladeCount
        {
            get { return Mathf.Clamp(Mathf.RoundToInt(bladeCountFloat), 2, 8); }
            set { bladeCountFloat = Mathf.Clamp(value, 2, 8); }
        }

        public int bladePlanformIndex
        {
            get { return MatchOptionIndex(PropellerPresets.BladePlanformOptions, bladePlanformName, 1); }
            set { bladePlanformName = PropellerPresets.BladePlanformOptions[Mathf.Clamp(value, 0, 2)]; }
        }

        public int spinnerStyleIndex
        {
            get { return MatchOptionIndex(PropellerPresets.SpinnerStyleOptions, spinnerStyleName, 1); }
            set { spinnerStyleName = PropellerPresets.SpinnerStyleOptions[Mathf.Clamp(value, 0, 3)]; }
        }

        public int nacelleIndex
        {
            get { return MatchOptionIndex(PropellerPresets.NacelleOptions, nacelleName, 0); }
            set { nacelleName = PropellerPresets.NacelleOptions[Mathf.Clamp(value, 0, 2)]; }
        }

        public int aspirationIndex
        {
            get { return MatchOptionIndex(PropellerPresets.AspirationOptions, aspirationName, 2); }
            set { aspirationName = PropellerPresets.AspirationOptions[Mathf.Clamp(value, 0, 5)]; }
        }

        public bool IsTurboprop { get { return architectureIndex == (int)EngineArchitecture.Turboprop; } }

        /// <summary>Cylinders per radial row / inline bank (resolved), and in total (0 for turboprops).</summary>
        public int CylindersPerRowResolved { get { return PropellerPhysicsEngine.CylindersPerRow(this); } }
        public int TotalCylinders { get { return PropellerPhysicsEngine.CylinderCount(this); } }

        /// <summary>
        /// Before the first edit of a preset (or legacy custom engine), fix the cylinder size so that
        /// from then on power follows the design (cylinders x size x rpm x boost) instead of the
        /// other way round. Chosen so the power doesn't jump on that first edit.
        /// </summary>
        public void FreezeDisplacement()
        {
            if (IsTurboprop || cylinderLitres > 0f)
                return;
            // A preset keeps its real displacement; the boost that gives its real power from it
            // becomes the design's boost (Merlin 66: 27 L at 3000 rpm and ~77 inHg = 1975 hp).
            PropellerPreset p = ActivePreset;
            AspirationType asp = (AspirationType)Mathf.Clamp(aspirationIndex, 0, 5);
            if (p != null && p.displacement > 1.0 && asp != AspirationType.NaturallyAspirated)
            {
                float rpm = Mathf.Clamp(maxEngineRPM, 1800f, 3400f);
                float need = shaftPowerHP / (5.2e-6f * rpm * (float)p.displacement);
                float min, max;
                PropellerPhysicsEngine.BoostRange(asp, out min, out max);
                boostInHg = Mathf.Round(Mathf.Clamp(need, min, max) * 2f) / 2f;
            }
            cylinderLitres = Mathf.Clamp(PropellerPhysicsEngine.LitresFromPower(this, shaftPowerHP),
                PropellerPhysicsEngine.MinCylinderLitres, PropellerPhysicsEngine.MaxCylinderLitres);
        }

        /// <summary>Sets the power by resizing the cylinders (the Workshop's power slider).</summary>
        public void SetPowerViaCylinders(float hp)
        {
            if (IsTurboprop)
            {
                shaftPowerHP = hp;
                return;
            }
            cylinderLitres = Mathf.Clamp(PropellerPhysicsEngine.LitresFromPower(this, hp),
                PropellerPhysicsEngine.MinCylinderLitres, PropellerPhysicsEngine.MaxCylinderLitres);
            shaftPowerHP = PropellerPhysicsEngine.PowerFromLitres(this, cylinderLitres);
        }

        public PropellerPreset ActivePreset
        {
            get
            {
                if (string.Equals(selectedPreset, PropellerPresets.CustomId, StringComparison.OrdinalIgnoreCase))
                    return null;
                return PropellerPresets.GetPreset(selectedPreset);
            }
        }

        public PropellerPerformanceMetrics CurrentMetrics { get { return _metrics; } }
        public PropellerLiveState CurrentLiveState { get { return _live; } }
        public float LiveThrustKN { get { return _eng != null ? _eng.finalThrust : 0f; } }
        public bool LiveRunning { get { return EngineRunning(); } }
        public EnginePhase LivePhase
        {
            get
            {
                if (_seq != null) return _seq.Phase;
                return EngineRunning() ? EnginePhase.Running : EnginePhase.Off;
            }
        }

        // ==================== Runtime state ====================

        private Transform _frontHubTr;
        private Transform _rearHubTr;
        private Transform _frontDiscTr;
        private Transform _rearDiscTr;
        private Transform _thrustTr;
        private Transform _exhaustLTr;
        private Transform _exhaustRTr;

        private Mesh _cowlMesh, _coreMesh, _exhMesh, _flapMesh;
        private Mesh _fSpinMesh, _fBladesMesh, _fDiscMesh;
        private Mesh _rSpinMesh, _rBladesMesh, _rDiscMesh;
        private Mesh _cowlColMesh, _spinColMesh;
        private MeshCollider _cowlCollider, _spinCollider;

        private Renderer _fBladesRenderer, _rBladesRenderer, _fDiscRenderer, _rDiscRenderer;
        private readonly List<Renderer> _bodyRenderers = new List<Renderer>();
        private Renderer _exhaustRenderer;
        private Material _bodyMat, _exhaustMat, _fDiscMat, _rDiscMat;
        private Material _prefabBodyMat, _prefabDiscMat;
        private readonly List<Material> _ourMaterials = new List<Material>();
        private int _adoptCount;
        private bool _adoptLogged;
        private readonly List<UnityEngine.Object> _ownedObjects = new List<UnityEngine.Object>();

        private ModuleEngines _eng;
        private AJEBridge _aje;
        private PropellerAudio _audio;
        private PropellerPerformanceMetrics _metrics;
        private PropellerLiveState _live;

        private string _lastFullSig = string.Empty;
        private string _lastEngineSig = string.Empty;
        private string _lastPreset = string.Empty;
        private string _lastLiveryApplied = string.Empty;
        private int _lastArchIdx = -1;
        private bool _isSyncing;

        private float _visualRPM;
        private float _frontAngle;
        private float _rearAngle;
        private float _discSlowAngle;
        private float _builtPitchDelta = -999f;
        private float _visualPitchDelta;
        private float _builtFlap = -1f;
        private float _exhaustGlow;
        private bool _wasFlameout;
        private EngineStartSequence _seq;
        private bool _seedRPM;
        private bool _throttleWasClosed = true;
        private float _compPhase;
        private float _telemetryTimer;
        private float _appliedVolE = -1f;
        private float _appliedCt = -1f;
        private bool _appliedFeather;
        private bool _pauseHooked;
        private Texture2D _liveryTex;
        private float _materialCheckTimer;
        private float _strikeTimer;
        private float _featherTimer = -1f;
        private bool _fixedWasRunning;
        private float _restartNagTimer;
        private EngineEffects _effects;

        public float AutoCowlDiameter { get; private set; }
        public float AutoCowlLength { get; private set; }

        // ==================== Lifecycle ====================

        public override void OnStart(StartState state)
        {
            base.OnStart(state);

            NormalizeLegacyValues();
            if (HighLogic.LoadedSceneIsEditor)
            {
                propDamaged = false;
                autoFeathered = false;
            }
            _eng = part.FindModuleImplementing<ModuleEngines>();
            _aje = new AJEBridge(_eng);

            BindModelHierarchy();
            SetupMaterials();

            PropellerPreset preset = ActivePreset;
            if (preset != null)
                CopyPresetEngineFields(preset);

            _lastPreset = selectedPreset;
            _lastArchIdx = architectureIndex;
            _lastEngineSig = EngineSignature();

            RebuildEverything(false);
            ApplyLivery(true);

            if (HighLogic.LoadedSceneIsFlight)
            {
                _seq = new EngineStartSequence();
                _seq.Configure(this, _metrics);
                _seq.StartSeed = StartGroupSeed;
                _audio = new PropellerAudio();
                _audio.Init(part);
                _audio.Configure(this, _metrics);
                _effects = new EngineEffects();
                _effects.Init(_exhaustLTr, _exhaustRTr);
                _effects.Configure(this);
                GameEvents.onGamePause.Add(OnGamePause);
                GameEvents.onGameUnpause.Add(OnGameUnpause);
                _pauseHooked = true;
                _fixedWasRunning = EngineRunning();
                if (_fixedWasRunning)
                {
                    // Loaded already running (scene change, vessel switch): no start-up, spin the propeller up
                    _seq.SetRunning(0f);
                    _seedRPM = true;
                }
                else
                {
                    _seq.Warmth = vessel != null && vessel.LandedOrSplashed ? 0f : 0.6f;
                }
            }
        }

        public void OnDestroy()
        {
            if (_pauseHooked)
            {
                GameEvents.onGamePause.Remove(OnGamePause);
                GameEvents.onGameUnpause.Remove(OnGameUnpause);
                _pauseHooked = false;
            }
            if (_audio != null)
            {
                _audio.Destroy();
                _audio = null;
            }
            if (_effects != null)
            {
                _effects.Destroy();
                _effects = null;
            }
            for (int i = 0; i < _ownedObjects.Count; i++)
            {
                if (_ownedObjects[i] != null)
                    Destroy(_ownedObjects[i]);
            }
            _ownedObjects.Clear();
        }

        private void OnGamePause()
        {
            if (_audio != null) _audio.SetPaused(true);
        }

        private void OnGameUnpause()
        {
            if (_audio != null) _audio.SetPaused(false);
        }

        public void Update()
        {
            if (part == null || _cowlMesh == null)
                return;
            _materialCheckTimer -= Time.unscaledDeltaTime;
            if (_materialCheckTimer <= 0f)
            {
                _materialCheckTimer = 0.3f;
                EnsureMaterials();
            }
            if (HighLogic.LoadedSceneIsEditor)
                EditorUpdate();
            else if (HighLogic.LoadedSceneIsFlight)
                FlightUpdate(Time.deltaTime);
        }

        public void FixedUpdate()
        {
            if (HighLogic.LoadedSceneIsFlight && part != null && _eng != null)
                FlightFixedUpdate(TimeWarp.fixedDeltaTime);
        }

        // ==================== Editor ====================

        private float _editorCheckTimer;

        private void EditorUpdate()
        {
            if (_isSyncing)
                return;
            // The design checks build signature strings: 10 times a second is plenty and keeps the
            // editor from churning garbage every frame for every engine on the craft
            _editorCheckTimer -= Time.unscaledDeltaTime;
            if (_editorCheckTimer > 0f)
                return;
            _editorCheckTimer = 0.1f;

            if (!string.Equals(selectedPreset, _lastPreset, StringComparison.OrdinalIgnoreCase))
            {
                _lastPreset = selectedPreset;
                PropellerPreset p = ActivePreset;
                if (p != null)
                    ApplyPreset(p);
            }

            int arch = architectureIndex;
            if (arch != _lastArchIdx)
            {
                if (arch == (int)EngineArchitecture.Turboprop && !PropellerPresets.IsTechAvailable(PropellerPresets.TurbopropTech))
                {
                    architectureIndex = _lastArchIdx;
                    ScreenMessages.PostScreenMessage("Turboprops unlock with the Mature Supersonic tech node", 4f, ScreenMessageStyle.UPPER_CENTER);
                }
                else
                {
                    _lastArchIdx = arch;
                    OnArchitectureChanged();
                }
            }


            string engSig = EngineSignature();
            if (!string.Equals(engSig, _lastEngineSig, StringComparison.Ordinal))
            {
                _lastEngineSig = engSig;
                if (ActivePreset != null)
                {
                    selectedPreset = PropellerPresets.CustomId;
                    _lastPreset = selectedPreset;
                }
            }

            string sig = FullSignature();
            if (!string.Equals(sig, _lastFullSig, StringComparison.Ordinal))
                RebuildEverything(true);
            else if (handedPair)
                EnforceHandedness();
        }

        /// <summary>
        /// Handed propellers: KSP places symmetry copies as clones, so a new twin starts with the
        /// same rotation as the original. One engine per symmetry group (the lowest persistentId,
        /// so every engine agrees which) sets the other side's engines to the opposite rotation.
        /// </summary>
        private void EnforceHandedness()
        {
            if (part.symmetryCounterparts == null || part.symmetryCounterparts.Count == 0)
                return;
            Part master = HandedMaster();
            if (master != part)
                return;
            for (int i = 0; i < part.symmetryCounterparts.Count; i++)
            {
                Part p = part.symmetryCounterparts[i];
                ModuleProceduralPropeller sym = p != null ? p.FindModuleImplementing<ModuleProceduralPropeller>() : null;
                if (sym == null)
                    continue;
                int want = SameSideAsMaster(master, p) ? propRotation : 1 - propRotation;
                if (sym.propRotation == want && sym.handedPair)
                    continue;
                sym._isSyncing = true;
                try
                {
                    sym.propRotation = want;
                    sym.handedPair = true;
                    sym.RebuildEverything(false);
                }
                finally
                {
                    sym._isSyncing = false;
                }
            }
        }

        /// <summary>The engine of this symmetry group whose position defines the sides (lowest persistentId).</summary>
        private Part HandedMaster()
        {
            Part best = part;
            for (int i = 0; i < part.symmetryCounterparts.Count; i++)
            {
                Part p = part.symmetryCounterparts[i];
                if (p != null && p.persistentId < best.persistentId)
                    best = p;
            }
            return best;
        }

        /// <summary>
        /// Is p on the master engine's side of the aircraft? The dividing plane lies halfway between
        /// the master and its first counterpart, square to the line joining them: for a mirrored pair
        /// that is the aircraft's centreline plane; radial symmetry is split into two halves.
        /// </summary>
        private static bool SameSideAsMaster(Part master, Part p)
        {
            if (p == master || master.symmetryCounterparts == null || master.symmetryCounterparts.Count == 0)
                return true;
            Vector3 self = master.transform.position;
            Vector3 n = master.symmetryCounterparts[0].transform.position - self;
            if (n.sqrMagnitude < 1e-6f)
                return true;
            Vector3 mid = self + 0.5f * n;
            return Vector3.Dot(p.transform.position - mid, n) < 0f;
        }

        private void OnArchitectureChanged()
        {
            isTurboprop = IsTurboprop;
            if (IsTurboprop)
            {
                isFeathered = false;
                isReversed = false;
                if (maxEngineRPM < 2000f) maxEngineRPM = 2600f;
            }
        }

        public void ApplyPreset(PropellerPreset preset)
        {
            if (preset == null)
                return;

            CopyPresetEngineFields(preset);
            bladePlanformIndex = (int)preset.bladePlanform;
            spinnerStyleIndex = (int)preset.spinnerStyle;
            cowlDiameter = preset.cowlDiameter;
            cowlLength = preset.cowlLength;
            nacelleIndex = (int)preset.nacelleStyle;
            liveryName = preset.liveryName;
            isPusher = false;
            autoCowl = true;
            cowlFit = preset.cowlFit;

            selectedPreset = preset.id;
            _lastPreset = selectedPreset;
            _lastArchIdx = architectureIndex;
            _lastEngineSig = EngineSignature();
            RebuildEverything(true);
        }

        private void CopyPresetEngineFields(PropellerPreset preset)
        {
            architectureIndex = (int)preset.architecture;
            subStyleIndex = preset.subStyleIndex;
            cylindersPerRow = PropellerPhysicsEngine.ResolveCylindersPerRow((int)preset.architecture, preset.subStyleIndex, preset.cylindersPerRow);
            cylinderLitres = 0f; // fixed from the preset's power on the first edit (FreezeDisplacement)
            boostInHg = 0f;
            isTurboprop = preset.IsTurboprop;
            isContraRotating = preset.isContraRotating;
            shaftPowerHP = preset.shaftPowerHP;
            aspirationIndex = (int)preset.aspiration;
            criticalAltitudeKm = preset.CriticalAltitudeKm;
            maxEngineRPM = (float)preset.maxRPM;
            propDiameter = preset.propDiameter;
            bladeCount = preset.bladeCount;
        }

        // ==================== Rebuild ====================

        public void RebuildEverything(bool syncSymmetry)
        {
            if (_cowlMesh == null)
                return;

            isTurboprop = IsTurboprop;
            if (ActivePreset == null)
                EnforceEngineLimits();
            _metrics = PropellerPhysicsEngine.Evaluate(this);
            bool resized = ApplyCowlSizing();
            if (EnforcePropClearance())
                resized = true;
            if (resized)
                _metrics = PropellerPhysicsEngine.Evaluate(this);
            RebuildVisualMeshes(0f, cowlFlapPercent * 0.01f, true);
            PlaceExhaustTransforms();
            ApplyLivery(false);

            PropellerPhysicsEngine.ApplyToEngineModules(part, this, _metrics, _aje);
            _appliedVolE = -1f;
            _appliedCt = -1f;
            PropellerPhysicsEngine.NotifyFARRebuild(part);
            UpdateSpecDisplay();
            UpdateActionVisibility();

            _lastFullSig = FullSignature();

            if (syncSymmetry && HighLogic.LoadedSceneIsEditor && part.symmetryCounterparts != null)
                SyncToSymmetryCounterparts();

            if (HighLogic.LoadedSceneIsEditor && EditorLogic.fetch != null && EditorLogic.fetch.ship != null)
                GameEvents.onEditorShipModified.Fire(EditorLogic.fetch.ship);

            if (_seq != null)
                _seq.Configure(this, _metrics);
            if (_audio != null)
                _audio.Configure(this, _metrics);
            if (_effects != null)
                _effects.Configure(this);
        }

        private void RebuildVisualMeshes(float pitchDelta, float flap01, bool updateNodes)
        {
            float frontHubY, rearHubY, aftNodeY, fwdNodeY;
            PropellerMeshGenerator.BuildAllProceduralMeshes(
                this,
                _cowlMesh, _coreMesh, _exhMesh, _flapMesh,
                _fSpinMesh, _fBladesMesh, _fDiscMesh,
                _rSpinMesh, _rBladesMesh, _rDiscMesh,
                _cowlColMesh, _spinColMesh,
                pitchDelta, flap01,
                out frontHubY, out rearHubY, out aftNodeY, out fwdNodeY);
            _builtPitchDelta = pitchDelta;
            _builtFlap = flap01;
            ReclaimMeshes();

            if (_frontHubTr != null)
                _frontHubTr.localPosition = new Vector3(0f, frontHubY, 0f);
            if (_rearHubTr != null)
            {
                _rearHubTr.localPosition = new Vector3(0f, rearHubY, 0f);
                _rearHubTr.localScale = isContraRotating ? Vector3.one : new Vector3(0.0001f, 0.0001f, 0.0001f);
            }
            if (_thrustTr != null)
            {
                _thrustTr.localPosition = new Vector3(0f, frontHubY, 0f);
                UpdateThrustTransformDirection();
            }

            if (!updateNodes)
                return;

            if (_cowlCollider != null)
            {
                _cowlCollider.sharedMesh = null;
                _cowlCollider.sharedMesh = _cowlColMesh;
                _cowlCollider.convex = true;
            }
            if (_spinCollider != null)
            {
                _spinCollider.sharedMesh = null;
                _spinCollider.sharedMesh = _spinColMesh;
                _spinCollider.convex = true;
            }
            UpdateAttachNodes(aftNodeY, fwdNodeY);
        }

        /// <summary>
        /// Fits the cowling around the engine (cylinder count, layout, displacement). In manual mode
        /// it only stops the cowling from being smaller than the engine inside it.
        /// </summary>
        private bool ApplyCowlSizing()
        {
            float dia, len, tightDia, tightLen;
            cowlFit = Mathf.Clamp(cowlFit, 0, 2);
            PropellerPhysicsEngine.AutoCowl(this, _metrics.aje, cowlFit, out dia, out len);
            PropellerPhysicsEngine.AutoCowl(this, _metrics.aje, 0, out tightDia, out tightLen);
            AutoCowlDiameter = dia;
            AutoCowlLength = len;
            TightCowlDiameter = tightDia;
            float newDia = cowlDiameter;
            float newLen = cowlLength;
            if (autoCowl)
            {
                newDia = Mathf.Round(dia * 100f) / 100f;
                newLen = Mathf.Round(len * 100f) / 100f;
            }
            else
            {
                newDia = Mathf.Clamp(newDia, MinCowlDiameter, 2.6f);
                newLen = Mathf.Clamp(newLen, MinCowlLength, 4.0f);
            }
            bool changed = Mathf.Abs(newDia - cowlDiameter) > 1e-4f || Mathf.Abs(newLen - cowlLength) > 1e-4f;
            cowlDiameter = newDia;
            cowlLength = newLen;
            return changed;
        }

        // The cowling can be made bigger than the engine, never smaller than the tight fit.
        public float TightCowlDiameter { get; private set; }
        public float MinCowlDiameter { get { return Mathf.Max(0.5f, (TightCowlDiameter > 0.1f ? TightCowlDiameter : AutoCowlDiameter) * 0.99f); } }
        public float MinCowlLength { get { return Mathf.Max(0.6f, AutoCowlLength * 0.98f); } }

        /// <summary>The propeller must reach well past the cowling and spinner.</summary>
        public float MinPropDiameter { get { return Mathf.Max(1.2f, cowlDiameter * 1.45f); } }

        private bool EnforcePropClearance()
        {
            float min = MinPropDiameter;
            if (propDiameter >= min - 1e-4f)
                return false;
            propDiameter = Mathf.Ceil(min * 20f) / 20f;
            return true;
        }

        /// <summary>
        /// Keeps custom engines physically plausible: RPM in the piston range, rated altitude sane,
        /// and power inside what the chosen cylinders can make (1.0-4.2 L per cylinder).
        /// </summary>
        private void EnforceEngineLimits()
        {
            criticalAltitudeKm = Mathf.Clamp(criticalAltitudeKm, 0.5f, 12f);
            if (IsTurboprop)
            {
                maxEngineRPM = 2600f;
                float minHP, maxHP;
                string why;
                PropellerPhysicsEngine.GetPowerLimits(this, out minHP, out maxHP, out why);
                shaftPowerHP = Mathf.Clamp(shaftPowerHP, minHP, maxHP);
                return;
            }
            // Pistons: the design is cylinders x cylinder size; power follows (with rpm and boost)
            maxEngineRPM = Mathf.Clamp(maxEngineRPM, 1800f, 3400f);
            cylindersPerRow = CylindersPerRowResolved;
            if (boostInHg > 0f)
                boostInHg = PropellerPhysicsEngine.EffectiveBoostInHg(this);
            FreezeDisplacement();
            float litres = Mathf.Clamp(cylinderLitres, PropellerPhysicsEngine.MinCylinderLitres, PropellerPhysicsEngine.MaxCylinderLitres);
            maxEngineRPM = Mathf.Min(maxEngineRPM, PropellerPhysicsEngine.PistonSpeedLimitRPM(litres));
            float hp = PropellerPhysicsEngine.PowerFromLitres(this, litres);
            if (hp > PropellerPhysicsEngine.MaxPistonHP)
                litres = PropellerPhysicsEngine.LitresFromPower(this, PropellerPhysicsEngine.MaxPistonHP);
            else if (hp < 100f)
                litres = PropellerPhysicsEngine.LitresFromPower(this, 100f);
            cylinderLitres = Mathf.Round(litres * 100f) / 100f;
            shaftPowerHP = Mathf.Round(PropellerPhysicsEngine.PowerFromLitres(this, cylinderLitres));
        }

        /// <summary>
        /// Switches engine type keeping roughly the same engine weight: turboprops weigh ~0.18 kg/shp
        /// against ~0.45 kg/hp for pistons, so the same-size turboprop makes ~2.5x the power.
        /// </summary>
        public void ChangeArchitecture(int newArch)
        {
            int old = architectureIndex;
            if (newArch == old)
                return;
            bool wasTurbo = old == (int)EngineArchitecture.Turboprop;
            bool toTurbo = newArch == (int)EngineArchitecture.Turboprop;
            if (!wasTurbo && toTurbo)
                shaftPowerHP *= 2.5f;
            else if (wasTurbo && !toTurbo)
                shaftPowerHP /= 2.5f;
            architectureIndex = newArch;
            cylindersPerRow = 0;   // the new layout's default
            cylinderLitres = 0f;   // re-derived from the carried-over power
            boostInHg = 0f;
            if (toTurbo)
            {
                maxEngineRPM = 2600f;
                subStyleIndex = shaftPowerHP > 7000f ? 1 : (shaftPowerHP < 1500f ? 2 : 0);
            }
            else
            {
                if (wasTurbo)
                {
                    maxEngineRPM = 2700f;
                    aspirationIndex = (int)AspirationType.SingleStage2Speed;
                    criticalAltitudeKm = 6f;
                }
                subStyleIndex = 0;
            }
            MarkCustom();
        }

        private void PlaceExhaustTransforms()
        {
            Vector3 pL, dL, pR, dR;
            PropellerMeshGenerator.GetExhaustPorts(this, out pL, out dL, out pR, out dR);
            if (_exhaustLTr != null)
            {
                _exhaustLTr.localPosition = pL;
                _exhaustLTr.localRotation = Quaternion.LookRotation(dL, Vector3.back);
            }
            if (_exhaustRTr != null)
            {
                _exhaustRTr.localPosition = pR;
                _exhaustRTr.localRotation = Quaternion.LookRotation(dR, Vector3.back);
            }
        }

        // ==================== Flight ====================

        private bool EngineRunning()
        {
            return _eng != null && _eng.EngineIgnited && !_eng.flameout && _eng.isOperational;
        }

        private void FlightFixedUpdate(float dt)
        {
            bool running = EngineRunning();

            // A broken propeller keeps the engine from being restarted
            if (propDamaged && _eng.EngineIgnited)
            {
                _eng.Shutdown();
                running = false;
                _restartNagTimer -= dt;
                if (_restartNagTimer <= 0f)
                {
                    _restartNagTimer = 4f;
                    ScreenMessages.PostScreenMessage("Propeller wrecked: an engineer on EVA can replace it on the ground, or recover the craft", 4f, ScreenMessageStyle.UPPER_CENTER);
                }
            }

            UpdateAutoFeather(running, dt);
            CheckPropStrike(dt);
            _fixedWasRunning = running;
            bool engineUp = running && (_seq == null || _seq.Phase == EnginePhase.Running);

            // WEP timer
            bool wepActive = false;
            if (wepEngaged)
            {
                if (_metrics.wepMultiplier <= 1.001f || isFeathered)
                {
                    wepEngaged = false;
                    UpdateFlightButtonLabels();
                }
                else if (wepRemainingSec > 0f)
                {
                    if (engineUp)
                    {
                        wepRemainingSec = Mathf.Max(0f, wepRemainingSec - dt);
                        wepActive = true;
                    }
                }
                else
                {
                    wepEngaged = false;
                    ScreenMessages.PostScreenMessage("WEP limit reached", 3f, ScreenMessageStyle.UPPER_CENTER);
                    UpdateFlightButtonLabels();
                }
            }
            else if (wepRemainingSec < 300f)
            {
                wepRemainingSec = Mathf.Min(300f, wepRemainingSec + dt * 0.35f);
            }

            float volE = wepActive ? _metrics.wepMultiplier : 1f;
            AJEParameters a = _metrics.aje;
            float ct = (a != null ? a.ctTweak : 1f) * (isReversed ? 0.45f : 1f);

            if (_aje != null && _aje.Valid)
            {
                if (Mathf.Abs(volE - _appliedVolE) > 1e-4f || Mathf.Abs(ct - _appliedCt) > 1e-4f)
                {
                    _aje.ApplyTweaks(ct, a != null ? a.cpTweak : 1f, volE);
                    _appliedVolE = volE;
                    _appliedCt = ct;
                }
                if (isFeathered != _appliedFeather || Time.frameCount % 50 == 0)
                {
                    _aje.SetFeather(isFeathered);
                    _appliedFeather = isFeathered;
                }
                _live = _aje.ReadLiveState();
                DriveAJEPropeller(running, dt);
            }
            else
            {
                if (_seq != null)
                    _seq.Tick(dt, running, _live.propRPM);
                // Stock fallback: no thrust until the engine has caught
                float startGate = _seq == null || _seq.Phase == EnginePhase.Running ? 1f
                    : (_seq.Phase == EnginePhase.Catching ? 0.05f * _seq.Firing : 0f);
                float thrustMult = isFeathered ? 0.001f : (volE * (isReversed ? 0.45f : 1f));
                _eng.maxThrust = Mathf.Max(0.001f, _metrics.staticThrustKn * thrustMult * startGate);
                _live = FallbackLiveState(running, dt);
            }

            if (propTorque && engineUp)
                ApplyPropellerTorque();

            _telemetryTimer -= dt;
            if (_telemetryTimer <= 0f)
            {
                _telemetryTimer = 0.25f;
                UpdateFlightTelemetry(running, wepActive);
            }
        }

        // Engines of one vessel whose starts begin within StartGroupWindow seconds of the first one
        // share a seed, so they go through the start in step (see EngineStartSequence.StartSeed)
        private const float StartGroupWindow = 1.5f;
        private static readonly Dictionary<Guid, KeyValuePair<float, int>> StartGroups = new Dictionary<Guid, KeyValuePair<float, int>>();

        private int StartGroupSeed()
        {
            if (vessel == null)
                return UnityEngine.Random.Range(1, int.MaxValue);
            float now = Time.time;
            KeyValuePair<float, int> g;
            if (StartGroups.TryGetValue(vessel.id, out g) && now - g.Key >= 0f && now - g.Key < StartGroupWindow)
                return g.Value;
            int seed = UnityEngine.Random.Range(1, int.MaxValue);
            StartGroups[vessel.id] = new KeyValuePair<float, int>(now, seed);
            return seed;
        }

        /// <summary>
        /// AJE models the propeller's inertia and air loads but starts the engine with a starter of
        /// 20 % rated power (so it reaches running speed in about a second), stops making power at a
        /// closed throttle, and has no engine friction. While the start sequence runs, the propeller
        /// is held at the sequence's speed (cranking, catching, flare); with the throttle closed a
        /// piston engine idles; once shut down, friction and compression stop the propeller.
        /// Thrust and power with the engine running are left entirely to AJE.
        /// </summary>
        private void DriveAJEPropeller(bool ignition, float dt)
        {
            if (_seq == null)
                return;
            bool closed = _eng.currentThrottle <= 0f;
            if (_seedRPM)
            {
                _seedRPM = false;
                if (_live.propRPM < _seq.IdlePropRPM)
                {
                    float throttle = vessel != null ? vessel.ctrlState.mainThrottle : 0f;
                    float seed = throttle > 0f && !isFeathered ? _metrics.maxPropRPM * 0.95f : _seq.IdlePropRPM;
                    _aje.SetPropRPM(seed);
                    _live.propRPM = seed;
                    _visualRPM = seed;
                }
            }

            if (propDamaged)
            {
                // A struck propeller is wrecked and the engine stopped dead: it never turns again
                _seq.Tick(dt, false, 0f);
                _aje.SetPropRPM(0f);
                _live.propRPM = 0f;
                return;
            }

            _seq.Tick(dt, ignition, _live.propRPM);

            float pin = -1f;
            if (_seq.Starting)
            {
                pin = _seq.SeqPropRPM;
            }
            else if (_seq.Phase == EnginePhase.Running)
            {
                if (!isFeathered && _live.propRPM < _seq.IdlePropRPM)
                {
                    // Pistons idle at a closed throttle (a few percent of thrust, like the real thing).
                    // Turboprops idle in ground fine pitch at ~zero thrust, so AJE only gets the idle
                    // speed back when the throttle opens; the idle itself is shown, not flown.
                    if (closed && !IsTurboprop)
                        pin = _seq.IdlePropRPM;
                    else if (!closed && _throttleWasClosed && IsTurboprop)
                        pin = _seq.IdlePropRPM;
                }
            }
            else if (_live.propRPM > 0f)
            {
                pin = Mathf.Max(0f, _live.propRPM - _seq.OffDecel(_live.propRPM) * dt);
            }
            _throttleWasClosed = closed;

            if (pin >= 0f)
            {
                _aje.SetPropRPM(pin);
                _live.propRPM = pin;
            }
        }

        /// <summary>
        /// Reaction of the shaft torque on the airframe (AJE's propeller applies none): the airframe
        /// is twisted opposite to the way the propeller is drawn turning (SpinSign about +Y), so a
        /// propeller turning clockwise seen from behind rolls the aircraft left. Contra-rotating
        /// propellers cancel it, and so do handed pairs on a twin. Torque = shaft power / propeller
        /// angular speed.
        /// </summary>
        private void ApplyPropellerTorque()
        {
            if (isContraRotating || propDamaged || vessel == null || vessel.packed || part.Rigidbody == null)
                return;
            float rpm = _live.propRPM;
            float hp = _live.shaftHP;
            if (rpm < 60f || hp < 1f)
                return;
            float omega = rpm * (2f * Mathf.PI / 60f);
            float torqueKNm = Mathf.Min(hp * 745.7f / omega * 0.001f, 80f);
            part.AddTorque(-SpinSign * torqueKNm * part.transform.up);
        }

        private void UpdateAutoFeather(bool running, float dt)
        {
            if (!IsTurboprop || !autoFeather || vessel == null)
                return;
            if (running)
            {
                _featherTimer = -1f;
                if (autoFeathered)
                {
                    autoFeathered = false;
                    isFeathered = false;
                    UpdateFlightButtonLabels();
                }
                return;
            }
            if (_fixedWasRunning && !isFeathered && vessel.srfSpeed > 15.0 && !vessel.LandedOrSplashed)
                _featherTimer = 1.0f;
            if (_featherTimer > 0f)
            {
                _featherTimer -= dt;
                if (_featherTimer <= 0f)
                {
                    _featherTimer = -1f;
                    isFeathered = true;
                    autoFeathered = true;
                    isReversed = false;
                    UpdateThrustTransformDirection();
                    UpdateFlightButtonLabels();
                    ScreenMessages.PostScreenMessage("Engine out: propeller auto-feathered", 3f, ScreenMessageStyle.UPPER_CENTER);
                }
            }
        }

        private void CheckPropStrike(float dt)
        {
            if (!propStrikes || propDamaged || vessel == null || vessel.packed || _frontHubTr == null)
                return;
            if (_visualRPM < 60f)
                return;
            _strikeTimer -= dt;
            if (_strikeTimer > 0f)
                return;
            // Close to the ground: every physics frame, so a fast nose-in registers the blades hitting
            // before the cowling does (otherwise KSP may destroy the whole part first)
            _strikeTimer = vessel.radarAltitude < propDiameter + 4.0 ? 0f : 0.06f;
            // Nothing to hit up here: skip the raycasts
            if (vessel.radarAltitude > propDiameter + 25.0)
            {
                _strikeTimer = 0.5f;
                return;
            }

            Vector3 axis = part.transform.up;
            Vector3 radial = Vector3.Cross(axis, part.transform.forward).normalized;
            if (radial.sqrMagnitude < 0.5f)
                radial = Vector3.Cross(axis, part.transform.right).normalized;
            float radius = 0.5f * propDiameter * 0.96f;
            Vector3 hub = _frontHubTr.position;
            const int mask = (1 << 15) | (1 << 28); // local scenery + terrain colliders

            bool hit = false;
            bool water = false;
            RaycastHit info = new RaycastHit();
            for (int i = 0; i < 12 && !hit; i++)
            {
                Vector3 dir = Quaternion.AngleAxis(i * 30f, axis) * radial;
                hit = Physics.Raycast(hub, dir, out info, radius, mask, QueryTriggerInteraction.Ignore);
            }
            Vector3 point = hit ? info.point : hub;
            // Water only counts over the sea (terrain below sea level), never on a sea-level runway
            if (!hit && vessel.mainBody != null && vessel.mainBody.ocean && (vessel.Splashed || vessel.terrainAltitude < 0.0))
            {
                double alt = FlightGlobals.getAltitudeAtPos(hub, vessel.mainBody);
                hit = water = alt < radius * 0.85;
                Vector3 up = (hub - vessel.mainBody.position).normalized;
                point = hub - up * (float)Math.Max(0.0, alt);
            }
            if (!hit)
                return;

            bool paved = false;
            if (!water && info.collider != null)
            {
                string n = info.collider.gameObject.name.ToLowerInvariant();
                paved = n.Contains("runway") || n.Contains("pad") || n.Contains("ksc") || n.Contains("concrete") ||
                        (vessel.landedAt != null && vessel.landedAt.IndexOf("Runway", StringComparison.OrdinalIgnoreCase) >= 0);
            }
            ApplyPropStrike(hub, point, water, paved);
        }

        /// <summary>
        /// The blades dig in: the propeller and engine stop dead within a fraction of a revolution,
        /// the blades snap or curl back, the engine is wrecked (no restart until repaired).
        /// </summary>
        private void ApplyPropStrike(Vector3 hub, Vector3 point, bool water, bool paved)
        {
            float rpmAtStrike = _visualRPM;
            propDamaged = true;
            propDamageSeed = UnityEngine.Random.Range(1, int.MaxValue);
            isFeathered = false;
            wepEngaged = false;
            if (_eng != null && _eng.EngineIgnited)
                _eng.Shutdown();
            _visualRPM = 0f;
            _live.propRPM = 0f;
            if (_aje != null && _aje.Valid)
                _aje.SetPropRPM(0f);
            RebuildVisualMeshes(_visualPitchDelta, cowlFlapPercent * 0.01f, false);
            SetRendererEnabled(_fBladesRenderer, true);
            SetRendererEnabled(_rBladesRenderer, isContraRotating);
            EnsureMaterials();
            if (_effects != null) _effects.PropStrike(hub, point, water, paved, bladeCount * (isContraRotating ? 2 : 1));
            if (_audio != null) _audio.PropStrike(water);
            Debug.Log(string.Format("[ROPlanesPlus] PROP STRIKE ({0}) at {1:F0} prop rpm, {2:F0} m/s: blades rebuilt bent (seed {3}, {4} vertices), damaged-blade texture {5}, strike sound {6}",
                water ? "water" : (paved ? "runway" : "ground"), rpmAtStrike, vessel != null ? vessel.srfSpeed : 0.0, propDamageSeed,
                _fBladesMesh != null ? _fBladesMesh.vertexCount : -1,
                _damagedBladeMat != null && _damagedBladeMat.mainTexture != null ? _damagedBladeMat.mainTexture.name : "MISSING",
                _audio != null ? _audio.StrikeClipName(water) : "no audio"));
            ScreenMessages.PostScreenMessage(water
                ? "PROP STRIKE! The propeller hit the water and is wrecked"
                : "PROP STRIKE! The propeller hit the ground and is wrecked", 5f, ScreenMessageStyle.UPPER_CENTER);
            UpdateActionVisibility();
        }

        private PropellerLiveState FallbackLiveState(bool running, float dt)
        {
            PropellerLiveState s = _live;
            float throttle = running ? _eng.currentThrottle : 0f;
            bool engineUp = running && (_seq == null || _seq.Phase == EnginePhase.Running);
            if (propDamaged)
            {
                s.propRPM = 0f;
            }
            else if (_seq != null && _seq.Starting)
            {
                s.propRPM = _seq.SeqPropRPM;
            }
            else if (engineUp)
            {
                float idle = _seq != null ? _seq.IdlePropRPM : _metrics.minPropRPM * 0.55f;
                float target = isFeathered ? 0f : Mathf.Lerp(idle, _metrics.maxPropRPM, throttle);
                s.propRPM = Mathf.Lerp(s.propRPM, target, 1f - Mathf.Exp(-1.8f * dt));
            }
            else
            {
                float windmill = !isFeathered && vessel != null ? Mathf.Min(_metrics.minPropRPM * 0.5f, (float)vessel.srfSpeed * 4f) : 0f;
                float decel = _seq != null ? _seq.OffDecel(s.propRPM) : 45f + 0.35f * s.propRPM;
                if (s.propRPM > windmill)
                    s.propRPM = Mathf.Max(windmill, s.propRPM - decel * dt);
                else
                    s.propRPM = Mathf.Lerp(s.propRPM, windmill, 1f - Mathf.Exp(-0.5f * dt));
            }
            s.bladePitchDeg = isFeathered ? 86f : (isReversed ? -15f : 18f + 22f * throttle);
            s.shaftHP = engineUp ? _metrics.shaftPowerHP * Mathf.Max(0.08f, throttle) : 0f;
            s.manifoldInHg = engineUp ? Mathf.Lerp(18f, 50f, throttle) : 0f;
            s.hasData = false;
            return s;
        }

        private void FlightUpdate(float dt)
        {
            bool running = EngineRunning();
            bool starting = _seq != null && _seq.Starting;
            bool engineUp = running && (_seq == null || _seq.Phase == EnginePhase.Running);
            // Combustion you can see: running, or already firing while the engine catches / lights off
            bool firing = engineUp || (running && _seq != null && _seq.Phase == EnginePhase.Catching && _seq.Firing > 0.35f);
            float powerFrac = engineUp && _metrics.shaftPowerHP > 1f ? Mathf.Clamp01(_live.shaftHP / _metrics.shaftPowerHP) : 0f;
            if (starting)
                powerFrac = 0.1f * _seq.Firing;

            // --- Start-up / shut-down / flameout events ---
            if (_seq != null)
            {
                int ev = _seq.TakeEvents();
                if (ev != 0)
                    OnSequenceEvents(ev);
            }
            bool flameout = _eng != null && _eng.flameout;
            if (flameout && !_wasFlameout)
            {
                if (_effects != null) _effects.Backfire();
                if (_audio != null) _audio.Backfire();
            }
            _wasFlameout = flameout;

            // --- Propeller spin and blur disc ---
            float targetRPM;
            if (starting)
            {
                targetRPM = _seq.SeqPropRPM;
            }
            else
            {
                targetRPM = isFeathered ? 0f : Mathf.Max(0f, _live.propRPM);
                // A turboprop at ground idle keeps turning in ground-fine pitch (AJE's propeller just coasts)
                if (engineUp && _seq != null && IsTurboprop && !isFeathered && _eng.currentThrottle <= 0f)
                    targetRPM = Mathf.Max(targetRPM, _seq.IdlePropRPM);
            }
            if (propDamaged)
                targetRPM = 0f;
            _visualRPM = propDamaged ? 0f : Mathf.Lerp(_visualRPM, targetRPM, 1f - Mathf.Exp(-8f * dt));
            float degPerSec = _visualRPM * 6f;
            // Turning slowly (starter, last revolutions) a piston engine jerks on every compression stroke
            if (!IsTurboprop && _seq != null && _visualRPM > 0.5f)
            {
                float slow = 1f - Mathf.Clamp01(_visualRPM / (_seq.CrankPropRPM * 3f));
                if (slow > 0f)
                {
                    float strokesPerPropRev = _seq.Cylinders * 0.5f / Mathf.Max(0.05f, _seq.GearRatio);
                    _compPhase = Mathf.Repeat(_compPhase + degPerSec * dt / 360f * strokesPerPropRev, 1f);
                    degPerSec *= 1f + 0.55f * slow * Mathf.Sin(_compPhase * 2f * Mathf.PI);
                }
            }
            float spin = SpinSign;
            _frontAngle = Mathf.Repeat(_frontAngle + spin * degPerSec * dt, 360f);
            _rearAngle = Mathf.Repeat(_rearAngle - spin * degPerSec * dt, 360f);
            if (_frontHubTr != null)
                _frontHubTr.localRotation = Quaternion.Euler(0f, _frontAngle, 0f);
            if (_rearHubTr != null && isContraRotating)
                _rearHubTr.localRotation = Quaternion.Euler(0f, _rearAngle, 0f);

            float blurT = Mathf.Clamp01((_visualRPM - BlurStartRPM) / (BlurFullRPM - BlurStartRPM));
            float discAlpha = blurT * blurT * (3f - 2f * blurT);
            bool bladesVisible = blurT < 0.6f;
            SetRendererEnabled(_fBladesRenderer, bladesVisible);
            SetRendererEnabled(_rBladesRenderer, bladesVisible && isContraRotating);
            UpdateDisc(_frontDiscTr, _fDiscRenderer, _fDiscMat, discAlpha, -_frontAngle, true, dt);
            UpdateDisc(_rearDiscTr, _rDiscRenderer, _rDiscMat, isContraRotating ? discAlpha : 0f, -_rearAngle, false, dt);

            // --- Collective pitch (only rebuilt while blades are visible) ---
            float targetDelta = isFeathered ? 65f : (isReversed ? -36f : _live.bladePitchDeg - BladePitchRef);
            if (!_live.hasData && !running && !isFeathered)
                targetDelta = 0f;
            _visualPitchDelta = Mathf.MoveTowards(_visualPitchDelta, Mathf.Clamp(targetDelta, -40f, 70f), 45f * dt);

            // --- Automatic cowl / radiator flaps (piston engines) ---
            float flapTarget = 0.10f;
            if (!IsTurboprop && engineUp)
            {
                float slow = 1f - Mathf.Clamp01(vessel != null ? (float)vessel.srfSpeed / 90f : 1f);
                flapTarget = Mathf.Clamp01(0.15f + 0.45f * powerFrac * slow + 0.25f * slow + (wepEngaged ? 0.35f : 0f));
            }
            cowlFlapPercent = Mathf.MoveTowards(cowlFlapPercent, flapTarget * 100f, 12f * dt);

            if (Mathf.Abs(cowlFlapPercent * 0.01f - _builtFlap) > 0.04f)
            {
                // Only the flap mesh moves: cheap enough to animate in small steps
                PropellerMeshGenerator.BuildFlapsOnly(this, _flapMesh, cowlFlapPercent * 0.01f);
                _builtFlap = cowlFlapPercent * 0.01f;
            }
            if (bladesVisible && !propDamaged && Mathf.Abs(_visualPitchDelta - _builtPitchDelta) > 1.5f)
            {
                PropellerMeshGenerator.BuildBladesOnly(this, _fBladesMesh, _rBladesMesh, _visualPitchDelta);
                _builtPitchDelta = _visualPitchDelta;
            }

            // --- Exhaust glow and smoke ---
            float glowTarget = firing ? (IsTurboprop ? 0.25f + 0.35f * powerFrac : 0.30f + 0.70f * powerFrac) : 0f;
            _exhaustGlow = Mathf.MoveTowards(_exhaustGlow, glowTarget, (firing ? 0.5f : 0.08f) * dt);
            if (_exhaustMat != null)
            {
                float g = _exhaustGlow * (wepEngaged ? 1.2f : 1f);
                _exhaustMat.SetColor("_EmissiveColor", new Color(g * 1.0f, g * 0.42f, g * 0.12f, 1f));
            }

            float pressure = vessel != null ? Mathf.Clamp01((float)(vessel.staticPressurekPa / 101.325)) : 1f;
            if (_effects != null)
            {
                bool packed = vessel == null || vessel.packed;
                float airspeed = vessel != null ? (float)vessel.srfSpeed : 0f;
                _effects.Tick(dt, firing, packed, powerFrac, wepEngaged && engineUp, airspeed, pressure);
            }

            // --- Audio ---
            if (_audio != null && _seq != null)
            {
                _audio.Tick(dt, BuildSoundInput(engineUp, powerFrac, pressure));
                if (_audio.TakePops() > 0 && _effects != null)
                    _effects.Pop();
            }
        }

        private float _windOwnerCheck;
        private bool _windOwner;

        /// <summary>The airflow sound belongs to the aircraft, not each engine: the first propeller part of the active vessel plays it.</summary>
        private bool IsWindOwner()
        {
            _windOwnerCheck -= Time.deltaTime;
            if (_windOwnerCheck > 0f)
                return _windOwner;
            _windOwnerCheck = 1f;
            _windOwner = false;
            if (vessel == null || vessel != FlightGlobals.ActiveVessel || vessel.parts == null)
                return false;
            for (int i = 0; i < vessel.parts.Count; i++)
            {
                Part p = vessel.parts[i];
                if (p != null && p.FindModuleImplementing<ModuleProceduralPropeller>() != null)
                {
                    _windOwner = p == part;
                    break;
                }
            }
            return _windOwner;
        }

        private void OnSequenceEvents(int ev)
        {
            if (propDamaged)
                ev &= ~(EngineStartSequence.EvShutdown | EngineStartSequence.EvPropStopped); // the strike already said it all
            if (ev == 0)
                return;
            if (_audio != null)
                _audio.OnSequenceEvents(ev);
            if (_effects == null)
                return;
            if ((ev & EngineStartSequence.EvCough) != 0) _effects.Cough();
            if ((ev & EngineStartSequence.EvCatch) != 0) _effects.StartBurst();
            if ((ev & EngineStartSequence.EvLightOff) != 0) _effects.LightOff();
            if ((ev & EngineStartSequence.EvMisfire) != 0) _effects.Pop();
        }

        /// <summary>Everything the engine sound depends on, from the live state.</summary>
        private EngineSoundInput BuildSoundInput(bool engineUp, float powerFrac, float pressure)
        {
            EngineSoundInput si = new EngineSoundInput();
            si.phase = _seq.Phase;
            si.propRPM = _visualRPM;
            si.engineRPM = IsTurboprop ? 0f : _visualRPM / Mathf.Max(0.05f, _seq.GearRatio);
            si.coreN = _seq.CoreN;
            si.firing = _seq.Firing;
            si.starter = _seq.Starter;
            si.starterEngaged = _seq.StarterEngaged;
            si.igniters = _seq.Igniters;
            si.load = powerFrac;
            si.roughness = _seq.Roughness;
            si.pressure = pressure;
            si.feathered = isFeathered;
            si.reversed = isReversed;
            si.wep = wepEngaged && engineUp;

            float speed = vessel != null ? (float)vessel.srfSpeed : 0f;
            float sound = vessel != null && vessel.speedOfSound > 1.0 ? (float)vessel.speedOfSound : 340f;
            si.windSpeed = IsWindOwner() ? speed : 0f;
            float tip = Mathf.PI * propDiameter * _visualRPM / 60f;
            si.tipMach = Mathf.Sqrt(tip * tip + speed * speed) / sound;

            si.boostPitch = 1f;
            if (!IsTurboprop && engineUp && aspirationIndex != (int)AspirationType.NaturallyAspirated)
            {
                // The blower works harder the higher the manifold pressure is above ambient
                float ambient = Mathf.Max(1f, pressure * 29.92f);
                float map = _live.hasData ? _live.manifoldInHg : Mathf.Lerp(ambient * 0.6f, ambient * 1.6f, powerFrac);
                si.boost = Mathf.Clamp01((map / ambient - 0.8f) / 1.4f);
                bool turbo = aspirationIndex == (int)AspirationType.Turbosupercharged ||
                             aspirationIndex == (int)AspirationType.TurboCompound;
                if (turbo)
                    si.boostPitch = Mathf.Clamp(0.55f + 0.5f * powerFrac + 0.35f * (1f - pressure), 0.4f, 1.4f);
                else if (_live.boostMode > 0)
                    si.boostPitch = 1.24f; // high blower gear / second stage
            }
            return si;
        }

        private void UpdateDisc(Transform tr, Renderer r, Material mat, float alpha, float counterAngle, bool front, float dt)
        {
            if (tr == null)
                return;
            bool show = alpha > 0.01f;
            tr.localScale = show ? Vector3.one : new Vector3(0.0001f, 0.0001f, 0.0001f);
            SetRendererEnabled(r, show);
            if (!show)
                return;
            _discSlowAngle = Mathf.Repeat(_discSlowAngle + 50f * dt, 360f);
            float slow = (front ? _discSlowAngle : -_discSlowAngle) * SpinSign;
            tr.localRotation = Quaternion.Euler(0f, counterAngle + slow, 0f);
            if (mat != null)
            {
                if (mat.HasProperty("_Color"))
                {
                    Color c = mat.GetColor("_Color");
                    c.a = alpha;
                    mat.SetColor("_Color", c);
                }
                if (mat.HasProperty("_TintColor"))
                {
                    Color c = mat.GetColor("_TintColor");
                    c.a = alpha * 0.5f;
                    mat.SetColor("_TintColor", c);
                }
                if (mat.HasProperty("_Opacity"))
                    mat.SetFloat("_Opacity", alpha);
            }
        }

        private static void SetRendererEnabled(Renderer r, bool enabled)
        {
            if (r != null && r.enabled != enabled)
                r.enabled = enabled;
        }

        private void UpdateFlightTelemetry(bool running, bool wepActive)
        {
            if (propDamaged)
            {
                powerDisplay = "Propeller broken";
            }
            else if (running && _seq != null && _seq.Starting)
            {
                if (IsTurboprop)
                    powerDisplay = string.Format("Starting · {0:F0} % rpm", _seq.CoreN * 100f);
                else
                    powerDisplay = _seq.Phase == EnginePhase.Cranking ? "Starting · cranking" : "Starting · catching";
            }
            else if (!running && _live.propRPM < 5f)
            {
                powerDisplay = isFeathered ? "Shut down (feathered)" : "Shut down";
            }
            else if (running && _eng.currentThrottle <= 0f)
            {
                powerDisplay = "Idle";
            }
            else
            {
                string tag = wepActive ? "  WEP" : (isReversed ? "  REV" : "");
                powerDisplay = string.Format("{0:N0} hp{1}", _live.shaftHP, tag);
            }

            string mp = (!IsTurboprop && _live.manifoldInHg > 1f) ? string.Format(" · {0:F0} inHg", _live.manifoldInHg) : "";
            propDisplay = string.Format("{0:N0} rpm · {1:F0}°{2}", _live.propRPM,
                isFeathered ? 86f : _live.bladePitchDeg, mp);

            if (wepEngaged || wepRemainingSec < 299f)
            {
                BaseEvent wep = Events["ToggleWEPEvent"];
                if (wep != null)
                    wep.guiName = string.Format("{0} WEP ({1:F0} s)", wepEngaged ? "Stop" : "Engage", wepRemainingSec);
            }
        }

        // ==================== PAW events & actions ====================

        // The visible button lives in ModuleEngineWorkshopButton (first module, top of the menu);
        // this event stays hidden so older action-group/craft references still resolve.
        [KSPEvent(guiActiveEditor = false, guiActive = false, guiName = "Engine Workshop")]
        public void ToggleStudioWindowEvent()
        {
            EngineWorkshopWindow.Toggle(this);
        }

        [KSPEvent(guiActiveEditor = false, guiActive = true, guiName = "Engage WEP")]
        public void ToggleWEPEvent()
        {
            if (_metrics.wepMultiplier <= 1.001f)
                return;
            wepEngaged = !wepEngaged;
            if (wepEngaged)
                isFeathered = false;
            UpdateFlightButtonLabels();
        }

        /// <summary>
        /// Test button (only with a ROPLANESPLUS_DEBUG { } node in GameData): strikes the propeller on
        /// demand, as if it had hit the ground, so the strike can be checked without crashing.
        /// </summary>
        [KSPEvent(guiActive = false, guiActiveEditor = false, guiName = "Debug: Prop Strike")]
        public void DebugPropStrikeEvent()
        {
            if (propDamaged || _frontHubTr == null)
                return;
            Vector3 hub = _frontHubTr.position;
            Vector3 down = Vector3.down;
            if (vessel != null && vessel.mainBody != null)
                down = ((Vector3)vessel.mainBody.position - hub).normalized;
            ApplyPropStrike(hub, hub + down * 0.5f * propDiameter, false, false);
        }

        private static int _debugTools = -1;
        private static bool DebugTools
        {
            get
            {
                if (_debugTools < 0 && GameDatabase.Instance != null)
                    _debugTools = GameDatabase.Instance.GetConfigNodes("ROPLANESPLUS_DEBUG").Length > 0 ? 1 : 0;
                return _debugTools == 1;
            }
        }

        /// <summary>Field repair: an engineer on EVA fits a new propeller to an aircraft on the ground.</summary>
        [KSPEvent(guiActive = false, guiActiveEditor = false, guiActiveUnfocused = false, externalToEVAOnly = true,
            unfocusedRange = 5f, guiName = "Replace Wrecked Propeller")]
        public void ReplacePropellerEvent()
        {
            if (!propDamaged)
                return;
            Vessel kerbal = FlightGlobals.ActiveVessel;
            if (kerbal == null || !kerbal.isEVA)
                return;
            List<ProtoCrewMember> crew = kerbal.GetVesselCrew();
            ProtoCrewMember k = crew != null && crew.Count > 0 ? crew[0] : null;
            if (k == null || k.experienceTrait == null || k.experienceTrait.TypeName != "Engineer")
            {
                ScreenMessages.PostScreenMessage("Only an engineer can replace a propeller", 4f, ScreenMessageStyle.UPPER_CENTER);
                return;
            }
            if (vessel == null || !vessel.LandedOrSplashed)
            {
                ScreenMessages.PostScreenMessage("The aircraft must be on the ground (or on the water) to change the propeller", 4f, ScreenMessageStyle.UPPER_CENTER);
                return;
            }
            propDamaged = false;
            propDamageSeed = 0;
            RebuildVisualMeshes(0f, cowlFlapPercent * 0.01f, false);
            EnsureMaterials();
            UpdateActionVisibility();
            ScreenMessages.PostScreenMessage(k.name + " fitted a new propeller", 4f, ScreenMessageStyle.UPPER_CENTER);
        }

        [KSPAction("Toggle WEP")]
        public void ToggleWEPAction(KSPActionParam param)
        {
            ToggleWEPEvent();
        }

        [KSPEvent(guiActiveEditor = false, guiActive = true, guiName = "Feather Propeller")]
        public void ToggleFeatherEvent()
        {
            isFeathered = !isFeathered;
            if (isFeathered)
            {
                wepEngaged = false;
                isReversed = false;
            }
            UpdateThrustTransformDirection();
            UpdateFlightButtonLabels();
        }

        [KSPAction("Toggle Feather")]
        public void ToggleFeatherAction(KSPActionParam param)
        {
            ToggleFeatherEvent();
        }

        [KSPEvent(guiActiveEditor = false, guiActive = true, guiName = "Reverse Pitch")]
        public void ToggleReverseEvent()
        {
            if (!IsTurboprop)
                return;
            isReversed = !isReversed;
            if (isReversed)
            {
                isFeathered = false;
                wepEngaged = false;
            }
            UpdateThrustTransformDirection();
            UpdateFlightButtonLabels();
        }

        [KSPAction("Toggle Reverse Pitch")]
        public void ToggleReverseAction(KSPActionParam param)
        {
            ToggleReverseEvent();
        }

        private void UpdateActionVisibility()
        {
            bool hasWep = _metrics.wepMultiplier > 1.001f;
            BaseEvent e = Events["ToggleWEPEvent"];
            if (e != null) e.guiActive = hasWep;
            e = Events["ToggleReverseEvent"];
            if (e != null) e.guiActive = IsTurboprop;
            BaseAction a = Actions["ToggleWEPAction"];
            if (a != null) a.active = hasWep;
            a = Actions["ToggleReverseAction"];
            if (a != null) a.active = IsTurboprop;
            e = Events["ReplacePropellerEvent"];
            if (e != null) e.guiActiveUnfocused = propDamaged && HighLogic.LoadedSceneIsFlight;
            e = Events["DebugPropStrikeEvent"];
            if (e != null) e.guiActive = DebugTools && !propDamaged && HighLogic.LoadedSceneIsFlight;
            UpdateFlightButtonLabels();
        }

        private void UpdateFlightButtonLabels()
        {
            if (Events == null)
                return;
            BaseEvent wep = Events["ToggleWEPEvent"];
            if (wep != null)
                wep.guiName = wepEngaged ? "Stop WEP" : "Engage WEP";
            BaseEvent fth = Events["ToggleFeatherEvent"];
            if (fth != null)
                fth.guiName = isFeathered ? "Unfeather Propeller" : "Feather Propeller";
            BaseEvent rev = Events["ToggleReverseEvent"];
            if (rev != null)
                rev.guiName = isReversed ? "Normal Pitch" : "Reverse Pitch";
        }

        private void UpdateThrustTransformDirection()
        {
            if (_thrustTr == null)
                return;
            // KSP/AJE push along -thrustTransform.forward. Normal: forward = down (thrust +Y).
            Vector3 exhaustDir = isReversed ? Vector3.up : Vector3.down;
            _thrustTr.localRotation = Quaternion.LookRotation(exhaustDir, Vector3.back);
        }

        // ==================== Part menu & design snapshot ====================

        private void UpdateSpecDisplay()
        {
            float hp = _metrics.shaftPowerHP;
            string wet = _metrics.wepMultiplier > 1.001f ? string.Format(" ({0:N0} WEP)", hp * _metrics.wepMultiplier) : "";
            specDisplay = string.Format("{0:N0} {1}{2} | {3:N0} kg", hp, IsTurboprop ? "shp" : "hp", wet, _metrics.dryMassTons * 1000f);
            engineNameDisplay = DisplayName;
        }

        /// <summary>Preset name, or a short description for custom engines.</summary>
        public string DisplayName
        {
            get
            {
                PropellerPreset p = ActivePreset;
                if (p != null)
                    return p.displayName;
                return "Custom " + PropellerPresets.EngineTypeName(architectureIndex, subStyleIndex, TotalCylinders);
            }
        }

        /// <summary>Copies every design field into a node (used by the Workshop's Revert).</summary>
        public ConfigNode SaveDesign()
        {
            ConfigNode n = new ConfigNode("DESIGN");
            for (int i = 0; i < DesignFieldNames.Length; i++)
            {
                BaseField f = Fields[DesignFieldNames[i]];
                if (f != null)
                    n.AddValue(DesignFieldNames[i], f.GetStringValue(this, false));
            }
            return n;
        }

        public void LoadDesign(ConfigNode n)
        {
            if (n == null)
                return;
            for (int i = 0; i < DesignFieldNames.Length; i++)
            {
                BaseField f = Fields[DesignFieldNames[i]];
                string v = n.GetValue(DesignFieldNames[i]);
                if (f != null && v != null)
                    f.Read(v, this);
            }
            _lastPreset = selectedPreset;
            _lastArchIdx = architectureIndex;
            _lastEngineSig = EngineSignature();
            RebuildEverything(true);
        }

        /// <summary>Called by the Workshop after it changes engine-defining fields.</summary>
        public void MarkCustom()
        {
            selectedPreset = PropellerPresets.CustomId;
            _lastPreset = selectedPreset;
        }

        public static bool TurbopropAllowed
        {
            get { return PropellerPresets.IsTechAvailable(PropellerPresets.TurbopropTech); }
        }

        private void NormalizeLegacyValues()
        {
            PropellerPreset p = PropellerPresets.GetPreset(selectedPreset);
            if (p != null)
                selectedPreset = p.id;
            else
                selectedPreset = PropellerPresets.CustomId;

            architectureName = PropellerPresets.ArchitectureOptions[PropellerPresets.ParseArchitecture(architectureName)];
            subStyleName = PropellerPresets.SubStyleOptions[PropellerPresets.ParseSubStyle(subStyleName)];
            liveryName = PropellerPresets.LiveryOptions[PropellerPresets.ParseLivery(liveryName)];
            isTurboprop = IsTurboprop;
            if (!IsTurboprop)
                isReversed = false;
        }

        // ==================== Model binding & materials ====================

        private void BindModelHierarchy()
        {
            _frontHubTr = part.FindModelTransform("FrontPropHub");
            _rearHubTr = part.FindModelTransform("RearPropHub");
            _frontDiscTr = part.FindModelTransform("FrontRotorDisc");
            _rearDiscTr = part.FindModelTransform("RearRotorDisc");
            _thrustTr = part.FindModelTransform("thrustTransform");
            _exhaustLTr = part.FindModelTransform("exhaustPortL");
            _exhaustRTr = part.FindModelTransform("exhaustPortR");

            Renderer r;
            _cowlMesh = DuplicateMeshFilter("CowlingMesh", out r); AddBody(r);
            _coreMesh = DuplicateMeshFilter("EngineCoreDetailsMesh", out r); AddBody(r);
            _exhMesh = DuplicateMeshFilter("ExhaustAndRadiatorMesh", out _exhaustRenderer);
            _flapMesh = DuplicateMeshFilter("CowlFlapsMesh", out r); AddBody(r);
            _fSpinMesh = DuplicateMeshFilter("SpinnerMesh", out r); AddBody(r);
            _fBladesMesh = DuplicateMeshFilter("FrontBladesMesh", out _fBladesRenderer); AddBody(_fBladesRenderer);
            _fDiscMesh = DuplicateMeshFilter("FrontRotorDisc", out _fDiscRenderer);
            _rSpinMesh = DuplicateMeshFilter("RearSpinnerMesh", out r); AddBody(r);
            _rBladesMesh = DuplicateMeshFilter("RearBladesMesh", out _rBladesRenderer); AddBody(_rBladesRenderer);
            _rDiscMesh = DuplicateMeshFilter("RearRotorDisc", out _rDiscRenderer);

            _cowlCollider = BindCollider("cowlingCollider", out _cowlColMesh);
            _spinCollider = BindCollider("spinnerCollider", out _spinColMesh);
        }

        private void AddBody(Renderer r)
        {
            if (r != null)
                _bodyRenderers.Add(r);
        }

        private MeshCollider BindCollider(string name, out Mesh mesh)
        {
            mesh = null;
            Transform tr = part.FindModelTransform(name);
            if (tr == null)
                return null;
            MeshCollider mc = tr.GetComponent<MeshCollider>();
            if (mc == null)
                mc = tr.gameObject.AddComponent<MeshCollider>();
            mesh = new Mesh();
            mesh.name = "ROPP_" + name;
            _ownedObjects.Add(mesh);
            return mc;
        }

        private Mesh DuplicateMeshFilter(string transformName, out Renderer outRenderer)
        {
            outRenderer = null;
            Transform tr = part.FindModelTransform(transformName);
            if (tr == null)
                return null;
            outRenderer = tr.GetComponent<Renderer>();
            MeshFilter mf = tr.GetComponent<MeshFilter>();
            if (mf == null)
                mf = tr.gameObject.AddComponent<MeshFilter>();
            // Created through MeshFilter.mesh so Unity treats it as this filter's own instance: other
            // mods that read MeshFilter.mesh (Firefly's vessel bounds, KSPCF drag cubes, Deferred)
            // then get this same mesh back instead of silently cloning it onto the filter, which
            // left every later rebuild (bent blades after a strike, blade pitch, cowl flaps) invisible.
            Mesh runtimeMesh = mf.mesh;
            runtimeMesh.Clear();
            runtimeMesh.name = "Runtime_" + transformName;
            runtimeMesh.MarkDynamic();
            _ownedObjects.Add(runtimeMesh);
            _ownedFilters.Add(mf);
            _ownedFilterMeshes.Add(runtimeMesh);
            return runtimeMesh;
        }

        private readonly List<MeshFilter> _ownedFilters = new List<MeshFilter>();
        private readonly List<Mesh> _ownedFilterMeshes = new List<Mesh>();
        private bool _meshSwapLogged;

        /// <summary>
        /// If another mod still replaced one of our filters' meshes with a copy, put ours back so
        /// the geometry we rebuild is the geometry on screen. Returns true if anything was fixed.
        /// </summary>
        private bool ReclaimMeshes()
        {
            bool fixedAny = false;
            for (int i = 0; i < _ownedFilters.Count; i++)
            {
                MeshFilter mf = _ownedFilters[i];
                Mesh ours = _ownedFilterMeshes[i];
                if (mf == null || ours == null || mf.sharedMesh == ours)
                    continue;
                if (!_meshSwapLogged)
                {
                    _meshSwapLogged = true;
                    Debug.Log("[ROPlanesPlus] another mod replaced the engine mesh on " + mf.name + " (" +
                        (mf.sharedMesh != null ? mf.sharedMesh.name : "null") + "); putting the live mesh back");
                }
                mf.sharedMesh = ours;
                fixedAny = true;
            }
            return fixedAny;
        }

        private void SetupMaterials()
        {
            Material baseMat = null;
            for (int i = 0; i < _bodyRenderers.Count && baseMat == null; i++)
                baseMat = _bodyRenderers[i].sharedMaterial;
            if (baseMat != null)
            {
                _prefabBodyMat = baseMat;
                // One instance for the painted body; a separate one for the exhausts so the heat
                // glow only lights the stubs, never the whole cowling.
                _bodyMat = NewOwnedMaterial(baseMat);
                for (int i = 0; i < _bodyRenderers.Count; i++)
                    _bodyRenderers[i].sharedMaterial = _bodyMat;
                if (_exhaustRenderer != null)
                {
                    _exhaustMat = NewOwnedMaterial(baseMat);
                    _exhaustMat.SetColor("_EmissiveColor", Color.black);
                    _exhaustRenderer.sharedMaterial = _exhaustMat;
                }
            }
            if (_fDiscRenderer != null)
                _prefabDiscMat = _fDiscRenderer.sharedMaterial;
            _fDiscMat = CloneDiscMaterial(_fDiscRenderer);
            _rDiscMat = CloneDiscMaterial(_rDiscRenderer);
            RefreshHighlighter();
        }

        private Material NewOwnedMaterial(Material source)
        {
            Material m = new Material(source);
            _ownedObjects.Add(m);
            _ourMaterials.Add(m);
            return m;
        }

        /// <summary>
        /// Other mods (shader converters, effects, highlight systems) can swap a renderer's material
        /// after we set ours, which silently disconnected the livery. Every 0.3 s each renderer is
        /// checked: if it went back to the original shared material we re-assign ours; if another
        /// mod gave it a private copy we clone that copy (keeping its shader) and paint the clone.
        /// Shared materials are never painted, so other engines are never affected.
        /// </summary>
        private void EnsureMaterials()
        {
            bool changed = ReclaimMeshes();
            for (int i = 0; i < _bodyRenderers.Count; i++)
            {
                Renderer r = _bodyRenderers[i];
                if (propDamaged && r != null && (r == _fBladesRenderer || r == _rBladesRenderer))
                    changed |= EnforceDamagedBlade(r);
                else
                    changed |= Enforce(r, ref _bodyMat, _prefabBodyMat, true);
            }
            changed |= Enforce(_exhaustRenderer, ref _exhaustMat, _prefabBodyMat, true);
            changed |= Enforce(_fDiscRenderer, ref _fDiscMat, _prefabDiscMat, false);
            changed |= Enforce(_rDiscRenderer, ref _rDiscMat, _prefabDiscMat, false);
            if (changed)
                RefreshHighlighter();
        }

        private const string DamagedBladeTexPath = "ROPlanesPlus/Parts/PropShared/ropp_blades_damaged";
        private Material _damagedBladeMat;

        /// <summary>Struck blades: scraped to bare metal, gouged and smeared with dirt (ropp_blades_damaged).</summary>
        private bool EnforceDamagedBlade(Renderer r)
        {
            if (_bodyMat == null)
                return false;
            if (_damagedBladeMat == null)
            {
                _damagedBladeMat = NewOwnedMaterial(_bodyMat);
                Texture2D tex = GameDatabase.Instance != null ? GameDatabase.Instance.GetTexture(DamagedBladeTexPath, false) : null;
                if (tex != null)
                    _damagedBladeMat.mainTexture = tex;
            }
            if (r.sharedMaterial == _damagedBladeMat)
                return false;
            r.sharedMaterial = _damagedBladeMat;
            return true;
        }

        private bool Enforce(Renderer r, ref Material ours, Material prefab, bool applyLivery)
        {
            if (r == null || ours == null)
                return false;
            bool changed = false;
            Material cur = r.sharedMaterial;
            if (cur != ours)
            {
                if (cur == null || cur == prefab || _ourMaterials.Contains(cur))
                {
                    r.sharedMaterial = ours;
                }
                else if (_adoptCount < 16)
                {
                    _adoptCount++;
                    if (!_adoptLogged)
                    {
                        _adoptLogged = true;
                        Debug.Log("[ROPlanesPlus] another mod replaced the engine material (shader " +
                            (cur.shader != null ? cur.shader.name : "?") + "); adopting a private copy so the livery still applies");
                    }
                    ours = NewOwnedMaterial(cur);
                    r.sharedMaterial = ours;
                }
                else
                {
                    ours = cur; // something keeps replacing it: paint whatever is there
                }
                changed = true;
            }
            if (applyLivery && _liveryTex != null && ours.mainTexture != _liveryTex)
            {
                ours.mainTexture = _liveryTex;
                changed = true;
            }
            return changed;
        }

        private void RefreshHighlighter()
        {
            try
            {
                const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance |
                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
                System.Reflection.MethodInfo refresh = typeof(Part).GetMethod("RefreshHighlighter", flags, null, Type.EmptyTypes, null);
                if (refresh != null)
                    refresh.Invoke(part, null);
                System.Reflection.PropertyInfo hlProp = typeof(Part).GetProperty("highlighter", flags);
                object hl = hlProp != null ? hlProp.GetValue(part, null) : null;
                if (hl != null)
                {
                    System.Reflection.MethodInfo reinit = hl.GetType().GetMethod("ReinitMaterials", flags, null, Type.EmptyTypes, null);
                    if (reinit != null)
                        reinit.Invoke(hl, null);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[ROPlanesPlus] highlighter refresh failed: " + ex.Message);
            }
        }

        private Material CloneDiscMaterial(Renderer r)
        {
            if (r == null || r.sharedMaterial == null)
                return null;
            Material m = NewOwnedMaterial(r.sharedMaterial);
            r.sharedMaterial = m;
            return m;
        }

        private string LiveryKey
        {
            get { return liveryName + "|" + paintCowl + paintNose + paintSpinner + paintFinish; }
        }

        private void ApplyLivery(bool force)
        {
            string key = LiveryKey;
            if (!force && string.Equals(key, _lastLiveryApplied, StringComparison.Ordinal))
                return;
            _lastLiveryApplied = key;
            if (GameDatabase.Instance == null)
                return;
            int idx = PropellerPresets.ParseLivery(liveryName);
            Texture2D tex;
            if (idx == PropellerPresets.CustomLiveryIndex)
            {
                tex = CustomPaint.GetTexture(
                    CustomPaint.ParseColor(paintCowl, PropellerPresets.PaintColors[6]),
                    CustomPaint.ParseColor(paintNose, PropellerPresets.PaintColors[0]),
                    CustomPaint.ParseColor(paintSpinner, PropellerPresets.PaintColors[0]),
                    paintFinish);
                if (tex == null)
                    tex = GameDatabase.Instance.GetTexture(LiveryPath + PropellerPresets.LiveryKeys[0], false);
            }
            else
            {
                tex = GameDatabase.Instance.GetTexture(LiveryPath + PropellerPresets.LiveryKeys[idx], false);
            }
            if (tex == null)
            {
                Debug.LogWarning("[ROPlanesPlus] livery texture not found for " + liveryName);
                return;
            }
            _liveryTex = tex;
            if (_bodyMat != null) _bodyMat.mainTexture = tex;
            if (_exhaustMat != null) _exhaustMat.mainTexture = tex;
            EnsureMaterials();
            RefreshHighlighter();
        }

        private void UpdateAttachNodes(float aftNodeY, float fwdNodeY)
        {
            if (part.attachNodes == null)
                return;
            int nodeSize = Mathf.Clamp(Mathf.RoundToInt(cowlDiameter), 1, 3);
            for (int i = 0; i < part.attachNodes.Count; i++)
            {
                AttachNode an = part.attachNodes[i];
                if (an == null) continue;
                if (string.Equals(an.id, "bottom", StringComparison.OrdinalIgnoreCase))
                {
                    an.position = new Vector3(0f, aftNodeY, 0f);
                    an.orientation = new Vector3(0f, -1f, 0f);
                    an.size = nodeSize;
                }
                else if (string.Equals(an.id, "top", StringComparison.OrdinalIgnoreCase))
                {
                    an.position = new Vector3(0f, fwdNodeY, 0f);
                    an.orientation = new Vector3(0f, 1f, 0f);
                    an.size = nodeSize;
                }
            }
            if (part.srfAttachNode != null)
            {
                part.srfAttachNode.position = new Vector3(0f, 0f, 0.5f * cowlDiameter);
                part.srfAttachNode.orientation = new Vector3(0f, 0f, -1f);
            }
        }

        private void SyncToSymmetryCounterparts()
        {
            for (int i = 0; i < part.symmetryCounterparts.Count; i++)
            {
                Part symPart = part.symmetryCounterparts[i];
                if (symPart == null) continue;
                ModuleProceduralPropeller sym = symPart.FindModuleImplementing<ModuleProceduralPropeller>();
                if (sym == null) continue;

                sym._isSyncing = true;
                try
                {
                    sym.selectedPreset = selectedPreset;
                    sym.liveryName = liveryName;
                    sym.architectureName = architectureName;
                    sym.subStyleName = subStyleName;
                    sym.isContraRotating = isContraRotating;
                    sym.isPusher = isPusher;
                    sym.cowlDiameter = cowlDiameter;
                    sym.cowlLength = cowlLength;
                    sym.propDiameter = propDiameter;
                    sym.bladeCountFloat = bladeCountFloat;
                    sym.bladePlanformName = bladePlanformName;
                    sym.spinnerStyleName = spinnerStyleName;
                    sym.nacelleName = nacelleName;
                    sym.shaftPowerHP = shaftPowerHP;
                    sym.aspirationName = aspirationName;
                    sym.criticalAltitudeKm = criticalAltitudeKm;
                    sym.maxEngineRPM = maxEngineRPM;
                    sym.autoCowl = autoCowl;
                    sym.propStrikes = propStrikes;
                    sym.autoFeather = autoFeather;
                    sym.paintCowl = paintCowl;
                    sym.paintNose = paintNose;
                    sym.paintSpinner = paintSpinner;
                    sym.paintFinish = paintFinish;
                    sym.cylindersPerRow = cylindersPerRow;
                    sym.cylinderLitres = cylinderLitres;
                    sym.cowlFit = cowlFit;
                    sym.boostInHg = boostInHg;
                    sym.propTorque = propTorque;
                    sym.handedPair = handedPair;
                    sym.propRotation = RotationFor(symPart);
                    sym._lastPreset = selectedPreset;
                    sym._lastArchIdx = architectureIndex;
                    sym._lastEngineSig = sym.EngineSignature();
                    sym.RebuildEverything(false);
                }
                finally
                {
                    sym._isSyncing = false;
                }
            }
        }

        /// <summary>
        /// Rotation a symmetry counterpart gets from this engine: the same, or with handed
        /// propellers the opposite on the other side. Sides come from the group's master engine (see
        /// EnforceHandedness), so editing any engine of the group gives the same split.
        /// </summary>
        private int RotationFor(Part other)
        {
            if (!handedPair)
                return propRotation;
            Part master = HandedMaster();
            int masterRotation = SameSideAsMaster(master, part) ? propRotation : 1 - propRotation;
            return SameSideAsMaster(master, other) ? masterRotation : 1 - masterRotation;
        }

        // Fields that define the engine itself: touching any of them turns the preset into "Custom".
        private string EngineSignature()
        {
            return string.Format("{0}|{1}|{2}|{3:F0}|{4:F2}|{5}|{6}|{7:F1}|{8:F0}|{9}|{10:F2}|{11:F1}",
                architectureIndex, subStyleIndex, isContraRotating, shaftPowerHP, propDiameter,
                bladeCount, aspirationIndex, criticalAltitudeKm, maxEngineRPM, cylindersPerRow, cylinderLitres, boostInHg);
        }

        private string FullSignature()
        {
            return string.Format("{0}|{1}|{2}|{3}|{4}|{5:F2}|{6:F2}|{7}|{8}",
                EngineSignature(), selectedPreset, bladePlanformName, spinnerStyleName, nacelleName,
                cowlDiameter, cowlLength, isPusher, LiveryKey + autoCowl + propStrikes + autoFeather + cowlFit + propTorque + propRotation + handedPair);
        }

        private static int MatchOptionIndex(string[] options, string current, int fallback)
        {
            if (options == null || string.IsNullOrEmpty(current))
                return fallback;
            for (int i = 0; i < options.Length; i++)
            {
                if (string.Equals(options[i], current, StringComparison.OrdinalIgnoreCase))
                    return i;
            }
            return fallback;
        }

        // ==================== KSP modifier interfaces ====================

        public float GetModuleMass(float defaultMass, ModifierStagingSituation sit)
        {
            float target = _metrics.dryMassTons > 0.01f ? _metrics.dryMassTons : defaultMass;
            return target - defaultMass;
        }

        public ModifierChangeWhen GetModuleMassChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }

        public float GetModuleCost(float defaultCost, ModifierStagingSituation sit)
        {
            float target = _metrics.partCostFunds > 1f ? _metrics.partCostFunds : defaultCost;
            return target - defaultCost;
        }

        public ModifierChangeWhen GetModuleCostChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }

        public Vector3 GetModuleSize(Vector3 defaultSize, ModifierStagingSituation sit)
        {
            return new Vector3(cowlDiameter, cowlLength, cowlDiameter) - defaultSize;
        }

        public ModifierChangeWhen GetModuleSizeChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }
    }
}
