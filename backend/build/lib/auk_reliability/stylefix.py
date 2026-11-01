"""Prosody transplant for custom style edits: keep the source speaker's voice,
take the styled generation's pitch movement only.

Why this exists: custom style instructions collapse speaker identity
(systemic W3 finding, 3/17): the vendor re-synthesizes the voice when a style
instruction is applied, whatever the prompt wording. This module treats the
vendor's styled generation as a PROSODY DONOR ONLY and resynthesizes the
ORIGINAL source with its own spectral envelope + aperiodicity (which carry
speaker identity) and the donor's smoothed, median-normalized F0 ratio
contour, clamped to a bounded semitone range. Words are the source's own
content, so transcripts are preserved by construction.

Mechanism offline-validated 2026-10-28 (speaker cosine 0.857/0.849 with exact
transcripts, human listening-approved).

Scope: style/prosody custom edits whose expected transcript equals the source
transcript. The caller (worker) applies this only in that case. Source timing
is preserved; tempo-changing instructions stay with the vendor path.

Requires pyworld + numpy in the runtime environment (installed by the runner
setup); imported lazily so the rest of the backend has no new hard dependency.
"""
from __future__ import annotations
import array, wave
from pathlib import Path
import numpy as np
from .core import EditorError

SR = 24000
FRAME_PERIOD_MS = 5.0

def _read_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), 'rb') as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != SR:
            raise EditorError('wrong_output_format', 'Prosody transplant needs mono PCM16 24kHz audio.')
        data = stream.readframes(stream.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float64) / 32768.0

def _write_mono(path: Path, y: np.ndarray) -> None:
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.999:
        y = y * (0.999 / peak)
    pcm = np.clip(np.round(y * 32767.0), -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(SR)
        stream.writeframes(pcm.tobytes())

def _f0_world(pw, y):
    f0, t = pw.harvest(y, SR, frame_period=FRAME_PERIOD_MS)
    return pw.stonemask(y, f0, t, SR), t

def _smooth(x, sigma_frames):
    # gaussian smoothing without a scipy dependency
    radius = max(1, int(3 * sigma_frames))
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma_frames) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(x, radius, mode='edge'), k, mode='valid')

def prosody_transplant(source_path, donor_path, out_path, *,
                       max_semitone_shift: float = 5.0,
                       smooth_sigma_frames: float = 6.0) -> dict:
    """Resynthesize source with donor-style pitch movement. Never alters source
    words or spectral envelope; unvoiced source frames stay unvoiced."""
    try:
        import pyworld as pw
    except ImportError as exc:
        raise EditorError('stylefix_unavailable', 'pyworld is required for the custom style prosody transplant.') from exc
    src = _read_mono(Path(source_path))
    donor = _read_mono(Path(donor_path))
    f0_s, t_s = _f0_world(pw, src)
    sp = pw.cheaptrick(src, f0_s, t_s, SR)
    ap = pw.d4c(src, f0_s, t_s, SR)
    f0_d, _ = _f0_world(pw, donor)
    if len(f0_d) < 4:
        raise EditorError('donor_f0_unavailable', 'Styled generation has no usable pitch contour.')
    frame_s = FRAME_PERIOD_MS / 1000.0
    donor_times = np.arange(len(f0_d)) * frame_s
    src_times = np.arange(len(f0_s)) * frame_s
    scale = (src_times[-1] / donor_times[-1]) if donor_times[-1] > 0 else 1.0
    f0_d_al = np.interp(src_times, donor_times * scale, f0_d)
    voiced_d = f0_d_al > 0
    voiced_s = f0_s > 0
    med_d = float(np.median(f0_d_al[voiced_d])) if voiced_d.any() else 0.0
    med_s = float(np.median(f0_s[voiced_s])) if voiced_s.any() else 0.0
    if med_d <= 0 or med_s <= 0:
        raise EditorError('unvoiced_source_or_donor', 'Prosody transplant needs voiced frames in source and donor.')
    ratio = np.ones_like(f0_s)
    ratio[voiced_d] = f0_d_al[voiced_d] / med_d
    ratio = _smooth(np.log2(ratio), smooth_sigma_frames)
    lim = max_semitone_shift / 12.0
    ratio = np.clip(ratio, -lim, lim)
    new_f0 = np.zeros_like(f0_s)
    new_f0[voiced_s] = med_s * (2.0 ** ratio[voiced_s])
    out = pw.synthesize(new_f0, sp, ap, SR, frame_period=FRAME_PERIOD_MS)
    n = min(len(out), len(src))
    out = out[:n]
    rms_s = float(np.sqrt(np.mean(src[:n] ** 2))) or 1.0
    rms_o = float(np.sqrt(np.mean(out ** 2))) or 1.0
    out = out * (rms_s / rms_o)
    _write_mono(Path(out_path), out)
    return {'source_f0_median': med_s, 'donor_f0_median': med_d,
            'semitone_clamp': max_semitone_shift, 'frames': int(len(f0_s)),
            'voiced_source_frac': float(voiced_s.mean()), 'voiced_donor_frac': float(voiced_d.mean())}
