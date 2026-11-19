using System;
using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    [KSPAddon(KSPAddon.Startup.EditorAny, false)]
    public class EngineWorkshopEditor : EngineWorkshopWindow { }

    [KSPAddon(KSPAddon.Startup.Flight, false)]
    public class EngineWorkshopFlight : EngineWorkshopWindow { }

    /// <summary>
    /// The Engine Workshop. Editor: five tabs (Engines, Engine, Propeller, Paint, Options) and a
    /// performance panel that says in plain words how each aspect changed since the window opened,
    /// plus what the last change did. Flight: live cockpit gauges, engine controls and engine info.
    /// </summary>
    public class EngineWorkshopWindow : MonoBehaviour
    {
        private const float WinW = 900f;
        private const float WinH = 640f;
        private const float SideW = 300f;
        private const float MainW = WinW - SideW - 38f;
        private const string LockId = "ROPP_EngineWorkshop";

        private struct Aspects
        {
            public bool valid;
            public float power, takeoff, speed, altitude, mass, ptw, fuel, cost;
        }

        private static readonly string[] AspectNames =
        {
            "Power", "Takeoff pull", "Pull at 500 km/h", "Power at 6 km", "Weight", "Power-to-weight", "Fuel use", "Cost"
        };
        private static readonly bool[] HigherIsBetter = { true, true, true, true, false, true, false, false };
        private static readonly string[] UpWords =
        {
            "more power", "stronger takeoff", "more pull at speed", "better at altitude",
            "heavier", "better power-to-weight", "more fuel use", "more expensive"
        };
        private static readonly string[] DownWords =
        {
            "less power", "weaker takeoff", "less pull at speed", "worse at altitude",
            "lighter", "worse power-to-weight", "less fuel use", "cheaper"
        };

        private static EngineWorkshopWindow _instance;

        private List<ModuleProceduralPropeller> _engines = new List<ModuleProceduralPropeller>();
        private float _enginesTimer;
        private ModuleProceduralPropeller _switchTo;

        private ModuleProceduralPropeller _target;
        private bool _visible;
        private Rect _rect;
        private bool _locked;
        private int _tab;
        private int _filter;
        private Vector2 _scroll;

        private ConfigNode _startDesign;
        private Aspects _start;

        // Feedback for the most recent change
        private bool _pending;
        private string _pendingLabel = "";
        private Aspects _before;
        private AJEParameters _beforeAje;
        private string _lastLabel = "";
        private float _lastChangeTime = -10f;
        private string _changeText = "";

        // Audio preview ("Listen"): the real start sequence and mixer, driven by a scripted run
        private PropellerAudio _prevAudio;
        private EngineStartSequence _prevSeq;
        private float _prevTime = -1f;
        private float _prevRunTime;
        private float _prevOffTime;
        private float _prevRPM;
        private float _prevLoad;
        private bool _prevIgnition;

        // Styles
        private bool _stylesReady;
        private GUIStyle _sWindow, _sTitle, _sSubtitle, _sSection, _sLabel, _sSmall, _sHint, _sValue, _sCard, _sCardSel;
        private GUIStyle _sBtn, _sBtnOn, _sTab, _sTabOn, _sPanel, _sHeaderBar, _sBox, _sRow;
        private Texture2D _tBg, _tPanel, _tCard, _tCardHover, _tCardSel, _tAccent, _tBarBg, _tBtn, _tBtnHover, _tBtnOn, _tHeader, _tWhite, _tCyan, _tGreen, _tRed, _tBox;
        private readonly List<Texture2D> _ownedTex = new List<Texture2D>();
        private static readonly Color Accent = new Color(1f, 0.62f, 0.2f);

        // ================================================================ lifecycle

        public static void Toggle(ModuleProceduralPropeller m)
        {
            if (_instance == null || m == null)
                return;
            if (_instance._visible && _instance._target == m)
                _instance.Hide();
            else
                _instance.Show(m, false);
        }

        protected virtual void Awake()
        {
            _instance = this;
            _rect = new Rect((Screen.width - WinW) * 0.5f, Mathf.Max(40f, (Screen.height - WinH) * 0.35f), WinW, WinH);
        }

        protected virtual void OnDestroy()
        {
            SetLock(false);
            StopPreview();
            if (_prevAudio != null)
            {
                _prevAudio.Destroy();
                _prevAudio = null;
            }
            for (int i = 0; i < _ownedTex.Count; i++)
                if (_ownedTex[i] != null) Destroy(_ownedTex[i]);
            if (_instance == this)
                _instance = null;
        }

        private void Show(ModuleProceduralPropeller m, bool keepTab)
        {
            _target = m;
            _visible = true;
            if (!keepTab)
                _tab = 0;
            _startDesign = m.SaveDesign();
            _start = Measure(m);
            _pending = false;
            _changeText = "";
            _engines = ShipEngines();
            _enginesTimer = 0.5f;
        }

        private void Hide()
        {
            _visible = false;
            SetLock(false);
            StopPreview();
        }

        // ================================================================ engine picker

        /// <summary>One engine per symmetry group, from the craft in the editor or the active vessel.</summary>
        private static List<ModuleProceduralPropeller> ShipEngines()
        {
            List<ModuleProceduralPropeller> res = new List<ModuleProceduralPropeller>();
            List<Part> parts = null;
            if (HighLogic.LoadedSceneIsEditor)
            {
                if (EditorLogic.fetch != null && EditorLogic.fetch.ship != null)
                    parts = EditorLogic.fetch.ship.parts;
            }
            else if (FlightGlobals.ActiveVessel != null)
            {
                parts = FlightGlobals.ActiveVessel.parts;
            }
            if (parts == null)
                return res;
            for (int i = 0; i < parts.Count; i++)
            {
                Part p = parts[i];
                if (p == null) continue;
                ModuleProceduralPropeller m = p.FindModuleImplementing<ModuleProceduralPropeller>();
                if (m == null) continue;
                bool twin = false;
                if (p.symmetryCounterparts != null)
                {
                    for (int j = 0; j < p.symmetryCounterparts.Count && !twin; j++)
                    {
                        Part c = p.symmetryCounterparts[j];
                        if (c == null) continue;
                        ModuleProceduralPropeller cm = c.FindModuleImplementing<ModuleProceduralPropeller>();
                        twin = cm != null && res.Contains(cm);
                    }
                }
                if (!twin)
                    res.Add(m);
            }
            return res;
        }

        private void SetLock(bool on)
        {
            if (on == _locked) return;
            _locked = on;
            if (on)
                InputLockManager.SetControlLock(HighLogic.LoadedSceneIsEditor ? ControlTypes.EDITOR_LOCK : ControlTypes.CAMERACONTROLS, LockId);
            else
                InputLockManager.RemoveControlLock(LockId);
        }

        protected virtual void Update()
        {
            if (_visible && (_target == null || _target.part == null))
                Hide();
            if (_switchTo != null)
            {
                ModuleProceduralPropeller next = _switchTo;
                _switchTo = null;
                if (_visible && next.part != null)
                {
                    StopPreview();
                    Show(next, true);
                }
            }
            if (_visible)
            {
                _enginesTimer -= Time.unscaledDeltaTime;
                if (_enginesTimer <= 0f)
                {
                    _enginesTimer = 0.5f;
                    _engines = ShipEngines();
                }
            }
            if (_visible && _pending && _target != null && _target.CurrentMetrics.aje != _beforeAje)
            {
                _pending = false;
                _changeText = Describe(_pendingLabel, _before, Measure(_target));
            }
            UpdatePreview(Time.unscaledDeltaTime);
        }

        protected virtual void OnGUI()
        {
            if (!_visible || _target == null || _target.part == null)
            {
                SetLock(false);
                return;
            }
            InitStyles();
            SetLock(_rect.Contains(Event.current.mousePosition));
            _rect = GUILayout.Window(GetInstanceID() + 51723, _rect, DrawWindow, "", _sWindow, GUILayout.Width(WinW), GUILayout.Height(WinH));
        }

        // ================================================================ measuring & describing

        private static Aspects Measure(ModuleProceduralPropeller t)
        {
            Aspects a = new Aspects();
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            if (m.aje == null)
                return a;
            bool turbo = t.IsTurboprop;
            a.valid = true;
            a.power = m.shaftPowerHP;
            a.takeoff = m.staticThrustKn;
            a.speed = PerformanceModel.ThrustKN(m.shaftPowerHP, t.propDiameter, t.isContraRotating, turbo,
                m.aje.exhaustThrust, m.maxPropRPM, 500f / 3.6f, 0f);
            a.altitude = PerformanceModel.PowerHP(m.aje, turbo, 6000f, 1f);
            a.mass = m.dryMassTons * 1000f;
            a.ptw = a.power / Mathf.Max(1f, a.mass);
            a.fuel = PerformanceModel.FuelLitresPerHour(m.aje.bsfc, m.shaftPowerHP, m.fuelResourceName);
            a.cost = m.partCostFunds;
            return a;
        }

        private static float Get(Aspects a, int i)
        {
            switch (i)
            {
                case 0: return a.power;
                case 1: return a.takeoff;
                case 2: return a.speed;
                case 3: return a.altitude;
                case 4: return a.mass;
                case 5: return a.ptw;
                case 6: return a.fuel;
                default: return a.cost;
            }
        }

        private string Format(int i, float v)
        {
            string hp = _target != null && _target.IsTurboprop ? "shp" : "hp";
            switch (i)
            {
                case 0: return string.Format("{0:N0} {1}", v, hp);
                case 1: return string.Format("{0:F1} kN", v);
                case 2: return string.Format("{0:F1} kN", v);
                case 3: return string.Format("{0:N0} {1}", v, hp);
                case 4: return string.Format("{0:N0} kg", v);
                case 5: return string.Format("{0:F2} {1}/kg", v, hp);
                case 6: return string.Format("{0:N0} L/h", v);
                default: return string.Format("{0:N0}", v);
            }
        }

        /// <summary>"+12% stronger takeoff" in green or red, or null when the change is under 1 %.</summary>
        private static string ChangeWords(int i, float before, float after)
        {
            if (Mathf.Abs(before) < 1e-4f)
                return null;
            float pct = (after - before) / Mathf.Abs(before) * 100f;
            if (Mathf.Abs(pct) < 1f)
                return null;
            bool good = (pct > 0f) == HigherIsBetter[i];
            return string.Format("<color={0}>{1:F0}% {2}</color>", good ? "#7fe08a" : "#ff8a7a",
                Mathf.Abs(pct), pct > 0f ? UpWords[i] : DownWords[i]);
        }

        private static string Describe(string label, Aspects before, Aspects after)
        {
            if (!before.valid || !after.valid)
                return "<b>" + label + "</b>";
            List<KeyValuePair<float, string>> parts = new List<KeyValuePair<float, string>>();
            for (int i = 0; i < AspectNames.Length; i++)
            {
                if (i == 5) continue; // power-to-weight follows from power and weight
                float b = Get(before, i);
                float a = Get(after, i);
                string w = ChangeWords(i, b, a);
                if (w != null)
                    parts.Add(new KeyValuePair<float, string>(Mathf.Abs((a - b) / Mathf.Max(1e-4f, Mathf.Abs(b))), w));
            }
            if (parts.Count == 0)
                return "<b>" + label + "</b>\nNo effect on performance (looks only).";
            parts.Sort((x, y) => y.Key.CompareTo(x.Key));
            List<string> words = new List<string>();
            for (int i = 0; i < parts.Count && i < 5; i++)
                words.Add(parts[i].Value);
            return "<b>" + label + "</b>\n" + string.Join(", ", words.ToArray());
        }

        /// <summary>Call before changing anything; a continuous slider drag counts as one change.</summary>
        private void BeginChange(string label)
        {
            float now = Time.realtimeSinceStartup;
            bool sameDrag = label == _lastLabel && now - _lastChangeTime < 1.5f && _before.valid;
            if (!sameDrag)
                _before = Measure(_target);
            _lastLabel = label;
            _lastChangeTime = now;
            _pending = true;
            _pendingLabel = label;
            _beforeAje = _target.CurrentMetrics.aje;
        }

        // ================================================================ window

        private void DrawWindow(int id)
        {
            bool editor = HighLogic.LoadedSceneIsEditor;
            if (_target.CurrentMetrics.aje == null)
            {
                GUILayout.Label("The engine is still starting up...", _sLabel);
                GUI.DragWindow();
                return;
            }

            DrawHeader(editor);
            GUILayout.Space(4f);
            DrawTabs(editor);
            GUILayout.Space(6f);

            GUILayout.BeginHorizontal();
            GUILayout.BeginVertical(_sPanel, GUILayout.Width(MainW), GUILayout.ExpandHeight(true));
            _scroll = GUILayout.BeginScrollView(_scroll, false, false, GUIStyle.none, HighLogic.Skin.verticalScrollbar);
            if (editor)
            {
                switch (_tab)
                {
                    case 0: DrawEnginesTab(); break;
                    case 1: DrawEngineTab(); break;
                    case 2: DrawPropellerTab(); break;
                    case 3: DrawPaintTab(); break;
                    default: DrawOptionsTab(); break;
                }
            }
            else
            {
                if (_tab == 0) DrawCockpitTab();
                else DrawInfoTab();
            }
            GUILayout.EndScrollView();
            GUILayout.EndVertical();
            GUILayout.Space(8f);
            DrawPerformancePanel(editor);
            GUILayout.EndHorizontal();

            string tip = GUI.tooltip;
            GUILayout.Label(string.IsNullOrEmpty(tip)
                ? (editor ? "Tip: hover over any option to see what it does. Changes show on the part immediately."
                          : "Live values come from the engine simulation (AJE).")
                : tip, _sHint);
            GUI.DragWindow(new Rect(0f, 0f, WinW, 44f));
        }

        private void DrawHeader(bool editor)
        {
            GUILayout.BeginHorizontal(_sHeaderBar, GUILayout.Height(44f));
            GUILayout.BeginVertical(GUILayout.Width(420f));
            GUILayout.Label(_target.DisplayName, _sTitle);
            PropellerPreset p = _target.ActivePreset;
            GUILayout.Label(p != null ? "Historical engine  ·  " + p.historicalAircraft : "Your own design", _sSubtitle);
            GUILayout.EndVertical();
            GUILayout.FlexibleSpace();
            int idx = _engines.IndexOf(_target);
            if (_engines.Count > 1 && idx >= 0)
            {
                int pick = idx;
                if (GUILayout.Button(new GUIContent("<", "Previous engine on this craft."), _sBtn, GUILayout.Width(28f), GUILayout.Height(30f)))
                    pick = (idx + _engines.Count - 1) % _engines.Count;
                GUILayout.Label(new GUIContent(string.Format("Engine {0}/{1}", idx + 1, _engines.Count),
                    "This craft has several engines (symmetry twins count as one). Use the arrows to switch."),
                    _sSmall, GUILayout.Width(66f), GUILayout.Height(30f));
                if (GUILayout.Button(new GUIContent(">", "Next engine on this craft."), _sBtn, GUILayout.Width(28f), GUILayout.Height(30f)))
                    pick = (idx + 1) % _engines.Count;
                if (pick != idx)
                    _switchTo = _engines[pick]; // applied in Update so this GUI pass stays consistent
                GUILayout.Space(6f);
            }
            if (editor)
            {
                if (GUILayout.Button(new GUIContent(_prevTime >= 0f ? "Stop sound" : "Listen", "Play this engine starting from cold, idling, running up to full power, throttling back and shutting down."),
                    _sBtn, GUILayout.Width(96f), GUILayout.Height(30f)))
                {
                    if (_prevTime >= 0f) StopPreview();
                    else StartPreview();
                }
                if (GUILayout.Button(new GUIContent("Undo all", "Put the engine back the way it was when you opened the workshop."),
                    _sBtn, GUILayout.Width(86f), GUILayout.Height(30f)))
                {
                    BeginChange("Undo all changes");
                    _target.LoadDesign(_startDesign);
                }
            }
            if (GUILayout.Button(new GUIContent("Close", "Close the workshop."), _sBtn, GUILayout.Width(66f), GUILayout.Height(30f)))
                Hide();
            GUILayout.EndHorizontal();
        }

        private void DrawTabs(bool editor)
        {
            string[] tabs = editor
                ? new string[] { "Engines", "Engine", "Propeller", "Paint", "Options" }
                : new string[] { "Cockpit", "Engine info" };
            string[] tips = editor
                ? new string[]
                {
                    "Pick a real historical engine.",
                    "Engine type, cylinders, power and supercharger.",
                    "Propeller size, blades and contra-rotation.",
                    "Paint schemes and your own colours.",
                    "Cowling size, nacelle, mounting and realism options."
                }
                : new string[] { "Live gauges and engine controls.", "What this engine is and how it performs." };
            if (_tab >= tabs.Length) _tab = 0;
            GUILayout.BeginHorizontal();
            for (int i = 0; i < tabs.Length; i++)
            {
                if (GUILayout.Button(new GUIContent(tabs[i], tips[i]), _tab == i ? _sTabOn : _sTab, GUILayout.Height(30f), GUILayout.Width(editor ? 112f : 150f)))
                {
                    _tab = i;
                    _scroll = Vector2.zero;
                }
            }
            GUILayout.EndHorizontal();
        }

        // ================================================================ tab: engines (presets)

        private static string TechLabel(string tech)
        {
            switch (tech)
            {
                case "supersonicFlightRP0": return "Supersonic Flight (1950)";
                case "matureSupersonic": return "Mature Supersonic (1952-58)";
                case "highSpeedFlight": return "High Speed Flight (1959)";
                default: return tech;
            }
        }

        private static string KindLabel(PropellerPreset p)
        {
            string k = p.architecture == EngineArchitecture.Turboprop ? "turboprop"
                : PropellerPresets.EngineTypeName((int)p.architecture, p.subStyleIndex, PropellerPresets.PresetCylinders(p));
            if (p.isContraRotating) k += ", contra-prop";
            return k;
        }

        private void DrawEnginesTab()
        {
            GUILayout.Label("Pick a real engine, or build your own. Every value of a historical engine comes from real data.", _sSmall);
            string[] filters = { "All", "Radial", "Inline", "Turboprop" };
            GUILayout.BeginHorizontal();
            for (int i = 0; i < filters.Length; i++)
            {
                if (GUILayout.Button(filters[i], _filter == i ? _sBtnOn : _sBtn, GUILayout.Height(26f)))
                    _filter = i;
            }
            GUILayout.EndHorizontal();
            GUILayout.Space(4f);

            bool custom = _target.ActivePreset == null;
            if (GUILayout.Button(new GUIContent("<b>Build your own engine</b>\n<size=11><color=#9fb2c4>Keep the current engine as a starting point and change anything you like.</color></size>",
                "Turns this into a custom engine and opens the Engine tab."), custom ? _sCardSel : _sCard, GUILayout.Height(46f)))
            {
                if (!custom)
                {
                    BeginChange("Custom engine");
                    _target.MarkCustom();
                }
                _tab = 1;
                _scroll = Vector2.zero;
            }

            List<PropellerPreset> list = new List<PropellerPreset>();
            List<PropellerPreset> all = PropellerPresets.AllPresets;
            for (int i = 0; i < all.Count; i++)
            {
                PropellerPreset p = all[i];
                if (_filter == 1 && p.architecture != EngineArchitecture.Radial) continue;
                if (_filter == 2 && p.architecture != EngineArchitecture.VInline) continue;
                if (_filter == 3 && p.architecture != EngineArchitecture.Turboprop) continue;
                list.Add(p);
            }

            float cardW = (MainW - 40f) * 0.5f;
            for (int i = 0; i < list.Count; i += 2)
            {
                GUILayout.BeginHorizontal();
                for (int j = i; j < i + 2 && j < list.Count; j++)
                {
                    PropellerPreset p = list[j];
                    bool unlocked = PropellerPresets.IsTechAvailable(p.techRequired);
                    bool sel = _target.ActivePreset == p;
                    string unit = p.IsTurboprop ? "shp" : "hp";
                    string line3 = unlocked
                        ? string.Format("{0:N0} {1} · {2:N0} kg · {3}", p.shaftPowerHP, unit, p.massTons * 1000f, p.historicalAircraft)
                        : "<color=#ff8a7a>Unlocks with " + TechLabel(p.techRequired) + "</color>";
                    string text = string.Format("<b>{0}</b>\n<size=11><color=#9fb2c4>{1}</color></size>\n<size=11>{2}</size>",
                        p.displayName, KindLabel(p), line3);
                    GUI.enabled = unlocked;
                    if (GUILayout.Button(new GUIContent(text, p.description), sel ? _sCardSel : _sCard, GUILayout.Width(cardW), GUILayout.Height(66f)) && !sel)
                    {
                        BeginChange("Loaded " + p.displayName);
                        _target.ApplyPreset(p);
                    }
                    GUI.enabled = true;
                }
                GUILayout.EndHorizontal();
            }
        }

        // ================================================================ tab: engine

        private void DrawEngineTab()
        {
            ModuleProceduralPropeller t = _target;
            if (t.ActivePreset != null)
                GUILayout.Label("This is a historical engine. Changing anything here turns it into your own custom design.", _sBox);

            Section("ENGINE TYPE");
            string[] names = { "Radial", "Inline", "Turboprop" };
            string[] subs = { "air-cooled, rugged, wide", "liquid-cooled, slim, fast", "turbine: light and powerful" };
            string[] tips =
            {
                "Air-cooled cylinders arranged in a star. Tough and simple, but a wide, draggy nose.",
                "Liquid-cooled cylinders in a V. Slim and streamlined for fast fighters.",
                "A gas turbine driving the propeller. About 2.5x the power for the same weight, burns kerosene."
            };
            int arch = t.architectureIndex;
            GUILayout.BeginHorizontal();
            for (int i = 0; i < 3; i++)
            {
                bool locked = i == 2 && !ModuleProceduralPropeller.TurbopropAllowed && arch != 2;
                GUI.enabled = !locked;
                string label = "<b>" + names[i] + "</b>\n<size=10>" + (locked ? "unlocks with Mature Supersonic" : subs[i]) + "</size>";
                if (GUILayout.Button(new GUIContent(label, tips[i]), arch == i ? _sBtnOn : _sBtn, GUILayout.Height(44f)) && arch != i)
                {
                    BeginChange("Engine type: " + names[i]);
                    t.ChangeArchitecture(i);
                }
                GUI.enabled = true;
            }
            GUILayout.EndHorizontal();
            if (arch == 2)
                Hint("Switching type keeps the engine's weight, so a turboprop gets about 2.5x the power of the piston engine it replaces.");

            Section(arch == 0 ? "ROWS OF CYLINDERS" : (arch == 1 ? "CYLINDER BANKS" : "LAYOUT"));
            string[] layouts = PropellerPresets.GetSubStyleLabels(arch);
            string[] layoutTips = arch == 0
                ? new[] { "Two rows, one behind the other (R-2800, BMW 801, ASh-82): the classic fighter radial.", "One row (R-1820, Bristol Mercury): small, light and simple.", "Four rows (R-4360): huge power, long engine." }
                : (arch == 1
                    ? new[] { "Two banks in an upright V (Merlin, Griffon, Allison V-1710).", "Two banks hanging under the crankshaft (DB 605, Jumo 213): good view over the nose, slim nose with a tight cowling.", "Four banks in an X: twice the cylinders on one crankshaft (Rolls-Royce Vulture)." }
                    : new[] { "Medium turboprop with a chin air intake (T56).", "Big turboprop with a ring-shaped intake (NK-12).", "Small free-turbine turboprop (PT6)." });
            int sub = t.subStyleIndex;
            int newSub = ButtonRow(layouts, layoutTips, sub, 30f);
            if (newSub != sub)
            {
                BeginChange("Layout: " + layouts[newSub]);
                t.FreezeDisplacement();
                t.subStyleIndex = newSub;
                t.MarkCustom();
            }

            float minHP, maxHP;
            string why;
            PropellerPhysicsEngine.GetPowerLimits(t, out minHP, out maxHP, out why);
            string unit = arch == 2 ? "shp" : "hp";
            if (arch != 2)
            {
                DrawCylinderControls(t, arch, minHP, maxHP);
            }
            else
            {
                Section("POWER");
                float pw = Slider(t.shaftPowerHP, minHP, maxHP, 25f, "{0:N0} " + unit,
                    "Maximum shaft power. More power gives more pull but a bigger, heavier, thirstier engine.");
                if (pw != t.shaftPowerHP)
                {
                    BeginChange("Power");
                    t.shaftPowerHP = pw;
                    t.MarkCustom();
                }
                Hint(string.Format("Possible for this layout: {0:N0} - {1:N0} {2} ({3}).", minHP, maxHP, unit, why));
            }

            if (arch != 2)
            {
                Section("SUPERCHARGER");
                Hint("Air gets thinner as you climb. A supercharger squeezes it so the engine keeps its power higher up.");
                string[] sc = { "None", "Single stage", "Two-speed", "Two-stage + intercooler", "Turbocharger", "Turbo-compound" };
                string[] scDesc =
                {
                    "simple and light, loses power from take-off",
                    "full power up to a moderate altitude",
                    "two gears: strong low and at medium altitude",
                    "the best high-altitude fighters (Merlin 66)",
                    "exhaust turbine: full power very high (bombers)",
                    "exhaust turbines geared to the crankshaft: ~40% less fuel"
                };
                int asp = t.aspirationIndex;
                for (int i = 0; i < sc.Length; i++)
                {
                    string txt = "<b>" + sc[i] + "</b>  <size=11><color=#9fb2c4>" + scDesc[i] + "</color></size>";
                    if (GUILayout.Button(txt, asp == i ? _sCardSel : _sRow, GUILayout.Height(26f)) && asp != i)
                    {
                        BeginChange("Supercharger: " + sc[i]);
                        t.FreezeDisplacement();
                        t.aspirationIndex = i;
                        t.boostInHg = 0f; // the new supercharger's usual boost
                        t.MarkCustom();
                    }
                }
                if (t.aspirationIndex != (int)AspirationType.NaturallyAspirated)
                {
                    GUILayout.Space(4f);
                    float bMin, bMax;
                    PropellerPhysicsEngine.BoostRange((AspirationType)t.aspirationIndex, out bMin, out bMax);
                    float boost = PropellerPhysicsEngine.EffectiveBoostInHg(t);
                    GUILayout.Label("Boost (manifold pressure at full power)", _sLabel);
                    float nb = Slider(boost, bMin, bMax, 0.5f, "{0:F1} inHg",
                        "How hard the supercharger may push. More boost: more power from the same cylinders, but the engine runs hotter and needs high-octane fuel.");
                    if (nb != boost)
                    {
                        BeginChange("Boost");
                        t.FreezeDisplacement();
                        t.boostInHg = nb;
                        t.MarkCustom();
                    }
                    Hint(string.Format("{0:+0.0;-0.0} lb/sq in ({1:F2} ata). Merlin 66: 81 inHg (+25 lb), R-2800: 52-58, DB 605A: 42.",
                        (boost - 29.92f) * 0.4912f, boost / 28.96f));
                    GUILayout.Label("Full power up to", _sLabel);
                    float alt = Slider(t.criticalAltitudeKm, 0.5f, 12f, 0.1f, "{0:F1} km",
                        "Altitude where the supercharger runs out of breath and power starts to drop.");
                    if (alt != t.criticalAltitudeKm)
                    {
                        BeginChange("Full-power altitude");
                        t.criticalAltitudeKm = alt;
                        t.MarkCustom();
                    }
                }

                Section("ENGINE SPEED");
                float rpmMax = PropellerPhysicsEngine.PistonSpeedLimitRPM(PropellerPhysicsEngine.CylinderLitres(t, t.CurrentMetrics.aje));
                float shownRpm = Mathf.Clamp(t.maxEngineRPM, 1800f, rpmMax);
                float rpm = Slider(shownRpm, 1800f, rpmMax, 50f, "{0:N0} rpm",
                    "Faster-revving engines make more power from the same cylinders.");
                if (rpm != shownRpm)
                {
                    BeginChange("Engine speed");
                    t.FreezeDisplacement();
                    t.maxEngineRPM = rpm;
                    t.MarkCustom();
                }
                Hint(string.Format("Power grows with engine speed, but the pistons can't go faster than ~17 m/s: cylinders this size top out at {0:N0} rpm (smaller cylinders rev higher). The propeller gearbox keeps the blade tips below the speed of sound.", rpmMax));
            }
            else
            {
                Hint("Turboprops need no supercharger: they lose power gradually as the air thins and gain some back from ram air at speed.");
            }
        }

        /// <summary>Cylinders per row/bank, cylinder size and the resulting power of a piston engine.</summary>
        private void DrawCylinderControls(ModuleProceduralPropeller t, int arch, float minHP, float maxHP)
        {
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            int rows = PropellerPhysicsEngine.CylinderRows(arch, t.subStyleIndex);
            int perRow = t.CylindersPerRowResolved;
            int[] opts = PropellerPhysicsEngine.CylinderOptions(arch);

            Section(arch == 0 ? "CYLINDERS PER ROW" : "CYLINDERS PER BANK");
            string[] labels = new string[opts.Length];
            string[] tips = new string[opts.Length];
            int sel = 0;
            for (int i = 0; i < opts.Length; i++)
            {
                labels[i] = opts[i] + "  (" + PropellerPresets.EngineTypeName(arch, t.subStyleIndex, opts[i] * rows) + ")";
                if (opts[i] == perRow) sel = i;
            }
            if (arch == 0)
            {
                tips[0] = "Five per row: small, light radials (Kinner, Warner, early trainers).";
                tips[1] = "Seven per row: R-1830 Twin Wasp, BMW 801, ASh-82, Bristol Hercules, R-4360.";
                tips[2] = "Nine per row: R-1820 Cyclone, R-2800 Double Wasp, R-3350. The most a row can hold.";
            }
            else
            {
                tips[0] = "Four per bank: V-8 / X-16. Short and light, but rougher-running.";
                tips[1] = "Six per bank: the classic V-12 (Merlin, DB 605, Allison) or X-24.";
                tips[2] = "Eight per bank: V-16 / X-32. Very long crankshaft, lots of power from a slim engine.";
            }
            int ns = ButtonRow(labels, tips, sel, 28f);
            if (ns != sel)
            {
                BeginChange(opts[ns] + " cylinders per " + (arch == 0 ? "row" : "bank"));
                t.FreezeDisplacement();
                t.cylindersPerRow = opts[ns];
                t.MarkCustom();
            }

            Section("CYLINDER SIZE");
            float litres = PropellerPhysicsEngine.CylinderLitres(t, m.aje);
            float shownL = Mathf.Clamp(litres, PropellerPhysicsEngine.MinCylinderLitres, PropellerPhysicsEngine.MaxCylinderLitres);
            float nl = Slider(shownL, PropellerPhysicsEngine.MinCylinderLitres, PropellerPhysicsEngine.MaxCylinderLitres, 0.05f, "{0:F2} L each",
                "Swept volume of one cylinder. Bigger cylinders make more power but make a radial wider and an inline longer and taller.");
            if (Mathf.Abs(nl - shownL) > 0.004f)
            {
                BeginChange("Cylinder size");
                t.FreezeDisplacement();
                t.cylinderLitres = nl;
                t.MarkCustom();
            }
            float bore, stroke;
            PropellerPhysicsEngine.BoreStroke(litres, out bore, out stroke);
            int total = rows * perRow;
            Hint(string.Format("{0} cylinders of {1:F0} x {2:F0} mm bore x stroke: {3:F1} L ({4:N0} cu in) in total. The bare engine is {5:F2} m wide.",
                total, bore * 1000f, stroke * 1000f, litres * total, litres * total * 61.0237f, PropellerPhysicsEngine.EngineWidth(t, m.aje)));

            Section("POWER");
            float shownP = Mathf.Clamp(t.shaftPowerHP, minHP, maxHP);
            float pw = Slider(shownP, minHP, maxHP, 25f, "{0:N0} hp",
                "Take-off power. Comes from cylinders x size x engine speed x boost; dragging this resizes the cylinders.");
            if (Mathf.Abs(pw - shownP) > 0.5f)
            {
                BeginChange("Power");
                t.FreezeDisplacement();
                t.SetPowerViaCylinders(pw);
                t.MarkCustom();
            }
            Hint(string.Format("{0:N0} hp per litre. Change the cylinders, engine speed or boost and the power follows; this slider resizes the cylinders instead.",
                t.shaftPowerHP / Mathf.Max(0.1f, litres * total)));
        }

        // ================================================================ tab: propeller

        private void DrawPropellerTab()
        {
            ModuleProceduralPropeller t = _target;
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            int total = t.isContraRotating ? t.bladeCount * 2 : t.bladeCount;

            Section("SIZE");
            GUILayout.BeginHorizontal();
            float d = Slider(t.propDiameter, t.MinPropDiameter, 6.2f, 0.05f, "{0:F2} m",
                "A bigger propeller moves more air: more pull, especially at take-off, but heavier and its tips spin faster.");
            if (GUILayout.Button(new GUIContent("Best size", "Size the propeller for this engine's power and blade count."), _sBtn, GUILayout.Width(84f), GUILayout.Height(24f)))
            {
                BeginChange("Best propeller size");
                t.propDiameter = Mathf.Max(t.MinPropDiameter, Mathf.Round(PropellerPhysicsEngine.OptimalPropDiameter(m.shaftPowerHP, total) * 20f) / 20f);
                t.MarkCustom();
            }
            else if (d != t.propDiameter)
            {
                BeginChange("Propeller size");
                t.propDiameter = d;
                t.MarkCustom();
            }
            GUILayout.EndHorizontal();
            string tip = m.staticTipMach < 0.85f ? "<color=#7fe08a>good</color>"
                : (m.staticTipMach < 0.92f ? "<color=#ffd966>getting close to the speed of sound: some loss at high speed</color>"
                                           : "<color=#ff8a7a>supersonic tips: big losses, use a smaller propeller</color>");
            Hint(string.Format("Blade tips move at Mach {0:F2} on the ground: {1}. Propeller turns at {2:N0} rpm.", m.staticTipMach, tip, m.maxPropRPM));

            Section(t.isContraRotating ? "BLADES PER PROPELLER" : "BLADES");
            string[] bl = { "2", "3", "4", "5", "6", "7", "8" };
            int b = t.bladeCount - 2;
            int nb = ButtonRow(bl, null, b, 26f);
            if (nb != b)
            {
                BeginChange((nb + 2) + " blades");
                t.bladeCount = nb + 2;
                t.MarkCustom();
            }
            Hint("More blades let the propeller absorb more power without growing bigger. Each blade adds weight.");

            Section("ROTATION");
            int contra = t.isContraRotating ? 1 : 0;
            string[] rot = { "Single propeller", "Contra-rotating pair" };
            string[] rotTips =
            {
                "One propeller.",
                "Two propellers on one shaft spinning opposite ways: no torque, and the rear one recovers the swirl of the front one."
            };
            int nc = ButtonRow(rot, rotTips, contra, 30f);
            if (nc != contra)
            {
                BeginChange(nc == 1 ? "Contra-rotating on" : "Contra-rotating off");
                t.isContraRotating = nc == 1;
                t.MarkCustom();
            }
            float gain = (PerformanceModel.ContraThrustGain(m.shaftPowerHP, t.propDiameter) - 1f) * 100f;
            Hint(string.Format("A contra-rotating pair recovers the slipstream swirl a single propeller wastes: about +{0:F0}% pull for this engine (more for very powerful engines on small propellers). The two torques cancel. Heavier and more expensive.", gain));

            Section("BLADE SHAPE (looks)");
            int pf = ButtonRow(new[] { "Elliptical", "Paddle", "Scimitar" }, null, t.bladePlanformIndex, 26f);
            if (pf != t.bladePlanformIndex)
            {
                BeginChange("Blade shape");
                t.bladePlanformIndex = pf;
            }
            Section("SPINNER (looks)");
            int sp = ButtonRow(new[] { "Pointed", "Dome", "Cannon", "Bare hub" }, null, t.spinnerStyleIndex, 26f);
            if (sp != t.spinnerStyleIndex)
            {
                BeginChange("Spinner style");
                t.spinnerStyleIndex = sp;
            }
        }

        // ================================================================ tab: paint

        private void DrawPaintTab()
        {
            ModuleProceduralPropeller t = _target;
            Section("PAINT SCHEME");
            int liv = PropellerPresets.ParseLivery(t.liveryName);
            int cols = 3;
            float tileW = (MainW - 50f) / cols;
            for (int i = 0; i < PropellerPresets.LiveryOptions.Length; i += cols)
            {
                GUILayout.BeginHorizontal();
                for (int j = i; j < i + cols && j < PropellerPresets.LiveryOptions.Length; j++)
                {
                    GUILayout.BeginVertical(GUILayout.Width(tileW));
                    Rect r = GUILayoutUtility.GetRect(tileW - 6f, 34f, GUILayout.Width(tileW - 6f), GUILayout.Height(34f));
                    if (j == liv)
                        GUI.DrawTexture(new Rect(r.x - 3f, r.y - 3f, r.width + 6f, r.height + 6f), _tAccent);
                    DrawSwatch(new Rect(r.x, r.y, r.width, r.height * 0.55f), PropellerPresets.LiveryTop[j]);
                    DrawSwatch(new Rect(r.x, r.y + r.height * 0.55f, r.width, r.height * 0.45f), PropellerPresets.LiveryBottom[j]);
                    if (j == PropellerPresets.CustomLiveryIndex)
                    {
                        Color32 c1 = CustomPaint.ParseColor(t.paintCowl, PropellerPresets.PaintColors[6]);
                        Color32 c2 = CustomPaint.ParseColor(t.paintSpinner, PropellerPresets.PaintColors[0]);
                        DrawSwatch(new Rect(r.x, r.y, r.width * 0.7f, r.height), c1);
                        DrawSwatch(new Rect(r.x + r.width * 0.7f, r.y, r.width * 0.3f, r.height), c2);
                    }
                    if (GUI.Button(r, new GUIContent("", PropellerPresets.LiveryOptions[j]), GUIStyle.none) && j != liv)
                    {
                        BeginChange("Paint: " + PropellerPresets.LiveryOptions[j]);
                        t.liveryName = PropellerPresets.LiveryOptions[j];
                    }
                    GUILayout.Label(PropellerPresets.LiveryOptions[j], j == liv ? _sLabel : _sSmall);
                    GUILayout.EndVertical();
                }
                GUILayout.EndHorizontal();
                GUILayout.Space(4f);
            }

            if (liv == PropellerPresets.CustomLiveryIndex)
            {
                string c = PaintPicker("COWLING COLOUR", t.paintCowl);
                if (c != t.paintCowl) { BeginChange("Cowling colour"); t.paintCowl = c; }
                c = PaintPicker("NOSE RING COLOUR", t.paintNose);
                if (c != t.paintNose) { BeginChange("Nose ring colour"); t.paintNose = c; }
                c = PaintPicker("SPINNER COLOUR", t.paintSpinner);
                if (c != t.paintSpinner) { BeginChange("Spinner colour"); t.paintSpinner = c; }
                Section("FINISH");
                int f = ButtonRow(PropellerPresets.FinishNames, null, Mathf.Clamp(t.paintFinish, 0, 2), 26f);
                if (f != t.paintFinish) { BeginChange("Paint finish"); t.paintFinish = f; }
            }
            else
            {
                Hint("Pick \"Custom Paint\" to choose your own cowling, nose ring and spinner colours.");
            }
        }

        private string PaintPicker(string title, string current)
        {
            Section(title);
            Color32 cur = CustomPaint.ParseColor(current, PropellerPresets.PaintColors[0]);
            string result = current;
            int perRow = 11;
            for (int i = 0; i < PropellerPresets.PaintColors.Length; i += perRow)
            {
                GUILayout.BeginHorizontal();
                for (int j = i; j < i + perRow && j < PropellerPresets.PaintColors.Length; j++)
                {
                    Color32 pc = PropellerPresets.PaintColors[j];
                    Rect r = GUILayoutUtility.GetRect(36f, 24f, GUILayout.Width(36f), GUILayout.Height(24f));
                    bool sel = pc.r == cur.r && pc.g == cur.g && pc.b == cur.b;
                    if (sel)
                        GUI.DrawTexture(new Rect(r.x - 2f, r.y - 2f, r.width + 4f, r.height + 4f), _tAccent);
                    DrawSwatch(r, pc);
                    if (GUI.Button(r, new GUIContent("", PropellerPresets.PaintNames[j]), GUIStyle.none))
                        result = CustomPaint.ToHex(pc);
                }
                GUILayout.EndHorizontal();
            }
            return result;
        }

        private void DrawSwatch(Rect r, Color32 c)
        {
            Color prev = GUI.color;
            GUI.color = c;
            GUI.DrawTexture(r, _tWhite);
            GUI.color = prev;
        }

        // ================================================================ tab: options

        private void DrawOptionsTab()
        {
            ModuleProceduralPropeller t = _target;
            int cyl = t.TotalCylinders;

            Section("COWLING");
            int fit = t.autoCowl ? 0 : 1;
            int nf = ButtonRow(new[] { "Fit to the engine", "Choose my own size" }, new[]
            {
                "The cowling is sized around the cylinders automatically (recommended).",
                "Set the diameter yourself, e.g. to match a fuselage ring."
            }, fit, 28f);
            if (nf != fit)
            {
                BeginChange(nf == 0 ? "Cowling fitted to engine" : "Manual cowling size");
                t.autoCowl = nf == 0;
            }
            if (t.autoCowl)
            {
                int cf = ButtonRow(new[] { "Tight", "Standard", "Roomy" }, new[]
                {
                    "Cowling hugging the engine, like the Bf 109, Spitfire or Fw 190: the slimmest nose and the least drag.",
                    "Normal clearance around the engine.",
                    "Extra room for oil coolers, ducts and accessories: a fatter nose."
                }, Mathf.Clamp(t.cowlFit, 0, 2), 26f);
                if (cf != t.cowlFit)
                {
                    BeginChange("Cowling fit: " + PropellerPhysicsEngine.CowlFitNames[cf]);
                    t.cowlFit = cf;
                }
            }
            string inside = cyl > 0
                ? string.Format("{0} ({1} x {2:F1} L)", PropellerPresets.EngineTypeName(t.architectureIndex, t.subStyleIndex, cyl), cyl,
                    PropellerPhysicsEngine.CylinderLitres(t, t.CurrentMetrics.aje))
                : "turbine core";
            Hint(string.Format("Now {0:F2} m across. The engine inside, a {1}, needs at least {2:F2} m (tight fit) and {3:F2} m length. Smaller cylinders or an inline engine give a slimmer nose.",
                t.cowlDiameter, inside, t.MinCowlDiameter, t.MinCowlLength));
            if (!t.autoCowl)
            {
                GUILayout.Label("Diameter", _sLabel);
                float cd = Slider(Mathf.Max(t.cowlDiameter, t.MinCowlDiameter), t.MinCowlDiameter, 2.6f, 0.02f, "{0:F2} m", "Cowling diameter. It can't be smaller than the engine.");
                if (cd != Mathf.Max(t.cowlDiameter, t.MinCowlDiameter)) { BeginChange("Cowling diameter"); t.cowlDiameter = cd; }
                // Standard fuselage ring sizes (the ROPlanes+ cockpits use these)
                float[] rings = { 0.9375f, 1.25f, 1.5f, 1.875f };
                GUILayout.BeginHorizontal();
                GUILayout.Label("Match a ring:", _sSmall, GUILayout.Width(90f));
                for (int i = 0; i < rings.Length; i++)
                {
                    bool fits = rings[i] >= t.MinCowlDiameter - 1e-3f;
                    GUI.enabled = fits;
                    if (GUILayout.Button(new GUIContent(rings[i].ToString("0.###") + " m",
                        fits ? "Set the cowling to this standard fuselage diameter." : "The engine is too big for this ring: use smaller cylinders, fewer per row, or an inline engine."),
                        Mathf.Abs(t.cowlDiameter - rings[i]) < 0.005f ? _sBtnOn : _sBtn, GUILayout.Height(22f)))
                    {
                        BeginChange("Cowling diameter " + rings[i].ToString("0.###") + " m");
                        t.cowlDiameter = rings[i];
                    }
                    GUI.enabled = true;
                }
                GUILayout.EndHorizontal();
                GUILayout.Label("Length", _sLabel);
                float cl = Slider(t.cowlLength, t.MinCowlLength, 4.0f, 0.05f, "{0:F2} m", "Cowling length. It can't be shorter than the engine.");
                if (cl != t.cowlLength) { BeginChange("Cowling length"); t.cowlLength = cl; }
            }

            Section("NACELLE");
            int nac = ButtonRow(new[] { "Firewall", "Wing nacelle", "Tank nacelle" }, new[]
            {
                "Just the engine, to bolt onto a fuselage nose or firewall.",
                "Engine with a short fairing behind it for mounting on a wing (small fuel tank).",
                "Long streamlined nacelle with a built-in fuel tank."
            }, t.nacelleIndex, 28f);
            if (nac != t.nacelleIndex) { BeginChange("Nacelle"); t.nacelleIndex = nac; }
            if (t.CurrentMetrics.integratedFuelLiters > 1f)
                Hint(string.Format("Carries {0:N0} L of {1}.", t.CurrentMetrics.integratedFuelLiters, t.CurrentMetrics.fuelResourceName));

            Section("MOUNTING");
            int mount = t.isPusher ? 1 : 0;
            int nm = ButtonRow(new[] { "Tractor (propeller in front)", "Pusher (propeller behind)" }, null, mount, 28f);
            if (nm != mount) { BeginChange(nm == 1 ? "Pusher mounting" : "Tractor mounting"); t.isPusher = nm == 1; }

            Section("REALISM");
            int strikes = t.propStrikes ? 0 : 1;
            int ns = ButtonRow(new[] { "Propeller strikes on", "off" }, new[]
            {
                "A spinning propeller that touches the ground or water is wrecked and the engine stops dead. An engineer on EVA can fit a new one on the ground, or recover the craft.",
                "Propellers never break."
            }, strikes, 26f);
            if (ns != strikes) t.propStrikes = ns == 0;
            Hint("Keep the propeller tips clear of the runway: watch out on tail-draggers and belly landings.");
            int tq = t.propTorque ? 0 : 1;
            int ntq = ButtonRow(new[] { "Propeller torque on", "off" }, new[]
            {
                "The engine twists the airframe the opposite way to the propeller: the aircraft wants to roll and to swing on take-off, so you need rudder and aileron (like the real thing). No effect with contra-rotating propellers.",
                "No reaction torque (the propeller only pulls)."
            }, tq, 26f);
            if (ntq != tq) { BeginChange(ntq == 0 ? "Propeller torque on" : "Propeller torque off"); t.propTorque = ntq == 0; }

            Section("PROPELLER ROTATION");
            int rot = Mathf.Clamp(t.propRotation, 0, 1);
            int nrot = ButtonRow(new[] { "Clockwise", "Counter-clockwise" }, new[]
            {
                "Seen from behind, looking forward (the pilot's view). Most engines turn this way, e.g. the Merlin and the R-2800: the torque rolls the aircraft to the left.",
                "Seen from behind, looking forward. E.g. the Griffon, or the left engine of the P-38: the torque rolls the aircraft to the right."
            }, rot, 26f);
            if (nrot != rot) { BeginChange(nrot == 0 ? "Propeller turns clockwise" : "Propeller turns counter-clockwise"); t.propRotation = nrot; }
            bool symmetric = t.part != null && t.part.symmetryCounterparts != null && t.part.symmetryCounterparts.Count > 0;
            if (symmetric)
            {
                int hp = t.handedPair ? 1 : 0;
                int nhp = ButtonRow(new[] { "Same way on all engines", "Opposite on the other side" }, new[]
                {
                    "Every engine of this symmetry group turns the same way, as on most real twins: their torques add up.",
                    "Engines on the other side of the aircraft turn the other way (handed propellers, like the P-38 Lightning or DH Hornet): on a twin their torques cancel."
                }, hp, 26f);
                if (nhp != hp) { BeginChange(nhp == 1 ? "Handed propellers" : "Propellers all turn the same way"); t.handedPair = nhp == 1; }
            }
            if (t.isContraRotating)
            {
                Hint("Contra-rotating: this sets the front propeller; the rear one turns the other way, so there is no torque either way.");
            }
            else
            {
                string side = t.propRotation == 1 ? "right" : "left";
                float kNm = t.CurrentMetrics.shaftPowerHP * 745.7f / Mathf.Max(1f, t.CurrentMetrics.maxPropRPM * 2f * Mathf.PI / 60f) / 1000f;
                string torqueText = t.propTorque
                    ? string.Format("At full power about {0:N1} kN·m of torque rolls the aircraft to the {1}", kNm, side)
                    : "With propeller torque on, the aircraft would roll to the " + side;
                if (symmetric && t.handedPair)
                    Hint(torqueText + " on this engine; the engines on the other side turn the other way, so a balanced pair cancels out.");
                else if (symmetric)
                    Hint(torqueText + ", and every engine in this group adds to it. Choose \"Opposite on the other side\" to balance it.");
                else
                    Hint(torqueText + ". To balance it, give another engine the opposite rotation.");
            }
            if (t.IsTurboprop)
            {
                int af = t.autoFeather ? 0 : 1;
                int na = ButtonRow(new[] { "Auto-feather on", "off" }, new[]
                {
                    "If the engine stops in flight, the propeller turns its blades edge-on after a second to cut drag.",
                    "You feather the propeller yourself."
                }, af, 26f);
                if (na != af) t.autoFeather = na == 0;
            }
        }

        // ================================================================ flight tabs

        private void DrawCockpitTab()
        {
            ModuleProceduralPropeller t = _target;
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            PropellerLiveState s = t.CurrentLiveState;

            string state;
            if (t.propDamaged) state = "<color=#ff8a7a>PROPELLER BROKEN</color>";
            else if (t.isFeathered) state = "<color=#ffd966>FEATHERED</color>";
            else if (t.LiveRunning && t.LivePhase == EnginePhase.Cranking) state = "<color=#ffd966>STARTING · CRANKING</color>";
            else if (t.LiveRunning && t.LivePhase == EnginePhase.Catching)
                state = t.IsTurboprop ? "<color=#ffd966>STARTING · SPOOLING UP</color>" : "<color=#ffd966>STARTING · CATCHING</color>";
            else state = t.LiveRunning ? "<color=#7fe08a>RUNNING</color>" : "<color=#9aa6b2>SHUT DOWN</color>";
            if (t.wepEngaged) state += "   <color=#ff8a4a>WEP</color>";
            if (t.isReversed) state += "   <color=#66ccff>REVERSE PITCH</color>";
            GUILayout.Label(state, _sTitle);
            GUILayout.Space(6f);

            string unit = t.IsTurboprop ? "shp" : "hp";
            float ratedHP = Mathf.Max(1f, m.shaftPowerHP * Mathf.Max(1f, m.wepMultiplier));
            Gauge("Power", s.shaftHP, ratedHP, string.Format("{0:N0} {1}  ({2:F0}%)", s.shaftHP, unit, 100f * s.shaftHP / Mathf.Max(1f, m.shaftPowerHP)), _tAccent);
            Gauge("Propeller", s.propRPM, Mathf.Max(1f, m.maxPropRPM * 1.05f), string.Format("{0:N0} rpm", s.propRPM), _tCyan);
            Gauge("Blade pitch", Mathf.Clamp(s.bladePitchDeg, 0f, 90f), 90f, string.Format("{0:F0}°", t.isFeathered ? 86f : s.bladePitchDeg), _tCyan);
            if (!t.IsTurboprop)
                Gauge("Boost", s.manifoldInHg, Mathf.Max(30f, (float)m.aje.wastegateMP * 1.1f), string.Format("{0:F1} inHg", s.manifoldInHg), _tCyan);
            Gauge("Thrust", t.LiveThrustKN, Mathf.Max(1f, m.staticThrustKn * 1.1f), string.Format("{0:F1} kN", t.LiveThrustKN), _tGreen);
            if (m.wepMultiplier > 1.001f)
                Gauge("WEP left", t.wepRemainingSec, 300f, string.Format("{0:F0} s", t.wepRemainingSec), t.wepEngaged ? _tRed : _tAccent);
            if (t.vessel != null)
                Hint(string.Format("Altitude {0:N0} m   ·   Airspeed {1:N0} km/h   ·   Full power available here: {2:N0} {3}",
                    t.vessel.altitude, t.vessel.srfSpeed * 3.6, PerformanceModel.PowerHP(m.aje, t.IsTurboprop, (float)t.vessel.altitude, 1f), unit));

            Section("CONTROLS");
            GUILayout.BeginHorizontal();
            if (m.wepMultiplier > 1.001f &&
                GUILayout.Button(new GUIContent(t.wepEngaged ? "Stop WEP" : "Engage WEP", "War Emergency Power: extra power for up to 5 minutes."), t.wepEngaged ? _sBtnOn : _sBtn, GUILayout.Height(36f)))
                t.ToggleWEPEvent();
            if (GUILayout.Button(new GUIContent(t.isFeathered ? "Unfeather" : "Feather", "Turn the blades edge-on to stop a dead engine's propeller dragging."), t.isFeathered ? _sBtnOn : _sBtn, GUILayout.Height(36f)))
                t.ToggleFeatherEvent();
            if (t.IsTurboprop &&
                GUILayout.Button(new GUIContent(t.isReversed ? "Normal pitch" : "Reverse pitch", "Reverse the blades to brake after landing."), t.isReversed ? _sBtnOn : _sBtn, GUILayout.Height(36f)))
                t.ToggleReverseEvent();
            GUILayout.EndHorizontal();
        }

        private void DrawInfoTab()
        {
            ModuleProceduralPropeller t = _target;
            PropellerPreset p = t.ActivePreset;
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            Section("ENGINE");
            if (p != null)
            {
                GUILayout.Label("<b>" + p.displayName + "</b>  ·  " + KindLabel(p), _sLabel);
                Hint("Flew in: " + p.historicalAircraft + ". " + p.description);
            }
            else
            {
                GUILayout.Label("<b>" + t.DisplayName + "</b>", _sLabel);
            }
            Section("PROPELLER");
            GUILayout.Label(string.Format("{0}{1} blades, {2:F2} m, {3:N0} rpm{4}", t.isContraRotating ? "2 x " : "", t.bladeCount,
                t.propDiameter, m.maxPropRPM, t.isContraRotating ? ", contra-rotating (no torque)" : ""), _sLabel);
            Section("FUEL");
            GUILayout.Label(string.Format("{0}, about {1:N0} L/h at full power", m.fuelResourceName,
                PerformanceModel.FuelLitresPerHour(m.aje.bsfc, m.shaftPowerHP, m.fuelResourceName)), _sLabel);
            if (m.wepMultiplier > 1.001f)
            {
                Section("WAR EMERGENCY POWER");
                GUILayout.Label(string.Format("+{0:F0}% power for up to 5 minutes", (m.wepMultiplier - 1f) * 100f), _sLabel);
            }
        }

        // ================================================================ performance panel

        private void DrawPerformancePanel(bool editor)
        {
            Aspects now = Measure(_target);
            GUILayout.BeginVertical(_sPanel, GUILayout.Width(SideW), GUILayout.ExpandHeight(true));
            GUILayout.Label("PERFORMANCE", _sSection);
            if (editor)
                GUILayout.Label("Changes since you opened the workshop", _sSmall);

            for (int i = 0; i < AspectNames.Length; i++)
            {
                GUILayout.BeginHorizontal();
                GUILayout.Label(AspectNames[i], _sLabel, GUILayout.Width(128f));
                GUILayout.Label(Format(i, Get(now, i)), _sValue);
                GUILayout.EndHorizontal();
                if (editor)
                {
                    string w = _start.valid ? ChangeWords(i, Get(_start, i), Get(now, i)) : null;
                    GUILayout.Label(w ?? "<color=#5d6874>no change</color>", _sSmall);
                }
                GUILayout.Space(1f);
            }

            if (editor)
            {
                GUILayout.Space(6f);
                GUILayout.Label("LAST CHANGE", _sSection);
                GUILayout.Label(string.IsNullOrEmpty(_changeText) ? "Change something to see what it does to the engine." : _changeText, _sBox);
            }

            List<string> notes = Warnings();
            if (notes.Count > 0)
            {
                GUILayout.Space(4f);
                for (int i = 0; i < notes.Count; i++)
                    GUILayout.Label(notes[i], _sSmall);
            }
            GUILayout.EndVertical();
        }

        private List<string> Warnings()
        {
            List<string> notes = new List<string>();
            PropellerPerformanceMetrics m = _target.CurrentMetrics;
            if (m.staticTipMach > 0.92f)
                notes.Add("<color=#ff8a7a>Propeller tips are supersonic: use a smaller propeller or more blades.</color>");
            float area = 0.25f * Mathf.PI * _target.propDiameter * _target.propDiameter;
            if (m.shaftPowerHP * 0.7457f / Mathf.Max(0.5f, area) > 220f && !_target.isContraRotating)
                notes.Add("<color=#ffd966>The propeller is very heavily loaded: a bigger one, more blades or contra-rotation would pull harder.</color>");
            if (_target.propDamaged)
                notes.Add("<color=#ff8a7a>The propeller is broken from a ground strike.</color>");
            return notes;
        }

        // ================================================================ widgets

        private void Section(string title)
        {
            GUILayout.Space(6f);
            GUILayout.Label(title, _sSection);
        }

        private void Hint(string text)
        {
            GUILayout.Label(text, _sSmall);
        }

        /// <summary>Slider with -/+ buttons. Returns a new value only when the user moved it.</summary>
        private float Slider(float value, float min, float max, float step, string fmt, string tooltip)
        {
            GUILayout.BeginHorizontal();
            float v = value;
            bool moved = false;
            if (GUILayout.Button(new GUIContent("-", tooltip), _sBtn, GUILayout.Width(26f), GUILayout.Height(22f)))
            {
                v -= step;
                moved = true;
            }
            float s = GUILayout.HorizontalSlider(v, min, max, HighLogic.Skin.horizontalSlider, HighLogic.Skin.horizontalSliderThumb,
                GUILayout.ExpandWidth(true), GUILayout.Height(22f));
            if (Mathf.Abs(s - v) > 1e-5f)
            {
                v = s;
                moved = true;
            }
            if (GUILayout.Button(new GUIContent("+", tooltip), _sBtn, GUILayout.Width(26f), GUILayout.Height(22f)))
            {
                v += step;
                moved = true;
            }
            if (moved)
                v = Mathf.Clamp(Mathf.Round(v / step) * step, min, max);
            GUILayout.Label(new GUIContent(string.Format(fmt, moved ? v : value), tooltip), _sValue, GUILayout.Width(92f));
            GUILayout.EndHorizontal();
            return moved ? v : value;
        }

        private int ButtonRow(string[] options, string[] tooltips, int selected, float height)
        {
            GUILayout.BeginHorizontal();
            int result = selected;
            for (int i = 0; i < options.Length; i++)
            {
                GUIContent c = new GUIContent(options[i], tooltips != null && i < tooltips.Length ? tooltips[i] : "");
                if (GUILayout.Button(c, i == selected ? _sBtnOn : _sBtn, GUILayout.Height(height)))
                    result = i;
            }
            GUILayout.EndHorizontal();
            return result;
        }

        private void Gauge(string label, float value, float max, string text, Texture2D fill)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(label, _sLabel, GUILayout.Width(96f));
            Rect r = GUILayoutUtility.GetRect(120f, 22f, GUILayout.ExpandWidth(true), GUILayout.Height(22f));
            GUI.DrawTexture(r, _tBarBg);
            GUI.DrawTexture(new Rect(r.x, r.y, r.width * Mathf.Clamp01(value / Mathf.Max(1e-3f, max)), r.height), fill);
            GUI.Label(new Rect(r.x + 6f, r.y, r.width - 6f, r.height), text, _sLabel);
            GUILayout.EndHorizontal();
            GUILayout.Space(3f);
        }

        // ================================================================ audio preview

        private void StartPreview()
        {
            if (GameDatabase.Instance == null || _target == null)
                return;
            StopPreview();
            ModuleProceduralPropeller t = _target;
            if (_prevAudio == null)
            {
                _prevAudio = new PropellerAudio();
                _prevAudio.InitPreview(transform);
            }
            _prevAudio.Configure(t, t.CurrentMetrics);
            _prevSeq = new EngineStartSequence();
            _prevSeq.Configure(t, t.CurrentMetrics);
            _prevSeq.Warmth = 0f; // a cold start on the flight line
            _prevTime = 0f;
            _prevRunTime = -1f;
            _prevOffTime = -1f;
            _prevRPM = 0f;
            _prevLoad = 0f;
            _prevIgnition = true;
        }

        /// <summary>
        /// Plays the engine's real start sequence through the flight mixer, with a simple propeller
        /// model standing in for AJE: once running it idles 3 s, opens up over 2 s, holds full power
        /// for 4 s, chops the throttle for 4 s (overrun, afterfire), then shuts down.
        /// </summary>
        private void UpdatePreview(float dt)
        {
            if (_prevTime < 0f || _prevAudio == null || _prevSeq == null)
                return;
            if (_target == null || dt <= 0f)
            {
                if (_target == null) StopPreview();
                return;
            }
            dt = Mathf.Min(dt, 0.1f);
            _prevTime += dt;
            ModuleProceduralPropeller t = _target;
            PropellerPerformanceMetrics m = t.CurrentMetrics;
            bool turbo = t.IsTurboprop;

            if (_prevSeq.Phase == EnginePhase.Running && _prevRunTime < 0f)
                _prevRunTime = 0f;
            if (_prevRunTime >= 0f)
                _prevRunTime += dt;
            float rt = _prevRunTime;
            float throttle = 0f;
            if (rt >= 3f && rt < 5f) throttle = (rt - 3f) / 2f;
            else if (rt >= 5f && rt < 9f) throttle = 1f;
            if (rt >= 13f && _prevIgnition)
            {
                _prevIgnition = false;
                _prevOffTime = 0f;
            }

            _prevSeq.Tick(dt, _prevIgnition, _prevRPM);
            float maxRPM = Mathf.Max(200f, m.maxPropRPM);
            if (_prevSeq.Starting)
            {
                _prevRPM = _prevSeq.SeqPropRPM;
            }
            else if (_prevSeq.Phase == EnginePhase.Running)
            {
                float target = Mathf.Lerp(_prevSeq.IdlePropRPM, maxRPM, Mathf.Clamp01(throttle * 1.5f));
                _prevRPM += (target - _prevRPM) * (1f - Mathf.Exp(-dt / (turbo ? 1.6f : 0.9f)));
            }
            else
            {
                float aero = turbo ? 0f : 0.15f * _prevRPM;
                _prevRPM = Mathf.Max(0f, _prevRPM - (_prevSeq.OffDecel(_prevRPM) + aero) * dt);
            }
            float loadTarget = _prevSeq.Phase == EnginePhase.Running ? throttle : 0f;
            _prevLoad += (loadTarget - _prevLoad) * (1f - Mathf.Exp(-dt / (turbo ? 1.0f : 0.25f)));

            _prevAudio.OnSequenceEvents(_prevSeq.TakeEvents());

            EngineSoundInput si = new EngineSoundInput();
            si.phase = _prevSeq.Phase;
            si.propRPM = _prevRPM;
            si.engineRPM = turbo ? 0f : _prevRPM / Mathf.Max(0.05f, _prevSeq.GearRatio);
            si.coreN = _prevSeq.CoreN;
            si.firing = _prevSeq.Firing;
            si.starter = _prevSeq.Starter;
            si.starterEngaged = _prevSeq.StarterEngaged;
            si.igniters = _prevSeq.Igniters;
            si.load = _prevSeq.Starting ? 0.1f * _prevSeq.Firing : _prevLoad;
            si.roughness = _prevSeq.Roughness;
            si.pressure = 1f;
            si.tipMach = Mathf.PI * t.propDiameter * _prevRPM / 60f / 340f;
            bool blower = !turbo && t.aspirationIndex != (int)AspirationType.NaturallyAspirated;
            si.boost = blower && _prevSeq.Phase == EnginePhase.Running ? Mathf.Clamp01(0.15f + 0.6f * _prevLoad) : 0f;
            si.boostPitch = 1f;
            _prevAudio.Tick(dt, si);
            _prevAudio.TakePops();

            if (_prevOffTime >= 0f)
            {
                _prevOffTime += dt;
                if (_prevOffTime > (turbo ? 10f : 5f))
                    StopPreview();
            }
        }

        private void StopPreview()
        {
            _prevTime = -1f;
            if (_prevAudio != null)
                _prevAudio.StopAll();
        }

        // ================================================================ styles

        private Texture2D Tex(float r, float g, float b, float a)
        {
            Texture2D t = new Texture2D(1, 1, TextureFormat.RGBA32, false);
            t.SetPixel(0, 0, new Color(r, g, b, a));
            t.Apply();
            _ownedTex.Add(t);
            return t;
        }

        private GUIStyle Button(Texture2D normal, Texture2D hover, Color text, bool bold, int fontSize)
        {
            GUIStyle s = new GUIStyle(HighLogic.Skin.button);
            s.normal.background = normal;
            s.hover.background = hover;
            s.active.background = hover;
            s.focused.background = normal;
            s.onNormal.background = normal;
            s.onHover.background = hover;
            s.onActive.background = hover;
            s.normal.textColor = text;
            s.hover.textColor = text;
            s.active.textColor = text;
            s.fontSize = fontSize;
            s.fontStyle = bold ? FontStyle.Bold : FontStyle.Normal;
            s.border = new RectOffset(0, 0, 0, 0);
            s.margin = new RectOffset(2, 2, 2, 2);
            s.padding = new RectOffset(8, 8, 4, 4);
            s.richText = true;
            s.wordWrap = true;
            return s;
        }

        private void InitStyles()
        {
            if (_stylesReady)
                return;
            _stylesReady = true;

            _tBg = Tex(0.065f, 0.078f, 0.098f, 0.97f);
            _tPanel = Tex(0.095f, 0.112f, 0.138f, 1f);
            _tCard = Tex(0.13f, 0.152f, 0.185f, 1f);
            _tCardHover = Tex(0.17f, 0.20f, 0.245f, 1f);
            _tCardSel = Tex(0.36f, 0.22f, 0.07f, 1f);
            _tAccent = Tex(Accent.r, Accent.g, Accent.b, 1f);
            _tBarBg = Tex(0.17f, 0.20f, 0.24f, 1f);
            _tBtn = Tex(0.16f, 0.19f, 0.23f, 1f);
            _tBtnHover = Tex(0.23f, 0.27f, 0.32f, 1f);
            _tBtnOn = Tex(0.88f, 0.52f, 0.14f, 1f);
            _tHeader = Tex(0.045f, 0.055f, 0.07f, 1f);
            _tWhite = Tex(1f, 1f, 1f, 1f);
            _tCyan = Tex(0.30f, 0.62f, 0.80f, 1f);
            _tGreen = Tex(0.35f, 0.70f, 0.42f, 1f);
            _tRed = Tex(0.85f, 0.32f, 0.28f, 1f);
            _tBox = Tex(0.12f, 0.16f, 0.20f, 1f);

            _sWindow = new GUIStyle(HighLogic.Skin.window);
            _sWindow.normal.background = _tBg;
            _sWindow.onNormal.background = _tBg;
            _sWindow.border = new RectOffset(0, 0, 0, 0);
            _sWindow.padding = new RectOffset(12, 12, 10, 8);

            _sHeaderBar = new GUIStyle();
            _sHeaderBar.normal.background = _tHeader;
            _sHeaderBar.padding = new RectOffset(12, 8, 4, 4);

            _sTitle = new GUIStyle(HighLogic.Skin.label);
            _sTitle.fontSize = 18;
            _sTitle.fontStyle = FontStyle.Bold;
            _sTitle.normal.textColor = Accent;
            _sTitle.richText = true;

            _sSubtitle = new GUIStyle(HighLogic.Skin.label);
            _sSubtitle.fontSize = 12;
            _sSubtitle.normal.textColor = new Color(0.62f, 0.70f, 0.78f);

            _sSection = new GUIStyle(HighLogic.Skin.label);
            _sSection.fontSize = 12;
            _sSection.fontStyle = FontStyle.Bold;
            _sSection.normal.textColor = new Color(0.55f, 0.68f, 0.82f);
            _sSection.margin = new RectOffset(2, 2, 6, 2);

            _sLabel = new GUIStyle(HighLogic.Skin.label);
            _sLabel.fontSize = 13;
            _sLabel.normal.textColor = new Color(0.90f, 0.92f, 0.95f);
            _sLabel.richText = true;
            _sLabel.wordWrap = true;

            _sSmall = new GUIStyle(_sLabel);
            _sSmall.fontSize = 11;
            _sSmall.normal.textColor = new Color(0.64f, 0.70f, 0.77f);

            _sHint = new GUIStyle(_sSmall);
            _sHint.fontStyle = FontStyle.Italic;
            _sHint.normal.textColor = new Color(0.75f, 0.80f, 0.86f);
            _sHint.wordWrap = false;

            _sValue = new GUIStyle(_sLabel);
            _sValue.fontStyle = FontStyle.Bold;
            _sValue.alignment = TextAnchor.MiddleRight;
            _sValue.wordWrap = false;

            _sPanel = new GUIStyle();
            _sPanel.normal.background = _tPanel;
            _sPanel.padding = new RectOffset(10, 10, 8, 10);

            _sBox = new GUIStyle(_sLabel);
            _sBox.normal.background = _tBox;
            _sBox.padding = new RectOffset(8, 8, 6, 6);
            _sBox.fontSize = 12;

            _sCard = Button(_tCard, _tCardHover, new Color(0.92f, 0.94f, 0.96f), false, 13);
            _sCard.alignment = TextAnchor.UpperLeft;
            _sCard.padding = new RectOffset(10, 8, 6, 6);
            _sCard.margin = new RectOffset(0, 6, 0, 6);
            _sCardSel = new GUIStyle(_sCard);
            _sCardSel.normal.background = _tCardSel;
            _sCardSel.hover.background = _tCardSel;

            _sRow = new GUIStyle(_sCard);
            _sRow.alignment = TextAnchor.MiddleLeft;
            _sRow.margin = new RectOffset(0, 0, 0, 3);
            _sRow.padding = new RectOffset(10, 8, 3, 3);

            _sBtn = Button(_tBtn, _tBtnHover, new Color(0.90f, 0.92f, 0.95f), false, 12);
            _sBtnOn = Button(_tBtnOn, _tBtnOn, new Color(0.08f, 0.06f, 0.03f), true, 12);
            _sTab = Button(_tBtn, _tBtnHover, new Color(0.80f, 0.84f, 0.90f), true, 13);
            _sTabOn = Button(_tAccent, _tAccent, new Color(0.08f, 0.06f, 0.03f), true, 13);
        }
    }
}
