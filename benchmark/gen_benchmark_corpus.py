"""AuK enhancer benchmark corpus generator (v2).

Extends eval-set v1 with the spec's full category matrix. Deterministic (seeded),
no external noise assets - synthetic builders only, recipes recorded in manifest.

Categories (spec: phonemsg-01M6HZ6YNCBMA380JEC6GDB22M):
  clean-studio, wind, traffic, crowd/cafe, reverb, music-under-dialogue,
  multi-speaker, whisper-like + quiet speech, clipped, low-volume, silence,
  short + long, mono/stereo, 44.1/48k, WAV/AAC/MP3, video-sync container.

Sources: 10 held-out VCTK clips in /downloads (clean studio, 48k).
Output: <out>/benchmark/<clip files> + manifest.json (recipe, seed, measured SNR,
duration, channels, sample rate, expected gate notes per clip).
"""
import json, hashlib, subprocess, sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal as sig

SR = 48000
SEED = 20261103

def read_mono(path, target_sr=SR):
    x, sr = sf.read(path, dtype='float64')
    if x.ndim > 1: x = x.mean(axis=1)
    if sr != target_sr:
        x = sig.resample(x, int(round(len(x) * target_sr / sr)))
    return x

def norm_peak(x, peak=0.9):
    return x / (np.abs(x).max() + 1e-12) * peak

def rms(x): return float(np.sqrt(np.mean(x**2)) + 1e-12)

def mix_at_snr(clean, noise, snr_db):
    k = rms(clean) / (rms(noise) + 1e-12) / (10 ** (snr_db / 20))
    return clean + noise * k, 20*np.log10(rms(clean)/(rms(noise*k)+1e-12))

def to16(x):
    peak = np.abs(x).max()
    if peak > 0.98: x = x * 0.98 / peak
    return (x * 32767).astype(np.int16)

def seeded_rng(*parts):
    h = int(hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:12], 16)
    return np.random.default_rng((SEED + h) % (2**32))

# ---------- noise builders ----------
def babble(n, rng, voices=6):
    out = np.zeros(n)
    for _ in range(voices):
        fc = rng.uniform(300, 2800); bw = rng.uniform(150, 500)
        b, a = sig.butter(2, [max(fc-bw/2, 80)/(SR/2), min(fc+bw/2, SR/2-1)/(SR/2)], btype='band')
        v = sig.lfilter(b, a, rng.standard_normal(n))
        mod = 0.5 + 0.5*np.sin(2*np.pi*rng.uniform(3, 5)*np.arange(n)/SR + rng.uniform(0, 2*np.pi))
        out += v * (mod ** 1.5)
    cl = (rng.random(n) < 0.002).astype(float) * rng.uniform(0.3, 1.0, n)
    b, a = sig.butter(2, 2500/(SR/2), btype='high')
    out += sig.lfilter(b, a, cl) * 0.5
    b, a = sig.butter(2, 60/(SR/2), btype='low')
    hum = np.sin(2*np.pi*60*np.arange(n)/SR) + 0.4*np.sin(2*np.pi*120*np.arange(n)/SR)
    out += 0.02 * hum + sig.lfilter(b, a, rng.standard_normal(n)) * 0.4
    return out

def wind(n, rng):
    brown = np.cumsum(rng.standard_normal(n)); brown /= np.abs(brown).max() + 1e-12
    gust = 0.4 + 0.6*(0.5 + 0.5*np.sin(2*np.pi*rng.uniform(0.05, 0.15)*np.arange(n)/SR + rng.uniform(0, 2*np.pi)))**2
    gust *= 0.6 + 0.4*(0.5 + 0.5*np.sin(2*np.pi*rng.uniform(0.4, 0.9)*np.arange(n)/SR + rng.uniform(0, 2*np.pi)))
    b, a = sig.butter(2, [80/(SR/2), 1200/(SR/2)], btype='band')
    whistle = sig.lfilter(b, a, rng.standard_normal(n))
    fmod = 0.5 + 0.5*np.sin(2*np.pi*rng.uniform(0.2, 0.5)*np.arange(n)/SR)
    return brown * gust * 0.8 + whistle * fmod * 0.25

def traffic(n, rng):
    brown = np.cumsum(rng.standard_normal(n)); brown /= np.abs(brown).max() + 1e-12
    b, a = sig.butter(2, 300/(SR/2), btype='low')
    rumble = sig.lfilter(b, a, brown) * 1.5
    out = rumble.copy()
    t = np.arange(n) / SR
    for start in np.sort(rng.uniform(0, max(n/SR - 4, 1), size=max(int(n/SR/12), 1))):
        i0 = int(start * SR); i1 = min(i0 + int(4*SR), n)
        m = i1 - i0
        sweep_fc = np.linspace(400, 1800, m)
        ph = np.cumsum(2*np.pi*sweep_fc/SR)
        env = np.sin(np.pi * np.arange(m)/m) ** 2
        out[i0:i1] += np.sin(ph) * env * 0.3
    for _ in range(rng.integers(1, 4)):
        i0 = int(rng.uniform(0, 0.9) * n); honk_len = int(0.35 * SR)
        f0 = rng.uniform(300, 420)
        honk = (np.sin(2*np.pi*f0*t[:honk_len]) + 0.5*np.sin(2*np.pi*2*f0*t[:honk_len]))
        honk *= np.hanning(honk_len)
        if i0 + honk_len <= n: out[i0:i0+honk_len] += honk * 0.12
    return out

def music_bed(n, rng, bpm=100, root=220.0):
    t = np.arange(n) / SR
    beat = 60.0 / bpm
    chords = [[1, 1.189, 1.498], [0.841, 1.0, 1.26], [0.749, 0.891, 1.122], [0.667, 0.841, 1.0]]
    chord_len = int(4 * beat * SR)
    out = np.zeros(n)
    pos = 0; ci = 0
    while pos < n:
        m = min(chord_len, n - pos)
        tt = np.arange(m) / SR
        pad = np.zeros(m)
        for ratio in chords[ci % len(chords)]:
            f = root * ratio
            pad += 0.5*np.sin(2*np.pi*f*tt) + 0.2*np.sin(2*np.pi*2*f*tt) + 0.1*np.sin(2*np.pi*3*f*tt)
        pad *= 0.5 + 0.5*np.sin(2*np.pi*0.5*tt) ** 2
        bassf = root * chords[ci % len(chords)][0] / 2
        bass_pat = (np.sin(2*np.pi*bassf*tt) * (np.sin(2*np.pi*(1/beat)*tt) > 0.3)).astype(float)
        out[pos:pos+m] += pad * 0.35 + bass_pat * 0.25
        pos += m; ci += 1
    kick_per = int(beat * SR)
    for k0 in range(0, n - int(0.12*SR), kick_per):
        kl = int(0.12*SR); kt = np.arange(kl)/SR
        kick = np.sin(2*np.pi*np.linspace(120, 45, kl)*kt) * np.exp(-kt*30)
        out[k0:k0+kl] += kick * 0.5
    return out

def rir(t60, rng, sr=SR):
    n = int(max(t60 * 1.2, 0.1) * sr)
    t = np.arange(n) / sr
    h = rng.standard_normal(n) * np.exp(-6.91 * t / t60)
    h[0] = 1.0
    b, a = sig.butter(2, [150/(sr/2), 8000/(sr/2)], btype='band')
    h = sig.lfilter(b, a, h)
    return h / (np.abs(h).max() + 1e-12)

def whisperize(x):
    b, a = sig.butter(2, [400/(SR/2), 5000/(SR/2)], btype='band')
    shaped = sig.lfilter(b, a, x)
    b2, a2 = sig.butter(2, 2000/(SR/2), btype='high')
    breath = sig.lfilter(b2, a2, np.random.default_rng(7).standard_normal(len(x)))
    e = np.sqrt(sig.convolve(x**2, np.ones(int(0.02*SR))/int(0.02*SR), mode='same'))
    return (shaped * 0.5 + breath * (e / (e.max()+1e-12)) * 0.3) * 0.35

# ---------- corpus ----------
def build(src_dir, out_dir):
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    srcs = sorted(src_dir.glob('vctk-*.wav'))
    assert len(srcs) >= 10, f'need 10 vctk sources, got {len(srcs)}'
    cleans = {}
    for w in srcs:
        cleans[w.stem.replace('vctk-', '')] = norm_peak(read_mono(w))
    keys = sorted(cleans)
    man = {'seed': SEED, 'sr_default': SR, 'version': 'benchmark-v2', 'clips': []}

    def emit(name, y, sr=SR, channels=1, category='', recipe='', gate_notes='', subtype='PCM_16', container='wav'):
        p = out_dir / name
        if container == 'wav':
            if channels == 2:
                sf.write(p, to16(y[0]).reshape(-1,1).repeat(2,1) if not isinstance(y, tuple) else np.stack([to16(y[0]), to16(y[1])], 1), sr, subtype=subtype)
            else:
                sf.write(p, to16(y), sr, subtype=subtype)
        man['clips'].append({'file': name, 'category': category, 'recipe': recipe,
            'sr': sr, 'channels': channels, 'duration_s': round(p.stat().st_size and sf.info(str(p)).duration or 0, 3),
            'gate_notes': gate_notes})
        print('WROTE', name, category)

    def noisy_pair(base, builder, snr_db, cat, tag, extra_gate=''):
        for i, k in enumerate(keys[:2] if False else [keys[(hash(tag)+i) % len(keys)] for i in range(2)]):
            rng = seeded_rng(tag, k)
            x = cleans[k]
            nse = builder(len(x), rng)
            y, snr_a = mix_at_snr(x, nse, snr_db)
            emit(f'bench-{tag}-0{i+1}.wav', y, category=cat,
                 recipe=f'{tag}: {cat} noise at {snr_db}dB SNR (measured {snr_a:.2f}) on {k}',
                 gate_notes=f'words must survive; measured_snr={snr_a:.2f}. {extra_gate}')

    # 1. clean studio (bypass gate)
    for i, k in enumerate(keys[:2]):
        emit(f'bench-clean-studio-0{i+1}.wav', cleans[k], category='clean-studio',
             recipe=f'untouched clean source {k}', gate_notes='bypass or near-identity expected; no timbre change')
    # 2. wind
    noisy_pair(None, wind, 10.0, 'wind', 'wind-10db')
    # 3. traffic
    noisy_pair(None, traffic, 8.0, 'traffic', 'traffic-8db')
    # 4. crowd/cafe
    noisy_pair(None, babble, 10.0, 'crowd', 'crowd-cafe-10db')
    # 5. reverb (+ reverb+noise hard)
    for i, k in enumerate([keys[3], keys[4]]):
        rng = seeded_rng('reverb', k)
        xr = sig.fftconvolve(cleans[k], rir(0.8, rng))[:len(cleans[k])]
        emit(f'bench-reverb-t60-08-0{i+1}.wav', norm_peak(xr), category='reverb',
             recipe=f'T60=0.8s synthetic RIR on {k}', gate_notes='dereverb without metallic tail or word loss')
    for i, k in enumerate([keys[5], keys[6]]):
        rng = seeded_rng('reverbnoise', k)
        xr = norm_peak(sig.fftconvolve(cleans[k], rir(0.6, rng))[:len(cleans[k])])
        y, snr_a = mix_at_snr(xr, babble(len(xr), rng), 7.5)
        emit(f'bench-reverb-noise-hard-0{i+1}.wav', y, category='reverb+noise',
             recipe=f'T60=0.6s + babble 7.5dB (measured {snr_a:.2f}) on {k}', gate_notes='hardest case; no chopped consonants')
    # 6. music under dialogue
    noisy_pair(None, music_bed, 12.0, 'music-under-dialogue', 'music-12db',
               extra_gate='dialogue must stay intact; music bed may remain at reduced level per preserve_original_mix mode')
    # 7. multi-speaker overlap
    for i in range(2):
        k1, k2 = keys[(7+i) % 10], keys[(2+i) % 10]
        a, b_ = cleans[k1], cleans[k2]
        n = max(len(a), len(b_)); a2 = np.zeros(n); b2 = np.zeros(n)
        a2[:len(a)] = a; off = int(0.35 * SR); b2[off:off+len(b_)] = b_[:max(0, n-off)]
        y = a2 + b2 * 0.7
        emit(f'bench-multi-speaker-0{i+1}.wav', y, category='multi-speaker',
             recipe=f'{k1} primary + {k2} overlapping at -3dB, offset 0.35s',
             gate_notes='both speakers words preserved; no speaker removal unless isolation requested')
    # 8. whisper-like + quiet speech
    k = keys[8]
    emit('bench-whisper-like-01.wav', whisperize(cleans[k]), category='whisper-like',
         recipe=f'spectral-shaped breathy/quiet render of {k} (no true whisper source available)',
         gate_notes='speech must not be erased as noise; acceptable to keep low level')
    emit('bench-quiet-speech-01.wav', cleans[keys[9]] * 0.16, category='quiet-speech',
         recipe=f'{keys[9]} at -16dB', gate_notes='gain up without noise pumping')
    # 9. clipped
    for i, k in enumerate([keys[0], keys[5]]):
        x = cleans[k] * 2.0
        y = np.clip(x, -0.7, 0.7)
        emit(f'bench-clipped-0{i+1}.wav', y, category='clipped',
             recipe=f'{k} gained 2x hard-clipped at 0.7', gate_notes='declip reasonable; no added harshness; words intact')
    # 10. low-volume
    emit('bench-low-volume-01.wav', cleans[keys[1]] * 0.1, category='low-volume',
         recipe=f'{keys[1]} at -20dB', gate_notes='normalize to loudness target without pumping')
    # 11. silence
    k = keys[2]
    pre = np.zeros(int(2.0*SR)); post = np.zeros(int(3.0*SR))
    rng = seeded_rng('silence', k)
    floor_pre = rng.standard_normal(int(2.0*SR)) * 0.0004
    floor_post = rng.standard_normal(int(3.0*SR)) * 0.0004
    emit('bench-silence-lead-trail-01.wav', np.concatenate([pre+floor_pre, cleans[k], post+floor_post]),
         category='silence-lead-trail', recipe=f'2s silence + {k} + 3s silence, -68dBFS floor',
         gate_notes='silence stays silent (no hallucinated speech, no hiss swell); speech timing preserved')
    emit('bench-silence-only-01.wav', np.random.default_rng(11).standard_normal(int(5*SR)) * 0.0004,
         category='silence-only', recipe='5s of -68dBFS noise floor only',
         gate_notes='output must be silence; no hallucination; no DC offset')
    # 12. short
    emit('bench-short-2s-01.wav', cleans[keys[3]][:int(2.0*SR)], category='short',
         recipe=f'first 2.0s of {keys[3]}', gate_notes='short-file path: no padding artifacts, no truncation')
    # 13. long 5-min looped concat with noise bed
    rng = seeded_rng('long')
    seq = []
    order = [keys[i % 10] for i in rng.permutation(np.arange(60))]
    for i, k in enumerate(order):
        seq.append(cleans[k]); seq.append(np.zeros(int(0.4*SR)))
    long_clean = np.concatenate(seq)
    target = int(300 * SR)
    long_clean = long_clean[:target] if len(long_clean) > target else np.concatenate([long_clean, np.zeros(target - len(long_clean))])
    bed = babble(len(long_clean), seeded_rng('long-bed'))
    y, snr_a = mix_at_snr(long_clean, bed, 12.0)
    emit('bench-long-5min-01.wav', y, category='long-form',
         recipe=f'60 utterances looped + babble 12dB (measured {snr_a:.2f}), 300s',
         gate_notes='chunk-consistency: no boundary clicks, no loudness drift, whole-file == chunked')
    # 14. stereo
    for i, k in enumerate([keys[4], keys[6]]):
        rng = seeded_rng('stereo', k)
        x = cleans[k]
        d = int(0.012*SR)
        left = x; right = np.concatenate([np.zeros(d), x[:-d]]) * 0.85
        nse_l = babble(len(x), rng); nse_r = babble(len(x), rng)
        L, _ = mix_at_snr(left, nse_l, 10.0); R, _ = mix_at_snr(right, nse_r, 10.0)
        emit(f'bench-stereo-0{i+1}.wav', (L, R), channels=2, category='stereo',
             recipe=f'decorrelated stereo noise (10dB) on {k}, 12ms ITD image', gate_notes='stereo stays stereo; image stable; no phase collapse')
    # 15. sample-rate variants
    x44 = read_mono(src_dir / f'vctk-{keys[7]}.wav', 44100)
    rng = seeded_rng('sr44')
    y, snr_a = mix_at_snr(norm_peak(x44), sig.resample(babble(int(len(x44)*SR/44100), rng), len(x44)), 10.0)
    emit('bench-sr-44k-01.wav', y, sr=44100, category='sample-rate-44.1k',
         recipe=f'44.1kHz native + babble 10dB on {keys[7]}', gate_notes='sample rate preserved unless destination conversion requested')
    # 16. codec variants (encode noisy master to aac/mp3, then decode for analysis)
    k = keys[8]
    rng = seeded_rng('codec', k)
    y, _ = mix_at_snr(cleans[k], babble(len(cleans[k]), rng), 10.0)
    master = out_dir / 'tmp-codec-master.wav'
    sf.write(master, to16(y), SR, subtype='PCM_16')
    for codec, args in [('aac-96k', ['-c:a', 'aac', '-b:a', '96k']), ('mp3-128k', ['-c:a', 'libmp3lame', '-b:a', '128k'])]:
        out_c = out_dir / f'bench-codec-{codec}-01.{"m4a" if codec.startswith("aac") else "mp3"}'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(master)] + args + [str(out_c)], check=True)
        man['clips'].append({'file': out_c.name, 'category': f'codec-{codec}', 'recipe': f'babble 10dB on {k}, encoded {codec}',
            'sr': SR, 'channels': 1, 'duration_s': round(float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(out_c)], text=True).strip()), 3),
            'gate_notes': 'decoder delay/encoder padding must not break sync; treat as lossy source'})
        print('WROTE', out_c.name, codec)
    master.unlink()
    # 17. video-sync container
    k = keys[9]
    rng = seeded_rng('video', k)
    y, _ = mix_at_snr(cleans[k], traffic(len(cleans[k]), rng), 10.0)
    tmpa = out_dir / 'tmp-video-audio.wav'
    sf.write(tmpa, to16(y), SR, subtype='PCM_16')
    mp4 = out_dir / 'bench-video-sync-01.mp4'
    dur = len(y)/SR
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'lavfi', '-i', f'testsrc2=size=320x240:rate=25:duration={dur:.3f}',
        '-i', str(tmpa), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
        '-shortest', str(mp4)], check=True)
    man['clips'].append({'file': mp4.name, 'category': 'video-sync', 'recipe': f'traffic 10dB on {k}, H.264+AAC mp4, {dur:.3f}s',
        'sr': SR, 'channels': 1, 'duration_s': round(dur, 3),
        'gate_notes': 'audio-video sync preserved within one frame; output duration == input duration'})
    print('WROTE', mp4.name, 'video-sync')
    tmpa.unlink()
    man['total_clips'] = len(man['clips'])
    (out_dir/'manifest.json').write_text(json.dumps(man, indent=1))
    print('DONE', man['total_clips'], 'clips')

if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2])
