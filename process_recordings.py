#!/usr/bin/env python3
"""
Turns real aircraft recordings into the engine loops PropellerAudio.cs plays.

Used by generate_sounds.py: every loop listed in RECIPES is built from a recording when its
source file is present and numpy/scipy/ffmpeg are available; everything else stays synthesized.

Sources live in sound_sources/ (not shipped):
  sound_sources/originals/<id>.<ext>   full-quality download (preferred when present)
  sound_sources/previews/<id>.ogg      Freesound HQ preview (192 kbps Ogg), used otherwise
Every source is CC0 or CC-BY; SOURCES holds the credits, written to Sounds/CREDITS.txt.

What happens to a piston recording:
  1. cut the steady section, decode to mono 44.1 kHz
  2. track the engine's cycle frequency (harmonic comb, 0.5-order grid = rpm / 120) through the
     section, so Doppler and rpm drift can be flattened out
  3. time-warp it so the firing frequency (cylinders x cycle frequency) sits exactly on the
     mixer's reference (radial: 18 cyl at 800/1600/2600 rpm; V-12 at 800/1600/2600 rpm), i.e. the
     mixer's "equivalent rpm" pitch rule plays the original engine at its own pitch
  4. even out the level (approach/recede), cut a loop that is a whole number of engine cycles
     long and crossfade its seam in phase, so it repeats without a hitch in the rhythm
  5. high-pass, match the loudness the mixer was balanced for, soft-limit, 44.1 kHz
Closed-throttle (_off) loops come from an unloaded engine (Merlin on a test stand) or from the
on-load loop with the firing thinned out, a darker tone and exhaust crackle/pops added.
Turboprop whine/roar and the propeller loop are separated from a turbine Otter take-off by
harmonic/noise separation (median filtering of the spectrogram) and band limits.

Needs: numpy, scipy (pip install numpy scipy) and ffmpeg on PATH (winget install Gyan.FFmpeg).
"""

import glob
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT, 'sound_sources')
WORK_SR = 44100  # processed and written at this rate (loop lengths are exact sample counts)
OUT_SR = WORK_SR
MAX_LOOP_SEC = 6.0

# Firing frequency the mixer expects at each loop's reference (PropellerAudio.cs: IdleRef/MidRef/
# HighRef = 800/1600/2600 rpm; radial loops = 18 cylinders, vinline = 12)
def ref_firing(family, band):
    rpm = {'idle': 800.0, 'mid': 1600.0, 'high': 2600.0}[band]
    cyl = 18 if family == 'radial' else 12
    return rpm * cyl / 120.0


# ------------------------------------------------------------------------------
# Sources (all CC0 / CC-BY; Freesound ids unless noted)
# ------------------------------------------------------------------------------

SOURCES = {
    '437838': dict(user='craigsmith', title='G06-18_C-47 2 Engine Prop Idle', licence='CC0 1.0',
                   what='Douglas C-47, two P&W R-1830 (14-cyl radial) idling'),
    '437863': dict(user='craigsmith', title='G07-19_4 Engine Prop Steady Int or Ext Amb', licence='CC0 1.0',
                   what='four-engine airliner (14-cyl radials) in cruise'),
    '143559': dict(user='Fight2FlyPhoto', title='B-25s Taking Off', licence='CC BY 3.0',
                   what='North American B-25 Mitchell, two Wright R-2600 (14-cyl radial) at take-off power'),
    '142898': dict(user='Fight2FlyPhoto', title='Bf-109 - Daimler-Benz Run-Up', licence='CC BY 3.0',
                   what='Messerschmitt Bf 109E-3, Daimler-Benz DB 601 (inverted V-12) warm-up and run-up'),
    '143561': dict(user='Fight2FlyPhoto', title='P-51 Mustang Takeoff', licence='CC BY 3.0',
                   what='North American P-51B, Packard Merlin (V-12) at take-off power'),
    '276597': dict(user='squashy555', title='merlin engine.wav', licence='CC0 1.0',
                   what='Rolls-Royce Merlin running on a static display stand without propeller'),
    '772822': dict(user='jerry.berumen', title='seaplane takeoff vancouver city port engine', licence='CC BY 4.0',
                   what='turboprop floatplane (PT6) taking off'),
    '772823': dict(user='jerry.berumen', title='seaplane vancouver dock engine start cruise', licence='CC BY 4.0',
                   what='turboprop floatplane (PT6) start and taxi'),
    '437745': dict(user='craigsmith', title='G02-21-Aircraft-Glider', licence='CC0 1.0',
                   what='glider in flight: airflow'),
    '140436': dict(user='jarekgie', title='PZL 104 WILGA START ENGINE (CLOSE).MP3', licence='CC BY 3.0',
                   what='PZL-104 Wilga, Ivchenko AI-14R (9-cyl radial) idling, recorded close'),
    '143560': dict(user='Fight2FlyPhoto', title='P-47 Flyby', licence='CC BY 3.0',
                   what='Republic P-47D, P&W R-2800 (18-cyl radial) at power on approach'),
}


def source_url(sid):
    return 'https://freesound.org/people/%s/sounds/%s/' % (SOURCES[sid]['user'], sid)


# ------------------------------------------------------------------------------
# Recipes
# ------------------------------------------------------------------------------
# piston: grid = cycle frequency (Hz) at t0 as heard in the recording (0.5 engine order;
# firing = cyl x grid). Identified from the harmonic series (and, for the Bf 109 and P-51, the
# propeller's blade-passage line, which pins the crankshaft speed through the reduction gear).

# level = A-weighted loudness (dBFS) the loop is normalised to: that of the synthesized loop it
# replaces, so the mixer's balance (idle/mid/high crossfades, on/off load, engine vs. propeller
# vs. wind) stays as it was tuned. Plain RMS matching left dark recordings up to 4 dB quiet and
# put a 7 dB dip into the V-12's mid->high crossfade.
# presence = high shelf (dB above ~1.5 kHz) for recordings made far away, giving back the top end
# that distance and air absorption took (a close engine is brighter).

# Radial loops come from SINGLE-engine recordings only. The first set (C-47 twin, a four-engine
# airliner, B-25 twin) carried the beat of unsynchronised engines ("wooow wooow" about every
# 0.7-1.4 s, harmonic lines pulsing 53-57 %), which no mixing can take out again.
# P-47 approach: harmonic grid 30.95 Hz = crankshaft, 61.9 Hz line = 4-blade propeller at half
# crank speed (R-2800-59, 0.5 reduction), so the 0.5-order grid is 15.475 Hz and firing 278.6 Hz
# as heard (Doppler included); mid and high are both cut from it, so their crossfade is seamless.

RECIPES = {
    'radial_idle': dict(kind='piston', family='radial', band='idle', src='140436', t0=9.0, t1=28.0,
                        cyl=9, grid=8.5, track=True, level=-20.4, lp=12000.0),
    'radial_mid': dict(kind='piston', family='radial', band='mid', src='143560', t0=1.0, t1=5.6,
                       cyl=18, grid=15.475, track=True, level=-17.2, lp=14000.0, flatten=0.95, presence=4.0, specflat=True),
    'radial_high': dict(kind='piston', family='radial', band='high', src='143560', t0=1.0, t1=5.6,
                        cyl=18, grid=15.475, track=True, level=-14.6, lp=14000.0, flatten=0.95, presence=4.0, specflat=True),
    'radial_mid_off': dict(kind='off', base='radial_mid', level=-23.3, crackle=8.0, pops=1.0, lp=2600.0),
    'radial_high_off': dict(kind='off', base='radial_high', level=-21.4, crackle=20.0, pops=2.2, lp=3200.0),
    'vinline_idle': dict(kind='piston', family='vinline', band='idle', src='142898', t0=5.0, t1=17.5,
                         cyl=12, grid=7.95, level=-20.1, lp=12000.0),
    'vinline_mid': dict(kind='piston', family='vinline', band='mid', src='142898', t0=57.5, t1=68.5,
                        cyl=12, grid=14.45, level=-16.1, lp=5000.0),  # mic beside the run-up: very bright
    'vinline_high': dict(kind='piston', family='vinline', band='high', src='143561', t0=16.8, t1=20.7,
                         cyl=12, grid=22.0, track=True, level=-13.0, lp=16000.0, flatten=0.9, presence=6.0),
    # unloaded Merlin: rpm hunts and there is no clear harmonic series, so the loop is not
    # cycle-aligned; its ~145 Hz band is taken as the firing frequency
    'vinline_mid_off': dict(kind='piston', family='vinline', band='mid', src='276597', t0=40.0, t1=70.0,
                            cyl=12, grid=145.0 / 12, align=False, level=-21.7, lp=7000.0,
                            add_crackle=6.0, add_pops=0.8),
    'vinline_high_off': dict(kind='off', base='vinline_high', level=-19.7, crackle=24.0, pops=2.8, lp=4500.0),
    # turboprop: compressor whine (tonal part above 1.4 kHz) and combustion/exhaust roar (noise part)
    'turbine_whine': dict(kind='whine', src='772823', t0=36.0, t1=52.0, level=-8.9),
    'turbine_roar': dict(kind='roar', src='772822', t0=33.0, t1=46.0, level=-13.7),
    # propeller: 3-blade turboprop at take-off, blade passage 100 Hz -> mixer reference 80 Hz
    'prop_loop': dict(kind='prop', src='772822', t0=33.0, t1=46.0, bpf=99.6, blades=3, ref_bpf=80.0,
                      level=-18.6, presence=6.0),
    'wind': dict(kind='wind', src='437745', t0=2.0, t1=30.0, speed=1.25, level=-14.9),
}


# ------------------------------------------------------------------------------
# Availability / IO
# ------------------------------------------------------------------------------

_np = None


def _libs():
    global _np
    if _np is None:
        import numpy  # noqa: F401
        import scipy.signal  # noqa: F401
        import scipy.ndimage  # noqa: F401
        _np = numpy
    return _np


def ffmpeg_exe():
    p = shutil.which('ffmpeg')
    if p:
        return p
    for pat in (r'%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe',
                r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\ffmpeg.exe'):
        c = glob.glob(os.path.expandvars(pat), recursive=True)
        if c:
            return c[0]
    return None


def source_path(sid):
    for pat in (os.path.join(SRC_DIR, 'originals', sid + '.*'), os.path.join(SRC_DIR, 'previews', sid + '.ogg')):
        c = [p for p in glob.glob(pat) if os.path.getsize(p) > 0]
        if c:
            return c[0]
    return None


def unavailable_reason(name):
    """None if the loop can be built from its recording, else why not."""
    r = RECIPES.get(name)
    if r is None:
        return 'no recipe'
    while r['kind'] == 'off':
        r = RECIPES[r['base']]
    try:
        _libs()
    except ImportError as e:
        return 'python module missing (%s): pip install numpy scipy' % e.name
    if ffmpeg_exe() is None:
        return 'ffmpeg not found: winget install Gyan.FFmpeg'
    if source_path(r['src']) is None:
        return 'source %s missing in sound_sources/' % r['src']
    return None


def load(sid, t0, t1, sr=WORK_SR):
    np = _libs()
    out = subprocess.run([ffmpeg_exe(), '-v', 'error', '-ss', '%.3f' % t0, '-t', '%.3f' % (t1 - t0),
                          '-i', source_path(sid), '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).astype(np.float64)


# ------------------------------------------------------------------------------
# DSP
# ------------------------------------------------------------------------------

def sos_filter(x, kind, f, sr, order=4):
    from scipy import signal
    if kind == 'bp':
        sos = signal.butter(order, [f[0], min(f[1], sr * 0.45)], 'bandpass', fs=sr, output='sos')
    else:
        if kind == 'lp' and f >= sr * 0.45:
            return x
        sos = signal.butter(order, f, 'lowpass' if kind == 'lp' else 'highpass', fs=sr, output='sos')
    return signal.sosfiltfilt(sos, x)


def track_grid(x, sr, grid0, rel=0.06, win=0.6, hop=0.1, fmax=1500.0, harmonics=36):
    """Cycle frequency of an aircraft going past (Doppler): per frame, the comb (multiples of the
    grid, at most `harmonics` of them and below fmax) with the most harmonic prominence within
    +-rel of grid0; outliers removed and a smooth quadratic fitted through time (a pass changes
    pitch smoothly; anything faster is the tracker, not the engine)."""
    np = _libs()
    from scipy import ndimage
    n = int(win * sr)
    h = int(hop * sr)
    nfft = 1 << int(np.ceil(np.log2(n * 8)))
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    fmax = min(fmax, harmonics * grid0 * (1 + rel))
    band = freqs < fmax
    w = np.hanning(n)
    cands = np.linspace(grid0 * (1 - rel), grid0 * (1 + rel), 241)
    times, est = [], []
    for start in range(0, len(x) - n, h):
        spec = 20 * np.log10(np.abs(np.fft.rfft(x[start:start + n] * w, nfft))[band] + 1e-9)
        prom = np.clip(spec - ndimage.median_filter(spec, 151), 0, 30)
        scores = [prom[np.round(np.arange(1, int(fmax / c)) * c / freqs[1]).astype(int)].mean() for c in cands]
        times.append((start + n / 2) / sr)
        est.append(cands[int(np.argmax(scores))])
    times, est = np.array(times), np.array(est)
    med = ndimage.median_filter(est, 7)
    keep = np.abs(est - med) < 0.015 * med
    coef = np.polyfit(times[keep], est[keep], 2)
    return times, np.polyval(coef, times)


def warp(x, sr, speed_t, speed_v):
    """Resample with a time-varying read speed (input samples per output sample): pitch and
    tempo scale together, like playing a tape faster. speed_v sampled at input times speed_t."""
    np = _libs()
    from scipy import signal
    vmax = float(np.max(speed_v))
    if vmax > 1.0:
        x = sos_filter(x, 'lp', 0.45 * sr / vmax, sr, 8)
    up = 4
    xu = signal.resample_poly(x, up, 1)
    pos = []
    p = 0.0
    tin = np.asarray(speed_t)
    vin = np.asarray(speed_v)
    limit = len(x) - 2
    # integrate in blocks of 64 output samples (speed varies slowly)
    while p < limit:
        v = float(np.interp(p / sr, tin, vin))
        pos.append(p + v * np.arange(64))
        p += 64 * v
    pos = np.concatenate(pos)
    pos = pos[pos < limit]
    return np.interp(pos * up, np.arange(len(xu)), xu)


def level_flatten(x, sr, amount=0.8, tau=0.35):
    """Take out slow level changes (an aircraft approaching or receding), keep the fast ones."""
    np = _libs()
    from scipy import ndimage
    e = np.sqrt(ndimage.uniform_filter1d(x * x, int(tau * sr)) + 1e-12)
    e = ndimage.uniform_filter1d(e, int(tau * sr))
    g = (np.median(e) / e) ** amount
    return x * g


def spectral_flatten(x, sr, tau=0.8, amount=1.0, bands=28):
    """Take out slow changes of tone colour, band by band (an aircraft getting closer gets
    brighter, and the ground reflection sweeps notches through the spectrum). Level flattening
    alone left the far, dark start and the near, bright end of an approach in one loop, so it
    jumped back from bright to dark at every seam: a 'whoosh' once per loop. Fast changes (the
    firing pulses) stay; only what is slower than tau seconds is evened out."""
    np = _libs()
    from scipy import signal, ndimage
    nper = 2048
    hop = nper // 4
    f, t, Z = signal.stft(x, sr, nperseg=nper, noverlap=nper - hop)
    P = np.abs(Z) ** 2
    edges = np.geomspace(40.0, sr * 0.45, bands + 1)
    gains = np.ones_like(P)
    k = max(3, int(tau * sr / hop))
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi)
        if not m.any():
            continue
        e = P[m].mean(axis=0) + 1e-14
        slow = ndimage.uniform_filter1d(ndimage.uniform_filter1d(e, k, mode='nearest'), k, mode='nearest')
        g = (np.median(slow) / slow) ** (0.5 * amount)
        gains[m] = g
    # smooth the per-bin gains across frequency so band edges don't step
    gains = ndimage.uniform_filter1d(gains, 9, axis=0)
    _, y = signal.istft(Z * gains, sr, nperseg=nper, noverlap=nper - hop)
    return y[:len(x)]


def make_loop(x, sr, period=None, max_sec=MAX_LOOP_SEC, xfade=0.25):
    """Seamless loop: length = whole number of engine cycles (if period given), seam crossfaded
    with the material that followed it, which is in the same firing phase."""
    np = _libs()
    X = int(xfade * sr)
    avail = len(x) - 2 * X
    L = min(int(max_sec * sr), avail)
    if period:
        cycles = max(1, int(L / (period * sr)))
        L = int(round(cycles * period * sr))
    y = x[X:X + L].copy()
    th = np.linspace(0.0, np.pi / 2, X)
    tail = slice(L - X, L)
    y[tail] = x[X + L - X:X + L] * np.cos(th) + x[0:X] * np.sin(th)
    return y


def hpss(x, sr, kh=31, kp=31):
    """Harmonic (steady tones) / noise split by median filtering the spectrogram along time /
    frequency, soft masks."""
    np = _libs()
    from scipy import signal, ndimage
    nper = 2048
    f, t, Z = signal.stft(x, sr, nperseg=nper, noverlap=nper * 3 // 4)
    S = np.abs(Z)
    H = ndimage.median_filter(S, size=(1, kh))
    P = ndimage.median_filter(S, size=(kp, 1))
    mh = H ** 2 / (H ** 2 + P ** 2 + 1e-12)
    _, xh = signal.istft(Z * mh, sr, nperseg=nper, noverlap=nper * 3 // 4)
    _, xp = signal.istft(Z * (1 - mh), sr, nperseg=nper, noverlap=nper * 3 // 4)
    return xh[:len(x)], xp[:len(x)]


def crackle_layer(n, sr, rng, rate, pops, amp=1.0):
    """Afterfire crackle (tiny bright cracks) and occasional pops in the exhaust, circular."""
    np = _libs()
    out = np.zeros(n)

    def burst(length, f0, q_lo, q_hi, decay):
        m = int(length * sr)
        e = rng.uniform(-1, 1, m) * np.exp(-np.arange(m) / (decay * sr))
        e = sos_filter(e, 'bp', (f0 * q_lo, f0 * q_hi), sr, 2)
        e[: max(2, int(0.0004 * sr))] *= np.linspace(0, 1, max(2, int(0.0004 * sr)))
        return e / (np.max(np.abs(e)) + 1e-9)

    def add(sig, start, a):
        idx = (start + np.arange(len(sig))) % n
        np.add.at(out, idx, sig * a)

    t = 0.0
    while t < n / sr:
        add(burst(0.02, rng.uniform(1500, 3200), 0.6, 1.8, 0.0012), int(t * sr), 0.25 + 0.9 * rng.random() ** 3)
        t += rng.exponential(1.0 / rate)
    t = rng.uniform(0, 0.4)
    while t < n / sr and pops > 0:
        m = int(0.12 * sr)
        tt = np.arange(m) / sr
        thump = np.sin(2 * np.pi * rng.uniform(70, 110) * tt) * np.exp(-tt / 0.02)
        crack = burst(0.12, rng.uniform(900, 1800), 0.5, 2.5, 0.006)
        add(0.8 * thump + crack, int(t * sr), rng.uniform(1.0, 1.7))
        t += rng.exponential(1.0 / pops)
    return out * amp


def a_weight(x, sr):
    """IEC 61672 A-weighting filter (bilinear transform of the analogue prototype)."""
    np = _libs()
    from scipy import signal
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    num = [(2 * np.pi * f4) ** 2 * 10 ** (1.9997 / 20), 0, 0, 0, 0]
    den = np.polymul([1, 4 * np.pi * f4, (2 * np.pi * f4) ** 2], [1, 4 * np.pi * f1, (2 * np.pi * f1) ** 2])
    den = np.polymul(np.polymul(den, [1, 2 * np.pi * f3]), [1, 2 * np.pi * f2])
    b, a = signal.bilinear(num, den, sr)
    return signal.lfilter(b, a, x)


def a_level(y, sr):
    """A-weighted RMS level in dBFS (the loop is weighted twice over so filter start-up is excluded)."""
    np = _libs()
    ya = a_weight(np.concatenate([y, y]), sr)[len(y):]
    return 20 * np.log10(np.sqrt(np.mean(ya * ya)) + 1e-12)


def high_shelf(x, sr, gain_db, f0=1500.0):
    """RBJ high shelf, slope 1."""
    np = _libs()
    from scipy import signal
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / 2 * np.sqrt(2)
    c = np.cos(w0)
    b = [A * ((A + 1) + (A - 1) * c + 2 * np.sqrt(A) * alpha), -2 * A * ((A - 1) + (A + 1) * c),
         A * ((A + 1) + (A - 1) * c - 2 * np.sqrt(A) * alpha)]
    a = [(A + 1) - (A - 1) * c + 2 * np.sqrt(A) * alpha, 2 * ((A - 1) - (A + 1) * c),
         (A + 1) - (A - 1) * c - 2 * np.sqrt(A) * alpha]
    return signal.lfilter(b, a, x)


MAX_LIMIT_DB = 1.5
LIMITER_STATS = {}  # name -> (fraction of samples the limiter touched, dB short of the loudness target)


def finish(y, sr, level, hp=25.0, lp=None, presence=0.0, name=None):
    """Final filters (run circularly so the loop seam stays clean), A-weighted loudness, soft limiter."""
    np = _libs()
    pad = min(len(y) - 1, int(0.25 * sr))
    z = np.concatenate([y[-pad:], y, y[:pad]])
    z = sos_filter(z, 'hp', hp, sr, 2)
    if lp:
        z = sos_filter(z, 'lp', lp, sr, 4)
    if presence:
        z = high_shelf(z, sr, presence)
    y = z[pad:pad + len(y)]
    y = y - np.mean(y)
    k = 0.6

    def limit(a):  # soft limiter: transparent below k, peaks squeezed under 0.98
        return np.where(a > k, k + (0.98 - k) * np.tanh((a - k) / (0.98 - k)), a)

    # gain for the loudness target, but never so much that the limiter takes more than
    # MAX_LIMIT_DB off the peaks (99.9th percentile: lone crackle spikes may be squeezed harder,
    # which is inaudible; squeezing every blade slap or firing pulse is not): such a loop stays a
    # little quiet instead, and the shortfall is reported
    gain = 10 ** ((level - a_level(y, sr)) / 20)
    peak = float(np.percentile(np.abs(y), 99.9))
    lo, hi = k, 4.0
    for _ in range(40):  # largest output peak whose reduction is within budget
        mid = 0.5 * (lo + hi)
        if limit(np.array([mid]))[0] / mid >= 10 ** (-MAX_LIMIT_DB / 20):
            lo = mid
        else:
            hi = mid
    gain = min(gain, lo / peak)
    y = y * gain
    a = np.abs(y)
    over = a > k
    if name:
        LIMITER_STATS[name] = (float(over.mean()), level - a_level(y, sr))
    return np.sign(y) * limit(a)


# ------------------------------------------------------------------------------
# Builders
# ------------------------------------------------------------------------------

_cache = {}


def build_piston(r, rng):
    np = _libs()
    sr = WORK_SR
    x = load(r['src'], r['t0'], r['t1'])
    x = sos_filter(x, 'hp', 20.0, sr, 2)
    y, period = piston_aligned(r, x)
    if r.get('add_crackle'):
        y = y / (np.sqrt(np.mean(y * y)) + 1e-12)
        y = y + 0.35 * crackle_layer(len(y), WORK_SR, rng, r['add_crackle'], r.get('add_pops', 0.0))
    loop = make_loop(y, WORK_SR, period if r.get('align', True) else None)
    return finish(loop, WORK_SR, r['level'], lp=r.get('lp'), presence=r.get('presence', 0.0), name=r.get('_name'))


def piston_aligned(r, x):
    """Recording warped so its firing frequency sits on the mixer's reference (tracked through a
    Doppler pass if track=True, else constant: ground runs at steady rpm need no tracking, and the
    dense harmonic grid of a 14-cylinder engine would only tempt a tracker to wander).
    Returns (signal, engine cycle period in seconds at the reference)."""
    np = _libs()
    sr = WORK_SR
    f_ref = ref_firing(r['family'], r['band'])
    if r.get('track'):
        t, g = track_grid(x, sr, r['grid'])
    else:
        t, g = np.array([0.0, len(x) / sr]), np.array([r['grid'], r['grid']])
    y = warp(x, sr, t, f_ref / (r['cyl'] * g))
    if r.get('specflat'):
        y = spectral_flatten(y, sr)
    y = level_flatten(y, sr, r.get('flatten', 0.6))
    return y, r['cyl'] / f_ref


def build_off(r, rng, name):
    """Throttle closed at rpm: firing thinned and soft, darker, with afterfire crackle and pops."""
    np = _libs()
    base = RECIPES[r['base']]
    sr = WORK_SR
    x = load(base['src'], base['t0'], base['t1'])
    x = sos_filter(x, 'hp', 20.0, sr, 2)
    f_ref = ref_firing(base['family'], base['band'])
    y, period = piston_aligned(base, x)
    y = make_loop(y, sr, period)
    n = len(y)
    # firing thinned: slow random dips (some cylinders not firing) at the firing rate
    fire_n = int(round(n / sr * f_ref))
    env = np.ones(fire_n)
    skip = rng.random(fire_n) < 0.18
    env[skip] = rng.uniform(0.25, 0.55, skip.sum())
    env = env * rng.uniform(0.75, 1.1, fire_n)
    env = np.interp(np.arange(n) * fire_n / n, np.arange(fire_n + 1), np.append(env, env[0]))
    from scipy import ndimage
    env = ndimage.uniform_filter1d(env, int(sr / f_ref), mode='wrap')
    pad = int(0.25 * sr)
    y = sos_filter(np.concatenate([y[-pad:], y, y[:pad]]), 'lp', r['lp'], sr, 2)[pad:pad + n] * env
    y = y / (np.sqrt(np.mean(y * y)) + 1e-12)
    y = y + 0.45 * crackle_layer(n, sr, rng, r['crackle'], r['pops'])
    return finish(y, sr, r['level'], lp=None, presence=r.get('presence', base.get('presence', 0.0)), name=r.get('_name'))


def build_whine(r, rng):
    sr = WORK_SR
    x = load(r['src'], r['t0'], r['t1'])
    xh, xp = hpss(x, sr, kh=41, kp=17)
    tone = sos_filter(xh, 'hp', 1400.0, sr, 4)
    air = sos_filter(xp, 'hp', 2500.0, sr, 2)
    y = level_flatten(tone + 0.25 * air, sr, 0.7)
    return finish(make_loop(y, sr, None, xfade=0.4), sr, r['level'], hp=300.0, name=r.get('_name'))


def build_roar(r, rng):
    sr = WORK_SR
    x = load(r['src'], r['t0'], r['t1'])
    xh, xp = hpss(x, sr, kh=41, kp=17)
    y = level_flatten(sos_filter(xp, 'lp', 6000.0, sr, 2), sr, 0.85, tau=0.5)
    return finish(make_loop(y, sr, None, xfade=0.4), sr, r['level'], hp=25.0, name=r.get('_name'))


def build_prop(r, rng):
    np = _libs()
    sr = WORK_SR
    x = load(r['src'], r['t0'], r['t1'])
    x = sos_filter(x, 'lp', 3200.0, sr, 6)  # leave the turbine whine out
    t, g = track_grid(x, sr, r['bpf'] / r['blades'], fmax=900.0, harmonics=27)
    y = warp(x, sr, t, r['ref_bpf'] / (r['blades'] * g))
    y = level_flatten(y, sr, 0.85, tau=0.5)
    period = r['blades'] / r['ref_bpf']  # one revolution
    return finish(make_loop(y, sr, period), sr, r['level'], hp=25.0, presence=r.get('presence', 0.0), name=r.get('_name'))


def build_wind(r, rng):
    np = _libs()
    from scipy import signal
    sr = WORK_SR
    x = load(r['src'], r['t0'], r['t1'])
    xh, xp = hpss(x, sr, kh=41, kp=17)  # drop tonal bits (distant engines), keep the rush
    y = signal.resample_poly(xp, 4, int(round(4 * r['speed'])))
    y = level_flatten(y, sr, 0.6, tau=0.8)
    return finish(make_loop(y, sr, None, xfade=0.6), sr, r['level'], hp=30.0, name=r.get('_name'))


def build(name):
    """Returns the loop as a numpy float array at OUT_SR, or None if no recipe."""
    np = _libs()
    r = RECIPES.get(name)
    if r is None:
        return None
    if name in _cache:
        return _cache[name]
    rng = np.random.default_rng(sum(map(ord, name)) * 7919)  # deterministic per loop
    r = dict(r, _name=name)
    kind = r['kind']
    if kind == 'piston':
        y = build_piston(r, rng)
    elif kind == 'off':
        y = build_off(r, rng, name)
    elif kind == 'whine':
        y = build_whine(r, rng)
    elif kind == 'roar':
        y = build_roar(r, rng)
    elif kind == 'prop':
        y = build_prop(r, rng)
    elif kind == 'wind':
        y = build_wind(r, rng)
    else:
        raise ValueError(kind)
    _cache[name] = y
    return y


def used_sources(names):
    out = []
    for n in names:
        r = RECIPES[n]
        while r['kind'] == 'off':
            r = RECIPES[r['base']]
        if r['src'] not in out:
            out.append(r['src'])
    return out


def credits_text(built):
    lines = ['ROPlanes+ engine sounds', '=======================', '',
             'Loops built from real recordings (cut, pitch-aligned, looped, filtered and level-matched',
             'by process_recordings.py); all other sounds are synthesized by generate_sounds.py.', '']
    for sid in used_sources(built):
        s = SOURCES[sid]
        uses = ', '.join(n for n in built if (RECIPES[n].get('src') or RECIPES[RECIPES[n]['base']]['src']) == sid)
        lines += ['"%s" by %s (%s)' % (s['title'], s['user'], s['what']),
                  '  %s' % source_url(sid),
                  '  Licence: %s%s' % (s['licence'], '' if s['licence'].startswith('CC0') else
                                       ' - https://creativecommons.org/licenses/by/%s/' % s['licence'].split()[-1]),
                  '  Used (modified) in: %s' % uses, '']
    return '\n'.join(lines)
