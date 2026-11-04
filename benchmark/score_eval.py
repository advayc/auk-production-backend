#!/usr/bin/env python3
"""Score speech-enhancement outputs against the AuK eval-v1 benchmark.

One scorer for every pipeline comparison (AuK, open-source baselines, Adobe
Enhance Speech head-to-head). Outputs are audio files named
``<tag>__<eval clip name>`` in a single folder, e.g.
``adobe__enh-eval-p363_029-mic1-noisy-cafe-10db.wav``.

Per file:
  * WER - faster-whisper base.en transcription vs the matching clean-vctk
    reference transcription (identical ASR and normalization on both sides,
    beam size 5). WER is the primary metric; it tracks what a downstream
    transcript consumer experiences.
  * ESTOI (extended, pystoi) after cross-correlation alignment to the clean
    reference. Intrusive metrics penalize generative reconstruction even when
    words are right, so ESTOI is secondary context, never the headline.
  * Band stats - energy fraction above 8 kHz and 95% spectral rolloff. These
    document band-limiting (Adobe Enhance Speech caps at ~9.5 kHz).

Prints ROW lines per clip and AGG means per condition, writes a JSON result
array, and with --compare-reference diffs mean WER against the pinned
2026-11-03 L4 reference table (PASS within +-0.02 absolute).

Deps: numpy, soundfile, librosa, pystoi, faster-whisper (CUDA if present).
Run as a subprocess from notebooks: kernels may hold numpy 2.x in memory
while site-packages carries 1.26.x, which breaks pystoi/librosa in-kernel.
faster-whisper on GPU needs the nvidia cu12 pip lib dirs on LD_LIBRARY_PATH.
"""
import argparse, json, math, pathlib, re, sys

# Mean pooled WER, n=20 per model, verified L4 run 2026-11-03.
REFERENCE_WER = {
    'auk_s16g1wn1': 0.130, 'auk_s32g2wn1': 0.135, 'mossformer2': 0.203,
    'INPUT-noisy': 0.262, 'dfn3': 0.285, 'resemble_denoise': 0.287,
    'resemble_enhance': 0.697,
}
REFERENCE_TOL = 0.02
SR = 48000


def norm_words(t):
    return [w for w in re.sub(r"[^a-z0-9' ]", ' ', t.lower()).split()]


def wer(ref_text, hyp_text):
    import numpy as np
    r, h = norm_words(ref_text), norm_words(hyp_text)
    if not r:
        return None
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0] = range(len(r) + 1)
    d[0, :] = range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1,
                          d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r), len(h)] / len(r)


def load_mono(path, target_sr):
    import numpy as np, soundfile as sf, librosa
    y, sr = sf.read(str(path), dtype='float32')
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != target_sr:
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    return np.asarray(y)


def align_lag(ref, sig, max_lag=9600):
    """Lag of sig relative to ref by cross-correlation (positive = sig delayed)."""
    import numpy as np
    n = min(len(ref), len(sig), 1 << 18)
    a, b = ref[:n], sig[:n]
    c = np.fft.irfft(np.fft.rfft(b, 2 * n) * np.conj(np.fft.rfft(a, 2 * n)))
    c = np.concatenate([c[-max_lag:], c[:max_lag + 1]])
    return int(np.argmax(c)) - max_lag


def band_stats(y, sr):
    import numpy as np
    S = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    freqs = np.fft.rfftfreq(len(y), 1 / sr)
    tot = S.sum() + 1e-12
    hi = float(S[freqs > 8000].sum() / tot)
    cum = np.cumsum(S) / tot
    ro95 = int(freqs[min(len(freqs) - 1, int(np.searchsorted(cum, 0.95)))])
    return hi, ro95


def clip_base(clip_name):
    return (clip_name.replace('enh-eval-', '')
            .replace('-noisy-cafe-10db.wav', '').replace('-reverb-noise-hard.wav', '')
            .replace('.wav', '').replace('.mp3', ''))


def condition_of(clip_name):
    return 'cafe10' if 'cafe' in clip_name else ('reverbhard' if 'reverb' in clip_name else 'other')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--outputs', required=True, help='folder of <tag>__<clip> outputs (or the eval inputs with --tag INPUT-noisy)')
    ap.add_argument('--tag', required=True, help='model tag for result rows; files must start with <tag>__ unless --raw-inputs')
    ap.add_argument('--raw-inputs', action='store_true', help='score every file in --outputs directly (unprocessed eval inputs)')
    ap.add_argument('--eval-dir', default='eval-v1')
    ap.add_argument('--clean-dir', default='clean-vctk')
    ap.add_argument('--json', dest='json_path', default=None)
    ap.add_argument('--compare-reference', action='store_true')
    args = ap.parse_args()

    try:
        import numpy as np, soundfile as sf  # noqa: F401
        from faster_whisper import WhisperModel
        from pystoi import stoi
    except ImportError as e:
        print('DEPS_FAIL', e, '- pip install faster-whisper pystoi librosa soundfile', flush=True)
        return 2

    try:
        model = WhisperModel('base.en', device='cuda', compute_type='float16')
        device = 'cuda'
    except Exception as e:
        print('CUDA_UNAVAILABLE', str(e)[:160], '- scoring on CPU int8', flush=True)
        model = WhisperModel('base.en', device='cpu', compute_type='int8')
        device = 'cpu'
    print('ASR_DEVICE', device, flush=True)

    def tx(path):
        import numpy as np
        x = load_mono(path, 16000)
        segs, _ = model.transcribe(np.asarray(x, dtype='float32'), beam_size=5)
        return ' '.join(s.text for s in segs).strip()

    clean = pathlib.Path(args.clean_dir)
    refs = {p.stem.replace('vctk-', ''): {'path': p, 'text': tx(p)} for p in sorted(clean.iterdir())}
    print('REFS', sorted(refs.keys()), flush=True)

    out_dir = pathlib.Path(args.outputs)
    rows = []
    for p in sorted(out_dir.iterdir()):
        if args.raw_inputs:
            tag, clip = args.tag, p.name
        else:
            if not p.name.startswith(args.tag + '__'):
                continue
            tag, clip = args.tag, p.name.split('__', 1)[1]
        base = clip_base(clip)
        if base not in refs:
            print('NOREF', p.name, base, flush=True)
            continue
        ref = refs[base]
        y = load_mono(p, SR)
        c = load_mono(ref['path'], SR).astype('float64')
        lag = align_lag(c, y)
        if lag > 0:
            ra, ya = c[lag:], y[:len(y) - lag]
        elif lag < 0:
            ra, ya = c[:lag], y[-lag:]
        else:
            ra, ya = c, y
        n = min(len(ra), len(ya))
        estoi = float(stoi(ra[:n], np.asarray(ya[:n], dtype='float64'), SR, extended=True)) if n > SR else None
        hi8, ro95 = band_stats(y, SR)
        w = wer(ref['text'], tx(p))
        rows.append({'model': tag, 'clip': clip, 'condition': condition_of(clip),
                     'wer': w, 'estoi': estoi, 'lag_samples': lag,
                     'hi8k_energy': round(hi8, 4), 'rolloff95_hz': ro95})
        print('ROW %s | %s | %s | wer=%s estoi=%s hi8k=%.4f ro95=%d lag=%d' % (
            tag, rows[-1]['condition'], clip,
            round(w, 3) if w is not None else None,
            round(estoi, 4) if estoi is not None else None, hi8, ro95, lag), flush=True)

    if not rows:
        print('NO_OUTPUTS_MATCHED in', out_dir, 'for tag', args.tag, flush=True)
        return 1

    import collections
    agg = collections.defaultdict(list)
    for r in rows:
        for k in ('wer', 'estoi'):
            if r[k] is not None:
                agg[(r['condition'], k)].append(r[k])
    means = {}
    for (cond, k), v in sorted(agg.items()):
        means.setdefault(cond, {})[k] = sum(v) / len(v)
        print('AGG %s | %s | %s = %.4f (n=%d)' % (args.tag, cond, k, sum(v) / len(v), len(v)), flush=True)
    pooled = [r['wer'] for r in rows if r['wer'] is not None]
    pooled_mean = sum(pooled) / len(pooled) if pooled else None
    print('AGG %s | pooled | wer = %.4f (n=%d)' % (args.tag, pooled_mean, len(pooled)), flush=True)

    if args.compare_reference and pooled_mean is not None and args.tag in REFERENCE_WER:
        ref = REFERENCE_WER[args.tag]
        diff = pooled_mean - ref
        verdict = 'PASS' if abs(diff) <= REFERENCE_TOL else 'WARN'
        print('REF_DIFF %s fresh=%.4f reference_2026-11-03=%.4f diff=%+.4f tol=%.2f -> %s' % (
            args.tag, pooled_mean, ref, diff, REFERENCE_TOL, verdict), flush=True)
    elif args.compare_reference:
        ref = REFERENCE_WER.get(args.tag)
        print('REF_DIFF skipped: no pinned reference for tag', args.tag, flush=True)

    if args.json_path:
        pathlib.Path(args.json_path).write_text(json.dumps(rows, indent=1))
        print('JSON_WRITTEN', args.json_path, len(rows), 'rows', flush=True)
    print('SCORE_DONE', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
