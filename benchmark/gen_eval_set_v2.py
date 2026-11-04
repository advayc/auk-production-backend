"""Deterministic enhancer eval-set generator (v2 - 10 additional held-out speakers).

Speakers: p226 p228 p232 p237 p240 p248 p254 p261 p267 p272 (all mic1) -
disjoint from eval-v1's ten and from every corpus-v2 source speaker, so v2
scores measure generalization to speakers no earlier artifact touched.
Sources: VCTK 0.92 wav48_silence_trimmed flacs fetched from
https://datashare.is.ed.ac.uk/bitstream/handle/10283/3443/VCTK-Corpus-0.92.zip
via HTTP Range requests (pick rule: first utterance estimated 3.5-6.5 s
closest to 4.5 s, mic1 preferred). Transcripts recorded in eval-v2/manifest.json.

Conditions: identical DSP to gen_eval_set.py v1 (same babble/RIR/SNR recipe),
only the seed changes. v2 derives per-clip seeds from sha256(base|condition):
v1 used Python's salted hash(), which is NOT reproducible across processes;
v1 outputs stay pinned as scored on 2026-11-03 and are not regenerated.

Conditions (seeded, reproducible):
  A noisy-cafe-10db   synthetic babble + clatter at 10 dB SNR
  B reverb-noise-hard synthetic RIR (T60 ~0.6s) + babble/hum noise at 7.5 dB SNR
Output: 48 kHz mono 16-bit wavs + manifest.json. No external noise files.
"""
import json, hashlib, sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal as sig

SR = 48000
SEED = 20261104

def read_mono48(path):
    x, sr = sf.read(path, dtype='float64')
    if x.ndim > 1: x = x.mean(axis=1)
    if sr != SR:
        n = int(round(len(x) * SR / sr))
        x = sig.resample(x, n)
    return x

def babble(n, rng):
    out = np.zeros(n)
    for _ in range(6):
        fc = rng.uniform(300, 2800)
        bw = rng.uniform(150, 500)
        b, a = sig.butter(2, [max(fc-bw/2, 80)/ (SR/2), min(fc+bw/2, SR/2-1)/(SR/2)], btype='band')
        v = sig.lfilter(b, a, rng.standard_normal(n))
        rate = rng.uniform(3, 5)
        ph = rng.uniform(0, 2*np.pi)
        mod = 0.5 + 0.5*np.sin(2*np.pi*rate*np.arange(n)/SR + ph)
        out += v * (mod ** 1.5)
    cl = (rng.random(n) < 0.002).astype(float) * rng.uniform(0.3, 1.0, n)
    b, a = sig.butter(2, 2500/(SR/2), btype='high')
    out += sig.lfilter(b, a, cl) * 0.5
    b, a = sig.butter(2, 60/(SR/2), btype='low')
    humsrc = np.sin(2*np.pi*60*np.arange(n)/SR) + 0.4*np.sin(2*np.pi*120*np.arange(n)/SR)
    out += 0.02 * humsrc + sig.lfilter(b, a, rng.standard_normal(n)) * 0.4
    return out

def rir(t60, rng, sr=SR):
    dur = max(t60 * 1.2, 0.1)
    n = int(dur * sr)
    t = np.arange(n) / sr
    env = np.exp(-6.91 * t / t60)
    h = rng.standard_normal(n) * env
    h[0] = 1.0
    b, a = sig.butter(2, [150/(sr/2), 8000/(sr/2)], btype='band')
    h = sig.lfilter(b, a, h)
    h = h / np.abs(h).max()
    return h

def rms(x): return float(np.sqrt(np.mean(x**2)) + 1e-12)

def mix_at_snr(clean, noise, snr_db):
    k = rms(clean) / rms(noise) / (10 ** (snr_db / 20))
    return clean + noise * k

def to16(x):
    peak = np.abs(x).max()
    if peak > 0.98: x = x * 0.98 / peak
    return (x * 32767).astype(np.int16)

def clip_seed(base, cond):
    return SEED + int.from_bytes(hashlib.sha256(f'{base}|{cond}'.encode()).digest()[:4], 'little')

def main(src_dir, out_dir):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'seed': SEED, 'seed_derivation': 'SEED + sha256(base|condition)[:4] little-endian',
                'sr': SR, 'conditions': {
        'noisy-cafe-10db': {'snr_db': 10.0, 'reverb_t60': None},
        'reverb-noise-hard': {'snr_db': 7.5, 'reverb_t60': 0.6}}, 'files': []}
    transcripts = {}
    picks_path = src_dir.parent / 'vctk2_picks.json'
    if picks_path.is_file():
        for p in json.loads(picks_path.read_text()):
            transcripts[p['stem']] = p.get('transcript')
    for wav in sorted(src_dir.glob('*.wav')):
        clean = read_mono48(wav)
        clean = clean / (np.abs(clean).max() + 1e-12) * 0.9
        base = wav.stem.replace('vctk-', '')
        sha_clean = hashlib.sha256(Path(wav).read_bytes()).hexdigest()
        stem_key = base.replace('-mic', '_mic').replace('-', '_')  # p226_006-mic1 -> lookup-safe
        for cond, cfg in manifest['conditions'].items():
            rng = np.random.default_rng(clip_seed(base, cond))
            x = clean
            if cfg['reverb_t60']:
                x = sig.fftconvolve(x, rir(cfg['reverb_t60'], rng))[:len(clean)]
                x = x / (np.abs(x).max() + 1e-12) * 0.9
            n = babble(len(x), rng)
            y = mix_at_snr(x, n, cfg['snr_db'])
            achieved = 20*np.log10(rms(x)/rms(y-x))
            name = f'enh-eval-{base}-{cond}.wav'
            sf.write(out_dir/name, to16(y), SR, subtype='PCM_16')
            manifest['files'].append({'file': name, 'source': wav.name, 'source_sha256': sha_clean,
                                      'condition': cond, 'snr_db_target': cfg['snr_db'],
                                      'snr_db_achieved': round(achieved, 2), 'duration_s': round(len(y)/SR, 3),
                                      'transcript': transcripts.get(stem_key)})
            print('WROTE', name, 'snr', round(achieved,2), 'dur', round(len(y)/SR,2))
    (out_dir/'manifest.json').write_text(json.dumps(manifest, indent=1))
    print('DONE', len(manifest['files']), 'files')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
