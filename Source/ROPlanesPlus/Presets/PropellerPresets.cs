using System;
using System.Collections.Generic;
using UnityEngine;

namespace ROPlanesPlus
{
    public enum EngineArchitecture
    {
        Radial = 0,
        VInline = 1,
        Turboprop = 2
    }

    public enum BladePlanform
    {
        Elliptical = 0,
        Paddle = 1,
        Scimitar = 2
    }

    public enum SpinnerStyle
    {
        PointedFighter = 0,
        RoundedDome = 1,
        HollowCannon = 2,
        ExposedHub = 3
    }

    public enum AspirationType
    {
        NaturallyAspirated = 0,
        SingleStage1Speed = 1,
        SingleStage2Speed = 2,
        TwoStageIntercooled = 3,
        Turbosupercharged = 4,
        TurboCompound = 5
    }

    public enum NacelleStyle
    {
        FirewallMount = 0,
        ShortWingNacelle = 1,
        StreamlinedTankNacelle = 2
    }

    /// <summary>
    /// A historical powerplant. Geometry fields drive the procedural model; the AJE block is
    /// copied verbatim into ModuleEnginesAJEPropeller. Where AJE ships its own config for the
    /// engine (AJE/Parts/Props, AJE/SXT.cfg, AJE/KAX.cfg) those numbers are used unchanged so
    /// the part behaves exactly like the RO-endorsed engine; the rest are derived from
    /// published data using the same conventions.
    /// </summary>
    public class PropellerPreset
    {
        public string id;
        public string displayName;
        public string historicalAircraft;
        public string description;
        public string techRequired = "unlockParts";

        public EngineArchitecture architecture;
        public int subStyleIndex;
        public int cylindersPerRow;   // per radial row / inline bank; 0 = the layout's default (9 or 7 per row, 6 per bank)
        public int cowlFit = 1;       // 0 tight (Spitfire, Bf 109), 1 standard, 2 roomy
        public bool isContraRotating;

        public float cowlDiameter;
        public float cowlLength;
        public float propDiameter;
        public int bladeCount;
        public BladePlanform bladePlanform;
        public SpinnerStyle spinnerStyle;
        public NacelleStyle nacelleStyle;
        public string liveryName;

        public float massTons;
        public float shaftPowerHP;
        public AspirationType aspiration;
        public float wepMultiplier = 1.0f;

        // ---- AJE ModuleEnginesAJEPropeller block (inHg, cubic inches, HP, metres) ----
        public double displacement;
        public double compression;
        public double minRPM;
        public double maxRPM;
        public double gearRatio;
        public double bsfc;
        public double coolerEffic;
        public double coolerMin = -200.0;
        public double ramAir;
        public double exhaustThrust;
        public double meredithEffect;
        public double boost0;
        public double rated0;
        public double boost1;
        public double rated1;
        public double cost1;
        public double switchAlt = -1.0;
        public bool turbo;
        public double wastegateMP;
        public string propName;
        public float ctTweak;   // 0 = derive from blade count
        public float cpTweak;   // 0 = derive from blade count

        public bool IsTurboprop { get { return architecture == EngineArchitecture.Turboprop; } }

        public float CriticalAltitudeKm
        {
            get
            {
                double alt = rated1 > rated0 ? rated1 : rated0;
                return (float)(alt / 1000.0);
            }
        }
    }

    public static class PropellerPresets
    {
        public const string CustomId = "Custom";

        // Turboprop architecture as a whole needs this RP-1 node (1952-1958) in career games.
        public const string TurbopropTech = "matureSupersonic";

        public static readonly string[] ArchitectureOptions = new string[]
        {
            "Radial",
            "V-Inline",
            "Turboprop"
        };

        public static readonly string[] SubStyleOptions = new string[] { "A", "B", "C" };

        public static readonly string[] BladePlanformOptions = new string[]
        {
            "Elliptical",
            "Wide Paddle",
            "Scimitar Swept"
        };

        public static readonly string[] SpinnerStyleOptions = new string[]
        {
            "Pointed Fighter",
            "Rounded Dome",
            "Hollow Cannon Hub",
            "Exposed Hub"
        };

        public static readonly string[] AspirationOptions = new string[]
        {
            "Naturally Aspirated",
            "1-Stage 1-Speed",
            "1-Stage 2-Speed",
            "2-Stage Intercooled",
            "Turbosupercharged",
            "Turbo-Compound"
        };

        public static readonly string[] NacelleOptions = new string[]
        {
            "Firewall Mount",
            "Short Wing Nacelle",
            "Streamlined Tank Nacelle"
        };

        // Display names are persisted in craft files: only ever append, never rename/reorder.
        public static readonly string[] LiveryOptions = new string[]
        {
            "Polished Aluminum",
            "RAF Camo + Sky",
            "Luftwaffe Mottled",
            "US Navy Sea Blue",
            "Soviet VVS Metal",
            "USAAF Olive Drab",
            "Desert Camo",
            "IJN Black Cowl",
            "Air Racer Red",
            "Airliner White",
            "Night Fighter Black",
            "Trainer Yellow",
            "Arctic Whitewash",
            "Italian Smoke Rings",
            "Custom Paint"
        };

        // Texture file keys matching LiveryOptions (PropShared/ropp_livery_<key>.png).
        // "custom" has no file: CustomPaint composites it at runtime from the paint kit.
        public static readonly string[] LiveryKeys = new string[]
        {
            "aluminum", "raf", "luftwaffe", "usn", "soviet", "olive", "desert", "ijn",
            "racer", "civil", "night", "trainer", "arctic", "italian", "custom"
        };

        public const int CustomLiveryIndex = 14;

        // Two-tone swatches (upper surface, lower surface) for the livery picker
        public static readonly Color32[] LiveryTop = new Color32[]
        {
            new Color32(186, 190, 198, 255), new Color32(56, 70, 45, 255), new Color32(72, 78, 83, 255),
            new Color32(32, 47, 76, 255), new Color32(104, 118, 126, 255), new Color32(84, 82, 52, 255),
            new Color32(110, 86, 58, 255), new Color32(30, 32, 34, 255), new Color32(178, 28, 28, 255),
            new Color32(232, 232, 228, 255), new Color32(26, 26, 28, 255), new Color32(226, 178, 24, 255),
            new Color32(226, 228, 224, 255), new Color32(190, 160, 100, 255), new Color32(120, 120, 120, 255)
        };

        public static readonly Color32[] LiveryBottom = new Color32[]
        {
            new Color32(170, 176, 184, 255), new Color32(146, 150, 152, 255), new Color32(150, 170, 182, 255),
            new Color32(28, 42, 70, 255), new Color32(142, 172, 196, 255), new Color32(122, 124, 124, 255),
            new Color32(98, 140, 190, 255), new Color32(30, 32, 34, 255), new Color32(236, 236, 232, 255),
            new Color32(180, 186, 192, 255), new Color32(26, 26, 28, 255), new Color32(226, 178, 24, 255),
            new Color32(60, 74, 48, 255), new Color32(150, 152, 154, 255), new Color32(200, 200, 200, 255)
        };

        // Palette for Custom Paint (cowling, nose ring and spinner each pick one)
        public static readonly string[] PaintNames = new string[]
        {
            "White", "Light Grey", "Medium Grey", "Dark Grey", "Black", "Silver",
            "Insignia Red", "Maroon", "Orange", "Chrome Yellow", "Cream", "Sand",
            "Dark Earth", "Olive Drab", "Dark Green", "Sky", "Azure", "Sea Blue",
            "Navy Blue", "Royal Blue", "Teal", "Purple"
        };

        public static readonly Color32[] PaintColors = new Color32[]
        {
            new Color32(236, 236, 232, 255), new Color32(186, 188, 190, 255), new Color32(132, 136, 140, 255),
            new Color32(74, 78, 82, 255), new Color32(26, 26, 28, 255), new Color32(196, 200, 206, 255),
            new Color32(178, 30, 32, 255), new Color32(110, 28, 32, 255), new Color32(222, 112, 26, 255),
            new Color32(232, 184, 24, 255), new Color32(226, 214, 176, 255), new Color32(190, 160, 100, 255),
            new Color32(110, 86, 58, 255), new Color32(84, 82, 52, 255), new Color32(52, 70, 44, 255),
            new Color32(188, 200, 166, 255), new Color32(98, 140, 190, 255), new Color32(32, 47, 76, 255),
            new Color32(22, 30, 58, 255), new Color32(30, 70, 160, 255), new Color32(28, 110, 110, 255),
            new Color32(90, 50, 120, 255)
        };

        public static readonly string[] FinishNames = new string[] { "Matt", "Satin", "Gloss" };
        public static readonly byte[] FinishGloss = new byte[] { 45, 120, 215 };

        /// <summary>"14-cyl radial", "inverted V-12", "X-24"; turboprops by class.</summary>
        public static string EngineTypeName(int arch, int subStyle, int cylinders)
        {
            if (arch == (int)EngineArchitecture.Radial)
                return cylinders + "-cyl radial";
            if (arch == (int)EngineArchitecture.VInline)
                return subStyle == 2 ? "X-" + cylinders : (subStyle == 1 ? "inverted V-" + cylinders : "V-" + cylinders);
            return GetSubStyleLabels(arch)[Mathf.Clamp(subStyle, 0, 2)].ToLowerInvariant() + " turboprop";
        }

        /// <summary>Total cylinders of a preset ("14-cyl radial" in the engine cards).</summary>
        public static int PresetCylinders(PropellerPreset p)
        {
            int arch = (int)p.architecture;
            int perRow = PropellerPhysicsEngine.ResolveCylindersPerRow(arch, p.subStyleIndex, p.cylindersPerRow);
            return PropellerPhysicsEngine.CylinderRows(arch, p.subStyleIndex) * perRow;
        }

        public static string[] GetSubStyleLabels(int archIdx)
        {
            if (archIdx == (int)EngineArchitecture.Radial)
                return new string[] { "Twin row", "Single row", "Four rows" };
            if (archIdx == (int)EngineArchitecture.VInline)
                return new string[] { "Upright V", "Inverted V", "X (4 banks)" };
            return new string[] { "Chin intake", "Annular intake", "Free turbine" };
        }

        public static int ParseSubStyle(string value)
        {
            if (string.IsNullOrEmpty(value))
                return 0;
            string v = value.Trim();
            // Accept "A"/"B"/"C" and legacy "Style A (...)" strings saved by older versions
            if (v.StartsWith("Style ", StringComparison.OrdinalIgnoreCase) && v.Length > 6)
                v = v.Substring(6, 1);
            if (v.StartsWith("B", StringComparison.OrdinalIgnoreCase))
                return 1;
            if (v.StartsWith("C", StringComparison.OrdinalIgnoreCase))
                return 2;
            return 0;
        }

        public static int ParseArchitecture(string value)
        {
            if (string.IsNullOrEmpty(value))
                return 0;
            if (value.IndexOf("Turbo", StringComparison.OrdinalIgnoreCase) >= 0)
                return 2;
            if (value.IndexOf("V-", StringComparison.OrdinalIgnoreCase) >= 0 ||
                value.IndexOf("Inline", StringComparison.OrdinalIgnoreCase) >= 0)
                return 1;
            return 0;
        }

        public static int ParseLivery(string value)
        {
            if (string.IsNullOrEmpty(value))
                return 0;
            for (int i = 0; i < LiveryOptions.Length; i++)
            {
                if (string.Equals(LiveryOptions[i], value, StringComparison.OrdinalIgnoreCase))
                    return i;
            }
            // Legacy / loose matches
            if (value.IndexOf("RAF", StringComparison.OrdinalIgnoreCase) >= 0) return 1;
            if (value.IndexOf("Luftwaffe", StringComparison.OrdinalIgnoreCase) >= 0) return 2;
            if (value.IndexOf("Navy", StringComparison.OrdinalIgnoreCase) >= 0) return 3;
            if (value.IndexOf("Soviet", StringComparison.OrdinalIgnoreCase) >= 0) return 4;
            return 0;
        }

        /// <summary>True when the RP-1 tech node is researched, or when not playing a career game.</summary>
        public static bool IsTechAvailable(string techId)
        {
            if (string.IsNullOrEmpty(techId) || techId == "unlockParts")
                return true;
            if (HighLogic.CurrentGame == null || ResearchAndDevelopment.Instance == null)
                return true;
            if (HighLogic.CurrentGame.Mode != Game.Modes.CAREER && HighLogic.CurrentGame.Mode != Game.Modes.SCIENCE_SANDBOX)
                return true;
            return ResearchAndDevelopment.GetTechnologyState(techId) == RDTech.State.Available;
        }

        private static readonly List<PropellerPreset> _presets = new List<PropellerPreset>
        {
            // ---------------------------------------------------------------- V-Inline
            new PropellerPreset
            {
                // AJE/SXT.cfg  SXTMerlin66prop
                id = "Merlin66", displayName = "Rolls-Royce Merlin 66",
                historicalAircraft = "Spitfire LF.IX",
                description = "Two-stage two-speed intercooled V-12 at +25 lb boost.",
                architecture = EngineArchitecture.VInline, subStyleIndex = 0, cowlFit = 0, isContraRotating = false,
                cowlDiameter = 1.02f, cowlLength = 1.95f, propDiameter = 3.30f, bladeCount = 4,
                bladePlanform = BladePlanform.Elliptical, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "RAF Camo + Sky",
                massTons = 0.94f, shaftPowerHP = 1975f, aspiration = AspirationType.TwoStageIntercooled,
                displacement = 1647, compression = 6, minRPM = 1793, maxRPM = 3000, gearRatio = 0.477,
                bsfc = 1.26e-7, coolerEffic = 0.67, coolerMin = -15, ramAir = 0.35, exhaustThrust = 0.75,
                meredithEffect = 0.007, boost0 = 50.9, rated0 = 1200, boost1 = 50.9, rated1 = 4280,
                cost1 = 255, switchAlt = -1, turbo = false, wastegateMP = 60.5, propName = "RotolRX5",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/Parts/Props/Griffon88.cfg
                id = "Griffon88", displayName = "Rolls-Royce Griffon 88",
                historicalAircraft = "Seafire FR.47",
                description = "37-litre V-12 driving a 2x3 Rotol contra-rotating propeller.",
                architecture = EngineArchitecture.VInline, subStyleIndex = 0, isContraRotating = true,
                cowlDiameter = 1.10f, cowlLength = 2.10f, propDiameter = 3.35f, bladeCount = 3,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "RAF Camo + Sky",
                massTons = 1.237f, shaftPowerHP = 2320f, aspiration = AspirationType.TwoStageIntercooled,
                displacement = 2239, compression = 6, minRPM = 2000, maxRPM = 2750, gearRatio = 0.5102,
                bsfc = 1.162e-7, coolerEffic = 1, coolerMin = -200, ramAir = 0.9, exhaustThrust = 1,
                meredithEffect = 0.011, boost0 = 80.8, rated0 = 500, boost1 = 80.8, rated1 = 3800,
                cost1 = 390, switchAlt = -1, turbo = false, wastegateMP = 80.8, propName = "GriffonProp",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/Parts/Props/DB60x.cfg (DB 605 A) + MW-50 as WEP
                id = "DB605", displayName = "Daimler-Benz DB 605A",
                historicalAircraft = "Bf 109G-6",
                description = "Inverted V-12 with fluid-coupled supercharger; WEP = MW-50 injection.",
                architecture = EngineArchitecture.VInline, subStyleIndex = 1, cowlFit = 0, isContraRotating = false,
                cowlDiameter = 1.02f, cowlLength = 1.85f, propDiameter = 3.00f, bladeCount = 3,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.HollowCannon,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Luftwaffe Mottled",
                massTons = 0.976f, shaftPowerHP = 1475f, aspiration = AspirationType.SingleStage2Speed,
                wepMultiplier = 1.20f,
                displacement = 2176, compression = 8.5, minRPM = 1670, maxRPM = 2800, gearRatio = 0.594,
                bsfc = 1.2747e-7, coolerEffic = 0.325, coolerMin = 0, ramAir = 0, exhaustThrust = 1,
                meredithEffect = 0.015, boost0 = 39.3, rated0 = 2300, boost1 = 39.3, rated1 = 5650,
                cost1 = 165, switchAlt = 3500, turbo = false, wastegateMP = 38.9, propName = "RotolRX5",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/SXT.cfg  SXTJ213 (Jumo 213E)
                id = "Jumo213E", displayName = "Junkers Jumo 213E",
                historicalAircraft = "Ta 152H",
                description = "High-altitude inverted V-12, two-stage three-speed supercharger; WEP = MW-50/GM-1.",
                architecture = EngineArchitecture.VInline, subStyleIndex = 1, isContraRotating = false,
                cowlDiameter = 1.12f, cowlLength = 1.95f, propDiameter = 3.60f, bladeCount = 3,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.HollowCannon,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Luftwaffe Mottled",
                massTons = 1.07f, shaftPowerHP = 1865f, aspiration = AspirationType.TwoStageIntercooled,
                wepMultiplier = 1.10f,
                displacement = 2135.2, compression = 6.5, minRPM = 2000, maxRPM = 3250, gearRatio = 0.426,
                bsfc = 8.498e-8, coolerEffic = 0.15, coolerMin = 65, ramAir = 0.3, exhaustThrust = 1.9,
                meredithEffect = 0.015, boost0 = 60.74, rated0 = 5000, boost1 = 60.74, rated1 = 9800,
                cost1 = 500, switchAlt = -1, turbo = false, wastegateMP = 60.74, propName = "HS6501A-0x4",
                ctTweak = 0.77f, cpTweak = 0.75f
            },
            new PropellerPreset
            {
                // Derived from AJE V-1710-89 (turbo) doubled
                id = "V3420", displayName = "Allison V-3420",
                historicalAircraft = "Fisher P-75A Eagle",
                description = "Two coupled V-1710 banks with GE turbosupercharger and contra-rotating props.",
                architecture = EngineArchitecture.VInline, subStyleIndex = 2, isContraRotating = true,
                cowlDiameter = 1.32f, cowlLength = 2.30f, propDiameter = 4.00f, bladeCount = 3,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Polished Aluminum",
                massTons = 1.65f, shaftPowerHP = 2600f, aspiration = AspirationType.Turbosupercharged,
                displacement = 3420, compression = 6.65, minRPM = 2300, maxRPM = 3000, gearRatio = 0.40,
                bsfc = 1.21e-7, coolerEffic = 0.75, coolerMin = -15, ramAir = 0.4, exhaustThrust = 0.8,
                meredithEffect = 0.010, boost0 = 60, rated0 = 6100, boost1 = 40, rated1 = 0,
                cost1 = 0, switchAlt = 40000, turbo = true, wastegateMP = 60, propName = "GriffonProp"
            },
            // ---------------------------------------------------------------- Radial
            new PropellerPreset
            {
                id = "R1820", displayName = "Wright R-1820 Cyclone",
                historicalAircraft = "B-17G Flying Fortress",
                description = "Single-row radial with GE turbosupercharger for high-altitude bombing.",
                architecture = EngineArchitecture.Radial, subStyleIndex = 1, isContraRotating = false,
                cowlDiameter = 1.38f, cowlLength = 1.25f, propDiameter = 3.53f, bladeCount = 3,
                bladePlanform = BladePlanform.Elliptical, spinnerStyle = SpinnerStyle.ExposedHub,
                nacelleStyle = NacelleStyle.ShortWingNacelle, liveryName = "Polished Aluminum",
                massTons = 0.78f, shaftPowerHP = 1200f, aspiration = AspirationType.Turbosupercharged,
                displacement = 1823, compression = 6.7, minRPM = 1800, maxRPM = 2500, gearRatio = 0.5625,
                bsfc = 1.15e-7, coolerEffic = 0.30, coolerMin = 20, ramAir = 0.5, exhaustThrust = 0.2,
                meredithEffect = 0.003, boost0 = 46, rated0 = 7600, boost1 = 32, rated1 = 0,
                cost1 = 0, switchAlt = 40000, turbo = true, wastegateMP = 46, propName = "RotolRX5",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/SXT.cfg  SXTR280018WProp (dry rating; WEP = water injection to the AJE wet figure)
                id = "R2800", displayName = "P&W R-2800 Double Wasp",
                historicalAircraft = "F4U-4 Corsair",
                description = "Twin-row 18-cylinder radial; WEP = water injection.",
                architecture = EngineArchitecture.Radial, subStyleIndex = 0, isContraRotating = false,
                cowlDiameter = 1.34f, cowlLength = 1.55f, propDiameter = 4.01f, bladeCount = 4,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.RoundedDome,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "US Navy Sea Blue",
                massTons = 1.381f, shaftPowerHP = 2100f, aspiration = AspirationType.SingleStage2Speed,
                wepMultiplier = 1.133f,
                displacement = 2804.5, compression = 6.75, minRPM = 2200, maxRPM = 2800, gearRatio = 0.45,
                bsfc = 1.104e-7, coolerEffic = 0.35, coolerMin = 5, ramAir = 0.5, exhaustThrust = 1,
                meredithEffect = 0.005, boost0 = 60, rated0 = 10, boost1 = 52.5, rated1 = 7950,
                cost1 = 347, switchAlt = 1500, turbo = false, wastegateMP = 60, propName = "HS6501A-0x4",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/KAX.cfg  aje_r3350 (BSFC slightly relaxed to a realistic full-power figure)
                id = "R3350TC", displayName = "Wright R-3350 Turbo-Compound",
                historicalAircraft = "L-1049 Super Constellation",
                description = "18-cylinder radial with three power-recovery turbines; WEP = water injection.",
                architecture = EngineArchitecture.Radial, subStyleIndex = 0, isContraRotating = false,
                cowlDiameter = 1.42f, cowlLength = 1.72f, propDiameter = 4.11f, bladeCount = 4,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.RoundedDome,
                nacelleStyle = NacelleStyle.ShortWingNacelle, liveryName = "Polished Aluminum",
                massTons = 1.89f, shaftPowerHP = 3250f, aspiration = AspirationType.TurboCompound,
                wepMultiplier = 1.077f,
                displacement = 3347, compression = 6.7, minRPM = 2200, maxRPM = 2800, gearRatio = 0.4375,
                bsfc = 7.0e-8, coolerEffic = 0.08, coolerMin = 20, ramAir = 0.8, exhaustThrust = 0.4,
                meredithEffect = 0.017, boost0 = 59.5, rated0 = 3500, boost1 = 59.5, rated1 = 8000,
                cost1 = 100, switchAlt = -1, turbo = true, wastegateMP = 59.5, propName = "HS6501A-0x4",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                id = "R4360", displayName = "P&W R-4360 Wasp Major",
                historicalAircraft = "B-50 Superfortress / C-97",
                description = "Four-row 'corncob' radial with GE turbosupercharger; WEP = water injection.",
                architecture = EngineArchitecture.Radial, subStyleIndex = 2, isContraRotating = false,
                cowlDiameter = 1.45f, cowlLength = 2.15f, propDiameter = 5.08f, bladeCount = 4,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.RoundedDome,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Polished Aluminum",
                massTons = 2.25f, shaftPowerHP = 3500f, aspiration = AspirationType.Turbosupercharged,
                wepMultiplier = 1.086f,
                displacement = 4363, compression = 6.7, minRPM = 2200, maxRPM = 2700, gearRatio = 0.375,
                bsfc = 1.18e-7, coolerEffic = 0.30, coolerMin = 20, ramAir = 0.6, exhaustThrust = 0.3,
                meredithEffect = 0.005, boost0 = 58, rated0 = 9000, boost1 = 40, rated1 = 0,
                cost1 = 0, switchAlt = 40000, turbo = true, wastegateMP = 58, propName = "HS6501A-0x4",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // AJE/Parts/Props/M82.cfg (converted from litres/ata to cu in/inHg)
                id = "ASh82FN", displayName = "Shvetsov ASh-82FN",
                historicalAircraft = "La-7",
                description = "Fuel-injected twin-row Soviet fighter radial with two-speed supercharger.",
                architecture = EngineArchitecture.Radial, subStyleIndex = 0, cylindersPerRow = 7, isContraRotating = false,
                cowlDiameter = 1.26f, cowlLength = 1.42f, propDiameter = 3.10f, bladeCount = 3,
                bladePlanform = BladePlanform.Elliptical, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Soviet VVS Metal",
                massTons = 0.98f, shaftPowerHP = 1850f, aspiration = AspirationType.SingleStage2Speed,
                displacement = 2515, compression = 7.05, minRPM = 1500, maxRPM = 2500, gearRatio = 0.687,
                bsfc = 1.335e-7, coolerEffic = 1, coolerMin = -15, ramAir = 0.5, exhaustThrust = 0.3,
                meredithEffect = 0.001, boost0 = 39.4, rated0 = 750, boost1 = 39.4, rated1 = 5000,
                cost1 = 730, switchAlt = 3600, turbo = false, wastegateMP = 39.4, propName = "VISh-105V-4",
                ctTweak = 1f, cpTweak = 1f
            },
            // ---------------------------------------------------------------- Turboprop
            new PropellerPreset
            {
                id = "DoubleMamba", displayName = "AS Double Mamba",
                historicalAircraft = "Fairey Gannet AS.4",
                description = "Two coupled axial turboprops driving 2x4 contra-rotating propellers.",
                techRequired = "supersonicFlightRP0",
                architecture = EngineArchitecture.Turboprop, subStyleIndex = 1, isContraRotating = true,
                cowlDiameter = 1.18f, cowlLength = 2.20f, propDiameter = 3.96f, bladeCount = 4,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "RAF Camo + Sky",
                massTons = 1.35f, shaftPowerHP = 2950f, aspiration = AspirationType.NaturallyAspirated,
                displacement = 7100, compression = 6, minRPM = 2000, maxRPM = 2600, gearRatio = 0.496,
                bsfc = 1.15e-7, coolerEffic = 0, coolerMin = -200, ramAir = 1, exhaustThrust = 0.8,
                meredithEffect = 0.001, boost0 = 0, rated0 = 0, boost1 = 0, rated1 = 0,
                cost1 = 0, switchAlt = -1, turbo = false, wastegateMP = 52.5, propName = "4mHighAltx5"
            },
            new PropellerPreset
            {
                id = "T56", displayName = "Allison T56",
                historicalAircraft = "C-130H Hercules / P-3C Orion",
                description = "14-stage axial military turboprop with offset reduction gearbox.",
                techRequired = "matureSupersonic",
                architecture = EngineArchitecture.Turboprop, subStyleIndex = 0, isContraRotating = false,
                cowlDiameter = 1.05f, cowlLength = 2.15f, propDiameter = 4.11f, bladeCount = 4,
                bladePlanform = BladePlanform.Paddle, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.ShortWingNacelle, liveryName = "Polished Aluminum",
                massTons = 1.35f, shaftPowerHP = 4910f, aspiration = AspirationType.NaturallyAspirated,
                displacement = 11800, compression = 6, minRPM = 2000, maxRPM = 2600, gearRatio = 0.392,
                bsfc = 8.45e-8, coolerEffic = 0, coolerMin = -200, ramAir = 1, exhaustThrust = 1.0,
                meredithEffect = 0.001, boost0 = 0, rated0 = 0, boost1 = 0, rated1 = 0,
                cost1 = 0, switchAlt = -1, turbo = false, wastegateMP = 52.5, propName = "HS6501A-0x4",
                ctTweak = 1f, cpTweak = 1f
            },
            new PropellerPreset
            {
                // RP-1 places the SXT NK-12M at highSpeedFlight; same here.
                id = "NK12", displayName = "Kuznetsov NK-12MV",
                historicalAircraft = "Tu-95MS / An-22",
                description = "The most powerful turboprop built, driving 5.6 m 2x4 contra-rotating props.",
                techRequired = "highSpeedFlight",
                architecture = EngineArchitecture.Turboprop, subStyleIndex = 1, isContraRotating = true,
                cowlDiameter = 1.35f, cowlLength = 2.85f, propDiameter = 5.60f, bladeCount = 4,
                bladePlanform = BladePlanform.Scimitar, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.StreamlinedTankNacelle, liveryName = "Soviet VVS Metal",
                massTons = 4.00f, shaftPowerHP = 14795f, aspiration = AspirationType.NaturallyAspirated,
                displacement = 35500, compression = 6, minRPM = 2000, maxRPM = 2600, gearRatio = 0.283,
                bsfc = 6.6e-8, coolerEffic = 0, coolerMin = -200, ramAir = 1, exhaustThrust = 1.0,
                meredithEffect = 0.001, boost0 = 0, rated0 = 0, boost1 = 0, rated1 = 0,
                cost1 = 0, switchAlt = -1, turbo = false, wastegateMP = 52.5, propName = "4mHighAltx5"
            },
            new PropellerPreset
            {
                // AJE/SXT.cfg  SXTPWPT6 (gear raised to the real 2,200 rpm prop speed for a 2.59 m prop)
                id = "PT6A", displayName = "P&W Canada PT6A",
                historicalAircraft = "DHC-6 Twin Otter / King Air",
                description = "Reverse-flow free-turbine turboprop with forward exhaust stacks.",
                techRequired = "highSpeedFlight",
                architecture = EngineArchitecture.Turboprop, subStyleIndex = 2, isContraRotating = false,
                cowlDiameter = 0.68f, cowlLength = 1.58f, propDiameter = 2.59f, bladeCount = 3,
                bladePlanform = BladePlanform.Elliptical, spinnerStyle = SpinnerStyle.PointedFighter,
                nacelleStyle = NacelleStyle.FirewallMount, liveryName = "Polished Aluminum",
                massTons = 0.22f, shaftPowerHP = 680f, aspiration = AspirationType.NaturallyAspirated,
                displacement = 1800, compression = 6, minRPM = 2000, maxRPM = 3000, gearRatio = 0.73,
                bsfc = 8.47e-8, coolerEffic = 0, coolerMin = -200, ramAir = 1, exhaustThrust = 0.5,
                meredithEffect = 0.001, boost0 = 0, rated0 = 0, boost1 = 0, rated1 = 0,
                cost1 = 0, switchAlt = -1, turbo = false, wastegateMP = 52.5, propName = "RotolRX5",
                ctTweak = 1f, cpTweak = 1f
            }
        };

        public static List<PropellerPreset> AllPresets { get { return _presets; } }

        public static PropellerPreset GetPreset(string id)
        {
            if (string.IsNullOrEmpty(id))
                return null;
            for (int i = 0; i < _presets.Count; i++)
            {
                if (string.Equals(_presets[i].id, id, StringComparison.OrdinalIgnoreCase))
                    return _presets[i];
            }
            // Legacy ids written by older versions
            switch (id)
            {
                case "R2800_DoubleWasp": return GetPreset("R2800");
                case "Griffon88_Contra": return GetPreset("Griffon88");
                case "DB605AM": return GetPreset("DB605");
                case "Allison_V3420": return GetPreset("V3420");
                case "Wright_R1820": return GetPreset("R1820");
                case "Wright_R3350_TC": return GetPreset("R3350TC");
                case "PW_R4360_WaspMajor": return GetPreset("R4360");
                case "Shvetsov_ASh82FN": return GetPreset("ASh82FN");
                case "PW_PT6A": return GetPreset("PT6A");
                case "Allison_T56":
                case "T56_A15": return GetPreset("T56");
                case "Kuznetsov_NK12": return GetPreset("NK12");
            }
            return null;
        }

        /// <summary>Preset ids/labels for the editor chooser, filtered by career tech and part type.</summary>
        public static void GetChooserOptions(bool allowPiston, bool allowTurboprop, out string[] ids, out string[] labels)
        {
            List<string> idList = new List<string>();
            List<string> labelList = new List<string>();
            for (int i = 0; i < _presets.Count; i++)
            {
                PropellerPreset p = _presets[i];
                if (p.IsTurboprop && !allowTurboprop) continue;
                if (!p.IsTurboprop && !allowPiston) continue;
                if (!IsTechAvailable(p.techRequired)) continue;
                idList.Add(p.id);
                labelList.Add(p.displayName);
            }
            idList.Add(CustomId);
            labelList.Add("Custom");
            ids = idList.ToArray();
            labels = labelList.ToArray();
        }
    }
}
