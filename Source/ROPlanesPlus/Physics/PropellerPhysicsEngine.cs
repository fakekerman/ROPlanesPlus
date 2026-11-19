using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>Values pushed into AJE's ModuleEnginesAJEPropeller (inHg, cu in, HP, m).</summary>
    public class AJEParameters
    {
        public double power;
        public double displacement;
        public double compression;
        public double minRPM;
        public double maxRPM;
        public double gearRatio;
        public double bsfc;
        public double coolerEffic;
        public double coolerMin;
        public double ramAir;
        public double exhaustThrust;
        public double meredithEffect;
        public double boost0;
        public double rated0;
        public double boost1;
        public double rated1;
        public double cost1;
        public double switchAlt;
        public bool turbo;
        public double wastegateMP;
        public string propName;
        public double propDiam;
        public float ctTweak;
        public float cpTweak;
    }

    public struct PropellerPerformanceMetrics
    {
        public AJEParameters aje;
        public float shaftPowerHP;
        public float wepMultiplier;
        public float effectiveGearRatio;
        public float maxPropRPM;
        public float minPropRPM;
        public float staticTipMach;
        public float staticThrustKn;
        public float residualJetThrustKn;
        public float sfcLbPerHpHr;
        public float criticalAltitudeKm;
        public float dryMassTons;
        public float partCostFunds;
        public string fuelResourceName;
        public float integratedFuelLiters;
    }

    public struct PropellerLiveState
    {
        public float propRPM;
        public float bladePitchDeg;
        public float shaftHP;
        public float manifoldInHg;
        public int boostMode;      // supercharger gear / stage AJE is using (0 low, 1 high)
        public bool hasData;
    }

    /// <summary>
    /// Cached reflection access to AJE's ModuleEnginesAJEPropeller. AJE is never referenced at
    /// compile time, so the DLL loads fine without it.
    /// </summary>
    public class AJEBridge
    {
        private const BindingFlags Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        private readonly ModuleEngines _eng;
        private readonly Type _type;
        private readonly Dictionary<string, FieldInfo> _fields = new Dictionary<string, FieldInfo>();
        private readonly MethodInfo _createEngine;
        private readonly MethodInfo _setUnits;
        private readonly FieldInfo _solverPropField;
        private readonly FieldInfo _pistonField;

        private object _cachedSolver;
        private object _cachedJsb;
        private MethodInfo _solverSetTweaks;
        private MethodInfo _jsbSetFeather;
        private FieldInfo _jsbFeathered;
        private FieldInfo _jsbRPM;
        private FieldInfo _solverPropRPM;
        private FieldInfo _boostModeField;

        public bool Valid { get { return _eng != null && _type != null; } }

        public static bool IsAJEPropeller(ModuleEngines eng)
        {
            return eng != null && string.Equals(eng.GetType().Name, "ModuleEnginesAJEPropeller", StringComparison.Ordinal);
        }

        public AJEBridge(ModuleEngines eng)
        {
            if (!IsAJEPropeller(eng))
                return;
            _eng = eng;
            _type = eng.GetType();
            _createEngine = _type.GetMethod("CreateEngine", Flags, null, Type.EmptyTypes, null);
            _setUnits = _type.GetMethod("SetUnits", Flags, null, Type.EmptyTypes, null);
            _solverPropField = _type.GetField("solverProp", Flags);
            _pistonField = _type.GetField("pistonEngine", Flags);
        }

        private FieldInfo Field(string name)
        {
            FieldInfo fi;
            if (!_fields.TryGetValue(name, out fi))
            {
                fi = _type.GetField(name, Flags);
                _fields[name] = fi;
            }
            return fi;
        }

        public void Set(string name, double value)
        {
            FieldInfo fi = Field(name);
            if (fi == null) return;
            if (fi.FieldType == typeof(double)) fi.SetValue(_eng, value);
            else if (fi.FieldType == typeof(float)) fi.SetValue(_eng, (float)value);
            else if (fi.FieldType == typeof(int)) fi.SetValue(_eng, (int)Math.Round(value));
        }

        public void Set(string name, bool value)
        {
            FieldInfo fi = Field(name);
            if (fi != null && fi.FieldType == typeof(bool))
                fi.SetValue(_eng, value);
        }

        public void Set(string name, string value)
        {
            FieldInfo fi = Field(name);
            if (fi != null && fi.FieldType == typeof(string))
                fi.SetValue(_eng, value);
        }

        public float GetFloat(string name)
        {
            FieldInfo fi = Field(name);
            if (fi == null) return 0f;
            object o = fi.GetValue(_eng);
            if (o is float) return (float)o;
            if (o is double) return (float)(double)o;
            return 0f;
        }

        public void Rebuild()
        {
            if (_setUnits != null)
                _setUnits.Invoke(_eng, null);
            if (_createEngine != null)
                _createEngine.Invoke(_eng, null);
            _cachedSolver = null;
            _cachedJsb = null;
        }

        private object Solver()
        {
            if (_solverPropField == null) return null;
            object s = _solverPropField.GetValue(_eng);
            if (s != _cachedSolver)
            {
                _cachedSolver = s;
                _cachedJsb = null;
                _solverSetTweaks = null;
                _solverPropRPM = null;
                _jsbRPM = null;
                if (s != null)
                {
                    Type st = s.GetType();
                    _solverSetTweaks = st.GetMethod("SetTweaks", Flags);
                    _solverPropRPM = st.GetField("propRPM", Flags);
                    FieldInfo jf = st.GetField("propJSB", Flags);
                    _cachedJsb = jf != null ? jf.GetValue(s) : null;
                    if (_cachedJsb != null)
                    {
                        Type jt = _cachedJsb.GetType();
                        _jsbSetFeather = jt.GetMethod("SetFeather", Flags);
                        _jsbFeathered = jt.GetField("Feathered", Flags);
                        _jsbRPM = jt.GetField("RPM", Flags);
                    }
                }
            }
            return s;
        }

        /// <summary>Pushes Ct/Cp/VE tweaks to both the module fields and the live solver.</summary>
        public void ApplyTweaks(float ctTweak, float cpTweak, float volETweak)
        {
            Set("CtTweak", ctTweak);
            Set("CpTweak", cpTweak);
            Set("VolETweak", volETweak);
            object s = Solver();
            if (s != null && _solverSetTweaks != null)
            {
                float mach = GetFloat("MachPowTweak");
                if (mach <= 0f) mach = 1f;
                try
                {
                    _solverSetTweaks.Invoke(s, new object[] { (double)ctTweak, (double)cpTweak, (double)volETweak, (double)mach });
                }
                catch (Exception)
                {
                    // Signature differs in this AJE build; module fields are still set.
                }
            }
        }

        public void SetFeather(bool feathered)
        {
            Solver();
            if (_cachedJsb == null || _jsbSetFeather == null)
                return;
            if (_jsbFeathered != null)
            {
                object cur = _jsbFeathered.GetValue(_cachedJsb);
                if (cur is bool && (bool)cur == feathered)
                    return;
            }
            _jsbSetFeather.Invoke(_cachedJsb, new object[] { feathered });
        }

        /// <summary>
        /// Sets the propeller speed AJE integrates from (its JSBSim propeller keeps RPM as state and
        /// accelerates it with the shaft torque). Used while the engine is starting, idling with the
        /// throttle closed (AJE treats that as magnetos off) and stopping (AJE has no engine friction).
        /// </summary>
        public void SetPropRPM(float rpm)
        {
            object s = Solver();
            if (s == null)
                return;
            double v = Math.Max(0.0, rpm);
            if (_jsbRPM != null && _cachedJsb != null && _jsbRPM.FieldType == typeof(double))
                _jsbRPM.SetValue(_cachedJsb, v);
            if (_solverPropRPM != null && _solverPropRPM.FieldType == typeof(double))
                _solverPropRPM.SetValue(s, v);
            Set("propRPM", v);
        }

        private int BoostMode()
        {
            if (_pistonField == null)
                return 0;
            object pe = _pistonField.GetValue(_eng);
            if (pe == null)
                return 0;
            if (_boostModeField == null || _boostModeField.DeclaringType != pe.GetType())
                _boostModeField = pe.GetType().GetField("_boostMode", Flags);
            object v = _boostModeField != null ? _boostModeField.GetValue(pe) : null;
            return v is int ? (int)v : 0;
        }

        public PropellerLiveState ReadLiveState()
        {
            PropellerLiveState s = new PropellerLiveState();
            s.propRPM = GetFloat("propRPM");
            s.bladePitchDeg = GetFloat("propPitch");
            s.shaftHP = GetFloat("brakeShaftPower");
            s.manifoldInHg = GetFloat("manifoldPressure");
            s.boostMode = BoostMode();
            s.hasData = true;
            return s;
        }
    }

    public static class PropellerPhysicsEngine
    {
        private const float HPToWatts = 745.699872f;
        private const float SeaLevelSpeedOfSound = 340.29f;
        private const float G0 = 9.80665f;

        private static bool _checkedMods = false;
        private static bool _hasAJE = false;
        private static bool _hasFAR = false;

        public static bool HasAJE { get { EnsureChecked(); return _hasAJE; } }
        public static bool HasFAR { get { EnsureChecked(); return _hasFAR; } }

        public static void EnsureChecked()
        {
            if (_checkedMods || AssemblyLoader.loadedAssemblies == null)
                return;

            for (int i = 0; i < AssemblyLoader.loadedAssemblies.Count; i++)
            {
                AssemblyLoader.LoadedAssembly asm = AssemblyLoader.loadedAssemblies[i];
                if (asm == null || string.IsNullOrEmpty(asm.name))
                    continue;
                if (string.Equals(asm.name, "AJE", StringComparison.OrdinalIgnoreCase))
                    _hasAJE = true;
                else if (string.Equals(asm.name, "FerramAerospaceResearch", StringComparison.OrdinalIgnoreCase))
                    _hasFAR = true;
            }
            _checkedMods = true;
        }

        // Blade count of each AJE propeller table we use (from AJE/Propellers.cfg)
        private static int TableBlades(string propName)
        {
            switch (propName)
            {
                case "81in2CS": return 2;
                case "RotolRX5":
                case "RotolRX5HiSpd":
                case "VISh-105V-4":
                case "JSBJug":
                case "Curtiss12-2x3": return 3;
                case "GriffonProp":
                case "4mHighAltx5": return 5;
                default: return 4;
            }
        }

        private static string TableForBlades(int totalBlades)
        {
            if (totalBlades <= 2) return "81in2CS";
            if (totalBlades == 3) return "RotolRX5";
            if (totalBlades == 4) return "HS6501A-0x4";
            return "4mHighAltx5";
        }

        /// <summary>Typical sea-level boost for each supercharger type (inHg).</summary>
        public static float DefaultBoostInHg(AspirationType asp)
        {
            switch (asp)
            {
                case AspirationType.NaturallyAspirated: return 29.92f;
                case AspirationType.SingleStage1Speed: return 46f;
                case AspirationType.SingleStage2Speed: return 52f;
                case AspirationType.TwoStageIntercooled: return 61f;
                case AspirationType.Turbosupercharged: return 56f;
                default: return 59.5f;
            }
        }

        /// <summary>Boost (manifold pressure, inHg) a supercharger type can be set to.</summary>
        public static void BoostRange(AspirationType asp, out float min, out float max)
        {
            switch (asp)
            {
                case AspirationType.NaturallyAspirated: min = 29.92f; max = 29.92f; break;
                case AspirationType.SingleStage1Speed: min = 36f; max = 56f; break;
                case AspirationType.SingleStage2Speed: min = 40f; max = 66f; break;
                case AspirationType.TwoStageIntercooled: min = 48f; max = 90f; break;
                case AspirationType.Turbosupercharged: min = 40f; max = 75f; break;
                default: min = 45f; max = 75f; break;
            }
        }

        /// <summary>The design's boost: the chosen value (clamped to the supercharger's range) or the type's default.</summary>
        public static float EffectiveBoostInHg(ModuleProceduralPropeller m)
        {
            AspirationType asp = (AspirationType)Mathf.Clamp(m.aspirationIndex, 0, 5);
            if (asp == AspirationType.NaturallyAspirated || m.boostInHg <= 0f)
                return DefaultBoostInHg(asp);
            float min, max;
            BoostRange(asp, out min, out max);
            return Mathf.Clamp(m.boostInHg, min, max);
        }

        // ---------------------------------------------------------------- cylinders

        public const float MinCylinderLitres = 0.8f;   // small 5/7-cylinder radials, light inlines
        public const float MaxCylinderLitres = 5.0f;   // Lycoming XR-7755 class
        public const float MaxPistonHP = 6000f;
        private const float CuInPerLitre = 61.0237f;
        private const float StrokeToBore = 1.08f;      // typical of WW2 aero engines

        /// <summary>Rows of a radial (1, 2 or 4) or banks of an inline (2 for a V, 4 for an X).</summary>
        public static int CylinderRows(int arch, int subStyle)
        {
            if (arch == (int)EngineArchitecture.Radial)
                return subStyle == 1 ? 1 : (subStyle == 2 ? 4 : 2);
            if (arch == (int)EngineArchitecture.VInline)
                return subStyle == 2 ? 4 : 2;
            return 0;
        }

        /// <summary>Choices for cylinders per row (radial) or per bank (inline).</summary>
        public static int[] CylinderOptions(int arch)
        {
            if (arch == (int)EngineArchitecture.Radial)
                return new int[] { 5, 7, 9 };
            if (arch == (int)EngineArchitecture.VInline)
                return new int[] { 4, 6, 8 };
            return new int[0];
        }

        public static int DefaultCylindersPerRow(int arch, int subStyle)
        {
            if (arch == (int)EngineArchitecture.Radial)
                return subStyle == 2 ? 7 : 9;
            if (arch == (int)EngineArchitecture.VInline)
                return 6;
            return 0;
        }

        /// <summary>Resolves a stored per-row/bank count (0 or invalid = the layout's default).</summary>
        public static int ResolveCylindersPerRow(int arch, int subStyle, int stored)
        {
            int[] opts = CylinderOptions(arch);
            for (int i = 0; i < opts.Length; i++)
                if (opts[i] == stored)
                    return stored;
            return DefaultCylindersPerRow(arch, subStyle);
        }

        public static int CylindersPerRow(ModuleProceduralPropeller m)
        {
            return ResolveCylindersPerRow(m.architectureIndex, m.subStyleIndex, m.cylindersPerRow);
        }

        public static int CylinderCount(ModuleProceduralPropeller m)
        {
            return CylinderRows(m.architectureIndex, m.subStyleIndex) * CylindersPerRow(m);
        }

        /// <summary>
        /// Power of a custom piston engine from its swept volume, using the same relation that sizes
        /// custom engines for AJE: hp = 5.2e-6 x MAP(inHg) x RPM x cu in (fits R-2800, Merlin, R-1820, Jumo 213).
        /// </summary>
        public static float PowerFromLitres(ModuleProceduralPropeller m, float litresPerCylinder)
        {
            float mp = EffectiveBoostInHg(m);
            float rpm = Mathf.Clamp(m.maxEngineRPM, 1800f, 3400f);
            return 5.2e-6f * mp * rpm * CylinderCount(m) * litresPerCylinder * CuInPerLitre;
        }

        public static float LitresFromPower(ModuleProceduralPropeller m, float hp)
        {
            float per = PowerFromLitres(m, 1f);
            return per > 1f ? hp / per : 2f;
        }

        /// <summary>Litres per cylinder the engine actually has (preset: AJE displacement; custom: the design value).</summary>
        public static float CylinderLitres(ModuleProceduralPropeller m, AJEParameters a)
        {
            int cyl = CylinderCount(m);
            if (cyl <= 0)
                return 0f;
            if (a != null && a.displacement > 1.0)
                return (float)a.displacement / CuInPerLitre / cyl;
            return m.cylinderLitres > 0f ? m.cylinderLitres : LitresFromPower(m, m.shaftPowerHP);
        }

        /// <summary>
        /// Highest crankshaft speed a cylinder of this size can run: mean piston speed limited to
        /// ~17 m/s like the best WW2 engines (Merlin 66: 15.2 m/s at 3000 rpm), so big cylinders
        /// must turn slower.
        /// </summary>
        public static float PistonSpeedLimitRPM(float litres)
        {
            float bore, stroke;
            BoreStroke(litres, out bore, out stroke);
            return Mathf.Clamp(Mathf.Floor(17f * 60f / (2f * stroke) / 50f) * 50f, 1800f, 3400f);
        }

        /// <summary>Bore and stroke (m) of a cylinder of this size.</summary>
        public static void BoreStroke(float litres, out float bore, out float stroke)
        {
            float dm = Mathf.Pow(4f * Mathf.Max(0.1f, litres) / (Mathf.PI * StrokeToBore), 1f / 3f);
            bore = dm * 0.1f;
            stroke = bore * StrokeToBore;
        }

        /// <summary>
        /// Bare engine width (m), from a simple layout model: radial diameter grows with the stroke
        /// (cylinder length) and with crowding of the crankcase; a 60-degree V is as wide as one
        /// cylinder's deck height plus a bore; an X is wider still. Checked against R-985 (0.98 m),
        /// R-2800 (1.32), R-1820 (1.38), Merlin (0.78) and DB 605 (0.76).
        /// </summary>
        public static float EngineWidth(ModuleProceduralPropeller m, AJEParameters a)
        {
            int arch = m.architectureIndex;
            float bore, stroke;
            BoreStroke(CylinderLitres(m, a), out bore, out stroke);
            if (arch == (int)EngineArchitecture.Radial)
            {
                int perRow = CylindersPerRow(m);
                float crowd = perRow <= 5 ? 0.88f : (perRow <= 7 ? 0.96f : 1f);
                return (0.24f + 6.3f * stroke) * crowd;
            }
            float deck = 2.9f * stroke + 0.5f * bore;
            float spread = m.subStyleIndex == 2 ? 1.414f : 1f;
            return spread * deck + bore + 0.10f;
        }

        public static readonly string[] CowlFitNames = new string[] { "Tight", "Standard", "Roomy" };

        /// <summary>
        /// Cowling that fits the engine. Pistons: from the bare engine width (EngineWidth) plus a
        /// clearance set by the fit (tight: Bf 109 / Spitfire / Fw 190 style, the cowl hugging the
        /// cylinders; standard; roomy: room for oil coolers and ducts). Length from rows/banks and
        /// bore. Turboprops scale with sqrt(shp).
        /// </summary>
        public static void AutoCowl(ModuleProceduralPropeller m, AJEParameters a, int fit, out float dia, out float len)
        {
            int arch = m.architectureIndex;
            int sub = m.subStyleIndex;
            fit = Mathf.Clamp(fit, 0, 2);
            if (arch == (int)EngineArchitecture.Turboprop || a == null)
            {
                float s = Mathf.Sqrt(Mathf.Max(1f, m.shaftPowerHP) / 100f);
                dia = 0.50f + 0.068f * s;
                len = 1.25f + 0.125f * s;
                if (sub == 2) dia *= 0.92f;
                dia *= fit == 0 ? 0.92f : (fit == 2 ? 1.1f : 1f);
            }
            else
            {
                float bore, stroke;
                BoreStroke(CylinderLitres(m, a), out bore, out stroke);
                float width = EngineWidth(m, a);
                int rows = CylinderRows(arch, sub);
                int perRow = CylindersPerRow(m);
                if (arch == (int)EngineArchitecture.Radial)
                {
                    dia = width + (fit == 0 ? 0.02f : (fit == 1 ? 0.07f : 0.16f));
                    len = 1.05f + rows * bore * 1.65f;
                }
                else
                {
                    dia = width + (fit == 0 ? 0.13f : (fit == 1 ? 0.25f : 0.40f));
                    len = 0.75f + perRow * bore * 1.30f + (sub == 2 ? 0.35f : 0f);
                }
            }
            if (m.isContraRotating)
                len += 0.15f;
            dia = Mathf.Clamp(dia, 0.5f, 2.6f);
            len = Mathf.Clamp(len, 0.6f, 4.0f);
        }

        /// <summary>
        /// Weight of a custom engine: dry engine (specific weights fitted to the presets: radials
        /// ~0.47 kg/hp, inline V-12 ~0.38 kg/hp + cooling, turboprops ~0.18 kg/shp), supercharger or
        /// turbo hardware, the propeller (blades scale ~D^2.4, hubs ~D^2) and a contra gearbox.
        /// </summary>
        public static float CustomMassTons(ModuleProceduralPropeller m, float hp, float propD, int totalBlades)
        {
            float engine;
            int arch = m.architectureIndex;
            if (arch == (int)EngineArchitecture.Turboprop)
            {
                engine = 0.02f + 0.000175f * hp;
            }
            else
            {
                // Crankcase, cylinders and crank scale with swept volume (~18 kg/L across R-1820,
                // R-2800, R-4360, Merlin, Griffon, DB 605); reduction gear and accessories with power.
                // So a high-boost, high-rpm engine is light for its power, a big lazy one heavy.
                // Inlines carry coolant, header tank and radiator.
                float litres = CylinderLitres(m, null) * CylinderCount(m);
                engine = (arch == (int)EngineArchitecture.Radial ? 0.020f : 0.070f) + 0.018f * litres + 0.00012f * hp;
            }

            if (arch != (int)EngineArchitecture.Turboprop)
            {
                AspirationType asp = (AspirationType)Mathf.Clamp(m.aspirationIndex, 0, 5);
                if (asp == AspirationType.Turbosupercharged || asp == AspirationType.TurboCompound)
                    engine += 0.03f * hp / 1000f;
                else if (asp == AspirationType.TwoStageIntercooled)
                    engine += 0.015f * hp / 1000f;
            }

            int hubs = m.isContraRotating ? 2 : 1;
            float prop = 0.04f * totalBlades * Mathf.Pow(propD / 4f, 2.4f) + 0.04f * hubs * Mathf.Pow(propD / 4f, 2f);
            float gearbox = m.isContraRotating ? 0.06f * Mathf.Pow(hp / 2000f, 0.7f) : 0f;
            return engine + prop + gearbox;
        }

        /// <summary>
        /// Power range for the current layout: cylinders of MinCylinderLitres-MaxCylinderLitres at
        /// this boost and RPM (pistons), or the turboprop size class.
        /// </summary>
        public static void GetPowerLimits(ModuleProceduralPropeller m, out float minHP, out float maxHP, out string reason)
        {
            int arch = m.architectureIndex;
            int sub = m.subStyleIndex;
            if (arch == (int)EngineArchitecture.Turboprop)
            {
                if (sub == 2) { minHP = 300f; maxHP = 2000f; reason = "small free-turbine class"; }
                else if (sub == 1) { minHP = 2000f; maxHP = 15000f; reason = "large axial turboprop class"; }
                else { minHP = 1000f; maxHP = 8000f; reason = "medium axial turboprop class"; }
                return;
            }
            int cyl = CylinderCount(m);
            AspirationType asp = (AspirationType)Mathf.Clamp(m.aspirationIndex, 0, 5);
            float mp = EffectiveBoostInHg(m);
            float rpm = Mathf.Clamp(m.maxEngineRPM, 1800f, 3400f);
            minHP = Mathf.Max(100f, PowerFromLitres(m, MinCylinderLitres));
            maxHP = Mathf.Min(MaxPistonHP, PowerFromLitres(m, MaxCylinderLitres));
            minHP = Mathf.Min(minHP, maxHP * 0.5f);
            reason = string.Format("{0} cylinders of {1:F1}-{2:F1} L at {3:N0} rpm, {4}", cyl, MinCylinderLitres, MaxCylinderLitres, rpm,
                asp == AspirationType.NaturallyAspirated ? "no supercharger" : string.Format("{0:F0} inHg boost", mp));
        }

        /// <summary>Propeller diameter for a sensible disk loading (~120 kW/m² for four blades).</summary>
        public static float OptimalPropDiameter(float shaftHP, int totalBlades)
        {
            float loading = 120f * Mathf.Pow(Mathf.Max(2, totalBlades) / 4f, 0.7f);
            float area = shaftHP * 0.7457f / loading;
            return Mathf.Clamp(Mathf.Sqrt(4f * area / Mathf.PI), 1.2f, 6.2f);
        }

        public static PropellerPerformanceMetrics Evaluate(ModuleProceduralPropeller m)
        {
            PropellerPerformanceMetrics p = new PropellerPerformanceMetrics();
            PropellerPreset preset = m.ActivePreset;
            bool turboprop = m.IsTurboprop;
            bool contra = m.isContraRotating;
            int totalBlades = contra ? m.bladeCount * 2 : m.bladeCount;
            float propD = Mathf.Clamp(m.propDiameter, 1.1f, 6.5f);
            float hp = Mathf.Clamp(m.shaftPowerHP, 100f, 16000f);

            AJEParameters a = new AJEParameters();
            if (preset != null)
            {
                a.power = preset.shaftPowerHP;
                a.displacement = preset.displacement;
                a.compression = preset.compression;
                a.minRPM = preset.minRPM;
                a.maxRPM = preset.maxRPM;
                a.gearRatio = preset.gearRatio;
                a.bsfc = preset.bsfc;
                a.coolerEffic = preset.coolerEffic;
                a.coolerMin = preset.coolerMin;
                a.ramAir = preset.ramAir;
                a.exhaustThrust = preset.exhaustThrust;
                a.meredithEffect = preset.meredithEffect;
                a.boost0 = preset.boost0;
                a.rated0 = preset.rated0;
                a.boost1 = preset.boost1;
                a.rated1 = preset.rated1;
                a.cost1 = preset.cost1;
                a.switchAlt = preset.switchAlt;
                a.turbo = preset.turbo;
                a.wastegateMP = preset.wastegateMP;
                a.propName = preset.propName;
                a.ctTweak = preset.ctTweak;
                a.cpTweak = preset.cpTweak;
                p.wepMultiplier = preset.wepMultiplier;
                p.criticalAltitudeKm = preset.CriticalAltitudeKm;
            }
            else
            {
                DeriveCustom(m, hp, propD, turboprop, contra, a);
                p.wepMultiplier = turboprop ? 1.0f : 1.10f;
                p.criticalAltitudeKm = turboprop ? 0f : m.criticalAltitudeKm;
            }

            a.propDiam = propD;
            if (a.ctTweak <= 0f || a.cpTweak <= 0f)
            {
                // Solidity scaling against the AJE table; (3/4)^0.9 = 0.77 reproduces AJE's own
                // 3-blade tweak on the HS6501A-0x4 table (SXT Jumo 213E / Jumo 211F configs).
                float solidity = Mathf.Pow((float)totalBlades / TableBlades(a.propName), 0.9f);
                a.cpTweak = solidity;
                a.ctTweak = solidity * (contra ? PerformanceModel.ContraThrustGain(hp, propD) : 1.0f);
            }
            p.aje = a;
            p.shaftPowerHP = (float)a.power;

            // Propeller speed
            p.effectiveGearRatio = (float)a.gearRatio;
            p.maxPropRPM = (float)(a.maxRPM * a.gearRatio);
            p.minPropRPM = (float)(a.minRPM * a.gearRatio);
            float vTip = (p.maxPropRPM / 60f) * Mathf.PI * propD;
            p.staticTipMach = vTip / SeaLevelSpeedOfSound;
            p.sfcLbPerHpHr = (float)a.bsfc * HPToWatts * 3600f * 2.20462f;

            // Static thrust from the same model the Engine Workshop charts use
            p.residualJetThrustKn = turboprop ? p.shaftPowerHP * 0.00065f * (float)a.exhaustThrust : 0f;
            p.staticThrustKn = PerformanceModel.ThrustKN(p.shaftPowerHP, propD, contra, turboprop,
                a.exhaustThrust, p.maxPropRPM, 0f, 0f);

            // Mass (preset: AJE/historical figure; custom: specific weight by architecture)
            float massT;
            if (preset != null)
                massT = preset.massTons;
            else
                massT = CustomMassTons(m, hp, propD, totalBlades);
            if (m.nacelleIndex == (int)NacelleStyle.ShortWingNacelle)
                massT += 0.035f * m.cowlDiameter * m.cowlLength;
            else if (m.nacelleIndex == (int)NacelleStyle.StreamlinedTankNacelle)
                massT += 0.07f * m.cowlDiameter * m.cowlLength;
            p.dryMassTons = Mathf.Max(0.08f, massT);

            // RP-1 cost scale (RP-0 TREE-Parts.cfg, SXT AJE engines): Merlin 46 = 19, Merlin 66 = 20,
            // R-2800-18W = 24, R-2800-21 = 27, NK-12M = 400
            float cost = turboprop ? (4f + p.shaftPowerHP * 0.0267f) : (8f + p.shaftPowerHP * 0.0085f);
            if (contra && !turboprop) cost *= 1.2f; // the turboprop line is fitted to the (contra) NK-12M already
            p.partCostFunds = Mathf.Round(cost);

            // Fuel
            string fuel = turboprop ? "Kerosene" : "AvGas";
            if (PartResourceLibrary.Instance != null && PartResourceLibrary.Instance.GetDefinition(fuel) == null &&
                PartResourceLibrary.Instance.GetDefinition("LiquidFuel") != null)
                fuel = "LiquidFuel";
            p.fuelResourceName = fuel;

            float cowlArea = 0.25f * Mathf.PI * m.cowlDiameter * m.cowlDiameter;
            if (m.nacelleIndex == (int)NacelleStyle.StreamlinedTankNacelle)
                p.integratedFuelLiters = Mathf.Round(cowlArea * m.cowlLength * 0.55f * 500f);
            else if (m.nacelleIndex == (int)NacelleStyle.ShortWingNacelle)
                p.integratedFuelLiters = Mathf.Round(cowlArea * m.cowlLength * 0.25f * 350f);
            else
                p.integratedFuelLiters = 0f;

            return p;
        }

        private static void DeriveCustom(ModuleProceduralPropeller m, float hp, float propD, bool turboprop, bool contra, AJEParameters a)
        {
            float rpm = Mathf.Clamp(m.maxEngineRPM, 1500f, 3500f);
            int totalBlades = contra ? m.bladeCount * 2 : m.bladeCount;
            a.power = hp;
            a.maxRPM = rpm;
            a.propName = TableForBlades(totalBlades);
            a.ctTweak = 0f;
            a.cpTweak = 0f;

            float targetTip = turboprop ? 235f : (contra ? 240f : 250f);
            float gear = (targetTip * 60f / (Mathf.PI * propD)) / rpm;
            a.gearRatio = Math.Round(Mathf.Clamp(gear, 0.22f, 0.85f), 3);

            if (turboprop)
            {
                // Same conventions as AJE's SXT PT6 config (pseudo-displacement ~2.4-2.6 cu in/shp)
                a.displacement = 2.4 * hp;
                a.compression = 6;
                a.minRPM = 0.77 * rpm;
                a.bsfc = Mathf.Lerp(9.5e-8f, 6.8e-8f, Mathf.InverseLerp(600f, 12000f, hp));
                a.coolerEffic = 0;
                a.coolerMin = -200;
                a.ramAir = 1;
                a.exhaustThrust = 0.8;
                a.meredithEffect = 0.001;
                a.boost0 = 0; a.rated0 = 0; a.boost1 = 0; a.rated1 = 0; a.cost1 = 0;
                a.switchAlt = -1;
                a.turbo = false;
                a.wastegateMP = 52.5;
                return;
            }

            AspirationType asp = (AspirationType)Mathf.Clamp(m.aspirationIndex, 0, 5);
            double mp = EffectiveBoostInHg(m);
            double critM = Math.Max(0.0, m.criticalAltitudeKm * 1000.0);

            // hp per cu in ~= 5.2e-6 * MAP(inHg) * RPM — fits R-2800, Merlin, R-1820 and Jumo 213 in AJE
            a.displacement = Math.Round(hp / (5.2e-6 * mp * rpm));
            a.compression = 6.7;
            a.minRPM = Math.Round(0.68 * rpm);
            a.bsfc = asp == AspirationType.TurboCompound ? 7.0e-8 : (asp == AspirationType.NaturallyAspirated ? 1.10e-7 : 1.15e-7);
            // Boost above the supercharger's usual figure needs a richer mixture to keep the
            // cylinders from detonating: ~0.4 % more fuel per extra inHg
            a.bsfc *= 1.0 + 0.004 * Math.Max(0.0, mp - DefaultBoostInHg(asp));
            bool inline = m.architectureIndex == (int)EngineArchitecture.VInline;
            a.ramAir = 0.5;
            a.exhaustThrust = inline ? 1.0 : 0.3;
            a.meredithEffect = inline ? 0.010 : 0.004;
            a.coolerEffic = 0.30;
            a.coolerMin = 20;
            a.wastegateMP = mp;
            a.switchAlt = -1;
            a.turbo = false;
            a.boost0 = 0; a.rated0 = 0; a.boost1 = 0; a.rated1 = 0; a.cost1 = 0;

            switch (asp)
            {
                case AspirationType.NaturallyAspirated:
                    a.wastegateMP = 29.92;
                    break;
                case AspirationType.SingleStage1Speed:
                    a.boost0 = mp; a.rated0 = Math.Max(500.0, critM);
                    break;
                case AspirationType.SingleStage2Speed:
                    a.boost0 = mp; a.rated0 = Math.Max(500.0, critM * 0.4);
                    a.boost1 = mp; a.rated1 = Math.Max(2000.0, critM);
                    a.cost1 = hp * 0.08;
                    break;
                case AspirationType.TwoStageIntercooled:
                    a.boost0 = mp; a.rated0 = Math.Max(800.0, critM * 0.45);
                    a.boost1 = mp; a.rated1 = Math.Max(3000.0, critM);
                    a.cost1 = hp * 0.12;
                    a.coolerEffic = 0.6; a.coolerMin = -15;
                    break;
                default:
                    // Turbosupercharged / turbo-compound: AJE V-1710-89 style single turbo stage
                    a.turbo = true;
                    a.boost0 = mp; a.rated0 = Math.Max(2000.0, critM);
                    a.boost1 = mp * 0.7; a.rated1 = 0; a.cost1 = 0;
                    a.switchAlt = 40000;
                    break;
            }
        }

        public static void ApplyToEngineModules(Part part, ModuleProceduralPropeller m, PropellerPerformanceMetrics metrics, AJEBridge aje)
        {
            if (part == null)
                return;
            ModuleEngines eng = part.FindModuleImplementing<ModuleEngines>();
            if (eng == null)
                return;

            UpdateEnginePropellant(eng, metrics.fuelResourceName);
            SyncIntegratedNacelleFuel(part, metrics.fuelResourceName, metrics.integratedFuelLiters);

            if (aje != null && aje.Valid)
            {
                try
                {
                    AJEParameters a = metrics.aje;
                    aje.Set("useOxygen", true);
                    aje.Set("useHP", true);
                    aje.Set("useInHg", true);
                    aje.Set("power", a.power);
                    aje.Set("displacement", a.displacement);
                    aje.Set("compression", a.compression);
                    aje.Set("minRPM", a.minRPM);
                    aje.Set("maxRPM", a.maxRPM);
                    aje.Set("gearratio", a.gearRatio);
                    aje.Set("BSFC", a.bsfc);
                    aje.Set("coolerEffic", a.coolerEffic);
                    aje.Set("coolerMin", a.coolerMin);
                    aje.Set("ramAir", a.ramAir);
                    aje.Set("exhaustThrust", a.exhaustThrust);
                    aje.Set("meredithEffect", a.meredithEffect);
                    aje.Set("boost0", a.boost0);
                    aje.Set("rated0", a.rated0);
                    aje.Set("boost1", a.boost1);
                    aje.Set("rated1", a.rated1);
                    aje.Set("cost1", a.cost1);
                    aje.Set("switchAlt", a.switchAlt);
                    aje.Set("turbo", a.turbo);
                    aje.Set("wastegateMP", a.wastegateMP);
                    aje.Set("propName", a.propName);
                    aje.Set("propDiam", a.propDiam);
                    aje.Set("CtTweak", a.ctTweak);
                    aje.Set("CpTweak", a.cpTweak);
                    aje.Set("VolETweak", 1.0);
                    aje.Rebuild();
                }
                catch (Exception ex)
                {
                    Debug.LogWarning("[ROPlanesPlus] AJE sync failed: " + ex.Message);
                }
                return;
            }

            // Stock fallback: static thrust and a fuel flow that matches the BSFC at full power
            float thrust = Mathf.Max(0.5f, metrics.staticThrustKn);
            float fuelKgPerSec = (float)metrics.aje.bsfc * metrics.shaftPowerHP * HPToWatts;
            float isp = Mathf.Clamp((thrust * 1000f) / (G0 * Mathf.Max(0.001f, fuelKgPerSec)), 2000f, 40000f);
            FloatCurve atm = new FloatCurve();
            atm.Add(0f, isp);
            atm.Add(1f, isp);
            eng.atmosphereCurve = atm;
            eng.maxThrust = thrust;
            eng.minThrust = 0f;
            eng.maxFuelFlow = thrust / (isp * G0);
            eng.minFuelFlow = 0f;
        }

        /// <summary>
        /// Aircraft fuel systems pump from every tank, so wing-mounted engines don't depend on
        /// crossfeed through wing roots (AvGas/Kerosene are STACK_PRIORITY_SEARCH by definition).
        /// Balanced draw keeps the centre of gravity steady; tank flow priority still works.
        /// </summary>
        private const ResourceFlowMode FuelFlowMode = ResourceFlowMode.ALL_VESSEL_BALANCE;

        private static Propellant MakeFuelPropellant(string resourceName, float ratio)
        {
            ConfigNode n = new ConfigNode("PROPELLANT");
            n.AddValue("name", resourceName);
            n.AddValue("ratio", ratio.ToString("R"));
            n.AddValue("DrawGauge", "True");
            n.AddValue("resourceFlowMode", FuelFlowMode.ToString()); // the key Propellant.Load reads
            Propellant np = new Propellant();
            np.Load(n);
            if (np.GetFlowMode() != FuelFlowMode && _propFlowModeField != null)
            {
                try { _propFlowModeField.SetValue(np, FuelFlowMode); }
                catch (Exception) { }
            }
            return np;
        }

        private static readonly FieldInfo _propFlowModeField =
            typeof(Propellant).GetField("flowMode", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);

        private static void UpdateEnginePropellant(ModuleEngines eng, string resourceName)
        {
            if (eng == null || eng.propellants == null || string.IsNullOrEmpty(resourceName))
                return;
            if (PartResourceLibrary.Instance == null || PartResourceLibrary.Instance.GetDefinition(resourceName) == null)
                return;

            bool changed = false;
            bool foundFuel = false;
            for (int i = 0; i < eng.propellants.Count; i++)
            {
                Propellant pr = eng.propellants[i];
                if (pr == null || string.Equals(pr.name, "IntakeAir", StringComparison.OrdinalIgnoreCase))
                    continue;
                foundFuel = true;
                if (!string.Equals(pr.name, resourceName, StringComparison.OrdinalIgnoreCase))
                {
                    eng.propellants[i] = MakeFuelPropellant(resourceName, pr.ratio);
                    changed = true;
                }
                else if (pr.GetFlowMode() != FuelFlowMode)
                {
                    // Craft/configs from older versions: draw from every tank, not by crossfeed
                    eng.propellants[i] = MakeFuelPropellant(resourceName, pr.ratio);
                    changed = true;
                }
            }
            if (!foundFuel)
            {
                eng.propellants.Insert(0, MakeFuelPropellant(resourceName, 1f));
                changed = true;
            }
            if (changed)
                eng.SetupPropellant();
        }

        private static void SyncIntegratedNacelleFuel(Part part, string fuelName, float liters)
        {
            if (part == null || part.Resources == null || PartResourceLibrary.Instance == null)
                return;

            string[] managedFuels = new string[] { "AvGas", "Kerosene", "LiquidFuel" };
            for (int i = 0; i < managedFuels.Length; i++)
            {
                if (string.Equals(managedFuels[i], fuelName, StringComparison.OrdinalIgnoreCase))
                    continue;
                PartResource oldRes = part.Resources[managedFuels[i]];
                if (oldRes != null)
                    part.Resources.Remove(oldRes);
            }

            PartResource current = part.Resources[fuelName];
            if (liters <= 0.5f)
            {
                if (current != null)
                    part.Resources.Remove(current);
                return;
            }

            if (PartResourceLibrary.Instance.GetDefinition(fuelName) == null)
                return;

            double targetMax = Math.Round(liters, 1);
            if (current == null)
            {
                ConfigNode rNode = new ConfigNode("RESOURCE");
                rNode.AddValue("name", fuelName);
                rNode.AddValue("amount", targetMax.ToString("F1"));
                rNode.AddValue("maxAmount", targetMax.ToString("F1"));
                part.AddResource(rNode);
            }
            else if (Math.Abs(current.maxAmount - targetMax) > 0.5)
            {
                bool wasFull = current.amount >= current.maxAmount * 0.98;
                current.maxAmount = targetMax;
                if (HighLogic.LoadedSceneIsEditor || wasFull || current.amount > targetMax)
                    current.amount = targetMax;
            }
        }

        public static void NotifyFARRebuild(Part part)
        {
            if (part == null || !HasFAR)
                return;
            try
            {
                part.SendMessage("GeometryPartModuleRebuildMeshData", SendMessageOptions.DontRequireReceiver);
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[ROPlanesPlus] FAR voxel rebuild warning: " + ex.Message);
            }
        }
    }
}
