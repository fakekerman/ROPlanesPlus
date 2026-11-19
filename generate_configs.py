#!/usr/bin/env python3
"""
Generates part .cfg files and RP-1 / RO / Kerbalism / FAR / RealAntennas
compatibility configs for all 10 cockpits in ROPlanesPlus.
"""

import math
import os

import cockpit_specs as CS

COCKPIT_CONFIGS = [
    {
        'id': 'spitfire',
        'manufacturer': 'Supermarine',
        'description': (
            'Single-seat fighter cockpit section of the Supermarine Spitfire at its real size, from the firewall to '
            'behind the razorback glazing. Round 0.9375 m rings at both ends: the front takes the Procedural Propeller '
            'Engine, the back a standard 0.9375 m fuselage.'
        ),
        'tags': 'cockpit, plane, fighter, ww2, prop, propeller, spitfire, supermarine, inline, merlin, griffon',
        'mass': 0.310, 'crew': 1, 'skin_temp': 'Aluminum', 'conduction_mult': 1.0,
        'iva_name': 'rooldfighterInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 0.20, 'ec_amount': 2900, 'fuel_type': 'SM-I', 'fuel_vol': 180, 'oxygen_amount': 46,
        'ejection_enabled': 'false', 'ejection_mass': 0.04, 'has_sas': False,
        'tech_node': 'unlockParts', 'cost': 32, 'entry_cost': 1, 'death_alt': 14000,
        'training_type': 'GeneralAviation', 'hab_vol': 1.05, 'hab_surf': 2.40,
        'bda_hp': 900, 'bda_armor': 8, 'bda_max_armor': 25,
    },
    {
        'id': 'bf109',
        'manufacturer': 'Messerschmitt AG',
        'description': (
            'Single-seat fighter cockpit section of the Messerschmitt Bf 109 at its real size, from the firewall to '
            'behind the armoured headrest. Round 0.9375 m rings at both ends: the front takes the Procedural '
            'Propeller Engine, the back a standard 0.9375 m fuselage.'
        ),
        'tags': 'cockpit, plane, fighter, ww2, prop, propeller, bf109, bf-109, me109, messerschmitt, inline, db605',
        'mass': 0.290, 'crew': 1, 'skin_temp': 'Aluminum', 'conduction_mult': 1.0,
        'iva_name': 'rooldfighterInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 0.20, 'ec_amount': 2900, 'fuel_type': 'SM-I', 'fuel_vol': 160, 'oxygen_amount': 46,
        'ejection_enabled': 'false', 'ejection_mass': 0.04, 'has_sas': False,
        'tech_node': 'unlockParts', 'cost': 30, 'entry_cost': 1, 'death_alt': 14000,
        'training_type': 'GeneralAviation', 'hab_vol': 0.95, 'hab_surf': 2.20,
        'bda_hp': 850, 'bda_armor': 8, 'bda_max_armor': 25,
    },
    {
        'id': 'me262',
        'manufacturer': 'Messerschmitt AG',
        'description': (
            'Forward fuselage of the Messerschmitt Me 262 Schwalbe, the first operational jet fighter, with its '
            'triangular "shark" cross-section and teardrop canopy.'
        ),
        'tags': 'cockpit, plane, fighter, jet, ww2, me262, me-262, schwalbe, messerschmitt, jumo',
        'mass': 0.380, 'crew': 1, 'skin_temp': 'Aluminum', 'conduction_mult': 1.0,
        'iva_name': 'rooldfighterInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 0.35, 'ec_amount': 3600, 'fuel_type': 'SM-I', 'fuel_vol': 220, 'oxygen_amount': 50,
        'ejection_enabled': 'false', 'ejection_mass': 0.04, 'has_sas': False,
        'tech_node': 'unlockParts', 'cost': 55, 'entry_cost': 1, 'death_alt': 15000,
        'training_type': 'GeneralAviation', 'hab_vol': 1.15, 'hab_surf': 2.65,
        'bda_hp': 1100, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'b29',
        'manufacturer': '#roMfrBoeing',
        'description': (
            'Pressurised forward crew compartment of the Boeing B-29 Superfortress bomber and X-1 mothership, with the '
            'navigator\'s astrodome and the forward gun turrets.'
        ),
        'tags': 'cockpit, plane, bomber, heavy, prop, propeller, b29, b-29, superfortress, boeing, airlaunch, mothership',
        'mass': 2.100, 'crew': 4, 'skin_temp': 'Aluminum', 'conduction_mult': 1.0,
        'iva_name': 'kossakint', 'iva_offset': '0.0, 0.0, -0.40',
        'ec_rate': 0.60, 'ec_amount': 21600, 'fuel_type': 'SM-I', 'fuel_vol': 950, 'oxygen_amount': 240,
        'ejection_enabled': 'false', 'ejection_mass': 0.16, 'has_sas': True,
        'tech_node': 'unlockParts', 'cost': 320, 'entry_cost': 1, 'death_alt': 16000,
        'training_type': 'GeneralAviation', 'hab_vol': 14.0, 'hab_surf': 30.0,
        'bda_hp': 4500, 'bda_armor': 6, 'bda_max_armor': 40,
    },
    {
        'id': 'mig15',
        'manufacturer': 'Mikoyan-Gurevich (OKB-155)',
        'description': (
            'Forward fuselage of the Soviet MiG-15bis transonic jet fighter: round barrel, sliding bubble canopy and '
            'the nose intake with its splitter.'
        ),
        'tags': 'cockpit, plane, fighter, jet, mig, mig15, mig-15, fagot, soviet, mikoyan, vk1',
        'mass': 0.440, 'crew': 1, 'skin_temp': 'Aluminum', 'conduction_mult': 0.5,
        'iva_name': 'mk1CockpitInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 0.75, 'ec_amount': 7200, 'fuel_type': 'SM-I', 'fuel_vol': 280, 'oxygen_amount': 60,
        'ejection_enabled': 'true', 'ejection_mass': 0.04, 'has_sas': True,
        'tech_node': 'supersonicFlightRP0', 'cost': 220, 'entry_cost': 2500, 'death_alt': 20000,
        'training_type': 'JetFighter', 'hab_vol': 1.25, 'hab_surf': 2.85,
        'bda_hp': 1300, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'f104',
        'manufacturer': '#roMfrLockheed',
        'description': (
            'Forward fuselage of the Lockheed F-104 Starfighter Mach 2 interceptor: needle radome, pitot boom and the '
            'narrow clamshell canopy.'
        ),
        'tags': 'cockpit, plane, fighter, supersonic, interceptor, f104, f-104, starfighter, lockheed, century, j79',
        'mass': 0.550, 'crew': 1, 'skin_temp': 'Titanium', 'conduction_mult': 0.1,
        'iva_name': 'mk1CockpitInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 1.00, 'ec_amount': 10800, 'fuel_type': 'Fuselage', 'fuel_vol': 200, 'oxygen_amount': 65,
        'ejection_enabled': 'true', 'ejection_mass': 0.05, 'has_sas': True,
        'tech_node': 'matureSupersonic', 'cost': 260, 'entry_cost': 5000, 'death_alt': 37000,
        'training_type': 'JetFighter', 'hab_vol': 1.20, 'hab_surf': 2.75,
        'bda_hp': 1500, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'f4',
        'manufacturer': '#roMfrMcDonnell',
        'description': (
            'Two-seat tandem forward fuselage of the McDonnell Douglas F-4 Phantom II, pilot in front and weapons '
            'officer behind.'
        ),
        'tags': 'cockpit, plane, fighter, supersonic, interceptor, phantom, f4, f-4, mcdonnell, tandem, j79',
        'mass': 1.050, 'crew': 2, 'skin_temp': 'Titanium', 'conduction_mult': 0.1,
        'iva_name': 'rofighterinlineInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 1.25, 'ec_amount': 21600, 'fuel_type': 'Fuselage', 'fuel_vol': 280, 'oxygen_amount': 110,
        'ejection_enabled': 'true', 'ejection_mass': 0.09, 'has_sas': True,
        'tech_node': 'highSpeedFlight', 'cost': 480, 'entry_cost': 8500, 'death_alt': 38000,
        'training_type': 'JetFighter', 'hab_vol': 2.40, 'hab_surf': 5.80,
        'bda_hp': 2200, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'su27',
        'manufacturer': 'Sukhoi OKB',
        'description': (
            'Forward fuselage of the Sukhoi Su-27 Flanker air-superiority fighter: drooped radome, IRST ball ahead of '
            'the big bubble canopy and the dorsal hump behind it.'
        ),
        'tags': 'cockpit, plane, fighter, supersonic, flanker, su27, su-27, sukhoi, al31, soviet, modern',
        'mass': 0.900, 'crew': 1, 'skin_temp': 'Titanium', 'conduction_mult': 0.1,
        'iva_name': 'mk1InlineInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 1.15, 'ec_amount': 21600, 'fuel_type': 'ServiceModule', 'fuel_vol': 300, 'oxygen_amount': 90,
        'ejection_enabled': 'true', 'ejection_mass': 0.05, 'has_sas': True,
        'tech_node': 'refinedTurbofans', 'cost': 1150, 'entry_cost': 12000, 'death_alt': 38000,
        'training_type': 'JetFighter', 'hab_vol': 1.65, 'hab_surf': 3.60,
        'bda_hp': 2200, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'f16',
        'manufacturer': 'General Dynamics / Lockheed Martin',
        'description': (
            'Forward fuselage of the F-16 Fighting Falcon: frameless gold-tinted bubble canopy, chined forebody and the '
            'formation lights on its flanks.'
        ),
        'tags': 'cockpit, plane, fighter, supersonic, viper, falcon, f16, f-16, general dynamics, lockheed, f100, f110',
        'mass': 0.620, 'crew': 1, 'skin_temp': 'Titanium', 'conduction_mult': 0.1,
        'iva_name': 'mk1InlineInternal', 'iva_offset': '0.0, 0.0, 0.0',
        'ec_rate': 1.00, 'ec_amount': 18000, 'fuel_type': 'ServiceModule', 'fuel_vol': 240, 'oxygen_amount': 80,
        'ejection_enabled': 'true', 'ejection_mass': 0.05, 'has_sas': True,
        'tech_node': 'matureTurbofans', 'cost': 950, 'entry_cost': 9500, 'death_alt': 37000,
        'training_type': 'JetFighter', 'hab_vol': 1.50, 'hab_surf': 3.30,
        'bda_hp': 1800, 'bda_armor': 10, 'bda_max_armor': 30,
    },
    {
        'id': 'b52',
        'manufacturer': '#roMfrBoeing',
        'description': (
            'Forward fuselage of the Boeing B-52 Stratofortress strategic bomber and X-15 mothership, with the raised '
            'six-window flight deck and the chin radome.'
        ),
        'tags': 'cockpit, plane, bomber, heavy, jet, b52, b-52, stratofortress, boeing, nb52, x15, airlaunch, mothership',
        'mass': 3.600, 'crew': 4, 'skin_temp': 'Aluminum', 'conduction_mult': 0.5,
        'iva_name': 'kossakint', 'iva_offset': '0.0, 0.0, -1.10',
        'ec_rate': 1.20, 'ec_amount': 43200, 'fuel_type': 'Fuselage', 'fuel_vol': 1800, 'oxygen_amount': 360,
        'ejection_enabled': 'true', 'ejection_mass': 0.18, 'has_sas': True,
        'tech_node': 'matureSupersonic', 'cost': 1950, 'entry_cost': 38000, 'death_alt': 20000,
        'training_type': 'GeneralAviation', 'hab_vol': 18.0, 'hab_surf': 38.0,
        'bda_hp': 6000, 'bda_armor': 6, 'bda_max_armor': 40,
    },
]

# Geometry, variants and liveries come from cockpit_specs.py (shared with blender/build_cockpits.py)
for _c in COCKPIT_CONFIGS:
    _s = CS.get(_c['id'])
    _c['part_name'] = _s['part_name']
    _c['title'] = _s['title']
    _c['spec'] = _s


def _fmt(v):
    return f"{v:.4f}".rstrip('0').rstrip('.') if isinstance(v, float) else str(v)


def _vec(t):
    return ', '.join(_fmt(float(x)) for x in t)


def cockpit_dimensions(s):
    v0 = s['variants'][0]
    if v0.get('nose') == 'adapter':
        ys, ln, r, zc = CS.adapter_geometry(s, v0)
        length = ys + ln
    else:
        length = CS.variant_length(s, v0)
    lengths = []
    for v in s['variants']:
        if v.get('nose') == 'adapter':
            ys, ln, r, zc = CS.adapter_geometry(s, v)
            lengths.append(ys + ln)
        else:
            lengths.append(CS.variant_length(s, v))
    return length, min(lengths), max(lengths)


def format_part_cfg(c):
    s = c['spec']
    oy = s['origin_y']
    rear = s['rear_dia']
    ns = CS.node_size(rear)
    bottom = (0.0, -oy, 0.0)
    v0 = s['variants'][0]
    fy, fz = CS.front_node(s, v0)
    top = CS.ksp_point(s, fy, fz)
    sec = CS.BodyProfile(s['body'], s['length'], s.get('nose')).section(oy)
    belly = round(sec['hb'] - sec['zc'], 3)
    front_dia = s.get('front_dia') or (v0.get('front_dia') if v0.get('nose') == 'adapter' else None)
    top_size = CS.node_size(front_dia) if front_dia else 1
    length, lmin, lmax = cockpit_dimensions(s)
    profiles = sorted({CS.bulkhead_profile(rear)} | ({CS.bulkhead_profile(front_dia)} if front_dia else set()))

    vnames = ', '.join(v['title'] for v in s['variants'])
    lnames = ', '.join(l['title'] for l in s['liveries'])
    size_txt = (f"Real size: {lmin:.1f} m long" if abs(lmax - lmin) < 0.05 else f"Real size: {lmin:.1f}-{lmax:.1f} m long") + \
        f", {rear:g} m round rear ring."
    description = (f"{c['description']} {size_txt} Versions (switch in the editor): {vnames}. "
                   f"Paint schemes: {lnames}.")

    sas_block = ''
    if c['has_sas']:
        sas_block = "\tMODULE\n\t{\n\t\tname = ModuleSAS\n\t\tSASServiceLevel = 1\n\t}\n\n"

    intake_block = ''
    if s.get('intake'):
        intake_block = (
            "\t// Built-in nose intake (the open-front version keeps it for your own intake part)\n"
            "\tMODULE\n\t{\n\t\tname = ModuleResourceIntake\n\t\tresourceName = IntakeAir\n"
            "\t\tcheckForOxygen = true\n\t\tarea = 0.006\n\t\tintakeSpeed = 12\n"
            "\t\tintakeTransformName = intakeTransform\n\t}\n"
            "\tRESOURCE\n\t{\n\t\tname = IntakeAir\n\t\tamount = 0.6\n\t\tmaxAmount = 0.6\n\t}\n\n"
        )

    seats = ''
    for (sx, sy) in s['seats']:
        ztop = CS.canopy_top_at(s, v0, sy)
        seats += (
            "\t\tSEAT\n\t\t{\n"
            f"\t\t\tcolliderOffset = {_vec((sx, sy - oy, -(ztop + 0.45)))}\n"
            "\t\t\tcolliderRotAngles = -90.0, 0.0, 0.0\n"
            f"\t\t\tforceDir = {_vec((0.05 * (1 if sx > 0 else -1) if sx else 0.0, 0.12, -1.0))}\n"
            "\t\t}\n"
        )

    # B9PartSwitch: versions (model groups + node moves) and paint schemes (texture swaps)
    subtypes = ''
    for v in s['variants']:
        vy, vz = CS.front_node(s, v)
        pos = CS.ksp_point(s, vy, vz)
        desc = v['desc'].replace('\n', ' ')
        subtypes += (
            "\t\tSUBTYPE\n\t\t{\n"
            f"\t\t\tname = {v['key']}\n"
            f"\t\t\ttitle = {v['title']}\n"
            f"\t\t\tdescriptionSummary = {desc}\n"
            f"\t\t\ttransform = variant_{v['key']}\n"
            f"\t\t\taddedMass = {_fmt(float(v['mass']))}\n"
            f"\t\t\taddedCost = {_fmt(float(v['cost']))}\n"
            "\t\t\tNODE\n\t\t\t{\n\t\t\t\tname = top\n"
            f"\t\t\t\tposition = {_vec(pos)}\n"
            "\t\t\t}\n"
            "\t\t}\n"
        )
    paints = ''
    for lv in s['liveries']:
        paints += (
            "\t\tSUBTYPE\n\t\t{\n"
            f"\t\t\tname = {lv['key']}\n"
            f"\t\t\ttitle = {lv['title']}\n"
            f"\t\t\tprimaryColor = {lv['top']}\n"
            f"\t\t\tsecondaryColor = {lv['under'] or lv['belly'] or lv['top']}\n"
            "\t\t\tTEXTURE\n\t\t\t{\n"
            f"\t\t\t\ttexture = ROPlanesPlus/Parts/{s['id']}/{s['id']}_{lv['key']}\n"
            f"\t\t\t\tcurrentTexture = {s['id']}_{s['liveries'][0]['key']}\n"
            "\t\t\t\tshaderProperty = _MainTex\n"
            "\t\t\t}\n"
            "\t\t}\n"
        )

    return f"""PART
{{
	name = {c['part_name']}
	module = Part
	author = ROPlanesPlus

	RSSROConfig = True

	// Model, textures and icon are built by generate_cockpits.py (Blender); do not edit by hand.
	MODEL
	{{
		model = ROPlanesPlus/Parts/{s['id']}/{s['id']}
	}}
	scale = 1.0
	rescaleFactor = 1.0

	// +Y forward, -Z up (canopy). Origin at the pilot station. The rear ring is a true {rear:g} m circle;
	// the front node moves with the version (see ModuleB9PartSwitch below).
	node_stack_top = {_vec(top)}, 0.0, 1.0, 0.0, {top_size}
	node_stack_bottom = {_vec(bottom)}, 0.0, -1.0, 0.0, {ns}
	node_attach = 0.0, 0.0, {_fmt(belly)}, 0.0, 0.0, -1.0, 1

	TechRequired = {c['tech_node']}
	entryCost = {c['entry_cost']}
	cost = {c['cost']}
	category = Pods
	subcategory = 0
	title = {c['title']}
	manufacturer = {c['manufacturer']}
	description = {description}

	tags = {c['tags']}

	attachRules = 1,1,1,1,0

	mass = {c['mass']}
	dragModelType = default
	maximum_drag = 0.08
	minimum_drag = 0.08
	angularDrag = 1.0
	crashTolerance = 10
	breakingForce = 2000
	breakingTorque = 2000
	skinInternalConductionMult = {c['conduction_mult']}

	skinTempTag = {c['skin_temp']}
	internalTempTag = Instruments

	vesselType = Plane
	CrewCapacity = {c['crew']}
	bulkheadProfiles = {', '.join(profiles)}, srf

	INTERNAL
	{{
		name = {c['iva_name']}
		offset = {c['iva_offset']}
	}}

	MODULE
	{{
		name = ModuleCommand
		minimumCrew = 1
		RESOURCE
		{{
			name = ElectricCharge
			rate = {c['ec_rate']}
		}}
	}}

{sas_block}{intake_block}	MODULE
	{{
		name = ModuleFuelTanks
		type = {c['fuel_type']}
		basemass = {c['mass']}
		baseCost = -1
		volume = {c['fuel_vol']}

		TANK
		{{
			name = ElectricCharge
			amount = {c['ec_amount']}
			maxAmount = {c['ec_amount']}
		}}

		UNMANAGED_RESOURCE
		{{
			name = Oxygen
			amount = {c['oxygen_amount']}
			maxAmount = {c['oxygen_amount']}
		}}
	}}

	MODULE
	{{
		name = ModuleB9PartSwitch
		moduleID = cockpitVersion
		switcherDescription = Version
		switcherDescriptionPlural = Versions
		affectDragCubes = true
		affectFARVoxels = true
		switchInFlight = false
{subtypes}	}}

	MODULE
	{{
		name = ModuleB9PartSwitch
		moduleID = cockpitPaint
		switcherDescription = Paint
		switcherDescriptionPlural = Paint schemes
		affectDragCubes = false
		affectFARVoxels = false
		switchInFlight = false
{paints}	}}

	MODULE:NEEDS[ConnectedLivingSpace]
	{{
		name = ModuleConnectedLivingSpace
		passable = true
	}}

	MODULE
	{{
		name = ModuleScienceExperiment
		experimentID = crewReport
		experimentActionName = Crew Report
		resetActionName = Discard Crew Report
		reviewActionName = Review Report
		useStaging = False
		useActionGroups = True
		hideUIwhenUnavailable = True
		rerunnable = True
		xmitDataScalar = 1.0
		usageReqMaskInternal = 5
		usageReqMaskExternal = -1
	}}

	MODULE
	{{
		name = ModuleScienceContainer
		reviewActionName = Review Stored Data
		storeActionName = Store Experiments
		evaOnlyStorage = True
		storageRange = 1.8
	}}

	MODULE
	{{
		name = ModuleROEjectionSeat
		mass = {c['ejection_mass']}
		IsEnabled = {c['ejection_enabled']}

{seats}	}}

	// Cockpit / instrument lights: brightens the emissive map (canopy glow, formation lights)
	MODULE
	{{
		name = ModuleColorChanger
		shaderProperty = _EmissiveColor
		animRate = 0.8
		animState = false
		useRate = true
		toggleInEditor = true
		toggleInFlight = true
		unfocusedRange = 5
		toggleName = Toggle Cockpit Lights
		eventOnName = Cockpit Lights On
		eventOffName = Cockpit Lights Off
		toggleAction = True
		defaultActionGroup = Light
		redCurve
		{{
			key = 0 0 0 3
			key = 1 1 0 0
		}}
		greenCurve
		{{
			key = 0 0 0 1
			key = 1 1 1 0
		}}
		blueCurve
		{{
			key = 0 0 0 0
			key = 1 1 1.5 0
		}}
		alphaCurve
		{{
			key = 0 1
		}}
	}}

	MODULE
	{{
		name = FlagDecal
		textureQuadName = flagDecal
	}}
}}
"""


def generate_all_configs(workspace_root):
    parts_root = os.path.join(workspace_root, 'GameData', 'ROPlanesPlus', 'Parts')
    compat_root = os.path.join(workspace_root, 'GameData', 'ROPlanesPlus', 'Compatibility')
    os.makedirs(compat_root, exist_ok=True)

    # 1. Individual Part .cfg files
    for c in COCKPIT_CONFIGS:
        pdir = os.path.join(parts_root, c['id'])
        os.makedirs(pdir, exist_ok=True)
        cfg_path = os.path.join(pdir, f"{c['id']}.cfg")
        with open(cfg_path, 'w', encoding='utf-8') as f:
            f.write(format_part_cfg(c))

    all_names_pipe = '|'.join(c['part_name'] for c in COCKPIT_CONFIGS)

    # 2. RP-1 Tech Tree, Entry Cost Modifiers, Training Times, Crew Science, Service Ceilings
    rp1_lines = [
        "// ============================================================================",
        "// ROPlanesPlus: RP-1 Tech Tree, Entry Costs, Crew Science, & Altitude Limits",
        "// ============================================================================",
        "",
        "// 1. Tag all ROPlanesPlus cockpits for RP-1 & ForAllKerbalkind Supersonic/Recon Crew Science",
        f"@PART[{all_names_pipe}]:BEFORE[RP-0-Kerbalism]",
        "{",
        "\t%capsuleTier = Cockpit",
        "}",
        "",
        "// 2. Crew Proficiency & Mission Training Times",
        "@TRAININGTIMES:FOR[RP-0]",
        "{",
    ]
    for c in COCKPIT_CONFIGS:
        rp1_lines.append(f"\t{c['part_name']} = {c['training_type']}")
    rp1_lines.extend([
        "}",
        "",
        "// 3. Ejection Seat Cost Modifiers",
        "@PART[ROPlanes-Spitfire-Cockpit|ROPlanes-Bf109-Cockpit|ROPlanes-Me262-Cockpit|ROPlanes-MiG15-Cockpit|ROPlanes-F104-Cockpit|ROPlanes-Su27-Cockpit|ROPlanes-F16-Cockpit]:FOR[RP-0]",
        "{",
        "\t@MODULE[ModuleROEjectionSeat]",
        "\t{",
        "\t\t%cost = 35",
        "\t}",
        "}",
        "@PART[ROPlanes-F4-Cockpit|ROPlanes-B29-Cockpit|ROPlanes-B52-Cockpit]:FOR[RP-0]",
        "{",
        "\t@MODULE[ModuleROEjectionSeat]",
        "\t{",
        "\t\t%cost = 70",
        "\t}",
        "}",
        "",
        "// 4. RP-1 Tech Tree Placement & Part Tags (:FOR[xxxRP0])",
    ])
    for c in COCKPIT_CONFIGS:
        rp1_lines.extend([
            f"@PART[{c['part_name']}]:FOR[xxxRP0]",
            "{",
            f"\t%TechRequired = {c['tech_node']}",
            f"\t%cost = {c['cost']}",
            f"\t%entryCost = {c['entry_cost']}",
            "\t%RP0conf = true",
            "\t@description ^=:$: <b><color=green>From ROPlanes+ mod</color></b>",
            "",
            "\t%MODULE[ModuleTagList] { tag = Cockpit }",
            "\tMODULE { name = ModuleNoEVA }",
            "\t%MODULE[ModuleTagList] { tag = NoResourceCostMult }",
            "\tMODULE { name = ModuleNonReentryRated }",
            "\tMODULE { name = ModuleUnpressurizedCockpit }",
            "}",
            "",
        ])

    rp1_lines.extend([
        "// 5. RP-1 Entry Cost Modifiers (:FOR[xxxRP-0])",
        "@ENTRYCOSTMODS:FOR[xxxRP-0]",
        "{",
    ])
    for c in COCKPIT_CONFIGS:
        rp1_lines.append(f"\t{c['part_name']} = {c['entry_cost']}")
    rp1_lines.extend([
        "}",
        "",
        "// 6. Cockpit Service Ceilings / Crew Death Altitudes (:FOR[zRP-0])",
    ])
    for c in COCKPIT_CONFIGS:
        rp1_lines.extend([
            f"@PART[{c['part_name']}]:FOR[zRP-0]",
            "{",
            "\t@MODULE[ModuleUnpressurizedCockpit],*",
            "\t{",
            f"\t\t%crewDeathAltitude = {c['death_alt']}",
            "\t}",
            "}",
            "",
        ])

    with open(os.path.join(compat_root, 'RP1_Cockpits.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(rp1_lines))

    # 3. Kerbalism, FAR, RealAntennas, RemoteTech Compatibility
    compat_lines = [
        "// ============================================================================",
        "// ROPlanesPlus: Kerbalism, FAR, RealAntennas, & RemoteTech Compatibility",
        "// ============================================================================",
        "",
        "// 1. Kerbalism Air Pump Life Support ProcessController",
        f"@PART[{all_names_pipe}]:NEEDS[ProfileRealismOverhaul]:AFTER[RealismOverhaul]",
        "{",
        "\tprocessConfigureExclude = true",
        "\tMODULE",
        "\t{",
        "\t\tname = ProcessController",
        "\t\tresource = _AirPump",
        "\t\ttitle = Air Pump",
        "\t\tcapacity = #$/CrewCapacity$",
        "\t\trunning = true",
        "\t}",
        "}",
        "",
        "// 2. Kerbalism Habitat Volumes, Surface Areas, & Unpressurized Settings",
    ]
    for c in COCKPIT_CONFIGS:
        compat_lines.extend([
            f"@PART[{c['part_name']}]:NEEDS[FeatureHabitat]:AFTER[zzzKerbalism]",
            "{",
            "\t@MODULE[Habitat]",
            "\t{",
            f"\t\t%volume = {c['hab_vol']}",
            f"\t\t%surface = {c['hab_surf']}",
            "\t\t%max_pressure = 0",
            "\t}",
            "}",
            "",
        ])

    compat_lines.extend([
        "// 3. Ferram Aerospace Research (FAR) Mesh Voxelization Override",
        f"@PART[{all_names_pipe}]:AFTER[FerramAerospaceResearch]",
        "{",
        "\t@MODULE[GeometryPartModule]",
        "\t{",
        "\t\t%forceUseMeshes = true",
        "\t}",
        "}",
        "",
        "// 4. RealAntennas Integrated VHF/UHF Aviation Omni Radio",
        f"@PART[{all_names_pipe}]:HAS[!MODULE[ModuleRealAntenna]]:FOR[RealAntennas]",
        "{",
        "\t!MODULE[ModuleDataTransmitter] {}",
        "\t%MODULE[ModuleRealAntenna] { %referenceGain = 1.5 }",
        "}",
        "",
        "// 5. RemoteTech Passive Antenna Fallback",
        f"@PART[{all_names_pipe}]:NEEDS[RemoteTech]:FOR[RealismOverhaul]",
        "{",
        "\tMODULE",
        "\t{",
        "\t\tname = ModuleSPU",
        "\t}",
        "\tMODULE",
        "\t{",
        "\t\tname = ModuleRTAntennaPassive",
        "\t\tTechRequired = start",
        "\t\tOmniRange = 50000",
        "\t\tTRANSMITTER",
        "\t\t{",
        "\t\t\tPacketInterval = 0.4",
        "\t\t\tPacketSize = 0.27",
        "\t\t\tPacketResourceCost = 0.01",
        "\t\t}",
        "\t}",
        "}",
        "",
    ])

    with open(os.path.join(compat_root, 'RO_Kerbalism_FAR_RealAntennas.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(compat_lines))

    # 4. BDArmory: armour and hit points (applies only when BDArmory is installed)
    bda_lines = [
        "// ============================================================================",
        "// ROPlanesPlus: BDArmory compatibility (cockpit hit points and armour)",
        "// HitpointTracker field names from BDArmory Plus. maxSupportedArmor caps the editor",
        "// armour slider; hullType keeps the aluminium airframe.",
        "// ============================================================================",
        "",
    ]
    for c in COCKPIT_CONFIGS:
        bda_lines.extend([
            f"@PART[{c['part_name']}]:NEEDS[BDArmory]:AFTER[BDArmory]",
            "{",
            "\t%MODULE[HitpointTracker]",
            "\t{",
            f"\t\t%maxHitPoints = {c['bda_hp']}",
            f"\t\t%ArmorThickness = {c['bda_armor']}",
            f"\t\t%maxSupportedArmor = {c['bda_max_armor']}",
            "\t\t%hullType = Aluminium",
            "\t\t%ExplodeMode = Never",
            "\t}",
            "}",
            "",
        ])
    with open(os.path.join(compat_root, 'BDArmory_Cockpits.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(bda_lines))

    # 5. TexturesUnlimited: every paint scheme as a TU texture set + a recolourable set
    with open(os.path.join(compat_root, 'TexturesUnlimited_Cockpits.cfg'), 'w', encoding='utf-8') as f:
        f.write(format_tu_config())
    # 6. SimpleRepaint: keep its colour on the fuselage skin (not the glass or the cockpit tub)
    with open(os.path.join(compat_root, 'SimpleRepaint_Cockpits.cfg'), 'w', encoding='utf-8') as f:
        f.write(format_simplerepaint_config())

    generate_propeller_configs(parts_root, compat_root)
    generate_pylon_configs(parts_root, compat_root)
    sanitize_mm_passes(compat_root)
    print(f"Generated {len(COCKPIT_CONFIGS)} cockpit + {len(PROPELLER_CONFIGS)} propeller engine + 1 launch pylon "
          ".cfg files and RP-1/RO/AJE/FAR/Kerbalism patches!")


# ModuleManager: ":FOR[X]" DECLARES mod X as installed, which would switch on every other mod's
# ":NEEDS[X]" patches in games without X (e.g. stripping antennas without RealAntennas, or FAR
# patches without FAR). Our patches therefore never use FOR for a mod we don't own: each one is
# rewritten to run after (or, for AJE, before) that mod's pass and only when its mod is installed.
MM_PASS_RULES = {
    'FerramAerospaceResearch': ('FerramAerospaceResearch', 'AFTER'),
    'RealismOverhaul': ('RealismOverhaul', 'AFTER'),
    'RealAntennas': ('RealAntennas', 'AFTER'),
    'AJE': ('AJE', 'BEFORE'),         # AJE's own FOR/FINAL patches must see ModuleEnginesAJEPropeller
    'RP-0': ('RP-0', 'AFTER'),
    'xxxRP0': ('RP-0', 'AFTER'),       # RP-1's tech-tree pass
    'xxxRP-0': ('RP-0', 'AFTER'),      # RP-1's entry-cost pass
    'zRP-0': ('RP-0', 'AFTER'),        # RP-1's last pass
}


def sanitize_mm_passes(compat_root):
    import re
    pat = re.compile(r':FOR\[([^\]]+)\]')
    for fn in sorted(os.listdir(compat_root)):
        if not fn.endswith('.cfg'):
            continue
        path = os.path.join(compat_root, fn)
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('\n')
        changed = False
        for i, line in enumerate(lines):
            if not line.startswith(('@', '+', '$', '!')):
                continue  # comments and node bodies stay as they are
            m = pat.search(line)
            if not m or m.group(1) not in MM_PASS_RULES:
                continue
            needs, when = MM_PASS_RULES[m.group(1)]
            line = line[:m.start()] + f':{when}[{m.group(1)}]' + line[m.end():]
            nm = re.search(r':NEEDS\[([^\]]+)\]', line)
            if nm is None:
                line += f':NEEDS[{needs}]'
            elif needs not in nm.group(1).replace('|', '&').split('&'):
                line = line[:nm.end(1)] + '&' + needs + line[nm.end(1):]   # one NEEDS clause per patch
            lines[i] = line
            changed = True
        if changed:
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(lines))


def _rgb255(hexstr):
    h = hexstr.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _tu_colour(hexstr, gloss, metal):
    """TU colour value: r,g,b,specular,metallic,detail (0-255; detail 100 = normal panel detail)."""
    r, g, b = _rgb255(hexstr)
    return f"{r},{g},{b},{min(255, int(gloss * 300))},{metal},100"


TU_EXCLUDE = ('windows', 'flagDecal', 'canopyInterior')   # glass, flag and cockpit tub keep their materials


def format_tu_config():
    """TexturesUnlimited support for the cockpits (only active with TU installed).
    The B9 paint switch is replaced by TU's own KSPTextureSwitch. The FIRST (default) set is the recolourable
    Plain White: TU's SSTURecolorGUI only shows its 'Open Recoloring GUI' button while the part's current
    texture set is recolourable, so a fixed default set would hide it. Zones: main = upper surfaces,
    second = lower surfaces, detail = canopy frames, anti-glare panel, radome and intake lip. The historical
    schemes follow as fixed sets (TU/Metallic in stock-spec mode, gloss from the livery alpha). Glass, flag
    decal and cockpit interior keep their own materials. Cockpit Lights still drive _EmissiveColor."""
    out = [
        "// ============================================================================",
        "// ROPlanesPlus: TexturesUnlimited compatibility (generated by generate_configs.py)",
        "// Default paint = 'Plain White (recolourable)': use 'Open Recoloring GUI' in the part menu (editor).",
        "// Zones: main = upper surfaces, second = lower surfaces, detail = canopy frames, anti-glare panel,",
        "// radome and intake lip. The historical schemes follow as fixed sets. Without TU the B9 paint switch",
        "// is used instead. TU-based painters (TURD, Recolour Collection, Lazy Painter) use these sets too.",
        "// ============================================================================",
        "",
    ]
    excl = [f"\t\texcludeMesh = {m}" for m in TU_EXCLUDE]
    presets = {}
    for c in COCKPIT_CONFIGS:
        s = c['spec']
        sid = s['id']
        root = f"ROPlanesPlus/Parts/{sid}/{sid}"
        rec = f"ROPP-{sid}-recolor"
        sets = [rec]
        for lv in s['liveries']:
            if lv['key'] == 'white':
                continue          # the recolourable set is the plain white one
            name = f"ROPP-{sid}-{lv['key']}"
            sets.append(name)
            metal = 0.65 if lv['pattern'] == 'metal' else 0.05
            out += [
                "KSP_TEXTURE_SET:NEEDS[TexturesUnlimited]",
                "{",
                f"\tname = {name}",
                f"\ttitle = {lv['title']}",
                "\trecolorable = false",
                "\tMATERIAL",
                "\t{",
                "\t\tshader = TU/Metallic",
                "\t\tkeyword = TU_STOCK_SPEC",
            ] + excl + [
                f"\t\ttexture = _MainTex, {root}_{lv['key']}",
                f"\t\ttexture = _BumpMap, {root}_NRM",
                f"\t\ttexture = _Emissive, {root}_emissive",
                "\t\tPROPERTY",
                "\t\t{",
                "\t\t\tname = _Metal",
                f"\t\t\tfloat = {metal}",
                "\t\t}",
                "\t\tPROPERTY",
                "\t\t{",
                "\t\t\tname = _Smoothness",
                "\t\t\tfloat = 1.0",
                "\t\t}",
                "\t}",
                "}",
                "",
            ]
            role_cols = [('upper', lv['top']), ('lower', lv['under'] or lv['belly']), ('anti-glare', lv['antiglare']),
                         ('radome', lv['radome']), ('intake lip', lv.get('lip')), ('mottle', lv['mottle'])]
            role_cols += [(f'camo {k + 1}', h) for k, h in enumerate(lv['colors'])]
            for role, h in role_cols:
                if h and h.upper() not in presets:
                    presets[h.upper()] = (f"{s['title'].replace(' Cockpit', '')}: {lv['title']} ({role})",
                                          lv['gloss'], 160 if lv['pattern'] == 'metal' and role == 'upper' else 0)
        white = _tu_colour(CS.PLAIN_WHITE, 0.45, 0)
        out += [
            "KSP_TEXTURE_SET:NEEDS[TexturesUnlimited]",
            "{",
            f"\tname = {rec}",
            "\ttitle = Plain White (recolourable)",
            "\trecolorable = true",
            "\tMATERIAL",
            "\t{",
            "\t\tshader = TU/Metallic",
            "\t\tkeyword = TU_RECOLOR",
        ] + excl + [
            f"\t\ttexture = _MainTex, {root}_paint",
            f"\t\ttexture = _BumpMap, {root}_NRM",
            f"\t\ttexture = _MetallicGlossMap, {root}_metal",
            f"\t\ttexture = _MaskTex, {root}_mask",
            f"\t\ttexture = _Emissive, {root}_emissive",
            "\t\tvector = _DiffuseNorm, 0.5, 0.5, 0.5",
            "\t\tvector = _MetalNorm, 0.5, 0.5, 0.5",
            "\t\tvector = _SmoothnessNorm, 0.5, 0.5, 0.5",
            "\t}",
            "\tCOLORS",
            "\t{",
            f"\t\tmainColor = {white}",
            f"\t\tsecondColor = {white}",
            f"\t\tdetailColor = {white}",
            "\t}",
            "}",
            "",
            f"@PART[{c['part_name']}]:NEEDS[TexturesUnlimited]",
            "{",
            "\t!MODULE[ModuleB9PartSwitch]:HAS[#moduleID[cockpitPaint]] {}",
            "\tMODULE",
            "\t{",
            "\t\tname = KSPTextureSwitch",
            "\t\tsectionName = Paint",
            f"\t\tcurrentTextureSet = {sets[0]}",
        ] + [f"\t\ttextureSet = {n}" for n in sets] + [
            "\t}",
            "\tMODULE",
            "\t{",
            "\t\tname = SSTURecolorGUI",
            "\t}",
            "}",
            "",
        ]
    out += ["// Period colours of every paint scheme, for the TU recolouring window's preset list", ""]
    for k, (h, (title, gloss, metal)) in enumerate(sorted(presets.items())):
        r, g, b = _rgb255(h)
        out += [
            "KSP_COLOR_PRESET:NEEDS[TexturesUnlimited]",
            "{",
            f"\tname = ROPP_{h.lstrip('#')}",
            f"\ttitle = {title}",
            f"\tcolor = {r}, {g}, {b}",
            f"\tspecular = {min(255, int(gloss * 300))}",
            f"\tmetallic = {metal}",
            "}",
            "",
        ]
    out += ["PRESET_COLOR_GROUP:NEEDS[TexturesUnlimited]", "{", "\tname = ROPlanes+ Aircraft"]
    out += [f"\tcolor = ROPP_{h.lstrip('#')}" for h in sorted(presets)]
    out += ["}", ""]
    return '\n'.join(out)


def format_simplerepaint_config():
    """SimpleRepaint (judicator) adds a ModuleB9PartSwitch (moduleID = SimpleRepaint) to every part, whose
    subtypes set _Color in MATERIAL nodes. B9 picks renderers by transform, and a MATERIAL without one
    tints every renderer whose shader has _Color: the canopy glass and the cockpit interior too. After its
    pass we add 'transform = fuselage' to those MATERIAL nodes, so only the skin (incl. canopy frames and
    details, which are part of the fuselage meshes) changes colour. Reforged Materials needs no patch: it
    skips renderers named *window*/*canopy*/*flag* by itself (our windows, canopyInterior and flagDecal).
    With TexturesUnlimited installed SimpleRepaint ignores parts that carry TU's KSPTextureSwitch, so TU's
    recolouring is used instead."""
    names = '|'.join(c['part_name'] for c in COCKPIT_CONFIGS)
    return '\n'.join([
        "// ============================================================================",
        "// ROPlanesPlus: SimpleRepaint compatibility (generated by generate_configs.py)",
        "// SimpleRepaint tints materials through B9PartSwitch; this keeps its colour on the fuselage skin so",
        "// the canopy glass and the cockpit interior are not tinted. The cockpits default to Plain White,",
        "// which SimpleRepaint needs to show its colours properly.",
        "// ============================================================================",
        "",
        f"@PART[{names}]:NEEDS[SimpleRepaint]:AFTER[zzzzzzSimpleRepaint]",
        "{",
        "\t@MODULE[ModuleB9PartSwitch]:HAS[#moduleID[SimpleRepaint]]",
        "\t{",
        "\t\t@SUBTYPE,*",
        "\t\t{",
        "\t\t\t@MATERIAL,*",
        "\t\t\t{",
        "\t\t\t\ttransform = fuselage",
        "\t\t\t}",
        "\t\t}",
        "\t}",
        "}",
        "",
    ])


PROPELLER_CONFIGS = [
    {
        'id': 'proc_prop',
        'part_name': 'ROPlanes-ProcProp',
        'title': 'Procedural Propeller Engine',
        'description': (
            'One engine part for every propeller aircraft: radial, inline or turboprop, single or '
            'contra-rotating. Right-click the part and press Open Engine Workshop (top of the menu) to '
            'pick a historical engine (R-2800, Merlin, Griffon, DB 605, Jumo 213, R-3350, R-4360, T56, '
            'NK-12, PT6 and more) or design your own and see what every change does to performance. '
            'Default: P&W R-2800-18W Double Wasp.'
        ),
        'tags': 'propeller piston radial inline v12 turboprop contra engine workshop merlin griffon r2800 t56 nk12 aje',
        'preset_id': 'R2800', 'arch': 'Radial', 'sub_style': 'A', 'contra': 'false',
        'cowl_dia': 1.34, 'cowl_len': 1.55, 'prop_dia': 4.01, 'blades': 4,
        'planform': 'Wide Paddle', 'spinner': 'Rounded Dome', 'nacelle': 'Firewall Mount',
        'livery': 'US Navy Sea Blue', 'livery_key': 'usn',
        'power_hp': 2100, 'aspiration': '1-Stage 2-Speed', 'crit_alt_km': 8.0, 'max_rpm': 2800,
        'mass': 1.381, 'fuel_name': 'AvGas', 'tech': 'unlockParts', 'entry_cost': 1,
        'aje': dict(displacement=2804.5, compression=6.75, minRPM=2200, maxRPM=2800, gearratio=0.45,
                    BSFC=1.104e-7, coolerEffic=0.35, coolerMin=5, ramAir=0.5, exhaustThrust=1,
                    meredithEffect=0.005, boost0=60, rated0=10, boost1=52.5, rated1=7950, cost1=347,
                    switchAlt=1500, turbo='false', wastegateMP=60, propName='HS6501A-0x4', propDiam=4.01,
                    CtTweak=1.0, CpTweak=1.0),
    },
]


def propeller_cost(p):
    """Same formula as PropellerPhysicsEngine.Evaluate (RP-1 scale)."""
    if p['fuel_name'] == 'Kerosene':
        c = 4.0 + p['power_hp'] * 0.0267
    else:
        c = 8.0 + p['power_hp'] * 0.0085
        if p['contra'] == 'true':
            c *= 1.2
    return int(round(c))


def static_thrust_kn(p):
    """Actuator-disk estimate used for the stock (non-AJE) fallback; matches the plugin."""
    power_w = p['power_hp'] * 745.699872
    area = 0.25 * math.pi * p['prop_dia'] ** 2
    ideal = (2.0 * 1.225 * area * power_w * power_w) ** (1.0 / 3.0)
    fom = 0.74 if p['contra'] == 'true' else 0.70
    return round(ideal * fom * 0.001, 1)


def format_propeller_part_cfg(p):
    top_y = round(p['cowl_len'] * 0.5 + 0.5, 3)
    bottom_y = round(-p['cowl_len'] * 0.5, 3)
    max_thrust = static_thrust_kn(p)

    return f"""PART
{{
	name = {p['part_name']}
	module = Part
	author = ROPlanesPlus

	RSSROConfig = True

	// Shared model + textures for all procedural propeller parts (geometry is rebuilt at runtime)
	MODEL
	{{
		model = ROPlanesPlus/Parts/PropShared/proc_prop
	}}
	scale = 1.0
	rescaleFactor = 1.0

	// +Y = propeller. The plugin moves these nodes to the procedural cowling ends.
	node_stack_bottom = 0.0, {bottom_y}, 0.0, 0.0, -1.0, 0.0, 1
	node_stack_top = 0.0, {top_y}, 0.0, 0.0, 1.0, 0.0, 1
	node_attach = 0.0, 0.0, {round(p['cowl_dia'] * 0.5, 3)}, 0.0, 0.0, -1.0, 1

	TechRequired = {p['tech']}
	entryCost = {p['entry_cost']}
	cost = {propeller_cost(p)}
	category = {'none' if p.get('legacy') else 'Engine'}
	subcategory = 0
	{'TechHidden = True' if p.get('legacy') else '// Shown in the Engine category'}
	title = {('Legacy: ' if p.get('legacy') else '') + p['title']}
	manufacturer = ROPlanes+ Powerplant Division
	description = {p['description']}

	tags = {p['tags']}

	attachRules = 1,1,1,1,0

	mass = {p['mass']}
	dragModelType = default
	maximum_drag = 0.15
	minimum_drag = 0.10
	angularDrag = 1.5
	crashTolerance = 12
	breakingForce = 2500
	breakingTorque = 2500
	maxTemp = 1973.15
	skinMaxTemp = 2200.0

	stagingIcon = LIQUID_ENGINE
	bulkheadProfiles = size1, size2, srf

	// Engine sound and exhaust effects (flames, smoke, start-up smoke, backfires) are produced by
	// ModuleProceduralPropeller at the exhaustPortL/R transforms, so there is no EFFECTS block.

	// First module on purpose: puts the "Open Engine Workshop" button at the top of the part menu.
	MODULE
	{{
		name = ModuleEngineWorkshopButton
	}}

	MODULE
	{{
		name = ModuleEnginesFX
		engineID = ProceduralPropeller
		thrustVectorTransformName = thrustTransform
		exhaustDamage = False
		ignitionThreshold = 0.05
		minThrust = 0.0
		maxThrust = {max_thrust}
		heatProduction = 10
		useEngineResponseTime = True
		engineAccelerationSpeed = 0.8
		engineDecelerationSpeed = 1.2
		PROPELLANT
		{{
			name = {p['fuel_name']}
			ratio = 1.0
			DrawGauge = True
			// Aircraft fuel systems pump from every tank: wing-mounted engines must not depend on
			// crossfeed through wing roots. Balanced draw keeps the centre of gravity steady;
			// tank flow priority still lets drop tanks empty first.
			resourceFlowMode = ALL_VESSEL_BALANCE
		}}
		PROPELLANT
		{{
			name = IntakeAir
			ignoreForIsp = True
			ratio = 14.0
		}}
		atmosphereCurve
		{{
			key = 0 17000 0 0
		}}
		atmChangeFlow = True
		useVelCurve = True
		useAtmCurve = True
		velCurve
		{{
			key = 0.00 1.00 0.00 -0.25
			key = 0.25 0.94 -0.35 -0.45
			key = 0.50 0.78 -0.80 -0.95
			key = 0.70 0.42 -2.10 -2.40
			key = 0.85 0.08 -1.50 -0.80
			key = 0.95 0.01 0.00 0.00
		}}
		atmCurve
		{{
			key = 0.00 0.00 0.00 0.00
			key = 0.08 0.15 2.00 2.00
			key = 0.35 0.92 1.80 0.50
			key = 1.00 1.00 0.10 0.00
		}}
	}}

	MODULE
	{{
		name = ModuleProceduralPropeller
		selectedPreset = {p['preset_id']}
		liveryName = {p['livery']}
		architectureName = {p['arch']}
		subStyleName = {p['sub_style']}
		isTurboprop = {'true' if p['arch'] == 'Turboprop' else 'false'}
		isContraRotating = {p['contra']}
		isPusher = false
		shaftPowerHP = {p['power_hp']}
		aspirationName = {p['aspiration']}
		criticalAltitudeKm = {p['crit_alt_km']}
		maxEngineRPM = {p['max_rpm']}
		propDiameter = {p['prop_dia']}
		bladeCountFloat = {p['blades']}
		bladePlanformName = {p['planform']}
		spinnerStyleName = {p['spinner']}
		cowlDiameter = {p['cowl_dia']}
		cowlLength = {p['cowl_len']}
		nacelleName = {p['nacelle']}
		frontHubTransformName = FrontPropHub
		rearHubTransformName = RearPropHub
		frontBladesTransformName = FrontBladesMesh
		rearBladesTransformName = RearBladesMesh
		frontDiscTransformName = FrontRotorDisc
		rearDiscTransformName = RearRotorDisc
	}}

	// Stock fallback only: AJE's zzWildcards removes the intake and IntakeAir for AJE propellers.
	MODULE
	{{
		name = ModuleResourceIntake
		resourceName = IntakeAir
		checkForOxygen = true
		area = 0.015
		intakeSpeed = 25
		intakeTransformName = thrustTransform
	}}

	RESOURCE
	{{
		name = IntakeAir
		amount = 1.5
		maxAmount = 1.5
	}}

	MODULE
	{{
		name = ModuleAlternator
		RESOURCE
		{{
			name = ElectricCharge
			rate = 3.5
		}}
	}}
}}
"""


# Part folders of the old per-type engine parts (removed; the single procedural part replaces them)
REMOVED_PART_DIRS = ['proc_prop_radial', 'proc_prop_vinline', 'proc_prop_turboprop', 'proc_prop_contra']


def generate_propeller_configs(parts_root, compat_root):
    import shutil
    for old_dir in REMOVED_PART_DIRS:
        path = os.path.join(parts_root, old_dir)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"   removed old part folder Parts/{old_dir}")

    for p in PROPELLER_CONFIGS:
        pdir = os.path.join(parts_root, p['id'])
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, f"{p['id']}.cfg"), 'w', encoding='utf-8') as f:
            f.write(format_propeller_part_cfg(p))

    prop_names_pipe = '|'.join(p['part_name'] for p in PROPELLER_CONFIGS)

    # 1. RO + AJE + FAR
    lines = [
        "// ============================================================================",
        "// ROPlanesPlus: RealismOverhaul, AJE (SolverEngines) & FAR propeller patches",
        "// ============================================================================",
        "",
        "// 1. FAR never voxelizes the spinning hubs, blades or blur discs",
        "@FARPartModuleTransformExceptions:FOR[FerramAerospaceResearch]",
        "{",
        "\tFARPartModuleException",
        "\t{",
        "\t\tPartModuleName = ModuleProceduralPropeller",
        "\t\tTransformException = frontHubTransformName",
        "\t\tTransformException = rearHubTransformName",
        "\t\tTransformException = frontBladesTransformName",
        "\t\tTransformException = rearBladesTransformName",
        "\t\tTransformException = frontDiscTransformName",
        "\t\tTransformException = rearDiscTransformName",
        "\t}",
        "}",
        "",
        "// 2. FAR voxelizes the procedural cowling & spinner colliders",
        f"@PART[{prop_names_pipe}]:AFTER[FerramAerospaceResearch]",
        "{",
        "\t@MODULE[GeometryPartModule]",
        "\t{",
        "\t\t%forceUseColliders = True",
        "\t\t%forceUseMeshes = False",
        "\t\t%ignoreIfNoRenderer = False",
        "\t}",
        "}",
        "",
        "// 3. RealismOverhaul",
        f"@PART[{prop_names_pipe}]:FOR[RealismOverhaul]",
        "{",
        "\t%RSSROConfig = True",
        "\t%maxTemp = 1973.15",
        "\t%skinMaxTemp = 2200.0",
        "}",
        "",
        "// 4. AJE: start-up values for the default engine. ModuleProceduralPropeller rewrites every",
        "//    field and calls CreateEngine() whenever the engine or preset changes.",
    ]
    for p in PROPELLER_CONFIGS:
        a = p['aje']
        lines.extend([
            f"@PART[{p['part_name']}]:FOR[AJE]:NEEDS[AJE]",
            "{",
            "\t@MODULE[ModuleEngines*]",
            "\t{",
            "\t\t@name = ModuleEnginesAJEPropeller",
            "\t\t%IspMultiplier = 1",
            "\t\t%useOxygen = true",
            f"\t\t%power = {p['power_hp']}",
        ])
        for k in ('displacement', 'compression', 'minRPM', 'maxRPM', 'gearratio', 'BSFC', 'coolerEffic',
                  'coolerMin', 'ramAir', 'exhaustThrust', 'meredithEffect', 'boost0', 'rated0', 'boost1',
                  'rated1', 'cost1', 'switchAlt', 'turbo', 'wastegateMP', 'propName', 'propDiam',
                  'CtTweak', 'CpTweak'):
            lines.append(f"\t\t%{k} = {a[k]}")
        lines.extend([
            "\t\t!PROPELLANT,* {}",
            "\t\tPROPELLANT",
            "\t\t{",
            f"\t\t\tname = {p['fuel_name']}",
            "\t\t\tratio = 1.0",
            "\t\t\tDrawGauge = True",
            "\t\t\tresourceFlowMode = ALL_VESSEL_BALANCE",
            "\t\t}",
            "\t}",
            "}",
            "",
        ])
    with open(os.path.join(compat_root, 'RO_AJE_FAR_ProceduralPropellers.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # 2. RP-1: piston parts at the 1950 start; the turboprop base part at matureSupersonic (1952-58).
    #    Inside any part, individual turboprop presets are further gated by their own tech node.
    rp1 = [
        "// ============================================================================",
        "// ROPlanesPlus: RP-1 procedural propeller engines",
        "// Costs follow SXT's AJE engines in RP-1 (Merlin 66 = 20, R-2800 = 24-27, NK-12M = 400);",
        "// the plugin sets the real cost of each design (cylinders, power, contra-props) in the editor.",
        "// ============================================================================",
        "",
    ]
    for p in PROPELLER_CONFIGS:
        rp1.extend([
            f"@PART[{p['part_name']}]:FOR[xxxRP0]",
            "{",
            f"\t%TechRequired = {p['tech']}",
            f"\t%cost = {propeller_cost(p)}",
            f"\t%entryCost = {p['entry_cost']}",
            "\t%RP0conf = true",
            "\t@description ^=:$: <b><color=green>From ROPlanes+ mod</color></b>",
            "}",
            "",
        ])
    rp1.extend(["@ENTRYCOSTMODS:FOR[xxxRP-0]", "{"])
    for p in PROPELLER_CONFIGS:
        rp1.append(f"\t{p['part_name']} = {p['entry_cost']}")
    rp1.extend(["}", ""])
    for p in PROPELLER_CONFIGS:
        rp1.extend([
            f"@PART[{p['part_name']}]:FOR[zRP-0]",
            "{",
            f"\t%TechRequired = {p['tech']}",
            f"\t%entryCost = {p['entry_cost']}",
            "\t%RP0conf = true",
            "}",
            "",
        ])
    with open(os.path.join(compat_root, 'RP1_ProceduralPropellers.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(rp1))


# ---------------------------------------------------------------------------------------------
# Procedural Launch Pylon (ModuleROPPLaunchPylon): air-launch / drop pylon that stays on the carrier
# ---------------------------------------------------------------------------------------------

PYLON_CONFIG = {
    'id': 'proc_pylon',
    'part_name': 'ROPlanes-ProcPylon',
    'title': 'Procedural Launch Pylon',
    # RP-1: air launches were routine from 1946 (B-29 + X-1), so the pylon is a starting part next to
    # the B-29 cockpit and the early X-plane records.
    'tech': 'unlockParts', 'entry_cost': 1,
    'ejection_force': 250,
    'description': (
        'Drop pylon / launch rack for air launches (B-29 + X-1, NB-52 + X-15, mother ship + parasite '
        'fighter) and launch stands. Unlike a radial decoupler it STAYS ON THE PART IT IS MOUNTED TO: '
        'place it on the carrier first, then hang the aircraft from its hook face (surface attach or the '
        'release node). On release only the aircraft drops away. Length, height, thickness, taper, rake, '
        'cross-section (aerofoil / rounded / box) and the hooks are set in the part menu; mass and cost '
        'follow the size. Tip: use "Control From Here" on the aircraft\'s cockpit before the drop and the '
        'camera follows it.'
    ),
    'tags': 'pylon, launch, airlaunch, air-launch, drop, rack, release, hook, mothership, carrier, parasite, '
            'decoupler, separator, x-1, x-15, b-29, b-52, stand, cradle, procedural',
}


def format_pylon_part_cfg(p):
    import generate_pylon_assets as PA
    sh = PA.Shape(PA.DEFAULT_SHAPE)
    mass = PA.pylon_mass()
    cost = int(round(PA.COST_BASE + PA.COST_PER_TON * mass))
    release = (0.0, sh.bottom_centre, sh.height)
    paints = ''
    first = PA.LIVERIES[0][0]
    for key, title, rgb, _gloss, _var in PA.LIVERIES:
        hexcol = '#%02X%02X%02X' % rgb
        paints += (
            "\t\tSUBTYPE\n\t\t{\n"
            f"\t\t\tname = {key}\n"
            f"\t\t\ttitle = {title}\n"
            f"\t\t\tprimaryColor = {hexcol}\n"
            f"\t\t\tsecondaryColor = {hexcol}\n"
            "\t\t\tTEXTURE\n\t\t\t{\n"
            f"\t\t\t\ttexture = ROPlanesPlus/Parts/{p['id']}/ropp_pylon_{key}\n"
            f"\t\t\t\tcurrentTexture = ropp_pylon_{first}\n"
            "\t\t\t\tshaderProperty = _MainTex\n"
            "\t\t\t\ttransform = pylonBody\n"
            "\t\t\t}\n"
            "\t\t}\n"
        )
    return f"""PART
{{
	name = {p['part_name']}
	module = Part
	author = ROPlanesPlus

	RSSROConfig = True

	// Default model + textures from generate_pylon_assets.py; ModuleROPPLaunchPylon rebuilds the
	// geometry from the shape fields at runtime. Do not edit by hand (generate_configs.py).
	MODEL
	{{
		model = ROPlanesPlus/Parts/{p['id']}/{p['id']}
	}}
	scale = 1.0
	rescaleFactor = 1.0

	// +Y forward, +Z down towards the released aircraft. Mount face (surface attach + "mount" node) at
	// z = 0, hook face ("release" node) at z = height. The plugin moves the release node with the shape.
	node_stack_mount = 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0
	node_stack_release = {_vec(release)}, 0.0, 0.0, 1.0, 0
	node_attach = 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0

	TechRequired = {p['tech']}
	entryCost = {p['entry_cost']}
	cost = {cost}
	category = Coupling
	subcategory = 0
	title = {p['title']}
	manufacturer = ROPlanes+ Flight Test Division
	description = {p['description']}

	tags = {p['tags']}

	attachRules = 1,1,1,1,0

	mass = {_fmt(round(mass, 4))}
	dragModelType = default
	maximum_drag = 0.1
	minimum_drag = 0.1
	angularDrag = 1.0
	crashTolerance = 12
	breakingForce = 2500
	breakingTorque = 2500
	maxTemp = 900
	skinMaxTemp = 1000
	skinTempTag = Aluminum
	fuelCrossFeed = False
	stagingIcon = DECOUPLER_HOR
	bulkheadProfiles = srf

	sound_decoupler_fire = decouple

	MODULE
	{{
		name = ModuleROPPLaunchPylon
		ejectionForce = {p['ejection_force']}
		explosiveNodeID = release
		isOmniDecoupler = false
		fxGroupName = decouple
		menuName = Release Aircraft
		stagingEnableText = Release not staged
		stagingDisableText = Release staged
		pylonLength = {_fmt(float(sh.length))}
		pylonHeight = {_fmt(float(sh.height))}
		pylonWidth = {_fmt(float(sh.width))}
		bottomLengthPct = {_fmt(float(sh.bl * 100))}
		bottomWidthPct = {_fmt(float(sh.bw * 100))}
		sweepPct = {_fmt(float(sh.sweep * 100))}
		profileName = Aerofoil
		showHooks = True
		massPerVolume = {PA.MASS_PER_M3}
		baseMass = {PA.MASS_BASE}
		hookMass = {PA.MASS_HOOK}
		baseCost = {PA.COST_BASE}
		costPerTon = {PA.COST_PER_TON}
	}}

	// Off by default; switch on to top up the aircraft's tanks from the carrier before the drop
	MODULE
	{{
		name = ModuleToggleCrossfeed
		crossfeedStatus = false
		toggleEditor = true
		toggleFlight = true
	}}

	MODULE
	{{
		name = ModuleB9PartSwitch
		moduleID = pylonPaint
		switcherDescription = Paint
		switcherDescriptionPlural = Paint schemes
		affectDragCubes = false
		affectFARVoxels = false
		switchInFlight = false
{paints}	}}
}}
"""


def generate_pylon_configs(parts_root, compat_root):
    p = PYLON_CONFIG
    pdir = os.path.join(parts_root, p['id'])
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, f"{p['id']}.cfg"), 'w', encoding='utf-8') as f:
        f.write(format_pylon_part_cfg(p))
    import generate_pylon_assets as PA
    cost = int(round(PA.COST_BASE + PA.COST_PER_TON * PA.pylon_mass()))
    rp1 = [
        "// ============================================================================",
        "// ROPlanesPlus: RP-1 tech tree placement of the Procedural Launch Pylon",
        "// A starting part (unlockParts): air launches were routine from 1946 (B-29 + X-1).",
        "// The plugin sets mass and cost from the pylon's size in the editor.",
        "// ============================================================================",
        "",
        f"@PART[{p['part_name']}]:FOR[xxxRP0]",
        "{",
        f"\t%TechRequired = {p['tech']}",
        f"\t%cost = {cost}",
        f"\t%entryCost = {p['entry_cost']}",
        "\t%RP0conf = true",
        "\t@description ^=:$: <b><color=green>From ROPlanes+ mod</color></b>",
        "}",
        "",
        "@ENTRYCOSTMODS:FOR[xxxRP-0]",
        "{",
        f"\t{p['part_name']} = {p['entry_cost']}",
        "}",
        "",
        f"@PART[{p['part_name']}]:FOR[zRP-0]",
        "{",
        f"\t%TechRequired = {p['tech']}",
        f"\t%entryCost = {p['entry_cost']}",
        "\t%RP0conf = true",
        "}",
        "",
    ]
    with open(os.path.join(compat_root, 'RP1_LaunchPylon.cfg'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(rp1))


if __name__ == '__main__':
    generate_all_configs(os.path.dirname(os.path.abspath(__file__)))
