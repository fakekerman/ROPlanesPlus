using System;
using System.Collections;
using System.Collections.Generic;
using KSP.UI.Screens;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>
    /// Procedural drop pylon / launch rack for air launches (B-29 + X-1, NB-52 + X-15, carrier + parasite
    /// fighter) and launch stands. Unlike a stock radial decoupler, which leaves itself on the part attached
    /// to it, the pylon stays on the part it is MOUNTED to (the part it was placed on in the editor) and
    /// releases everything on its hook face.
    ///
    /// Part space: +Y forward, +Z down towards the released aircraft. The mount face (surface attach point
    /// and the "mount" stack node) is at z = 0, the hook face (the "release" stack node) at z = height.
    /// Release side = anything on the release node, or surface-attached to the pylon nearer the hook face
    /// than the mount face. If the pylon itself hangs from the release node of its parent (aircraft built
    /// as the root), the pylon separates from that parent instead, so it again stays with the carrier.
    /// </summary>
    public class ModuleROPPLaunchPylon : ModuleDecouple, IStageSeparatorChild, IPartMassModifier, IPartCostModifier, IPartSizeModifier
    {
        public const string MountNodeId = "mount";
        public const string ReleaseNodeId = "release";
        public static readonly string[] ProfileOptions = { "Aerofoil", "Rounded", "Box" };
        private const string Group = "roppPylon";

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Length", guiUnits = " m", guiFormat = "F2",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatEdit(scene = UI_Scene.Editor, minValue = 0.3f, maxValue = 15f, incrementLarge = 1f, incrementSmall = 0.1f,
            incrementSlide = 0.01f, unit = " m", sigFigs = 2)]
        public float pylonLength = 2.4f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Height", guiUnits = " m", guiFormat = "F2",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatEdit(scene = UI_Scene.Editor, minValue = 0.05f, maxValue = 4f, incrementLarge = 0.5f, incrementSmall = 0.05f,
            incrementSlide = 0.005f, unit = " m", sigFigs = 3)]
        public float pylonHeight = 0.55f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Thickness", guiUnits = " m", guiFormat = "F2",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatEdit(scene = UI_Scene.Editor, minValue = 0.05f, maxValue = 3f, incrementLarge = 0.5f, incrementSmall = 0.05f,
            incrementSlide = 0.005f, unit = " m", sigFigs = 3)]
        public float pylonWidth = 0.3f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Hook face length", guiUnits = "%", guiFormat = "F0",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatRange(scene = UI_Scene.Editor, minValue = 20f, maxValue = 150f, stepIncrement = 1f)]
        public float bottomLengthPct = 75f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Hook face thickness", guiUnits = "%", guiFormat = "F0",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatRange(scene = UI_Scene.Editor, minValue = 40f, maxValue = 150f, stepIncrement = 1f)]
        public float bottomWidthPct = 100f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Rake (hook face aft)", guiUnits = "%", guiFormat = "F0",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_FloatRange(scene = UI_Scene.Editor, minValue = -50f, maxValue = 50f, stepIncrement = 1f)]
        public float sweepPct = 12f;

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Cross-section",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_ChooseOption(scene = UI_Scene.Editor, options = new[] { "Aerofoil", "Rounded", "Box" })]
        public string profileName = "Aerofoil";

        [KSPField(isPersistant = true, guiActiveEditor = true, guiName = "Hooks & sway braces",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        [UI_Toggle(scene = UI_Scene.Editor, enabledText = "Shown", disabledText = "Hidden")]
        public bool showHooks = true;

        [KSPField(guiActiveEditor = true, guiName = "Pylon mass",
            groupName = Group, groupDisplayName = "Launch Pylon Shape", groupStartCollapsed = false)]
        public string massDisplay = string.Empty;

        [KSPField] public string bodyTransformName = "pylonBody";
        [KSPField] public string hooksTransformName = "pylonHooks";
        [KSPField] public string colliderTransformName = "pylonCollider";
        // Structure mass per m^3 of enclosed pylon volume (semi-monocoque aluminium + fittings), t/m^3
        [KSPField] public float massPerVolume = 0.20f;
        [KSPField] public float baseMass = 0.008f;
        [KSPField] public float hookMass = 0.004f;
        [KSPField] public float baseCost = 3f;
        [KSPField] public float costPerTon = 60f;

        private Mesh _bodyMesh, _hooksMesh, _colMesh;
        private MeshFilter _bodyFilter, _hooksFilter;
        private MeshCollider _collider;
        private readonly RuntimeMeshBuffer _buf = new RuntimeMeshBuffer();
        private string _lastSig;
        private float _checkTimer;
        private float _massTons = -1f;
        private Vector3 _releasePoint;
        private bool _built;

        public PylonShape Shape
        {
            get
            {
                PylonShape s;
                s.length = pylonLength;
                s.height = pylonHeight;
                s.width = pylonWidth;
                s.bottomLengthFrac = bottomLengthPct * 0.01f;
                s.bottomWidthFrac = bottomWidthPct * 0.01f;
                s.sweepFrac = sweepPct * 0.01f;
                s.profile = ProfileIndex;
                s.hooks = showHooks;
                return s;
            }
        }

        private int ProfileIndex
        {
            get
            {
                for (int i = 0; i < ProfileOptions.Length; i++)
                    if (string.Equals(ProfileOptions[i], profileName, StringComparison.OrdinalIgnoreCase))
                        return i;
                return 0;
            }
        }

        // ==================== Lifecycle ====================

        public override void OnStart(StartState state)
        {
            base.OnStart(state);
            if (string.IsNullOrEmpty(explosiveNodeID) || part.FindAttachNode(explosiveNodeID) == null)
                explosiveNodeID = ReleaseNodeId;
            BindModel();
            Rebuild(false);
        }

        private void BindModel()
        {
            _bodyMesh = OwnMesh(bodyTransformName, out _bodyFilter);
            _hooksMesh = OwnMesh(hooksTransformName, out _hooksFilter);
            Transform ct = part.FindModelTransform(colliderTransformName);
            if (ct != null)
            {
                _collider = ct.GetComponent<MeshCollider>();
                if (_collider == null)
                    _collider = ct.gameObject.AddComponent<MeshCollider>();
                _colMesh = new Mesh();
                _colMesh.name = "ROPP_PylonCollider";
            }
        }

        // Same rule as the propeller: create runtime meshes through MeshFilter.mesh so mods that read
        // MeshFilter.mesh (Firefly, KSPCF drag cubes, Deferred) get this mesh instead of cloning it.
        private static Mesh OwnMesh(Transform tr, out MeshFilter mf)
        {
            mf = null;
            if (tr == null)
                return null;
            mf = tr.GetComponent<MeshFilter>();
            if (mf == null)
                return null;
            Mesh m = mf.mesh;
            m.MarkDynamic();
            return m;
        }

        private Mesh OwnMesh(string transformName, out MeshFilter mf)
        {
            return OwnMesh(part.FindModelTransform(transformName), out mf);
        }

        // No OnDestroy here: ModuleDecouplerBase has a private OnDestroy (it unhooks onVesselWasModified),
        // and Unity would call only ours. The collider mesh goes with Resources.UnloadUnusedAssets.

        public void Update()
        {
            if (!HighLogic.LoadedSceneIsEditor || !_built)
                return;
            _checkTimer -= Time.unscaledDeltaTime;
            if (_checkTimer > 0f)
                return;
            _checkTimer = 0.1f;
            if (ShapeSignature() != _lastSig)
                Rebuild(true);
        }

        private string ShapeSignature()
        {
            return string.Format("{0:F3}|{1:F3}|{2:F3}|{3:F1}|{4:F1}|{5:F1}|{6}|{7}", pylonLength, pylonHeight, pylonWidth,
                bottomLengthPct, bottomWidthPct, sweepPct, ProfileIndex, showHooks);
        }

        // ==================== Geometry ====================

        private void Rebuild(bool moveAttached)
        {
            pylonLength = Mathf.Clamp(pylonLength, 0.3f, 15f);
            pylonHeight = Mathf.Clamp(pylonHeight, 0.05f, 4f);
            pylonWidth = Mathf.Clamp(pylonWidth, 0.05f, 3f);
            bottomLengthPct = Mathf.Clamp(bottomLengthPct, 20f, 150f);
            bottomWidthPct = Mathf.Clamp(bottomWidthPct, 40f, 150f);
            sweepPct = Mathf.Clamp(sweepPct, -50f, 50f);
            profileName = ProfileOptions[ProfileIndex];

            PylonShape sh = Shape;
            Vector3 oldRelease = _releasePoint;
            Vector3 newRelease = new Vector3(0f, sh.BottomCentreY, sh.height);

            if (_bodyMesh != null)
            {
                PylonMeshGenerator.BuildBody(sh, _buf, false);
                _buf.ApplyToMesh(_bodyMesh, "ROPP_PylonBody");
            }
            if (_hooksMesh != null)
            {
                PylonMeshGenerator.BuildHooks(sh, _buf);
                _buf.ApplyToMesh(_hooksMesh, "ROPP_PylonHooks");
            }
            if (_colMesh != null && _collider != null)
            {
                PylonMeshGenerator.BuildBody(sh, _buf, true);
                _buf.ApplyToMesh(_colMesh, "ROPP_PylonCollider");
                _collider.sharedMesh = null;
                _collider.sharedMesh = _colMesh;
                _collider.convex = true;
            }
            ReclaimMeshes();

            UpdateNodes(sh, newRelease);
            if (moveAttached && _built && HighLogic.LoadedSceneIsEditor)
                MoveReleasedParts(newRelease - oldRelease);
            _releasePoint = newRelease;

            _massTons = ComputeMass(sh);
            massDisplay = string.Format("{0:F0} kg", _massTons * 1000f);
            _lastSig = ShapeSignature();
            _built = true;

            PropellerPhysicsEngine.NotifyFARRebuild(part);
            if (HighLogic.LoadedSceneIsEditor && EditorLogic.fetch != null && EditorLogic.fetch.ship != null)
                GameEvents.onEditorShipModified.Fire(EditorLogic.fetch.ship);
        }

        private void ReclaimMeshes()
        {
            if (_bodyFilter != null && _bodyMesh != null && _bodyFilter.sharedMesh != _bodyMesh)
                _bodyFilter.sharedMesh = _bodyMesh;
            if (_hooksFilter != null && _hooksMesh != null && _hooksFilter.sharedMesh != _hooksMesh)
                _hooksFilter.sharedMesh = _hooksMesh;
        }

        private void UpdateNodes(PylonShape sh, Vector3 release)
        {
            float size = Mathf.Max(sh.length * 0.5f, sh.width);
            int nodeSize = size < 0.9f ? 0 : (size < 1.8f ? 1 : 2);
            if (part.attachNodes != null)
            {
                for (int i = 0; i < part.attachNodes.Count; i++)
                {
                    AttachNode an = part.attachNodes[i];
                    if (an == null)
                        continue;
                    if (string.Equals(an.id, ReleaseNodeId, StringComparison.OrdinalIgnoreCase))
                    {
                        an.position = release;
                        an.originalPosition = release;
                        an.orientation = an.originalOrientation = new Vector3(0f, 0f, 1f);
                        an.size = nodeSize;
                    }
                    else if (string.Equals(an.id, MountNodeId, StringComparison.OrdinalIgnoreCase))
                    {
                        an.position = an.originalPosition = Vector3.zero;
                        an.orientation = an.originalOrientation = new Vector3(0f, 0f, -1f);
                        an.size = nodeSize;
                    }
                }
            }
            if (part.srfAttachNode != null)
            {
                part.srfAttachNode.position = part.srfAttachNode.originalPosition = Vector3.zero;
                part.srfAttachNode.orientation = part.srfAttachNode.originalOrientation = new Vector3(0f, 0f, 1f);
            }
        }

        /// <summary>Keeps the aircraft on the hooks when the editor shape changes.</summary>
        private void MoveReleasedParts(Vector3 localDelta)
        {
            if (localDelta.sqrMagnitude < 1e-10f)
                return;
            Vector3 world = part.transform.TransformVector(localDelta);
            for (int i = 0; i < part.children.Count; i++)
            {
                Part c = part.children[i];
                if (c != null && IsOnReleaseSide(c))
                    c.transform.position += world;
            }
            // aircraft built as the root: the pylon (and the carrier hanging from it) moves instead
            if (part.parent != null && IsOnReleaseSide(part.parent))
                part.transform.position -= world;
        }

        private float ComputeMass(PylonShape sh)
        {
            float aTop = PylonMeshGenerator.SectionArea(sh.profile, sh.TopFront, sh.TopAft, sh.TopHalfWidth);
            float aBot = PylonMeshGenerator.SectionArea(sh.profile, sh.BottomFront, sh.BottomAft, sh.BottomHalfWidth);
            float volume = 0.5f * (aTop + aBot) * sh.height;
            float m = baseMass + massPerVolume * volume;
            if (sh.hooks)
                m += hookMass * PylonMeshGenerator.HookStations(sh).Length * sh.HardwareScale * sh.HardwareScale;
            return m;
        }

        // ==================== Release ====================

        /// <summary>True if <paramref name="other"/> (a part connected to the pylon) is released.</summary>
        public bool IsOnReleaseSide(Part other)
        {
            if (other == null)
                return false;
            AttachNode n = part.FindAttachNodeByPart(other);
            if (n != null && n != part.srfAttachNode)
                return string.Equals(n.id, ReleaseNodeId, StringComparison.OrdinalIgnoreCase);
            if (other == part.parent)
                return false;     // the pylon was placed on it (surface attach on the mount face): stays with it
            if (other.parent == part)
            {
                // surface-attached to the pylon: released if nearer the hook face than the mount face
                Vector3 p = other.transform.position;
                if (other.srfAttachNode != null && other.attachMode == AttachModes.SRF_ATTACH)
                    p = other.transform.TransformPoint(other.srfAttachNode.position);
                Vector3 local = part.transform.InverseTransformPoint(p);
                return local.z > 0.5f * pylonHeight;
            }
            return false;
        }

        public List<Part> ReleasedParts()
        {
            var list = new List<Part>();
            if (part.parent != null && IsOnReleaseSide(part.parent))
                list.Add(part.parent);
            for (int i = 0; i < part.children.Count; i++)
                if (IsOnReleaseSide(part.children[i]))
                    list.Add(part.children[i]);
            return list;
        }

        // Re-implements IStageSeparatorChild (the base method is not overridable) so the staging and
        // delta-v simulation know what the pylon actually releases.
        public new bool PartDetaches(out List<Part> decoupledParts)
        {
            decoupledParts = new List<Part>();
            List<Part> rel = ReleasedParts();
            for (int i = 0; i < rel.Count; i++)
                decoupledParts.Add(rel[i] == part.parent ? part : rel[i]);
            return decoupledParts.Count > 0 && !isDecoupled;
        }

        public override void OnDecouple()
        {
            if (isDecoupled)
                return;
            List<Part> released = ReleasedParts();
            if (fx != null)
                fx.Burst();

            Vessel oldVessel = vessel;
            Part controlPart = oldVessel != null ? oldVessel.GetReferenceTransformPart() : null;
            Vector3 dir = part.transform.TransformDirection(Vector3.forward);   // pylon +Z: towards the aircraft
            float force = ejectionForce * ejectionForcePercent * 0.01f * 0.5f;

            for (int i = 0; i < released.Count; i++)
            {
                Part p = released[i];
                if (p == part.parent)
                    part.decouple(0f);
                else
                    p.decouple(0f);
            }
            if (released.Count > 0)
            {
                StartCoroutine(Eject(released, dir, force));
                GameEvents.onStageSeparation.Fire(new EventReport(FlightEvents.STAGESEPARATION, part, null, null,
                    StageManager.CurrentStage, string.Empty, 0f));
            }
            isDecoupled = true;
            refreshStaging = true;
            BaseEvent ev = Events["Decouple"];
            if (ev != null)
                ev.active = false;
            if (controlPart != null && oldVessel != null)
                StartCoroutine(FollowControlPart(controlPart, oldVessel));
        }

        // Push the aircraft away from the hooks (and the carrier the other way) for one physics frame
        private IEnumerator Eject(List<Part> released, Vector3 dir, float force)
        {
            yield return new WaitForFixedUpdate();
            if (force <= 0f)
                yield break;
            for (int i = 0; i < released.Count; i++)
            {
                Part p = released[i];
                if (p != null && p.Rigidbody != null)
                    p.Rigidbody.AddForce(dir * force, ForceMode.Force);
            }
            if (part != null && part.Rigidbody != null)
                part.Rigidbody.AddForce(-dir * force, ForceMode.Force);
        }

        // Like stock decouplers: if the part you control from ("Control From Here", e.g. the X-plane's
        // cockpit) left with the released aircraft, the camera and controls follow it.
        private IEnumerator FollowControlPart(Part controlPart, Vessel oldVessel)
        {
            yield return null;
            yield return null;
            if (controlPart != null && controlPart.vessel != null && controlPart.vessel != oldVessel &&
                FlightGlobals.ActiveVessel == oldVessel)
                FlightGlobals.ForceSetActiveVessel(controlPart.vessel);
        }

        // ==================== Info & modifiers ====================

        public override string GetModuleDisplayName()
        {
            return "Launch Pylon";
        }

        public override string GetInfo()
        {
            return "Releases the aircraft hanging from its hooks and <b>stays on the part it is mounted to</b> " +
                   "(the carrier or launch stand), unlike a radial decoupler.\n\n" +
                   "Place it on the carrier first, then attach the aircraft to the hook face (surface attach or the " +
                   "release node). Shape and size are set in the part menu.\n\n" +
                   "<b>Ejection force:</b> " + ejectionForce.ToString("F0") + " kN";
        }

        public float GetModuleMass(float defaultMass, ModifierStagingSituation sit)
        {
            float m = _massTons > 0f ? _massTons : ComputeMass(Shape);
            return m - defaultMass;
        }

        public ModifierChangeWhen GetModuleMassChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }

        public float GetModuleCost(float defaultCost, ModifierStagingSituation sit)
        {
            float m = _massTons > 0f ? _massTons : ComputeMass(Shape);
            return baseCost + costPerTon * m - defaultCost;
        }

        public ModifierChangeWhen GetModuleCostChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }

        public Vector3 GetModuleSize(Vector3 defaultSize, ModifierStagingSituation sit)
        {
            float len = Mathf.Max(pylonLength, pylonLength * bottomLengthPct * 0.01f + Mathf.Abs(sweepPct) * 0.01f * pylonLength);
            float wid = pylonWidth * Mathf.Max(1f, bottomWidthPct * 0.01f);
            return new Vector3(wid, len, pylonHeight) - defaultSize;
        }

        public ModifierChangeWhen GetModuleSizeChangeWhen()
        {
            return ModifierChangeWhen.CONSTANTLY;
        }
    }
}
