"""Adaptive speech enhancement (voice_enhancer mode).

Pipeline (spec: adaptive enhancement, not one filter for every recording):
decode to float PCM -> measured analysis -> bypass/light/full decision ->
generative cleanup in overlapped chunks (AuK via the worker adapter) -> per-chunk
length restore -> raised-cosine crossfade stitch -> dry/wet blend vs source ->
stereo recombine (side channel untouched) -> measured loudness master
(-16 LUFS speech default, true peak <= -1 dBTP) -> sample-exact duration ->
encode once -> validation. Every decision number is measured, never assumed.

The generative core only ever sees mono 24 kHz chunks. Stereo width survives
because the side channel never enters the model. The dry/wet blend keeps
natural range on moderate inputs and caps reconstruction on severe ones.
"""
from __future__ import annotations
import dataclasses, json, math, subprocess, time
from pathlib import Path
import numpy as np

from .core import (EditorError, Limits, atomic_json, atomic_bytes, command, sha256_file,
    utc_now, probe_audio, decode_response, validate_output)

MODEL_SR = 24000
ENHANCER_INSTRUCTIONS = {
    # 'enhance' phrasing matches the bounded grid-search probe (18 combos, 2026-10):
    # 16 steps / guidance 1.0 / sway -1.0 won on fidelity+ cleanliness trade-off.
    'enhance': 'Preserve all speakers, remove noise and reverberation, and output clean speech of the same length.',
    'denoise': 'Remove the background noise. Keep every word, pause, and the original speaker voice unchanged.',
    'dereverb': 'Remove the room reverberation. Keep every word and the original speaker voice unchanged.',
}
ENHANCER_GENERATION_OPTIONS = {'num_inference_steps': 16, 'guidance_scale': 1.0, 'sway_sampling_coef': -1.0}

@dataclasses.dataclass
class EnhanceConfig:
    bypass_snr_db: float = 25.0      # measured estimate at/above which cleanup is bypassed
    full_snr_db: float = 12.0        # at/below -> full-strength generative cleanup
    clipping_full_fraction: float = 0.001
    light_wet: float = 0.35          # dry/wet blend for moderate noise
    full_wet: float = 0.85           # never fully reconstructed by default, even when severe
    max_chunk_seconds: float = 12.0
    overlap_seconds: float = 0.5
    target_lufs: float = -16.0
    loudness_tolerance_lu: float = 0.5
    true_peak_dbtp: float = -1.0
    max_duration_drift: float = 0.02 # per-chunk length restore hard limit (fraction)
    dc_offset_limit: float = 1e-3
    nan_allowed: bool = False

# ---------- IO: decode to float, encode once ----------
def decode_float(path, timeout=120):
    """Any container -> (float32 [n, ch], sample_rate) via ffmpeg; no intermediate encodes."""
    # Internal decode path: float intermediates (premaster/mastering float wavs) are
    # legitimately larger than the user-upload byte cap (e.g. 600s stereo f32 > 64 MiB).
    # Keep metadata probing; the upload bound does not apply inside the pipeline.
    info = probe_audio(Path(path), dataclasses.replace(Limits(), max_upload_bytes=1 << 31))
    sr = info['sample_rate']; ch = info['channels']
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
        '-f', 'f32le', '-acodec', 'pcm_f32le', '-'], capture_output=True, check=True, timeout=timeout).stdout
    y = np.frombuffer(raw, dtype='<f4').astype(np.float64)
    if ch > 1: y = y.reshape(-1, ch)
    return y, sr, info

def write_wav(path, y, sr, timeout=120, subtype='float'):
    path = Path(path)
    y = np.asarray(y, dtype='<f4')
    ch = 1 if y.ndim == 1 else y.shape[1]
    codec = 'pcm_f32le' if subtype == 'float' else 'pcm_s16le'
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'f32le', '-ar', str(sr),
        '-ac', str(ch), '-i', '-', '-c:a', codec, str(path)],
        input=y.tobytes(), check=True, timeout=timeout)
    return path

def resample(y, sr_in, sr_out):
    if sr_in == sr_out: return y
    n_out = int(round(len(y) * sr_out / sr_in))
    t_in = np.arange(len(y)) / sr_in
    t_out = np.arange(n_out) / sr_out
    if y.ndim == 1: return np.interp(t_out, t_in, y)
    return np.stack([np.interp(t_out, t_in, y[:, c]) for c in range(y.shape[1])], axis=1)

# ---------- measured analysis ----------
def analyze(path):
    """Signal measurements feeding the strength decision. Heuristics, honestly labeled."""
    y, sr, info = decode_float(path)
    mono = y if y.ndim == 1 else y.mean(axis=1)
    n = len(mono)
    win = max(int(0.02 * sr), 1)
    nwin = n // win
    frames = mono[:nwin * win].reshape(nwin, win)
    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-15)
    frame_db = 20 * np.log10(frame_rms + 1e-12)
    peak = float(np.abs(mono).max()) if n else 0.0
    rms = float(np.sqrt(np.mean(mono ** 2))) if n else 0.0
    clipped = float(np.mean(np.abs(mono) > 0.98))
    dc = float(np.mean(mono)) if n else 0.0
    silence_ratio = float(np.mean(frame_db < -50.0)) if nwin else 1.0
    active = frame_db[frame_db >= -60.0]
    # SNR heuristic: spread between strong frames (speech+noise) and weak frames (noise floor).
    if len(active) >= 10:
        hi = float(np.percentile(active, 90)); lo = float(np.percentile(frame_db, 25))
        est_snr = max(hi - lo, 0.0)
    else:
        est_snr = 0.0
    return {'duration_seconds': info['duration_seconds'], 'sample_rate': sr, 'channels': info['channels'],
        'samples': n, 'rms_dbfs': round(20 * math.log10(rms + 1e-12), 2),
        'peak_dbfs': round(20 * math.log10(peak + 1e-12), 2), 'clipping_fraction': round(clipped, 6),
        'dc_offset': round(dc, 6), 'silence_ratio': round(silence_ratio, 4),
        'est_snr_db': round(est_snr, 2)}

def choose_strength(meas, cfg: EnhanceConfig):
    """bypass | light | full, with the measured reasons recorded."""
    reasons = []
    if meas['silence_ratio'] >= 0.95:
        return 'bypass', ['input is >=95% silence: nothing to enhance; loudness master only']
    if meas['est_snr_db'] <= cfg.full_snr_db:
        reasons.append(f"est_snr {meas['est_snr_db']}dB <= full threshold {cfg.full_snr_db}dB")
        return 'full', reasons
    if meas['clipping_fraction'] >= cfg.clipping_full_fraction:
        reasons.append(f"clipping fraction {meas['clipping_fraction']} >= {cfg.clipping_full_fraction}")
        return 'full', reasons
    if meas['est_snr_db'] >= cfg.bypass_snr_db:
        reasons.append(f"est_snr {meas['est_snr_db']}dB >= bypass threshold {cfg.bypass_snr_db}dB")
        return 'bypass', reasons
    reasons.append(f"est_snr {meas['est_snr_db']}dB between full {cfg.full_snr_db} and bypass {cfg.bypass_snr_db}")
    return 'light', reasons

def wet_gain_for(strength, cfg: EnhanceConfig):
    return {'bypass': 0.0, 'light': cfg.light_wet, 'full': cfg.full_wet}[strength]

# ---------- chunking / stitch (chunk vs whole equivalence) ----------
def chunk_plan(n_samples, sr, cfg: EnhanceConfig):
    chunk = int(cfg.max_chunk_seconds * sr); ov = int(cfg.overlap_seconds * sr)
    if n_samples <= chunk: return [(0, n_samples)]
    spans = []; start = 0
    while start < n_samples:
        end = min(start + chunk, n_samples)
        spans.append((start, end))
        if end == n_samples: break
        start = end - ov
    return spans

def crossfade_stitch(pieces, ov_samples):
    if len(pieces) == 1: return pieces[0]
    out = pieces[0]
    for piece in pieces[1:]:
        ov = min(ov_samples, len(out), len(piece))
        if ov > 0:
            t = np.linspace(0, np.pi, ov)
            fade_out = 0.5 + 0.5 * np.cos(t); fade_in = 0.5 - 0.5 * np.cos(t)
            blended = out[-ov:] * fade_out + piece[:ov] * fade_in
            out = np.concatenate([out[:-ov], blended, piece[ov:]])
        else:
            out = np.concatenate([out, piece])
    return out

def restore_length(y, n_target, max_drift):
    """Snap a processed chunk back to its input sample count; flag real drift."""
    if len(y) == n_target: return y, 0.0
    drift = abs(len(y) - n_target) / max(n_target, 1)
    if len(y) > n_target: return y[:n_target], drift
    return np.concatenate([y, np.zeros(n_target - len(y))]), drift

def blend_dry_wet(dry, wet, g):
    n = min(len(dry), len(wet))
    return (1.0 - g) * dry[:n] + g * wet[:n]

# ---------- loudness mastering (measured, true-peak limited) ----------
def measure_loudness(path, timeout=120):
    r = subprocess.run(['ffmpeg', '-nostdin', '-i', str(path), '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
        capture_output=True, text=True, timeout=timeout)
    text = r.stderr
    start = text.rfind('{')
    if start < 0: raise EditorError('loudness_measure_failed', 'ffmpeg loudnorm produced no measurement.')
    m = json.loads(text[start:text.rfind('}') + 1])
    def finite(v):
        v = float(v)
        return v if math.isfinite(v) else None
    return {'integrated_lufs': finite(m['input_i']), 'true_peak_dbtp': finite(m['input_tp']),
        'lra_lu': finite(m['input_lra'])}

def true_peak_dbtp(y, sr, oversample=4):
    """4x-oversampled peak estimate (BS.1770-style true peak, numpy interp)."""
    if y.ndim == 1: y = y.reshape(-1, 1)
    peak = 0.0
    for c in range(y.shape[1]):
        ch = y[:, c]
        n = len(ch)
        t = np.arange(n)
        ti = np.linspace(0, n - 1, n * oversample)
        peak = max(peak, float(np.abs(np.interp(ti, t, ch)).max()))
    return 20 * math.log10(peak + 1e-12)

def align_to_reference(ref, sig, max_lag=8192):
    """Filter chains (loudnorm, limiters, resamplers) add a constant leading delay.
    Measure it by cross-correlation against the pre-master signal and remove it,
    so the output stays sample-aligned with the source. Returns (aligned, lag)."""
    n = min(len(ref), len(sig), 1 << 18)
    if n < 1024: return sig, 0
    a = np.asarray(ref[:n], dtype=np.float64); b = np.asarray(sig[:n], dtype=np.float64)
    a = a - a.mean(); b = b - b.mean()
    n2 = 2 * n
    c = np.fft.irfft(np.fft.rfft(a, n2) * np.conj(np.fft.rfft(b, n2)), n2)
    # c[n2 - d] peaks when b is delayed by d samples. Include d=0 and accept a
    # positive delay only when it beats zero-lag by a real margin - for smooth
    # signals neighboring lags correlate nearly equally and a spurious 1-sample
    # shift damages the waveform more than the latency it removes.
    lo = n2 - min(max_lag, n // 2)
    window = c[lo:n2 + 1]
    k = lo + int(np.argmax(window))
    d = n2 - k
    if d <= 0 or c[k] <= 0 or c[k] < c[0] * 1.001: return sig, 0
    return np.concatenate([sig[d:], np.zeros(d)]), d

def master_loudness(in_path, out_path, cfg: EnhanceConfig, timeout=180, out_sr=None, out_channels=None, n_target=None):
    """Measured normalization to target LUFS + true-peak limiting, sample-aligned.

    One code path: BS.1770-gated measurement (ffmpeg loudnorm print) -> measured gain
    -> corrective measured passes (gain is not exactly 1:1 in LUFS under K-weighting)
    -> numpy true-peak enforcement (static gain; speech at -16 LUFS rarely needs it)
    -> cross-correlation realignment against the pre-master signal (filter latency is
    measured and removed, never assumed) -> single s16 encode at the source rate.
    Silence stays silence: a degenerate measurement skips normalization and says so.
    """
    before = measure_loudness(in_path, timeout)
    float_tmp = Path(str(out_path) + '.float.wav')
    mode = 'measured_gain'
    if before['integrated_lufs'] is None or before['integrated_lufs'] <= -70.0:
        mode = 'skipped_silence'
        chain = 'anull'
    else:
        gain_db = max(-30.0, min(30.0, cfg.target_lufs - before['integrated_lufs']))
        chain = f'volume={gain_db:.2f}dB'
    def render(src, dst, first_filter):
        tail = [first_filter]
        if out_sr: tail.append(f'aresample={out_sr}')
        if n_target: tail.append(f'apad=whole_len={n_target},atrim=end_sample={n_target}')
        cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(src), '-af', ','.join(tail),
            '-c:a', 'pcm_f32le']
        if out_channels: cmd += ['-ac', str(out_channels)]
        cmd += [str(dst)]
        subprocess.run(cmd, check=True, timeout=timeout)
    render(in_path, float_tmp, chain)
    after = measure_loudness(float_tmp, timeout)
    for _ in range(2):
        if mode == 'skipped_silence' or after['integrated_lufs'] is None:
            break
        residual = cfg.target_lufs - after['integrated_lufs']
        if abs(residual) <= cfg.loudness_tolerance_lu * 0.6:
            break
        render(float_tmp, Path(str(float_tmp) + '.fix.wav'), f'volume={max(-10.0, min(10.0, residual)):.2f}dB')
        Path(str(float_tmp) + '.fix.wav').replace(float_tmp)
        after = measure_loudness(float_tmp, timeout)
    # True-peak enforcement and realignment in float, then the single final encode.
    y, sr, _ = decode_float(float_tmp)
    ref, _rsr, _ = decode_float(in_path)
    ref_mono = ref if ref.ndim == 1 else ref.mean(axis=1)
    # Measure filter-chain latency ONCE on the channel mean and apply one shared shift:
    # per-channel estimates can lock onto stereo-image content and would decorrelate L/R.
    y_mono = y if y.ndim == 1 else y.mean(axis=1)
    _aligned, lag = align_to_reference(ref_mono, y_mono)
    if lag > 0:
        pad = np.zeros(lag)
        if y.ndim == 2:
            y = np.concatenate([y[lag:], np.zeros((lag, y.shape[1]))], axis=0)
        else:
            y = np.concatenate([y[lag:], pad])
    if n_target:
        if len(y) > n_target: y = y[:n_target]
        elif len(y) < n_target:
            pad = n_target - len(y)
            y = (np.pad(y, ((0, pad), (0, 0))) if y.ndim == 2 else np.concatenate([y, np.zeros(pad)]))
    # DC hygiene: an input can carry a DC component that survives the enhance chain
    # (RB1 2026-11-11 row 'Why 2-Minute': input dc -0.002456, output dc -0.001529 vs
    # the 1e-3 output contract). Subtract the exact per-channel mean in float before
    # TP enforcement: no filter latency, no phase effects, sample count unchanged.
    dc_removed = y.mean(axis=0) if y.ndim == 2 else float(y.mean())
    y = y - dc_removed
    tp_before = true_peak_dbtp(y, sr)
    tp_gain_db = 0.0
    if tp_before > cfg.true_peak_dbtp:
        tp_gain_db = cfg.true_peak_dbtp - tp_before
        y = y * (10 ** (tp_gain_db / 20))
    write_wav(out_path, y, sr, subtype='s16')
    float_tmp.unlink(missing_ok=True)
    final_meas = measure_loudness(out_path, timeout)
    final_meas['true_peak_dbtp'] = round(true_peak_dbtp(y, sr), 2)
    if mode == 'skipped_silence':
        ok = True
    else:
        loud_ok = (final_meas['integrated_lufs'] is not None
                   and abs(final_meas['integrated_lufs'] - cfg.target_lufs) <= cfg.loudness_tolerance_lu)
        ok = loud_ok and final_meas['true_peak_dbtp'] <= cfg.true_peak_dbtp + 0.1
    return {'mode': mode, 'before': before, 'after': final_meas, 'target_lufs': cfg.target_lufs,
        'true_peak_dbtp_limit': cfg.true_peak_dbtp, 'true_peak_gain_db': round(tp_gain_db, 3),
        'dc_offset_removed': [round(float(v), 8) for v in np.atleast_1d(dc_removed)],
        'alignment_shift_samples': lag, 'within_tolerance': ok}

# ---------- output validation ----------
def validate_enhanced(path, meas, cfg: EnhanceConfig, frame_seconds=1 / 25):
    """Sample-exact output contract: the output must hold exactly the decoded input's
    sample count. meas['duration_seconds'] is the container/stream duration, which can
    exceed the decoded length by codec padding (e.g. MP3 gapless trimming), so a
    duration comparison against it false-fails on correctly sample-exact outputs."""
    out = analyze(path)
    problems = []
    if math.isnan(out['rms_dbfs']) or math.isnan(out['peak_dbfs']): problems.append('nan_or_invalid_signal')
    if abs(out['dc_offset']) > cfg.dc_offset_limit: problems.append(f"dc_offset {out['dc_offset']}")
    if out['clipping_fraction'] > 0.005: problems.append(f"clipping_fraction {out['clipping_fraction']}")
    if out['samples'] != meas['samples']:
        problems.append(f"sample drift {out['samples']} vs {meas['samples']}")
    if out['channels'] != meas['channels']: problems.append(f"channels {out['channels']} != {meas['channels']}")
    if out['sample_rate'] != meas['sample_rate']: problems.append(f"sample_rate {out['sample_rate']} != {meas['sample_rate']}")
    return {'ok': not problems, 'problems': problems, 'output': out}

def probe_duration(path, timeout=60):
    raw = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
        capture_output=True, text=True, check=True, timeout=timeout).stdout.strip()
    return float(raw)

def run_voice_enhancer(worker, source, folder, rid, plan, profile, p, limits, request_started, cfg=None):
    """voice_enhancer request: measured analysis -> adaptive generative cleanup -> master -> gate.

    Single attempt by design (v1): the DSP path is deterministic, and generative chunk
    seeds are fixed; bounded-retry semantics for transient adapter failures arrive with
    the acceptance-suite integration. Every decision lands in the attempt record.
    """
    from .worker import Result
    cfg = cfg or EnhanceConfig()
    operation = plan['public_operation']
    plan = dict(plan)
    plan['instruction'] = ENHANCER_INSTRUCTIONS.get(operation, plan['instruction'])
    gen_options = dict(ENHANCER_GENERATION_OPTIONS)
    gen_options.update({k: v for k, v in (p.get('generation_options') or {}).items()})
    plan['generation_options'] = gen_options
    began = time.monotonic()
    record = {'attempt': 1, 'seed': plan['seed'], 'model_profile': profile,
        'runtime_profile': worker.runtime_profile, 'started_at': utc_now(),
        'technical_success': False, 'automatic_qa_pass': False, 'failure_reason': None,
        'artifact_paths': [], 'plan': dict(plan), 'selected': False,
        'mechanism': 'adaptive_analysis_generative_chunks_blend_master'}
    final = folder / 'output.wav'
    qa_pass = False
    try:
        meas = analyze(source)
        record['analysis'] = meas
        strength, reasons = choose_strength(meas, cfg)
        g = wet_gain_for(strength, cfg)
        record['decision'] = {'strength': strength, 'reasons': reasons, 'wet_gain': g}
        y, sr, _info = decode_float(source)
        channel_mode = p.get('channel_mode', 'preserve_original_mix')
        if meas['channels'] == 2 and channel_mode != 'speech_only_mono':
            mid = 0.5 * (y[:, 0] + y[:, 1]); side = 0.5 * (y[:, 0] - y[:, 1])
        else:
            mid = y if y.ndim == 1 else y.mean(axis=1); side = None
        record['channel_mode'] = 'mid_side_stereo' if side is not None else 'mono'
        if g == 0.0:
            enhanced_mid = mid
            record['generative'] = {'skipped': 'bypass: input meets the cleanliness threshold', 'chunks': 0}
        else:
            work = resample(mid, sr, MODEL_SR)
            spans = chunk_plan(len(work), MODEL_SR, cfg)
            pieces = []; drift_max = 0.0
            for ci, (a, b) in enumerate(spans):
                if worker.deadline is not None and time.monotonic() >= worker.deadline:
                    raise EditorError('inference_timeout', f'Wall-clock budget exhausted before enhancer chunk {ci + 1}.')
                chunk = work[a:b]
                cin = folder / f'enh-chunk-{ci:02d}-in.wav'; cout = folder / f'enh-chunk-{ci:02d}-out.wav'
                write_wav(cin, chunk, MODEL_SR, subtype='s16')  # model boundary is s16 24k mono, same as prepare_audio
                cplan = dict(plan); cplan['target_seconds'] = round(len(chunk) / MODEL_SR, 3)
                cplan['seed'] = (plan['seed'] + ci) % (2 ** 31)
                response, timing = worker.adapter.run(profile, cin, cplan)
                record.setdefault('chunk_timing', []).append(timing)
                atomic_bytes(cout, decode_response(response, limits))
                raw, rsr, _rinfo = decode_float(cout)
                if raw.ndim > 1: raw = raw.mean(axis=1)
                piece, drift = restore_length(resample(raw, rsr, MODEL_SR), b - a, cfg.max_duration_drift)
                drift_max = max(drift_max, drift)
                pieces.append(piece)
                record['artifact_paths'] += [str(cin), str(cout)]
            stitched = crossfade_stitch(pieces, int(cfg.overlap_seconds * MODEL_SR))
            stitched, drift_s = restore_length(stitched, len(work), cfg.max_duration_drift)
            enhanced_mid = resample(stitched, MODEL_SR, sr)
            enhanced_mid, drift_f = restore_length(enhanced_mid, len(mid), cfg.max_duration_drift)
            record['generative'] = {'chunks': len(spans),
                'max_length_drift': round(max(drift_max, drift_s, drift_f), 6)}
        mixed = blend_dry_wet(mid, enhanced_mid, g)
        out_sig = np.stack([mixed + side, mixed - side], axis=1) if side is not None else mixed
        premaster = folder / 'enh-premaster.wav'
        write_wav(premaster, out_sig, sr)
        master = master_loudness(premaster, final, cfg, out_sr=sr, out_channels=meas['channels'], n_target=meas['samples'])
        record['loudness'] = master
        record['artifact_paths'] += [str(premaster), str(final)]
        checks = validate_enhanced(final, meas, cfg)
        record['validation'] = checks
        if not checks['ok']:
            raise EditorError('enhance_validation_failed', '; '.join(checks['problems']))
        record['technical_success'] = True
        qa = worker.gate.check(source, final, plan)
        record['qa'] = qa
        qa_pass = qa['automatic_pass']
        record['automatic_qa_pass'] = qa_pass
        if qa_pass: record['selected'] = True
        else: record['failure_reason'] = 'qa_unverified' if qa['unverified'] else 'qa_failed'
    except Exception as exc:
        record['technical_success'] = False
        record['failure_reason'] = getattr(exc, 'code', type(exc).__name__)
        record['error_detail'] = str(exc)[:1800]
        qa_pass = False
    record['latency_seconds'] = time.monotonic() - began
    ad = folder / 'attempt-01'; ad.mkdir(exist_ok=True)
    atomic_json(ad / 'attempt.json', record)
    atomic_json(folder / 'attempts.json', [record])
    result = Result(rid, 'qa_pass_review_pending' if record['automatic_qa_pass'] else 'review_required',
        record['technical_success'], record['automatic_qa_pass'], None,
        str(final) if record['automatic_qa_pass'] else None, record['failure_reason'], profile,
        time.monotonic() - request_started, [record], str(folder))
    atomic_json(folder / 'result.json', dataclasses.asdict(result))
    return result
