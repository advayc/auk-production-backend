"""Splice-join seam diagnostics (stdlib only).

Diagnostic metrics only. They never change technical or automatic-QA
outcomes; joins and phrase voice still need human listening review.
"""
from __future__ import annotations
import array, cmath, math, sys, wave
from pathlib import Path

SAMPLE_RATE = 24000
WINDOW = 1024          # ~42.7 ms at 24 kHz
BASELINE_STEP = 4800   # 200 ms between baseline window pairs
MAX_BASELINE_PAIRS = 30


def _read_mono16(path):
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError('seam metrics need mono PCM16 wav')
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = array.array('h')
    samples.frombytes(raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    return rate, samples


def _fft(x):
    n = len(x)
    if n == 1:
        return x
    even = _fft(x[0::2]); odd = _fft(x[1::2])
    t = [cmath.exp(-2j * math.pi * k / n) * odd[k] for k in range(n // 2)]
    return [even[k] + t[k] for k in range(n // 2)] + [even[k] - t[k] for k in range(n // 2)]


_HANN = [0.5 - 0.5 * math.cos(2 * math.pi * i / (WINDOW - 1)) for i in range(WINDOW)]


def _mags(segment):
    padded = list(segment[:WINDOW]) + [0] * max(0, WINDOW - len(segment))
    spec = _fft([padded[i] * _HANN[i] * (1 + 0j) for i in range(WINDOW)])
    return [abs(spec[i]) for i in range(WINDOW // 2)]


def _flux(pre, post):
    mp, mq = _mags(pre), _mags(post)
    num = math.sqrt(sum((a - b) ** 2 for a, b in zip(mp, mq)))
    den = math.sqrt(sum(a * a for a in mp)) + 1e-9
    return num / den


def seam_report(path, boundaries_seconds, sample_rate=SAMPLE_RATE):
    """Jump-peak and spectral-flux diagnostics at splice boundaries.

    flux_ratio compares the spectral change across each boundary with the
    median spectral change across ordinary adjacent windows elsewhere in
    the same clip, so it is relative to the clip's own content. Values
    near 1 mean the join looks like the surrounding audio; large values
    flag a discontinuity worth listening to. Diagnostic only.
    """
    rate, samples = _read_mono16(path)
    if rate != sample_rate:
        raise ValueError(f'seam metrics expect {sample_rate} Hz, got {rate}')
    n = len(samples)
    bounds = [round(float(t) * rate) for t in boundaries_seconds]
    baseline = []
    c = WINDOW
    while c + WINDOW <= n and len(baseline) < MAX_BASELINE_PAIRS:
        if all(abs(c - b) > 2 * WINDOW for b in bounds):
            baseline.append(_flux(samples[c - WINDOW:c], samples[c:c + WINDOW]))
        c += BASELINE_STEP
    med = sorted(baseline)[len(baseline) // 2] if baseline else None
    out = []
    for t, b in zip(boundaries_seconds, bounds):
        jump = abs(samples[b] - samples[b - 1]) / 32768 if 0 < b < n else None
        flux = ratio = None
        if b - WINDOW >= 0 and b + WINDOW <= n:
            flux = _flux(samples[b - WINDOW:b], samples[b:b + WINDOW])
            ratio = (flux / (med + 1e-9)) if med is not None else None
        out.append({'t_seconds': round(float(t), 3), 'jump_peak': (round(jump, 5) if jump is not None else None),
                    'spectral_flux': (round(flux, 5) if flux is not None else None),
                    'flux_ratio': (round(ratio, 3) if ratio is not None else None)})
    return {'boundaries': out, 'baseline_flux_median': (round(med, 5) if med is not None else None),
            'window_samples': WINDOW, 'baseline_pairs': len(baseline),
            'note': 'Diagnostic only: flags join discontinuities for listening review; never changes pass/fail.'}
