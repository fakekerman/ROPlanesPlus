#!/usr/bin/env python3
"""
Builds the ROPlanesPlus engine sounds.

Loops that have a recipe in process_recordings.py (radial/V-12 engine loops, turbine whine and
roar, prop_loop, wind) are made from real CC0/CC-BY aircraft recordings in sound_sources/ when
numpy, scipy and ffmpeg are available (44.1 kHz; credits -> Sounds/CREDITS.txt); otherwise, and
for everything else, they are synthesized here (pure standard-library Python, 22.05 kHz).

Output: GameData/ROPlanesPlus/Sounds/*.wav  (16-bit mono). Any other .wav in that folder is
deleted, so the folder always holds exactly the set below.

Loops are rendered into a circular buffer (events and filters wrap around) and every tone has a
whole number of cycles in the 6 s loop, so they repeat without a click. PropellerAudio.cs
crossfades and pitches them from the live engine state; each loop is rendered at a fixed
reference that must match the constants there:
  <family>_idle            : 800 rpm   (family: radial = 18 cylinders, vinline = V-12; the mixer
  <family>_mid/_mid_off    : 1600 rpm   pitches by firing frequency, so other cylinder counts
  <family>_high/_high_off  : 2600 rpm   reuse them)  _off = throttle closed: soft, uneven firing
                                        with afterfire crackle and pops
  piston_crank       : starter turning the engine, 20 compression strokes per second
  wind               : airflow over the airframe at 120 m/s
  starter_whine      : starter motor at full speed
  supercharger_whine : impeller at 2600 engine rpm (low blower gear)
  turbine_whine      : gas generator at 100 %
  turbine_roar       : combustion and exhaust at full power
  turbine_igniter    : igniter plugs snapping, 4 per second
  prop_loop          : blade-passage frequency 80 Hz
  prop_rasp          : blade-passage frequency 80 Hz, transonic blade tips
  prop_swish         : blade-passage frequency 8 Hz (slowly turning propeller)
One-shots: piston_cough, exhaust_pop, backfire, starter_engage, prop_stop, prop_strike,
prop_strike_water, turbine_lightoff.
"""

import math
import os
import random
import struct
import wave

SR = 22050
LOOP_SEC = 6.0
LOOP_N = int(LOOP_SEC * SR)
TWO_PI = 2.0 * math.pi

# Reference speeds (keep in sync with PropellerAudio.cs)
REF_IDLE = 800.0
REF_MID = 1600.0
REF_HIGH = 2600.0
REF_CRANK_HZ = 20.0
REF_BPF = 80.0
REF_SWISH_BPF = 8.0


# ------------------------------------------------------------------------------
# DSP helpers
# ------------------------------------------------------------------------------

def biquad_coeffs(kind, f0, q):
    w0 = TWO_PI * f0 / SR
    cw = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    if kind == 'lp':
        b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
    elif kind == 'hp':
        b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
    else:  # band-pass, 0 dB peak
        b0, b1, b2 = alpha, 0.0, -alpha
    a0 = 1 + alpha
    a1 = -2 * cw
    a2 = 1 - alpha
    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def biquad(x, kind, f0, q=0.707, circular=False):
    """Second-order filter. circular=True runs two passes so the loop seam carries the state."""
    b0, b1, b2, a1, a2 = biquad_coeffs(kind, f0, q)
    n = len(x)
    y = [0.0] * n
    x1 = x2 = y1 = y2 = 0.0
    passes = 2 if circular else 1
    for p in range(passes):
        last = p == passes - 1
        for i in range(n):
            xi = x[i]
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1 = x1, xi
            y2, y1 = y1, yi
            if last:
                y[i] = yi
    return y


def noise(n, rng):
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def add_into(buf, start, samples, gain=1.0, circular=False):
    n = len(buf)
    for i, s in enumerate(samples):
        j = start + i
        if circular:
            buf[j % n] += s * gain
        elif 0 <= j < n:
            buf[j] += s * gain


def mix(*parts):
    """mix((gain, signal), ...) -> sum."""
    n = len(parts[0][1])
    out = [0.0] * n
    for g, sig in parts:
        for i in range(n):
            out[i] += g * sig[i]
    return out


def rms(x):
    return math.sqrt(sum(v * v for v in x) / max(1, len(x)))


def peak(x):
    return max(1e-12, max(abs(v) for v in x))


def norm_peak(x, target=1.0):
    g = target / peak(x)
    return [v * g for v in x]


def normalize_rms(x, target):
    r = rms(x)
    if r < 1e-9:
        return x
    g = target / r
    return [v * g for v in x]


def soft_clip(x, drive=1.0):
    k = 1.0 / math.tanh(drive)
    return [math.tanh(v * drive) * k for v in x]


def fade(x, fade_in=0.0, fade_out=0.0):
    n = len(x)
    fi = int(fade_in * SR)
    fo = int(fade_out * SR)
    out = list(x)
    for i in range(min(fi, n)):
        out[i] *= i / float(fi)
    for i in range(min(fo, n)):
        out[n - 1 - i] *= i / float(fo)
    return out


def decay(n, tau, delay=0.0):
    d = int(delay * SR)
    return [0.0 if i < d else math.exp(-(i - d) / (tau * SR)) for i in range(n)]


def tone(n, freq, amp=1.0, phase=0.0):
    w = TWO_PI * freq / SR
    return [amp * math.sin(w * i + phase) for i in range(n)]


def loop_freq(f):
    """Nearest frequency with a whole number of cycles in the loop."""
    return round(f * LOOP_SEC) / LOOP_SEC


def write_wav(path, samples, sr=SR):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if hasattr(samples, 'tolist'):  # numpy array from process_recordings
        samples = samples.tolist()
    pk = peak(samples)
    scale = 0.95 / pk if pk > 0.95 else 1.0
    frames = bytearray()
    for v in samples:
        frames.extend(struct.pack('<h', int(max(-1.0, min(1.0, v * scale)) * 32767)))
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


# ------------------------------------------------------------------------------
# Building blocks
# ------------------------------------------------------------------------------

def exhaust_pulse(rng, length_s, body_hz, body_q, crack_hz, w_body, w_crack, w_thump,
                  thump_hz, thump_tau, exc_tau=0.0015):
    """One cylinder's exhaust blast: an excitation (kick + short noise burst) rings the exhaust
    pipe (band-pass 'body'), a bright crack escapes the stub, and the gas slug gives a low thump."""
    n = int(length_s * SR)
    exc = [rng.uniform(-1.0, 1.0) * math.exp(-i / (exc_tau * SR)) for i in range(n)]
    exc[0] += 2.5
    exc[1] += 1.2
    body = norm_peak(biquad(exc, 'bp', body_hz * rng.uniform(0.9, 1.1), body_q))
    crack = norm_peak(biquad(exc, 'bp', crack_hz * rng.uniform(0.85, 1.15), 0.9))
    tf = thump_hz * rng.uniform(0.93, 1.07)
    att = max(2, int(0.0005 * SR))
    tail = max(2, int(0.25 * n))
    out = []
    for i in range(n):
        t = i / SR
        v = (w_body * body[i] + w_crack * crack[i] * math.exp(-t / 0.004)
             + w_thump * math.sin(TWO_PI * tf * t) * math.exp(-t / thump_tau))
        if i < att:
            v *= i / att
        if i > n - tail:
            v *= (n - i) / tail
        out.append(v)
    return out


def pulse_bank(rng, count, **kw):
    return [exhaust_pulse(rng, **kw) for _ in range(count)]


def firing_train(buf, rng, bank, cylinders, rpm, cyl_amps, event_var, jitter, skip=0.0):
    """Exhaust pulses of a 4-stroke engine at constant rpm, written circularly into buf."""
    n = len(buf)
    interval = 120.0 / (rpm * cylinders)
    count = int(round((n / SR) / interval))
    for k in range(count):
        if skip > 0.0 and rng.random() < skip:
            continue
        cyl = k % cylinders
        t = k * interval + rng.uniform(-jitter, jitter) * interval
        a = cyl_amps[cyl] * (1.0 + rng.uniform(-event_var, event_var))
        add_into(buf, int(round(t * SR)) % n, bank[rng.randrange(len(bank))], a, circular=True)


def tick_train(buf, rng, rate_hz, amp, tick_hz=3200.0, var=0.5):
    """Mechanical clatter (valve train, gears): tiny bright ticks at a steady rate."""
    n = len(buf)
    count = int(round(rate_hz * LOOP_SEC))
    tick = [rng.uniform(-1, 1) * math.exp(-i / (0.0004 * SR)) for i in range(int(0.004 * SR))]
    tick = norm_peak(biquad(tick, 'bp', tick_hz, 1.5))
    for k in range(count):
        t = (k + rng.uniform(-0.2, 0.2)) / rate_hz
        add_into(buf, int(t * SR) % n, tick, amp * (1.0 + rng.uniform(-var, var)), circular=True)


def finish_loop(x, hp=28.0, lp=None, target=0.28, drive=1.4):
    out = biquad(x, 'hp', hp, 0.7, circular=True)
    if lp:
        out = biquad(out, 'lp', lp, 0.7, circular=True)
    return soft_clip(normalize_rms(out, target), drive)


# ------------------------------------------------------------------------------
# Piston engine loops (radial / V-inline at idle, mid and high rpm, on and off load)
# ------------------------------------------------------------------------------
#
# Each cylinder's exhaust blow-down is a pressure bump (fast rise, exponential decay) that
# rings its exhaust pipe / stub and, under load, escapes with a bright crack. The listener
# hears the near bank / near collector louder than the far one, so the firing train carries a
# strong rhythm at crankshaft and cycle rate (the "throb"). Turbulent jet noise from the
# exhaust ("roar") is modulated by the same firing train, which gives the growl. Closed
# throttle (_off): soft, uneven firing, some cylinders missing, afterfire crackle and pops.

def onepole_lp(x, fc, circular=False):
    a = 1.0 - math.exp(-TWO_PI * fc / SR)
    n = len(x)
    y = [0.0] * n
    s = 0.0
    for p in range(2 if circular else 1):
        for i in range(n):
            s += a * (x[i] - s)
            y[i] = s
    return y


def blowdown_pulse(rng, length_s, rise, decay, pipe_hz, pipe_q, crack_hz, wb, wp, wc):
    n = int(length_s * SR)
    rise *= rng.uniform(0.85, 1.15)
    decay *= rng.uniform(0.85, 1.15)
    bump = [(1.0 - math.exp(-(i / SR) / rise)) * math.exp(-(i / SR) / decay) for i in range(n)]
    turb = [rng.uniform(-1.0, 1.0) * bump[i] for i in range(n)]
    exc = [bump[i] - (bump[i - 1] if i else 0.0) for i in range(n)]
    exc = norm_peak(exc)
    turb = norm_peak(turb)
    exc = [exc[i] + 0.35 * turb[i] for i in range(n)]
    pipe = norm_peak(biquad(exc, 'bp', pipe_hz * rng.uniform(0.9, 1.1), pipe_q))
    crk = [rng.uniform(-1.0, 1.0) * math.exp(-i / (0.0012 * SR)) for i in range(n)]
    crk = norm_peak(biquad(crk, 'bp', crack_hz * rng.uniform(0.85, 1.15), 0.9))
    bump = norm_peak(bump)
    tail = max(2, n // 4)
    out = []
    for i in range(n):
        v = wb * bump[i] + wp * pipe[i] + wc * crk[i]
        if i > n - tail:
            v *= (n - i) / tail
        out.append(v)
    return out


PISTON = {
    # Radial: 18 big cylinders into collector rings -> deep, round, boomy roar
    'radial': {
        'cyl': 18, 'seed': 1337,
        'idle': dict(len=0.050, rise=0.0012, decay=0.0060, pipe=160.0, q=4.0, crack=900.0, wb=1.0, wp=0.7, wc=0.18,
                     var=0.25, jit=0.030, skip=0.02, roar=350.0, roar_amt=0.50, depth=0.60, lp=2400.0, target=0.22),
        'mid': dict(len=0.035, rise=0.0008, decay=0.0042, pipe=190.0, q=3.5, crack=1200.0, wb=1.0, wp=0.7, wc=0.30,
                    var=0.12, jit=0.012, skip=0.0, roar=500.0, roar_amt=0.60, depth=0.55, lp=3000.0, target=0.26),
        'mid_off': dict(len=0.030, rise=0.0016, decay=0.0035, pipe=190.0, q=3.0, crack=1000.0, wb=0.8, wp=0.5, wc=0.08,
                        var=0.45, jit=0.030, skip=0.12, roar=400.0, roar_amt=0.35, depth=0.30, lp=2600.0, target=0.17,
                        crackle=8.0, pops=1.0),
        'high': dict(len=0.025, rise=0.0005, decay=0.0028, pipe=230.0, q=3.0, crack=1600.0, wb=1.0, wp=0.7, wc=0.45,
                     var=0.08, jit=0.006, skip=0.0, roar=700.0, roar_amt=0.75, depth=0.50, lp=3800.0, target=0.28),
        'high_off': dict(len=0.022, rise=0.0014, decay=0.0022, pipe=230.0, q=3.0, crack=1300.0, wb=0.8, wp=0.5, wc=0.10,
                         var=0.45, jit=0.020, skip=0.15, roar=550.0, roar_amt=0.35, depth=0.30, lp=3400.0, target=0.19,
                         crackle=22.0, pops=2.5),
    },
    # V-12: short ejector stubs -> crisp, raspy, crackling growl
    'vinline': {
        'cyl': 12, 'seed': 4242,
        'idle': dict(len=0.045, rise=0.0009, decay=0.0070, pipe=260.0, q=4.5, crack=1700.0, wb=0.9, wp=0.8, wc=0.45,
                     var=0.25, jit=0.025, skip=0.02, roar=500.0, roar_amt=0.45, depth=0.60, lp=3500.0, target=0.22),
        'mid': dict(len=0.032, rise=0.0006, decay=0.0045, pipe=300.0, q=4.0, crack=2200.0, wb=0.9, wp=0.8, wc=0.70,
                    var=0.12, jit=0.010, skip=0.0, roar=800.0, roar_amt=0.55, depth=0.55, lp=4800.0, target=0.26),
        'mid_off': dict(len=0.028, rise=0.0014, decay=0.0038, pipe=300.0, q=3.5, crack=1800.0, wb=0.8, wp=0.6, wc=0.25,
                        var=0.45, jit=0.030, skip=0.12, roar=600.0, roar_amt=0.30, depth=0.30, lp=4000.0, target=0.17,
                        crackle=10.0, pops=1.2),
        'high': dict(len=0.024, rise=0.0004, decay=0.0030, pipe=340.0, q=3.0, crack=2600.0, wb=0.85, wp=0.8, wc=0.95,
                     var=0.07, jit=0.005, skip=0.0, roar=1100.0, roar_amt=0.70, depth=0.50, lp=6000.0, target=0.28),
        'high_off': dict(len=0.022, rise=0.0012, decay=0.0025, pipe=340.0, q=3.0, crack=2200.0, wb=0.8, wp=0.6, wc=0.30,
                         var=0.45, jit=0.020, skip=0.15, roar=800.0, roar_amt=0.30, depth=0.30, lp=5000.0, target=0.19,
                         crackle=26.0, pops=3.0),
    },
}
BAND_RPM = {'idle': REF_IDLE, 'mid': REF_MID, 'mid_off': REF_MID, 'high': REF_HIGH, 'high_off': REF_HIGH}


def piston_loop(kind, band):
    spec = PISTON[kind]
    p = spec[band]
    rpm = BAND_RPM[band]
    rng = random.Random(spec['seed'] * 7 + sorted(BAND_RPM).index(band))
    cyl = spec['cyl']
    n = LOOP_N
    interval = 120.0 / (rpm * cyl)
    count = int(round(LOOP_SEC / interval))

    # Static per-cylinder loudness: where each cylinder's exhaust is relative to the listener
    if kind == 'radial':
        # firing order steps two cylinders round each row; two collectors, one on each side
        cyl_amp = [0.70 + 0.30 * math.cos(TWO_PI * ((2 * k) % cyl) / cyl) + rng.uniform(-0.08, 0.08) for k in range(cyl)]
    else:
        # banks fire alternately; the near bank's stubs are much louder than the far bank's
        cyl_amp = [(1.0 if k % 2 == 0 else 0.6) + rng.uniform(-0.1, 0.1) for k in range(cyl)]

    pulses = [blowdown_pulse(rng, p['len'], p['rise'], p['decay'], p['pipe'], p['q'], p['crack'],
                             p['wb'], p['wp'], p['wc']) for _ in range(12)]
    # smooth bump per firing for the roar modulation
    bw = max(8, int(interval * 1.6 * SR))
    bump = [math.sin(math.pi * i / bw) ** 2 for i in range(bw)]

    drift = norm_peak(biquad(noise(n, rng), 'lp', 2.5, 0.7, circular=True))  # cycle-to-cycle combustion spread
    buf = [0.0] * n
    env = [0.0] * n
    for k in range(count):
        if p['skip'] > 0.0 and rng.random() < p['skip']:
            continue
        c = k % cyl
        t = (k + rng.uniform(-p['jit'], p['jit'])) * interval
        start = int(round(t * SR)) % n
        a = max(0.05, cyl_amp[c] * (1.0 + rng.gauss(0.0, p['var'])) * (1.0 + 0.12 * drift[start]))
        add_into(buf, start, pulses[rng.randrange(len(pulses))], a, circular=True)
        add_into(env, start, bump, a, circular=True)

    if 'crackle' in p:
        crackles = [blowdown_pulse(rng, 0.016, 0.0002, 0.0009, 1300.0, 2.0, 3000.0, 0.2, 0.6, 1.2) for _ in range(10)]
        pops = [blowdown_pulse(rng, 0.09, 0.0006, 0.0060, 420.0, 3.0, 2200.0, 1.0, 0.9, 1.0) for _ in range(5)]
        t = 0.0
        while t < LOOP_SEC:
            add_into(buf, int(t * SR), crackles[rng.randrange(10)], 0.3 + 1.0 * rng.random() ** 3, circular=True)
            t += rng.expovariate(p['crackle'])
        t = rng.uniform(0.0, 0.4)
        while t < LOOP_SEC:
            add_into(buf, int(t * SR), pops[rng.randrange(5)], rng.uniform(1.2, 2.0), circular=True)
            t += rng.expovariate(p['pops'])

    env = norm_peak(env)
    roar = norm_peak(biquad(noise(n, rng), 'bp', p['roar'], 0.7, circular=True))
    low = norm_peak(biquad(noise(n, rng), 'lp', rpm / 60.0 * 2.0, 0.8, circular=True))
    tick_train(buf, rng, cyl * 2 * rpm / 120.0, 0.04, 3400.0 if kind == 'radial' else 4200.0)
    depth = p['depth']
    out = []
    for i in range(n):
        m = 1.0 - depth + depth * env[i]
        out.append(buf[i] + p['roar_amt'] * roar[i] * m + 0.25 * low[i] * m)
    out = onepole_lp(out, p['lp'], circular=True)
    out = biquad(out, 'hp', 30.0, 0.7, circular=True)
    return soft_clip(normalize_rms(out, p['target']), 1.15)


def wind_loop():
    """Airflow over canopy and airframe at 120 m/s: broadband rush with slow gusts and flutter."""
    rng = random.Random(4711)
    n = LOOP_N
    low = norm_peak(biquad(noise(n, rng), 'lp', 180.0, 0.7, circular=True))
    mid = norm_peak(biquad(noise(n, rng), 'bp', 650.0, 0.5, circular=True))
    high = norm_peak(biquad(noise(n, rng), 'hp', 2800.0, 0.7, circular=True))
    whistle = norm_peak(biquad(noise(n, rng), 'bp', 1700.0, 10.0, circular=True))
    gust = norm_peak(biquad(noise(n, rng), 'lp', 0.35, 0.7, circular=True))
    flutter = norm_peak(biquad(noise(n, rng), 'lp', 6.0, 0.7, circular=True))
    out = []
    for i in range(n):
        g = 1.0 + 0.3 * gust[i]
        out.append(g * (1.4 * low[i] + mid[i] * (1.0 + 0.15 * flutter[i]) + 0.2 * high[i])
                   + 0.06 * whistle[i] * (0.5 + 0.5 * gust[i]))
    return finish_loop(out, hp=25.0, target=0.24, drive=1.05)


def piston_crank():
    """Starter turning a cold engine: a 'chuff-chug' on every compression stroke and gear rattle.
    No motor tone of its own: the starter_whine layer is the motor. This loop is played faster for
    more cylinders (by compression strokes per second), so a motor hum in it landed next to the
    starter whine on big radials (e.g. 173 vs 202 Hz) and the two beat into a buzz; it also had to
    stay in step between engines (its pitch sagged on every stroke), now it needn't."""
    rng = random.Random(77)
    n = LOOP_N
    buf = [0.0] * n
    count = int(REF_CRANK_HZ * LOOP_SEC)
    chugs = []
    for _ in range(6):
        m = int(0.12 * SR)
        exc = [rng.uniform(-1, 1) * math.exp(-i / (0.02 * SR)) for i in range(m)]
        chuff = norm_peak(biquad(exc, 'bp', rng.uniform(520, 700), 1.0))
        clank = norm_peak(biquad([rng.uniform(-1, 1) * math.exp(-i / (0.0015 * SR)) for i in range(m)],
                                 'bp', 2700.0, 2.5))
        f = rng.uniform(50.0, 60.0)
        p = []
        for i in range(m):
            tt = i / SR
            v = (1.0 * math.sin(TWO_PI * f * tt) * math.exp(-tt / 0.035) + 0.55 * chuff[i]
                 + 0.18 * clank[i])
            if i < 30:
                v *= i / 30.0
            if i > m - 200:
                v *= (m - i) / 200.0
            p.append(v)
        chugs.append(p)
    for k in range(count):
        t = (k + rng.uniform(-0.06, 0.06)) / REF_CRANK_HZ
        add_into(buf, int(t * SR) % n, chugs[rng.randrange(6)], rng.uniform(0.8, 1.15), circular=True)
    rattle = norm_peak(biquad(noise(n, rng), 'bp', 1800.0, 2.0, circular=True))
    out = []
    for i in range(n):
        t = i / SR
        load = 0.5 + 0.5 * math.cos(TWO_PI * REF_CRANK_HZ * t)
        out.append(buf[i] + 0.06 * rattle[i] * (0.4 + 0.6 * load))
    return finish_loop(out, hp=35.0, lp=6000.0, target=0.26, drive=1.3)


def starter_whine():
    """Electric / inertia starter at full speed: motor tone + harmonics, gear mesh whine, brushes."""
    rng = random.Random(15)
    n = LOOP_N
    brush = norm_peak(biquad(noise(n, rng), 'hp', 3500.0, 0.7, circular=True))
    f = loop_freq(240.0)
    g = loop_freq(1200.0)
    out = []
    for i in range(n):
        t = i / SR
        am = 1.0 + 0.08 * math.sin(TWO_PI * t / LOOP_SEC * 2)
        ph = TWO_PI * f * t
        v = am * (0.5 * math.sin(ph) + 0.25 * math.sin(2 * ph) + 0.14 * math.sin(3 * ph)
                  + 0.30 * math.sin(TWO_PI * g * t) + 0.08 * math.sin(TWO_PI * 2 * g * t))
        out.append(v + 0.035 * brush[i])
    return finish_loop(out, hp=60.0, target=0.22, drive=1.2)


def supercharger_whine():
    """Centrifugal impeller at 2600 engine rpm: a clean high whine plus air rush."""
    rng = random.Random(23)
    n = LOOP_N
    air = norm_peak(biquad(noise(n, rng), 'bp', 3200.0, 1.5, circular=True))
    f = loop_freq(2600.0)
    sub = loop_freq(2600.0 * 2.0 / 3.0)
    vib_rate = 1.0 / LOOP_SEC
    beta = 6.0 / vib_rate
    out = []
    for i in range(n):
        t = i / SR
        ph = TWO_PI * f * t + beta * math.sin(TWO_PI * vib_rate * t)
        v = (math.sin(ph) + 0.22 * math.sin(2 * ph) + 0.15 * math.sin(TWO_PI * sub * t)
             + 0.35 * air[i])
        out.append(v)
    return finish_loop(out, hp=400.0, target=0.22, drive=1.1)


# ------------------------------------------------------------------------------
# Turboprop loops
# ------------------------------------------------------------------------------

def turbine_whine():
    """Gas generator at 100 %: compressor blade-passage tones (two close ones beat slowly),
    shaft hum and high-frequency air."""
    rng = random.Random(777)
    n = LOOP_N
    hiss = norm_peak(biquad(noise(n, rng), 'bp', 3500.0, 1.2, circular=True))
    air = norm_peak(biquad(noise(n, rng), 'hp', 6000.0, 0.7, circular=True))
    tones = [(225.0, 0.25), (450.0, 0.12), (1450.0, 0.20), (2900.0, 1.0), (2903.0 + 1.0 / 3.0, 0.6),
             (4350.0, 0.35), (5800.0, 0.15), (7250.0, 0.06)]
    tones = [(loop_freq(f), a) for f, a in tones]
    phases = [rng.uniform(0, TWO_PI) for _ in tones]
    out = []
    for i in range(n):
        t = i / SR
        v = 0.0
        for (f, a), p in zip(tones, phases):
            v += a * math.sin(TWO_PI * f * t + p)
        out.append(0.45 * v + 0.30 * hiss[i] + 0.10 * air[i])
    return finish_loop(out, hp=80.0, target=0.24, drive=1.15)


def turbine_roar():
    """Combustion + exhaust at full power: broadband roar with a slow, random surge."""
    rng = random.Random(778)
    n = LOOP_N
    low = norm_peak(biquad(noise(n, rng), 'lp', 140.0, 0.8, circular=True))
    mid = norm_peak(biquad(noise(n, rng), 'bp', 520.0, 0.6, circular=True))
    upp = norm_peak(biquad(noise(n, rng), 'bp', 1500.0, 0.8, circular=True))
    hiss = norm_peak(biquad(noise(n, rng), 'hp', 3000.0, 0.7, circular=True))
    lfo = norm_peak(biquad(noise(n, rng), 'lp', 1.5, 0.7, circular=True))
    out = []
    for i in range(n):
        m = 1.0 + 0.15 * lfo[i]
        out.append(m * (1.5 * low[i] + 1.3 * mid[i] + 0.45 * upp[i] + 0.15 * hiss[i]))
    return finish_loop(out, hp=25.0, target=0.26, drive=1.3)


def turbine_igniter():
    """Two high-energy igniter plugs snapping alternately, 4 snaps per second."""
    rng = random.Random(5)
    n = LOOP_N
    buf = [0.0] * n
    m = int(0.03 * SR)
    for k in range(int(4 * LOOP_SEC)):
        exc = [rng.uniform(-1, 1) * math.exp(-i / (0.0004 * SR)) for i in range(m)]
        snap = norm_peak(biquad(exc, 'hp', 2500.0, 0.7))
        ring = [math.sin(TWO_PI * 3300.0 * i / SR) * math.exp(-i / (0.004 * SR)) for i in range(m)]
        zap = norm_peak(biquad(exc, 'bp', 6000.0, 2.0))
        tick = [snap[i] + 0.5 * ring[i] + 0.3 * zap[i] for i in range(m)]
        add_into(buf, int(k * SR / 4.0), tick, 1.0 if k % 2 == 0 else 0.75, circular=True)
    hum = norm_peak(biquad(noise(n, rng), 'bp', 400.0, 3.0, circular=True))
    out = [buf[i] + 0.02 * hum[i] for i in range(n)]
    return finish_loop(out, hp=200.0, target=0.12, drive=1.0)


# ------------------------------------------------------------------------------
# Propeller loops
# ------------------------------------------------------------------------------

def prop_loop():
    """Blade passage at 80 Hz (four blades at 1200 rpm): harmonic thrum, broadband noise whopped
    by each blade, and small blade-to-blade differences that put a once-per-revolution beat on it."""
    rng = random.Random(99)
    n = LOOP_N
    whoosh = biquad(noise(n, rng), 'bp', 520.0, 0.7, circular=True)
    hiss = biquad(noise(n, rng), 'bp', 1600.0, 0.8, circular=True)
    rumble = biquad(noise(n, rng), 'lp', 120.0, 0.8, circular=True)
    phases = [rng.uniform(0, TWO_PI) for _ in range(18)]
    rev = REF_BPF / 4.0
    out = []
    for i in range(n):
        t = i / SR
        ph = TWO_PI * REF_BPF * t
        buzz = 0.0
        for k in range(1, 18):
            buzz += math.sin(k * ph + phases[k]) / (k ** 1.25)
        beat = 1.0 + 0.08 * math.sin(TWO_PI * rev * t + 0.7) + 0.04 * math.sin(TWO_PI * 2 * rev * t + 2.1)
        blade = 0.5 + 0.5 * math.cos(ph)
        whop = (whoosh[i] + 0.35 * hiss[i]) * (0.3 + 0.7 * blade ** 4)
        out.append(beat * (0.55 * buzz + 1.5 * whop) + 0.8 * rumble[i])
    out = onepole_lp(out, 3200.0, circular=True)
    return soft_clip(normalize_rms(out, 0.26), 1.15)


def prop_rasp():
    """Blade tips near Mach 1: each blade passage becomes a sharp shock -> harsh buzz-saw rasp."""
    rng = random.Random(100)
    n = LOOP_N
    crackle = biquad(noise(n, rng), 'hp', 2500.0, 0.7, circular=True)
    whoosh = biquad(noise(n, rng), 'bp', 900.0, 0.8, circular=True)
    harmonics = 90
    phases = [rng.uniform(-0.4, 0.4) for _ in range(harmonics + 1)]
    out = []
    for i in range(n):
        t = i / SR
        ph = TWO_PI * REF_BPF * t
        buzz = 0.0
        for k in range(1, harmonics + 1):
            buzz += math.sin(k * ph + phases[k]) / (k ** 0.6)
        gate = (0.5 + 0.5 * math.cos(ph)) ** 10
        out.append(0.10 * buzz + 1.2 * crackle[i] * gate + 0.5 * whoosh[i])
    out = biquad(out, 'lp', 7000.0, 0.7, circular=True)
    return soft_clip(normalize_rms(out, 0.24), 1.6)


def prop_swish():
    """A slowly turning propeller: a separate 'whoosh' for every blade going past (8 per second)."""
    rng = random.Random(101)
    n = LOOP_N
    buf = [0.0] * n
    width = int(0.11 * SR)
    for k in range(int(REF_SWISH_BPF * LOOP_SEC)):
        exc = noise(width, rng)
        w = norm_peak(biquad(exc, 'bp', rng.uniform(380, 470), 0.9))
        ev = []
        for i in range(width):
            win = 0.5 - 0.5 * math.cos(TWO_PI * i / (width - 1))
            ev.append(win * (w[i] + 0.5 * math.sin(TWO_PI * 42.0 * i / SR)))
        start = int((k / REF_SWISH_BPF) * SR) - width // 2
        add_into(buf, start % n, ev, rng.uniform(0.9, 1.1), circular=True)
    air = norm_peak(biquad(noise(n, rng), 'bp', 700.0, 0.6, circular=True))
    out = [buf[i] + 0.05 * air[i] for i in range(n)]
    return finish_loop(out, hp=30.0, lp=5000.0, target=0.22, drive=1.1)


# ------------------------------------------------------------------------------
# One-shots
# ------------------------------------------------------------------------------

def piston_cough():
    """A few cylinders firing on a cold, rich engine: a loud bark with a stutter after it."""
    rng = random.Random(2024)
    dur = 0.8
    n = int(dur * SR)
    buf = [0.0] * n
    big = exhaust_pulse(rng, 0.25, 210.0, 3.0, 1500.0, 1.0, 0.9, 1.3, 62.0, 0.07, exc_tau=0.004)
    add_into(buf, 0, big, 1.0)
    for delay, a in ((0.065, 0.55), (0.150, 0.35)):
        p = exhaust_pulse(rng, 0.18, 230.0, 3.0, 1700.0, 1.0, 0.8, 1.0, 70.0, 0.04, exc_tau=0.003)
        add_into(buf, int(delay * SR), p, a * rng.uniform(0.8, 1.2))
    tail = biquad(noise(n, rng), 'lp', 300.0, 0.8)
    env = decay(n, 0.18, 0.01)
    tail = norm_peak(tail)
    out = [buf[i] + 0.35 * tail[i] * env[i] for i in range(n)]
    out = biquad(out, 'hp', 30.0, 0.7)
    return soft_clip(fade(norm_peak(out, 0.9), 0.0, 0.2), 1.4)


def exhaust_pop():
    """Afterfire in the exhaust stubs: a sharp crack with a short ring."""
    rng = random.Random(404)
    n = int(0.35 * SR)
    buf = [0.0] * n
    add_into(buf, 0, exhaust_pulse(rng, 0.2, 900.0, 3.0, 2600.0, 0.8, 1.6, 0.6, 90.0, 0.012,
                                   exc_tau=0.0007), 1.0)
    t = 0.03
    while t < 0.2:
        add_into(buf, int(t * SR), exhaust_pulse(rng, 0.015, 1500.0, 2.0, 3200.0, 0.4, 1.0, 0.0,
                                                 100.0, 0.005, exc_tau=0.0004), rng.uniform(0.1, 0.35))
        t += rng.uniform(0.015, 0.05)
    return soft_clip(fade(norm_peak(biquad(buf, 'hp', 40.0), 0.9), 0.0, 0.08), 1.3)


def backfire():
    rng = random.Random(8)
    dur = 1.3
    n = int(dur * SR)
    buf = [0.0] * n
    bang = biquad(noise(n, rng), 'lp', 1800.0, 0.7)
    for i in range(n):
        t = i / SR
        buf[i] += 1.6 * bang[i] * math.exp(-t / 0.035) + 1.2 * math.sin(TWO_PI * 52.0 * t) * math.exp(-t / 0.09)
    crackles = pulse_bank(rng, 6, length_s=0.02, body_hz=1200.0, body_q=2.0, crack_hz=2500.0,
                          w_body=0.6, w_crack=1.0, w_thump=0.3, thump_hz=200.0, thump_tau=0.004)
    t = 0.08
    while t < 1.0:
        add_into(buf, int(t * SR), crackles[rng.randrange(6)], rng.uniform(0.2, 0.6) * (1.0 - t))
        t += rng.uniform(0.02, 0.09)
    return soft_clip(fade(buf, 0.0, 0.2), 1.5)


def metal_ring(n, rng, modes, delay=0.0):
    """Inharmonic struck-metal modes [(freq, amp, tau), ...]."""
    d = int(delay * SR)
    out = [0.0] * n
    for f, a, tau in modes:
        ph = rng.uniform(0, TWO_PI)
        f *= rng.uniform(0.97, 1.03)
        for i in range(d, n):
            t = (i - d) / SR
            out[i] += a * math.sin(TWO_PI * f * t + ph) * math.exp(-t / tau)
    return out


def starter_engage():
    """Starter solenoid click, then the jaw engaging the crankshaft with a clunk."""
    rng = random.Random(61)
    n = int(0.6 * SR)
    click_exc = [rng.uniform(-1, 1) * math.exp(-i / (0.0006 * SR)) for i in range(n)]
    click = norm_peak(biquad(click_exc, 'hp', 2500.0, 0.7))
    click_ring = metal_ring(n, rng, [(2400.0, 0.5, 0.02)])
    clunk_d = int(0.12 * SR)
    clunk_exc = [0.0] * n
    for i in range(clunk_d, n):
        clunk_exc[i] = rng.uniform(-1, 1) * math.exp(-(i - clunk_d) / (0.004 * SR))
    clunk = norm_peak(biquad(clunk_exc, 'bp', 700.0, 1.0))
    modes = metal_ring(n, rng, [(1730.0, 0.5, 0.07), (2870.0, 0.35, 0.05), (4310.0, 0.2, 0.04)], 0.12)
    out = []
    for i in range(n):
        t = i / SR
        thud = 0.0
        if i >= clunk_d:
            tt = t - 0.12
            thud = 1.2 * math.sin(TWO_PI * 85.0 * tt) * math.exp(-tt / 0.04)
        out.append(0.5 * click[i] + 0.4 * click_ring[i] + 0.9 * clunk[i] + modes[i] + thud)
    return soft_clip(fade(norm_peak(out, 0.85), 0.0, 0.1), 1.2)


def prop_stop():
    """The last compression stroke stops the propeller: a heavy thunk and a softer rock-back."""
    rng = random.Random(62)
    n = int(0.9 * SR)
    out = [0.0] * n
    for delay, a in ((0.0, 1.0), (0.28, 0.45)):
        d = int(delay * SR)
        exc = [0.0] * n
        for i in range(d, n):
            exc[i] = rng.uniform(-1, 1) * math.exp(-(i - d) / (0.006 * SR))
        body = norm_peak(biquad(exc, 'bp', 380.0, 1.5))
        for i in range(d, n):
            t = (i - d) / SR
            out[i] += a * (1.1 * math.sin(TWO_PI * 48.0 * t) * math.exp(-t / 0.09) + 0.5 * body[i])
    rattle = metal_ring(n, rng, [(1250.0, 0.12, 0.05), (2100.0, 0.08, 0.04)], 0.01)
    out = [out[i] + rattle[i] for i in range(n)]
    return soft_clip(fade(norm_peak(out, 0.85), 0.0, 0.2), 1.2)


def _modes(n, rng, f0, ratios, amps, taus, spread=0.04, delay=0.0, fmax=10000.0):
    """Struck-metal modal ring: each mode a decaying sine, slightly detuned (real parts are never ideal)."""
    modes = []
    for r, a, tau in zip(ratios, amps, taus):
        f = f0 * r * rng.uniform(1.0 - spread, 1.0 + spread)
        if f < fmax:
            modes.append((f, a, tau))
    return metal_ring(n, rng, modes, delay)


def _click(n, rng, hp_hz=1500.0, tau=0.0012):
    """The hard contact transient of metal on metal / stone."""
    exc = [rng.uniform(-1.0, 1.0) * math.exp(-i / (tau * SR)) for i in range(n)]
    return norm_peak(biquad(exc, 'hp', hp_hz, 0.7))


# Aluminium propeller blade: cantilever bending (1, 6.27, 17.5), torsion (3.1, 9.4) and plate modes
BLADE_RATIOS = (1.0, 3.1, 6.27, 9.4, 11.3, 14.8, 17.5)
BLADE_AMPS = (1.0, 0.75, 0.7, 0.45, 0.35, 0.25, 0.18)
BLADE_TAUS = (0.55, 0.42, 0.32, 0.22, 0.16, 0.12, 0.09)


def _blade_clang(rng, f0, length_s=1.2):
    n = int(length_s * SR)
    ring = _modes(n, rng, f0, BLADE_RATIOS, BLADE_AMPS, BLADE_TAUS)
    click = _click(n, rng)
    out = []
    for i in range(n):
        out.append(ring[i] + 0.8 * click[i])
    return out


def _stick_slip(n, rng, t0, dur, f_start, f_end, resonances, q=32.0):
    """Metal bending/tearing: a stick-slip train of micro-impacts whose rate falls as the blade
    yields, ringing a few narrow metal resonances -> a screeching groan."""
    imp = [0.0] * n
    t = t0
    while t < t0 + dur:
        u = (t - t0) / dur
        f = f_start * (f_end / f_start) ** u
        env = min(1.0, u / 0.08) * (1.0 - u) ** 0.7
        i = int(t * SR)
        if i < n:
            imp[i] += env * rng.uniform(0.4, 1.0)
        t += (1.0 / f) * rng.uniform(0.75, 1.25)
    out = [0.0] * n
    for fr, a in resonances:
        y = biquad(imp, 'bp', fr, q)
        y = norm_peak(y)
        for i in range(n):
            out[i] += a * y[i]
    return out


def _snap(rng, length_s=0.4):
    """Metal giving way: a very sharp crack and a bright, short ring."""
    n = int(length_s * SR)
    crack = _click(n, rng, hp_hz=2500.0, tau=0.0004)
    ring = _modes(n, rng, 3800.0, (1.0, 1.47, 1.93, 2.6), (1.0, 0.7, 0.5, 0.3), (0.07, 0.05, 0.04, 0.03), spread=0.08)
    out = []
    for i in range(n):
        t = i / SR
        out.append(1.3 * crack[i] + 0.6 * ring[i] + 0.5 * math.sin(TWO_PI * 130.0 * t) * math.exp(-t / 0.012))
    return out


def _seize(rng, length_s=1.6, amp_low=1.4):
    """The crankshaft stopped dead: a heavy steel clunk with the engine block ringing."""
    n = int(length_s * SR)
    ring = _modes(n, rng, 92.0, (1.0, 2.31, 4.1, 6.9, 11.0, 16.3), (1.0, 0.8, 0.6, 0.4, 0.25, 0.15),
                  (0.38, 0.3, 0.24, 0.17, 0.12, 0.08), spread=0.03)
    click = _click(n, rng, hp_hz=600.0, tau=0.003)
    out = []
    for i in range(n):
        t = i / SR
        out.append(ring[i] + 0.6 * click[i] + amp_low * math.sin(TWO_PI * 42.0 * t) * math.exp(-t / 0.09))
    return out


def _fragment(rng, n):
    """A broken-off piece of blade landing: a bright ping that bounces a few times."""
    buf = [0.0] * n
    f0 = rng.uniform(1700.0, 4200.0)
    t, gap, a = 0.0, rng.uniform(0.10, 0.22), 1.0
    for _ in range(rng.randint(2, 4)):
        ping = _modes(int(0.3 * SR), rng, f0, (1.0, 2.3, 3.9, 5.6), (1.0, 0.6, 0.4, 0.2), (0.12, 0.08, 0.05, 0.03), spread=0.02)
        click = _click(len(ping), rng, hp_hz=3000.0, tau=0.0005)
        add_into(buf, int(t * SR), [ping[i] + 0.5 * click[i] for i in range(len(ping))], a)
        t += gap
        gap *= 0.6
        a *= 0.5
    return buf


def prop_strike():
    """Blades striking the ground at speed, all metal: each blade hits with a clang (slowing as the
    propeller is stopped dead), the aluminium screeches and groans as it bends, cracks as it gives
    way, scrapes along the surface; the crankshaft stops with a heavy clang; then broken pieces
    land and bounce."""
    rng = random.Random(63)
    dur = 2.8
    n = int(dur * SR)
    buf = [0.0] * n
    # Blade hits: four blades, each its own pitch; hits come slower as the propeller is stopped
    f_blades = [rng.uniform(260.0, 420.0) for _ in range(4)]
    t, interval, a = 0.0, 0.013, 1.0
    for k in range(8):
        add_into(buf, int(t * SR), _blade_clang(rng, f_blades[k % 4]), a)
        t += interval
        interval *= 1.25
        a *= 0.8
    # Bending: stick-slip screech that drops in pitch as the blades yield
    bend = _stick_slip(n, rng, 0.02, 0.45, 950.0, 240.0, [(1180.0, 1.0), (2310.0, 0.7), (3770.0, 0.4), (640.0, 0.5)])
    bend2 = _stick_slip(n, rng, 0.10, 0.30, 700.0, 300.0, [(1530.0, 0.8), (2860.0, 0.5), (880.0, 0.4)])
    # Metal giving way
    for ts, amp in ((0.055, 1.0), (0.125, 0.8), (0.21, 0.6)):
        add_into(buf, int(ts * SR), _snap(rng), amp)
    # Crankshaft stopped dead
    add_into(buf, int(0.16 * SR), _seize(rng), 0.9)
    # Blade tips scraping over the surface: grinding noise coloured by metal resonances
    grind_src = [0.0] * n
    for i in range(int(0.32 * SR)):
        tt = i / SR
        grind_src[i] = rng.uniform(-1.0, 1.0) * (0.5 + 0.5 * abs(math.sin(TWO_PI * 23.0 * tt))) * math.exp(-tt / 0.14)
    grind = [0.0] * n
    for fr, amp in ((1700.0, 1.0), (2900.0, 0.7), (4300.0, 0.4)):
        y = norm_peak(biquad(grind_src, 'bp', fr, 10.0))
        for i in range(n):
            grind[i] += amp * y[i]
    grind = norm_peak(grind)
    # Pieces landing
    for _ in range(5):
        frag = _fragment(rng, int(1.0 * SR))
        add_into(buf, int(rng.uniform(0.55, 1.9) * SR), frag, rng.uniform(0.12, 0.3))
    bend = norm_peak(bend)
    bend2 = norm_peak(bend2)
    out = [buf[i] + 0.55 * bend[i] + 0.35 * bend2[i] + 0.3 * grind[i] for i in range(n)]
    out = biquad(out, 'hp', 35.0, 0.7)
    return soft_clip(fade(norm_peak(out, 0.95), 0.0, 0.5), 1.25)


def prop_strike_water():
    """Blades slapping into water at speed: heavy slaps that bend the aluminium (clangs and a
    groan), the crankshaft stopping dead, a sheet of spray raining back down."""
    rng = random.Random(64)
    dur = 2.6
    n = int(dur * SR)
    buf = [0.0] * n
    f_blades = [rng.uniform(260.0, 420.0) for _ in range(4)]
    t, interval, a = 0.0, 1.0 / 45.0, 1.0
    for k in range(7):
        m = int(0.12 * SR)
        exc = [rng.uniform(-1.0, 1.0) * math.exp(-i / (0.010 * SR)) for i in range(m)]
        slap = norm_peak(biquad(exc, 'bp', rng.uniform(300, 420), 1.0))
        hiss = norm_peak(biquad(exc, 'bp', 1600.0, 0.8))
        ev = [slap[i] + 0.4 * hiss[i] + 0.9 * math.sin(TWO_PI * 60.0 * i / SR) * math.exp(-i / (0.025 * SR))
              for i in range(m)]
        add_into(buf, int(t * SR), ev, a)
        add_into(buf, int(t * SR), _blade_clang(rng, f_blades[k % 4], 0.8), 0.45 * a)  # the blade rings
        t += interval
        interval *= 1.3
        a *= 0.82
    bend = norm_peak(_stick_slip(n, rng, 0.04, 0.35, 800.0, 260.0, [(1180.0, 1.0), (2310.0, 0.6), (640.0, 0.5)]))
    add_into(buf, int(0.2 * SR), _seize(rng, 1.4, 1.0), 0.7)
    spray_src = biquad(noise(n, rng), 'bp', 2500.0, 0.7)
    spray = norm_peak([spray_src[i] * min(1.0, (i / SR) / 0.05) * math.exp(-(i / SR) / 0.7) for i in range(n)])
    t = 0.35
    while t < 2.3:
        dm = int(0.03 * SR)
        drop = norm_peak(biquad([rng.uniform(-1, 1) * math.exp(-i / (0.004 * SR)) for i in range(dm)],
                                'bp', rng.uniform(900, 2800), 3.0))
        add_into(buf, int(t * SR), drop, rng.uniform(0.04, 0.16) * (2.4 - t) / 2.0)
        t += rng.expovariate(14.0)
    out = [buf[i] + 0.35 * bend[i] + 0.45 * spray[i] for i in range(n)]
    out = biquad(out, 'hp', 30.0, 0.7)
    return soft_clip(fade(norm_peak(out, 0.95), 0.0, 0.4), 1.25)


def turbine_lightoff():
    """Fuel lighting in the combustor: a deep 'whoomp' that grows into the roar."""
    rng = random.Random(64)
    dur = 2.2
    n = int(dur * SR)
    rumble = norm_peak(biquad(noise(n, rng), 'lp', 180.0, 0.8))
    roar = norm_peak(biquad(noise(n, rng), 'bp', 700.0, 0.6))
    out = []
    ph = 0.0
    for i in range(n):
        t = i / SR
        att = min(1.0, t / 0.06)
        f = 35.0 + 25.0 * min(1.0, t / 0.4)
        ph += TWO_PI * f / SR
        v = (att * (1.6 * rumble[i] * math.exp(-t / 0.8) + 0.9 * math.sin(ph) * math.exp(-t / 0.5))
             + 0.5 * roar[i] * min(1.0, t / 0.3) * math.exp(-t / 1.2))
        out.append(v)
    return soft_clip(fade(norm_peak(out, 0.9), 0.01, 0.4), 1.3)


# ------------------------------------------------------------------------------

JOBS = [
    ('radial_idle', lambda: piston_loop('radial', 'idle')),
    ('radial_mid', lambda: piston_loop('radial', 'mid')),
    ('radial_mid_off', lambda: piston_loop('radial', 'mid_off')),
    ('radial_high', lambda: piston_loop('radial', 'high')),
    ('radial_high_off', lambda: piston_loop('radial', 'high_off')),
    ('vinline_idle', lambda: piston_loop('vinline', 'idle')),
    ('vinline_mid', lambda: piston_loop('vinline', 'mid')),
    ('vinline_mid_off', lambda: piston_loop('vinline', 'mid_off')),
    ('vinline_high', lambda: piston_loop('vinline', 'high')),
    ('vinline_high_off', lambda: piston_loop('vinline', 'high_off')),
    ('wind', wind_loop),
    ('piston_crank', piston_crank),
    ('starter_whine', starter_whine),
    ('supercharger_whine', supercharger_whine),
    ('turbine_whine', turbine_whine),
    ('turbine_roar', turbine_roar),
    ('turbine_igniter', turbine_igniter),
    ('prop_loop', prop_loop),
    ('prop_rasp', prop_rasp),
    ('prop_swish', prop_swish),
    ('piston_cough', piston_cough),
    ('exhaust_pop', exhaust_pop),
    ('backfire', backfire),
    ('starter_engage', starter_engage),
    ('prop_stop', prop_stop),
    ('prop_strike', prop_strike),
    ('prop_strike_water', prop_strike_water),
    ('turbine_lightoff', turbine_lightoff),
]


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(root, 'GameData', 'ROPlanesPlus', 'Sounds')
    os.makedirs(out_dir, exist_ok=True)
    keep = {name + '.wav' for name, _ in JOBS}
    for fn in os.listdir(out_dir):
        if fn.lower().endswith('.wav') and fn not in keep:
            os.remove(os.path.join(out_dir, fn))
            print(f"  removed stale {fn}")
    try:
        import process_recordings as rec
    except ImportError:
        rec = None
    recorded = []
    for name, fn in JOBS:
        sr = SR
        why = rec.unavailable_reason(name) if rec else 'process_recordings.py missing'
        if rec is not None and why is None:
            samples = rec.build(name)
            sr = rec.OUT_SR
            recorded.append(name)
            src = 'recording'
        else:
            if rec is not None and name in rec.RECIPES:
                print(f"  WARNING: {name} falls back to synthesis ({why})")
            samples = fn()
            src = 'synthesized'
        path = os.path.join(out_dir, name + '.wav')
        write_wav(path, samples, sr)
        print(f"  {name}.wav  {len(samples) / sr:.2f} s  rms {rms(list(samples)):.3f}  {src}")
    credits = os.path.join(out_dir, 'CREDITS.txt')
    if recorded:
        with open(credits, 'w', encoding='utf-8', newline='\n') as f:
            f.write(rec.credits_text(recorded))
    elif os.path.exists(credits):
        os.remove(credits)
    print(f"Wrote {len(JOBS)} sounds to {out_dir} ({len(recorded)} from recordings, credits in CREDITS.txt)")


if __name__ == '__main__':
    main()
